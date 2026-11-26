"""API FastAPI de Map Inclusive (100% Python + Google Gemini API).

Ejecución local:
    uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

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
    GuardianContact,
    GuardianLocationShareRequest,
    GuardianLocationShareResponse,
    IncidentCreateRequest,
    IncidentRecord,
    LostMinorAlertRequest,
    LostMinorAlertResponse,
    RiskLevel,
    RouteEstimate,
    UpdateDisabilityRequest,
    UpdateProfileRequest,
    UserLoginRequest,
    UserProfileResponse,
    UserRegisterRequest,
    VolunteerApplicationRequest,
    VolunteerMember,
    VolunteerRequest,
    VolunteerResponse,
    normalize_disabilities,
)

load_dotenv()

app = FastAPI(
    title="Map Inclusive API",
    description=(
        "Backend 100% Python (FastAPI + Google Gemini Interactions API) para "
        "Map Inclusive (Equipo Apex soa · Campus Coyoacán)."
    ),
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

gemini_service = GeminiEnvironmentService()

# ---------------------------------------------------------------------------
# Reglas independientes de ruteo y velocidad por discapacidad (combinables)
# ---------------------------------------------------------------------------
PROFILE_ROUTING_CONFIG: Dict[AccessibilityProfile, dict] = {
    AccessibilityProfile.SILLA_DE_RUEDAS: {
        "route_prefix": "Rampas continuas",
        "distance_factor": 1.15,
        "minutes_per_km": 15.0,
        "summary": "Sin escalones, banquetas anchas y rampas verificadas.",
        "step": "Silla de ruedas: avanza por banqueta norte ancha con rampas disponibles (evitando rampa bloqueada).",
    },
    AccessibilityProfile.VISUAL: {
        "route_prefix": "Guía podotáctil y sonoro",
        "distance_factor": 1.05,
        "minutes_per_km": 14.0,
        "summary": "Prioriza guía podotáctil, cruces con semáforo sonoro y aviso de obras.",
        "step": "Visual: sigue la línea podotáctil continua y cruza en el semáforo sonoro a 90 m.",
    },
    AccessibilityProfile.AUDITIVO: {
        "route_prefix": "Alta visibilidad",
        "distance_factor": 1.0,
        "minutes_per_km": 12.0,
        "summary": "Cruces con semáforos visuales claros y alertas en pantalla cada 10 min.",
        "step": "Auditivo: utiliza el paso con semáforo luminoso visible y espejo peatonal.",
    },
    AccessibilityProfile.MOVILIDAD_REDUCIDA: {
        "route_prefix": "Pendiente suave y descansos",
        "distance_factor": 1.08,
        "minutes_per_km": 16.5,
        "summary": "Menor pendiente, trayecto sin escaleras largas y bancas intermedias.",
        "step": "Movilidad reducida: toma el andador plano con barandal y banca de descanso a mitad de ruta.",
    },
    AccessibilityProfile.NEURODIVERGENTE: {
        "route_prefix": "Baja estimulación",
        "distance_factor": 1.12,
        "minutes_per_km": 13.5,
        "summary": "Evita avenidas ruidosas, obras y aglomeraciones con avisos simples.",
        "step": "Neurodivergente: camina por calle secundaria arbolada y tranquila con menor ruido vehicular.",
    },
}


def parse_profiles_query(
    profiles: Optional[str],
    profile: AccessibilityProfile,
) -> List[AccessibilityProfile]:
    """Parsea una lista separada por comas (`silla_de_ruedas,visual`) o usa `profile`."""
    if not profiles:
        return [profile]
    parsed: List[AccessibilityProfile] = []
    for raw in profiles.split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            parsed.append(AccessibilityProfile(token))
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Discapacidad no válida: '{token}'.",
            ) from exc
    return normalize_disabilities(parsed, profile)


def compute_route_for_disabilities(
    dest_id: str,
    destination: str,
    address: str,
    category: str,
    base_km: float,
    disabilities: List[AccessibilityProfile],
) -> RouteEstimate:
    """Calcula distancia, tiempo estimado y pasos combinando TODAS las discapacidades elegidas."""
    active = normalize_disabilities(disabilities)
    configs = [PROFILE_ROUTING_CONFIG[d] for d in active]

    # Al combinar múltiples discapacidades se aplica el criterio más seguro/conservador
    # más un pequeño margen adicional (3% por restricción extra) por desvíos combinados.
    extra_margin = 1.0 + 0.03 * max(0, len(active) - 1)
    distance_factor = max(c["distance_factor"] for c in configs) * extra_margin
    minutes_per_km = max(c["minutes_per_km"] for c in configs)

    adjusted_km = round(base_km * distance_factor, 2)
    est_minutes = max(3, int(round(adjusted_km * minutes_per_km)))
    dist_text = (
        f"{int(round(adjusted_km * 1000))} m"
        if adjusted_km < 1.0
        else f"{adjusted_km:.1f} km"
    )

    labels = [PROFILE_LABELS[d] for d in active]
    prefixes = " + ".join(c["route_prefix"] for c in configs)
    summary = " ".join(c["summary"] for c in configs)
    steps = [c["step"] for c in configs] + [f"Llegada accesible verificada a {destination}."]

    return RouteEstimate(
        id=dest_id,
        destination=destination,
        address=address,
        category=category,
        profile=active[0],
        profile_label=" + ".join(labels),
        disabilities=active,
        disabilities_labels=labels,
        route_name=f"Ruta ({prefixes}) · {destination}",
        distance_km=adjusted_km,
        distance_text=dist_text,
        estimated_minutes=est_minutes,
        accessibility_summary=summary,
        steps=steps,
    )


def _validate_base64_image(photo_b64: str, field_name: str = "foto de rostro") -> str:
    cleaned = photo_b64.strip()
    if "," in cleaned and cleaned.lower().startswith("data:image"):
        cleaned = cleaned.split(",", 1)[1].strip()
    if len(cleaned) < 20:
        raise HTTPException(
            status_code=400,
            detail=f"Debes adjuntar una {field_name} válida.",
        )
    try:
        raw = base64.b64decode(cleaned, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"La {field_name} no tiene un formato de imagen válido.",
        ) from exc
    if len(raw) < 16:
        raise HTTPException(status_code=400, detail=f"La {field_name} está vacía o dañada.")
    if len(raw) > 6 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="La imagen supera el límite de 6 MB.")
    return cleaned


# Catálogo de clínicas cercanas en Coyoacán
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


def _default_incidents() -> List[IncidentRecord]:
    now = datetime.now(timezone.utc)
    return [
        IncidentRecord(
            id="inc-001",
            title="Rampa bloqueada por vehículo",
            description="Vehículo estacionado bloqueando la rampa peatonal en esquina norte.",
            location="Av. Universidad esq. Miguel Ángel de Quevedo",
            profile=AccessibilityProfile.SILLA_DE_RUEDAS,
            disabilities=[
                AccessibilityProfile.SILLA_DE_RUEDAS,
                AccessibilityProfile.MOVILIDAD_REDUCIDA,
            ],
            disabilities_labels=["Silla de ruedas", "Movilidad reducida"],
            reported_by="Comunidad Campus Coyoacán",
            severity=RiskLevel.ALTO,
            ai_advice="Rodea por el cruce peatonal a 80 m con rampa disponible y paso seguro.",
            created_at=(now - timedelta(minutes=18)).isoformat(),
        ),
        IncidentRecord(
            id="inc-002",
            title="Obra ruidosa en banqueta",
            description="Trabajos de pavimentación con taladro neumático y paso estrecho.",
            location="Calle Ignacio Allende 120, Del Carmen",
            profile=AccessibilityProfile.NEURODIVERGENTE,
            disabilities=[
                AccessibilityProfile.NEURODIVERGENTE,
                AccessibilityProfile.VISUAL,
            ],
            disabilities_labels=["Persona neurodivergente", "Discapacidad visual"],
            reported_by="Reporte ciudadano",
            severity=RiskLevel.MEDIO,
            ai_advice="Usa la acera opuesta o calle paralela arbolada para evitar ruido y obstáculos.",
            created_at=(now - timedelta(hours=1, minutes=25)).isoformat(),
        ),
    ]


INCIDENTS_DB: List[IncidentRecord] = _default_incidents()
USERS_DB: Dict[str, dict] = {}
# Lista de voluntarios comienza VACÍA (se llena cuando alguien con foto de rostro se postula)
VOLUNTEERS_DB: List[VolunteerMember] = []
EMERGENCY_ALERTS_DB: List[dict] = []
GUARDIAN_TRACKING_DB: List[GuardianLocationShareResponse] = []
LOST_MINOR_ALERTS_DB: List[LostMinorAlertResponse] = []


def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return dk.hex()


def _to_user_response(user: dict) -> UserProfileResponse:
    disabilities = [AccessibilityProfile(d) for d in user["disabilities"]]
    labels = [PROFILE_LABELS[d] for d in disabilities]
    guardian = GuardianContact(**user["guardian"]) if user.get("guardian") else None
    return UserProfileResponse(
        id=user["id"],
        username=user["username"],
        email=user["email"],
        disability_profile=disabilities[0],
        disability_label=" + ".join(labels),
        disabilities=disabilities,
        disabilities_labels=labels,
        face_photo_base64=user.get("face_photo_base64"),
        face_photo_filename=user.get("face_photo_filename"),
        is_minor=bool(user.get("is_minor", False)),
        guardian=guardian,
        is_volunteer=bool(user.get("is_volunteer", False)),
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
    return gemini_service.check_environment(req, active_incidents=INCIDENTS_DB)


# ---------------------------------------------------------------------------
# Rutas independientes (1 o múltiples discapacidades) y clínicas
# ---------------------------------------------------------------------------
@app.get("/api/v1/routes/suggestions", response_model=List[RouteEstimate])
def list_route_suggestions(
    profile: AccessibilityProfile = Query(default=AccessibilityProfile.SILLA_DE_RUEDAS),
    profiles: Optional[str] = Query(
        default=None,
        description="Lista separada por comas para múltiples discapacidades, ej. silla_de_ruedas,visual",
    ),
) -> List[RouteEstimate]:
    active_disabilities = parse_profiles_query(profiles, profile)
    return [
        compute_route_for_disabilities(
            dest_id=p["id"],
            destination=p["destination"],
            address=p["address"],
            category=p["category"],
            base_km=p["base_km"],
            disabilities=active_disabilities,
        )
        for p in SUGGESTED_PLACES
    ]


@app.get("/api/v1/routes/estimate", response_model=RouteEstimate)
def estimate_route(
    destination: str = Query(default="Clínica 19 (UMF IMSS)"),
    profile: AccessibilityProfile = Query(default=AccessibilityProfile.SILLA_DE_RUEDAS),
    profiles: Optional[str] = Query(default=None),
) -> RouteEstimate:
    active_disabilities = parse_profiles_query(profiles, profile)
    lowered = destination.lower()
    for place in SUGGESTED_PLACES:
        if place["destination"].lower() in lowered or lowered in place["destination"].lower():
            return compute_route_for_disabilities(
                dest_id=place["id"],
                destination=place["destination"],
                address=place["address"],
                category=place["category"],
                base_km=place["base_km"],
                disabilities=active_disabilities,
            )
    return compute_route_for_disabilities(
        dest_id="custom-route",
        destination=destination,
        address="Zona Coyoacán, CDMX",
        category="Destino personalizado",
        base_km=1.0,
        disabilities=active_disabilities,
    )


@app.get("/api/v1/clinics", response_model=List[ClinicInfo])
def list_clinics(
    profile: AccessibilityProfile = Query(default=AccessibilityProfile.SILLA_DE_RUEDAS),
    profiles: Optional[str] = Query(default=None),
) -> List[ClinicInfo]:
    active_disabilities = parse_profiles_query(profiles, profile)
    result: List[ClinicInfo] = []
    for c in CLINICS_CATALOG:
        est = compute_route_for_disabilities(
            dest_id=c["id"],
            destination=c["name"],
            address=c["address"],
            category="Clínica",
            base_km=c["base_km"],
            disabilities=active_disabilities,
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
# Historial y reporte de incidencias
# ---------------------------------------------------------------------------
@app.get("/api/v1/incidents", response_model=List[IncidentRecord])
def list_incidents() -> List[IncidentRecord]:
    """Devuelve el historial completo de incidencias (más recientes primero)."""
    return INCIDENTS_DB


@app.post("/api/v1/incidents", response_model=IncidentRecord, status_code=201)
def create_incident(payload: IncidentCreateRequest) -> IncidentRecord:
    disabilities = normalize_disabilities(payload.disabilities, payload.profile)
    severity, ai_advice = gemini_service.classify_incident(
        title=payload.title,
        description=payload.description,
        location=payload.location,
        disabilities=disabilities,
    )
    record = IncidentRecord(
        id=f"inc-{uuid.uuid4().hex[:6]}",
        title=payload.title,
        description=payload.description,
        location=payload.location,
        profile=disabilities[0],
        disabilities=disabilities,
        disabilities_labels=[PROFILE_LABELS[d] for d in disabilities],
        reported_by=(payload.reported_by or "Usuario Map Inclusive").strip(),
        severity=severity,
        ai_advice=ai_advice,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    INCIDENTS_DB.insert(0, record)
    gemini_service.clear_cache()
    return record


# ---------------------------------------------------------------------------
# Perfil de usuario (foto opcional, múltiples discapacidades, menor + familiar)
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

    photo_clean: Optional[str] = None
    if payload.face_photo_base64:
        photo_clean = _validate_base64_image(payload.face_photo_base64, "foto de perfil")

    guardian_dict: Optional[dict] = None
    if payload.is_minor:
        if not payload.guardian or not payload.guardian.name.strip():
            raise HTTPException(
                status_code=400,
                detail="Si eres menor de edad, debes registrar el nombre de un familiar o tutor.",
            )
        if not (payload.guardian.phone.strip() or payload.guardian.email.strip()):
            raise HTTPException(
                status_code=400,
                detail="Registra al menos un teléfono o correo de tu familiar para compartir ubicación.",
            )
        guardian_dict = payload.guardian.model_dump()
    elif payload.guardian and payload.guardian.name.strip():
        guardian_dict = payload.guardian.model_dump()

    disabilities = normalize_disabilities(payload.disabilities, payload.disability_profile)
    user_id = f"usr-{uuid.uuid4().hex[:8]}"
    salt = secrets.token_hex(16)
    user = {
        "id": user_id,
        "username": username_clean,
        "email": email_clean,
        "salt": salt,
        "password_hash": _hash_password(payload.password, salt),
        "disabilities": [d.value for d in disabilities],
        "face_photo_base64": photo_clean,
        "face_photo_filename": payload.face_photo_filename if photo_clean else None,
        "is_minor": payload.is_minor,
        "guardian": guardian_dict,
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
    disabilities = normalize_disabilities(payload.disabilities, payload.disability_profile)
    user["disabilities"] = [d.value for d in disabilities]
    return _to_user_response(user)


@app.put("/api/v1/profile", response_model=UserProfileResponse)
def update_user_profile(payload: UpdateProfileRequest) -> UserProfileResponse:
    """Actualiza discapacidades múltiples, foto opcional y datos de menor/familiar."""
    user = USERS_DB.get(payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    if payload.disabilities:
        user["disabilities"] = [d.value for d in normalize_disabilities(payload.disabilities)]

    if payload.clear_photo:
        user["face_photo_base64"] = None
        user["face_photo_filename"] = None
    elif payload.face_photo_base64:
        user["face_photo_base64"] = _validate_base64_image(
            payload.face_photo_base64, "foto de perfil"
        )
        user["face_photo_filename"] = payload.face_photo_filename or "perfil.jpg"

    if payload.is_minor is not None:
        if payload.is_minor:
            guardian_obj = payload.guardian or (
                GuardianContact(**user["guardian"]) if user.get("guardian") else None
            )
            if not guardian_obj or not guardian_obj.name.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Registra el nombre de un familiar o tutor para activar el modo menor de edad.",
                )
            if not (guardian_obj.phone.strip() or guardian_obj.email.strip()):
                raise HTTPException(
                    status_code=400,
                    detail="Registra un teléfono o correo del familiar.",
                )
            user["is_minor"] = True
            user["guardian"] = guardian_obj.model_dump()
        else:
            user["is_minor"] = False
            if payload.guardian is not None:
                user["guardian"] = payload.guardian.model_dump()
    elif payload.guardian is not None:
        user["guardian"] = payload.guardian.model_dump()

    return _to_user_response(user)


# ---------------------------------------------------------------------------
# Voluntarios (FOTO DE ROSTRO OBLIGATORIA + lista inicialmente vacía)
# ---------------------------------------------------------------------------
@app.get("/api/v1/volunteers", response_model=List[VolunteerMember])
def list_volunteers() -> List[VolunteerMember]:
    return VOLUNTEERS_DB


@app.post("/api/v1/volunteers/apply", response_model=VolunteerMember, status_code=201)
def apply_as_volunteer(payload: VolunteerApplicationRequest) -> VolunteerMember:
    """Postula a un usuario con sesión iniciada como voluntario (requiere foto de rostro)."""
    user = USERS_DB.get(payload.user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Debes iniciar sesión en tu perfil para postularte como voluntario.",
        )

    photo_clean = _validate_base64_image(
        payload.face_photo_base64,
        "foto de rostro obligatoria de voluntario",
    )

    for existing in VOLUNTEERS_DB:
        if existing.user_id == user["id"]:
            existing.face_photo_base64 = photo_clean
            existing.face_photo_filename = payload.face_photo_filename
            return existing

    member = VolunteerMember(
        id=f"vol-{uuid.uuid4().hex[:6]}",
        user_id=user["id"],
        username=user["username"],
        email=user["email"],
        face_photo_base64=photo_clean,
        face_photo_filename=payload.face_photo_filename or "rostro_voluntario.jpg",
        zone=payload.zone.strip() or "Campus Coyoacán",
        availability=payload.availability.strip() or "Horario flexible",
        support_notes=payload.support_notes.strip() or "Apoyo en rutas accesibles",
        registered_at=datetime.now(timezone.utc).isoformat(),
    )
    user["is_volunteer"] = True
    if not user.get("face_photo_base64"):
        user["face_photo_base64"] = photo_clean
        user["face_photo_filename"] = member.face_photo_filename
    VOLUNTEERS_DB.insert(0, member)
    return member


@app.post("/api/v1/volunteer-request", response_model=VolunteerResponse, status_code=201)
def request_volunteer(payload: VolunteerRequest) -> VolunteerResponse:
    if not VOLUNTEERS_DB:
        return VolunteerResponse(
            request_id=f"req-{uuid.uuid4().hex[:6]}",
            status="sin_voluntarios",
            volunteer_name=None,
            volunteer_photo_base64=None,
            eta_minutes=None,
            message=(
                "Por el momento no hay voluntarios activos en la zona. "
                "Puedes postularte como voluntario desde la pestaña Perfil (con foto de rostro) "
                "o usar el botón de Emergencia."
            ),
        )

    disabilities = normalize_disabilities(payload.disabilities, payload.profile)
    labels = " + ".join(PROFILE_LABELS[d] for d in disabilities)
    chosen = VOLUNTEERS_DB[0]
    return VolunteerResponse(
        request_id=f"req-{uuid.uuid4().hex[:6]}",
        status="asignado",
        volunteer_name=f"{chosen.username} ({chosen.zone})",
        volunteer_photo_base64=chosen.face_photo_base64,
        eta_minutes=6,
        message=(
            f"Guía voluntaria con rostro verificado confirmada para acompañarte hacia "
            f"{payload.destination} (perfil: {labels})."
        ),
    )


# ---------------------------------------------------------------------------
# Protección de menores: ubicación en tiempo real + alerta sonora por extravío
# ---------------------------------------------------------------------------
@app.post("/api/v1/guardian/location", response_model=GuardianLocationShareResponse, status_code=201)
def share_minor_location(payload: GuardianLocationShareRequest) -> GuardianLocationShareResponse:
    now_iso = datetime.now(timezone.utc).isoformat()
    record = GuardianLocationShareResponse(
        share_id=f"loc-{uuid.uuid4().hex[:6]}",
        status=payload.status,
        guardian_name=payload.guardian_name,
        guardian_contact=payload.guardian_contact,
        location_text=payload.location_text,
        latitude=payload.latitude,
        longitude=payload.longitude,
        shared_at=now_iso,
        message=(
            f"Ubicación en tiempo real enviada a {payload.guardian_name} "
            f"({payload.guardian_contact}) · rumbo a {payload.destination}."
        ),
    )
    GUARDIAN_TRACKING_DB.insert(0, record)
    return record


@app.get("/api/v1/guardian/locations", response_model=List[GuardianLocationShareResponse])
def list_minor_locations() -> List[GuardianLocationShareResponse]:
    return GUARDIAN_TRACKING_DB[:20]


@app.post("/api/v1/guardian/lost-alert", response_model=LostMinorAlertResponse, status_code=201)
def trigger_lost_minor_alert(payload: LostMinorAlertRequest) -> LostMinorAlertResponse:
    now_iso = datetime.now(timezone.utc).isoformat()
    contact = payload.guardian_phone or payload.guardian_email or "familiar registrado"
    labels = ", ".join(PROFILE_LABELS[d] for d in payload.disabilities)
    record = LostMinorAlertResponse(
        alert_id=f"lost-{uuid.uuid4().hex[:6]}",
        status="alarma_activa",
        sound_alarm_triggered=True,
        guardian_notified=f"{payload.guardian_name} ({contact})",
        location_text=payload.location_text,
        timestamp=now_iso,
        helper_message=(
            f"¡ALERTA DE EXTRAVÍO! {payload.username} ({labels}) necesita ayuda. "
            f"Por favor comunícate con su familiar {payload.guardian_name} al {contact} "
            f"o marca al 911."
        ),
    )
    LOST_MINOR_ALERTS_DB.insert(0, record)
    return record


# ---------------------------------------------------------------------------
# Emergencia SOS
# ---------------------------------------------------------------------------
@app.post("/api/v1/emergency", response_model=EmergencyAlertResponse, status_code=201)
def trigger_emergency(payload: EmergencyAlertRequest) -> EmergencyAlertResponse:
    now_iso = datetime.now(timezone.utc).isoformat()
    alert_id = f"sos-{uuid.uuid4().hex[:6]}"
    disabilities = normalize_disabilities(payload.disabilities, payload.profile)
    labels = " + ".join(PROFILE_LABELS[d] for d in disabilities)
    EMERGENCY_ALERTS_DB.insert(
        0,
        {
            "alert_id": alert_id,
            "location": payload.location,
            "disabilities": [d.value for d in disabilities],
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
            f"Alerta SOS registrada ({alert_id}) para perfil {labels} "
            f"en {payload.location}. Mantén la calma y comunícate al 911 si hay peligro inmediato."
        ),
    )
