"""Esquemas de datos para el backend de Map Inclusive (Equipo Apex soa)."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class AccessibilityProfile(str, Enum):
    """Perfiles de accesibilidad definidos en Map Inclusive."""

    SILLA_DE_RUEDAS = "silla_de_ruedas"
    VISUAL = "visual"
    AUDITIVO = "auditivo"
    MOVILIDAD_REDUCIDA = "movilidad_reducida"
    NEURODIVERGENTE = "neurodivergente"


PROFILE_LABELS = {
    AccessibilityProfile.SILLA_DE_RUEDAS: "Silla de ruedas",
    AccessibilityProfile.VISUAL: "Discapacidad visual",
    AccessibilityProfile.AUDITIVO: "Discapacidad auditiva",
    AccessibilityProfile.MOVILIDAD_REDUCIDA: "Movilidad reducida",
    AccessibilityProfile.NEURODIVERGENTE: "Persona neurodivergente",
}


class RiskLevel(str, Enum):
    BAJO = "bajo"
    MEDIO = "medio"
    ALTO = "alto"


# ---------------------------------------------------------------------------
# Entorno y Gemini API
# ---------------------------------------------------------------------------
class EnvironmentCheckRequest(BaseModel):
    """Solicitud enviada desde la app móvil (Pantalla 3) o script CLI."""

    origin: str = Field(
        default="Campus Coyoacán, CDMX",
        description="Punto de origen del usuario.",
    )
    destination: str = Field(
        default="Clínica 19, Av. Universidad, Coyoacán, CDMX",
        description="Destino consultado por el usuario.",
    )
    profile: AccessibilityProfile = Field(
        default=AccessibilityProfile.SILLA_DE_RUEDAS,
        description="Perfil de accesibilidad activo.",
    )
    latitude: Optional[float] = Field(
        default=19.3498,
        description="Latitud opcional del usuario.",
    )
    longitude: Optional[float] = Field(
        default=-99.1617,
        description="Longitud opcional del usuario.",
    )
    force_refresh: bool = Field(
        default=False,
        description="Si es true, omite el caché de 10 minutos y consulta a Gemini al instante.",
    )


class GeminiEnvironmentPayload(BaseModel):
    """Esquema JSON estructurado que genera Gemini mediante Structured Output."""

    banner_resumen: str = Field(
        description=(
            "Resumen muy corto (máximo 90 caracteres) para la franja verde de la app. "
            "Ejemplo: 'Clima despejado, sin bloqueos en Av. Universidad'."
        )
    )
    clima: str = Field(
        description="Condición actual del clima y temperatura aproximada en la zona."
    )
    bloqueos: List[str] = Field(
        description="Lista de bloqueos viales, peatonales o marchas detectadas en la zona."
    )
    transporte_afectado: List[str] = Field(
        description="Estaciones o rutas de transporte público fuera de servicio o con retrasos."
    )
    incidencias_accesibilidad: List[str] = Field(
        description="Obstáculos o alertas relevantes para accesibilidad en el trayecto."
    )
    zonas_riesgo: List[str] = Field(
        description="Avisos sobre zonas poco concurridas o potencialmente riesgosas."
    )
    recomendaciones_perfil: List[str] = Field(
        description="Recomendaciones prácticas adaptadas específicamente al perfil seleccionado."
    )
    nivel_riesgo: RiskLevel = Field(
        description="Nivel general de riesgo o dificultad del trayecto: bajo, medio o alto."
    )


class SourceCitation(BaseModel):
    title: str
    url: str


class EnvironmentCheckResponse(BaseModel):
    """Respuesta completa consumida por la app móvil cada 10 minutos."""

    origin: str
    destination: str
    profile: AccessibilityProfile
    profile_label: str
    status_mode: str = Field(
        description="'gemini_live' si vino de Gemini API o 'offline_demo' si operó sin API key/red."
    )
    from_cache: bool = Field(
        default=False,
        description="Indica si la respuesta fue servida desde el caché de 10 minutos.",
    )
    model_used: str
    updated_at: str
    next_refresh_minutes: int = 10
    banner_resumen: str
    clima: str
    bloqueos: List[str]
    transporte_afectado: List[str]
    incidencias_accesibilidad: List[str]
    zonas_riesgo: List[str]
    recomendaciones_perfil: List[str]
    nivel_riesgo: RiskLevel
    fuentes: List[SourceCitation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Rutas independientes por discapacidad y tiempo estimado
# ---------------------------------------------------------------------------
class RouteEstimate(BaseModel):
    id: str
    destination: str
    address: str
    category: str
    profile: AccessibilityProfile
    profile_label: str
    route_name: str
    distance_km: float
    distance_text: str
    estimated_minutes: int
    accessibility_summary: str
    steps: List[str]


# ---------------------------------------------------------------------------
# Clínicas (con horario, accesibilidad y requisitos que debe llevar el usuario)
# ---------------------------------------------------------------------------
class ClinicInfo(BaseModel):
    id: str
    name: str
    address: str
    distance_text: str
    distance_km: float
    estimated_minutes: int
    schedule: str
    emergency_hours: str
    phone: str
    accessible_entrance: bool
    accessibility_features: List[str]
    services: List[str]
    requirements_to_bring: List[str]
    latitude: float
    longitude: float


# ---------------------------------------------------------------------------
# Incidencias ciudadanas
# ---------------------------------------------------------------------------
class IncidentCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, description="Título corto, ej. 'Rampa bloqueada'")
    description: str = Field(default="", description="Descripción opcional del obstáculo.")
    location: str = Field(default="Av. Universidad, Coyoacán")
    profile: AccessibilityProfile = Field(default=AccessibilityProfile.SILLA_DE_RUEDAS)


class IncidentRecord(BaseModel):
    id: str
    title: str
    description: str
    location: str
    profile: AccessibilityProfile
    severity: RiskLevel
    ai_advice: str
    created_at: str


# ---------------------------------------------------------------------------
# Perfil, Autenticación (usuario + correo + contraseña + discapacidad)
# ---------------------------------------------------------------------------
class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    email: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=6, max_length=128)
    disability_profile: AccessibilityProfile = Field(
        default=AccessibilityProfile.SILLA_DE_RUEDAS
    )


class UserLoginRequest(BaseModel):
    identifier: str = Field(..., min_length=3, description="Nombre de usuario o correo vinculado")
    password: str = Field(..., min_length=1)


class UpdateDisabilityRequest(BaseModel):
    user_id: str
    disability_profile: AccessibilityProfile


class UserProfileResponse(BaseModel):
    id: str
    username: str
    email: str
    disability_profile: AccessibilityProfile
    disability_label: str
    is_volunteer: bool
    created_at: str


# ---------------------------------------------------------------------------
# Voluntarios (lista inicialmente vacía + postulación desde Perfil)
# ---------------------------------------------------------------------------
class VolunteerApplicationRequest(BaseModel):
    user_id: str
    zone: str = Field(default="Campus Coyoacán / Av. Universidad")
    availability: str = Field(default="Lun-Vie 09:00 - 18:00")
    support_notes: str = Field(
        default="Acompañamiento peatonal y apoyo en cruces accesibles."
    )


class VolunteerMember(BaseModel):
    id: str
    user_id: str
    username: str
    email: str
    zone: str
    availability: str
    support_notes: str
    registered_at: str


class VolunteerRequest(BaseModel):
    user_location: str = Field(default="Av. Universidad 400, Coyoacán")
    destination: str = Field(default="Clínica 19")
    profile: AccessibilityProfile = Field(default=AccessibilityProfile.SILLA_DE_RUEDAS)
    notes: str = Field(default="")


class VolunteerResponse(BaseModel):
    request_id: str
    status: str
    volunteer_name: Optional[str] = None
    eta_minutes: Optional[int] = None
    message: str


# ---------------------------------------------------------------------------
# Emergencia SOS
# ---------------------------------------------------------------------------
class EmergencyAlertRequest(BaseModel):
    location: str = Field(default="Av. Universidad, Coyoacán, CDMX")
    profile: AccessibilityProfile = Field(default=AccessibilityProfile.SILLA_DE_RUEDAS)
    username: Optional[str] = None
    notes: str = Field(default="Solicitud de ayuda inmediata desde Map Inclusive")


class EmergencyAlertResponse(BaseModel):
    alert_id: str
    status: str
    timestamp: str
    nearest_emergency_clinic: str
    emergency_numbers: List[str]
    message: str
