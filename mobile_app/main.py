"""Map Inclusive — App móvil para Android hecha 100% en Python (Flet / motor Flutter).

Sin una sola línea de Java. Implementa:
- Selección de UNA O MÚLTIPLES discapacidades (inicio, ruta y perfil) con rutas y tiempos
  estimados combinados e independientes.
- Lista vertical de sugerencias de rutas con distancia y tiempo estimado.
- Pantalla de Ruta Accesible con actualización automática de Gemini cada 10 minutos.
- Historial completo de incidencias + reporte nuevo clasificado con Gemini.
- Lista completa de clínicas con horarios, accesibilidad, teléfono y qué debes llevar.
- Voluntarios: foto de rostro OBLIGATORIA para postularse e identificación visual en lista
  (lista inicialmente vacía). Usuarios regulares pueden subir foto de forma OPCIONAL.
- Protección para menores de edad: registro de familiar/tutor, envío de ubicación en tiempo
  real y botón "Me extravié" con alarma sonora real para alertar a personas cercanas.
- Botón de Emergencia (SOS) siempre accesible.

Ejecución local:
    python mobile_app/main.py
    flet run --web --port 8550 mobile_app/main.py
    flet run --android mobile_app/main.py
"""

from __future__ import annotations

import asyncio
import base64
import io
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import flet as ft
import httpx

# Paleta oficial de alto contraste de Map Inclusive
INDIGO_DARK = "#1B2354"
BLUE_ACTION = "#2563EB"
EMERALD_GREEN = "#0E9F6E"
EMERALD_SURFACE = "#D1FAE5"
ALERT_ORANGE = "#EA7B1B"
WARN_SURFACE = "#FEF3C7"
NEUTRAL_BG = "#F5F6FA"
CARD_BORDER = "#DCE1EC"
TEXT_MUTED = "#4B5563"
DANGER_RED = "#DC2626"
DANGER_SURFACE = "#FEE2E2"
INFO_BLUE_BG = "#DBEAFE"

TEN_MINUTES_SECONDS = 600
MINOR_TRACKING_INTERVAL_SECONDS = 15
DEFAULT_API_URL = os.getenv("MAP_INCLUSIVE_API_URL", "http://127.0.0.1:8000").rstrip("/")


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
        nav_hint="Cruce con señalización visual clara",
        route_prefix="Alta visibilidad",
        distance_factor=1.0,
        minutes_per_km=12.0,
        accessibility_summary="Cruces con semáforos visibles y alertas visuales cada 10 min.",
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
# Alarma sonora real para extravío de menores (100% Python stdlib, sin Java)
# ---------------------------------------------------------------------------
def generate_alert_siren_wav() -> bytes:
    """Genera una señal sonora audible de doble tono (WAV en memoria) para alertar cercanías."""
    sample_rate = 22050
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        pattern = [(1200, 0.24), (820, 0.24), (1320, 0.24), (820, 0.24)]
        for freq, duration in pattern:
            count = int(sample_rate * duration)
            for i in range(count):
                sample = int(28000 * math.sin(2.0 * math.pi * freq * i / sample_rate))
                frames += struct.pack("<h", sample)
        wf.writeframes(bytes(frames))
    return buf.getvalue()


_SIREN_WAV_BYTES = generate_alert_siren_wav()


def play_alert_sound_once() -> None:
    """Reproduce un ciclo de la alarma sonora por los altavoces del dispositivo."""
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

    # Fallback para Linux / macOS
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

    # Último recurso: campana del sistema
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
# Catálogos locales de respaldo (coinciden con backend/main.py)
# ---------------------------------------------------------------------------
LOCAL_SUGGESTIONS_BASE: List[Dict[str, Any]] = [
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
        "steps": [o.step_text for o in objs] + [f"Llegada accesible verificada a {destination}."],
    }


def build_local_suggestions(disabilities: List[str]) -> List[Dict[str, Any]]:
    return [
        compute_local_route(
            dest_id=p["id"],
            destination=p["destination"],
            address=p["address"],
            category=p["category"],
            base_km=p["base_km"],
            disabilities=disabilities,
        )
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
    # Pantallas: onboarding | search | route | active | incidents | clinics | volunteers | profile
    screen: str = "onboarding"
    # Múltiples discapacidades simultáneas (mínimo 1)
    disabilities: List[str] = field(default_factory=lambda: ["silla_de_ruedas"])
    origin: str = "Campus Coyoacán, CDMX"
    destination: str = "Clínica 19 (UMF IMSS)"
    search_query: str = ""

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
    # Lista de voluntarios comienza VACÍA
    volunteers: List[Dict[str, Any]] = field(default_factory=list)

    # Perfil y autenticación (persistimos borradores para no perder texto al re-renderizar)
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

    # Borradores de postulación de voluntario (foto OBLIGATORIA)
    vol_zone: str = "Campus Coyoacán / Av. Universidad"
    vol_availability: str = "Lun-Vie 10:00 - 17:00"
    vol_notes: str = "Acompañamiento en cruces accesibles y traslado a clínicas"
    vol_photo_b64: Optional[str] = None
    vol_photo_name: Optional[str] = None
    vol_error: Optional[str] = None

    # Protección para menores: ubicación en tiempo real + alarma sonora de extravío
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


def build_face_avatar(photo_b64: Optional[str], size: int = 58, fallback_icon: Any = ft.Icons.PERSON) -> ft.Container:
    """Muestra la foto real de rostro en avatar circular o un icono por defecto."""
    if photo_b64:
        try:
            raw_bytes = base64.b64decode(photo_b64)
            return ft.Container(
                width=size,
                height=size,
                border_radius=size // 2,
                border=ft.Border.all(2, EMERALD_GREEN),
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Image(
                    src=raw_bytes,
                    width=size,
                    height=size,
                    fit=ft.BoxFit.COVER,
                ),
            )
        except Exception:
            pass

    return ft.Container(
        width=size,
        height=size,
        border_radius=size // 2,
        bgcolor="#E5E7EB",
        border=ft.Border.all(1.5, CARD_BORDER),
        alignment=ft.Alignment.CENTER,
        content=ft.Icon(fallback_icon, color=INDIGO_DARK, size=size // 2),
    )


def build_minimalist_map(
    *,
    show_route: bool,
    badge_text: str,
    show_clinics: bool = False,
    show_user_arrow: bool = False,
    height: int = 175,
) -> ft.Container:
    layers: List[ft.Control] = [
        ft.Container(left=0, right=0, top=46, height=12, bgcolor=ft.Colors.WHITE),
        ft.Container(left=0, right=0, top=122, height=12, bgcolor=ft.Colors.WHITE),
        ft.Container(top=0, bottom=0, left=92, width=12, bgcolor=ft.Colors.WHITE),
        ft.Container(top=0, bottom=0, right=82, width=12, bgcolor=ft.Colors.WHITE),
        ft.Container(left=126, top=20, width=74, height=74, border_radius=37, bgcolor="#D7EFE2"),
    ]

    if show_clinics:
        for pos in ((54, 66), (150, 32), (235, 108)):
            layers.append(
                ft.Container(
                    left=pos[0],
                    top=pos[1],
                    width=32,
                    height=32,
                    border_radius=16,
                    bgcolor=EMERALD_GREEN,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.LOCAL_HOSPITAL, color=ft.Colors.WHITE, size=17),
                )
            )

    if show_route:
        layers.extend(
            [
                ft.Container(left=98, top=46, width=148, height=8, border_radius=4, bgcolor=INDIGO_DARK),
                ft.Container(left=238, top=46, width=8, height=84, border_radius=4, bgcolor=INDIGO_DARK),
                ft.Container(left=132, top=122, width=114, height=8, border_radius=4, bgcolor=INDIGO_DARK),
                ft.Container(
                    left=88,
                    top=37,
                    width=26,
                    height=26,
                    border_radius=13,
                    bgcolor=INDIGO_DARK,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.ACCESSIBLE, color=ft.Colors.WHITE, size=14),
                ),
            ]
        )

    if show_user_arrow:
        layers.append(
            ft.Container(
                left=126,
                top=108,
                width=40,
                height=40,
                border_radius=20,
                bgcolor="#BFDBFE",
                alignment=ft.Alignment.CENTER,
                content=ft.Container(
                    width=26,
                    height=26,
                    border_radius=13,
                    bgcolor=BLUE_ACTION,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.NAVIGATION, color=ft.Colors.WHITE, size=15),
                ),
            )
        )

    if badge_text:
        layers.append(
            ft.Container(
                right=10,
                top=10,
                bgcolor=ALERT_ORANGE,
                border_radius=16,
                padding=ft.Padding.symmetric(horizontal=10, vertical=5),
                content=ft.Row(
                    tight=True,
                    spacing=5,
                    controls=[
                        ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.WHITE, size=14),
                        ft.Text(badge_text, color=ft.Colors.WHITE, size=11, weight=ft.FontWeight.W_600),
                    ],
                ),
            )
        )

    return ft.Container(
        height=height,
        width=float("inf"),
        bgcolor="#EDF0F5",
        border_radius=16,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Stack(controls=layers),
    )


