"""API FastAPI de Map Inclusive (100% Python + Google Gemini API).

Ejecución local:
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from typing import Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from gemini_service import GeminiEnvironmentService
from models import (
    PROFILE_LABELS,
    AccessibilityProfile,
    ClinicInfo,
    EmergencyAlertRequest,
    EmergencyAlertResponse,
    EnvironmentCheckRequest,
    EnvironmentCheckResponse,
    IncidentCreateRequest,
    IncidentRecord,
    RiskLevel,
    RouteEstimate,
    UpdateDisabilityRequest,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
    VolunteerApplicationRequest,
    VolunteerMember,
    VolunteerRequest,
    VolunteerResponse,
)

load_dotenv()

app = FastAPI(
    title="Map Inclusive API",
    description=(
        "Backend 100% Python (FastAPI + Google Gemini Interactions API) para "
        "Map Inclusive (Equipo Apex soa · Campus Coyoacán)."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

gemini_service = GeminiEnvironmentService()

# ---------------------------------------------------------------------------
# Reglas independientes de ruteo y velocidad por tipo de discapacidad
# ---------------------------------------------------------------------------
PROFILE_ROUTING_CONFIG: Dict[AccessibilityProfile, dict] = {
    AccessibilityProfile.SILLA_DE_RUEDAS: {
        "route_prefix": "Ruta con rampas continuas",
        "distance_factor": 1.15,  # rodea escalones o rampas bloqueadas
        "minutes_per_km": 15.0,
        "summary": "Sin escalones, banquetas anchas y rampas verificadas en cada cruce.",
        "step_templates": [
            "Avanza por banqueta norte ancha de Av. Universidad (rampa disponible).",
            "Gira a la derecha en 80 m evitando la rampa bloqueada reportada.",
            "Cruza por paso peatonal a nivel de calle hacia {dest}.",
        ],
    },
    AccessibilityProfile.VISUAL: {
        "route_prefix": "Ruta podotáctil y semáforo sonoro",
        "distance_factor": 1.05,
        "minutes_per_km": 14.0,
        "summary": "Prioriza guía podotáctil, cruces con semáforo sonoro y aviso de obras.",
        "step_templates": [
            "Sigue la línea podotáctil continua sobre Av. Universidad.",
            "Cruce seguro con semáforo sonoro en 90 m; sin obstáculos a nivel de piso.",
            "Acceso principal señalizado y bien iluminado hacia {dest}.",
        ],
    },
    AccessibilityProfile.AUDITIVO: {
        "route_prefix": "Ruta de alta visibilidad y señalética",
        "distance_factor": 1.0,
        "minutes_per_km": 12.0,
        "summary": "Cruces con semáforos visuales claros y alertas en pantalla cada 10 min.",
        "step_templates": [
            "Continúa por corredor peatonal con visibilidad abierta en ambos sentidos.",
            "Cruce con semáforo peatonal luminoso y espejo vial en 100 m.",
            "Llegada directa con señalización visual clara a {dest}.",
        ],
    },
    AccessibilityProfile.MOVILIDAD_REDUCIDA: {
        "route_prefix": "Ruta de pendiente suave con descansos",
        "distance_factor": 1.08,
        "minutes_per_km": 16.5,
        "summary": "Menor pendiente, trayecto más corto sin escaleras y bancas intermedias.",
        "step_templates": [
            "Toma el andador plano con barandal y sombra lateral.",
            "Zona de descanso con banca disponible a mitad del recorrido.",
            "Entrada sin escalones y acceso preferente en {dest}.",
        ],
    },
    AccessibilityProfile.NEURODIVERGENTE: {
        "route_prefix": "Ruta tranquila de baja estimulación",
        "distance_factor": 1.12,
        "minutes_per_km": 13.5,
        "summary": "Evita avenidas ruidosas, obras y aglomeraciones con avisos simples.",
        "step_templates": [
            "Camina por calle secundaria arbolada con bajo nivel de ruido vehicular.",
            "Paso 2 simple: gira a la derecha en la esquina del parque (zona tranquila).",
            "Acceso ordenado y con menor flujo de personas hacia {dest}.",
        ],
    },
}


def compute_route_for_profile(
    dest_id: str,
    destination: str,
    address: str,
    category: str,
    base_km: float,
    profile: AccessibilityProfile,
) -> RouteEstimate:
    """Calcula distancia, tiempo estimado y pasos independientes para cada discapacidad."""
    cfg = PROFILE_ROUTING_CONFIG[profile]
    adjusted_km = round(base_km * cfg["distance_factor"], 2)
    est_minutes = max(3, int(round(adjusted_km * cfg["minutes_per_km"])))
    dist_text = (
        f"{int(round(adjusted_km * 1000))} m"
        if adjusted_km < 1.0
        else f"{adjusted_km:.1f} km"
    )
    steps = [tpl.format(dest=destination) for tpl in cfg["step_templates"]]
    return RouteEstimate(
        id=dest_id,
        destination=destination,
        address=address,
        category=category,
        profile=profile,
        profile_label=PROFILE_LABELS[profile],
        route_name=f"{cfg['route_prefix']} · {destination}",
        distance_km=adjusted_km,
        distance_text=dist_text,
        estimated_minutes=est_minutes,
        accessibility_summary=cfg["summary"],
        steps=steps,
    )


# Catálogo de clínicas cercanas en Coyoacán (con horario, accesibilidad y qué llevar)
CLINICS_CATALOG: List[dict] = [
    {
        "id": "clinica-19",
        "name": "Clínica 19 (UMF IMSS)",
        "address": "Av. Universidad, Col. Coyoacán, CDMX",
        "base_km": 0.4,
        "schedule": "Lun-Vie 08:00 - 20:00",
        "emergency_hours": "Atención médica continua 24 horas",
        "phone": "55 5554 1919",
        "accessible_entrance": True,
        "accessibility_features": [
            "Rampa de acceso principal con barandal",
            "Elevador funcional para planta alta",
            "Sanitarios adaptados para silla de ruedas",
            "Módulo de atención preferente",
        ],
        "services": ["Medicina familiar", "Urgencias menores", "Farmacia", "Curaciones"],
        "requirements_to_bring": [
            "Identificación oficial vigente (INE o pasaporte)",
            "Cartilla Nacional de Salud / Carnet de citas IMSS",
            "Número de Seguridad Social (NSS) y CURP",
            "Receta médica vigente o resumen clínico (si aplica)",
            "Comprobante de domicilio reciente (solo para primera vez)",
        ],
        "latitude": 19.3512,
        "longitude": -99.1631,
    },
    {
        "id": "centro-salud-coyoacan",
        "name": "Centro de Salud T-III Coyoacán",
        "address": "Calle Ignacio Allende, Col. Del Carmen, Coyoacán",
        "base_km": 0.85,
        "schedule": "Lun-Dom 07:30 - 19:00",
        "emergency_hours": "Valoración inicial en horario de consulta",
        "phone": "55 5554 2840",
        "accessible_entrance": True,
        "accessibility_features": [
            "Entrada a nivel de calle sin escalones",
            "Señalización visual en alto contraste",
            "Área de espera tranquila con asientos preferentes",
        ],
        "services": ["Consulta general gratuita", "Vacunación", "Odontología", "Psicología"],
        "requirements_to_bring": [
            "Identificación oficial vigente (INE) o acta de nacimiento (menores)",
            "CURP impreso o digital",
            "Cartilla Nacional de Salud",
            "Comprobante de domicilio (antigüedad menor a 3 meses)",
            "Hoja de gratuidad / IMSS-Bienestar (si cuentas con ella)",
        ],
        "latitude": 19.3481,
        "longitude": -99.1604,
    },
    {
        "id": "hospital-xoco",
        "name": "Hospital General Xoco",
        "address": "Av. México Coyoacán s/n, Col. General Anaya",
        "base_km": 1.4,
        "schedule": "Abierto 24 horas (Lunes a Domingo)",
        "emergency_hours": "Urgencias 24 horas (Trauma y Emergencias)",
        "phone": "55 5688 9015",
        "accessible_entrance": True,
        "accessibility_features": [
            "Acceso vehicular y rampa para ambulancias y sillas de ruedas",
            "Préstamo de silla de ruedas en admisión",
            "Elevadores amplios y señalización podotáctil en vestíbulo",
        ],
        "services": ["Urgencias 24h", "Traumatología", "Rayos X", "Hospitalización"],
        "requirements_to_bring": [
            "Identificación oficial vigente del paciente y de un familiar",
            "CURP del paciente",
            "Lista de medicamentos actuales y alergias conocidas",
            "Estudios médicos previos o carnet de control (si aplica)",
            "En urgencia vital se atiende de inmediato sin documentos previos",
        ],
        "latitude": 19.3597,
        "longitude": -99.1628,
    },
]

SUGGESTED_PLACES: List[dict] = [
    {
        "id": "sug-clinica-19",
        "destination": "Clínica 19 (UMF IMSS)",
        "address": "Av. Universidad, Coyoacán",
        "category": "Clínica",
        "base_km": 0.4,
    },
    {
        "id": "sug-centro-salud",
        "destination": "Centro de Salud T-III Coyoacán",
        "address": "Calle Ignacio Allende, Del Carmen",
        "category": "Clínica",
        "base_km": 0.85,
    },
    {
        "id": "sug-metro-coyoacan",
        "destination": "Metro Coyoacán (Línea 3)",
        "address": "Av. Universidad y Mayorazgo",
        "category": "Transporte",
        "base_km": 0.95,
    },
    {
        "id": "sug-parque-centenario",
        "destination": "Jardín Centenario Coyoacán",
        "address": "Centro de Coyoacán",
        "category": "Espacio público",
        "base_km": 1.1,
    },
    {
        "id": "sug-hospital-xoco",
        "destination": "Hospital General Xoco (Urgencias 24h)",
        "address": "Av. México Coyoacán s/n",
        "category": "Hospital",
        "base_km": 1.4,
    },
]

# Almacenamiento en memoria para la prueba corta
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

USERS_DB: Dict[str, dict] = {}
# Lista de voluntarios comienza VACÍA a propósito (se llena al postularse desde Perfil)
VOLUNTEERS_DB: List[VolunteerMember] = []
EMERGENCY_ALERTS_DB: List[dict] = []


def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return dk.hex()


def _to_user_response(user: dict) -> UserProfileResponse:
    prof = AccessibilityProfile(user["disability_profile"])
    return UserProfileResponse(
        id=user["id"],
        username=user["username"],
        email=user["email"],
        disability_profile=prof,
        disability_label=PROFILE_LABELS[prof],
        is_volunteer=user["is_volunteer"],
        created_at=user["created_at"],
    )


# ---------------------------------------------------------------------------
# Endpoints generales y Gemini
# ---------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "map-inclusive-backend",
        "gemini_live_enabled": gemini_service.is_live_enabled,
        "model": gemini_service.model,
        "refresh_interval_minutes": max(1, gemini_service.cache_ttl_seconds // 60),
    }


@app.post("/api/v1/environment-check", response_model=EnvironmentCheckResponse)
def environment_check(req: EnvironmentCheckRequest) -> EnvironmentCheckResponse:
    """Consulta a Gemini sobre clima, bloqueos, transporte e incidencias (caché 10 min)."""
    return gemini_service.check_environment(req, active_incidents=INCIDENTS_DB)


# ---------------------------------------------------------------------------
# Rutas independientes por discapacidad y clínicas
# ---------------------------------------------------------------------------
@app.get("/api/v1/routes/suggestions", response_model=List[RouteEstimate])
def list_route_suggestions(
    profile: AccessibilityProfile = Query(default=AccessibilityProfile.SILLA_DE_RUEDAS),
) -> List[RouteEstimate]:
    """Devuelve lista de destinos sugeridos con rutas y tiempos independientes por discapacidad."""
    return [
        compute_route_for_profile(
            dest_id=p["id"],
            destination=p["destination"],
            address=p["address"],
            category=p["category"],
            base_km=p["base_km"],
            profile=profile,
        )
        for p in SUGGESTED_PLACES
    ]


@app.get("/api/v1/routes/estimate", response_model=RouteEstimate)
def estimate_route(
    destination: str = Query(default="Clínica 19 (UMF IMSS)"),
    profile: AccessibilityProfile = Query(default=AccessibilityProfile.SILLA_DE_RUEDAS),
) -> RouteEstimate:
    """Calcula la ruta independiente y tiempo estimado para cualquier destino y discapacidad."""
    lowered = destination.lower()
    for place in SUGGESTED_PLACES:
        if place["destination"].lower() in lowered or lowered in place["destination"].lower():
            return compute_route_for_profile(
                dest_id=place["id"],
                destination=place["destination"],
                address=place["address"],
                category=place["category"],
                base_km=place["base_km"],
                profile=profile,
            )
    return compute_route_for_profile(
        dest_id="custom-route",
        destination=destination,
        address="Zona Coyoacán, CDMX",
        category="Destino personalizado",
        base_km=1.0,
        profile=profile,
    )


@app.get("/api/v1/clinics", response_model=List[ClinicInfo])
def list_clinics(
    profile: AccessibilityProfile = Query(default=AccessibilityProfile.SILLA_DE_RUEDAS),
) -> List[ClinicInfo]:
    """Lista clínicas cercanas con horario, accesibilidad, qué llevar y tiempo estimado."""
    result: List[ClinicInfo] = []
    for c in CLINICS_CATALOG:
        est = compute_route_for_profile(
            dest_id=c["id"],
            destination=c["name"],
            address=c["address"],
            category="Clínica",
            base_km=c["base_km"],
            profile=profile,
        )
        result.append(
            ClinicInfo(
                id=c["id"],
                name=c["name"],
                address=c["address"],
                distance_text=est.distance_text,
                distance_km=est.distance_km,
                estimated_minutes=est.estimated_minutes,
                schedule=c["schedule"],
                emergency_hours=c["emergency_hours"],
                phone=c["phone"],
                accessible_entrance=c["accessible_entrance"],
                accessibility_features=c["accessibility_features"],
                services=c["services"],
                requirements_to_bring=c["requirements_to_bring"],
                latitude=c["latitude"],
                longitude=c["longitude"],
            )
        )
    return result


# ---------------------------------------------------------------------------
# Incidencias ciudadanas
# ---------------------------------------------------------------------------
@app.get("/api/v1/incidents", response_model=List[IncidentRecord])
def list_incidents() -> List[IncidentRecord]:
    return INCIDENTS_DB


@app.post("/api/v1/incidents", response_model=IncidentRecord, status_code=201)
def create_incident(payload: IncidentCreateRequest) -> IncidentRecord:
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
    gemini_service.clear_cache()
    return record


# ---------------------------------------------------------------------------
# Perfil de usuario (registro, correo vinculado, contraseña, discapacidad)
# ---------------------------------------------------------------------------
@app.post("/api/v1/auth/register", response_model=UserProfileResponse, status_code=201)
def register_user(payload: UserRegisterRequest) -> UserProfileResponse:
    username_clean = payload.username.strip()
    email_clean = payload.email.strip().lower()
    if "@" not in email_clean or "." not in email_clean.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Ingresa un correo electrónico válido.")

    for existing in USERS_DB.values():
        if existing["username"].lower() == username_clean.lower():
            raise HTTPException(status_code=409, detail="Ese nombre de usuario ya está registrado.")
        if existing["email"] == email_clean:
            raise HTTPException(status_code=409, detail="Ese correo ya está vinculado a una cuenta.")

    user_id = f"usr-{uuid.uuid4().hex[:8]}"
    salt = secrets.token_hex(16)
    user = {
        "id": user_id,
        "username": username_clean,
        "email": email_clean,
        "salt": salt,
        "password_hash": _hash_password(payload.password, salt),
        "disability_profile": payload.disability_profile.value,
        "is_volunteer": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    USERS_DB[user_id] = user
    return _to_user_response(user)


@app.post("/api/v1/auth/login", response_model=UserProfileResponse)
def login_user(payload: UserLoginRequest) -> UserProfileResponse:
    ident = payload.identifier.strip().lower()
    matched = None
    for user in USERS_DB.values():
        if user["username"].lower() == ident or user["email"] == ident:
            matched = user
            break
    if not matched:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")

    candidate_hash = _hash_password(payload.password, matched["salt"])
    if not hmac.compare_digest(candidate_hash, matched["password_hash"]):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    return _to_user_response(matched)


@app.put("/api/v1/profile/disability", response_model=UserProfileResponse)
def update_user_disability(payload: UpdateDisabilityRequest) -> UserProfileResponse:
    user = USERS_DB.get(payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    user["disability_profile"] = payload.disability_profile.value
    return _to_user_response(user)


# ---------------------------------------------------------------------------
# Voluntarios (lista inicialmente vacía + postulación desde Perfil)
# ---------------------------------------------------------------------------
@app.get("/api/v1/volunteers", response_model=List[VolunteerMember])
def list_volunteers() -> List[VolunteerMember]:
    """Devuelve la lista de voluntarios registrados (inicialmente vacía)."""
    return VOLUNTEERS_DB


@app.post("/api/v1/volunteers/apply", response_model=VolunteerMember, status_code=201)
def apply_as_volunteer(payload: VolunteerApplicationRequest) -> VolunteerMember:
    """Permite a un usuario con sesión iniciada postularse como voluntario."""
    user = USERS_DB.get(payload.user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Debes iniciar sesión en tu perfil para postularte como voluntario.",
        )

    for existing in VOLUNTEERS_DB:
        if existing.user_id == user["id"]:
            return existing

    member = VolunteerMember(
        id=f"vol-{uuid.uuid4().hex[:6]}",
        user_id=user["id"],
        username=user["username"],
        email=user["email"],
        zone=payload.zone.strip() or "Campus Coyoacán",
        availability=payload.availability.strip() or "Horario flexible",
        support_notes=payload.support_notes.strip() or "Apoyo en rutas accesibles",
        registered_at=datetime.now(timezone.utc).isoformat(),
    )
    user["is_volunteer"] = True
    VOLUNTEERS_DB.insert(0, member)
    return member


@app.post("/api/v1/volunteer-request", response_model=VolunteerResponse, status_code=201)
def request_volunteer(payload: VolunteerRequest) -> VolunteerResponse:
    """Asigna una guía voluntaria registrada o informa si todavía no hay voluntarios activos."""
    if not VOLUNTEERS_DB:
        return VolunteerResponse(
            request_id=f"req-{uuid.uuid4().hex[:6]}",
            status="sin_voluntarios",
            volunteer_name=None,
            eta_minutes=None,
            message=(
                "Por el momento no hay voluntarios activos en la zona. "
                "Puedes postularte como voluntario desde la pestaña Perfil o usar el botón de Emergencia."
            ),
        )

    chosen = VOLUNTEERS_DB[0]
    return VolunteerResponse(
        request_id=f"req-{uuid.uuid4().hex[:6]}",
        status="asignado",
        volunteer_name=f"{chosen.username} ({chosen.zone})",
        eta_minutes=6,
        message=(
            f"Guía voluntaria confirmada para acompañarte hacia {payload.destination} "
            f"(perfil: {PROFILE_LABELS[payload.profile]})."
        ),
    )


# ---------------------------------------------------------------------------
# Emergencia SOS
# ---------------------------------------------------------------------------
@app.post("/api/v1/emergency", response_model=EmergencyAlertResponse, status_code=201)
def trigger_emergency(payload: EmergencyAlertRequest) -> EmergencyAlertResponse:
    now_iso = datetime.now(timezone.utc).isoformat()
    alert_id = f"sos-{uuid.uuid4().hex[:6]}"
    EMERGENCY_ALERTS_DB.insert(
        0,
        {
            "alert_id": alert_id,
            "location": payload.location,
            "profile": payload.profile.value,
            "username": payload.username,
            "notes": payload.notes,
            "timestamp": now_iso,
        },
    )
    return EmergencyAlertResponse(
        alert_id=alert_id,
        status="alerta_enviada",
        timestamp=now_iso,
        nearest_emergency_clinic="Hospital General Xoco (Urgencias 24h · Tel. 55 5688 9015)",
        emergency_numbers=[
            "911 — Emergencias generales (Policía / Ambulancia / Protección Civil)",
            "065 — Cruz Roja Mexicana",
            "55 5658 1111 — LOCATEL CDMX (apoyo y orientación 24h)",
        ],
        message=(
            f"Alerta SOS registrada ({alert_id}) para perfil {PROFILE_LABELS[payload.profile]} "
            f"en {payload.location}. Mantén la calma y comunícate al 911 si hay peligro inmediato."
        ),
    )
