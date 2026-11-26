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


def test_health_endpoint() -> None:
    client = TestClient(main.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["model"] == "gemini-4-hydrogen"
    assert body["refresh_interval_minutes"] == 10


def test_environment_check_demo_and_10min_cache() -> None:
    main.gemini_service = GeminiEnvironmentService(api_key="", cache_ttl_seconds=600)
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
    assert data1["banner_resumen"]

    # Segunda consulta dentro de los 10 minutos debe responder desde caché
    second = client.post("/api/v1/environment-check", json=payload)
    assert second.status_code == 200
    assert second.json()["from_cache"] is True

    # force_refresh=True omite el caché
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
    assert resp.banner_resumen == "Clima despejado, sin bloqueos en Av. Universidad"
    assert len(resp.fuentes) == 1
    assert resp.fuentes[0].url == "https://www.metro.cdmx.gob.mx"

    # Validar argumentos exactos enviados al Interactions API
    _, kwargs = mock_client.interactions.create.call_args
    assert kwargs["model"] == "gemini-4-hydrogen"
    assert kwargs["tools"] == [{"type": "google_search"}]
    assert kwargs["response_format"]["type"] == "text"
    assert kwargs["response_format"]["mime_type"] == "application/json"
    assert "schema" in kwargs["response_format"]
    assert kwargs["generation_config"] == {"thinking_level": "low"}


def test_clinics_incidents_and_volunteer_flow() -> None:
    main.gemini_service = GeminiEnvironmentService(api_key="", cache_ttl_seconds=600)
    client = TestClient(main.app)

    clinics = client.get("/api/v1/clinics")
    assert clinics.status_code == 200
    assert any("Clínica 19" in c["name"] for c in clinics.json())

    created = client.post(
        "/api/v1/incidents",
        json={
            "title": "Rampa bloqueada por obra",
            "description": "Paso peatonal reducido",
            "location": "Av. Universidad 300",
            "profile": "silla_de_ruedas",
        },
    )
    assert created.status_code == 201
    inc = created.json()
    assert inc["severity"] == "alto"
    assert inc["ai_advice"]

    vol = client.post(
        "/api/v1/volunteer-request",
        json={
            "user_location": "Campus Coyoacán",
            "destination": "Clínica 19",
            "profile": "visual",
        },
    )
    assert vol.status_code == 201
    assert vol.json()["status"] == "asignado"
