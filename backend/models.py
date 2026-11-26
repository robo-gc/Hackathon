"""Esquemas de datos para el backend de Map Inclusive (Equipo Apex soa)."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


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


def normalize_disabilities(
    disabilities: Optional[List[AccessibilityProfile]],
    fallback_profile: AccessibilityProfile = AccessibilityProfile.SILLA_DE_RUEDAS,
) -> List[AccessibilityProfile]:
    """Devuelve una lista no vacía y sin duplicados preservando el orden."""
    if not disabilities:
        return [fallback_profile]
    seen: set[AccessibilityProfile] = set()
    ordered: List[AccessibilityProfile] = []
    for item in disabilities:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered or [fallback_profile]


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
        description="Perfil principal (compatibilidad). Usa `disabilities` para múltiples.",
    )
    disabilities: Optional[List[AccessibilityProfile]] = Field(
        default=None,
        description="Lista de una o más discapacidades seleccionadas por el usuario.",
    )
    latitude: Optional[float] = Field(default=19.3498)
    longitude: Optional[float] = Field(default=-99.1617)
    force_refresh: bool = Field(
        default=False,
        description="Si es true, omite el caché de 10 minutos y consulta a Gemini al instante.",
    )

    @model_validator(mode="after")
    def _sync_disabilities(self) -> "EnvironmentCheckRequest":
        normalized = normalize_disabilities(self.disabilities, self.profile)
        self.disabilities = normalized
        self.profile = normalized[0]
        return self


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
        description="Recomendaciones prácticas adaptadas a todas las discapacidades seleccionadas."
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
    disabilities: List[AccessibilityProfile]
    disabilities_labels: List[str]
    status_mode: str = Field(
        description="'gemini_live' si vino de Gemini API o 'offline_demo' si operó sin API key/red."
    )
    from_cache: bool = Field(default=False)
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
# Rutas independientes (soporta 1 o múltiples discapacidades + guía paso a paso)
# ---------------------------------------------------------------------------
class NavigationStep(BaseModel):
    step_number: int
    direction: str = Field(description="straight | right | left | arrive")
    distance_meters: int
    headline: str
    detail: str
    spoken_text: str
    visual_cue: str


class RouteEstimate(BaseModel):
    id: str
    destination: str
    address: str
    category: str
    profile: AccessibilityProfile
    profile_label: str
    disabilities: List[AccessibilityProfile]
    disabilities_labels: List[str]
    route_name: str
    distance_km: float
    distance_text: str
    estimated_minutes: int
    accessibility_summary: str
    voice_guidance_recommended: bool = True
    steps: List[str]
    navigation_steps: List[NavigationStep] = Field(default_factory=list)


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
# Incidencias ciudadanas e historial
# ---------------------------------------------------------------------------
class IncidentCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, description="Título corto, ej. 'Rampa bloqueada'")
    description: str = Field(default="", description="Descripción opcional del obstáculo.")
    location: str = Field(default="Av. Universidad, Coyoacán")
    profile: AccessibilityProfile = Field(default=AccessibilityProfile.SILLA_DE_RUEDAS)
    disabilities: Optional[List[AccessibilityProfile]] = Field(default=None)
    reported_by: Optional[str] = Field(default="Usuario anónimo")

    @model_validator(mode="after")
    def _sync_disabilities(self) -> "IncidentCreateRequest":
        normalized = normalize_disabilities(self.disabilities, self.profile)
        self.disabilities = normalized
        self.profile = normalized[0]
        return self


class IncidentRecord(BaseModel):
    id: str
    title: str
    description: str
    location: str
    profile: AccessibilityProfile
    disabilities: List[AccessibilityProfile] = Field(default_factory=list)
    disabilities_labels: List[str] = Field(default_factory=list)
    reported_by: str = "Comunidad Map Inclusive"
    severity: RiskLevel
    ai_advice: str
    created_at: str


# ---------------------------------------------------------------------------
# Perfil, Autenticación, Foto opcional, Múltiples discapacidades y Menor/Familiar
# ---------------------------------------------------------------------------
class GuardianContact(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    relation: str = Field(default="Familiar / Tutor", max_length=40)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=120)


class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=40)
    email: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=6, max_length=128)
    disability_profile: AccessibilityProfile = Field(
        default=AccessibilityProfile.SILLA_DE_RUEDAS
    )
    disabilities: Optional[List[AccessibilityProfile]] = Field(default=None)
    # Foto opcional para usuarios regulares
    face_photo_base64: Optional[str] = Field(default=None)
    face_photo_filename: Optional[str] = Field(default=None)
    # Protección para menores de edad
    is_minor: bool = Field(default=False)
    guardian: Optional[GuardianContact] = Field(default=None)

    @model_validator(mode="after")
    def _sync_fields(self) -> "UserRegisterRequest":
        normalized = normalize_disabilities(self.disabilities, self.disability_profile)
        self.disabilities = normalized
        self.disability_profile = normalized[0]
        return self


class UserLoginRequest(BaseModel):
    identifier: str = Field(..., min_length=3, description="Nombre de usuario o correo vinculado")
    password: str = Field(..., min_length=1)


class UpdateDisabilityRequest(BaseModel):
    user_id: str
    disability_profile: AccessibilityProfile = Field(
        default=AccessibilityProfile.SILLA_DE_RUEDAS
    )
    disabilities: Optional[List[AccessibilityProfile]] = Field(default=None)

    @model_validator(mode="after")
    def _sync_fields(self) -> "UpdateDisabilityRequest":
        normalized = normalize_disabilities(self.disabilities, self.disability_profile)
        self.disabilities = normalized
        self.disability_profile = normalized[0]
        return self


class UpdateProfileRequest(BaseModel):
    user_id: str
    disabilities: Optional[List[AccessibilityProfile]] = None
    face_photo_base64: Optional[str] = None
    face_photo_filename: Optional[str] = None
    clear_photo: bool = False
    is_minor: Optional[bool] = None
    guardian: Optional[GuardianContact] = None


class UserProfileResponse(BaseModel):
    id: str
    username: str
    email: str
    disability_profile: AccessibilityProfile
    disability_label: str
    disabilities: List[AccessibilityProfile]
    disabilities_labels: List[str]
    face_photo_base64: Optional[str] = None
    face_photo_filename: Optional[str] = None
    is_minor: bool = False
    guardian: Optional[GuardianContact] = None
    is_volunteer: bool
    created_at: str


# ---------------------------------------------------------------------------
# Voluntarios (FOTO DE ROSTRO OBLIGATORIA + lista inicialmente vacía)
# ---------------------------------------------------------------------------
class VolunteerApplicationRequest(BaseModel):
    user_id: str
    face_photo_base64: str = Field(
        ...,
        min_length=20,
        description="Foto de rostro en base64 obligatoria para identificar al voluntario.",
    )
    face_photo_filename: str = Field(default="rostro_voluntario.jpg")
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
    face_photo_base64: str
    face_photo_filename: str
    zone: str
    availability: str
    support_notes: str
    registered_at: str


class VolunteerRequest(BaseModel):
    user_location: str = Field(default="Av. Universidad 400, Coyoacán")
    destination: str = Field(default="Clínica 19")
    profile: AccessibilityProfile = Field(default=AccessibilityProfile.SILLA_DE_RUEDAS)
    disabilities: Optional[List[AccessibilityProfile]] = Field(default=None)
    notes: str = Field(default="")


class VolunteerResponse(BaseModel):
    request_id: str
    status: str
    volunteer_name: Optional[str] = None
    volunteer_photo_base64: Optional[str] = None
    eta_minutes: Optional[int] = None
    message: str


# ---------------------------------------------------------------------------
# Protección de menores: ubicación en tiempo real + alerta de extravío sonora
# ---------------------------------------------------------------------------
class GuardianLocationShareRequest(BaseModel):
    user_id: Optional[str] = None
    username: str = Field(default="Menor Map Inclusive")
    guardian_name: str = Field(..., min_length=2)
    guardian_contact: str = Field(..., min_length=3)
    location_text: str = Field(default="Av. Universidad, Coyoacán, CDMX")
    destination: str = Field(default="Clínica 19 (UMF IMSS)")
    latitude: float = Field(default=19.3498)
    longitude: float = Field(default=-99.1617)
    status: str = Field(default="en_ruta")


class GuardianLocationShareResponse(BaseModel):
    share_id: str
    status: str
    guardian_name: str
    guardian_contact: str
    location_text: str
    latitude: float
    longitude: float
    shared_at: str
    message: str


class LostMinorAlertRequest(BaseModel):
    user_id: Optional[str] = None
    username: str = Field(default="Usuario menor de edad")
    guardian_name: str = Field(default="Familiar registrado")
    guardian_phone: str = Field(default="")
    guardian_email: str = Field(default="")
    location_text: str = Field(default="Av. Universidad, Coyoacán, CDMX")
    disabilities: List[AccessibilityProfile] = Field(
        default_factory=lambda: [AccessibilityProfile.SILLA_DE_RUEDAS]
    )


class LostMinorAlertResponse(BaseModel):
    alert_id: str
    status: str
    sound_alarm_triggered: bool
    guardian_notified: str
    location_text: str
    timestamp: str
    helper_message: str


# ---------------------------------------------------------------------------
# Emergencia SOS
# ---------------------------------------------------------------------------
class EmergencyAlertRequest(BaseModel):
    location: str = Field(default="Av. Universidad, Coyoacán, CDMX")
    profile: AccessibilityProfile = Field(default=AccessibilityProfile.SILLA_DE_RUEDAS)
    disabilities: Optional[List[AccessibilityProfile]] = None
    username: Optional[str] = None
    notes: str = Field(default="Solicitud de ayuda inmediata desde Map Inclusive")


class EmergencyAlertResponse(BaseModel):
    alert_id: str
    status: str
    timestamp: str
    nearest_emergency_clinic: str
    emergency_numbers: List[str]
    message: str
