"""API FastAPI de prueba corta para Map Inclusive (Python + Android + Gemini API).

Ejecución local:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gemini_service import GeminiEnvironmentService
from models import (
    AccessibilityProfile,
    ClinicInfo,
    EnvironmentCheckRequest,
    EnvironmentCheckResponse,
    IncidentCreateRequest,
    IncidentRecord,
    RiskLevel,
    VolunteerRequest,
    VolunteerResponse,
)

load_dotenv()

app = FastAPI(
    title="Map Inclusive API",
    description=(
        "Backend Python (FastAPI + Google Gemini Interactions API) para la prueba corta "
        "de Map Inclusive (Equipo Apex soa · Campus Coyoacán)."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

gemini_service = GeminiEnvironmentService()

# Datos iniciales de demostración alineados con el boceto de Campus Coyoacán
CLINICS_DB: List[ClinicInfo] = [
    ClinicInfo(
        id="clinica-19",
        name="Clínica 19 (IMSS)",
        address="Av. Universidad, Coyoacán",
        distance_text="400 m",
        schedule="Lun-Vie 08:00 - 20:00 · Urgencias 24h",
        accessible_entrance=True,
        latitude=19.3512,
        longitude=-99.1631,
    ),
    ClinicInfo(
        id="centro-salud-coyoacan",
        name="Centro de Salud Coyoacán",
        address="Calle Ignacio Allende, Del Carmen",
        distance_text="850 m",
        schedule="Lun-Dom 07:30 - 19:00",
        accessible_entrance=True,
        latitude=19.3481,
        longitude=-99.1604,
    ),
    ClinicInfo(
        id="hospital-xoco",
        name="Hospital General Xoco",
        address="Av. México Coyoacán s/n",
        distance_text="1.4 km",
        schedule="Abierto 24 horas",
        accessible_entrance=True,
        latitude=19.3597,
        longitude=-99.1628,
    ),
]

INCIDENTS_DB: List[IncidentRecord] = [
    IncidentRecord(
        id="inc-001",
        title="Rampa bloqueada",
        description="Vehículo estacionado bloqueando la rampa peatonal en esquina norte.",
        location="Av. Universidad esq. Miguel Ángel de Quevedo",
        profile=AccessibilityProfile.SILLA_DE_RUEDAS,
        severity=RiskLevel.ALTO,
        ai_advice="Rodea por el cruce peatonal a 80 m con rampa disponible.",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
]


@app.get("/health")
def health() -> dict:
    """Verifica el estado del servidor y si Gemini live está configurado."""
    return {
        "status": "ok",
        "service": "map-inclusive-backend",
        "gemini_live_enabled": gemini_service.is_live_enabled,
        "model": gemini_service.model,
        "refresh_interval_minutes": max(1, gemini_service.cache_ttl_seconds // 60),
    }


@app.post("/api/v1/environment-check", response_model=EnvironmentCheckResponse)
def environment_check(req: EnvironmentCheckRequest) -> EnvironmentCheckResponse:
    """Consulta a Gemini sobre clima, bloqueos, transporte e incidencias (caché de 10 min)."""
    return gemini_service.check_environment(req, active_incidents=INCIDENTS_DB)


@app.get("/api/v1/clinics", response_model=List[ClinicInfo])
def list_clinics() -> List[ClinicInfo]:
    """Lista las clínicas cercanas con horarios y acceso adaptado."""
    return CLINICS_DB


@app.get("/api/v1/incidents", response_model=List[IncidentRecord])
def list_incidents() -> List[IncidentRecord]:
    """Devuelve las incidencias reportadas por la comunidad."""
    return INCIDENTS_DB


@app.post("/api/v1/incidents", response_model=IncidentRecord, status_code=201)
def create_incident(payload: IncidentCreateRequest) -> IncidentRecord:
    """Registra una incidencia desde Android (Pantalla 4) y la clasifica con Gemini."""
    severity, ai_advice = gemini_service.classify_incident(
        title=payload.title,
        description=payload.description,
        location=payload.location,
        profile=payload.profile,
    )
    record = IncidentRecord(
        id=f"inc-{uuid.uuid4().hex[:6]}",
        title=payload.title,
        description=payload.description,
        location=payload.location,
        profile=payload.profile,
        severity=severity,
        ai_advice=ai_advice,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    INCIDENTS_DB.insert(0, record)
    # Invalida el caché para que la siguiente actualización de ruta tome en cuenta este reporte
    gemini_service.clear_cache()
    return record


@app.post("/api/v1/volunteer-request", response_model=VolunteerResponse, status_code=201)
def request_volunteer(payload: VolunteerRequest) -> VolunteerResponse:
    """Simula la asignación inmediata de una persona guía voluntaria (Pantalla 4)."""
    return VolunteerResponse(
        request_id=f"vol-{uuid.uuid4().hex[:6]}",
        status="asignado",
        volunteer_name="Sofía Hernández (Voluntaria Campus Coyoacán)",
        eta_minutes=6,
        message=(
            f"Guía voluntaria confirmada para acompañarte hacia {payload.destination} "
            f"(perfil: {payload.profile.value})."
        ),
    )
