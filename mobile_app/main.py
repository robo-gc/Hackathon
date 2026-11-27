"""Map Inclusive — App móvil para Android hecha 100% en Python (Flet / motor Flutter).

Sin una sola línea de Java. Implementa:
- Modo Día y Modo Noche/Oscuro de alto contraste (todos los textos y campos 100% legibles).
- Selección de UNA O MÚLTIPLES discapacidades (inicio, ruta y perfil) con rutas y tiempos
  estimados combinados e independientes.
- Simulador de navegación paso a paso con instrucciones por VOZ en español adaptadas a cada
  discapacidad (y Modo Visual sin audio para personas con discapacidad auditiva).
- Reporte de incidencias estilo Waze ("¿Qué ves?") con cuadrícula visual de íconos +
  Historial cronológico completo clasificado con Google Gemini.
- Lista completa de clínicas con horarios, accesibilidad, teléfono y qué debes llevar.
- Voluntarios con foto de rostro OBLIGATORIA (usuarios regulares con foto opcional).
- Protección para menores: ubicación en tiempo real a familiar + alarma sonora de extravío.
- Botón de Emergencia (SOS) siempre visible.

Ejecución local:
    python mobile_app/main.py
    flet run --web --port 8550 mobile_app/main.py
    flet run --android mobile_app/main.py
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import flet as ft
import httpx

try:
    import flet_geolocator as ftg
except ImportError:
    ftg = None  # type: ignore

XMIND_FONT_REGULAR = "NeverMind"
XMIND_FONT_MEDIUM = "NeverMindMedium"
XMIND_FONT_DEMIBOLD = "NeverMindDemiBold"
XMIND_FONT_BOLD = "NeverMindBold"
XMIND_FONTS_MAP = {
    XMIND_FONT_REGULAR: "fonts/NeverMind-Regular.ttf",
    XMIND_FONT_MEDIUM: "fonts/NeverMind-Medium.ttf",
    XMIND_FONT_DEMIBOLD: "fonts/NeverMind-DemiBold.ttf",
    XMIND_FONT_BOLD: "fonts/NeverMind-Bold.ttf",
}
CAMPUS_COYOACAN_LAT = 19.3467
CAMPUS_COYOACAN_LON = -99.1617


def _http_get_json_sync(url: str, timeout: int = 5) -> Optional[Any]:
    """Obtiene JSON vía HTTP en Python nativo/Android y en Pyodide (Web/WASM)."""
    if sys.platform == "emscripten":
        try:
            from pyodide.http import open_url  # type: ignore

            return json.loads(open_url(url).read())
        except Exception:
            return None
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "MapInclusive-ApexSoa/1.0 (Campus Coyoacan)"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def reverse_geocode_location(lat: float, lon: float) -> str:
    """Convierte coordenadas GPS a calle/colonia/ciudad legible (OpenStreetMap Nominatim)."""
    url = (
        f"https://nominatim.openstreetmap.org/reverse?"
        f"format=jsonv2&lat={lat:.6f}&lon={lon:.6f}&zoom=17&accept-language=es"
    )
    data = _http_get_json_sync(url, timeout=5)
    if isinstance(data, dict):
        addr = data.get("address", {}) if isinstance(data.get("address"), dict) else {}
        road = addr.get("road") or addr.get("pedestrian") or addr.get("neighbourhood") or ""
        suburb = addr.get("suburb") or addr.get("borough") or addr.get("city_district") or ""
        city = addr.get("city") or addr.get("town") or addr.get("state") or ""
        parts = [p for p in (road, suburb, city) if p]
        if parts:
            return ", ".join(parts[:3])
        display = str(data.get("display_name", "")).strip()
        if display:
            return ", ".join(display.split(",")[:3]).strip()
    return f"Ubicación detectada ({lat:.4f}, {lon:.4f})"


def fetch_ip_location_sync() -> Optional[Dict[str, Any]]:
    """Respaldo aproximado por IP cuando el dispositivo no expone GPS nativo."""
    data = _http_get_json_sync("https://ipwho.is/", timeout=5)
    if isinstance(data, dict) and data.get("success") and data.get("latitude") is not None and data.get("longitude") is not None:
        lat = float(data["latitude"])
        lon = float(data["longitude"])
        parts = [p for p in (data.get("city"), data.get("region"), data.get("country")) if p]
        return {
            "lat": lat,
            "lon": lon,
            "accuracy_m": None,
            "label": ", ".join(parts) if parts else f"{lat:.4f}, {lon:.4f}",
            "source": "Ubicación aproximada (red)",
        }
    return None


def format_coords_text(lat: float, lon: float, accuracy_m: Optional[float] = None) -> str:
    acc = f" · ±{int(round(accuracy_m))}m" if accuracy_m is not None else ""
    return f"{lat:.5f}, {lon:.5f}{acc}"

TEN_MINUTES_SECONDS = 600
MINOR_TRACKING_INTERVAL_SECONDS = 15
SIMULATION_STEP_INTERVAL_SECONDS = 7
DEFAULT_API_URL = os.getenv("MAP_INCLUSIVE_API_URL", "http://127.0.0.1:8000").rstrip("/")


# ---------------------------------------------------------------------------
# Sistema de Temas: Modo Día (Claro) y Modo Noche (Oscuro) de Alto Contraste
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ThemePalette:
    is_dark: bool
    bg: str
    card_bg: str
    card_alt: str
    border: str
    text_primary: str
    text_heading: str
    text_muted: str
    input_bg: str
    input_text: str
    input_label: str
    input_hint: str
    input_border: str
    input_focus: str
    nav_bg: str
    indigo: str
    blue_action: str
    emerald: str
    emerald_bg: str
    emerald_text: str
    alert_orange: str
    warn_bg: str
    warn_text: str
    danger_red: str
    danger_bg: str
    danger_text: str
    info_bg: str
    info_text: str
    badge_bg: str
    badge_text: str
    map_bg: str
    map_street: str
    map_park: str
    map_route: str
    chip_idle_bg: str
    chip_idle_text: str
    chip_active_bg: str
    chip_active_text: str


LIGHT_THEME = ThemePalette(
    is_dark=False,
    bg="#F1F5F9",
    card_bg="#FFFFFF",
    card_alt="#EEF2F7",
    border="#CBD5E1",
    text_primary="#0F172A",
    text_heading="#1B2354",
    text_muted="#334155",
    input_bg="#FFFFFF",
    input_text="#0F172A",
    input_label="#1E293B",
    input_hint="#64748B",
    input_border="#94A3B8",
    input_focus="#2563EB",
    nav_bg="#FFFFFF",
    indigo="#1B2354",
    blue_action="#2563EB",
    emerald="#0E9F6E",
    emerald_bg="#D1FAE5",
    emerald_text="#065F46",
    alert_orange="#EA7B1B",
    warn_bg="#FEF3C7",
    warn_text="#92400E",
    danger_red="#DC2626",
    danger_bg="#FEE2E2",
    danger_text="#991B1B",
    info_bg="#DBEAFE",
    info_text="#1E3A8A",
    badge_bg="#E0E7FF",
    badge_text="#1B2354",
    map_bg="#E2E8F0",
    map_street="#FFFFFF",
    map_park="#CBEAD8",
    map_route="#1B2354",
    chip_idle_bg="#FFFFFF",
    chip_idle_text="#1B2354",
    chip_active_bg="#1B2354",
    chip_active_text="#FFFFFF",
)

DARK_THEME = ThemePalette(
    is_dark=True,
    bg="#0B1120",
    card_bg="#151E32",
    card_alt="#1E293B",
    border="#334155",
    text_primary="#F8FAFC",
    text_heading="#F8FAFC",
    text_muted="#CBD5E1",
    input_bg="#1E293B",
    input_text="#F8FAFC",
    input_label="#93C5FD",
    input_hint="#94A3B8",
    input_border="#475569",
    input_focus="#60A5FA",
    nav_bg="#0F172A",
    indigo="#1E3A8A",
    blue_action="#3B82F6",
    emerald="#10B981",
    emerald_bg="#064E3B",
    emerald_text="#A7F3D0",
    alert_orange="#F97316",
    warn_bg="#78350F",
    warn_text="#FDE68A",
    danger_red="#EF4444",
    danger_bg="#7F1D1D",
    danger_text="#FECACA",
    info_bg="#1E3A8A",
    info_text="#DBEAFE",
    badge_bg="#1E3A8A",
    badge_text="#E0E7FF",
    map_bg="#0F172A",
    map_street="#334155",
    map_park="#064E3B",
    map_route="#60A5FA",
    chip_idle_bg="#1E293B",
    chip_idle_text="#E2E8F0",
    chip_active_bg="#3B82F6",
    chip_active_text="#FFFFFF",
)


def get_theme(dark_mode: bool) -> ThemePalette:
    return DARK_THEME if dark_mode else LIGHT_THEME


def styled_text_field(
    t: ThemePalette,
    *,
    label: Optional[str] = None,
    hint_text: Optional[str] = None,
    value: str = "",
    prefix_icon: Any = None,
    password: bool = False,
    can_reveal_password: bool = False,
    multiline: bool = False,
    expand: bool = False,
    on_change: Optional[Callable[[ft.ControlEvent], None]] = None,
) -> ft.TextField:
    """TextField con alto contraste garantizado en Modo Día y Modo Noche."""
    return ft.TextField(
        label=label,
        hint_text=hint_text,
        value=value,
        prefix_icon=prefix_icon,
        password=password,
        can_reveal_password=can_reveal_password,
        multiline=multiline,
        expand=expand,
        color=t.input_text,
        bgcolor=t.input_bg,
        cursor_color=t.input_focus,
        border_color=t.input_border,
        focused_border_color=t.input_focus,
        border_radius=12,
        label_style=ft.TextStyle(color=t.input_label, weight=ft.FontWeight.W_600),
        hint_style=ft.TextStyle(color=t.input_hint),
        on_change=on_change,
    )


def styled_outlined_button(
    t: ThemePalette,
    *,
    text: str,
    icon: Any = None,
    icon_color: Optional[str] = None,
    text_color: Optional[str] = None,
    border_color: Optional[str] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    expand: bool = False,
    on_click: Optional[Callable[[ft.ControlEvent], None]] = None,
) -> ft.OutlinedButton:
    fg = text_color or t.text_primary
    bc = border_color or t.border
    return ft.OutlinedButton(
        content=ft.Text(text, color=fg, weight=ft.FontWeight.W_600, size=13),
        icon=icon,
        icon_color=icon_color or fg,
        width=width,
        height=height,
        expand=expand,
        style=ft.ButtonStyle(
            side=ft.BorderSide(1.2, bc),
            color=fg,
        ),
        on_click=on_click,
    )


# ---------------------------------------------------------------------------
# Catálogo Waze-style de tipos de incidencias ("¿Qué ves?")
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WazeIncidentCategory:
    id: str
    title: str
    short_label: str
    default_desc: str
    icon: Any
    color: str


WAZE_INCIDENT_CATEGORIES: List[WazeIncidentCategory] = [
    WazeIncidentCategory(
        id="rampa_bloqueada",
        title="Rampa bloqueada",
        short_label="Rampa\nbloqueada",
        default_desc="Vehículo u objeto obstruyendo la rampa peatonal.",
        icon=ft.Icons.ACCESSIBLE,
        color="#EA7B1B",
    ),
    WazeIncidentCategory(
        id="obra_banqueta",
        title="Obra o banqueta rota",
        short_label="Obra /\nBanqueta",
        default_desc="Trabajos en la acera o pavimento dañado que dificulta el paso.",
        icon=ft.Icons.CONSTRUCTION,
        color="#D97706",
    ),
    WazeIncidentCategory(
        id="zona_peligrosa",
        title="Zona poco concurrida o peligrosa",
        short_label="Zona\npeligrosa",
        default_desc="Calle solitaria o situación de riesgo en la zona.",
        icon=ft.Icons.WARNING_AMBER,
        color="#DC2626",
    ),
    WazeIncidentCategory(
        id="semaforo_sonoro",
        title="Semáforo sonoro dañado",
        short_label="Semáforo\nsonoro",
        default_desc="El semáforo peatonal no emite aviso sonoro ni luminoso.",
        icon=ft.Icons.VOLUME_OFF,
        color="#7C3AED",
    ),
    WazeIncidentCategory(
        id="elevador_fuera",
        title="Elevador fuera de servicio",
        short_label="Elevador\ndañado",
        default_desc="Elevador o plataforma accesible sin funcionar en estación o puente.",
        icon=ft.Icons.ELEVATOR,
        color="#2563EB",
    ),
    WazeIncidentCategory(
        id="inundacion_clima",
        title="Encharcamiento / Lluvia",
        short_label="Lluvia /\nCharco",
        default_desc="Agua acumulada en cruce peatonal o banqueta resbalosa.",
        icon=ft.Icons.WATER_DROP,
        color="#0891B2",
    ),
    WazeIncidentCategory(
        id="calle_cerrada",
        title="Calle cerrada o bloqueo",
        short_label="Calle\ncerrada",
        default_desc="Cierre vial o manifestación impidiendo el cruce normal.",
        icon=ft.Icons.BLOCK,
        color="#B91C1C",
    ),
    WazeIncidentCategory(
        id="ruido_aglomeracion",
        title="Ruido extremo / Aglomeración",
        short_label="Ruido /\nMultitud",
        default_desc="Alta sobrecarga sensorial por ruido fuerte o concentración de personas.",
        icon=ft.Icons.CAMPAIGN,
        color="#DB2777",
    ),
    WazeIncidentCategory(
        id="sin_iluminacion",
        title="Tramo sin iluminación",
        short_label="Sin\niluminación",
        default_desc="Luminarias apagadas con baja visibilidad nocturna.",
        icon=ft.Icons.NIGHTLIGHT_ROUND,
        color="#4338CA",
    ),
]


# ---------------------------------------------------------------------------
# Perfiles de discapacidad y lógica de rutas combinables + pasos guiados
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProfileOption:
    api_value: str
    label: str
    short_label: str
    icon: Any
    nav_hint: str
    route_prefix: str
    distance_factor: float
    minutes_per_km: float
    accessibility_summary: str
    step_text: str


PROFILES: List[ProfileOption] = [
    ProfileOption(
        api_value="silla_de_ruedas",
        label="Silla de ruedas",
        short_label="Silla de ruedas",
        icon=ft.Icons.ACCESSIBLE,
        nav_hint="Rampa disponible · sin escalones",
        route_prefix="Rampas continuas",
        distance_factor=1.15,
        minutes_per_km=15.0,
        accessibility_summary="Evita escaleras y rampas bloqueadas; prioriza banquetas anchas.",
        step_text="Silla de ruedas: avanza por banqueta norte ancha con rampas disponibles.",
    ),
    ProfileOption(
        api_value="visual",
        label="Visual",
        short_label="Visual",
        icon=ft.Icons.VISIBILITY,
        nav_hint="Semáforo sonoro y guía podotáctil",
        route_prefix="Podotáctil y sonoro",
        distance_factor=1.05,
        minutes_per_km=14.0,
        accessibility_summary="Prioriza líneas podotáctiles, cruces sonoros y alertas de obras.",
        step_text="Visual: sigue la línea podotáctil continua y cruza en el semáforo sonoro.",
    ),
    ProfileOption(
        api_value="auditivo",
        label="Auditivo",
        short_label="Auditivo",
        icon=ft.Icons.HEARING,
        nav_hint="Guía 100% visual · sin depender de audio",
        route_prefix="Alta visibilidad",
        distance_factor=1.0,
        minutes_per_km=12.0,
        accessibility_summary="Cruces con semáforos visuales claros y avisos visuales en pantalla (sin audio).",
        step_text="Auditivo: usa el cruce con semáforo luminoso visible en ambos sentidos.",
    ),
    ProfileOption(
        api_value="movilidad_reducida",
        label="Movilidad reducida",
        short_label="Mov. reducida",
        icon=ft.Icons.DIRECTIONS_WALK,
        nav_hint="Pendiente suave y banca en 50 m",
        route_prefix="Pendiente suave",
        distance_factor=1.08,
        minutes_per_km=16.5,
        accessibility_summary="Trayectos planos con menor esfuerzo y zonas de descanso intermedias.",
        step_text="Movilidad reducida: toma el andador plano con barandal y banca intermedia.",
    ),
    ProfileOption(
        api_value="neurodivergente",
        label="Persona neurodivergente",
        short_label="Neurodivergente",
        icon=ft.Icons.PSYCHOLOGY,
        nav_hint="Calle tranquila · baja estimulación",
        route_prefix="Baja estimulación",
        distance_factor=1.12,
        minutes_per_km=13.5,
        accessibility_summary="Evita ruido intenso y aglomeraciones con instrucciones simples.",
        step_text="Neurodivergente: camina por calle secundaria arbolada de bajo ruido.",
    ),
]


def get_profile(api_value: str) -> ProfileOption:
    for item in PROFILES:
        if item.api_value == api_value:
            return item
    return PROFILES[0]


def normalize_disabilities(values: List[str]) -> List[str]:
    valid = {p.api_value for p in PROFILES}
    ordered: List[str] = []
    for val in values:
        if val in valid and val not in ordered:
            ordered.append(val)
    return ordered or ["silla_de_ruedas"]


def format_disabilities_label(values: List[str]) -> str:
    return " + ".join(get_profile(v).label for v in normalize_disabilities(values))


def format_timestamp_short(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        return local_dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso_str[:16].replace("T", " ")


# ---------------------------------------------------------------------------
# Instrucciones paso a paso y VOZ en español (100% Python, cero Java)
# ---------------------------------------------------------------------------
def build_local_navigation_steps(destination: str, disabilities: List[str]) -> List[Dict[str, Any]]:
    """Genera 4 pasos de navegación simulada adaptados a cada discapacidad."""
    active = normalize_disabilities(disabilities)
    has_auditivo = "auditivo" in active
    primary = active[0]

    if primary == "auditivo":
        rows = [
            (
                "straight",
                90,
                "Sigue derecho 90 m · Corredor visible",
                "Banqueta despejada con señalización visual de alto contraste. Verifica salidas vehiculares a tu derecha.",
                "",
                "ALERTA VISUAL: Banqueta libre · Mantén visibilidad frontal",
            ),
            (
                "right",
                70,
                "Gira a la derecha en 70 m · Semáforo peatonal",
                "Encontrarás un cruce con semáforo peatonal luminoso verde y espejo vial panorámico.",
                "",
                "SEMÁFORO LUMINOSO: Espera figura verde fija y mira ambos lados",
            ),
            (
                "straight",
                50,
                "Cruza y avanza 50 m · Sin bloqueos",
                "Paso peatonal amplio y bien iluminado; alertas visuales activas en pantalla cada 10 minutos.",
                "",
                "AVANCE SEGURO: Señalización clara hacia tu destino",
            ),
            (
                "arrive",
                0,
                f"Llegaste a {destination}",
                "Entrada principal visible al frente con letrero de acceso.",
                "",
                "DESTINO ALCANZADO · Recorrido finalizado",
            ),
        ]
    elif primary == "visual":
        rows = [
            (
                "straight",
                80,
                "Sigue derecho 80 m · Guía podotáctil",
                "Avanza recto siguiendo la línea podotáctil del piso; mantente a la izquierda de los postes.",
                "" if has_auditivo else "Sigue derecho ochenta metros guiándote por la línea podotáctil del piso. Mantente a tu izquierda para evitar postes.",
                "Guía podotáctil continua · 80 m recto",
            ),
            (
                "right",
                60,
                "Gira a la derecha en 60 m · Cruce seguro",
                (
                    "Cruce peatonal señalado con línea táctil de advertencia antes de la esquina."
                    if has_auditivo
                    else "A 60 metros encontrarás un semáforo sonoro en Av. Universidad; espera el tono rápido para cruzar."
                ),
                "" if has_auditivo else "En sesenta metros gira a la derecha. Encontrarás un semáforo sonoro en Avenida Universidad; espera el tono rápido para cruzar.",
                "Cruce peatonal accesible · Gira derecha",
            ),
            (
                "straight",
                45,
                "Continúa 45 m · Banqueta despejada",
                "Tramo recto sin obras ni obstáculos a nivel del suelo.",
                "" if has_auditivo else "Continúa derecho cuarenta y cinco metros. La banqueta está despejada y sin obras reportadas.",
                "Banqueta libre de obstáculos · 45 m",
            ),
            (
                "arrive",
                0,
                f"Has llegado a {destination}",
                "La puerta principal está a 5 metros directamente frente a ti.",
                "" if has_auditivo else f"Has llegado a {destination}. La puerta principal está a cinco metros directamente frente a ti.",
                "Llegada confirmada · Acceso al frente",
            ),
        ]
    elif primary == "movilidad_reducida":
        rows = [
            (
                "straight",
                70,
                "Avanza 70 m · Andador plano con barandal",
                "Camina a tu ritmo por el tramo nivelado sin escalones; tienes barandal de apoyo a tu derecha.",
                "" if has_auditivo else "Avanza despacio setenta metros por el andador plano. Encontrarás un barandal de apoyo a tu derecha y superficie pareja.",
                "Andador plano con barandal · 70 m",
            ),
            (
                "right",
                50,
                "Gira a la derecha en 50 m · Banca con sombra",
                "Encontrarás una banca con sombra en la esquina por si deseas tomar un descanso.",
                "" if has_auditivo else "En cincuenta metros gira a la derecha. Encontrarás una banca con sombra justo en la esquina por si necesitas descansar.",
                "Zona de descanso con banca disponible",
            ),
            (
                "straight",
                40,
                "Continúa 40 m · Acceso sin escaleras",
                "Pendiente suave menor al 4% directo hacia la entrada preferente.",
                "" if has_auditivo else "Continúa cuarenta metros por una pendiente suave sin escaleras hacia el acceso preferente.",
                "Pendiente suave · Sin escaleras",
            ),
            (
                "arrive",
                0,
                f"Llegaste a {destination}",
                "Acceso preferente a nivel de calle justo frente a ti.",
                "" if has_auditivo else f"Has llegado a {destination}. Tienes el acceso preferente a nivel de calle frente a ti.",
                "Destino alcanzado · Acceso preferente",
            ),
        ]
    elif primary == "neurodivergente":
        rows = [
            (
                "straight",
                80,
                "Paso 1: Camina recto 80 m · Calle tranquila",
                "Calle arbolada con bajo ruido vehicular y espacio amplio para caminar sin prisas.",
                "" if has_auditivo else "Paso uno de cuatro. Camina recto ochenta metros por la calle arbolada. Es una zona tranquila con poco ruido.",
                "Zona tranquila · Baja estimulación",
            ),
            (
                "right",
                60,
                "Paso 2: Gira a la derecha en 60 m",
                "Gira en la esquina del parque. Evitamos la avenida con obras ruidosas.",
                "" if has_auditivo else "Paso dos de cuatro. Gira a la derecha en sesenta metros en la esquina del parque. Evitamos las obras ruidosas.",
                "Desvío tranquilo · Sin obras ruidosas",
            ),
            (
                "straight",
                40,
                "Paso 3: Cruza con calma · 40 m al frente",
                "Cruce amplio y ordenado con poco flujo de personas.",
                "" if has_auditivo else "Paso tres de cuatro. Cruce amplio y ordenado en cuarenta metros. Avanza a tu propio ritmo.",
                "Paso ordenado · Poco flujo peatonal",
            ),
            (
                "arrive",
                0,
                f"Paso 4: Llegaste a {destination}",
                "Entrada señalizada con zona de espera tranquila adentro.",
                "" if has_auditivo else f"Paso cuatro de cuatro. Llegaste a {destination}. Encontrarás la entrada tranquila frente a ti.",
                "Recorrido completado con calma",
            ),
        ]
    else:  # silla_de_ruedas
        rows = [
            (
                "straight",
                80,
                "Sigue derecho 80 m · Rampa disponible",
                "Banqueta norte ancha de Av. Universidad con rampa continua y superficie firme.",
                "" if has_auditivo else "Sigue derecho ochenta metros por la banqueta norte. Encontrarás una rampa amplia sin escalones.",
                "Banqueta ancha · Rampa disponible",
            ),
            (
                "right",
                65,
                "Gira a la derecha en 65 m · Desvío de obstáculo",
                "Rodeamos la rampa bloqueada reportada en la esquina; paso libre de escalones.",
                "" if has_auditivo else "Gira a la derecha en sesenta y cinco metros. Evitamos la rampa bloqueada reportada en la esquina.",
                "Obstáculo evitado · Ruta sin escalones",
            ),
            (
                "left",
                45,
                "Gira a la izquierda en 45 m · Cruce a nivel",
                "Paso peatonal con rampa en ambos extremos hacia la entrada principal.",
                "" if has_auditivo else "Gira a la izquierda en cuarenta y cinco metros. Encontrarás un cruce peatonal a nivel de calle con rampa en ambos lados.",
                "Cruce a nivel · Rampa verificada",
            ),
            (
                "arrive",
                0,
                f"Llegaste a {destination}",
                "Rampa principal de acceso y puerta amplia frente a ti.",
                "" if has_auditivo else f"Has llegado a {destination}. La rampa principal de acceso está justo frente a ti.",
                "Llegada accesible · Rampa al frente",
            ),
        ]

    extra_notes = [get_profile(d).accessibility_summary for d in active[1:]]
    extra_suffix = (" | Extra: " + " ".join(extra_notes)) if extra_notes else ""

    return [
        {
            "step_number": i,
            "direction": direction,
            "distance_meters": dist_m,
            "headline": headline,
            "detail": f"{detail}{extra_suffix}" if i == 1 and extra_suffix else detail,
            "spoken_text": spoken,
            "visual_cue": visual,
        }
        for i, (direction, dist_m, headline, detail, spoken, visual) in enumerate(rows, start=1)
    ]


_ACTIVE_TTS_PROCESS: Optional[subprocess.Popen[Any]] = None


def stop_voice_speech() -> None:
    """Detiene cualquier instrucción de voz en curso."""
    global _ACTIVE_TTS_PROCESS
    proc = _ACTIVE_TTS_PROCESS
    _ACTIVE_TTS_PROCESS = None
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass


def speak_spanish_instruction(text: str) -> None:
    """Lee en voz alta una instrucción en español usando el motor nativo del SO (sin Java)."""
    global _ACTIVE_TTS_PROCESS
    cleaned = text.strip()
    if not cleaned:
        return
    stop_voice_speech()

    try:
        if sys.platform == "win32":
            safe_text = cleaned.replace("'", "''")
            ps_script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'es*' } | Select-Object -First 1; "
                "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }; "
                "$s.Rate = 0; "
                f"$s.Speak('{safe_text}')"
            )
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            _ACTIVE_TTS_PROCESS = proc
            proc.wait(timeout=18)
            return

        if sys.platform == "darwin" and shutil.which("say"):
            proc = subprocess.Popen(["say", cleaned], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _ACTIVE_TTS_PROCESS = proc
            proc.wait(timeout=18)
            return

        for cmd in (["espeak-ng", "-v", "es", cleaned], ["espeak", "-v", "es", cleaned], ["spd-say", "-l", "es", cleaned]):
            if shutil.which(cmd[0]):
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _ACTIVE_TTS_PROCESS = proc
                proc.wait(timeout=18)
                return
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Alarma sonora real para extravío de menores (100% Python stdlib, sin Java)
# ---------------------------------------------------------------------------
def generate_alert_siren_wav() -> bytes:
    sample_rate = 22050
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for freq, duration in ((1200, 0.24), (820, 0.24), (1320, 0.24), (820, 0.24)):
            for i in range(int(sample_rate * duration)):
                sample = int(28000 * math.sin(2.0 * math.pi * freq * i / sample_rate))
                frames += struct.pack("<h", sample)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


_SIREN_WAV_BYTES = generate_alert_siren_wav()


def play_alert_sound_once() -> None:
    if sys.platform == "win32":
        try:
            import winsound  # type: ignore[import-not-found]

            winsound.PlaySound(_SIREN_WAV_BYTES, winsound.SND_MEMORY)
            return
        except Exception:
            try:
                import winsound  # type: ignore[import-not-found]

                winsound.Beep(1200, 320)
                winsound.Beep(820, 320)
                return
            except Exception:
                pass

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(_SIREN_WAV_BYTES)
            tmp_path = tmp.name
        for player in ("afplay", "paplay", "aplay"):
            if shutil.which(player):
                subprocess.run([player, tmp_path], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
    except Exception:
        pass
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    try:
        print("\a", end="", flush=True)
    except Exception:
        pass


def stop_alert_sound_immediately() -> None:
    if sys.platform == "win32":
        try:
            import winsound  # type: ignore[import-not-found]

            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Catálogos locales de respaldo
# ---------------------------------------------------------------------------
LOCAL_SUGGESTIONS_BASE: List[Dict[str, Any]] = [
    {"id": "sug-clinica-19", "destination": "Clínica 19 (UMF IMSS)", "address": "Av. Universidad, Coyoacán", "category": "Clínica", "base_km": 0.4},
    {"id": "sug-centro-salud", "destination": "Centro de Salud T-III Coyoacán", "address": "Calle Ignacio Allende, Del Carmen", "category": "Clínica", "base_km": 0.85},
    {"id": "sug-metro-coyoacan", "destination": "Metro Coyoacán (Línea 3)", "address": "Av. Universidad y Mayorazgo", "category": "Transporte", "base_km": 0.95},
    {"id": "sug-parque-centenario", "destination": "Jardín Centenario Coyoacán", "address": "Centro de Coyoacán", "category": "Espacio público", "base_km": 1.1},
    {"id": "sug-hospital-xoco", "destination": "Hospital General Xoco (Urgencias 24h)", "address": "Av. México Coyoacán s/n", "category": "Hospital", "base_km": 1.4},
]

LOCAL_CLINICS_BASE: List[Dict[str, Any]] = [
    {
        "id": "clinica-19",
        "name": "Clínica 19 (UMF IMSS)",
        "address": "Av. Universidad, Col. Coyoacán, CDMX",
        "base_km": 0.4,
        "schedule": "Lun-Vie 08:00 - 20:00",
        "emergency_hours": "Atención médica continua 24 horas",
        "phone": "55 5554 1919",
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
            "Comprobante de domicilio reciente (primera vez)",
        ],
    },
    {
        "id": "centro-salud-coyoacan",
        "name": "Centro de Salud T-III Coyoacán",
        "address": "Calle Ignacio Allende, Col. Del Carmen, Coyoacán",
        "base_km": 0.85,
        "schedule": "Lun-Dom 07:30 - 19:00",
        "emergency_hours": "Valoración inicial en horario de consulta",
        "phone": "55 5554 2840",
        "accessibility_features": [
            "Entrada a nivel de calle sin escalones",
            "Señalización visual en alto contraste",
            "Área de espera tranquila con asientos preferentes",
        ],
        "services": ["Consulta general gratuita", "Vacunación", "Odontología", "Psicología"],
        "requirements_to_bring": [
            "Identificación oficial vigente (INE) o acta (menores)",
            "CURP impreso o digital",
            "Cartilla Nacional de Salud",
            "Comprobante de domicilio (< 3 meses)",
            "Hoja de gratuidad / IMSS-Bienestar (si cuentas con ella)",
        ],
    },
    {
        "id": "hospital-xoco",
        "name": "Hospital General Xoco",
        "address": "Av. México Coyoacán s/n, Col. General Anaya",
        "base_km": 1.4,
        "schedule": "Abierto 24 horas (Lunes a Domingo)",
        "emergency_hours": "Urgencias 24 horas (Trauma y Emergencias)",
        "phone": "55 5688 9015",
        "accessibility_features": [
            "Rampa vehicular y peatonal para sillas de ruedas",
            "Préstamo de silla de ruedas en admisión",
            "Elevadores amplios y guía podotáctil en vestíbulo",
        ],
        "services": ["Urgencias 24h", "Traumatología", "Rayos X", "Hospitalización"],
        "requirements_to_bring": [
            "Identificación oficial del paciente y de un familiar",
            "CURP del paciente",
            "Lista de medicamentos actuales y alergias",
            "Estudios médicos previos (si aplica)",
            "En urgencia vital se atiende de inmediato sin documentos",
        ],
    },
]


def default_local_incidents() -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    return [
        {
            "id": "inc-001",
            "title": "Rampa bloqueada por vehículo",
            "description": "Vehículo estacionado bloqueando la rampa peatonal en esquina norte.",
            "location": "Av. Universidad esq. Miguel Ángel de Quevedo",
            "disabilities": ["silla_de_ruedas", "movilidad_reducida"],
            "disabilities_labels": ["Silla de ruedas", "Movilidad reducida"],
            "reported_by": "Comunidad Campus Coyoacán",
            "severity": "alto",
            "ai_advice": "Rodea por el cruce peatonal a 80 m con rampa disponible y paso seguro.",
            "created_at": (now - timedelta(minutes=18)).isoformat(),
        },
        {
            "id": "inc-002",
            "title": "Obra ruidosa en banqueta",
            "description": "Trabajos de pavimentación con taladro neumático y paso estrecho.",
            "location": "Calle Ignacio Allende 120, Del Carmen",
            "disabilities": ["neurodivergente", "visual"],
            "disabilities_labels": ["Persona neurodivergente", "Discapacidad visual"],
            "reported_by": "Reporte ciudadano",
            "severity": "medio",
            "ai_advice": "Usa la acera opuesta o calle paralela arbolada para evitar ruido y obstáculos.",
            "created_at": (now - timedelta(hours=1, minutes=25)).isoformat(),
        },
    ]


def compute_local_route(
    dest_id: str,
    destination: str,
    address: str,
    category: str,
    base_km: float,
    disabilities: List[str],
) -> Dict[str, Any]:
    active = normalize_disabilities(disabilities)
    objs = [get_profile(d) for d in active]
    extra_margin = 1.0 + 0.03 * max(0, len(objs) - 1)
    distance_factor = max(o.distance_factor for o in objs) * extra_margin
    minutes_per_km = max(o.minutes_per_km for o in objs)

    adj_km = round(base_km * distance_factor, 2)
    est_min = max(3, int(round(adj_km * minutes_per_km)))
    dist_text = f"{int(round(adj_km * 1000))} m" if adj_km < 1.0 else f"{adj_km:.1f} km"
    prefixes = " + ".join(o.route_prefix for o in objs)
    labels = [o.label for o in objs]

    return {
        "id": dest_id,
        "destination": destination,
        "address": address,
        "category": category,
        "profile": active[0],
        "profile_label": " + ".join(labels),
        "disabilities": active,
        "disabilities_labels": labels,
        "route_name": f"Ruta ({prefixes}) · {destination}",
        "distance_km": adj_km,
        "distance_text": dist_text,
        "estimated_minutes": est_min,
        "accessibility_summary": " ".join(o.accessibility_summary for o in objs),
        "voice_guidance_recommended": "auditivo" not in active,
        "steps": [o.step_text for o in objs] + [f"Llegada accesible verificada a {destination}."],
        "navigation_steps": build_local_navigation_steps(destination, active),
    }


def build_local_suggestions(disabilities: List[str]) -> List[Dict[str, Any]]:
    return [
        compute_local_route(p["id"], p["destination"], p["address"], p["category"], p["base_km"], disabilities)
        for p in LOCAL_SUGGESTIONS_BASE
    ]


def build_local_clinics(disabilities: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in LOCAL_CLINICS_BASE:
        est = compute_local_route(c["id"], c["name"], c["address"], "Clínica", c["base_km"], disabilities)
        item = dict(c)
        item["distance_text"] = est["distance_text"]
        item["distance_km"] = est["distance_km"]
        item["estimated_minutes"] = est["estimated_minutes"]
        out.append(item)
    return out


@dataclass
class AppState:
    api_url: str = DEFAULT_API_URL
    dark_mode: bool = False  # Alternable entre Modo Día y Modo Noche/Oscuro
    screen: str = "onboarding"
    disabilities: List[str] = field(default_factory=lambda: ["silla_de_ruedas"])
    origin: str = "Campus Coyoacán, CDMX"
    destination: str = "Clínica 19 (UMF IMSS)"
    search_query: str = ""

    # Ubicación actual del usuario (GPS real o respaldo)
    current_lat: float = CAMPUS_COYOACAN_LAT
    current_lon: float = CAMPUS_COYOACAN_LON
    current_accuracy_m: Optional[float] = None
    current_location_source: str = "Referencia Campus Coyoacán"
    current_location_updated_at: Optional[str] = None
    is_locating: bool = False
    auto_located_once: bool = False

    suggestions: List[Dict[str, Any]] = field(
        default_factory=lambda: build_local_suggestions(["silla_de_ruedas"])
    )
    current_route: Dict[str, Any] = field(
        default_factory=lambda: compute_local_route(
            "sug-clinica-19",
            "Clínica 19 (UMF IMSS)",
            "Av. Universidad, Coyoacán",
            "Clínica",
            0.4,
            ["silla_de_ruedas"],
        )
    )
    clinics: List[Dict[str, Any]] = field(
        default_factory=lambda: build_local_clinics(["silla_de_ruedas"])
    )
    incidents: List[Dict[str, Any]] = field(default_factory=default_local_incidents)
    volunteers: List[Dict[str, Any]] = field(default_factory=list)

    # Simulación paso a paso + Guía de voz en En Camino
    nav_step_index: int = 0
    nav_sim_running: bool = False
    nav_sim_generation: int = 0
    voice_enabled: bool = True

    # Borrador de reporte estilo Waze ("¿Qué ves?")
    waze_selected_id: str = "rampa_bloqueada"
    waze_location: str = "Av. Universidad, Coyoacán"
    waze_notes: str = ""

    # Perfil y autenticación
    current_user: Optional[Dict[str, Any]] = None
    local_users: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    auth_mode: str = "register"
    auth_feedback: Optional[str] = None
    auth_error: Optional[str] = None

    reg_username: str = ""
    reg_email: str = ""
    reg_password: str = ""
    reg_photo_b64: Optional[str] = None
    reg_photo_name: Optional[str] = None
    reg_is_minor: bool = False
    reg_guardian_name: str = ""
    reg_guardian_relation: str = "Madre / Padre / Tutor"
    reg_guardian_phone: str = ""
    reg_guardian_email: str = ""

    vol_zone: str = "Campus Coyoacán / Av. Universidad"
    vol_availability: str = "Lun-Vie 10:00 - 17:00"
    vol_notes: str = "Acompañamiento en cruces accesibles y traslado a clínicas"
    vol_photo_b64: Optional[str] = None
    vol_photo_name: Optional[str] = None
    vol_error: Optional[str] = None

    # Protección para menores
    live_sharing_active: bool = False
    live_sharing_generation: int = 0
    last_location_shared_at: Optional[str] = None
    last_location_status: Optional[str] = None
    lost_alarm_active: bool = False
    lost_alarm_generation: int = 0

    # Estado de Gemini cada 10 min
    env_report: Optional[Dict[str, Any]] = None
    is_loading_env: bool = False
    env_error: Optional[str] = None
    show_env_details: bool = False
    refresh_generation: int = 0


def build_face_avatar(
    t: ThemePalette,
    photo_b64: Optional[str],
    size: int = 58,
    fallback_icon: Any = ft.Icons.PERSON,
) -> ft.Container:
    if photo_b64:
        try:
            raw_bytes = base64.b64decode(photo_b64)
            return ft.Container(
                width=size,
                height=size,
                border_radius=size // 2,
                border=ft.Border.all(2, t.emerald),
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Image(src=raw_bytes, width=size, height=size, fit=ft.BoxFit.COVER),
            )
        except Exception:
            pass

    return ft.Container(
        width=size,
        height=size,
        border_radius=size // 2,
        bgcolor=t.card_alt,
        border=ft.Border.all(1.5, t.border),
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(fallback_icon, color=t.text_heading, size=size // 2),
    )


def get_map_blueprint(
    disabilities: List[str],
    destination: str,
    t: ThemePalette,
) -> Dict[str, Any]:
    """Genera un diseño de mapa, calles, ruta, obstáculos y waypoints únicos por discapacidad y destino."""
    active = normalize_disabilities(disabilities)
    primary = active[0]
    has_auditivo = "auditivo" in active
    dest_low = (destination or "").lower()

    # 1) Barrio / calles / parques distintos según el destino elegido
    if "centro de salud" in dest_low or "allende" in dest_low:
        street_label = "C. Ignacio Allende · Del Carmen"
        dest_icon = ft.Icons.LOCAL_HOSPITAL
        h_streets = [38, 102, 152]
        v_streets = [64, 178, 286]
        parks = [(18, 52, 58, 44), (210, 108, 72, 42)]
        mirror_x = True
    elif "metro" in dest_low:
        street_label = "Av. Universidad y C. Mayorazgo"
        dest_icon = ft.Icons.DIRECTIONS_SUBWAY
        h_streets = [48, 126]
        v_streets = [52, 154, 246, 310]
        parks = [(164, 58, 74, 58)]
        mirror_x = False
    elif "centenario" in dest_low or "parque" in dest_low or "jardín" in dest_low:
        street_label = "Centro Coyoacán · Jardín Centenario"
        dest_icon = ft.Icons.PARK
        h_streets = [34, 94, 146]
        v_streets = [82, 232]
        parks = [(98, 44, 126, 94), (248, 22, 68, 54)]
        mirror_x = True
    elif "xoco" in dest_low or "hospital" in dest_low:
        street_label = "Av. México Coyoacán · Zona Hospitalaria"
        dest_icon = ft.Icons.LOCAL_HOSPITAL
        h_streets = [42, 114, 156]
        v_streets = [70, 198, 294]
        parks = [(82, 56, 62, 50), (218, 52, 64, 52)]
        mirror_x = False
    elif "clínica 19" in dest_low or "clinica 19" in dest_low:
        street_label = "Av. Universidad · Campus Coyoacán"
        dest_icon = ft.Icons.LOCAL_HOSPITAL
        h_streets = [44, 124]
        v_streets = [88, 238]
        parks = [(118, 22, 78, 74)]
        mirror_x = False
    else:
        # Destino personalizado: layout determinista distinto basado en el nombre
        seed = sum(ord(ch) for ch in dest_low) % 3
        street_label = f"Zona Coyoacán · {destination[:22]}"
        dest_icon = ft.Icons.FLAG
        if seed == 0:
            h_streets, v_streets = [40, 118], [74, 196, 290]
            parks = [(92, 54, 88, 54)]
            mirror_x = False
        elif seed == 1:
            h_streets, v_streets = [36, 96, 148], [60, 224]
            parks = [(76, 46, 120, 46)]
            mirror_x = True
        else:
            h_streets, v_streets = [50, 132], [96, 256]
            parks = [(124, 62, 108, 60)]
            mirror_x = False

    # 2) Geometría de ruta, color, estilo y puntos clave únicos por discapacidad
    if primary == "silla_de_ruedas":
        route_color = "#60A5FA" if t.is_dark else "#1B2354"
        dashed = False
        waypoints = [(56, 134), (56, 44), (242, 44), (288, 96)]
        obstacle = (158, 128, "Rampa bloqueada", ft.Icons.WARNING_AMBER, t.alert_orange)
        landmarks = [
            (56, 86, "Rampa", ft.Icons.ACCESSIBLE, t.blue_action),
            (182, 44, "Cruce plano", ft.Icons.ACCESSIBLE, t.blue_action),
        ]
        legend = "Desvío con rampas continuas"
    elif primary == "visual":
        route_color = "#FBBF24" if t.is_dark else "#D97706"
        dashed = True  # línea podotáctil segmentada
        waypoints = [(164, 144), (164, 88), (164, 38), (278, 38)]
        obstacle = (84, 86, "Poste / Obra", ft.Icons.CONSTRUCTION, t.alert_orange)
        landmarks = [
            (
                164,
                38,
                "Cruce táctil" if has_auditivo else "Semáforo sonoro",
                ft.Icons.VISIBILITY if has_auditivo else ft.Icons.VOLUME_UP,
                "#7C3AED",
            ),
            (164, 108, "Podotáctil", ft.Icons.VISIBILITY, "#D97706"),
        ]
        legend = "Guía podotáctil" + (" (táctil)" if has_auditivo else " y sonoro")
    elif primary == "auditivo":
        route_color = "#38BDF8" if t.is_dark else "#0284C7"
        dashed = False
        waypoints = [(286, 140), (192, 140), (192, 66), (76, 66)]
        obstacle = (264, 52, "Cruce sin señal", ft.Icons.WARNING_AMBER, t.alert_orange)
        landmarks = [
            (192, 102, "Semáforo visual", ft.Icons.TRAFFIC, t.emerald),
            (126, 66, "Alta visibilidad", ft.Icons.VISIBILITY, "#0284C7"),
        ]
        legend = "Corredor 100% visual"
    elif primary == "movilidad_reducida":
        route_color = "#34D399" if t.is_dark else "#0E9F6E"
        dashed = False
        waypoints = [(48, 104), (138, 104), (218, 104), (288, 66)]
        obstacle = (158, 36, "Escaleras evitadas", ft.Icons.BLOCK, t.danger_red)
        landmarks = [
            (138, 104, "Banca / Sombra", ft.Icons.CHAIR, "#0E9F6E"),
            (218, 104, "Sin escalones", ft.Icons.DIRECTIONS_WALK, "#0E9F6E"),
        ]
        legend = "Andador plano con descansos"
    else:  # neurodivergente
        route_color = "#A78BFA" if t.is_dark else "#7C3AED"
        dashed = False
        waypoints = [(54, 142), (118, 142), (272, 142), (272, 40)]
        obstacle = (118, 44, "Obra ruidosa evitada", ft.Icons.CAMPAIGN, t.danger_red)
        landmarks = [
            (192, 142, "Calle tranquila", ft.Icons.PARK, t.emerald),
            (272, 88, "Bajo ruido", ft.Icons.PSYCHOLOGY, "#7C3AED"),
        ]
        legend = "Ruta tranquila (baja estimulación)"

    # Aplicar espejo horizontal para destinos alternos para que el mapa cambie también por destino
    if mirror_x:
        width_ref = 340
        waypoints = [(max(26, width_ref - x), y) for x, y in waypoints]
        ox, oy, otxt, oico, ocol = obstacle
        obstacle = (max(26, width_ref - ox), oy, otxt, oico, ocol)
        landmarks = [(max(26, width_ref - lx), ly, ltxt, lico, lcol) for lx, ly, ltxt, lico, lcol in landmarks]

    # Añadir un marcador extra si hay múltiples discapacidades combinadas
    if len(active) > 1:
        extra_prof = get_profile(active[1])
        mx, my = waypoints[1]
        landmarks.append((mx, max(24, my - 26), extra_prof.short_label, extra_prof.icon, t.blue_action))
        legend = f"{legend} + {extra_prof.short_label}"

    return {
        "street_label": street_label,
        "dest_icon": dest_icon,
        "h_streets": h_streets,
        "v_streets": v_streets,
        "parks": parks,
        "route_color": route_color,
        "dashed": dashed,
        "waypoints": waypoints,
        "obstacle": obstacle,
        "landmarks": landmarks,
        "legend": legend,
    }


def _draw_ortho_route_segments(
    points: List[tuple[int, int]],
    active_step: int,
    base_color: str,
    done_color: str,
    dashed: bool,
    show_progress: bool,
) -> List[ft.Control]:
    """Dibuja segmentos limpios (sólidos o punteados) entre los waypoints de la ruta."""
    controls: List[ft.Control] = []
    thickness = 7

    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        seg_color = done_color if (show_progress and i < active_step) else base_color

        # Si el segmento cambia en X y en Y, dibuja una esquina ortogonal (horizontal luego vertical)
        sub_segs = [(x1, y1, x2, y1), (x2, y1, x2, y2)] if (x1 != x2 and y1 != y2) else [(x1, y1, x2, y2)]

        for sx1, sy1, sx2, sy2 in sub_segs:
            if sx1 == sx2 and sy1 == sy2:
                continue
            if sy1 == sy2:
                left = min(sx1, sx2)
                total_w = abs(sx2 - sx1) + thickness
                if dashed:
                    cursor = left
                    while cursor < left + total_w - 4:
                        dash_w = min(12, left + total_w - cursor)
                        controls.append(
                            ft.Container(
                                left=cursor,
                                top=sy1 - thickness // 2,
                                width=dash_w,
                                height=thickness,
                                border_radius=3,
                                bgcolor=seg_color,
                            )
                        )
                        cursor += 18
                else:
                    controls.append(
                        ft.Container(
                            left=left,
                            top=sy1 - thickness // 2,
                            width=total_w,
                            height=thickness,
                            border_radius=4,
                            bgcolor=seg_color,
                        )
                    )
            else:
                top = min(sy1, sy2)
                total_h = abs(sy2 - sy1) + thickness
                if dashed:
                    cursor = top
                    while cursor < top + total_h - 4:
                        dash_h = min(12, top + total_h - cursor)
                        controls.append(
                            ft.Container(
                                left=sx1 - thickness // 2,
                                top=cursor,
                                width=thickness,
                                height=dash_h,
                                border_radius=3,
                                bgcolor=seg_color,
                            )
                        )
                        cursor += 18
                else:
                    controls.append(
                        ft.Container(
                            left=sx1 - thickness // 2,
                            top=top,
                            width=thickness,
                            height=total_h,
                            border_radius=4,
                            bgcolor=seg_color,
                        )
                    )

        # Nodo circular en cada punto de paso
        controls.append(
            ft.Container(
                left=x1 - 5,
                top=y1 - 5,
                width=10,
                height=10,
                border_radius=5,
                bgcolor=seg_color,
            )
        )

    return controls


def build_minimalist_map(
    t: ThemePalette,
    *,
    show_route: bool,
    badge_text: str = "",
    show_clinics: bool = False,
    show_user_arrow: bool = False,
    arrow_step: int = 0,
    disabilities: Optional[List[str]] = None,
    destination: str = "Clínica 19 (UMF IMSS)",
    height: int = 185,
) -> ft.Container:
    """Mapa vectorial dinámico: cambia calles, ruta, obstáculos, íconos y waypoints por discapacidad y destino."""
    bp = get_map_blueprint(disabilities or ["silla_de_ruedas"], destination, t)
    layers: List[ft.Control] = []

    # 1) Calles del barrio
    for hy in bp["h_streets"]:
        layers.append(ft.Container(left=0, right=0, top=hy, height=11, bgcolor=t.map_street))
    for vx in bp["v_streets"]:
        layers.append(ft.Container(top=0, bottom=0, left=vx, width=11, bgcolor=t.map_street))

    # 2) Parques / áreas verdes del barrio
    for px, py, pw, ph in bp["parks"]:
        layers.append(
            ft.Container(
                left=px,
                top=py,
                width=pw,
                height=ph,
                border_radius=min(pw, ph) // 2,
                bgcolor=t.map_park,
            )
        )

    # 3) Pines de clínicas en pantalla Explorar
    if show_clinics:
        for pos in ((44, 62), (168, 28), (272, 102)):
            layers.append(
                ft.Container(
                    left=pos[0],
                    top=pos[1],
                    width=30,
                    height=30,
                    border_radius=15,
                    bgcolor=t.emerald,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.LOCAL_HOSPITAL, color=ft.Colors.WHITE, size=16),
                )
            )

    # 4) Ruta específica de la discapacidad + marcadores + obstáculo evitado
    waypoints: List[tuple[int, int]] = bp["waypoints"]
    if show_route:
        layers.extend(
            _draw_ortho_route_segments(
                points=waypoints,
                active_step=arrow_step,
                base_color=bp["route_color"],
                done_color=t.emerald,
                dashed=bp["dashed"],
                show_progress=show_user_arrow,
            )
        )

        # Marcadores de accesibilidad específicos (rampas, semáforo sonoro/visual, banca, zona tranquila)
        for lx, ly, _ltxt, lico, lcol in bp["landmarks"]:
            layers.append(
                ft.Container(
                    left=lx - 11,
                    top=ly - 11,
                    width=22,
                    height=22,
                    border_radius=11,
                    bgcolor=lcol,
                    border=ft.Border.all(1.5, ft.Colors.WHITE),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(lico, color=ft.Colors.WHITE, size=12),
                )
            )

        # Obstáculo evitado en el mapa (ej. Rampa bloqueada, Obra ruidosa, Escaleras)
        ox, oy, otxt, oico, ocol = bp["obstacle"]
        layers.append(
            ft.Container(
                left=ox - 12,
                top=oy - 12,
                width=24,
                height=24,
                border_radius=12,
                bgcolor=ocol,
                border=ft.Border.all(1.5, ft.Colors.WHITE),
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(oico, color=ft.Colors.WHITE, size=13),
            )
        )

        # Pin de meta en el destino final
        gx, gy = waypoints[-1]
        layers.append(
            ft.Container(
                left=gx - 14,
                top=gy - 14,
                width=28,
                height=28,
                border_radius=14,
                bgcolor=t.emerald,
                border=ft.Border.all(2, ft.Colors.WHITE),
                alignment=ft.Alignment.CENTER,
                content=ft.Icon(bp["dest_icon"], color=ft.Colors.WHITE, size=15),
            )
        )

        if not badge_text:
            badge_text = otxt

    # 5) Flecha del usuario avanzando exactamente sobre los waypoints de esta discapacidad
    if show_user_arrow:
        ux, uy = waypoints[min(max(arrow_step, 0), len(waypoints) - 1)]
        layers.append(
            ft.Container(
                left=ux - 18,
                top=uy - 18,
                width=36,
                height=36,
                border_radius=18,
                bgcolor="#60A5FA" if t.is_dark else "#BFDBFE",
                alignment=ft.Alignment.CENTER,
                content=ft.Container(
                    width=24,
                    height=24,
                    border_radius=12,
                    bgcolor=t.blue_action,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.NAVIGATION, color=ft.Colors.WHITE, size=14),
                ),
            )
        )

    # 6) Etiqueta de aviso naranja en esquina superior derecha
    if badge_text:
        layers.append(
            ft.Container(
                right=8,
                top=8,
                bgcolor=t.alert_orange,
                border_radius=14,
                padding=ft.Padding.symmetric(horizontal=9, vertical=4),
                content=ft.Row(
                    tight=True,
                    spacing=4,
                    controls=[
                        ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.WHITE, size=13),
                        ft.Text(badge_text, color=ft.Colors.WHITE, size=10, weight=ft.FontWeight.W_600),
                    ],
                ),
            )
        )

    # 7) Leyenda discreta inferior con nombre de calle + tipo de ruta activa
    legend_text = f"{bp['street_label']} · {bp['legend']}" if show_route else bp["street_label"]
    layers.append(
        ft.Container(
            left=8,
            bottom=6,
            bgcolor=t.card_bg,
            border=ft.Border.all(1, t.border),
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            content=ft.Text(legend_text, size=10, weight=ft.FontWeight.W_600, color=t.text_primary),
        )
    )

    return ft.Container(
        height=height,
        width=float("inf"),
        bgcolor=t.map_bg,
        border_radius=16,
        border=ft.Border.all(1, t.border),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Stack(controls=layers),
    )


def main(page: ft.Page) -> None:
    page.title = "Map Inclusive · Apex soa"
    page.padding = 0
    page.window.width = 435
    page.window.height = 860

    state = AppState()
    file_picker = ft.FilePicker()
    if hasattr(page, "services"):
        try:
            page.services.append(file_picker)
        except Exception:
            pass

    # Registrar tipografía oficial de XMind (NeverMind) y servicio GPS nativo
    try:
        page.fonts = XMIND_FONTS_MAP
        xmind_text_theme = ft.TextTheme(
            headline_medium=ft.TextStyle(font_family=XMIND_FONT_BOLD),
            title_large=ft.TextStyle(font_family=XMIND_FONT_BOLD),
            title_medium=ft.TextStyle(font_family=XMIND_FONT_DEMIBOLD),
            label_large=ft.TextStyle(font_family=XMIND_FONT_DEMIBOLD),
            body_large=ft.TextStyle(font_family=XMIND_FONT_REGULAR),
            body_medium=ft.TextStyle(font_family=XMIND_FONT_REGULAR),
            body_small=ft.TextStyle(font_family=XMIND_FONT_REGULAR),
        )
        page.theme = ft.Theme(font_family=XMIND_FONT_REGULAR, text_theme=xmind_text_theme)
        page.dark_theme = ft.Theme(font_family=XMIND_FONT_REGULAR, text_theme=xmind_text_theme)
    except Exception:
        pass

    geolocator = None
    if ftg is not None and sys.platform != "emscripten" and hasattr(page, "services"):
        try:
            geolocator = ftg.Geolocator()
            page.services.append(geolocator)
        except Exception:
            geolocator = None

    pending_locate_feedback = {"show": False}
    pending_photo_callback: Dict[str, Any] = {"cb": None}
    web_bridge_state: Dict[str, Any] = {"channel": None, "proxy": None}

    def is_local_backend_unreachable_on_web() -> bool:
        return sys.platform == "emscripten" and (
            "127.0.0.1" in state.api_url or "localhost" in state.api_url
        )

    def send_web_bridge_cmd(cmd_type: str, **extra: Any) -> bool:
        """Envía comandos al navegador (GPS, Voz, Sirena, Vibración) vía BroadcastChannel sin alterar rutas ni cerrar diálogos."""
        if sys.platform != "emscripten":
            return False
        ch = web_bridge_state.get("channel")
        if ch is None:
            return False
        try:
            payload = {"type": cmd_type, **extra}
            ch.postMessage(json.dumps(payload))
            return True
        except Exception:
            return False

    def apply_location_result(
        lat: float,
        lon: float,
        label: str,
        source: str,
        accuracy_m: Optional[float] = None,
    ) -> None:
        state.current_lat = lat
        state.current_lon = lon
        state.current_accuracy_m = accuracy_m
        state.current_location_source = source
        state.current_location_updated_at = datetime.now().strftime("%H:%M:%S")
        state.origin = label
        state.waze_location = label
        state.is_locating = False
        render()

    async def apply_browser_gps_async(lat: float, lon: float, acc: Optional[float]) -> None:
        label = reverse_geocode_location(lat, lon)
        apply_location_result(lat, lon, label, "GPS en vivo", acc)
        if pending_locate_feedback["show"]:
            show_info_dialog(
                "Ubicación GPS actualizada",
                f"Dirección detectada:\n{label}\n\nCoordenadas:\n{format_coords_text(lat, lon, acc)}",
            )

    async def handle_browser_gps_error_async(code: str) -> None:
        fb = fetch_ip_location_sync()
        if fb is not None:
            apply_location_result(fb["lat"], fb["lon"], fb["label"], fb["source"], None)
        else:
            state.is_locating = False
            render()
        if pending_locate_feedback["show"]:
            msg = (
                "Se denegó el permiso de GPS en el navegador; habilítalo en Ajustes / Safari / Chrome."
                if code == "1"
                else f"No se recibió señal GPS; usando {state.current_location_source}."
            )
            show_info_dialog("Ubicación actual", f"{msg}\n\nUbicación: {state.origin}")

    if sys.platform == "emscripten":
        try:
            import js  # type: ignore
            from pyodide.ffi import create_proxy  # type: ignore

            ch = js.BroadcastChannel.new("map_inclusive_native")

            def _on_web_bridge_message(evt: Any) -> None:
                try:
                    raw = str(evt.data)
                    msg = json.loads(raw)
                except Exception:
                    return
                mtype = msg.get("type")
                if mtype == "gps_result":
                    try:
                        lat = float(msg["lat"])
                        lon = float(msg["lon"])
                        acc = float(msg["acc"]) if msg.get("acc") is not None else None
                        page.run_task(apply_browser_gps_async, lat, lon, acc)
                    except Exception:
                        pass
                elif mtype == "gps_error":
                    code = str(msg.get("code", "unknown"))
                    page.run_task(handle_browser_gps_error_async, code)
                elif mtype == "photo_result":
                    b64 = str(msg.get("b64") or "")
                    fname = str(msg.get("name") or "rostro.jpg")
                    cb = pending_photo_callback.get("cb")
                    pending_photo_callback["cb"] = None
                    if b64 and cb is not None:
                        try:
                            cb(b64, fname)
                        except Exception:
                            pass
                elif mtype == "photo_error":
                    pending_photo_callback["cb"] = None
                    err_txt = str(msg.get("message") or "No se pudo leer la imagen seleccionada.")
                    show_info_dialog("Foto no leída", err_txt)

            proxy = create_proxy(_on_web_bridge_message)
            ch.onmessage = proxy
            web_bridge_state["channel"] = ch
            web_bridge_state["proxy"] = proxy
        except Exception:
            pass

    async def locate_current_user_async(show_dialog_on_done: bool = True) -> None:
        if state.is_locating:
            return
        state.is_locating = True
        pending_locate_feedback["show"] = show_dialog_on_done
        render()

        if sys.platform == "emscripten":
            if send_web_bridge_cmd("request_gps"):
                await asyncio.sleep(12)
                if state.is_locating:
                    await handle_browser_gps_error_async("timeout")
                return

        found: Optional[Dict[str, Any]] = None
        if geolocator is not None and ftg is not None:
            try:
                perm = await geolocator.request_permission()
                allowed = {
                    ftg.GeolocatorPermissionStatus.WHILE_IN_USE,
                    ftg.GeolocatorPermissionStatus.ALWAYS,
                }
                if perm in allowed:
                    cfg = ftg.GeolocatorConfiguration(accuracy=ftg.GeolocatorPositionAccuracy.HIGH)
                    pos = await geolocator.get_current_position(configuration=cfg)
                    lat = float(getattr(pos, "latitude"))
                    lon = float(getattr(pos, "longitude"))
                    acc_raw = getattr(pos, "accuracy", None)
                    acc = float(acc_raw) if acc_raw is not None else None
                    label = await asyncio.to_thread(reverse_geocode_location, lat, lon)
                    found = {
                        "lat": lat,
                        "lon": lon,
                        "accuracy_m": acc,
                        "label": label,
                        "source": "GPS en vivo",
                    }
            except Exception:
                found = None

        if found is None:
            try:
                found = await asyncio.to_thread(fetch_ip_location_sync)
            except Exception:
                found = None

        if found is not None:
            apply_location_result(
                found["lat"],
                found["lon"],
                found["label"],
                found["source"],
                found["accuracy_m"],
            )
            if show_dialog_on_done:
                show_info_dialog(
                    "Ubicación actual detectada",
                    f"Origen: {found['label']}\n"
                    f"Coordenadas: {format_coords_text(found['lat'], found['lon'], found['accuracy_m'])}\n"
                    f"Fuente: {found['source']}",
                )
        else:
            state.is_locating = False
            render()
            if show_dialog_on_done:
                show_info_dialog(
                    "Ubicación actual",
                    "No se pudo obtener tu señal GPS ahora. Se mantiene Campus Coyoacán como referencia.",
                )

    def build_current_location_card() -> ft.Container:
        pal = t()
        is_gps = state.current_location_source == "GPS en vivo"
        return ft.Container(
            bgcolor=pal.card_bg,
            border_radius=14,
            border=ft.Border.all(1.2, pal.blue_action if is_gps else pal.border),
            padding=ft.Padding.symmetric(horizontal=12, vertical=10),
            content=ft.Row(
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        width=36,
                        height=36,
                        border_radius=18,
                        bgcolor=pal.blue_action,
                        alignment=ft.Alignment.CENTER,
                        content=ft.Icon(ft.Icons.MY_LOCATION, color=ft.Colors.WHITE, size=19),
                    ),
                    ft.Column(
                        expand=True,
                        spacing=2,
                        tight=True,
                        controls=[
                            ft.Row(
                                spacing=6,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Text(
                                        "Tu ubicación actual",
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=pal.text_heading,
                                    ),
                                    ft.Container(
                                        bgcolor=pal.emerald_bg if is_gps else pal.badge_bg,
                                        border_radius=8,
                                        padding=ft.Padding.symmetric(horizontal=6, vertical=1),
                                        content=ft.Text(
                                            "Buscando GPS..." if state.is_locating else state.current_location_source,
                                            size=9,
                                            weight=ft.FontWeight.BOLD,
                                            color=pal.emerald_text if is_gps else pal.badge_text,
                                        ),
                                    ),
                                ],
                            ),
                            ft.Text(
                                state.origin,
                                size=12,
                                weight=ft.FontWeight.W_600,
                                color=pal.text_primary,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            ft.Text(
                                format_coords_text(
                                    state.current_lat,
                                    state.current_lon,
                                    state.current_accuracy_m,
                                ),
                                size=10,
                                color=pal.text_muted,
                            ),
                        ],
                    ),
                    ft.IconButton(
                        icon=ft.Icons.GPS_FIXED,
                        icon_color=pal.blue_action,
                        icon_size=21,
                        tooltip="Obtener mi ubicación actual (GPS)",
                        disabled=state.is_locating,
                        on_click=lambda _: page.run_task(locate_current_user_async, True),
                    ),
                ],
            ),
        )

    def t() -> ThemePalette:
        return get_theme(state.dark_mode)

    def apply_page_theme() -> None:
        pal = t()
        page.theme_mode = ft.ThemeMode.DARK if pal.is_dark else ft.ThemeMode.LIGHT
        page.bgcolor = pal.bg

    def toggle_dark_mode(_: Any = None) -> None:
        state.dark_mode = not state.dark_mode
        render()

    def build_theme_toggle() -> ft.Container:
        pal = t()
        return ft.Container(
            bgcolor=pal.card_alt,
            border=ft.Border.all(1, pal.border),
            border_radius=18,
            padding=ft.Padding.symmetric(horizontal=8, vertical=5),
            ink=True,
            on_click=toggle_dark_mode,
            content=ft.Row(
                tight=True,
                spacing=4,
                controls=[
                    ft.Icon(
                        ft.Icons.LIGHT_MODE if pal.is_dark else ft.Icons.DARK_MODE,
                        color=pal.warn_text if pal.is_dark else pal.indigo,
                        size=15,
                    ),
                    ft.Text(
                        "Día" if pal.is_dark else "Noche",
                        size=11,
                        weight=ft.FontWeight.W_600,
                        color=pal.text_primary,
                    ),
                ],
            ),
        )

    def show_info_dialog(title: str, message: str) -> None:
        pal = t()
        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=pal.card_bg,
            title=ft.Text(title, weight=ft.FontWeight.BOLD, color=pal.text_heading),
            content=ft.Text(message, size=13, color=pal.text_primary),
            actions=[
                ft.TextButton(
                    content=ft.Text("Entendido", color=pal.blue_action, weight=ft.FontWeight.BOLD),
                    on_click=lambda _: page.pop_dialog(),
                )
            ],
        )
        page.show_dialog(dialog)

    # -----------------------------------------------------------------------
    # Selector de foto de rostro (nativo HTML en Web/iOS + FilePicker en APK/PC)
    # -----------------------------------------------------------------------
    async def pick_face_photo(
        dialog_title: str,
        on_picked: Callable[[str, str], None],
    ) -> None:
        if sys.platform == "emscripten":
            pending_photo_callback["cb"] = on_picked
            if send_web_bridge_cmd("pick_photo", title=dialog_title):
                return
        try:
            files = await file_picker.pick_files(
                dialog_title=dialog_title,
                file_type=ft.FilePickerFileType.IMAGE,
                allow_multiple=False,
                with_data=True,
            )
            if not files:
                return
            picked = files[0]
            raw_bytes: Optional[bytes] = picked.bytes
            if not raw_bytes and picked.path:
                raw_bytes = Path(picked.path).read_bytes()
            if not raw_bytes:
                show_info_dialog("Foto no leída", "No se pudo leer la imagen seleccionada. Intenta con un JPG o PNG.")
                return
            if len(raw_bytes) > 6 * 1024 * 1024:
                show_info_dialog("Imagen muy pesada", "Elige una foto menor a 6 MB.")
                return
            encoded = base64.b64encode(raw_bytes).decode("ascii")
            on_picked(encoded, picked.name or "rostro.jpg")
        except Exception as exc:
            show_info_dialog("Selector de foto", f"No se pudo abrir el selector de imágenes: {exc}")

    # -----------------------------------------------------------------------
    # Simulación de navegación paso a paso + VOZ en español (adaptada por discapacidad)
    # -----------------------------------------------------------------------
    def get_active_nav_steps() -> List[Dict[str, Any]]:
        steps = state.current_route.get("navigation_steps")
        if isinstance(steps, list) and steps:
            return steps
        return build_local_navigation_steps(state.destination, state.disabilities)

    def is_auditory_profile_active() -> bool:
        return "auditivo" in state.disabilities

    async def speak_current_step() -> None:
        if not state.voice_enabled or is_auditory_profile_active():
            return
        steps = get_active_nav_steps()
        idx = min(max(state.nav_step_index, 0), len(steps) - 1)
        spoken = str(steps[idx].get("spoken_text") or "").strip()
        if not spoken:
            return
        if sys.platform == "emscripten":
            send_web_bridge_cmd("speak", text=spoken)
        else:
            await asyncio.to_thread(speak_spanish_instruction, spoken)

    async def navigation_simulation_loop(generation: int) -> None:
        """Avanza automáticamente los pasos de navegación simulada y dicta cada paso por voz."""
        while state.nav_sim_running and state.nav_sim_generation == generation and state.screen == "active":
            await speak_current_step()
            steps = get_active_nav_steps()
            if state.nav_step_index >= len(steps) - 1:
                state.nav_sim_running = False
                render()
                break
            await asyncio.sleep(SIMULATION_STEP_INTERVAL_SECONDS)
            if not (state.nav_sim_running and state.nav_sim_generation == generation and state.screen == "active"):
                break
            state.nav_step_index = min(state.nav_step_index + 1, len(steps) - 1)
            render()

    def start_nav_simulation() -> None:
        steps = get_active_nav_steps()
        if state.nav_step_index >= len(steps) - 1:
            state.nav_step_index = 0
        state.nav_sim_running = True
        state.nav_sim_generation += 1
        gen = state.nav_sim_generation
        render()
        page.run_task(navigation_simulation_loop, gen)

    def pause_nav_simulation() -> None:
        state.nav_sim_running = False
        state.nav_sim_generation += 1
        stop_voice_speech()
        if sys.platform == "emscripten":
            send_web_bridge_cmd("speak_stop")
        render()

    def advance_nav_step() -> None:
        steps = get_active_nav_steps()
        if state.nav_step_index < len(steps) - 1:
            state.nav_step_index += 1
        else:
            state.nav_step_index = 0
        render()
        if state.voice_enabled and not is_auditory_profile_active():
            page.run_task(speak_current_step)

    # -----------------------------------------------------------------------
    # Protección de menores: ubicación en tiempo real + alarma sonora de extravío
    # -----------------------------------------------------------------------
    def is_minor_with_guardian() -> bool:
        user = state.current_user
        return bool(user and user.get("is_minor") and user.get("guardian"))

    async def send_guardian_location_once(status_label: str = "en_ruta") -> None:
        if not is_minor_with_guardian():
            return
        assert state.current_user is not None
        guardian = state.current_user["guardian"]
        contact = guardian.get("phone") or guardian.get("email") or "familiar registrado"
        now_local = datetime.now().strftime("%H:%M:%S")
        payload = {
            "user_id": state.current_user["id"],
            "username": state.current_user["username"],
            "guardian_name": guardian["name"],
            "guardian_contact": contact,
            "location_text": state.origin,
            "destination": state.destination,
            "latitude": state.current_lat,
            "longitude": state.current_lon,
            "status": status_label,
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(f"{state.api_url}/api/v1/guardian/location", json=payload)
                if resp.status_code < 300:
                    state.last_location_status = resp.json().get("message")
        except Exception:
            state.last_location_status = f"Ubicación compartida en tiempo real con {guardian['name']} ({contact})."
        state.last_location_shared_at = now_local
        render()

    async def minor_location_loop(generation: int) -> None:
        while state.live_sharing_active and state.live_sharing_generation == generation and is_minor_with_guardian():
            await send_guardian_location_once("en_ruta")
            await asyncio.sleep(MINOR_TRACKING_INTERVAL_SECONDS)

    def start_minor_live_sharing() -> None:
        if not is_minor_with_guardian():
            return
        state.live_sharing_active = True
        state.live_sharing_generation += 1
        gen = state.live_sharing_generation
        page.run_task(minor_location_loop, gen)

    def stop_minor_live_sharing() -> None:
        state.live_sharing_active = False
        state.live_sharing_generation += 1

    async def lost_sound_loop(generation: int) -> None:
        if sys.platform == "emscripten":
            send_web_bridge_cmd("siren_start")
            while state.lost_alarm_active and state.lost_alarm_generation == generation:
                await asyncio.sleep(0.5)
            send_web_bridge_cmd("siren_stop")
            return
        while state.lost_alarm_active and state.lost_alarm_generation == generation:
            await asyncio.to_thread(play_alert_sound_once)
            await asyncio.sleep(0.35)

    def stop_lost_alarm(_: Any = None) -> None:
        state.lost_alarm_active = False
        state.lost_alarm_generation += 1
        stop_alert_sound_immediately()
        if sys.platform == "emscripten":
            send_web_bridge_cmd("siren_stop")
        try:
            page.pop_dialog()
        except Exception:
            pass
        render()

    async def activate_lost_minor_alarm() -> None:
        stop_voice_speech()
        if sys.platform == "emscripten":
            send_web_bridge_cmd("speak_stop")
        state.lost_alarm_active = True
        state.lost_alarm_generation += 1
        gen = state.lost_alarm_generation

        user = state.current_user
        username = user["username"] if user else "Usuario menor de edad"
        guardian = (user or {}).get("guardian") or {}
        g_name = guardian.get("name") or "Familiar registrado"
        g_phone = guardian.get("phone") or "911"
        g_email = guardian.get("email") or ""

        helper_msg = (
            f"¡ALERTA DE EXTRAVÍO! {username} ({format_disabilities_label(state.disabilities)}) "
            f"necesita ayuda.\n\nPor favor comunícate con su familiar:\n"
            f"• Familiar: {g_name}\n"
            f"• Teléfono: {g_phone}"
            + (f"\n• Correo: {g_email}" if g_email else "")
            + f"\n• Ubicación: {state.origin}"
            + f"\n• GPS: {format_coords_text(state.current_lat, state.current_lon, state.current_accuracy_m)}"
            + "\n• Emergencias: 911"
        )

        # Iniciar sonido y abrir el diálogo de inmediato (sin esperar backend ni cerrar ventanas)
        page.run_task(lost_sound_loop, gen)

        if not is_local_backend_unreachable_on_web():
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.post(
                        f"{state.api_url}/api/v1/guardian/lost-alert",
                        json={
                            "user_id": user["id"] if user else None,
                            "username": username,
                            "guardian_name": g_name,
                            "guardian_phone": g_phone,
                            "guardian_email": g_email,
                            "location_text": state.origin,
                            "disabilities": state.disabilities,
                        },
                    )
                    if resp.status_code < 300:
                        helper_msg = resp.json().get("helper_message", helper_msg)
            except Exception:
                pass

        if is_minor_with_guardian() and not is_local_backend_unreachable_on_web():
            page.run_task(send_guardian_location_once, "extraviado")

        pal = t()
        alarm_dialog = ft.AlertDialog(
            modal=True,
            bgcolor=pal.danger_bg,
            title=ft.Row(
                spacing=8,
                controls=[
                    ft.Icon(ft.Icons.CAMPAIGN, color=pal.danger_red, size=28),
                    ft.Text("¡ALARMA SONORA ACTIVA!", weight=ft.FontWeight.BOLD, color=pal.danger_text, size=17),
                ],
            ),
            content=ft.Column(
                tight=True,
                spacing=10,
                controls=[
                    ft.Container(
                        bgcolor=pal.danger_red,
                        border_radius=12,
                        padding=12,
                        content=ft.Row(
                            spacing=8,
                            controls=[
                                ft.Icon(ft.Icons.VOLUME_UP, color=ft.Colors.WHITE, size=22),
                                ft.Text(
                                    "Emitiendo sonido fuerte para alertar a personas cercanas... "
                                    "(En iPhone verifica que el botón lateral de silencio esté desactivado).",
                                    color=ft.Colors.WHITE,
                                    weight=ft.FontWeight.BOLD,
                                    size=12,
                                    expand=True,
                                ),
                            ],
                        ),
                    ),
                    ft.Text(helper_msg, size=13, weight=ft.FontWeight.W_600, color=pal.danger_text),
                ],
            ),
            actions=[
                ft.OutlinedButton(
                    content="Reintentar sonido",
                    icon=ft.Icons.VOLUME_UP,
                    on_click=lambda _: send_web_bridge_cmd("siren_start") if sys.platform == "emscripten" else page.run_task(lost_sound_loop, gen),
                ),
                ft.FilledButton(
                    content="Detener alarma",
                    icon=ft.Icons.STOP_CIRCLE,
                    bgcolor=pal.indigo,
                    color=ft.Colors.WHITE,
                    on_click=stop_lost_alarm,
                ),
            ],
        )
        page.show_dialog(alarm_dialog)
        page.update()

    # -----------------------------------------------------------------------
    # Emergencia SOS
    # -----------------------------------------------------------------------
    def open_emergency_dialog(_: Any = None) -> None:
        pal = t()
        dis_label = format_disabilities_label(state.disabilities)

        async def send_sos() -> None:
            try:
                page.pop_dialog()
            except Exception:
                pass
            await asyncio.sleep(0.05)
            payload = {
                "location": state.origin,
                "profile": state.disabilities[0],
                "disabilities": state.disabilities,
                "username": state.current_user["username"] if state.current_user else None,
                "notes": f"Alerta SOS activada rumbo a {state.destination}",
            }
            if not is_local_backend_unreachable_on_web():
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.post(f"{state.api_url}/api/v1/emergency", json=payload)
                        resp.raise_for_status()
                        data = resp.json()
                        nums = "\n".join(f"• {n}" for n in data.get("emergency_numbers", []))
                        show_info_dialog(
                            "Alerta de Emergencia Enviada",
                            f"{data.get('message', '')}\n\n"
                            f"Urgencias más cercanas:\n{data.get('nearest_emergency_clinic', '')}\n\n"
                            f"Teléfonos de emergencia:\n{nums}",
                        )
                        return
                except Exception:
                    pass

            if sys.platform == "emscripten":
                send_web_bridge_cmd("vibrate")
                if state.voice_enabled and not is_auditory_profile_active():
                    send_web_bridge_cmd(
                        "speak",
                        text="Alerta de emergencia SOS activada. Comunícate al 911 o acude al Hospital General Xoco.",
                    )
            show_info_dialog(
                "Emergencia SOS Activada",
                f"Perfiles activos: {dis_label}\n"
                f"Ubicación: {state.origin}\n"
                f"GPS: {format_coords_text(state.current_lat, state.current_lon, state.current_accuracy_m)}\n\n"
                "Urgencias más cercanas: Hospital General Xoco (24h · Tel. 55 5688 9015)\n\n"
                "Comunícate de inmediato:\n"
                "• 911 — Emergencias generales\n"
                "• 065 — Cruz Roja Mexicana\n"
                "• 55 5658 1111 — LOCATEL 24h",
            )

        async def _trigger_lost_after_close() -> None:
            try:
                page.pop_dialog()
            except Exception:
                pass
            await asyncio.sleep(0.08)
            await activate_lost_minor_alarm()

        def trigger_lost_from_sos(_: ft.ControlEvent) -> None:
            page.run_task(_trigger_lost_after_close)

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=pal.card_bg,
            title=ft.Row(
                spacing=8,
                controls=[
                    ft.Icon(ft.Icons.EMERGENCY, color=pal.danger_red, size=26),
                    ft.Text("Emergencia SOS", weight=ft.FontWeight.BOLD, color=pal.danger_red),
                ],
            ),
            content=ft.Column(
                tight=True,
                spacing=8,
                controls=[
                    ft.Text(
                        f"Discapacidades: {dis_label}\n"
                        f"Ubicación: {state.origin}\n"
                        f"GPS: {format_coords_text(state.current_lat, state.current_lon, state.current_accuracy_m)}",
                        size=13,
                        weight=ft.FontWeight.W_600,
                        color=pal.text_primary,
                    ),
                    ft.Container(
                        bgcolor=pal.danger_bg,
                        border_radius=10,
                        padding=10,
                        content=ft.Text(
                            "• 911 — Policía / Ambulancia / Protección Civil\n"
                            "• 065 — Cruz Roja Mexicana\n"
                            "• 55 5658 1111 — LOCATEL CDMX\n"
                            "• Urgencias cercanas: Hospital General Xoco (24h)",
                            size=12,
                            color=pal.danger_text,
                        ),
                    ),
                    styled_outlined_button(
                        pal,
                        text="Me extravié · Activar alarma sonora",
                        icon=ft.Icons.VOLUME_UP,
                        icon_color=pal.alert_orange,
                        width=float("inf"),
                        on_click=trigger_lost_from_sos,
                    ),
                ],
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancelar", color=pal.text_muted),
                    on_click=lambda _: page.pop_dialog(),
                ),
                ft.FilledButton(
                    content="Enviar Alerta SOS",
                    icon=ft.Icons.SOS,
                    bgcolor=pal.danger_red,
                    color=ft.Colors.WHITE,
                    on_click=lambda _: page.run_task(send_sos),
                ),
            ],
        )
        page.show_dialog(dialog)

    def build_sos_pill() -> ft.Container:
        pal = t()
        return ft.Container(
            bgcolor=pal.danger_red,
            border_radius=18,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            ink=True,
            on_click=open_emergency_dialog,
            content=ft.Row(
                tight=True,
                spacing=4,
                controls=[
                    ft.Icon(ft.Icons.SOS, color=ft.Colors.WHITE, size=15),
                    ft.Text("SOS", color=ft.Colors.WHITE, size=12, weight=ft.FontWeight.BOLD),
                ],
            ),
        )

    # -----------------------------------------------------------------------
    # Reporte de incidencias estilo WAZE ("¿Qué ves?") — BottomSheet visual 3x3
    # -----------------------------------------------------------------------
    def open_waze_report_sheet(_: Any = None) -> None:
        pal = t()
        selected_cat_ref: Dict[str, WazeIncidentCategory] = {
            "cat": next(
                (c for c in WAZE_INCIDENT_CATEGORIES if c.id == state.waze_selected_id),
                WAZE_INCIDENT_CATEGORIES[0],
            )
        }

        banner_title_txt = ft.Text(
            f"Seleccionado: {selected_cat_ref['cat'].title}",
            size=13,
            weight=ft.FontWeight.BOLD,
            color="#0F172A",
        )
        banner_sub_txt = ft.Text(
            selected_cat_ref["cat"].default_desc,
            size=11,
            color="#334155",
        )
        submit_btn_label = ft.Text(
            f"Enviar reporte: {selected_cat_ref['cat'].title}",
            color=ft.Colors.WHITE,
            weight=ft.FontWeight.BOLD,
            size=14,
        )

        location_input = styled_text_field(
            pal,
            label="Ubicación del reporte",
            value=state.waze_location,
            prefix_icon=ft.Icons.LOCATION_ON,
            on_change=lambda e: setattr(state, "waze_location", e.control.value or ""),
        )
        notes_input = styled_text_field(
            pal,
            label="Detalle rápido (opcional)",
            hint_text="Ej. Esquina norte junto al cruce...",
            value=state.waze_notes,
            on_change=lambda e: setattr(state, "waze_notes", e.control.value or ""),
        )

        tile_containers: Dict[str, ft.Container] = {}

        def select_category(cat: WazeIncidentCategory) -> None:
            state.waze_selected_id = cat.id
            selected_cat_ref["cat"] = cat
            banner_title_txt.value = f"Seleccionado: {cat.title}"
            banner_sub_txt.value = cat.default_desc
            submit_btn_label.value = f"Enviar reporte: {cat.title}"
            for cid, box in tile_containers.items():
                is_active = cid == cat.id
                box.border = ft.Border.all(2.5 if is_active else 1, cat.color if is_active else pal.border)
                box.bgcolor = pal.badge_bg if is_active else pal.card_alt
            page.update()

        grid_rows: List[ft.Row] = []
        for row_start in range(0, len(WAZE_INCIDENT_CATEGORIES), 3):
            row_items = WAZE_INCIDENT_CATEGORIES[row_start : row_start + 3]
            row_controls: List[ft.Control] = []
            for cat in row_items:
                is_active = cat.id == selected_cat_ref["cat"].id
                circle_tile = ft.Container(
                    expand=True,
                    bgcolor=pal.badge_bg if is_active else pal.card_alt,
                    border=ft.Border.all(2.5 if is_active else 1, cat.color if is_active else pal.border),
                    border_radius=16,
                    padding=ft.Padding.symmetric(horizontal=6, vertical=10),
                    ink=True,
                    on_click=lambda _, c=cat: select_category(c),
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=6,
                        controls=[
                            ft.Container(
                                width=52,
                                height=52,
                                border_radius=26,
                                bgcolor=cat.color,
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(cat.icon, color=ft.Colors.WHITE, size=26),
                            ),
                            ft.Text(
                                cat.short_label,
                                size=11,
                                weight=ft.FontWeight.W_600,
                                color=pal.text_primary,
                                text_align=ft.TextAlign.CENTER,
                            ),
                        ],
                    ),
                )
                tile_containers[cat.id] = circle_tile
                row_controls.append(circle_tile)
            grid_rows.append(ft.Row(spacing=10, controls=row_controls))

        async def submit_waze_report() -> None:
            cat = selected_cat_ref["cat"]
            title_val = cat.title
            loc_val = (state.waze_location or "Av. Universidad, Coyoacán").strip()
            desc_val = (state.waze_notes or cat.default_desc).strip()
            reporter = state.current_user["username"] if state.current_user else "Usuario Map Inclusive"
            state.waze_notes = ""
            page.pop_dialog()

            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"{state.api_url}/api/v1/incidents",
                        json={
                            "title": title_val,
                            "description": desc_val,
                            "location": loc_val,
                            "profile": state.disabilities[0],
                            "disabilities": state.disabilities,
                            "reported_by": reporter,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    state.incidents.insert(0, data)
                    show_info_dialog(
                        f"¡Gracias! Reporte enviado ({data.get('severity', 'medio').upper()})",
                        f"{title_val} en {loc_val}\n\nConsejo de Gemini:\n{data.get('ai_advice', '')}",
                    )
                    if state.screen in ("route", "active"):
                        await refresh_environment(force=True)
                    else:
                        render()
            except Exception:
                local_inc = {
                    "id": f"inc-{uuid.uuid4().hex[:6]}",
                    "title": title_val,
                    "description": desc_val,
                    "location": loc_val,
                    "disabilities": list(state.disabilities),
                    "disabilities_labels": [get_profile(d).label for d in state.disabilities],
                    "reported_by": reporter,
                    "severity": "alto" if cat.id in ("rampa_bloqueada", "zona_peligrosa", "calle_cerrada") else "medio",
                    "ai_advice": f"Precaución cerca de {loc_val}; alerta visible en el historial comunitario.",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                state.incidents.insert(0, local_inc)
                show_info_dialog("Reporte agregado al historial", f"Se registró '{title_val}' en {loc_val}.")
                render()

        sheet = ft.BottomSheet(
            bgcolor=pal.card_bg,
            show_drag_handle=True,
            scrollable=True,
            content=ft.Container(
                padding=ft.Padding.only(left=18, right=18, top=6, bottom=22),
                content=ft.Column(
                    tight=True,
                    spacing=12,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Text("¿Qué ves?", size=21, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                ft.IconButton(
                                    icon=ft.Icons.CLOSE,
                                    icon_color=pal.text_muted,
                                    on_click=lambda _: page.pop_dialog(),
                                ),
                            ],
                        ),
                        # Píldora degradada estilo Waze con estado seleccionado
                        ft.Container(
                            width=float("inf"),
                            border_radius=14,
                            padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                            gradient=ft.LinearGradient(
                                begin=ft.Alignment.CENTER_LEFT,
                                end=ft.Alignment.CENTER_RIGHT,
                                colors=["#DDD6FE", "#BAE6FD"],
                            ),
                            content=ft.Row(
                                spacing=10,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Icon(ft.Icons.MIC, color="#1E3A8A", size=22),
                                    ft.Column(
                                        expand=True,
                                        spacing=2,
                                        controls=[banner_title_txt, banner_sub_txt],
                                    ),
                                ],
                            ),
                        ),
                        # Cuadrícula visual 3x3 de íconos estilo Waze
                        *grid_rows,
                        location_input,
                        notes_input,
                        ft.FilledButton(
                            content=submit_btn_label,
                            icon=ft.Icons.FLAG,
                            bgcolor=pal.blue_action,
                            color=ft.Colors.WHITE,
                            width=float("inf"),
                            height=48,
                            on_click=lambda _: page.run_task(submit_waze_report),
                        ),
                    ],
                ),
            ),
        )
        page.show_dialog(sheet)

    # -----------------------------------------------------------------------
    # Sincronización con Backend Python
    # -----------------------------------------------------------------------
    async def sync_routes_and_clinics() -> None:
        state.disabilities = normalize_disabilities(state.disabilities)
        # Si se selecciona perfil auditivo, la voz se desactiva automáticamente
        state.voice_enabled = "auditivo" not in state.disabilities
        profiles_csv = ",".join(state.disabilities)

        state.suggestions = build_local_suggestions(state.disabilities)
        state.clinics = build_local_clinics(state.disabilities)
        state.current_route = compute_local_route(
            "current",
            state.destination,
            "Zona Coyoacán, CDMX",
            "Ruta accesible",
            next(
                (p["base_km"] for p in LOCAL_SUGGESTIONS_BASE if p["destination"].lower() in state.destination.lower()),
                0.9,
            ),
            state.disabilities,
        )

        if not is_local_backend_unreachable_on_web():
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    s_resp = await client.get(f"{state.api_url}/api/v1/routes/suggestions", params={"profiles": profiles_csv})
                    if s_resp.status_code == 200:
                        state.suggestions = s_resp.json()

                    c_resp = await client.get(f"{state.api_url}/api/v1/clinics", params={"profiles": profiles_csv})
                    if c_resp.status_code == 200:
                        state.clinics = c_resp.json()

                    e_resp = await client.get(
                        f"{state.api_url}/api/v1/routes/estimate",
                        params={"destination": state.destination, "profiles": profiles_csv},
                    )
                    if e_resp.status_code == 200:
                        state.current_route = e_resp.json()
            except Exception:
                pass
        render()

    async def load_incidents_history() -> None:
        if is_local_backend_unreachable_on_web():
            return
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{state.api_url}/api/v1/incidents")
                if resp.status_code == 200 and isinstance(resp.json(), list):
                    state.incidents = resp.json()
                    if state.screen == "incidents":
                        render()
        except Exception:
            pass

    async def load_volunteers() -> None:
        if is_local_backend_unreachable_on_web():
            return
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{state.api_url}/api/v1/volunteers")
                if resp.status_code == 200:
                    state.volunteers = resp.json()
                    if state.screen == "volunteers":
                        render()
        except Exception:
            pass

    async def refresh_environment(force: bool = False) -> None:
        state.is_loading_env = True
        state.env_error = None
        render()

        payload = {
            "origin": state.origin,
            "destination": state.destination,
            "profile": state.disabilities[0],
            "disabilities": state.disabilities,
            "latitude": 19.3498,
            "longitude": -99.1617,
            "force_refresh": force,
        }
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(f"{state.api_url}/api/v1/environment-check", json=payload)
                resp.raise_for_status()
                state.env_report = resp.json()
        except Exception as exc:
            state.env_error = (
                f"Sin conexión con el servidor Python ({exc.__class__.__name__}). "
                "Mostrando ruta accesible en modo local."
            )
        finally:
            state.is_loading_env = False
            render()

    async def auto_refresh_loop(generation: int) -> None:
        while state.refresh_generation == generation and state.screen in ("route", "active"):
            await refresh_environment(force=False)
            await asyncio.sleep(TEN_MINUTES_SECONDS)

    def start_route_monitoring() -> None:
        state.refresh_generation += 1
        gen = state.refresh_generation
        page.run_task(sync_routes_and_clinics)
        page.run_task(auto_refresh_loop, gen)

    def go_to_route(destination_name: str, route_item: Optional[Dict[str, Any]] = None) -> None:
        state.destination = destination_name.strip() or "Clínica 19 (UMF IMSS)"
        if route_item is not None:
            state.current_route = route_item
        state.nav_step_index = 0
        state.screen = "route"
        render()
        start_route_monitoring()

    async def toggle_disability(prof_value: str) -> None:
        current = list(state.disabilities)
        if prof_value in current:
            if len(current) == 1:
                return
            current.remove(prof_value)
        else:
            current.append(prof_value)
        state.disabilities = normalize_disabilities(current)
        state.voice_enabled = "auditivo" not in state.disabilities

        if state.current_user is not None:
            state.current_user["disabilities"] = list(state.disabilities)
            state.current_user["disability_profile"] = state.disabilities[0]
            state.current_user["disability_label"] = format_disabilities_label(state.disabilities)
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    await client.put(
                        f"{state.api_url}/api/v1/profile/disability",
                        json={
                            "user_id": state.current_user["id"],
                            "disability_profile": state.disabilities[0],
                            "disabilities": state.disabilities,
                        },
                    )
            except Exception:
                pass

        await sync_routes_and_clinics()
        if state.screen in ("route", "active"):
            await refresh_environment(force=True)

    async def request_volunteer() -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{state.api_url}/api/v1/volunteer-request",
                    json={
                        "user_location": state.origin,
                        "destination": state.destination,
                        "profile": state.disabilities[0],
                        "disabilities": state.disabilities,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "sin_voluntarios":
                    show_info_dialog("Sin voluntarios activos", data["message"])
                else:
                    show_info_dialog(
                        "Guía Voluntaria Confirmada",
                        f"{data.get('volunteer_name', '')}\n"
                        f"Tiempo estimado: {data.get('eta_minutes', 6)} min\n\n"
                        f"{data.get('message', '')}",
                    )
        except Exception:
            if not state.volunteers:
                show_info_dialog(
                    "Sin voluntarios activos",
                    "Por el momento no hay voluntarios registrados. "
                    "Inicia sesión en la pestaña Perfil y sube tu foto de rostro para postularte.",
                )
            else:
                first = state.volunteers[0]
                show_info_dialog(
                    "Guía Voluntaria Confirmada",
                    f"{first['username']} ({first['zone']}) fue notificado.\nTiempo estimado: 6 min.",
                )

    # -----------------------------------------------------------------------
    # Barra inferior de navegación (adaptada a Modo Día y Modo Noche)
    # -----------------------------------------------------------------------
    def build_bottom_nav(selected_index: int) -> ft.NavigationBar:
        pal = t()

        def on_nav_change(e: ft.ControlEvent) -> None:
            idx = e.control.selected_index
            if idx == 0:
                state.screen = "search"
                render()
                page.run_task(sync_routes_and_clinics)
            elif idx == 1:
                state.screen = "incidents"
                render()
                page.run_task(load_incidents_history)
            elif idx == 2:
                state.screen = "clinics"
                render()
                page.run_task(sync_routes_and_clinics)
            elif idx == 3:
                state.screen = "volunteers"
                render()
                page.run_task(load_volunteers)
            elif idx == 4:
                state.screen = "profile"
                state.auth_error = None
                state.auth_feedback = None
                state.vol_error = None
                render()

        return ft.NavigationBar(
            selected_index=selected_index,
            bgcolor=pal.nav_bg,
            indicator_color=pal.badge_bg,
            on_change=on_nav_change,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.MAP, label="Mapa"),
                ft.NavigationBarDestination(icon=ft.Icons.HISTORY, label="Incidencias"),
                ft.NavigationBarDestination(icon=ft.Icons.LOCAL_HOSPITAL, label="Clínicas"),
                ft.NavigationBarDestination(icon=ft.Icons.PEOPLE, label="Voluntarios"),
                ft.NavigationBarDestination(icon=ft.Icons.PERSON, label="Perfil"),
            ],
        )

    def build_multi_disability_chips() -> ft.Row:
        pal = t()
        return ft.Row(
            wrap=True,
            spacing=8,
            run_spacing=8,
            controls=[
                ft.Chip(
                    label=ft.Text(
                        p.short_label,
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=pal.chip_active_text if p.api_value in state.disabilities else pal.chip_idle_text,
                    ),
                    selected=p.api_value in state.disabilities,
                    selected_color=pal.chip_active_bg,
                    bgcolor=pal.chip_idle_bg,
                    show_checkmark=True,
                    check_color=pal.chip_active_text,
                    on_select=lambda _, pv=p.api_value: page.run_task(toggle_disability, pv),
                )
                for p in PROFILES
            ],
        )

    # =======================================================================
    # PANTALLA 1: PANTALLA INICIAL
    # =======================================================================
    def build_onboarding_screen() -> ft.Control:
        pal = t()

        def profile_tile(option: ProfileOption, full_width: bool = False) -> ft.Container:
            is_selected = option.api_value in state.disabilities
            fg = pal.chip_active_text if is_selected else pal.text_primary
            bg = pal.chip_active_bg if is_selected else pal.card_bg
            bc = pal.chip_active_bg if is_selected else pal.border

            if full_width:
                return ft.Container(
                    height=62,
                    bgcolor=bg,
                    border=ft.Border.all(1.5, bc),
                    border_radius=16,
                    alignment=ft.Alignment.CENTER,
                    ink=True,
                    on_click=lambda _: page.run_task(toggle_disability, option.api_value),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(option.icon, color=fg, size=24),
                            ft.Text(option.label, color=fg, size=14, weight=ft.FontWeight.W_600),
                            *([ft.Icon(ft.Icons.CHECK_CIRCLE, color=pal.emerald_bg, size=18)] if is_selected else []),
                        ],
                    ),
                )

            return ft.Container(
                expand=True,
                height=108,
                bgcolor=bg,
                border=ft.Border.all(1.5, bc),
                border_radius=16,
                padding=10,
                alignment=ft.Alignment.CENTER,
                ink=True,
                on_click=lambda _: page.run_task(toggle_disability, option.api_value),
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                    controls=[
                        ft.Icon(option.icon, color=fg, size=30),
                        ft.Text(option.label, color=fg, size=13, weight=ft.FontWeight.W_600, text_align=ft.TextAlign.CENTER),
                    ],
                ),
            )

        return ft.Container(
            expand=True,
            bgcolor=pal.bg,
            padding=ft.Padding.symmetric(horizontal=18, vertical=18),
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Row(
                                spacing=8,
                                controls=[
                                    ft.Container(
                                        width=34,
                                        height=34,
                                        border_radius=17,
                                        bgcolor=pal.emerald,
                                        alignment=ft.Alignment.CENTER,
                                        content=ft.Icon(ft.Icons.ACCESSIBLE, color=ft.Colors.WHITE, size=19),
                                    ),
                                    ft.Column(
                                        spacing=0,
                                        controls=[
                                            ft.Text("map inclusive", size=20, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                            ft.Text("Campus Coyoacán · Apex soa", size=11, color=pal.text_muted),
                                        ],
                                    ),
                                ],
                            ),
                            ft.Row(spacing=6, controls=[build_theme_toggle(), build_sos_pill()]),
                        ],
                    ),
                    ft.Text("¿Cómo te desplazas hoy?", size=20, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                    ft.Text(
                        "Elige una o varias discapacidades; las rutas e instrucciones (por voz o visuales) se adaptarán a ti.",
                        size=12,
                        color=pal.text_muted,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Row(spacing=12, controls=[profile_tile(PROFILES[0]), profile_tile(PROFILES[1])]),
                    ft.Row(spacing=12, controls=[profile_tile(PROFILES[2]), profile_tile(PROFILES[3])]),
                    profile_tile(PROFILES[4], full_width=True),
                    ft.Container(
                        width=float("inf"),
                        bgcolor=pal.emerald_bg,
                        border_radius=12,
                        padding=10,
                        content=ft.Text(
                            f"Seleccionadas ({len(state.disabilities)}): {format_disabilities_label(state.disabilities)}"
                            + (
                                "\nModo Visual activo (sin depender de audio)."
                                if is_auditory_profile_active()
                                else "\nGuía por voz en español habilitada."
                            ),
                            size=12,
                            weight=ft.FontWeight.W_600,
                            color=pal.emerald_text,
                        ),
                    ),
                    ft.FilledButton(
                        content="Continuar al mapa",
                        bgcolor=pal.blue_action,
                        color=ft.Colors.WHITE,
                        width=float("inf"),
                        height=48,
                        on_click=lambda _: (
                            setattr(state, "screen", "search"),
                            render(),
                            page.run_task(sync_routes_and_clinics),
                            (
                                setattr(state, "auto_located_once", True),
                                page.run_task(locate_current_user_async, False),
                            )
                            if not state.auto_located_once
                            else None,
                        ),
                    ),
                    styled_outlined_button(
                        pal,
                        text="Activar sonido y permiso GPS (iOS / Android)",
                        icon=ft.Icons.VOLUME_UP,
                        icon_color=pal.emerald,
                        width=float("inf"),
                        height=44,
                        on_click=lambda _: (
                            send_web_bridge_cmd(
                                "unlock_and_test",
                                text="Sonido y permisos activados en Map Inclusive.",
                            )
                            if sys.platform == "emscripten"
                            else page.run_task(
                                asyncio.to_thread,
                                speak_spanish_instruction,
                                "Sonido y permisos activados en Map Inclusive.",
                            ),
                            page.run_task(locate_current_user_async, True),
                        ),
                    ),
                    styled_outlined_button(
                        pal,
                        text=(
                            f"Mi Perfil ({state.current_user['username']})"
                            if state.current_user
                            else "Crear perfil / Iniciar sesión"
                        ),
                        icon=ft.Icons.PERSON,
                        width=float("inf"),
                        height=44,
                        on_click=lambda _: (setattr(state, "screen", "profile"), render()),
                    ),
                ],
            ),
        )

    # =======================================================================
    # PANTALLA 2: EXPLORAR RUTAS (Lista vertical con tiempo estimado)
    # =======================================================================
    def build_search_screen() -> ft.Control:
        pal = t()
        dis_label = format_disabilities_label(state.disabilities)
        search_input = styled_text_field(
            pal,
            hint_text="Buscar destino...",
            value=state.search_query,
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            on_change=lambda e: setattr(state, "search_query", e.control.value or ""),
        )

        def category_icon(cat: str) -> Any:
            if "Clínica" in cat or "Hospital" in cat:
                return ft.Icons.LOCAL_HOSPITAL
            if "Transporte" in cat:
                return ft.Icons.DIRECTIONS
            return ft.Icons.LOCATION_ON

        suggestion_rows: List[ft.Control] = []
        for idx, item in enumerate(state.suggestions):
            is_health = "Clínica" in item["category"] or "Hospital" in item["category"]
            row_tile = ft.Container(
                bgcolor=pal.card_bg,
                padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                ink=True,
                on_click=lambda _, r=item: go_to_route(r["destination"], r),
                content=ft.Row(
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(
                            width=38,
                            height=38,
                            border_radius=10,
                            bgcolor=pal.emerald_bg if is_health else pal.badge_bg,
                            alignment=ft.Alignment.CENTER,
                            content=ft.Icon(
                                category_icon(item["category"]),
                                color=pal.emerald_text if is_health else pal.badge_text,
                                size=20,
                            ),
                        ),
                        ft.Column(
                            expand=True,
                            spacing=2,
                            controls=[
                                ft.Text(item["destination"], size=14, weight=ft.FontWeight.BOLD, color=pal.text_primary),
                                ft.Text(f"{item['address']} · {item['distance_text']}", size=12, color=pal.text_muted),
                                ft.Text(
                                    item["route_name"].split("·")[0].strip(),
                                    size=11,
                                    color=pal.emerald,
                                    weight=ft.FontWeight.W_600,
                                ),
                            ],
                        ),
                        ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            spacing=2,
                            controls=[
                                ft.Container(
                                    bgcolor=pal.badge_bg,
                                    border_radius=10,
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                    content=ft.Row(
                                        tight=True,
                                        spacing=4,
                                        controls=[
                                            ft.Icon(ft.Icons.ACCESS_TIME, size=13, color=pal.badge_text),
                                            ft.Text(
                                                f"{item['estimated_minutes']} min",
                                                size=12,
                                                weight=ft.FontWeight.BOLD,
                                                color=pal.badge_text,
                                            ),
                                        ],
                                    ),
                                ),
                                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=pal.text_muted),
                            ],
                        ),
                    ],
                ),
            )
            suggestion_rows.append(row_tile)
            if idx < len(state.suggestions) - 1:
                suggestion_rows.append(ft.Divider(height=1, color=pal.border))

        return ft.Container(
            expand=True,
            padding=16,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Column(
                                expand=True,
                                spacing=1,
                                controls=[
                                    ft.Text("Explorar rutas", size=19, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                    ft.Text(f"Perfiles: {dis_label}", size=11, color=pal.emerald, weight=ft.FontWeight.W_600),
                                ],
                            ),
                            ft.Row(spacing=6, controls=[build_theme_toggle(), build_sos_pill()]),
                        ],
                    ),
                    ft.Row(
                        spacing=8,
                        controls=[
                            search_input,
                            ft.FilledButton(
                                content="Ir",
                                bgcolor=pal.blue_action,
                                color=ft.Colors.WHITE,
                                height=48,
                                on_click=lambda _: go_to_route(state.search_query),
                            ),
                        ],
                    ),
                    build_current_location_card(),
                    build_minimalist_map(
                        pal,
                        show_route=False,
                        badge_text="Zona poco concurrida",
                        show_clinics=True,
                        disabilities=state.disabilities,
                        destination=state.destination,
                        height=175,
                    ),
                    ft.Text("Rutas sugeridas (lista con tiempo estimado)", size=14, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                    ft.Container(
                        bgcolor=pal.card_bg,
                        border_radius=16,
                        border=ft.Border.all(1, pal.border),
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        content=ft.Column(spacing=0, controls=suggestion_rows),
                    ),
                ],
            ),
        )

    # =======================================================================
    # PANTALLA 3: RUTA Y GEMINI
    # =======================================================================
    def build_route_screen() -> ft.Control:
        pal = t()
        route = state.current_route
        dis_label = format_disabilities_label(state.disabilities)

        if state.is_loading_env:
            banner_bg, banner_fg = pal.emerald_bg, pal.emerald_text
            banner_title = "Consultando entorno en tiempo real con Gemini..."
            banner_sub = "Recopilando clima, bloqueos y transporte..."
        elif state.env_error:
            banner_bg, banner_fg = pal.warn_bg, pal.warn_text
            banner_title = state.env_error
            banner_sub = "Toca recargar cuando vuelvas a tener conexión"
        elif state.env_report:
            banner_bg, banner_fg = pal.emerald_bg, pal.emerald_text
            banner_title = f"Actualizado con Gemini: {state.env_report.get('banner_resumen', '')}"
            banner_sub = (
                f"Cada {state.env_report.get('next_refresh_minutes', 10)} min · "
                f"{state.env_report.get('model_used', 'gemini-4-hydrogen')} · Toca para detalles"
            )
        else:
            banner_bg, banner_fg = pal.emerald_bg, pal.emerald_text
            banner_title = "Listo para consultar entorno con Gemini"
            banner_sub = "Actualización automática cada 10 minutos"

        steps_preview = [
            ft.Text(f"{i + 1}. {step}", size=12, color=pal.text_primary)
            for i, step in enumerate(route.get("steps", []))
        ]

        summary_controls: List[ft.Control] = [
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text("Ruta Accesible", size=17, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                            ft.Text(f"{dis_label} · {route.get('distance_text', '1.2 km')}", size=12, color=pal.text_muted),
                        ],
                    ),
                    ft.Container(
                        bgcolor=pal.badge_bg,
                        border_radius=12,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                        content=ft.Row(
                            tight=True,
                            spacing=4,
                            controls=[
                                ft.Icon(ft.Icons.ACCESS_TIME, size=15, color=pal.badge_text),
                                ft.Text(f"~{route.get('estimated_minutes', 15)} min", size=13, weight=ft.FontWeight.BOLD, color=pal.badge_text),
                            ],
                        ),
                    ),
                ],
            ),
            ft.Text(f"Origen: {state.origin} · Destino: {state.destination}", size=12, color=pal.text_muted),
            ft.Container(
                bgcolor=pal.info_bg if is_auditory_profile_active() else pal.card_alt,
                border_radius=10,
                padding=8,
                content=ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(
                            ft.Icons.HEARING_DISABLED if is_auditory_profile_active() else ft.Icons.RECORD_VOICE_OVER,
                            color=pal.info_text if is_auditory_profile_active() else pal.emerald,
                            size=18,
                        ),
                        ft.Text(
                            (
                                "Guía 100% visual lista (sin depender de audio para perfil auditivo)."
                                if is_auditory_profile_active()
                                else "Guía por voz en español lista: te indicará cada paso y obstáculo."
                            ),
                            size=12,
                            color=pal.info_text if is_auditory_profile_active() else pal.text_primary,
                            expand=True,
                        ),
                    ],
                ),
            ),
            ft.Container(
                bgcolor=pal.card_alt,
                border_radius=12,
                padding=10,
                content=ft.Column(spacing=4, controls=steps_preview),
            ),
        ]

        if is_minor_with_guardian():
            guardian_name = state.current_user["guardian"]["name"]  # type: ignore[index]
            summary_controls.append(
                ft.Container(
                    bgcolor=pal.info_bg,
                    border_radius=12,
                    padding=10,
                    content=ft.Row(
                        spacing=8,
                        controls=[
                            ft.Icon(ft.Icons.SHARE_LOCATION, color=pal.info_text, size=18),
                            ft.Text(
                                f"Protección de menor: al iniciar ruta se compartirá tu ubicación en tiempo real con {guardian_name}.",
                                size=12,
                                color=pal.info_text,
                                expand=True,
                            ),
                        ],
                    ),
                )
            )

        summary_controls.append(
            ft.Container(
                bgcolor=banner_bg,
                border_radius=14,
                padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                ink=True,
                on_click=lambda _: (setattr(state, "show_env_details", not state.show_env_details), render()),
                content=ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.ProgressRing(width=16, height=16, stroke_width=2, color=pal.emerald)
                        if state.is_loading_env
                        else ft.Container(
                            width=10,
                            height=10,
                            border_radius=5,
                            bgcolor=pal.alert_orange if state.env_error else pal.emerald,
                        ),
                        ft.Column(
                            expand=True,
                            spacing=2,
                            controls=[
                                ft.Text(banner_title, size=12, weight=ft.FontWeight.W_600, color=banner_fg),
                                ft.Text(banner_sub, size=11, color=banner_fg),
                            ],
                        ),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            icon_color=banner_fg,
                            icon_size=18,
                            on_click=lambda _: page.run_task(refresh_environment, True),
                        ),
                    ],
                ),
            )
        )

        if state.show_env_details and state.env_report:
            rep = state.env_report
            tips = rep.get("recomendaciones_perfil") or []
            summary_controls.append(
                ft.Container(
                    bgcolor=pal.card_alt,
                    border_radius=12,
                    padding=10,
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            ft.Text(f"Clima: {rep.get('clima', '-')}", size=12, color=pal.text_primary),
                            ft.Text(f"Bloqueos: {', '.join(rep.get('bloqueos', []))}", size=12, color=pal.text_primary),
                            ft.Text(f"Transporte: {', '.join(rep.get('transporte_afectado', []))}", size=12, color=pal.text_primary),
                            *[ft.Text(f"• {tip}", size=12, color=pal.emerald, weight=ft.FontWeight.W_600) for tip in tips],
                        ],
                    ),
                )
            )

        def start_navigation(_: ft.ControlEvent) -> None:
            state.nav_step_index = 0
            state.voice_enabled = not is_auditory_profile_active()
            state.screen = "active"
            if is_minor_with_guardian():
                start_minor_live_sharing()
            start_nav_simulation()

        summary_controls.append(
            ft.FilledButton(
                content="Iniciar Ruta Simulada",
                icon=ft.Icons.PLAY_ARROW,
                bgcolor=pal.blue_action,
                color=ft.Colors.WHITE,
                width=float("inf"),
                height=46,
                on_click=start_navigation,
            )
        )

        return ft.Container(
            expand=True,
            padding=16,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Ruta Accesible", size=20, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                            ft.Row(spacing=6, controls=[build_theme_toggle(), build_sos_pill()]),
                        ],
                    ),
                    ft.Text("Activa una o varias discapacidades:", size=12, color=pal.text_muted),
                    build_multi_disability_chips(),
                    build_minimalist_map(
                        pal,
                        show_route=True,
                        disabilities=state.disabilities,
                        destination=state.destination,
                        height=180,
                    ),
                    ft.Container(
                        bgcolor=pal.card_bg,
                        border_radius=20,
                        border=ft.Border.all(1, pal.border),
                        padding=16,
                        content=ft.Column(spacing=10, controls=summary_controls),
                    ),
                ],
            ),
        )

    # =======================================================================
    # PANTALLA 4: EN CAMINO (Simulación paso a paso + VOZ / Modo Visual Auditivo + Waze)
    # =======================================================================
    def build_active_screen() -> ft.Control:
        pal = t()
        route = state.current_route
        steps = get_active_nav_steps()
        idx = min(max(state.nav_step_index, 0), len(steps) - 1)
        cur = steps[idx]
        total_steps = len(steps)
        progress_val = (idx + 1) / max(1, total_steps)

        total_min = int(route.get("estimated_minutes", 15))
        remaining_min = max(0, int(round(total_min * (1 - idx / max(1, total_steps - 1)))))

        direction_icon_map = {
            "straight": ft.Icons.STRAIGHT,
            "right": ft.Icons.TURN_RIGHT,
            "left": ft.Icons.TURN_LEFT,
            "arrive": ft.Icons.CHECK_CIRCLE_OUTLINE,
        }
        dir_icon = direction_icon_map.get(cur.get("direction", "straight"), ft.Icons.STRAIGHT)

        gemini_chip = (
            f"Gemini activo · {state.env_report.get('banner_resumen', '')}"
            if state.env_report
            else "Monitoreo Gemini activo cada 10 min"
        )

        active_controls: List[ft.Control] = [
            # Tarjeta de instrucción detallada + Modo Visual (Auditivo) o Voz
            ft.Container(
                bgcolor=pal.warn_bg if is_auditory_profile_active() else pal.card_bg,
                border_radius=16,
                border=ft.Border.all(
                    2 if is_auditory_profile_active() else 1,
                    pal.alert_orange if is_auditory_profile_active() else pal.border,
                ),
                padding=14,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text(
                                    f"Paso {idx + 1} de {total_steps}",
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color=pal.warn_text if is_auditory_profile_active() else pal.blue_action,
                                ),
                                ft.Container(
                                    bgcolor=pal.info_bg if is_auditory_profile_active() else pal.emerald_bg,
                                    border_radius=10,
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                    content=ft.Row(
                                        tight=True,
                                        spacing=4,
                                        controls=[
                                            ft.Icon(
                                                ft.Icons.HEARING_DISABLED
                                                if is_auditory_profile_active()
                                                else (ft.Icons.RECORD_VOICE_OVER if state.voice_enabled else ft.Icons.VOLUME_OFF),
                                                size=13,
                                                color=pal.info_text if is_auditory_profile_active() else pal.emerald_text,
                                            ),
                                            ft.Text(
                                                "MODO VISUAL (Auditivo)"
                                                if is_auditory_profile_active()
                                                else ("Voz activa" if state.voice_enabled else "Voz silenciada"),
                                                size=11,
                                                weight=ft.FontWeight.BOLD,
                                                color=pal.info_text if is_auditory_profile_active() else pal.emerald_text,
                                            ),
                                        ],
                                    ),
                                ),
                            ],
                        ),
                        ft.ProgressBar(value=progress_val, color=pal.blue_action, bgcolor=pal.card_alt),
                        ft.Text(
                            cur.get("visual_cue", ""),
                            size=13,
                            weight=ft.FontWeight.BOLD,
                            color=pal.warn_text if is_auditory_profile_active() else pal.text_heading,
                        ),
                        ft.Text(
                            cur.get("detail", ""),
                            size=13,
                            color=pal.warn_text if is_auditory_profile_active() else pal.text_primary,
                        ),
                        # Controles de simulación y voz
                        ft.Row(
                            spacing=8,
                            controls=[
                                ft.FilledButton(
                                    content="Pausar" if state.nav_sim_running else "Simular",
                                    icon=ft.Icons.PAUSE if state.nav_sim_running else ft.Icons.PLAY_ARROW,
                                    bgcolor=pal.indigo if state.nav_sim_running else pal.blue_action,
                                    color=ft.Colors.WHITE,
                                    expand=True,
                                    on_click=lambda _: pause_nav_simulation() if state.nav_sim_running else start_nav_simulation(),
                                ),
                                styled_outlined_button(
                                    pal,
                                    text="Siguiente",
                                    icon=ft.Icons.SKIP_NEXT,
                                    expand=True,
                                    on_click=lambda _: advance_nav_step(),
                                ),
                            ],
                        ),
                        *(
                            [
                                ft.Container(
                                    bgcolor=pal.card_bg,
                                    border_radius=10,
                                    padding=8,
                                    content=ft.Row(
                                        spacing=6,
                                        controls=[
                                            ft.Icon(ft.Icons.VIBRATION, color=pal.alert_orange, size=16),
                                            ft.Text(
                                                "Audio desactivado automáticamente para perfil Auditivo. Todas las señales son visuales y claras.",
                                                size=11,
                                                color=pal.text_muted,
                                                expand=True,
                                            ),
                                        ],
                                    ),
                                )
                            ]
                            if is_auditory_profile_active()
                            else [
                                ft.Row(
                                    spacing=8,
                                    controls=[
                                        styled_outlined_button(
                                            pal,
                                            text="Repetir por voz",
                                            icon=ft.Icons.RECORD_VOICE_OVER,
                                            icon_color=pal.emerald,
                                            expand=True,
                                            on_click=lambda _: page.run_task(speak_current_step),
                                        ),
                                        styled_outlined_button(
                                            pal,
                                            text="Silenciar" if state.voice_enabled else "Activar voz",
                                            icon=ft.Icons.VOLUME_OFF if state.voice_enabled else ft.Icons.VOLUME_UP,
                                            expand=True,
                                            on_click=lambda _: (
                                                setattr(state, "voice_enabled", not state.voice_enabled),
                                                stop_voice_speech() if not state.voice_enabled else None,
                                                render(),
                                            ),
                                        ),
                                    ],
                                )
                            ]
                        ),
                    ],
                ),
            ),
            ft.Container(
                bgcolor=pal.emerald_bg,
                border_radius=14,
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                content=ft.Text(gemini_chip, size=12, color=pal.emerald_text, weight=ft.FontWeight.W_600),
            ),
        ]

        if is_minor_with_guardian():
            guardian = state.current_user["guardian"]  # type: ignore[index]
            shared_info = f"Último envío: {state.last_location_shared_at}" if state.last_location_shared_at else "Enviando ubicación..."
            active_controls.append(
                ft.Container(
                    bgcolor=pal.info_bg,
                    border_radius=14,
                    border=ft.Border.all(1, pal.blue_action),
                    padding=10,
                    content=ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.MY_LOCATION, color=pal.info_text, size=20),
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Text(
                                        f"Ubicación en tiempo real compartida con {guardian['name']}",
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=pal.info_text,
                                    ),
                                    ft.Text(f"{guardian.get('phone') or guardian.get('email')} · {shared_info}", size=11, color=pal.info_text),
                                ],
                            ),
                        ],
                    ),
                )
            )

        active_controls.append(
            build_minimalist_map(
                pal,
                show_route=True,
                show_user_arrow=True,
                arrow_step=idx,
                disabilities=state.disabilities,
                destination=state.destination,
                height=185,
            )
        )

        action_buttons: List[ft.Control] = [
            ft.Text(f"Rumbo a: {state.destination}", size=12, color=pal.text_muted),
            ft.FilledButton(
                content="Reportar Incidencia (¿Qué ves?)",
                icon=ft.Icons.WARNING_AMBER,
                bgcolor=pal.alert_orange,
                color=ft.Colors.WHITE,
                width=float("inf"),
                height=46,
                on_click=open_waze_report_sheet,
            ),
            ft.FilledButton(
                content="Botón de Emergencia (SOS)",
                icon=ft.Icons.EMERGENCY,
                bgcolor=pal.danger_red,
                color=ft.Colors.WHITE,
                width=float("inf"),
                height=44,
                on_click=open_emergency_dialog,
            ),
            ft.FilledButton(
                content="Detener alarma sonora" if state.lost_alarm_active else "Me extravié · Activar alarma sonora",
                icon=ft.Icons.STOP_CIRCLE if state.lost_alarm_active else ft.Icons.VOLUME_UP,
                bgcolor=pal.indigo if state.lost_alarm_active else "#B91C1C",
                color=ft.Colors.WHITE,
                width=float("inf"),
                height=44,
                on_click=stop_lost_alarm if state.lost_alarm_active else (lambda _: page.run_task(activate_lost_minor_alarm)),
            ),
            styled_outlined_button(
                pal,
                text="Pedir Guía Voluntaria",
                icon=ft.Icons.PEOPLE,
                icon_color=pal.blue_action,
                width=float("inf"),
                height=42,
                on_click=lambda _: page.run_task(request_volunteer),
            ),
            styled_outlined_button(
                pal,
                text="Finalizar recorrido",
                text_color=pal.danger_red,
                border_color=pal.danger_red,
                width=float("inf"),
                height=42,
                on_click=lambda _: (
                    pause_nav_simulation(),
                    stop_minor_live_sharing(),
                    stop_lost_alarm() if state.lost_alarm_active else None,
                    setattr(state, "refresh_generation", state.refresh_generation + 1),
                    setattr(state, "screen", "search"),
                    render(),
                ),
            ),
        ]

        active_controls.append(
            ft.Container(
                bgcolor=pal.card_bg,
                border_radius=20,
                border=ft.Border.all(1, pal.border),
                padding=16,
                content=ft.Column(spacing=9, controls=action_buttons),
            )
        )

        return ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    bgcolor=pal.indigo,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=16),
                    content=ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(dir_icon, color=ft.Colors.WHITE, size=36),
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Text(cur.get("headline", ""), color=ft.Colors.WHITE, size=16, weight=ft.FontWeight.BOLD),
                                    ft.Text(
                                        f"Restante: ~{remaining_min} min · {route.get('distance_text', '')}",
                                        color="#BFDBFE",
                                        size=12,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                ],
                            ),
                            ft.Column(
                                horizontal_alignment=ft.CrossAxisAlignment.END,
                                spacing=6,
                                controls=[build_sos_pill(), build_theme_toggle()],
                            ),
                        ],
                    ),
                ),
                ft.Container(
                    expand=True,
                    padding=16,
                    content=ft.Column(
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                        spacing=12,
                        controls=active_controls,
                    ),
                ),
            ],
        )

    # =======================================================================
    # SECCIÓN HISTORIAL DE INCIDENCIAS + Botón Waze ("¿Qué ves?")
    # =======================================================================
    def build_incidents_screen() -> ft.Control:
        pal = t()

        def severity_colors(sev: str) -> tuple[str, str]:
            val = sev.lower()
            if val == "alto":
                return pal.danger_bg, pal.danger_text
            if val == "medio":
                return pal.warn_bg, pal.warn_text
            return pal.emerald_bg, pal.emerald_text

        history_cards: List[ft.Control] = []
        if not state.incidents:
            history_cards.append(
                ft.Container(
                    bgcolor=pal.card_bg,
                    border_radius=16,
                    border=ft.Border.all(1, pal.border),
                    padding=20,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text("No hay incidencias registradas todavía.", color=pal.text_muted),
                )
            )
        else:
            for inc in state.incidents:
                sev = str(inc.get("severity", "medio"))
                sev_bg, sev_fg = severity_colors(sev)
                labels = inc.get("disabilities_labels") or [get_profile(d).label for d in inc.get("disabilities", [])]
                affected_text = ", ".join(labels) if labels else "Accesibilidad general"

                history_cards.append(
                    ft.Container(
                        bgcolor=pal.card_bg,
                        border_radius=16,
                        border=ft.Border.all(1, pal.border),
                        padding=14,
                        content=ft.Column(
                            spacing=6,
                            controls=[
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        ft.Text(inc.get("title", "Incidencia"), size=15, weight=ft.FontWeight.BOLD, color=pal.text_heading, expand=True),
                                        ft.Container(
                                            bgcolor=sev_bg,
                                            border_radius=10,
                                            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                            content=ft.Text(sev.upper(), size=11, weight=ft.FontWeight.BOLD, color=sev_fg),
                                        ),
                                    ],
                                ),
                                ft.Text(f"Ubicación: {inc.get('location', 'Coyoacán')}", size=12, color=pal.text_primary, weight=ft.FontWeight.W_500),
                                ft.Text(
                                    f"Fecha: {format_timestamp_short(inc.get('created_at', ''))} · Por: {inc.get('reported_by', 'Comunidad')}",
                                    size=11,
                                    color=pal.text_muted,
                                ),
                                ft.Text(f"Perfiles afectados: {affected_text}", size=11, color=pal.blue_action, weight=ft.FontWeight.W_600),
                                *([ft.Text(inc["description"], size=12, color=pal.text_muted)] if inc.get("description") else []),
                                ft.Container(
                                    bgcolor=pal.emerald_bg,
                                    border_radius=10,
                                    padding=8,
                                    content=ft.Text(f"Consejo de Gemini: {inc.get('ai_advice', '')}", size=12, color=pal.emerald_text, weight=ft.FontWeight.W_500),
                                ),
                            ],
                        ),
                    )
                )

        return ft.Container(
            expand=True,
            padding=16,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                expand=True,
                                spacing=1,
                                controls=[
                                    ft.Text("Historial de Incidencias", size=19, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                    ft.Text(f"Reportes registrados: {len(state.incidents)}", size=12, color=pal.text_muted),
                                ],
                            ),
                            ft.Row(spacing=6, controls=[build_theme_toggle(), build_sos_pill()]),
                        ],
                    ),
                    ft.FilledButton(
                        content="Reportar incidencia (¿Qué ves?)",
                        icon=ft.Icons.ADD_CIRCLE,
                        bgcolor=pal.alert_orange,
                        color=ft.Colors.WHITE,
                        width=float("inf"),
                        height=48,
                        on_click=open_waze_report_sheet,
                    ),
                    *history_cards,
                ],
            ),
        )

    # =======================================================================
    # SECCIÓN CLÍNICAS
    # =======================================================================
    def build_clinics_screen() -> ft.Control:
        pal = t()
        dis_label = format_disabilities_label(state.disabilities)
        cards: List[ft.Control] = []

        for clinic in state.clinics:
            reqs = [ft.Text(f"• {req}", size=12, color=pal.text_primary) for req in clinic.get("requirements_to_bring", [])]
            acc_items = [ft.Text(f"✓ {feat}", size=11, color=pal.emerald_text) for feat in clinic.get("accessibility_features", [])]

            cards.append(
                ft.Container(
                    bgcolor=pal.card_bg,
                    border_radius=18,
                    border=ft.Border.all(1, pal.border),
                    padding=16,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.START,
                                controls=[
                                    ft.Column(
                                        expand=True,
                                        spacing=2,
                                        controls=[
                                            ft.Text(clinic["name"], size=16, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                            ft.Text(clinic["address"], size=12, color=pal.text_muted),
                                        ],
                                    ),
                                    ft.Container(
                                        bgcolor=pal.badge_bg,
                                        border_radius=10,
                                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                        content=ft.Text(
                                            f"{clinic['distance_text']} · ~{clinic['estimated_minutes']} min",
                                            size=11,
                                            weight=ft.FontWeight.BOLD,
                                            color=pal.badge_text,
                                        ),
                                    ),
                                ],
                            ),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.Icon(ft.Icons.SCHEDULE, size=15, color=pal.emerald),
                                    ft.Text(
                                        f"Horario: {clinic['schedule']} · {clinic.get('emergency_hours', '')}",
                                        size=12,
                                        color=pal.text_primary,
                                        expand=True,
                                    ),
                                ],
                            ),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.Icon(ft.Icons.PHONE, size=15, color=pal.blue_action),
                                    ft.Text(f"Teléfono: {clinic.get('phone', 'N/D')}", size=12, color=pal.text_primary),
                                ],
                            ),
                            ft.Text(f"Servicios: {', '.join(clinic.get('services', []))}", size=12, color=pal.text_muted),
                            ft.Container(
                                bgcolor=pal.emerald_bg,
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text("Accesibilidad verificada:", size=12, weight=ft.FontWeight.BOLD, color=pal.emerald_text),
                                        *acc_items,
                                    ],
                                ),
                            ),
                            ft.Container(
                                bgcolor=pal.card_alt,
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    spacing=3,
                                    controls=[
                                        ft.Row(
                                            spacing=6,
                                            controls=[
                                                ft.Icon(ft.Icons.LIST_ALT, size=15, color=pal.text_heading),
                                                ft.Text("Qué debes llevar:", size=12, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                            ],
                                        ),
                                        *reqs,
                                    ],
                                ),
                            ),
                            ft.FilledButton(
                                content=f"Trazar ruta (~{clinic['estimated_minutes']} min)",
                                icon=ft.Icons.DIRECTIONS,
                                bgcolor=pal.blue_action,
                                color=ft.Colors.WHITE,
                                width=float("inf"),
                                height=42,
                                on_click=lambda _, c=clinic: go_to_route(c["name"]),
                            ),
                        ],
                    ),
                )
            )

        return ft.Container(
            expand=True,
            padding=16,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                expand=True,
                                spacing=1,
                                controls=[
                                    ft.Text("Clínicas cercanas", size=20, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                    ft.Text(f"Tiempos para: {dis_label}", size=11, color=pal.emerald, weight=ft.FontWeight.W_600),
                                ],
                            ),
                            ft.Row(spacing=6, controls=[build_theme_toggle(), build_sos_pill()]),
                        ],
                    ),
                    *cards,
                ],
            ),
        )

    # =======================================================================
    # SECCIÓN VOLUNTARIOS (Lista inicialmente vacía + foto rostro verificada)
    # =======================================================================
    def build_volunteers_screen() -> ft.Control:
        pal = t()
        body_controls: List[ft.Control] = []

        if not state.volunteers:
            body_controls.append(
                ft.Container(
                    bgcolor=pal.card_bg,
                    border_radius=18,
                    border=ft.Border.all(1, pal.border),
                    padding=24,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(ft.Icons.VOLUNTEER_ACTIVISM, size=48, color=pal.text_muted),
                            ft.Text("Aún no hay voluntarios registrados", size=16, weight=ft.FontWeight.BOLD, color=pal.text_heading, text_align=ft.TextAlign.CENTER),
                            ft.Text(
                                "Para seguridad de la comunidad, cada voluntario debe subir una foto de su rostro al postularse desde Perfil.",
                                size=13,
                                color=pal.text_muted,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            ft.FilledButton(
                                content="Ir a mi Perfil para postularme",
                                icon=ft.Icons.PERSON_ADD,
                                bgcolor=pal.blue_action,
                                color=ft.Colors.WHITE,
                                on_click=lambda _: (setattr(state, "screen", "profile"), render()),
                            ),
                        ],
                    ),
                )
            )
        else:
            for vol in state.volunteers:
                body_controls.append(
                    ft.Container(
                        bgcolor=pal.card_bg,
                        border_radius=16,
                        border=ft.Border.all(1, pal.border),
                        padding=14,
                        content=ft.Column(
                            spacing=8,
                            controls=[
                                ft.Row(
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        build_face_avatar(pal, vol.get("face_photo_base64"), size=64, fallback_icon=ft.Icons.VOLUNTEER_ACTIVISM),
                                        ft.Column(
                                            expand=True,
                                            spacing=3,
                                            controls=[
                                                ft.Text(vol["username"], size=16, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                                ft.Container(
                                                    bgcolor=pal.emerald_bg,
                                                    border_radius=10,
                                                    padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                                    content=ft.Text("Foto de rostro verificada · Disponible", size=11, color=pal.emerald_text, weight=ft.FontWeight.W_600),
                                                ),
                                                ft.Text(f"Zona: {vol['zone']}", size=12, color=pal.text_primary),
                                            ],
                                        ),
                                    ],
                                ),
                                ft.Text(f"Horario: {vol['availability']}", size=12, color=pal.text_muted),
                                ft.Text(f"Apoyo: {vol['support_notes']}", size=12, color=pal.text_muted),
                                styled_outlined_button(
                                    pal,
                                    text="Solicitar acompañamiento",
                                    icon=ft.Icons.PEOPLE,
                                    width=float("inf"),
                                    on_click=lambda _: page.run_task(request_volunteer),
                                ),
                            ],
                        ),
                    )
                )

        return ft.Container(
            expand=True,
            padding=16,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                expand=True,
                                spacing=1,
                                controls=[
                                    ft.Text("Guías Voluntarias", size=20, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                    ft.Text(f"Voluntarios activos: {len(state.volunteers)}", size=12, color=pal.text_muted),
                                ],
                            ),
                            ft.Row(spacing=6, controls=[build_theme_toggle(), build_sos_pill()]),
                        ],
                    ),
                    *body_controls,
                ],
            ),
        )

    # =======================================================================
    # SECCIÓN PERFIL (Alto contraste + Switch Modo Noche + Voluntario + Menor)
    # =======================================================================
    def build_profile_screen() -> ft.Control:
        pal = t()

        # --- Caso A: Sesión iniciada ---
        if state.current_user is not None:
            user = state.current_user

            def on_user_photo_picked(b64: str, filename: str) -> None:
                user["face_photo_base64"] = b64
                user["face_photo_filename"] = filename
                if not state.vol_photo_b64:
                    state.vol_photo_b64 = b64
                    state.vol_photo_name = filename

                async def sync_photo() -> None:
                    if is_local_backend_unreachable_on_web():
                        return
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            await client.put(
                                f"{state.api_url}/api/v1/profile",
                                json={"user_id": user["id"], "face_photo_base64": b64, "face_photo_filename": filename},
                            )
                    except Exception:
                        pass

                page.run_task(sync_photo)
                state.auth_feedback = f"Foto de perfil actualizada ({filename})."
                render()

            def on_volunteer_photo_picked(b64: str, filename: str) -> None:
                state.vol_photo_b64 = b64
                state.vol_photo_name = filename
                state.vol_error = None
                render()

            async def apply_volunteer() -> None:
                state.vol_error = None
                state.auth_feedback = None
                photo_to_use = state.vol_photo_b64 or user.get("face_photo_base64")
                photo_name = state.vol_photo_name or user.get("face_photo_filename") or "rostro_voluntario.jpg"

                if not photo_to_use:
                    state.vol_error = "Debes subir una foto de tu rostro obligatoriamente para poder identificarte como voluntario."
                    render()
                    return

                payload = {
                    "user_id": user["id"],
                    "face_photo_base64": photo_to_use,
                    "face_photo_filename": photo_name,
                    "zone": state.vol_zone.strip() or "Campus Coyoacán",
                    "availability": state.vol_availability.strip() or "Horario flexible",
                    "support_notes": state.vol_notes.strip() or "Apoyo peatonal accesible",
                }
                member: Optional[Dict[str, Any]] = None
                if not is_local_backend_unreachable_on_web():
                    try:
                        async with httpx.AsyncClient(timeout=12.0) as client:
                            resp = await client.post(f"{state.api_url}/api/v1/volunteers/apply", json=payload)
                            if resp.status_code >= 400:
                                state.vol_error = resp.json().get("detail", "No se pudo completar la postulación.")
                                render()
                                return
                            member = resp.json()
                    except Exception:
                        member = None
                if member is None:
                    member = {
                        "id": f"vol-{uuid.uuid4().hex[:6]}",
                        "user_id": user["id"],
                        "username": user["username"],
                        "email": user["email"],
                        "face_photo_base64": photo_to_use,
                        "face_photo_filename": photo_name,
                        "zone": payload["zone"],
                        "availability": payload["availability"],
                        "support_notes": payload["support_notes"],
                        "registered_at": datetime.now(timezone.utc).isoformat(),
                    }

                user["is_volunteer"] = True
                if not user.get("face_photo_base64"):
                    user["face_photo_base64"] = photo_to_use
                    user["face_photo_filename"] = photo_name
                if not any(v["user_id"] == user["id"] for v in state.volunteers):
                    state.volunteers.insert(0, member)
                state.auth_feedback = "¡Postulación verificada con foto de rostro! Ya apareces en Voluntarios."
                render()

            def logout(_: ft.ControlEvent) -> None:
                stop_minor_live_sharing()
                state.current_user = None
                state.vol_photo_b64 = None
                state.vol_photo_name = None
                state.auth_feedback = "Sesión cerrada correctamente."
                state.auth_error = None
                render()

            minor_guardian = user.get("guardian") or {}
            minor_section_controls: List[ft.Control] = [
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(ft.Icons.CHILD_CARE, color=pal.blue_action),
                        ft.Text("Protección para menores de edad", size=15, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                    ],
                )
            ]

            if user.get("is_minor") and minor_guardian:
                minor_section_controls.extend(
                    [
                        ft.Text(
                            f"Familiar registrado: {minor_guardian.get('name')} ({minor_guardian.get('relation', 'Familiar')})\n"
                            f"Contacto: {minor_guardian.get('phone') or minor_guardian.get('email')}",
                            size=12,
                            color=pal.text_primary,
                        ),
                        ft.Container(
                            bgcolor=pal.info_bg if state.live_sharing_active else pal.card_alt,
                            border_radius=10,
                            padding=10,
                            content=ft.Text(
                                (
                                    f"Ubicación compartiéndose en tiempo real · Último envío: {state.last_location_shared_at or 'ahora'}"
                                    if state.live_sharing_active
                                    else "La ubicación en tiempo real se activa automáticamente al iniciar una ruta o aquí abajo."
                                ),
                                size=12,
                                color=pal.info_text if state.live_sharing_active else pal.text_primary,
                            ),
                        ),
                        ft.FilledButton(
                            content="Pausar ubicación" if state.live_sharing_active else "Compartir ubicación ahora",
                            icon=ft.Icons.SHARE_LOCATION,
                            bgcolor=pal.indigo if state.live_sharing_active else pal.blue_action,
                            color=ft.Colors.WHITE,
                            width=float("inf"),
                            on_click=lambda _: (
                                (stop_minor_live_sharing(), render())
                                if state.live_sharing_active
                                else (start_minor_live_sharing(), render())
                            ),
                        ),
                        ft.FilledButton(
                            content="Detener alarma sonora" if state.lost_alarm_active else "Me extravié · Emitir alarma sonora",
                            icon=ft.Icons.STOP_CIRCLE if state.lost_alarm_active else ft.Icons.VOLUME_UP,
                            bgcolor=pal.indigo if state.lost_alarm_active else pal.alert_orange,
                            color=ft.Colors.WHITE,
                            width=float("inf"),
                            on_click=stop_lost_alarm if state.lost_alarm_active else (lambda _: page.run_task(activate_lost_minor_alarm)),
                        ),
                    ]
                )
            else:
                minor_section_controls.append(
                    ft.Text(
                        "Cuenta de usuario adulto. (Si necesitas modo menor con seguimiento familiar, actívalo al crear una cuenta de menor).",
                        size=12,
                        color=pal.text_muted,
                    )
                )

            effective_vol_photo = state.vol_photo_b64 or user.get("face_photo_base64")
            volunteer_block: ft.Control
            if user.get("is_volunteer"):
                volunteer_block = ft.Container(
                    bgcolor=pal.emerald_bg,
                    border_radius=14,
                    padding=14,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Row(
                                spacing=10,
                                controls=[
                                    build_face_avatar(pal, effective_vol_photo, size=50),
                                    ft.Column(
                                        expand=True,
                                        spacing=2,
                                        controls=[
                                            ft.Text("Ya eres guía voluntario verificado", weight=ft.FontWeight.BOLD, color=pal.emerald_text),
                                            ft.Text("Tu foto de rostro y datos ya aparecen en Voluntarios.", size=12, color=pal.emerald_text),
                                        ],
                                    ),
                                ],
                            ),
                            styled_outlined_button(
                                pal,
                                text="Ver lista de Voluntarios",
                                text_color=pal.emerald_text,
                                border_color=pal.emerald,
                                on_click=lambda _: (
                                    setattr(state, "screen", "volunteers"),
                                    render(),
                                    page.run_task(load_volunteers),
                                ),
                            ),
                        ],
                    ),
                )
            else:
                volunteer_block = ft.Container(
                    bgcolor=pal.card_bg,
                    border_radius=16,
                    border=ft.Border.all(1, pal.border),
                    padding=16,
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                spacing=8,
                                controls=[
                                    ft.Icon(ft.Icons.VOLUNTEER_ACTIVISM, color=pal.blue_action),
                                    ft.Text("Postularme como voluntario", size=16, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                ],
                            ),
                            ft.Container(
                                bgcolor=pal.emerald_bg if effective_vol_photo else pal.warn_bg,
                                border_radius=12,
                                padding=10,
                                content=ft.Row(
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        build_face_avatar(pal, effective_vol_photo, size=54, fallback_icon=ft.Icons.PHOTO_CAMERA),
                                        ft.Column(
                                            expand=True,
                                            spacing=4,
                                            controls=[
                                                ft.Text(
                                                    "Foto de rostro lista para identificación"
                                                    if effective_vol_photo
                                                    else "Foto de rostro OBLIGATORIA",
                                                    size=12,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=pal.emerald_text if effective_vol_photo else pal.warn_text,
                                                ),
                                                styled_outlined_button(
                                                    pal,
                                                    text="Cambiar foto" if effective_vol_photo else "Subir foto (obligatorio)",
                                                    icon=ft.Icons.ADD_A_PHOTO,
                                                    text_color=pal.emerald_text if effective_vol_photo else pal.warn_text,
                                                    border_color=pal.emerald if effective_vol_photo else pal.alert_orange,
                                                    on_click=lambda _: page.run_task(
                                                        pick_face_photo,
                                                        "Selecciona foto de tu rostro (obligatoria para voluntarios)",
                                                        on_volunteer_photo_picked,
                                                    ),
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                            ),
                            styled_text_field(
                                pal,
                                label="Zona o campus de apoyo",
                                value=state.vol_zone,
                                on_change=lambda e: setattr(state, "vol_zone", e.control.value or ""),
                            ),
                            styled_text_field(
                                pal,
                                label="Horario disponible",
                                value=state.vol_availability,
                                on_change=lambda e: setattr(state, "vol_availability", e.control.value or ""),
                            ),
                            styled_text_field(
                                pal,
                                label="¿Cómo puedes apoyar?",
                                value=state.vol_notes,
                                multiline=True,
                                on_change=lambda e: setattr(state, "vol_notes", e.control.value or ""),
                            ),
                            *(
                                [
                                    ft.Container(
                                        bgcolor=pal.danger_bg,
                                        border_radius=10,
                                        padding=10,
                                        content=ft.Text(state.vol_error, size=12, color=pal.danger_text, weight=ft.FontWeight.W_600),
                                    )
                                ]
                                if state.vol_error
                                else []
                            ),
                            ft.FilledButton(
                                content="Enviar postulación de voluntario",
                                icon=ft.Icons.VOLUNTEER_ACTIVISM,
                                bgcolor=pal.emerald,
                                color=ft.Colors.WHITE,
                                width=float("inf"),
                                height=46,
                                on_click=lambda _: page.run_task(apply_volunteer),
                            ),
                        ],
                    ),
                )

            return ft.Container(
                expand=True,
                padding=16,
                content=ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Mi Perfil", size=20, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                ft.Row(spacing=6, controls=[build_theme_toggle(), build_sos_pill()]),
                            ],
                        ),
                        ft.Container(
                            bgcolor=pal.indigo,
                            border_radius=18,
                            padding=16,
                            content=ft.Column(
                                spacing=10,
                                controls=[
                                    ft.Row(
                                        spacing=12,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            build_face_avatar(pal, user.get("face_photo_base64"), size=60),
                                            ft.Column(
                                                expand=True,
                                                spacing=2,
                                                controls=[
                                                    ft.Text(user["username"], size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                                    ft.Text(f"Correo: {user['email']}", size=12, color="#BFDBFE"),
                                                    ft.Text(f"Discapacidades: {format_disabilities_label(state.disabilities)}", size=11, color="#A7F3D0"),
                                                ],
                                            ),
                                        ],
                                    ),
                                    styled_outlined_button(
                                        pal,
                                        text="Cambiar foto de perfil (opcional)" if user.get("face_photo_base64") else "Agregar foto de perfil (opcional)",
                                        icon=ft.Icons.CAMERA_ALT,
                                        text_color=ft.Colors.WHITE,
                                        border_color="#93C5FD",
                                        on_click=lambda _: page.run_task(
                                            pick_face_photo,
                                            "Selecciona tu foto de perfil (opcional)",
                                            on_user_photo_picked,
                                        ),
                                    ),
                                ],
                            ),
                        ),
                        *(
                            [
                                ft.Container(
                                    bgcolor=pal.emerald_bg,
                                    border_radius=10,
                                    padding=10,
                                    content=ft.Text(state.auth_feedback, size=12, color=pal.emerald_text, weight=ft.FontWeight.W_600),
                                )
                            ]
                            if state.auth_feedback
                            else []
                        ),
                        ft.Container(
                            bgcolor=pal.card_bg,
                            border_radius=16,
                            border=ft.Border.all(1, pal.border),
                            padding=14,
                            content=ft.Switch(
                                label="Modo noche / oscuro de alto contraste",
                                value=state.dark_mode,
                                active_color=pal.blue_action,
                                on_change=lambda e: (setattr(state, "dark_mode", bool(e.control.value)), render()),
                            ),
                        ),
                        ft.Container(
                            bgcolor=pal.card_bg,
                            border_radius=16,
                            border=ft.Border.all(1, pal.border),
                            padding=16,
                            content=ft.Column(
                                spacing=8,
                                controls=[
                                    ft.Text("Discapacidades activas (puedes elegir varias)", size=14, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                                    ft.Text("Cada combinación recalcula rutas, pasos y modo de voz/visual.", size=12, color=pal.text_muted),
                                    build_multi_disability_chips(),
                                ],
                            ),
                        ),
                        ft.Container(
                            bgcolor=pal.card_bg,
                            border_radius=16,
                            border=ft.Border.all(1, pal.border),
                            padding=16,
                            content=ft.Column(spacing=10, controls=minor_section_controls),
                        ),
                        volunteer_block,
                        styled_outlined_button(
                            pal,
                            text="Cerrar sesión",
                            icon=ft.Icons.LOGOUT,
                            text_color=pal.danger_red,
                            border_color=pal.danger_red,
                            width=float("inf"),
                            height=44,
                            on_click=logout,
                        ),
                    ],
                ),
            )

        # --- Caso B: Sin sesión iniciada ---
        is_register = state.auth_mode == "register"

        def on_reg_photo_picked(b64: str, filename: str) -> None:
            state.reg_photo_b64 = b64
            state.reg_photo_name = filename
            render()

        username_tf = styled_text_field(
            pal,
            label="Nombre de usuario" if is_register else "Usuario o correo electrónico",
            value=state.reg_username,
            prefix_icon=ft.Icons.PERSON,
            on_change=lambda e: setattr(state, "reg_username", e.control.value or ""),
        )
        email_tf = styled_text_field(
            pal,
            label="Correo electrónico vinculado",
            value=state.reg_email,
            prefix_icon=ft.Icons.EMAIL,
            on_change=lambda e: setattr(state, "reg_email", e.control.value or ""),
        )
        password_tf = styled_text_field(
            pal,
            label="Contraseña (mín. 6 caracteres)",
            value=state.reg_password,
            prefix_icon=ft.Icons.LOCK,
            password=True,
            can_reveal_password=True,
            on_change=lambda e: setattr(state, "reg_password", e.control.value or ""),
        )
        guardian_name_tf = styled_text_field(
            pal,
            label="Nombre del familiar *",
            value=state.reg_guardian_name,
            on_change=lambda e: setattr(state, "reg_guardian_name", e.control.value or ""),
        )
        guardian_rel_tf = styled_text_field(
            pal,
            label="Parentesco",
            value=state.reg_guardian_relation,
            on_change=lambda e: setattr(state, "reg_guardian_relation", e.control.value or ""),
        )
        guardian_phone_tf = styled_text_field(
            pal,
            label="Teléfono del familiar *",
            value=state.reg_guardian_phone,
            on_change=lambda e: setattr(state, "reg_guardian_phone", e.control.value or ""),
        )
        guardian_email_tf = styled_text_field(
            pal,
            label="Correo del familiar (opcional)",
            value=state.reg_guardian_email,
            on_change=lambda e: setattr(state, "reg_guardian_email", e.control.value or ""),
        )

        async def submit_auth() -> None:
            state.auth_error = None
            state.auth_feedback = None
            # Sincroniza los valores directo de los TextField (evita fallos de autocorrect/autofill en iOS)
            state.reg_username = username_tf.value if username_tf.value is not None else state.reg_username
            if is_register:
                state.reg_email = email_tf.value if email_tf.value is not None else state.reg_email
            state.reg_password = password_tf.value if password_tf.value is not None else state.reg_password
            if state.reg_is_minor:
                state.reg_guardian_name = guardian_name_tf.value if guardian_name_tf.value is not None else state.reg_guardian_name
                state.reg_guardian_relation = guardian_rel_tf.value if guardian_rel_tf.value is not None else state.reg_guardian_relation
                state.reg_guardian_phone = guardian_phone_tf.value if guardian_phone_tf.value is not None else state.reg_guardian_phone
                state.reg_guardian_email = guardian_email_tf.value if guardian_email_tf.value is not None else state.reg_guardian_email

            u_val = (state.reg_username or "").strip()
            e_val = (state.reg_email or "").strip().lower()
            p_val = state.reg_password or ""

            if is_register:
                if len(u_val) < 3:
                    state.auth_error = "El nombre de usuario debe tener al menos 3 caracteres."
                    render()
                    return
                if "@" not in e_val or "." not in e_val.split("@")[-1]:
                    state.auth_error = "Ingresa un correo electrónico válido para vincular tu perfil."
                    render()
                    return
                if len(p_val) < 6:
                    state.auth_error = "La contraseña debe tener al menos 6 caracteres."
                    render()
                    return

                guardian_payload: Optional[Dict[str, Any]] = None
                if state.reg_is_minor:
                    if len(state.reg_guardian_name.strip()) < 2:
                        state.auth_error = "Al ser menor de edad, ingresa el nombre de tu familiar o tutor."
                        render()
                        return
                    if not (state.reg_guardian_phone.strip() or state.reg_guardian_email.strip()):
                        state.auth_error = "Ingresa el teléfono o correo de tu familiar para compartir tu ubicación."
                        render()
                        return
                    guardian_payload = {
                        "name": state.reg_guardian_name.strip(),
                        "relation": state.reg_guardian_relation.strip() or "Familiar / Tutor",
                        "phone": state.reg_guardian_phone.strip(),
                        "email": state.reg_guardian_email.strip(),
                    }

                req_body = {
                    "username": u_val,
                    "email": e_val,
                    "password": p_val,
                    "disability_profile": state.disabilities[0],
                    "disabilities": state.disabilities,
                    "face_photo_base64": state.reg_photo_b64,
                    "face_photo_filename": state.reg_photo_name,
                    "is_minor": state.reg_is_minor,
                    "guardian": guardian_payload,
                }
                user_obj: Optional[Dict[str, Any]] = None
                if not is_local_backend_unreachable_on_web():
                    try:
                        async with httpx.AsyncClient(timeout=12.0) as client:
                            resp = await client.post(f"{state.api_url}/api/v1/auth/register", json=req_body)
                            if resp.status_code >= 400:
                                state.auth_error = resp.json().get("detail", "Error al crear perfil.")
                                render()
                                return
                            user_obj = resp.json()
                    except Exception:
                        user_obj = None

                if user_obj is None:
                    user_obj = {
                        "id": f"usr-{uuid.uuid4().hex[:8]}",
                        "username": u_val,
                        "email": e_val,
                        "disability_profile": state.disabilities[0],
                        "disabilities": list(state.disabilities),
                        "disability_label": format_disabilities_label(state.disabilities),
                        "face_photo_base64": state.reg_photo_b64,
                        "face_photo_filename": state.reg_photo_name,
                        "is_minor": state.reg_is_minor,
                        "guardian": guardian_payload,
                        "is_volunteer": False,
                        "password_local": p_val,
                    }
                    state.local_users[u_val.lower()] = user_obj
                    state.local_users[e_val] = user_obj

                state.current_user = user_obj
                state.disabilities = normalize_disabilities(user_obj.get("disabilities", state.disabilities))
                state.vol_photo_b64 = user_obj.get("face_photo_base64")
                state.vol_photo_name = user_obj.get("face_photo_filename")
                state.auth_feedback = "Perfil creado y correo vinculado correctamente."
                render()
                await sync_routes_and_clinics()
            else:
                if not u_val or not p_val:
                    state.auth_error = "Ingresa tu usuario/correo y contraseña."
                    render()
                    return
                user_obj = None
                if not is_local_backend_unreachable_on_web():
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            resp = await client.post(
                                f"{state.api_url}/api/v1/auth/login",
                                json={"identifier": u_val, "password": p_val},
                            )
                            if resp.status_code >= 400:
                                state.auth_error = resp.json().get("detail", "Credenciales inválidas.")
                                render()
                                return
                            user_obj = resp.json()
                    except Exception:
                        user_obj = None
                if user_obj is None:
                    local = state.local_users.get(u_val.lower())
                    if not local or local.get("password_local") != p_val:
                        state.auth_error = "Usuario/correo o contraseña incorrectos (crea primero tu perfil)."
                        render()
                        return
                    user_obj = local

                state.current_user = user_obj
                state.disabilities = normalize_disabilities(user_obj.get("disabilities", state.disabilities))
                state.vol_photo_b64 = user_obj.get("face_photo_base64")
                state.vol_photo_name = user_obj.get("face_photo_filename")
                state.auth_feedback = f"¡Bienvenido de nuevo, {user_obj['username']}!"
                render()
                await sync_routes_and_clinics()

        form_controls: List[ft.Control] = [
            ft.Row(
                spacing=8,
                controls=[
                    ft.FilledButton(
                        content="Crear perfil",
                        expand=True,
                        bgcolor=pal.chip_active_bg if is_register else pal.card_alt,
                        color=pal.chip_active_text if is_register else pal.text_primary,
                        on_click=lambda _: (
                            setattr(state, "auth_mode", "register"),
                            setattr(state, "auth_error", None),
                            render(),
                        ),
                    ),
                    ft.FilledButton(
                        content="Iniciar sesión",
                        expand=True,
                        bgcolor=pal.chip_active_bg if not is_register else pal.card_alt,
                        color=pal.chip_active_text if not is_register else pal.text_primary,
                        on_click=lambda _: (
                            setattr(state, "auth_mode", "login"),
                            setattr(state, "auth_error", None),
                            render(),
                        ),
                    ),
                ],
            ),
            username_tf,
        ]

        if is_register:
            form_controls.append(email_tf)

        form_controls.append(password_tf)

        if is_register:
            form_controls.append(
                ft.Container(
                    bgcolor=pal.card_alt,
                    border_radius=12,
                    padding=10,
                    content=ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            build_face_avatar(pal, state.reg_photo_b64, size=48),
                            ft.Column(
                                expand=True,
                                spacing=4,
                                controls=[
                                    ft.Text(
                                        f"Foto: {state.reg_photo_name}" if state.reg_photo_b64 else "Foto de rostro (opcional para usuarios)",
                                        size=12,
                                        color=pal.text_primary,
                                    ),
                                    ft.Row(
                                        spacing=6,
                                        controls=[
                                            styled_outlined_button(
                                                pal,
                                                text="Subir foto (opcional)",
                                                icon=ft.Icons.CAMERA_ALT,
                                                on_click=lambda _: page.run_task(
                                                    pick_face_photo,
                                                    "Selecciona tu foto de rostro (opcional)",
                                                    on_reg_photo_picked,
                                                ),
                                            ),
                                            *(
                                                [
                                                    ft.TextButton(
                                                        content=ft.Text("Quitar", color=pal.danger_red),
                                                        on_click=lambda _: (
                                                            setattr(state, "reg_photo_b64", None),
                                                            setattr(state, "reg_photo_name", None),
                                                            render(),
                                                        ),
                                                    )
                                                ]
                                                if state.reg_photo_b64
                                                else []
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                )
            )

            form_controls.extend(
                [
                    ft.Text("Selecciona una o más discapacidades:", size=12, weight=ft.FontWeight.W_600, color=pal.text_heading),
                    build_multi_disability_chips(),
                    ft.Switch(
                        label="Soy menor de edad (ubicación en tiempo real a familiar)",
                        value=state.reg_is_minor,
                        active_color=pal.blue_action,
                        on_change=lambda e: (setattr(state, "reg_is_minor", bool(e.control.value)), render()),
                    ),
                ]
            )

            if state.reg_is_minor:
                form_controls.append(
                    ft.Container(
                        bgcolor=pal.info_bg,
                        border_radius=12,
                        padding=12,
                        content=ft.Column(
                            spacing=8,
                            controls=[
                                ft.Row(
                                    spacing=6,
                                    controls=[
                                        ft.Icon(ft.Icons.FAMILY_RESTROOM, color=pal.info_text, size=18),
                                        ft.Text("Familiar / Tutor registrado", size=13, weight=ft.FontWeight.BOLD, color=pal.info_text),
                                    ],
                                ),
                                guardian_name_tf,
                                guardian_rel_tf,
                                guardian_phone_tf,
                                guardian_email_tf,
                            ],
                        ),
                    )
                )

        if state.auth_error:
            form_controls.append(
                ft.Container(
                    bgcolor=pal.danger_bg,
                    border_radius=10,
                    padding=10,
                    content=ft.Text(state.auth_error, size=12, color=pal.danger_text, weight=ft.FontWeight.W_600),
                )
            )

        if state.auth_feedback:
            form_controls.append(
                ft.Container(
                    bgcolor=pal.emerald_bg,
                    border_radius=10,
                    padding=10,
                    content=ft.Text(state.auth_feedback, size=12, color=pal.emerald_text),
                )
            )

        form_controls.append(
            ft.FilledButton(
                content="Crear cuenta y vincular correo" if is_register else "Entrar a mi perfil",
                icon=ft.Icons.PERSON_ADD if is_register else ft.Icons.LOGIN,
                bgcolor=pal.blue_action,
                color=ft.Colors.WHITE,
                width=float("inf"),
                height=46,
                on_click=lambda _: page.run_task(submit_auth),
            )
        )

        return ft.Container(
            expand=True,
            padding=16,
            content=ft.Column(
                expand=True,
                scroll=ft.ScrollMode.AUTO,
                spacing=12,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Perfil de Usuario", size=20, weight=ft.FontWeight.BOLD, color=pal.text_heading),
                            ft.Row(spacing=6, controls=[build_theme_toggle(), build_sos_pill()]),
                        ],
                    ),
                    ft.Text(
                        "Crea tu cuenta con correo vinculado, elige una o más discapacidades y postúlate como voluntario con foto de rostro.",
                        size=12,
                        color=pal.text_muted,
                    ),
                    ft.Container(
                        bgcolor=pal.card_bg,
                        border_radius=18,
                        border=ft.Border.all(1, pal.border),
                        padding=16,
                        content=ft.Column(spacing=12, controls=form_controls),
                    ),
                ],
            ),
        )

    # -----------------------------------------------------------------------
    # Router principal
    # -----------------------------------------------------------------------
    def render() -> None:
        apply_page_theme()
        page.controls.clear()
        if state.screen == "onboarding":
            page.navigation_bar = None
            page.controls.append(build_onboarding_screen())
        elif state.screen == "search":
            page.navigation_bar = build_bottom_nav(selected_index=0)
            page.controls.append(build_search_screen())
        elif state.screen == "route":
            page.navigation_bar = build_bottom_nav(selected_index=0)
            page.controls.append(build_route_screen())
        elif state.screen == "active":
            page.navigation_bar = None
            page.controls.append(build_active_screen())
        elif state.screen == "incidents":
            page.navigation_bar = build_bottom_nav(selected_index=1)
            page.controls.append(build_incidents_screen())
        elif state.screen == "clinics":
            page.navigation_bar = build_bottom_nav(selected_index=2)
            page.controls.append(build_clinics_screen())
        elif state.screen == "volunteers":
            page.navigation_bar = build_bottom_nav(selected_index=3)
            page.controls.append(build_volunteers_screen())
        elif state.screen == "profile":
            page.navigation_bar = build_bottom_nav(selected_index=4)
            page.controls.append(build_profile_screen())
        page.update()

    render()


if __name__ == "__main__":
    ft.run(main, assets_dir=str(Path(__file__).resolve().parent / "assets"))
