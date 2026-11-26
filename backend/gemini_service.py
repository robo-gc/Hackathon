"""Servicio de integración con Google Gemini (Interactions API + Google Search Grounding).

Sigue las mejores prácticas del SDK oficial `google-genai >= 3.5.0`:
- Usa `client.interactions.create(...)` con el modelo `gemini-4-hydrogen`.
- Combina grounding con Google Search (`{"type": "google_search"}`) para obtener
  clima, bloqueos, transporte fuera de servicio e incidencias reales del entorno.
- Usa Structured Outputs (`response_format`) para devolver JSON validado por Pydantic
  directamente consumible por la aplicación Android.
- Mantiene caché de 10 minutos (600 s) y fallback claro sin conexión / sin API key.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from google import genai
from pydantic import BaseModel, Field

from models import (
    PROFILE_LABELS,
    AccessibilityProfile,
    EnvironmentCheckRequest,
    EnvironmentCheckResponse,
    GeminiEnvironmentPayload,
    IncidentRecord,
    RiskLevel,
    SourceCitation,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-4-hydrogen"
DEFAULT_CACHE_TTL_SECONDS = 600  # 10 minutos, según especificación de Map Inclusive

PROFILE_GUIDANCE: Dict[AccessibilityProfile, str] = {
    AccessibilityProfile.SILLA_DE_RUEDAS: (
        "Prioriza rampas funcionales, banquetas anchas sin escalones, elevadores de metro/transporte "
        "y desvía cualquier rampa bloqueada o encharcamiento."
    ),
    AccessibilityProfile.VISUAL: (
        "Prioriza cruces con semáforo sonoro, guías podotáctiles, avisos claros sobre obras "
        "o obstáculos a nivel de suelo y zonas bien iluminadas."
    ),
    AccessibilityProfile.AUDITIVO: (
        "Prioriza avisos visuales claros, alertas de tráfico o desvíos que requieran atención visual "
        "extra y señalización visible en estaciones de transporte."
    ),
    AccessibilityProfile.MOVILIDAD_REDUCIDA: (
        "Prioriza trayectos cortos con menor pendiente, zonas de descanso, accesos sin escaleras "
        "largas y transporte con acceso preferente."
    ),
    AccessibilityProfile.NEURODIVERGENTE: (
        "Prioriza rutas más tranquilas con menor sobrecarga sensorial (evitar marchas, obras ruidosas "
        "o aglomeraciones), instrucciones cortas, predecibles y paso a paso."
    ),
}


class IncidentClassification(BaseModel):
    severity: RiskLevel = Field(description="Severidad del obstáculo: bajo, medio o alto.")
    ai_advice: str = Field(
        description="Recomendación breve (máx. 140 caracteres) para quienes pasen por esa zona."
    )


class GeminiEnvironmentService:
    """Encapsula consultas a Gemini Interactions API con caché de 10 minutos."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        cache_ttl_seconds: Optional[int] = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        if self.api_key == "tu_api_key_aqui":
            self.api_key = ""
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.cache_ttl_seconds = (
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else int(os.getenv("ENVIRONMENT_CACHE_TTL_SECONDS", str(DEFAULT_CACHE_TTL_SECONDS)))
        )
        self._client: Optional[genai.Client] = (
            genai.Client(api_key=self.api_key) if self.api_key else None
        )
        self._cache: Dict[Tuple[str, str, str, int], Tuple[float, EnvironmentCheckResponse]] = {}

    @property
    def is_live_enabled(self) -> bool:
        return self._client is not None

    def clear_cache(self) -> None:
        self._cache.clear()

    def check_environment(
        self,
        req: EnvironmentCheckRequest,
        active_incidents: Optional[List[IncidentRecord]] = None,
    ) -> EnvironmentCheckResponse:
        """Consulta el entorno urbano actual y el destino final con actualización cada 10 min."""
        incidents = active_incidents or []
        cache_key = (
            req.origin.strip().lower(),
            req.destination.strip().lower(),
            req.profile.value,
            len(incidents),
        )

        now_mono = time.monotonic()
        if not req.force_refresh and cache_key in self._cache:
            cached_at, cached_resp = self._cache[cache_key]
            if now_mono - cached_at < self.cache_ttl_seconds:
                return cached_resp.model_copy(update={"from_cache": True})

        if not self._client:
            response = self._build_offline_demo_response(
                req=req,
                incidents=incidents,
                reason="Modo prueba local (configura GEMINI_API_KEY para datos web en vivo).",
            )
            self._cache[cache_key] = (now_mono, response)
            return response

        try:
            response = self._query_gemini_live(req, incidents)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fallo al consultar Gemini API, activando fallback: %s", exc)
            response = self._build_offline_demo_response(
                req=req,
                incidents=incidents,
                reason="Sin conexión con Gemini; mostrando estado preventivo en caché local.",
            )

        self._cache[cache_key] = (now_mono, response)
        return response

    def _query_gemini_live(
        self,
        req: EnvironmentCheckRequest,
        incidents: List[IncidentRecord],
    ) -> EnvironmentCheckResponse:
        assert self._client is not None

        profile_label = PROFILE_LABELS[req.profile]
        profile_rules = PROFILE_GUIDANCE[req.profile]
        now_iso = datetime.now(timezone.utc).isoformat()

        incidents_text = (
            "\n".join(
                f"- {inc.title} en {inc.location} (perfil: {inc.profile.value}, severidad: {inc.severity.value}): {inc.description}"
                for inc in incidents
            )
            if incidents
            else "Ninguna incidencia ciudadana activa registrada en la app."
        )

        coords_text = (
            f"Coordenadas aproximadas: lat={req.latitude}, lng={req.longitude}."
            if req.latitude is not None and req.longitude is not None
            else "Sin coordenadas GPS exactas."
        )

        system_instruction = (
            "Eres el asistente de accesibilidad y seguridad urbana de la app 'Map Inclusive' "
            "(Campus Coyoacán, Ciudad de México). "
            "Tu tarea es consultar información actual en internet sobre clima, bloqueos viales o "
            "peatonales, transporte público fuera de servicio e incidencias urbanas entre el origen "
            "y el destino, y traducirla en alertas claras, empáticas y concisas en español.\n"
            f"Regla de accesibilidad para el usuario actual ({profile_label}): {profile_rules}\n"
            "Devuelve únicamente JSON válido conforme al esquema solicitado. "
            "Si no encuentras bloqueos o fallas de transporte activas en este momento, indícalo con claridad."
        )

        user_prompt = (
            f"Fecha y hora actual (UTC): {now_iso}\n"
            f"Perfil del usuario: {profile_label}\n"
            f"Origen: {req.origin}\n"
            f"Destino: {req.destination}\n"
            f"{coords_text}\n"
            f"Reportes ciudadanos activos en Map Inclusive:\n{incidents_text}\n\n"
            "Busca información actualizada hoy sobre:\n"
            "1) Clima actual en la zona del origen y destino.\n"
            "2) Bloqueos viales, marchas, cierres peatonales u obras.\n"
            "3) Estaciones de Metro, Metrobús o rutas de transporte fuera de servicio.\n"
            "4) Recomendaciones concretas adaptadas al perfil de accesibilidad."
        )

        interaction = self._client.interactions.create(
            model=self.model,
            system_instruction=system_instruction,
            input=user_prompt,
            tools=[{"type": "google_search"}],
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": GeminiEnvironmentPayload.model_json_schema(),
            },
            generation_config={
                "thinking_level": "low",
            },
        )

        raw_json = interaction.output_text
        if not raw_json:
            raise RuntimeError("Gemini devolvió una respuesta vacía sin output_text.")

        payload = GeminiEnvironmentPayload.model_validate_json(raw_json)
        citations = self._extract_citations(interaction)

        return EnvironmentCheckResponse(
            origin=req.origin,
            destination=req.destination,
            profile=req.profile,
            profile_label=profile_label,
            status_mode="gemini_live",
            from_cache=False,
            model_used=self.model,
            updated_at=now_iso,
            next_refresh_minutes=max(1, self.cache_ttl_seconds // 60),
            banner_resumen=payload.banner_resumen,
            clima=payload.clima,
            bloqueos=payload.bloqueos,
            transporte_afectado=payload.transporte_afectado,
            incidencias_accesibilidad=payload.incidencias_accesibilidad,
            zonas_riesgo=payload.zonas_riesgo,
            recomendaciones_perfil=payload.recomendaciones_perfil,
            nivel_riesgo=payload.nivel_riesgo,
            fuentes=citations,
        )

    def classify_incident(
        self,
        title: str,
        description: str,
        location: str,
        profile: AccessibilityProfile,
    ) -> Tuple[RiskLevel, str]:
        """Evalúa severidad y recomendación corta para un nuevo reporte ciudadano."""
        if not self._client:
            lowered = f"{title} {description}".lower()
            if any(k in lowered for k in ("bloque", "cerrad", "peligr", "inund", "sin luz")):
                return (
                    RiskLevel.ALTO,
                    f"Evita {location}; usa ruta alterna accesible y solicita guía voluntaria si lo necesitas.",
                )
            return (
                RiskLevel.MEDIO,
                f"Precaución al transitar por {location}; incidencia registrada para la comunidad.",
            )

        try:
            interaction = self._client.interactions.create(
                model=self.model,
                system_instruction=(
                    "Clasifica la severidad de una incidencia urbana de accesibilidad para Map Inclusive "
                    "y da una recomendación breve en español (máx. 140 caracteres)."
                ),
                input=(
                    f"Incidencia: {title}\n"
                    f"Descripción: {description or 'Sin detalles adicionales'}\n"
                    f"Ubicación: {location}\n"
                    f"Perfil afectado: {PROFILE_LABELS[profile]}"
                ),
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": IncidentClassification.model_json_schema(),
                },
                generation_config={"thinking_level": "low"},
            )
            if interaction.output_text:
                parsed = IncidentClassification.model_validate_json(interaction.output_text)
                return parsed.severity, parsed.ai_advice
        except Exception as exc:  # noqa: BLE001
            logger.warning("No se pudo clasificar incidencia con Gemini: %s", exc)

        return (
            RiskLevel.MEDIO,
            f"Precaución cerca de {location}; reporte visible para usuarios de Map Inclusive.",
        )

    @staticmethod
    def _extract_citations(interaction: object) -> List[SourceCitation]:
        """Extrae enlaces de citación de los pasos devueltos por Interactions API."""
        citations: List[SourceCitation] = []
        seen_urls: set[str] = set()

        steps = getattr(interaction, "steps", None) or []
        for step in steps:
            step_type = getattr(step, "type", None)
            if step_type == "model_output":
                contents = getattr(step, "content", None) or []
                for item in contents:
                    annotations = getattr(item, "annotations", None) or []
                    for ann in annotations:
                        url = getattr(ann, "url", None) or (
                            ann.get("url") if isinstance(ann, dict) else None
                        )
                        title = getattr(ann, "title", None) or (
                            ann.get("title") if isinstance(ann, dict) else None
                        )
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            citations.append(SourceCitation(title=title or url, url=url))
            elif step_type == "google_search_result":
                results = getattr(step, "result", None) or []
                if isinstance(results, list):
                    for res in results:
                        url = getattr(res, "url", None) or (
                            res.get("url") if isinstance(res, dict) else None
                        )
                        title = getattr(res, "title", None) or (
                            res.get("title") if isinstance(res, dict) else None
                        )
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            citations.append(SourceCitation(title=title or url, url=url))

        return citations[:5]

    def _build_offline_demo_response(
        self,
        req: EnvironmentCheckRequest,
        incidents: List[IncidentRecord],
        reason: str,
    ) -> EnvironmentCheckResponse:
        """Respuesta preventiva para pruebas locales sin API key o sin internet."""
        now_iso = datetime.now(timezone.utc).isoformat()
        profile_label = PROFILE_LABELS[req.profile]

        incident_lines = [
            f"{inc.title} en {inc.location}" for inc in incidents
        ] or ["Rampa bloqueada reportada en esquina Av. Universidad (desvío activo)."]

        profile_tips: Dict[AccessibilityProfile, List[str]] = {
            AccessibilityProfile.SILLA_DE_RUEDAS: [
                "Usa la banqueta norte de Av. Universidad: cuenta con rampa disponible en 80 m.",
                "Evita el cruce secundario con obra reportada; ruta recalculada sin escalones.",
            ],
            AccessibilityProfile.VISUAL: [
                "Cruce peatonal principal con semáforo sonoro activo hacia Clínica 19.",
                "Atención a señalización temporal de mantenimiento a 120 m del destino.",
            ],
            AccessibilityProfile.AUDITIVO: [
                "Cruces con señalización luminosa visible en todo el trayecto.",
                "Revisa las alertas visuales en pantalla cada 10 minutos por posibles desvíos.",
            ],
            AccessibilityProfile.MOVILIDAD_REDUCIDA: [
                "Trayecto seleccionado con pendiente mínima y bancas de descanso a mitad de ruta.",
                "Acceso principal de Clínica 19 a nivel de calle sin escalones.",
            ],
            AccessibilityProfile.NEURODIVERGENTE: [
                "Ruta tranquila por calles secundarias iluminadas con menor ruido vehicular.",
                "Avisos simplificados paso a paso activos; evita zonas de alta concentración.",
            ],
        }

        has_high = any(inc.severity == RiskLevel.ALTO for inc in incidents)
        banner = (
            "Clima despejado · 1 alerta de rampa evitada en tu ruta"
            if incidents
            else "Clima despejado, sin bloqueos viales (modo demo)"
        )

        return EnvironmentCheckResponse(
            origin=req.origin,
            destination=req.destination,
            profile=req.profile,
            profile_label=profile_label,
            status_mode="offline_demo",
            from_cache=False,
            model_used=self.model,
            updated_at=now_iso,
            next_refresh_minutes=max(1, self.cache_ttl_seconds // 60),
            banner_resumen=banner,
            clima="Despejado, 22 °C en Coyoacán (dato preventivo local)",
            bloqueos=["Sin bloqueos mayores reportados en Av. Universidad."],
            transporte_afectado=["Línea 3 Metro Coyoacán operando con normalidad (dato demo)."],
            incidencias_accesibilidad=incident_lines,
            zonas_riesgo=[
                "Zona poco concurrida detectada en callejón lateral a 250 m (evitada en tu ruta).",
                reason,
            ],
            recomendaciones_perfil=profile_tips[req.profile],
            nivel_riesgo=RiskLevel.MEDIO if has_high else RiskLevel.BAJO,
            fuentes=[],
        )
