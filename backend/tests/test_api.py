"""Pruebas automatizadas del backend Python de Map Inclusive."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main  # noqa: E402
from gemini_service import GeminiEnvironmentService  # noqa: E402
from models import AccessibilityProfile, EnvironmentCheckRequest  # noqa: E402

SAMPLE_PHOTO_B64 = base64.b64encode(b"\xff\xd8\xff\xe0" + b"MAP_INCLUSIVE_FACE_PHOTO" * 4).decode("ascii")


def _reset_state() -> None:
    main.gemini_service = GeminiEnvironmentService(api_key="", cache_ttl_seconds=600)
    main.USERS_DB.clear()
    main.VOLUNTEERS_DB.clear()
    main.EMERGENCY_ALERTS_DB.clear()
    main.GUARDIAN_TRACKING_DB.clear()
    main.LOST_MINOR_ALERTS_DB.clear()
    main.INCIDENTS_DB[:] = main._default_incidents()


def test_health_endpoint() -> None:
    client = TestClient(main.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["model"] == "gemini-4-hydrogen"
    assert body["refresh_interval_minutes"] == 10


def test_environment_check_multi_disability_and_10min_cache() -> None:
    _reset_state()
    client = TestClient(main.app)

    payload = {
        "origin": "Campus Coyoacán",
        "destination": "Clínica 19, Av. Universidad",
        "disabilities": ["silla_de_ruedas", "visual"],
        "force_refresh": False,
    }
    first = client.post("/api/v1/environment-check", json=payload)
    assert first.status_code == 200
    data1 = first.json()
    assert data1["status_mode"] == "offline_demo"
    assert data1["from_cache"] is False
    assert data1["disabilities"] == ["silla_de_ruedas", "visual"]
    assert len(data1["recomendaciones_perfil"]) == 2

    second = client.post("/api/v1/environment-check", json=payload)
    assert second.status_code == 200
    assert second.json()["from_cache"] is True

    payload["force_refresh"] = True
    third = client.post("/api/v1/environment-check", json=payload)
    assert third.status_code == 200
    assert third.json()["from_cache"] is False


def test_gemini_live_interactions_api_contract() -> None:
    """Verifica el contrato oficial de google-genai Interactions API + Google Search + Structured Output."""
    service = GeminiEnvironmentService(api_key="fake-key-for-unit-test", model="gemini-4-hydrogen")
    mock_client = MagicMock()

    fake_json = json.dumps(
        {
            "banner_resumen": "Clima despejado, sin bloqueos en Av. Universidad",
            "clima": "Soleado, 23 °C",
            "bloqueos": ["Sin bloqueos activos"],
            "transporte_afectado": ["Metro Línea 3 operando normal"],
            "incidencias_accesibilidad": ["Rampa disponible en cruce principal"],
            "zonas_riesgo": ["Sin alertas de seguridad activas"],
            "recomendaciones_perfil": [
                "Silla de ruedas: usa banqueta norte con rampa.",
                "Neurodivergente: evita Av. Universidad en hora pico.",
            ],
            "nivel_riesgo": "bajo",
        }
    )

    fake_interaction = SimpleNamespace(
        output_text=fake_json,
        steps=[
            SimpleNamespace(
                type="model_output",
                content=[
                    SimpleNamespace(
                        text=fake_json,
                        annotations=[
                            SimpleNamespace(
                                title="Metro CDMX Estado del Servicio",
                                url="https://www.metro.cdmx.gob.mx",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    mock_client.interactions.create.return_value = fake_interaction
    service._client = mock_client

    req = EnvironmentCheckRequest(
        origin="Campus Coyoacán",
        destination="Clínica 19",
        disabilities=[AccessibilityProfile.SILLA_DE_RUEDAS, AccessibilityProfile.NEURODIVERGENTE],
    )
    resp = service.check_environment(req)

    assert resp.status_mode == "gemini_live"
    assert resp.model_used == "gemini-4-hydrogen"
    assert len(resp.disabilities) == 2
    assert len(resp.fuentes) == 1

    _, kwargs = mock_client.interactions.create.call_args
    assert kwargs["model"] == "gemini-4-hydrogen"
    assert kwargs["tools"] == [{"type": "google_search"}]
    assert kwargs["response_format"]["mime_type"] == "application/json"
    assert kwargs["generation_config"] == {"thinking_level": "low"}


def test_multi_disability_routes_and_clinics_requirements() -> None:
    _reset_state()
    client = TestClient(main.app)

    single_auditivo = client.get("/api/v1/routes/suggestions", params={"profiles": "auditivo"}).json()
    single_visual = client.get("/api/v1/routes/suggestions", params={"profiles": "visual"}).json()
    combo = client.get(
        "/api/v1/routes/suggestions",
        params={"profiles": "silla_de_ruedas,visual,neurodivergente"},
    ).json()

    assert len(combo) >= 5
    assert combo[0]["disabilities"] == ["silla_de_ruedas", "visual", "neurodivergente"]
    assert combo[-1]["estimated_minutes"] > single_auditivo[-1]["estimated_minutes"]
    assert len(combo[0]["steps"]) >= 4

    # Instrucciones paso a paso diferentes por discapacidad y SIN voz para perfil auditivo
    assert single_auditivo[0]["voice_guidance_recommended"] is False
    assert len(single_auditivo[0]["navigation_steps"]) == 4
    assert all(step["spoken_text"] == "" for step in single_auditivo[0]["navigation_steps"])
    assert "semáforo sonoro" not in single_auditivo[0]["navigation_steps"][1]["detail"].lower()

    assert single_visual[0]["voice_guidance_recommended"] is True
    assert all(step["spoken_text"] != "" for step in single_visual[0]["navigation_steps"])
    assert single_visual[0]["navigation_steps"][0]["headline"] != combo[0]["navigation_steps"][0]["headline"]

    # Combinado con auditivo también desactiva voz por seguridad
    combo_deaf = client.get("/api/v1/routes/estimate", params={"profiles": "visual,auditivo"}).json()
    assert combo_deaf["voice_guidance_recommended"] is False
    assert all(step["spoken_text"] == "" for step in combo_deaf["navigation_steps"])

    clinics = client.get("/api/v1/clinics", params={"profiles": "silla_de_ruedas,visual"})
    assert clinics.status_code == 200
    for clinic in clinics.json():
        assert clinic["schedule"]
        assert clinic["estimated_minutes"] > 0
        assert len(clinic["requirements_to_bring"]) >= 3


def test_optional_user_photo_mandatory_volunteer_face_photo() -> None:
    _reset_state()
    client = TestClient(main.app)

    # Lista de voluntarios comienza vacía
    assert client.get("/api/v1/volunteers").json() == []

    # Usuario regular puede registrarse SIN foto (opcional) y con múltiples discapacidades
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "username": "sebastian_soa",
            "email": "sebastian@apexsoa.mx",
            "password": "Password123",
            "disabilities": ["silla_de_ruedas", "auditivo"],
        },
    )
    assert reg.status_code == 201
    user = reg.json()
    assert user["face_photo_base64"] is None
    assert user["disabilities"] == ["silla_de_ruedas", "auditivo"]

    # Postularse como voluntario SIN foto de rostro debe fallar (422 / 400)
    bad_apply = client.post(
        "/api/v1/volunteers/apply",
        json={
            "user_id": user["id"],
            "face_photo_base64": "",
            "zone": "Campus Coyoacán",
        },
    )
    assert bad_apply.status_code in (400, 422)

    # Postularse como voluntario CON foto de rostro obligatoria debe pasar
    ok_apply = client.post(
        "/api/v1/volunteers/apply",
        json={
            "user_id": user["id"],
            "face_photo_base64": SAMPLE_PHOTO_B64,
            "face_photo_filename": "rostro_sebastian.jpg",
            "zone": "Campus Coyoacán",
            "availability": "Lun-Vie 10:00 - 16:00",
        },
    )
    assert ok_apply.status_code == 201
    member = ok_apply.json()
    assert member["face_photo_base64"] == SAMPLE_PHOTO_B64

    vols = client.get("/api/v1/volunteers").json()
    assert len(vols) == 1
    assert vols[0]["face_photo_base64"] == SAMPLE_PHOTO_B64


def test_minor_realtime_guardian_tracking_lost_alarm_and_incident_history() -> None:
    _reset_state()
    client = TestClient(main.app)

    # Menor sin familiar registrado debe ser rechazado
    minor_fail = client.post(
        "/api/v1/auth/register",
        json={
            "username": "menor_sin_tutor",
            "email": "menor1@apexsoa.mx",
            "password": "Password123",
            "disabilities": ["neurodivergente"],
            "is_minor": True,
        },
    )
    assert minor_fail.status_code == 400

    # Menor con familiar registrado + foto opcional funciona
    minor_ok = client.post(
        "/api/v1/auth/register",
        json={
            "username": "mateo_menor",
            "email": "mateo@apexsoa.mx",
            "password": "Password123",
            "disabilities": ["visual", "neurodivergente"],
            "face_photo_base64": SAMPLE_PHOTO_B64,
            "face_photo_filename": "mateo.jpg",
            "is_minor": True,
            "guardian": {
                "name": "Laura Gómez",
                "relation": "Madre",
                "phone": "55 1234 5678",
                "email": "laura@correo.mx",
            },
        },
    )
    assert minor_ok.status_code == 201
    minor_user = minor_ok.json()
    assert minor_user["is_minor"] is True
    assert minor_user["guardian"]["name"] == "Laura Gómez"

    # Compartir ubicación en tiempo real con familiar
    loc = client.post(
        "/api/v1/guardian/location",
        json={
            "user_id": minor_user["id"],
            "username": minor_user["username"],
            "guardian_name": "Laura Gómez",
            "guardian_contact": "55 1234 5678",
            "location_text": "Av. Universidad 300, Coyoacán",
            "destination": "Clínica 19 (UMF IMSS)",
        },
    )
    assert loc.status_code == 201
    assert "Laura Gómez" in loc.json()["message"]
    assert len(client.get("/api/v1/guardian/locations").json()) == 1

    # Alerta sonora de extravío
    lost = client.post(
        "/api/v1/guardian/lost-alert",
        json={
            "user_id": minor_user["id"],
            "username": minor_user["username"],
            "guardian_name": "Laura Gómez",
            "guardian_phone": "55 1234 5678",
            "location_text": "Jardín Centenario, Coyoacán",
            "disabilities": ["visual", "neurodivergente"],
        },
    )
    assert lost.status_code == 201
    assert lost.json()["sound_alarm_triggered"] is True
    assert "Laura Gómez" in lost.json()["helper_message"]

    # Historial de incidencias (inicial + nuevo reporte)
    initial_history = client.get("/api/v1/incidents").json()
    assert len(initial_history) >= 2

    created_inc = client.post(
        "/api/v1/incidents",
        json={
            "title": "Semáforo sonoro sin funcionar",
            "description": "No emite sonido al cruzar Av. Universidad",
            "location": "Av. Universidad y Miguel Ángel de Quevedo",
            "disabilities": ["visual", "silla_de_ruedas"],
            "reported_by": "mateo_menor",
        },
    )
    assert created_inc.status_code == 201
    updated_history = client.get("/api/v1/incidents").json()
    assert len(updated_history) == len(initial_history) + 1
    assert updated_history[0]["title"] == "Semáforo sonoro sin funcionar"
    assert updated_history[0]["disabilities"] == ["visual", "silla_de_ruedas"]