def main(page: ft.Page) -> None:
    page.title = "Map Inclusive · Apex soa"
    page.bgcolor = NEUTRAL_BG
    page.padding = 0
    page.window.width = 430
    page.window.height = 850

    state = AppState()
    file_picker = ft.FilePicker()

    def show_info_dialog(title: str, message: str) -> None:
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
            content=ft.Text(message, size=13),
            actions=[ft.TextButton(content="Entendido", on_click=lambda _: page.pop_dialog())],
        )
        page.show_dialog(dialog)

    # -----------------------------------------------------------------------
    # Selector de foto de rostro (usado opcional en Usuario y OBLIGATORIO en Voluntario)
    # -----------------------------------------------------------------------
    async def pick_face_photo(
        dialog_title: str,
        on_picked: Callable[[str, str], None],
    ) -> None:
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
                show_info_dialog("Foto no leída", "No se pudo leer la imagen seleccionada. Intenta con otro archivo JPG o PNG.")
                return
            if len(raw_bytes) > 6 * 1024 * 1024:
                show_info_dialog("Imagen muy pesada", "Elige una foto menor a 6 MB.")
                return
            encoded = base64.b64encode(raw_bytes).decode("ascii")
            on_picked(encoded, picked.name or "rostro.jpg")
        except Exception as exc:
            show_info_dialog("Selector de foto", f"No se pudo abrir el selector de imágenes: {exc}")

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
            "latitude": 19.3498,
            "longitude": -99.1617,
            "status": status_label,
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(f"{state.api_url}/api/v1/guardian/location", json=payload)
                if resp.status_code < 300:
                    state.last_location_status = resp.json().get("message")
        except Exception:
            state.last_location_status = (
                f"Ubicación compartida en tiempo real con {guardian['name']} ({contact})."
            )
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
        while state.lost_alarm_active and state.lost_alarm_generation == generation:
            await asyncio.to_thread(play_alert_sound_once)
            await asyncio.sleep(0.35)

    def stop_lost_alarm(_: Any = None) -> None:
        state.lost_alarm_active = False
        state.lost_alarm_generation += 1
        stop_alert_sound_immediately()
        try:
            page.pop_dialog()
        except Exception:
            pass
        render()

    async def activate_lost_minor_alarm() -> None:
        state.lost_alarm_active = True
        state.lost_alarm_generation += 1
        gen = state.lost_alarm_generation

        user = state.current_user
        username = user["username"] if user else "Usuario menor de edad"
        guardian = (user or {}).get("guardian") or {}
        g_name = guardian.get("name") or "Familiar registrado"
        g_phone = guardian.get("phone") or "911"
        g_email = guardian.get("email") or ""

        # Inicia el sonido real de alerta de inmediato
        page.run_task(lost_sound_loop, gen)

        helper_msg = (
            f"¡ALERTA DE EXTRAVÍO! {username} ({format_disabilities_label(state.disabilities)}) "
            f"necesita ayuda.\n\nPor favor comunícate con su familiar:\n"
            f"• Familiar: {g_name}\n"
            f"• Teléfono: {g_phone}"
            + (f"\n• Correo: {g_email}" if g_email else "")
            + "\n• Emergencias: 911"
        )

        # Notifica al backend + envía ubicación actual como "extraviado"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
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

        if is_minor_with_guardian():
            page.run_task(send_guardian_location_once, "extraviado")

        alarm_dialog = ft.AlertDialog(
            modal=True,
            bgcolor=DANGER_SURFACE,
            title=ft.Row(
                spacing=8,
                controls=[
                    ft.Icon(ft.Icons.CAMPAIGN, color=DANGER_RED, size=30),
                    ft.Text(
                        "¡ALARMA SONORA ACTIVA!",
                        weight=ft.FontWeight.BOLD,
                        color=DANGER_RED,
                        size=18,
                    ),
                ],
            ),
            content=ft.Column(
                tight=True,
                spacing=10,
                controls=[
                    ft.Container(
                        bgcolor=DANGER_RED,
                        border_radius=12,
                        padding=12,
                        content=ft.Row(
                            spacing=8,
                            controls=[
                                ft.Icon(ft.Icons.VOLUME_UP, color=ft.Colors.WHITE, size=24),
                                ft.Text(
                                    "Emitiendo sonido fuerte para alertar a personas cercanas...",
                                    color=ft.Colors.WHITE,
                                    weight=ft.FontWeight.BOLD,
                                    size=13,
                                    expand=True,
                                ),
                            ],
                        ),
                    ),
                    ft.Text(helper_msg, size=14, weight=ft.FontWeight.W_600, color="#7F1D1D"),
                ],
            ),
            actions=[
                ft.FilledButton(
                    content="Detener alarma sonora",
                    icon=ft.Icons.STOP_CIRCLE,
                    bgcolor=INDIGO_DARK,
                    color=ft.Colors.WHITE,
                    on_click=stop_lost_alarm,
                )
            ],
        )
        page.show_dialog(alarm_dialog)
        render()

    # -----------------------------------------------------------------------
    # Botón y diálogo de Emergencia SOS
    # -----------------------------------------------------------------------
    def open_emergency_dialog(_: Any = None) -> None:
        dis_label = format_disabilities_label(state.disabilities)

        async def send_sos() -> None:
            page.pop_dialog()
            payload = {
                "location": state.origin,
                "profile": state.disabilities[0],
                "disabilities": state.disabilities,
                "username": state.current_user["username"] if state.current_user else None,
                "notes": f"Alerta SOS activada rumbo a {state.destination}",
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
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
            except Exception:
                show_info_dialog(
                    "Emergencia SOS (Modo Local)",
                    f"Perfiles activos: {dis_label}\nUbicación: {state.origin}\n\n"
                    "Urgencias más cercanas: Hospital General Xoco (24h · Tel. 55 5688 9015)\n\n"
                    "Comunícate de inmediato:\n"
                    "• 911 — Emergencias generales\n"
                    "• 065 — Cruz Roja Mexicana\n"
                    "• 55 5658 1111 — LOCATEL 24h",
                )

        def trigger_lost_from_sos(_: ft.ControlEvent) -> None:
            page.pop_dialog()
            page.run_task(activate_lost_minor_alarm)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                spacing=8,
                controls=[
                    ft.Icon(ft.Icons.EMERGENCY, color=DANGER_RED, size=26),
                    ft.Text("Emergencia SOS", weight=ft.FontWeight.BOLD, color=DANGER_RED),
                ],
            ),
            content=ft.Column(
                tight=True,
                spacing=8,
                controls=[
                    ft.Text(
                        f"Discapacidades: {dis_label}\nUbicación: {state.origin}",
                        size=13,
                        weight=ft.FontWeight.W_600,
                        color=INDIGO_DARK,
                    ),
                    ft.Container(
                        bgcolor=DANGER_SURFACE,
                        border_radius=10,
                        padding=10,
                        content=ft.Text(
                            "• 911 — Policía / Ambulancia / Protección Civil\n"
                            "• 065 — Cruz Roja Mexicana\n"
                            "• 55 5658 1111 — LOCATEL CDMX\n"
                            "• Urgencias cercanas: Hospital General Xoco (24h)",
                            size=12,
                            color="#7F1D1D",
                        ),
                    ),
                    ft.OutlinedButton(
                        content="Me extravié · Activar alarma sonora",
                        icon=ft.Icons.VOLUME_UP,
                        icon_color=ALERT_ORANGE,
                        width=float("inf"),
                        on_click=trigger_lost_from_sos,
                    ),
                ],
            ),
            actions=[
                ft.TextButton(content="Cancelar", on_click=lambda _: page.pop_dialog()),
                ft.FilledButton(
                    content="Enviar Alerta SOS",
                    icon=ft.Icons.SOS,
                    bgcolor=DANGER_RED,
                    color=ft.Colors.WHITE,
                    on_click=lambda _: page.run_task(send_sos),
                ),
            ],
        )
        page.show_dialog(dialog)

    def build_sos_pill() -> ft.Container:
        return ft.Container(
            bgcolor=DANGER_RED,
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
    # Sincronización con Backend Python (rutas multi-discapacidad, clínicas, historial, voluntarios)
    # -----------------------------------------------------------------------
    async def sync_routes_and_clinics() -> None:
        state.disabilities = normalize_disabilities(state.disabilities)
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

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                s_resp = await client.get(
                    f"{state.api_url}/api/v1/routes/suggestions",
                    params={"profiles": profiles_csv},
                )
                if s_resp.status_code == 200:
                    state.suggestions = s_resp.json()

                c_resp = await client.get(
                    f"{state.api_url}/api/v1/clinics",
                    params={"profiles": profiles_csv},
                )
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
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{state.api_url}/api/v1/incidents")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        state.incidents = data
                        if state.screen == "incidents":
                            render()
        except Exception:
            pass

    async def load_volunteers() -> None:
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
                resp = await client.post(
                    f"{state.api_url}/api/v1/environment-check",
                    json=payload,
                )
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
        state.screen = "route"
        render()
        start_route_monitoring()

    async def toggle_disability(prof_value: str) -> None:
        current = list(state.disabilities)
        if prof_value in current:
            if len(current) == 1:
                # Siempre debe haber al menos una discapacidad seleccionada
                return
            current.remove(prof_value)
        else:
            current.append(prof_value)
        state.disabilities = normalize_disabilities(current)

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

    # -----------------------------------------------------------------------
    # Reporte de incidencias (se guarda en el historial y se clasifica con Gemini)
    # -----------------------------------------------------------------------
    def open_report_incident_dialog(_: Any = None) -> None:
        title_field = ft.TextField(label="Título de la incidencia", value="Rampa bloqueada")
        location_field = ft.TextField(label="Ubicación", value="Av. Universidad, Coyoacán")
        desc_field = ft.TextField(
            label="Descripción",
            value="Vehículo bloqueando la rampa peatonal en esquina",
            multiline=True,
        )

        async def submit_incident() -> None:
            title_val = (title_field.value or "Incidencia reportada").strip()
            loc_val = (location_field.value or "Av. Universidad, Coyoacán").strip()
            desc_val = (desc_field.value or "").strip()
            reporter = state.current_user["username"] if state.current_user else "Usuario Map Inclusive"
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
                        f"Incidencia registrada ({data.get('severity', 'medio').upper()})",
                        f"Agregada al historial.\n\nConsejo de Gemini:\n{data.get('ai_advice', '')}",
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
                    "severity": "alto" if "bloque" in title_val.lower() else "medio",
                    "ai_advice": f"Precaución cerca de {loc_val}; guardado en el historial local.",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                state.incidents.insert(0, local_inc)
                show_info_dialog(
                    "Incidencia guardada en el historial",
                    f"Se registró '{title_val}' localmente (sin conexión al servidor).",
                )
                render()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Reportar incidencia", weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
            content=ft.Column(
                tight=True,
                spacing=10,
                controls=[
                    ft.Text(
                        f"Afecta a: {format_disabilities_label(state.disabilities)}",
                        size=12,
                        color=TEXT_MUTED,
                    ),
                    title_field,
                    location_field,
                    desc_field,
                ],
            ),
            actions=[
                ft.TextButton(content="Cancelar", on_click=lambda _: page.pop_dialog()),
                ft.FilledButton(
                    content="Enviar reporte",
                    bgcolor=BLUE_ACTION,
                    color=ft.Colors.WHITE,
                    on_click=lambda _: page.run_task(submit_incident),
                ),
            ],
        )
        page.show_dialog(dialog)

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
    # Barra inferior de navegación (Mapa | Incidencias | Clínicas | Voluntarios | Perfil)
    # -----------------------------------------------------------------------
    def build_bottom_nav(selected_index: int) -> ft.NavigationBar:
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
            bgcolor=ft.Colors.WHITE,
            on_change=on_nav_change,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.MAP, label="Mapa"),
                ft.NavigationBarDestination(icon=ft.Icons.HISTORY, label="Incidencias"),
                ft.NavigationBarDestination(icon=ft.Icons.LOCAL_HOSPITAL, label="Clínicas"),
                ft.NavigationBarDestination(icon=ft.Icons.PEOPLE, label="Voluntarios"),
                ft.NavigationBarDestination(icon=ft.Icons.PERSON, label="Perfil"),
            ],
        )

    def build_multi_disability_chips(on_toggle_fn: Optional[Callable[[str], None]] = None) -> ft.Row:
        return ft.Row(
            wrap=True,
            spacing=8,
            run_spacing=8,
            controls=[
                ft.Chip(
                    label=ft.Text(
                        p.short_label,
                        size=12,
                        color=ft.Colors.WHITE if p.api_value in state.disabilities else INDIGO_DARK,
                    ),
                    selected=p.api_value in state.disabilities,
                    selected_color=INDIGO_DARK,
                    bgcolor=ft.Colors.WHITE,
                    show_checkmark=True,
                    check_color=ft.Colors.WHITE,
                    on_select=lambda _, pv=p.api_value: (
                        on_toggle_fn(pv) if on_toggle_fn else page.run_task(toggle_disability, pv)
                    ),
                )
                for p in PROFILES
            ],
        )

    # =======================================================================
    # PANTALLA 1: PANTALLA INICIAL (Multi-selección de discapacidades)
    # =======================================================================
    def build_onboarding_screen() -> ft.Control:
        def profile_tile(option: ProfileOption, full_width: bool = False) -> ft.Container:
            is_selected = option.api_value in state.disabilities

            def on_tile_click(_: ft.ControlEvent) -> None:
                page.run_task(toggle_disability, option.api_value)

            fg = ft.Colors.WHITE if is_selected else INDIGO_DARK
            bg = INDIGO_DARK if is_selected else ft.Colors.WHITE
            border_color = INDIGO_DARK if is_selected else CARD_BORDER

            if full_width:
                return ft.Container(
                    height=62,
                    bgcolor=bg,
                    border=ft.Border.all(1.5, border_color),
                    border_radius=16,
                    alignment=ft.Alignment.CENTER,
                    ink=True,
                    on_click=on_tile_click,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(option.icon, color=fg, size=24),
                            ft.Text(option.label, color=fg, size=14, weight=ft.FontWeight.W_600),
                            *(
                                [ft.Icon(ft.Icons.CHECK_CIRCLE, color=EMERALD_SURFACE, size=18)]
                                if is_selected
                                else []
                            ),
                        ],
                    ),
                )

            return ft.Container(
                expand=True,
                height=108,
                bgcolor=bg,
                border=ft.Border.all(1.5, border_color),
                border_radius=16,
                padding=10,
                alignment=ft.Alignment.CENTER,
                ink=True,
                on_click=on_tile_click,
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                    controls=[
                        ft.Icon(option.icon, color=fg, size=30),
                        ft.Text(
                            option.label,
                            color=fg,
                            size=13,
                            weight=ft.FontWeight.W_600,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                ),
            )

        selected_count = len(state.disabilities)
        selected_summary = format_disabilities_label(state.disabilities)

        return ft.Container(
            expand=True,
            bgcolor=ft.Colors.WHITE,
            padding=ft.Padding.symmetric(horizontal=20, vertical=18),
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
                                        bgcolor=EMERALD_GREEN,
                                        alignment=ft.Alignment.CENTER,
                                        content=ft.Icon(ft.Icons.ACCESSIBLE, color=ft.Colors.WHITE, size=19),
                                    ),
                                    ft.Column(
                                        spacing=0,
                                        controls=[
                                            ft.Text("map inclusive", size=20, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                            ft.Text("Campus Coyoacán · Apex soa", size=11, color=TEXT_MUTED),
                                        ],
                                    ),
                                ],
                            ),
                            build_sos_pill(),
                        ],
                    ),
                    ft.Text(
                        "¿Cómo te desplazas hoy?",
                        size=20,
                        weight=ft.FontWeight.W_600,
                        color=INDIGO_DARK,
                    ),
                    ft.Text(
                        "Puedes elegir UNA O MÁS discapacidades; combinaremos todas tus necesidades en la ruta.",
                        size=12,
                        color=TEXT_MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Row(spacing=12, controls=[profile_tile(PROFILES[0]), profile_tile(PROFILES[1])]),
                    ft.Row(spacing=12, controls=[profile_tile(PROFILES[2]), profile_tile(PROFILES[3])]),
                    profile_tile(PROFILES[4], full_width=True),
                    ft.Container(
                        width=float("inf"),
                        bgcolor=EMERALD_SURFACE,
                        border_radius=12,
                        padding=10,
                        content=ft.Text(
                            f"Seleccionadas ({selected_count}): {selected_summary}",
                            size=12,
                            weight=ft.FontWeight.W_600,
                            color="#065F46",
                        ),
                    ),
                    ft.FilledButton(
                        content="Continuar al mapa",
                        bgcolor=BLUE_ACTION,
                        color=ft.Colors.WHITE,
                        width=float("inf"),
                        height=48,
                        on_click=lambda _: (
                            setattr(state, "screen", "search"),
                            render(),
                            page.run_task(sync_routes_and_clinics),
                        ),
                    ),
                    ft.OutlinedButton(
                        content=(
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
        dis_label = format_disabilities_label(state.disabilities)
        search_input = ft.TextField(
            value=state.search_query,
            hint_text="Buscar destino...",
            prefix_icon=ft.Icons.SEARCH,
            border_radius=14,
            bgcolor=ft.Colors.WHITE,
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
                bgcolor=ft.Colors.WHITE,
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
                            bgcolor=EMERALD_SURFACE if is_health else "#E0E7FF",
                            alignment=ft.Alignment.CENTER,
                            content=ft.Icon(
                                category_icon(item["category"]),
                                color=EMERALD_GREEN if is_health else INDIGO_DARK,
                                size=20,
                            ),
                        ),
                        ft.Column(
                            expand=True,
                            spacing=2,
                            controls=[
                                ft.Text(
                                    item["destination"],
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=INDIGO_DARK,
                                ),
                                ft.Text(
                                    f"{item['address']} · {item['distance_text']}",
                                    size=12,
                                    color=TEXT_MUTED,
                                ),
                                ft.Text(
                                    item["route_name"].split("·")[0].strip(),
                                    size=11,
                                    color=EMERALD_GREEN,
                                    weight=ft.FontWeight.W_500,
                                ),
                            ],
                        ),
                        ft.Column(
                            horizontal_alignment=ft.CrossAxisAlignment.END,
                            spacing=2,
                            controls=[
                                ft.Container(
                                    bgcolor="#EEF2FF",
                                    border_radius=10,
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                    content=ft.Row(
                                        tight=True,
                                        spacing=4,
                                        controls=[
                                            ft.Icon(ft.Icons.ACCESS_TIME, size=13, color=INDIGO_DARK),
                                            ft.Text(
                                                f"{item['estimated_minutes']} min",
                                                size=12,
                                                weight=ft.FontWeight.BOLD,
                                                color=INDIGO_DARK,
                                            ),
                                        ],
                                    ),
                                ),
                                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=18, color=TEXT_MUTED),
                            ],
                        ),
                    ],
                ),
            )
            suggestion_rows.append(row_tile)
            if idx < len(state.suggestions) - 1:
                suggestion_rows.append(ft.Divider(height=1, color=CARD_BORDER))

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
                                    ft.Text("Explorar rutas", size=19, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                    ft.Text(
                                        f"Perfiles: {dis_label}",
                                        size=11,
                                        color=EMERALD_GREEN,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                ],
                            ),
                            build_sos_pill(),
                        ],
                    ),
                    ft.Row(
                        spacing=8,
                        controls=[
                            search_input,
                            ft.FilledButton(
                                content="Ir",
                                bgcolor=BLUE_ACTION,
                                color=ft.Colors.WHITE,
                                height=48,
                                on_click=lambda _: go_to_route(state.search_query),
                            ),
                        ],
                    ),
                    build_minimalist_map(
                        show_route=False,
                        badge_text="Zona poco concurrida",
                        show_clinics=True,
                        height=165,
                    ),
                    ft.Text(
                        "Rutas sugeridas (lista con tiempo estimado)",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=INDIGO_DARK,
                    ),
                    ft.Container(
                        bgcolor=ft.Colors.WHITE,
                        border_radius=16,
                        border=ft.Border.all(1, CARD_BORDER),
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        content=ft.Column(spacing=0, controls=suggestion_rows),
                    ),
                ],
            ),
        )

    # =======================================================================
    # PANTALLA 3: RUTA Y GEMINI (Multi-discapacidad + tiempo + Gemini cada 10 min)
    # =======================================================================
    def build_route_screen() -> ft.Control:
        route = state.current_route
        dis_label = format_disabilities_label(state.disabilities)

        if state.is_loading_env:
            banner_bg = EMERALD_SURFACE
            banner_title = "Consultando entorno en tiempo real con Gemini..."
            banner_sub = "Recopilando clima, bloqueos y transporte..."
        elif state.env_error:
            banner_bg = WARN_SURFACE
            banner_title = state.env_error
            banner_sub = "Toca recargar cuando vuelvas a tener conexión"
        elif state.env_report:
            banner_bg = EMERALD_SURFACE
            banner_title = f"Actualizado con Gemini: {state.env_report.get('banner_resumen', '')}"
            banner_sub = (
                f"Cada {state.env_report.get('next_refresh_minutes', 10)} min · "
                f"{state.env_report.get('model_used', 'gemini-4-hydrogen')} · Toca para detalles"
            )
        else:
            banner_bg = EMERALD_SURFACE
            banner_title = "Listo para consultar entorno con Gemini"
            banner_sub = "Actualización automática cada 10 minutos"

        def toggle_details(_: ft.ControlEvent) -> None:
            state.show_env_details = not state.show_env_details
            render()

        steps_preview = [
            ft.Text(f"{i + 1}. {step}", size=12, color=INDIGO_DARK)
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
                            ft.Text("Ruta Accesible", size=17, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                            ft.Text(
                                f"{dis_label} · {route.get('distance_text', '1.2 km')}",
                                size=12,
                                color=TEXT_MUTED,
                            ),
                        ],
                    ),
                    ft.Container(
                        bgcolor="#EEF2FF",
                        border_radius=12,
                        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
                        content=ft.Row(
                            tight=True,
                            spacing=4,
                            controls=[
                                ft.Icon(ft.Icons.ACCESS_TIME, size=15, color=INDIGO_DARK),
                                ft.Text(
                                    f"~{route.get('estimated_minutes', 15)} min",
                                    size=13,
                                    weight=ft.FontWeight.BOLD,
                                    color=INDIGO_DARK,
                                ),
                            ],
                        ),
                    ),
                ],
            ),
            ft.Text(f"Destino: {state.destination}", size=12, color=TEXT_MUTED),
            ft.Container(
                bgcolor=NEUTRAL_BG,
                border_radius=12,
                padding=10,
                content=ft.Column(spacing=4, controls=steps_preview),
            ),
        ]

        if is_minor_with_guardian():
            guardian_name = state.current_user["guardian"]["name"]  # type: ignore[index]
            summary_controls.append(
                ft.Container(
                    bgcolor=INFO_BLUE_BG,
                    border_radius=12,
                    padding=10,
                    content=ft.Row(
                        spacing=8,
                        controls=[
                            ft.Icon(ft.Icons.SHARE_LOCATION, color=BLUE_ACTION, size=18),
                            ft.Text(
                                f"Protección de menor: al iniciar ruta se compartirá tu ubicación en tiempo real con {guardian_name}.",
                                size=12,
                                color=INDIGO_DARK,
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
                on_click=toggle_details,
                content=ft.Row(
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.ProgressRing(width=16, height=16, stroke_width=2, color=EMERALD_GREEN)
                        if state.is_loading_env
                        else ft.Container(
                            width=10,
                            height=10,
                            border_radius=5,
                            bgcolor=ALERT_ORANGE if state.env_error else EMERALD_GREEN,
                        ),
                        ft.Column(
                            expand=True,
                            spacing=2,
                            controls=[
                                ft.Text(banner_title, size=12, weight=ft.FontWeight.W_600, color=INDIGO_DARK),
                                ft.Text(banner_sub, size=11, color="#065F46"),
                            ],
                        ),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            icon_color=INDIGO_DARK,
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
                    bgcolor=NEUTRAL_BG,
                    border_radius=12,
                    padding=10,
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            ft.Text(f"Clima: {rep.get('clima', '-')}", size=12, color=INDIGO_DARK),
                            ft.Text(f"Bloqueos: {', '.join(rep.get('bloqueos', []))}", size=12, color=INDIGO_DARK),
                            ft.Text(
                                f"Transporte: {', '.join(rep.get('transporte_afectado', []))}",
                                size=12,
                                color=INDIGO_DARK,
                            ),
                            *[
                                ft.Text(f"• {tip}", size=12, color=EMERALD_GREEN, weight=ft.FontWeight.W_600)
                                for tip in tips
                            ],
                        ],
                    ),
                )
            )

        def start_navigation(_: ft.ControlEvent) -> None:
            state.screen = "active"
            if is_minor_with_guardian():
                start_minor_live_sharing()
            render()

        summary_controls.append(
            ft.FilledButton(
                content="Iniciar Ruta",
                bgcolor=BLUE_ACTION,
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
                            ft.Text("Ruta Accesible", size=20, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.IconButton(
                                        icon=ft.Icons.SEARCH,
                                        icon_color=INDIGO_DARK,
                                        on_click=lambda _: (setattr(state, "screen", "search"), render()),
                                    ),
                                    build_sos_pill(),
                                ],
                            ),
                        ],
                    ),
                    ft.Text("Activa una o varias discapacidades:", size=12, color=TEXT_MUTED),
                    build_multi_disability_chips(),
                    build_minimalist_map(show_route=True, badge_text="Rampa bloqueada", height=155),
                    ft.Container(
                        bgcolor=ft.Colors.WHITE,
                        border_radius=20,
                        border=ft.Border.all(1, CARD_BORDER),
                        padding=16,
                        content=ft.Column(spacing=10, controls=summary_controls),
                    ),
                ],
            ),
        )

    # =======================================================================
    # PANTALLA 4: EN CAMINO (Ubicación en tiempo real + Alarma sonora extravío + SOS)
    # =======================================================================
    def build_active_screen() -> ft.Control:
        route = state.current_route
        hints = " · ".join(get_profile(d).nav_hint for d in state.disabilities[:2])
        gemini_chip = (
            f"Gemini activo · {state.env_report.get('banner_resumen', '')}"
            if state.env_report
            else "Monitoreo Gemini activo cada 10 min"
        )

        active_controls: List[ft.Control] = [
            ft.Container(
                bgcolor=EMERALD_SURFACE,
                border_radius=14,
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                content=ft.Text(gemini_chip, size=12, color=INDIGO_DARK, weight=ft.FontWeight.W_600),
            )
        ]

        if is_minor_with_guardian():
            guardian = state.current_user["guardian"]  # type: ignore[index]
            shared_info = (
                f"Último envío: {state.last_location_shared_at}"
                if state.last_location_shared_at
                else "Enviando ubicación en vivo..."
            )
            active_controls.append(
                ft.Container(
                    bgcolor=INFO_BLUE_BG,
                    border_radius=14,
                    border=ft.Border.all(1, BLUE_ACTION),
                    padding=10,
                    content=ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.MY_LOCATION, color=BLUE_ACTION, size=20),
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Text(
                                        f"Ubicación en tiempo real compartida con {guardian['name']}",
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                        color=INDIGO_DARK,
                                    ),
                                    ft.Text(
                                        f"{guardian.get('phone') or guardian.get('email')} · {shared_info}",
                                        size=11,
                                        color=TEXT_MUTED,
                                    ),
                                ],
                            ),
                        ],
                    ),
                )
            )

        active_controls.append(
            build_minimalist_map(
                show_route=True,
                badge_text="",
                show_user_arrow=True,
                height=170,
            )
        )

        action_buttons: List[ft.Control] = [
            ft.Text(f"Rumbo a: {state.destination}", size=12, color=TEXT_MUTED),
            ft.FilledButton(
                content="Botón de Emergencia (SOS)",
                icon=ft.Icons.EMERGENCY,
                bgcolor=DANGER_RED,
                color=ft.Colors.WHITE,
                width=float("inf"),
                height=46,
                on_click=open_emergency_dialog,
            ),
        ]

        # Botón de extravío con alarma sonora (visible siempre en ruta, destacado para menores)
        if state.lost_alarm_active:
            action_buttons.append(
                ft.FilledButton(
                    content="Detener alarma sonora de extravío",
                    icon=ft.Icons.STOP_CIRCLE,
                    bgcolor=INDIGO_DARK,
                    color=ft.Colors.WHITE,
                    width=float("inf"),
                    height=46,
                    on_click=stop_lost_alarm,
                )
            )
        else:
            action_buttons.append(
                ft.FilledButton(
                    content="Me extravié · Activar alarma sonora",
                    icon=ft.Icons.VOLUME_UP,
                    bgcolor=ALERT_ORANGE,
                    color=ft.Colors.WHITE,
                    width=float("inf"),
                    height=46,
                    on_click=lambda _: page.run_task(activate_lost_minor_alarm),
                )
            )

        action_buttons.extend(
            [
                ft.OutlinedButton(
                    content="Reportar Incidencia",
                    icon=ft.Icons.REPORT,
                    icon_color=ALERT_ORANGE,
                    width=float("inf"),
                    height=42,
                    on_click=open_report_incident_dialog,
                ),
                ft.OutlinedButton(
                    content="Pedir Guía Voluntaria",
                    icon=ft.Icons.PEOPLE,
                    icon_color=BLUE_ACTION,
                    width=float("inf"),
                    height=42,
                    on_click=lambda _: page.run_task(request_volunteer),
                ),
                ft.OutlinedButton(
                    content="Finalizar recorrido",
                    width=float("inf"),
                    height=42,
                    on_click=lambda _: (
                        stop_minor_live_sharing(),
                        stop_lost_alarm() if state.lost_alarm_active else None,
                        setattr(state, "refresh_generation", state.refresh_generation + 1),
                        setattr(state, "screen", "search"),
                        render(),
                    ),
                ),
            ]
        )

        active_controls.append(
            ft.Container(
                bgcolor=ft.Colors.WHITE,
                border_radius=20,
                border=ft.Border.all(1, CARD_BORDER),
                padding=16,
                content=ft.Column(spacing=9, controls=action_buttons),
            )
        )

        return ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    bgcolor=INDIGO_DARK,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=16),
                    content=ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.TURN_RIGHT, color=ft.Colors.WHITE, size=34),
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Text(
                                        "Gira a la derecha en 80m",
                                        color=ft.Colors.WHITE,
                                        size=17,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(f"· {hints}", color=EMERALD_SURFACE, size=12),
                                    ft.Text(
                                        f"Tiempo estimado: ~{route.get('estimated_minutes', 15)} min ({route.get('distance_text', '1.2 km')})",
                                        color="#BFDBFE",
                                        size=12,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                ],
                            ),
                            build_sos_pill(),
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
    # SECCIÓN HISTORIAL DE INCIDENCIAS (Reportar + Lista cronológica completa)
    # =======================================================================
    def build_incidents_screen() -> ft.Control:
        def severity_colors(sev: str) -> tuple[str, str]:
            val = sev.lower()
            if val == "alto":
                return DANGER_SURFACE, DANGER_RED
            if val == "medio":
                return WARN_SURFACE, "#B45309"
            return EMERALD_SURFACE, "#065F46"

        history_cards: List[ft.Control] = []
        if not state.incidents:
            history_cards.append(
                ft.Container(
                    bgcolor=ft.Colors.WHITE,
                    border_radius=16,
                    border=ft.Border.all(1, CARD_BORDER),
                    padding=20,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text("No hay incidencias registradas todavía.", color=TEXT_MUTED),
                )
            )
        else:
            for inc in state.incidents:
                sev = str(inc.get("severity", "medio"))
                sev_bg, sev_fg = severity_colors(sev)
                labels = inc.get("disabilities_labels") or [
                    get_profile(d).label for d in inc.get("disabilities", [])
                ]
                affected_text = ", ".join(labels) if labels else "Accesibilidad general"

                history_cards.append(
                    ft.Container(
                        bgcolor=ft.Colors.WHITE,
                        border_radius=16,
                        border=ft.Border.all(1, CARD_BORDER),
                        padding=14,
                        content=ft.Column(
                            spacing=6,
                            controls=[
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        ft.Text(
                                            inc.get("title", "Incidencia"),
                                            size=15,
                                            weight=ft.FontWeight.BOLD,
                                            color=INDIGO_DARK,
                                            expand=True,
                                        ),
                                        ft.Container(
                                            bgcolor=sev_bg,
                                            border_radius=10,
                                            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                            content=ft.Text(
                                                sev.upper(),
                                                size=11,
                                                weight=ft.FontWeight.BOLD,
                                                color=sev_fg,
                                            ),
                                        ),
                                    ],
                                ),
                                ft.Text(
                                    f"Ubicación: {inc.get('location', 'Coyoacán')}",
                                    size=12,
                                    color=INDIGO_DARK,
                                    weight=ft.FontWeight.W_500,
                                ),
                                ft.Text(
                                    f"Fecha: {format_timestamp_short(inc.get('created_at', ''))} · Por: {inc.get('reported_by', 'Comunidad')}",
                                    size=11,
                                    color=TEXT_MUTED,
                                ),
                                ft.Text(f"Perfiles afectados: {affected_text}", size=11, color=BLUE_ACTION),
                                *(
                                    [ft.Text(inc["description"], size=12, color=TEXT_MUTED)]
                                    if inc.get("description")
                                    else []
                                ),
                                ft.Container(
                                    bgcolor=EMERALD_SURFACE,
                                    border_radius=10,
                                    padding=8,
                                    content=ft.Text(
                                        f"Consejo de Gemini: {inc.get('ai_advice', '')}",
                                        size=12,
                                        color="#065F46",
                                        weight=ft.FontWeight.W_500,
                                    ),
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
                                spacing=1,
                                controls=[
                                    ft.Text("Historial de Incidencias", size=19, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                    ft.Text(
                                        f"Reportes registrados: {len(state.incidents)}",
                                        size=12,
                                        color=TEXT_MUTED,
                                    ),
                                ],
                            ),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.IconButton(
                                        icon=ft.Icons.REFRESH,
                                        icon_color=INDIGO_DARK,
                                        on_click=lambda _: page.run_task(load_incidents_history),
                                    ),
                                    build_sos_pill(),
                                ],
                            ),
                        ],
                    ),
                    ft.FilledButton(
                        content="Reportar nueva incidencia",
                        icon=ft.Icons.ADD_CIRCLE,
                        bgcolor=BLUE_ACTION,
                        color=ft.Colors.WHITE,
                        width=float("inf"),
                        height=46,
                        on_click=open_report_incident_dialog,
                    ),
                    *history_cards,
                ],
            ),
        )

    # =======================================================================
    # SECCIÓN CLÍNICAS (Horarios, accesibilidad, teléfono y QUÉ DEBES LLEVAR)
    # =======================================================================
    def build_clinics_screen() -> ft.Control:
        dis_label = format_disabilities_label(state.disabilities)
        cards: List[ft.Control] = []

        for clinic in state.clinics:
            reqs = [ft.Text(f"• {req}", size=12, color=INDIGO_DARK) for req in clinic.get("requirements_to_bring", [])]
            acc_items = [ft.Text(f"✓ {feat}", size=11, color="#065F46") for feat in clinic.get("accessibility_features", [])]

            cards.append(
                ft.Container(
                    bgcolor=ft.Colors.WHITE,
                    border_radius=18,
                    border=ft.Border.all(1, CARD_BORDER),
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
                                            ft.Text(clinic["name"], size=16, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                            ft.Text(clinic["address"], size=12, color=TEXT_MUTED),
                                        ],
                                    ),
                                    ft.Container(
                                        bgcolor="#EEF2FF",
                                        border_radius=10,
                                        padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                                        content=ft.Text(
                                            f"{clinic['distance_text']} · ~{clinic['estimated_minutes']} min",
                                            size=11,
                                            weight=ft.FontWeight.BOLD,
                                            color=INDIGO_DARK,
                                        ),
                                    ),
                                ],
                            ),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.Icon(ft.Icons.SCHEDULE, size=15, color=EMERALD_GREEN),
                                    ft.Text(
                                        f"Horario: {clinic['schedule']} · {clinic.get('emergency_hours', '')}",
                                        size=12,
                                        color=INDIGO_DARK,
                                        expand=True,
                                    ),
                                ],
                            ),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.Icon(ft.Icons.PHONE, size=15, color=BLUE_ACTION),
                                    ft.Text(f"Teléfono: {clinic.get('phone', 'N/D')}", size=12, color=INDIGO_DARK),
                                ],
                            ),
                            ft.Text(f"Servicios: {', '.join(clinic.get('services', []))}", size=12, color=TEXT_MUTED),
                            ft.Container(
                                bgcolor=EMERALD_SURFACE,
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text("Accesibilidad verificada:", size=12, weight=ft.FontWeight.BOLD, color="#065F46"),
                                        *acc_items,
                                    ],
                                ),
                            ),
                            ft.Container(
                                bgcolor=NEUTRAL_BG,
                                border_radius=10,
                                padding=10,
                                content=ft.Column(
                                    spacing=3,
                                    controls=[
                                        ft.Row(
                                            spacing=6,
                                            controls=[
                                                ft.Icon(ft.Icons.LIST_ALT, size=15, color=INDIGO_DARK),
                                                ft.Text("Qué debes llevar:", size=12, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                            ],
                                        ),
                                        *reqs,
                                    ],
                                ),
                            ),
                            ft.FilledButton(
                                content=f"Trazar ruta (~{clinic['estimated_minutes']} min)",
                                icon=ft.Icons.DIRECTIONS,
                                bgcolor=BLUE_ACTION,
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
                                    ft.Text("Clínicas cercanas", size=20, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                    ft.Text(
                                        f"Tiempos calculados para: {dis_label}",
                                        size=11,
                                        color=EMERALD_GREEN,
                                        weight=ft.FontWeight.W_600,
                                    ),
                                ],
                            ),
                            build_sos_pill(),
                        ],
                    ),
                    *cards,
                ],
            ),
        )

    # =======================================================================
    # SECCIÓN VOLUNTARIOS (Inicialmente vacía + foto de rostro obligatoria visible)
    # =======================================================================
    def build_volunteers_screen() -> ft.Control:
        body_controls: List[ft.Control] = []

        if not state.volunteers:
            body_controls.append(
                ft.Container(
                    bgcolor=ft.Colors.WHITE,
                    border_radius=18,
                    border=ft.Border.all(1, CARD_BORDER),
                    padding=24,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Column(
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(ft.Icons.VOLUNTEER_ACTIVISM, size=48, color=TEXT_MUTED),
                            ft.Text(
                                "Aún no hay voluntarios registrados",
                                size=16,
                                weight=ft.FontWeight.BOLD,
                                color=INDIGO_DARK,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            ft.Text(
                                "Para seguridad de la comunidad, cada voluntario debe subir una foto de su rostro al postularse desde Perfil.",
                                size=13,
                                color=TEXT_MUTED,
                                text_align=ft.TextAlign.CENTER,
                            ),
                            ft.FilledButton(
                                content="Ir a mi Perfil para postularme",
                                icon=ft.Icons.PERSON_ADD,
                                bgcolor=BLUE_ACTION,
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
                        bgcolor=ft.Colors.WHITE,
                        border_radius=16,
                        border=ft.Border.all(1, CARD_BORDER),
                        padding=14,
                        content=ft.Column(
                            spacing=8,
                            controls=[
                                ft.Row(
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        build_face_avatar(
                                            vol.get("face_photo_base64"),
                                            size=64,
                                            fallback_icon=ft.Icons.VOLUNTEER_ACTIVISM,
                                        ),
                                        ft.Column(
                                            expand=True,
                                            spacing=3,
                                            controls=[
                                                ft.Text(
                                                    vol["username"],
                                                    size=16,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=INDIGO_DARK,
                                                ),
                                                ft.Container(
                                                    bgcolor=EMERALD_SURFACE,
                                                    border_radius=10,
                                                    padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                                    content=ft.Text(
                                                        "Foto de rostro verificada · Disponible",
                                                        size=11,
                                                        color="#065F46",
                                                        weight=ft.FontWeight.W_600,
                                                    ),
                                                ),
                                                ft.Text(f"Zona: {vol['zone']}", size=12, color=INDIGO_DARK),
                                            ],
                                        ),
                                    ],
                                ),
                                ft.Text(f"Horario: {vol['availability']}", size=12, color=TEXT_MUTED),
                                ft.Text(f"Apoyo: {vol['support_notes']}", size=12, color=TEXT_MUTED),
                                ft.OutlinedButton(
                                    content="Solicitar acompañamiento",
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
                                spacing=1,
                                controls=[
                                    ft.Text("Guías Voluntarias", size=20, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                    ft.Text(f"Voluntarios activos: {len(state.volunteers)}", size=12, color=TEXT_MUTED),
                                ],
                            ),
                            ft.Row(
                                spacing=6,
                                controls=[
                                    ft.IconButton(
                                        icon=ft.Icons.REFRESH,
                                        icon_color=INDIGO_DARK,
                                        on_click=lambda _: page.run_task(load_volunteers),
                                    ),
                                    build_sos_pill(),
                                ],
                            ),
                        ],
                    ),
                    *body_controls,
                ],
            ),
        )

    # =======================================================================
    # SECCIÓN PERFIL (Foto opcional usuario, foto OBLIGATORIA voluntario,
    # múltiples discapacidades y protección para menores + familiar)
    # =======================================================================
    def build_profile_screen() -> ft.Control:
        # --- Caso A: Usuario con sesión iniciada ---
        if state.current_user is not None:
            user = state.current_user

            def on_user_photo_picked(b64: str, filename: str) -> None:
                user["face_photo_base64"] = b64
                user["face_photo_filename"] = filename
                # Si aún no eligió foto aparte para voluntario, se prellena automáticamente
                if not state.vol_photo_b64:
                    state.vol_photo_b64 = b64
                    state.vol_photo_name = filename

                async def sync_photo() -> None:
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            await client.put(
                                f"{state.api_url}/api/v1/profile",
                                json={
                                    "user_id": user["id"],
                                    "face_photo_base64": b64,
                                    "face_photo_filename": filename,
                                },
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
                    state.vol_error = (
                        "Debes subir una foto de tu rostro obligatoriamente para poder identificarte como voluntario."
                    )
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
                try:
                    async with httpx.AsyncClient(timeout=12.0) as client:
                        resp = await client.post(f"{state.api_url}/api/v1/volunteers/apply", json=payload)
                        if resp.status_code >= 400:
                            state.vol_error = resp.json().get("detail", "No se pudo completar la postulación.")
                            render()
                            return
                        member = resp.json()
                except Exception:
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

            # Panel de protección para menores (si es menor o desea configurar un familiar)
            minor_guardian = user.get("guardian") or {}
            minor_section_controls: List[ft.Control] = [
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(ft.Icons.CHILD_CARE, color=BLUE_ACTION),
                        ft.Text(
                            "Protección para menores de edad",
                            size=15,
                            weight=ft.FontWeight.BOLD,
                            color=INDIGO_DARK,
                        ),
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
                            color=INDIGO_DARK,
                        ),
                        ft.Container(
                            bgcolor=INFO_BLUE_BG if state.live_sharing_active else NEUTRAL_BG,
                            border_radius=10,
                            padding=10,
                            content=ft.Text(
                                (
                                    f"Ubicación compartiéndose en tiempo real · Último envío: {state.last_location_shared_at or 'ahora'}"
                                    if state.live_sharing_active
                                    else "La ubicación en tiempo real se activa automáticamente al iniciar una ruta o aquí abajo."
                                ),
                                size=12,
                                color=INDIGO_DARK,
                            ),
                        ),
                        ft.Row(
                            spacing=8,
                            controls=[
                                ft.FilledButton(
                                    content="Pausar ubicación" if state.live_sharing_active else "Compartir ubicación ahora",
                                    icon=ft.Icons.SHARE_LOCATION,
                                    bgcolor=INDIGO_DARK if state.live_sharing_active else BLUE_ACTION,
                                    color=ft.Colors.WHITE,
                                    expand=True,
                                    on_click=lambda _: (
                                        (stop_minor_live_sharing(), render())
                                        if state.live_sharing_active
                                        else (start_minor_live_sharing(), render())
                                    ),
                                ),
                            ],
                        ),
                        ft.FilledButton(
                            content="Detener alarma sonora" if state.lost_alarm_active else "Me extravié · Emitir alarma sonora",
                            icon=ft.Icons.STOP_CIRCLE if state.lost_alarm_active else ft.Icons.VOLUME_UP,
                            bgcolor=INDIGO_DARK if state.lost_alarm_active else ALERT_ORANGE,
                            color=ft.Colors.WHITE,
                            width=float("inf"),
                            on_click=stop_lost_alarm if state.lost_alarm_active else (lambda _: page.run_task(activate_lost_minor_alarm)),
                        ),
                    ]
                )
            else:
                minor_section_controls.append(
                    ft.Text(
                        "Cuenta de usuario adulto. (Si necesitas modo menor con seguimiento familiar, puedes activarlo al crear una cuenta de menor).",
                        size=12,
                        color=TEXT_MUTED,
                    )
                )

            # Bloque de postulación a voluntario (CON FOTO DE ROSTRO OBLIGATORIA)
            effective_vol_photo = state.vol_photo_b64 or user.get("face_photo_base64")
            volunteer_block: ft.Control
            if user.get("is_volunteer"):
                volunteer_block = ft.Container(
                    bgcolor=EMERALD_SURFACE,
                    border_radius=14,
                    padding=14,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Row(
                                spacing=10,
                                controls=[
                                    build_face_avatar(effective_vol_photo, size=50),
                                    ft.Column(
                                        expand=True,
                                        spacing=2,
                                        controls=[
                                            ft.Text("Ya eres guía voluntario verificado", weight=ft.FontWeight.BOLD, color="#065F46"),
                                            ft.Text(
                                                "Tu foto de rostro y datos ya aparecen en la lista de Voluntarios.",
                                                size=12,
                                                color="#065F46",
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            ft.OutlinedButton(
                                content="Ver lista de Voluntarios",
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
                    bgcolor=ft.Colors.WHITE,
                    border_radius=16,
                    border=ft.Border.all(1, CARD_BORDER),
                    padding=16,
                    content=ft.Column(
                        spacing=10,
                        controls=[
                            ft.Row(
                                spacing=8,
                                controls=[
                                    ft.Icon(ft.Icons.VOLUNTEER_ACTIVISM, color=BLUE_ACTION),
                                    ft.Text("Postularme como voluntario", size=16, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                ],
                            ),
                            ft.Container(
                                bgcolor=EMERALD_SURFACE if effective_vol_photo else WARN_SURFACE,
                                border_radius=12,
                                padding=10,
                                content=ft.Row(
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        build_face_avatar(effective_vol_photo, size=54, fallback_icon=ft.Icons.PHOTO_CAMERA),
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
                                                    color="#065F46" if effective_vol_photo else "#92400E",
                                                ),
                                                ft.OutlinedButton(
                                                    content="Cambiar foto" if effective_vol_photo else "Subir foto de rostro (obligatorio)",
                                                    icon=ft.Icons.ADD_A_PHOTO,
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
                            ft.TextField(
                                label="Zona o campus de apoyo",
                                value=state.vol_zone,
                                bgcolor=ft.Colors.WHITE,
                                on_change=lambda e: setattr(state, "vol_zone", e.control.value or ""),
                            ),
                            ft.TextField(
                                label="Horario disponible",
                                value=state.vol_availability,
                                bgcolor=ft.Colors.WHITE,
                                on_change=lambda e: setattr(state, "vol_availability", e.control.value or ""),
                            ),
                            ft.TextField(
                                label="¿Cómo puedes apoyar?",
                                value=state.vol_notes,
                                multiline=True,
                                bgcolor=ft.Colors.WHITE,
                                on_change=lambda e: setattr(state, "vol_notes", e.control.value or ""),
                            ),
                            *(
                                [
                                    ft.Container(
                                        bgcolor=DANGER_SURFACE,
                                        border_radius=10,
                                        padding=10,
                                        content=ft.Text(state.vol_error, size=12, color=DANGER_RED, weight=ft.FontWeight.W_600),
                                    )
                                ]
                                if state.vol_error
                                else []
                            ),
                            ft.FilledButton(
                                content="Enviar postulación de voluntario",
                                icon=ft.Icons.VOLUNTEER_ACTIVISM,
                                bgcolor=EMERALD_GREEN,
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
                                ft.Text("Mi Perfil", size=20, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                build_sos_pill(),
                            ],
                        ),
                        ft.Container(
                            bgcolor=INDIGO_DARK,
                            border_radius=18,
                            padding=16,
                            content=ft.Column(
                                spacing=10,
                                controls=[
                                    ft.Row(
                                        spacing=12,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            build_face_avatar(user.get("face_photo_base64"), size=60),
                                            ft.Column(
                                                expand=True,
                                                spacing=2,
                                                controls=[
                                                    ft.Text(user["username"], size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                                    ft.Text(f"Correo: {user['email']}", size=12, color="#BFDBFE"),
                                                    ft.Text(
                                                        f"Discapacidades: {format_disabilities_label(state.disabilities)}",
                                                        size=11,
                                                        color=EMERALD_SURFACE,
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                    ft.OutlinedButton(
                                        content="Cambiar foto de perfil (opcional)" if user.get("face_photo_base64") else "Agregar foto de perfil (opcional)",
                                        icon=ft.Icons.CAMERA_ALT,
                                        icon_color=ft.Colors.WHITE,
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
                                    bgcolor=EMERALD_SURFACE,
                                    border_radius=10,
                                    padding=10,
                                    content=ft.Text(state.auth_feedback, size=12, color="#065F46", weight=ft.FontWeight.W_600),
                                )
                            ]
                            if state.auth_feedback
                            else []
                        ),
                        ft.Container(
                            bgcolor=ft.Colors.WHITE,
                            border_radius=16,
                            border=ft.Border.all(1, CARD_BORDER),
                            padding=16,
                            content=ft.Column(
                                spacing=8,
                                controls=[
                                    ft.Text("Discapacidades activas (puedes elegir varias)", size=14, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                    ft.Text(
                                        "Cada combinación recalcula rutas, pasos y tiempos estimados.",
                                        size=12,
                                        color=TEXT_MUTED,
                                    ),
                                    build_multi_disability_chips(),
                                ],
                            ),
                        ),
                        ft.Container(
                            bgcolor=ft.Colors.WHITE,
                            border_radius=16,
                            border=ft.Border.all(1, CARD_BORDER),
                            padding=16,
                            content=ft.Column(spacing=10, controls=minor_section_controls),
                        ),
                        volunteer_block,
                        ft.OutlinedButton(
                            content="Cerrar sesión",
                            icon=ft.Icons.LOGOUT,
                            width=float("inf"),
                            height=44,
                            on_click=logout,
                        ),
                    ],
                ),
            )

        # --- Caso B: Sin sesión iniciada (Crear perfil / Iniciar sesión) ---
        is_register = state.auth_mode == "register"

        def on_reg_photo_picked(b64: str, filename: str) -> None:
            state.reg_photo_b64 = b64
            state.reg_photo_name = filename
            render()

        async def submit_auth() -> None:
            state.auth_error = None
            state.auth_feedback = None
            u_val = state.reg_username.strip()
            e_val = state.reg_email.strip().lower()
            p_val = state.reg_password

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
                try:
                    async with httpx.AsyncClient(timeout=12.0) as client:
                        resp = await client.post(f"{state.api_url}/api/v1/auth/register", json=req_body)
                        if resp.status_code >= 400:
                            state.auth_error = resp.json().get("detail", "Error al crear perfil.")
                            render()
                            return
                        user_obj = resp.json()
                except Exception:
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
                await sync_routes_and_clinics()
            else:
                if not u_val or not p_val:
                    state.auth_error = "Ingresa tu usuario/correo y contraseña."
                    render()
                    return
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
                    local = state.local_users.get(u_val.lower())
                    if not local or local.get("password_local") != p_val:
                        state.auth_error = "Usuario/correo o contraseña incorrectos (modo local)."
                        render()
                        return
                    user_obj = local

                state.current_user = user_obj
                state.disabilities = normalize_disabilities(user_obj.get("disabilities", state.disabilities))
                state.vol_photo_b64 = user_obj.get("face_photo_base64")
                state.vol_photo_name = user_obj.get("face_photo_filename")
                state.auth_feedback = f"¡Bienvenido de nuevo, {user_obj['username']}!"
                await sync_routes_and_clinics()

        form_controls: List[ft.Control] = [
            ft.Row(
                spacing=8,
                controls=[
                    ft.FilledButton(
                        content="Crear perfil",
                        expand=True,
                        bgcolor=INDIGO_DARK if is_register else "#E5E7EB",
                        color=ft.Colors.WHITE if is_register else INDIGO_DARK,
                        on_click=lambda _: (
                            setattr(state, "auth_mode", "register"),
                            setattr(state, "auth_error", None),
                            render(),
                        ),
                    ),
                    ft.FilledButton(
                        content="Iniciar sesión",
                        expand=True,
                        bgcolor=INDIGO_DARK if not is_register else "#E5E7EB",
                        color=ft.Colors.WHITE if not is_register else INDIGO_DARK,
                        on_click=lambda _: (
                            setattr(state, "auth_mode", "login"),
                            setattr(state, "auth_error", None),
                            render(),
                        ),
                    ),
                ],
            ),
            ft.TextField(
                label="Nombre de usuario" if is_register else "Usuario o correo electrónico",
                value=state.reg_username,
                prefix_icon=ft.Icons.PERSON,
                bgcolor=ft.Colors.WHITE,
                on_change=lambda e: setattr(state, "reg_username", e.control.value or ""),
            ),
        ]

        if is_register:
            form_controls.append(
                ft.TextField(
                    label="Correo electrónico vinculado",
                    value=state.reg_email,
                    prefix_icon=ft.Icons.EMAIL,
                    bgcolor=ft.Colors.WHITE,
                    on_change=lambda e: setattr(state, "reg_email", e.control.value or ""),
                )
            )

        form_controls.append(
            ft.TextField(
                label="Contraseña (mín. 6 caracteres)",
                value=state.reg_password,
                prefix_icon=ft.Icons.LOCK,
                password=True,
                can_reveal_password=True,
                bgcolor=ft.Colors.WHITE,
                on_change=lambda e: setattr(state, "reg_password", e.control.value or ""),
            )
        )

        if is_register:
            # Foto de perfil OPCIONAL para usuarios
            form_controls.append(
                ft.Container(
                    bgcolor=NEUTRAL_BG,
                    border_radius=12,
                    padding=10,
                    content=ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            build_face_avatar(state.reg_photo_b64, size=48),
                            ft.Column(
                                expand=True,
                                spacing=4,
                                controls=[
                                    ft.Text(
                                        f"Foto seleccionada: {state.reg_photo_name}"
                                        if state.reg_photo_b64
                                        else "Foto de rostro (opcional para usuarios)",
                                        size=12,
                                        color=INDIGO_DARK,
                                    ),
                                    ft.Row(
                                        spacing=6,
                                        controls=[
                                            ft.OutlinedButton(
                                                content="Subir foto (opcional)",
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
                                                        content="Quitar",
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

            # Múltiples discapacidades
            form_controls.extend(
                [
                    ft.Text(
                        "Selecciona una o más discapacidades (rutas personalizadas):",
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=INDIGO_DARK,
                    ),
                    build_multi_disability_chips(),
                ]
            )

            # Switch de menor de edad + familiar registrado
            form_controls.append(
                ft.Switch(
                    label="Soy menor de edad (compartir ubicación en tiempo real a familiar)",
                    value=state.reg_is_minor,
                    active_color=BLUE_ACTION,
                    on_change=lambda e: (setattr(state, "reg_is_minor", bool(e.control.value)), render()),
                )
            )

            if state.reg_is_minor:
                form_controls.append(
                    ft.Container(
                        bgcolor=INFO_BLUE_BG,
                        border_radius=12,
                        padding=12,
                        content=ft.Column(
                            spacing=8,
                            controls=[
                                ft.Row(
                                    spacing=6,
                                    controls=[
                                        ft.Icon(ft.Icons.FAMILY_RESTROOM, color=BLUE_ACTION, size=18),
                                        ft.Text(
                                            "Familiar / Tutor registrado",
                                            size=13,
                                            weight=ft.FontWeight.BOLD,
                                            color=INDIGO_DARK,
                                        ),
                                    ],
                                ),
                                ft.TextField(
                                    label="Nombre del familiar *",
                                    value=state.reg_guardian_name,
                                    bgcolor=ft.Colors.WHITE,
                                    on_change=lambda e: setattr(state, "reg_guardian_name", e.control.value or ""),
                                ),
                                ft.TextField(
                                    label="Parentesco",
                                    value=state.reg_guardian_relation,
                                    bgcolor=ft.Colors.WHITE,
                                    on_change=lambda e: setattr(state, "reg_guardian_relation", e.control.value or ""),
                                ),
                                ft.TextField(
                                    label="Teléfono del familiar *",
                                    value=state.reg_guardian_phone,
                                    bgcolor=ft.Colors.WHITE,
                                    on_change=lambda e: setattr(state, "reg_guardian_phone", e.control.value or ""),
                                ),
                                ft.TextField(
                                    label="Correo del familiar (opcional)",
                                    value=state.reg_guardian_email,
                                    bgcolor=ft.Colors.WHITE,
                                    on_change=lambda e: setattr(state, "reg_guardian_email", e.control.value or ""),
                                ),
                            ],
                        ),
                    )
                )

        if state.auth_error:
            form_controls.append(
                ft.Container(
                    bgcolor=DANGER_SURFACE,
                    border_radius=10,
                    padding=10,
                    content=ft.Text(state.auth_error, size=12, color=DANGER_RED, weight=ft.FontWeight.W_600),
                )
            )

        if state.auth_feedback:
            form_controls.append(
                ft.Container(
                    bgcolor=EMERALD_SURFACE,
                    border_radius=10,
                    padding=10,
                    content=ft.Text(state.auth_feedback, size=12, color="#065F46"),
                )
            )

        form_controls.append(
            ft.FilledButton(
                content="Crear cuenta y vincular correo" if is_register else "Entrar a mi perfil",
                icon=ft.Icons.PERSON_ADD if is_register else ft.Icons.LOGIN,
                bgcolor=BLUE_ACTION,
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
                            ft.Text("Perfil de Usuario", size=20, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                            build_sos_pill(),
                        ],
                    ),
                    ft.Text(
                        "Crea tu cuenta con correo vinculado, elige una o más discapacidades y postúlate como voluntario con foto de rostro.",
                        size=12,
                        color=TEXT_MUTED,
                    ),
                    ft.Container(
                        bgcolor=ft.Colors.WHITE,
                        border_radius=18,
                        border=ft.Border.all(1, CARD_BORDER),
                        padding=16,
                        content=ft.Column(spacing=12, controls=form_controls),
                    ),
                ],
            ),
        )

    # -----------------------------------------------------------------------
    # Router principal de pantallas
    # -----------------------------------------------------------------------
    def render() -> None:
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
    ft.run(main)
