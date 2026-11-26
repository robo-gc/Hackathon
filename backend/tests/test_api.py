"""Pruebas automatizadas del backend Python de Map Inclusive."""

from __future__ import annotations

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


def _reset_state() -> None:
    main.gemini_service = GeminiEnvironmentService(api_key="", cache_ttl_seconds=600)
    main.USERS_DB.clear()
    main.VOLUNTEERS_DB.clear()
    main.EMERGENCY_ALERTS_DB.clear()


def test_health_endpoint() -> None:
    client = TestClient(main.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["model"] == "gemini-4-hydrogen"
    assert body["refresh_interval_minutes"] == 10


def test_environment_check_demo_and_10min_cache() -> None:
    _reset_state()
    client = TestClient(main.app)

    payload = {
        "origin": "Campus Coyoacán",
        "destination": "Clínica 19, Av. Universidad",
        "profile": "silla_de_ruedas",
        "force_refresh": False,
    }
    first = client.post("/api/v1/environment-check", json=payload)
    assert first.status_code == 200
    data1 = first.json()
    assert data1["status_mode"] == "offline_demo"
    assert data1["from_cache"] is False
    assert data1["next_refresh_minutes"] == 10

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
            "recomendaciones_perfil": ["Usa banqueta norte con rampa continua."],
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
        profile=AccessibilityProfile.NEURODIVERGENTE,
    )
    resp = service.check_environment(req)

    assert resp.status_mode == "gemini_live"
    assert resp.model_used == "gemini-4-hydrogen"
    assert len(resp.fuentes) == 1

    _, kwargs = mock_client.interactions.create.call_args
    assert kwargs["model"] == "gemini-4-hydrogen"
    assert kwargs["tools"] == [{"type": "google_search"}]
    assert kwargs["response_format"]["mime_type"] == "application/json"
    assert kwargs["generation_config"] == {"thinking_level": "low"}


def test_independent_routes_per_disability_and_clinics_requirements() -> None:
    _reset_state()
    client = TestClient(main.app)

    wheelchair = client.get("/api/v1/routes/suggestions", params={"profile": "silla_de_ruedas"}).json()
    auditory = client.get("/api/v1/routes/suggestions", params={"profile": "auditivo"}).json()
    neuro = client.get("/api/v1/routes/suggestions", params={"profile": "neurodivergente"}).json()

    assert len(wheelchair) >= 5
    # Las rutas y tiempos estimados deben ser independientes por discapacidad
    assert wheelchair[0]["route_name"] != auditory[0]["route_name"]
    assert wheelchair[0]["route_name"] != neuro[0]["route_name"]
    assert wheelchair[-1]["estimated_minutes"] != auditory[-1]["estimated_minutes"]

    clinics = client.get("/api/v1/clinics", params={"profile": "movilidad_reducida"})
    assert clinics.status_code == 200
    clinics_data = clinics.json()
    assert len(clinics_data) >= 3
    for clinic in clinics_data:
        assert clinic["schedule"]
        assert clinic["estimated_minutes"] > 0
        assert len(clinic["requirements_to_bring"]) >= 3
        assert len(clinic["accessibility_features"]) >= 2


def test_profile_auth_empty_volunteers_apply_and_sos() -> None:
    _reset_state()
    client = TestClient(main.app)

    # 1) La lista de voluntarios comienza vacía
    vols_initial = client.get("/api/v1/volunteers")
    assert vols_initial.status_code == 200
    assert vols_initial.json() == []

    # Solicitar guía cuando no hay voluntarios informa correctamente
    req_empty = client.post(
        "/api/v1/volunteer-request",
        json={"user_location": "Campus Coyoacán", "destination": "Clínica 19", "profile": "visual"},
    )
    assert req_empty.status_code == 201
    assert req_empty.json()["status"] == "sin_voluntarios"

    # 2) Crear perfil con usuario, correo vinculado, contraseña y discapacidad
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "username": "emiliano_coyoacan",
            "email": "emiliano@apexsoa.mx",
            "password": "MiPassword123",
            "disability_profile": "visual",
        },
    )
    assert reg.status_code == 201
    user = reg.json()
    assert user["email"] == "emiliano@apexsoa.mx"
    assert user["disability_profile"] == "visual"
    assert user["is_volunteer"] is False

    # 3) Iniciar sesión con correo vinculado
    login = client.post(
        "/api/v1/auth/login",
        json={"identifier": "emiliano@apexsoa.mx", "password": "MiPassword123"},
    )
    assert login.status_code == 200
    assert login.json()["id"] == user["id"]

    # 4) Cambiar discapacidad en el perfil
    upd = client.put(
        "/api/v1/profile/disability",
        json={"user_id": user["id"], "disability_profile": "neurodivergente"},
    )
    assert upd.status_code == 200
    assert upd.json()["disability_profile"] == "neurodivergente"

    # 5) Postularse como voluntario y aparecer en la lista de voluntarios
    apply_resp = client.post(
        "/api/v1/volunteers/apply",
        json={
            "user_id": user["id"],
            "zone": "Campus Coyoacán",
            "availability": "Lun-Vie 10:00-16:00",
            "support_notes": "Acompañamiento a Clínica 19",
        },
    )
    assert apply_resp.status_code == 201

    vols_after = client.get("/api/v1/volunteers").json()
    assert len(vols_after) == 1
    assert vols_after[0]["username"] == "emiliano_coyoacan"

    # Ahora sí se puede asignar guía voluntaria
    req_ok = client.post(
        "/api/v1/volunteer-request",
        json={"user_location": "Campus Coyoacán", "destination": "Clínica 19", "profile": "visual"},
    )
    assert req_ok.status_code == 201
    assert req_ok.json()["status"] == "asignado"

    # 6) Botón de emergencia SOS
    sos = client.post(
        "/api/v1/emergency",
        json={
            "location": "Av. Universidad 400, Coyoacán",
            "profile": "silla_de_ruedas",
            "username": "emiliano_coyoacan",
        },
    )
    assert sos.status_code == 201
    sos_data = sos.json()
    assert sos_data["status"] == "alerta_enviada"
    assert any("911" in num for num in sos_data["emergency_numbers"])
