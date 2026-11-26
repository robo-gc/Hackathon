"""Esquemas de datos para el backend de Map Inclusive (Equipo Apex soa)."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class AccessibilityProfile(str, Enum):
    """Perfiles de accesibilidad definidos en la Pantalla 1 del boceto."""

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


class EnvironmentCheckRequest(BaseModel):
    """Solicitud enviada desde Android (Pantalla 3) o script CLI."""

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
    """Respuesta completa consumida por la app Android cada 10 minutos."""

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


class IncidentCreateRequest(BaseModel):
    """Reporte ciudadano de incidencia enviado desde la Pantalla 4."""

    title: str = Field(..., min_length=3, description="Título corto, ej. 'Rampa bloqueada'")
    description: str = Field(
        default="",
        description="Descripción opcional del obstáculo o problema.",
    )
    location: str = Field(
        default="Av. Universidad, Coyoacán",
        description="Ubicación aproximada de la incidencia.",
    )
    profile: AccessibilityProfile = Field(
        default=AccessibilityProfile.SILLA_DE_RUEDAS,
        description="Perfil principalmente afectado.",
    )


class IncidentRecord(BaseModel):
    id: str
    title: str
    description: str
    location: str
    profile: AccessibilityProfile
    severity: RiskLevel
    ai_advice: str
    created_at: str


class ClinicInfo(BaseModel):
    id: str
    name: str
    address: str
    distance_text: str
    schedule: str
    accessible_entrance: bool
    latitude: float
    longitude: float


class VolunteerRequest(BaseModel):
    user_location: str = Field(default="Av. Universidad 400, Coyoacán")
    destination: str = Field(default="Clínica 19")
    profile: AccessibilityProfile = Field(default=AccessibilityProfile.SILLA_DE_RUEDAS)
    notes: str = Field(default="")


class VolunteerResponse(BaseModel):
    request_id: str
    status: str
    volunteer_name: str
    eta_minutes: int
    message: str
