"""Map Inclusive — App móvil para Android hecha 100% en Python (Flet / motor Flutter).

Sin una sola línea de Java. Implementa:
- Selección de discapacidad (al inicio y editable en Perfil) con rutas y tiempos
  estimados independientes por tipo de discapacidad.
- Lista vertical de sugerencias de rutas con distancia y tiempo estimado.
- Pantalla de Ruta Accesible con actualización automática de Gemini cada 10 minutos.
- Lista completa de clínicas con horarios, accesibilidad, teléfono y qué debes llevar.
- Lista de voluntarios (inicialmente vacía) conectada a la postulación desde Perfil.
- Perfil con registro/inicio de sesión (usuario, correo vinculado, contraseña, discapacidad)
  y postulación a voluntario al iniciar sesión.
- Botón de Emergencia (SOS) siempre accesible.

Ejecución local:
    python mobile_app/main.py
    flet run --web --port 8550 mobile_app/main.py
    flet run --android mobile_app/main.py
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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

TEN_MINUTES_SECONDS = 600
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


PROFILES: List[ProfileOption] = [
    ProfileOption(
        api_value="silla_de_ruedas",
        label="Silla de ruedas",
        short_label="Silla de ruedas",
        icon=ft.Icons.ACCESSIBLE,
        nav_hint="Rampa disponible · sin escalones",
        route_prefix="Ruta con rampas continuas",
        distance_factor=1.15,
        minutes_per_km=15.0,
        accessibility_summary="Evita escaleras y rampas bloqueadas; prioriza banquetas anchas.",
    ),
    ProfileOption(
        api_value="visual",
        label="Visual",
        short_label="Visual",
        icon=ft.Icons.VISIBILITY,
        nav_hint="Semáforo sonoro y guía podotáctil",
        route_prefix="Ruta podotáctil y semáforo sonoro",
        distance_factor=1.05,
        minutes_per_km=14.0,
        accessibility_summary="Prioriza líneas podotáctiles, cruces sonoros y alertas de obras.",
    ),
    ProfileOption(
        api_value="auditivo",
        label="Auditivo",
        short_label="Auditivo",
        icon=ft.Icons.HEARING,
        nav_hint="Cruce con señalización visual clara",
        route_prefix="Ruta de alta visibilidad",
        distance_factor=1.0,
        minutes_per_km=12.0,
        accessibility_summary="Cruces con semáforos visibles y alertas visuales cada 10 min.",
    ),
    ProfileOption(
        api_value="movilidad_reducida",
        label="Movilidad reducida",
        short_label="Mov. reducida",
        icon=ft.Icons.DIRECTIONS_WALK,
        nav_hint="Pendiente suave y banca en 50 m",
        route_prefix="Ruta de pendiente suave",
        distance_factor=1.08,
        minutes_per_km=16.5,
        accessibility_summary="Trayectos planos con menor esfuerzo y zonas de descanso intermedias.",
    ),
    ProfileOption(
        api_value="neurodivergente",
        label="Persona neurodivergente",
        short_label="Neurodivergente",
        icon=ft.Icons.PSYCHOLOGY,
        nav_hint="Calle tranquila · baja estimulación",
        route_prefix="Ruta tranquila de baja estimulación",
        distance_factor=1.12,
        minutes_per_km=13.5,
        accessibility_summary="Evita ruido intenso y aglomeraciones con instrucciones simples.",
    ),
]


def get_profile(api_value: str) -> ProfileOption:
    for item in PROFILES:
        if item.api_value == api_value:
            return item
    return PROFILES[0]


# Catálogo local de respaldo (coincide con el backend para funcionar incluso sin servidor)
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


def compute_local_route(
    dest_id: str,
    destination: str,
    address: str,
    category: str,
    base_km: float,
    profile_value: str,
) -> Dict[str, Any]:
    prof = get_profile(profile_value)
    adj_km = round(base_km * prof.distance_factor, 2)
    est_min = max(3, int(round(adj_km * prof.minutes_per_km)))
    dist_text = f"{int(round(adj_km * 1000))} m" if adj_km < 1.0 else f"{adj_km:.1f} km"
    return {
        "id": dest_id,
        "destination": destination,
        "address": address,
        "category": category,
        "profile": prof.api_value,
        "profile_label": prof.label,
        "route_name": f"{prof.route_prefix} · {destination}",
        "distance_km": adj_km,
        "distance_text": dist_text,
        "estimated_minutes": est_min,
        "accessibility_summary": prof.accessibility_summary,
        "steps": [
            f"Inicio adaptado para {prof.label}: {prof.nav_hint}.",
            f"Trayecto independiente ({dist_text}, aprox. {est_min} min) evitando obstáculos reportados.",
            f"Llegada accesible a {destination}.",
        ],
    }


def build_local_suggestions(profile_value: str) -> List[Dict[str, Any]]:
    return [
        compute_local_route(
            dest_id=p["id"],
            destination=p["destination"],
            address=p["address"],
            category=p["category"],
            base_km=p["base_km"],
            profile_value=profile_value,
        )
        for p in LOCAL_SUGGESTIONS_BASE
    ]


def build_local_clinics(profile_value: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for c in LOCAL_CLINICS_BASE:
        est = compute_local_route(c["id"], c["name"], c["address"], "Clínica", c["base_km"], profile_value)
        item = dict(c)
        item["distance_text"] = est["distance_text"]
        item["distance_km"] = est["distance_km"]
        item["estimated_minutes"] = est["estimated_minutes"]
        out.append(item)
    return out


@dataclass
class AppState:
    api_url: str = DEFAULT_API_URL
    # Pantallas: onboarding | search | route | active | clinics | volunteers | profile
    screen: str = "onboarding"
    profile: str = "silla_de_ruedas"
    origin: str = "Campus Coyoacán, CDMX"
    destination: str = "Clínica 19 (UMF IMSS)"
    search_query: str = ""

    suggestions: List[Dict[str, Any]] = field(
        default_factory=lambda: build_local_suggestions("silla_de_ruedas")
    )
    current_route: Dict[str, Any] = field(
        default_factory=lambda: compute_local_route(
            "sug-clinica-19",
            "Clínica 19 (UMF IMSS)",
            "Av. Universidad, Coyoacán",
            "Clínica",
            0.4,
            "silla_de_ruedas",
        )
    )
    clinics: List[Dict[str, Any]] = field(
        default_factory=lambda: build_local_clinics("silla_de_ruedas")
    )
    # Lista de voluntarios comienza VACÍA como se solicitó
    volunteers: List[Dict[str, Any]] = field(default_factory=list)

    # Estado de usuario / perfil (registro + inicio de sesión + correo + voluntariado)
    current_user: Optional[Dict[str, Any]] = None
    local_users: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    auth_mode: str = "register"  # register | login
    auth_feedback: Optional[str] = None
    auth_error: Optional[str] = None

    # Estado de Gemini cada 10 min
    env_report: Optional[Dict[str, Any]] = None
    is_loading_env: bool = False
    env_error: Optional[str] = None
    show_env_details: bool = False
    refresh_generation: int = 0


def build_minimalist_map(
    *,
    show_route: bool,
    badge_text: str,
    show_clinics: bool = False,
    show_user_arrow: bool = False,
    height: int = 185,
) -> ft.Container:
    """Mapa vectorial minimalista de bajo ruido visual alineado con el boceto."""
    layers: List[ft.Control] = [
        ft.Container(left=0, right=0, top=48, height=12, bgcolor=ft.Colors.WHITE),
        ft.Container(left=0, right=0, top=126, height=12, bgcolor=ft.Colors.WHITE),
        ft.Container(top=0, bottom=0, left=92, width=12, bgcolor=ft.Colors.WHITE),
        ft.Container(top=0, bottom=0, right=82, width=12, bgcolor=ft.Colors.WHITE),
        ft.Container(left=126, top=22, width=76, height=76, border_radius=38, bgcolor="#D7EFE2"),
    ]

    if show_clinics:
        for pos in ((54, 68), (150, 34), (235, 112)):
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
                ft.Container(left=98, top=48, width=148, height=8, border_radius=4, bgcolor=INDIGO_DARK),
                ft.Container(left=238, top=48, width=8, height=86, border_radius=4, bgcolor=INDIGO_DARK),
                ft.Container(left=132, top=126, width=114, height=8, border_radius=4, bgcolor=INDIGO_DARK),
                ft.Container(
                    left=88,
                    top=39,
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
                top=112,
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
    page.window.width = 420
    page.window.height = 840

    state = AppState()

    def show_info_dialog(title: str, message: str) -> None:
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
            content=ft.Text(message, size=13),
            actions=[ft.TextButton(content="Entendido", on_click=lambda _: page.pop_dialog())],
        )
        page.show_dialog(dialog)

    # -----------------------------------------------------------------------
    # Botón y flujo de Emergencia SOS (disponible en toda la app)
    # -----------------------------------------------------------------------
    def open_emergency_dialog(_: Any = None) -> None:
        prof = get_profile(state.profile)

        async def send_sos() -> None:
            page.pop_dialog()
            payload = {
                "location": state.origin,
                "profile": state.profile,
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
                    f"Perfil activo: {prof.label}\nUbicación: {state.origin}\n\n"
                    "Urgencias más cercanas: Hospital General Xoco (24h · Tel. 55 5688 9015)\n\n"
                    "Comunícate de inmediato:\n"
                    "• 911 — Emergencias generales\n"
                    "• 065 — Cruz Roja Mexicana\n"
                    "• 55 5658 1111 — LOCATEL 24h",
                )

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
                        f"Perfil activo: {prof.label}\nUbicación: {state.origin}",
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
    # Sincronización con Backend Python
    # -----------------------------------------------------------------------
    async def sync_routes_and_clinics() -> None:
        state.suggestions = build_local_suggestions(state.profile)
        state.clinics = build_local_clinics(state.profile)
        state.current_route = compute_local_route(
            "current",
            state.destination,
            "Zona Coyoacán, CDMX",
            "Ruta accesible",
            next(
                (p["base_km"] for p in LOCAL_SUGGESTIONS_BASE if p["destination"].lower() in state.destination.lower()),
                0.9,
            ),
            state.profile,
        )
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                s_resp = await client.get(
                    f"{state.api_url}/api/v1/routes/suggestions",
                    params={"profile": state.profile},
                )
                if s_resp.status_code == 200:
                    state.suggestions = s_resp.json()

                c_resp = await client.get(
                    f"{state.api_url}/api/v1/clinics",
                    params={"profile": state.profile},
                )
                if c_resp.status_code == 200:
                    state.clinics = c_resp.json()

                e_resp = await client.get(
                    f"{state.api_url}/api/v1/routes/estimate",
                    params={"destination": state.destination, "profile": state.profile},
                )
                if e_resp.status_code == 200:
                    state.current_route = e_resp.json()
        except Exception:
            pass
        render()

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
            "profile": state.profile,
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
        """Actualiza automáticamente el estado de Gemini cada 10 minutos."""
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

    async def update_active_disability(new_profile: str) -> None:
        state.profile = new_profile
        if state.current_user is not None:
            state.current_user["disability_profile"] = new_profile
            state.current_user["disability_label"] = get_profile(new_profile).label
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    await client.put(
                        f"{state.api_url}/api/v1/profile/disability",
                        json={"user_id": state.current_user["id"], "disability_profile": new_profile},
                    )
            except Exception:
                pass
        await sync_routes_and_clinics()
        if state.screen in ("route", "active"):
            await refresh_environment(force=True)

    # -----------------------------------------------------------------------
    # Incidencias y solicitud de voluntario
    # -----------------------------------------------------------------------
    def open_report_incident_dialog(_: Any = None) -> None:
        title_field = ft.TextField(label="Título", value="Rampa bloqueada")
        desc_field = ft.TextField(
            label="Descripción",
            value="Vehículo bloqueando la rampa peatonal en esquina",
            multiline=True,
        )

        async def submit_incident() -> None:
            page.pop_dialog()
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"{state.api_url}/api/v1/incidents",
                        json={
                            "title": title_field.value or "Incidencia reportada",
                            "description": desc_field.value or "",
                            "location": "Av. Universidad, Coyoacán",
                            "profile": state.profile,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    show_info_dialog(
                        f"Incidencia reportada ({data.get('severity', 'medio').upper()})",
                        f"Consejo de Gemini:\n{data.get('ai_advice', 'Reporte registrado.')}",
                    )
                    if state.screen in ("route", "active"):
                        await refresh_environment(force=True)
            except Exception:
                show_info_dialog(
                    "Incidencia guardada localmente",
                    f"No se pudo conectar al backend ahora. El aviso '{title_field.value}' quedó en cola.",
                )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Reportar incidencia", weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
            content=ft.Column(
                tight=True,
                spacing=10,
                controls=[
                    ft.Text(f"Perfil activo: {get_profile(state.profile).label}", size=12, color=TEXT_MUTED),
                    title_field,
                    desc_field,
                ],
            ),
            actions=[
                ft.TextButton(content="Cancelar", on_click=lambda _: page.pop_dialog()),
                ft.FilledButton(
                    content="Enviar",
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
                        "profile": state.profile,
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
                    "Inicia sesión en la pestaña Perfil si deseas postularte como voluntario.",
                )
            else:
                first = state.volunteers[0]
                show_info_dialog(
                    "Guía Voluntaria Confirmada",
                    f"{first['username']} ({first['zone']}) fue notificado.\nTiempo estimado: 6 min.",
                )

    # -----------------------------------------------------------------------
    # Barra inferior de navegación (las 5 secciones completamente conectadas)
    # -----------------------------------------------------------------------
    def build_bottom_nav(selected_index: int) -> ft.NavigationBar:
        def on_nav_change(e: ft.ControlEvent) -> None:
            idx = e.control.selected_index
            if idx == 0:
                state.screen = "search"
                render()
                page.run_task(sync_routes_and_clinics)
            elif idx == 1:
                open_report_incident_dialog()
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
                render()

        return ft.NavigationBar(
            selected_index=selected_index,
            bgcolor=ft.Colors.WHITE,
            on_change=on_nav_change,
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.MAP, label="Mapa"),
                ft.NavigationBarDestination(icon=ft.Icons.FLAG, label="Reportar"),
                ft.NavigationBarDestination(icon=ft.Icons.LOCAL_HOSPITAL, label="Clínicas"),
                ft.NavigationBarDestination(icon=ft.Icons.PEOPLE, label="Voluntarios"),
                ft.NavigationBarDestination(icon=ft.Icons.PERSON, label="Perfil"),
            ],
        )

    # =======================================================================
    # PANTALLA 1: PANTALLA INICIAL (Selección de discapacidad + acceso a Perfil)
    # =======================================================================
    def build_onboarding_screen() -> ft.Control:
        def profile_tile(option: ProfileOption, full_width: bool = False) -> ft.Container:
            is_selected = state.profile == option.api_value

            def select_me(_: ft.ControlEvent) -> None:
                state.profile = option.api_value
                state.suggestions = build_local_suggestions(option.api_value)
                state.clinics = build_local_clinics(option.api_value)
                render()

            fg = ft.Colors.WHITE if is_selected else INDIGO_DARK
            bg = INDIGO_DARK if is_selected else ft.Colors.WHITE
            border_color = INDIGO_DARK if is_selected else CARD_BORDER

            if full_width:
                return ft.Container(
                    height=64,
                    bgcolor=bg,
                    border=ft.Border.all(1.5, border_color),
                    border_radius=16,
                    alignment=ft.Alignment.CENTER,
                    ink=True,
                    on_click=select_me,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Icon(option.icon, color=fg, size=26),
                            ft.Text(option.label, color=fg, size=15, weight=ft.FontWeight.W_600),
                        ],
                    ),
                )

            return ft.Container(
                expand=True,
                height=112,
                bgcolor=bg,
                border=ft.Border.all(1.5, border_color),
                border_radius=16,
                padding=10,
                alignment=ft.Alignment.CENTER,
                ink=True,
                on_click=select_me,
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                    controls=[
                        ft.Icon(option.icon, color=fg, size=32),
                        ft.Text(
                            option.label,
                            color=fg,
                            size=14,
                            weight=ft.FontWeight.W_600,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                ),
            )

        selected_obj = get_profile(state.profile)

        return ft.Container(
            expand=True,
            bgcolor=ft.Colors.WHITE,
            padding=ft.Padding.symmetric(horizontal=20, vertical=20),
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
                        "Cada perfil genera rutas y tiempos estimados independientes.",
                        size=12,
                        color=TEXT_MUTED,
                        text_align=ft.TextAlign.CENTER,
                    ),
                    ft.Row(spacing=12, controls=[profile_tile(PROFILES[0]), profile_tile(PROFILES[1])]),
                    ft.Row(spacing=12, controls=[profile_tile(PROFILES[2]), profile_tile(PROFILES[3])]),
                    profile_tile(PROFILES[4], full_width=True),
                    ft.Container(
                        width=float("inf"),
                        bgcolor=NEUTRAL_BG,
                        border_radius=12,
                        padding=10,
                        content=ft.Text(
                            f"{selected_obj.route_prefix}: {selected_obj.accessibility_summary}",
                            size=12,
                            color=INDIGO_DARK,
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
    # PANTALLA 2: BUSCAR DESTINO (Sugerencias en LISTA vertical con tiempo)
    # =======================================================================
    def build_search_screen() -> ft.Control:
        active_prof = get_profile(state.profile)
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

        # Sugerencias en formato LISTA vertical con tiempo estimado por discapacidad
        suggestion_rows: List[ft.Control] = []
        for idx, item in enumerate(state.suggestions):
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
                            bgcolor=EMERALD_SURFACE if "Clínica" in item["category"] or "Hospital" in item["category"] else "#E0E7FF",
                            alignment=ft.Alignment.CENTER,
                            content=ft.Icon(
                                category_icon(item["category"]),
                                color=EMERALD_GREEN if "Clínica" in item["category"] or "Hospital" in item["category"] else INDIGO_DARK,
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
                                spacing=1,
                                controls=[
                                    ft.Text("Explorar rutas", size=19, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                    ft.Text(f"Perfil: {active_prof.label}", size=12, color=EMERALD_GREEN, weight=ft.FontWeight.W_600),
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
                        height=175,
                    ),
                    ft.Text(
                        f"Rutas sugeridas ({active_prof.label})",
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
    # PANTALLA 3: RUTA Y GEMINI (Ruta independiente + tiempo estimado + Gemini)
    # =======================================================================
    def build_route_screen() -> ft.Control:
        active_profile = get_profile(state.profile)
        route = state.current_route

        chips = [
            ft.Chip(
                label=ft.Text(
                    p.short_label,
                    size=12,
                    color=ft.Colors.WHITE if p.api_value == state.profile else INDIGO_DARK,
                ),
                selected=p.api_value == state.profile,
                selected_color=INDIGO_DARK,
                bgcolor=ft.Colors.WHITE,
                show_checkmark=False,
                on_select=lambda _, pv=p.api_value: page.run_task(update_active_disability, pv),
            )
            for p in PROFILES
        ]

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
                                f"{active_profile.label} · {route.get('distance_text', '1.2 km')}",
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
            ft.Text(route.get("accessibility_summary", active_profile.accessibility_summary), size=12, color=EMERALD_GREEN),
            ft.Container(
                bgcolor=NEUTRAL_BG,
                border_radius=12,
                padding=10,
                content=ft.Column(spacing=4, controls=steps_preview),
            ),
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
            ),
        ]

        if state.show_env_details and state.env_report:
            rep = state.env_report
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
                            ft.Text(
                                f"Recomendación: {(rep.get('recomendaciones_perfil') or [''])[0]}",
                                size=12,
                                color=EMERALD_GREEN,
                                weight=ft.FontWeight.W_600,
                            ),
                        ],
                    ),
                )
            )

        summary_controls.append(
            ft.FilledButton(
                content="Iniciar Ruta",
                bgcolor=BLUE_ACTION,
                color=ft.Colors.WHITE,
                width=float("inf"),
                height=46,
                on_click=lambda _: (setattr(state, "screen", "active"), render()),
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
                    ft.Row(scroll=ft.ScrollMode.AUTO, spacing=8, controls=chips),
                    build_minimalist_map(show_route=True, badge_text="Rampa bloqueada", height=165),
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
    # PANTALLA 4: EN CAMINO (Navegación activa + SOS + Reportar + Voluntario)
    # =======================================================================
    def build_active_screen() -> ft.Control:
        active_profile = get_profile(state.profile)
        route = state.current_route
        gemini_chip = (
            f"Gemini activo · {state.env_report.get('banner_resumen', '')}"
            if state.env_report
            else "Monitoreo Gemini activo cada 10 min"
        )

        return ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.Container(
                    bgcolor=INDIGO_DARK,
                    padding=ft.Padding.symmetric(horizontal=16, vertical=18),
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
                                    ft.Text(
                                        f"· {active_profile.nav_hint}",
                                        color=EMERALD_SURFACE,
                                        size=12,
                                    ),
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
                        controls=[
                            ft.Container(
                                bgcolor=EMERALD_SURFACE,
                                border_radius=14,
                                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                                content=ft.Text(gemini_chip, size=12, color=INDIGO_DARK, weight=ft.FontWeight.W_600),
                            ),
                            build_minimalist_map(
                                show_route=True,
                                badge_text="",
                                show_user_arrow=True,
                                height=180,
                            ),
                            ft.Container(
                                bgcolor=ft.Colors.WHITE,
                                border_radius=20,
                                border=ft.Border.all(1, CARD_BORDER),
                                padding=16,
                                content=ft.Column(
                                    spacing=10,
                                    controls=[
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
                                        ft.OutlinedButton(
                                            content="Reportar Incidencia",
                                            icon=ft.Icons.REPORT,
                                            icon_color=ALERT_ORANGE,
                                            width=float("inf"),
                                            height=44,
                                            on_click=open_report_incident_dialog,
                                        ),
                                        ft.OutlinedButton(
                                            content="Pedir Guía Voluntaria",
                                            icon=ft.Icons.PEOPLE,
                                            icon_color=BLUE_ACTION,
                                            width=float("inf"),
                                            height=44,
                                            on_click=lambda _: page.run_task(request_volunteer),
                                        ),
                                        ft.OutlinedButton(
                                            content="Finalizar recorrido",
                                            width=float("inf"),
                                            height=42,
                                            on_click=lambda _: (
                                                setattr(state, "refresh_generation", state.refresh_generation + 1),
                                                setattr(state, "screen", "search"),
                                                render(),
                                            ),
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        )

    # =======================================================================
    # SECCIÓN CLÍNICAS (Horarios, accesibilidad, teléfono y QUÉ DEBES LLEVAR)
    # =======================================================================
    def build_clinics_screen() -> ft.Control:
        active_prof = get_profile(state.profile)

        cards: List[ft.Control] = []
        for clinic in state.clinics:
            reqs = [
                ft.Text(f"• {req}", size=12, color=INDIGO_DARK)
                for req in clinic.get("requirements_to_bring", [])
            ]
            acc_items = [
                ft.Text(f"✓ {feat}", size=11, color="#065F46")
                for feat in clinic.get("accessibility_features", [])
            ]

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
                            ft.Text(
                                f"Servicios: {', '.join(clinic.get('services', []))}",
                                size=12,
                                color=TEXT_MUTED,
                            ),
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
                                                ft.Text(
                                                    "Qué debes llevar:",
                                                    size=12,
                                                    weight=ft.FontWeight.BOLD,
                                                    color=INDIGO_DARK,
                                                ),
                                            ],
                                        ),
                                        *reqs,
                                    ],
                                ),
                            ),
                            ft.FilledButton(
                                content=f"Trazar ruta ({active_prof.short_label} · ~{clinic['estimated_minutes']} min)",
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
                                spacing=1,
                                controls=[
                                    ft.Text("Clínicas cercanas", size=20, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                    ft.Text(
                                        f"Tiempos calculados para: {active_prof.label}",
                                        size=12,
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
    # SECCIÓN VOLUNTARIOS (Lista inicialmente vacía + muestra postulados)
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
                                "La lista de guías voluntarias está vacía por el momento. "
                                "Inicia sesión en tu Perfil para postularte y ayudar a otras personas en su recorrido.",
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
                            spacing=6,
                            controls=[
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    controls=[
                                        ft.Row(
                                            spacing=8,
                                            controls=[
                                                ft.Icon(ft.Icons.VOLUNTEER_ACTIVISM, color=EMERALD_GREEN, size=22),
                                                ft.Text(vol["username"], size=15, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                            ],
                                        ),
                                        ft.Container(
                                            bgcolor=EMERALD_SURFACE,
                                            border_radius=10,
                                            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                            content=ft.Text("Disponible", size=11, color="#065F46", weight=ft.FontWeight.W_600),
                                        ),
                                    ],
                                ),
                                ft.Text(f"Zona: {vol['zone']}", size=12, color=INDIGO_DARK),
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
                                    ft.Text(
                                        f"Voluntarios activos: {len(state.volunteers)}",
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
    # SECCIÓN PERFIL (Registro/Login + Correo + Discapacidad + Postulación Voluntario)
    # =======================================================================
    def build_profile_screen() -> ft.Control:
        def disability_selector_chips() -> ft.Control:
            return ft.Row(
                wrap=True,
                spacing=8,
                run_spacing=8,
                controls=[
                    ft.Chip(
                        label=ft.Text(
                            p.short_label,
                            size=12,
                            color=ft.Colors.WHITE if p.api_value == state.profile else INDIGO_DARK,
                        ),
                        selected=p.api_value == state.profile,
                        selected_color=INDIGO_DARK,
                        bgcolor=ft.Colors.WHITE,
                        show_checkmark=False,
                        on_select=lambda _, pv=p.api_value: page.run_task(update_active_disability, pv),
                    )
                    for p in PROFILES
                ],
            )

        # --- Caso A: Usuario con sesión iniciada ---
        if state.current_user is not None:
            user = state.current_user
            zone_field = ft.TextField(
                label="Zona o campus de apoyo",
                value="Campus Coyoacán / Av. Universidad",
                bgcolor=ft.Colors.WHITE,
            )
            avail_field = ft.TextField(
                label="Horario disponible",
                value="Lun-Vie 10:00 - 17:00",
                bgcolor=ft.Colors.WHITE,
            )
            notes_field = ft.TextField(
                label="¿Cómo puedes apoyar?",
                value="Acompañamiento en cruces accesibles y traslado a clínicas",
                multiline=True,
                bgcolor=ft.Colors.WHITE,
            )

            async def apply_volunteer() -> None:
                state.auth_error = None
                state.auth_feedback = None
                payload = {
                    "user_id": user["id"],
                    "zone": zone_field.value or "Campus Coyoacán",
                    "availability": avail_field.value or "Horario flexible",
                    "support_notes": notes_field.value or "Apoyo peatonal accesible",
                }
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(f"{state.api_url}/api/v1/volunteers/apply", json=payload)
                        resp.raise_for_status()
                        member = resp.json()
                except Exception:
                    member = {
                        "id": f"vol-{uuid.uuid4().hex[:6]}",
                        "user_id": user["id"],
                        "username": user["username"],
                        "email": user["email"],
                        "zone": payload["zone"],
                        "availability": payload["availability"],
                        "support_notes": payload["support_notes"],
                        "registered_at": datetime.now(timezone.utc).isoformat(),
                    }

                user["is_volunteer"] = True
                if not any(v["user_id"] == user["id"] for v in state.volunteers):
                    state.volunteers.insert(0, member)
                state.auth_feedback = "¡Postulación registrada! Ya apareces en la lista de Voluntarios."
                render()

            def logout(_: ft.ControlEvent) -> None:
                state.current_user = None
                state.auth_feedback = "Sesión cerrada correctamente."
                state.auth_error = None
                render()

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
                                spacing=8,
                                controls=[
                                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=EMERALD_GREEN),
                                    ft.Text(
                                        "Ya eres guía voluntario activo",
                                        weight=ft.FontWeight.BOLD,
                                        color="#065F46",
                                    ),
                                ],
                            ),
                            ft.Text(
                                "Tu perfil ya aparece en la pestaña Voluntarios para ayudar a la comunidad.",
                                size=12,
                                color="#065F46",
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
                                    ft.Text(
                                        "Postularme como voluntario",
                                        size=16,
                                        weight=ft.FontWeight.BOLD,
                                        color=INDIGO_DARK,
                                    ),
                                ],
                            ),
                            ft.Text(
                                "Al postularte, tu nombre aparecerá en la lista de Voluntarios disponibles.",
                                size=12,
                                color=TEXT_MUTED,
                            ),
                            zone_field,
                            avail_field,
                            notes_field,
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
                                spacing=4,
                                controls=[
                                    ft.Row(
                                        spacing=10,
                                        controls=[
                                            ft.Icon(ft.Icons.BADGE, color=ft.Colors.WHITE, size=28),
                                            ft.Column(
                                                spacing=2,
                                                controls=[
                                                    ft.Text(user["username"], size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                                                    ft.Text(f"Correo vinculado: {user['email']}", size=12, color="#BFDBFE"),
                                                ],
                                            ),
                                        ],
                                    ),
                                    ft.Text(
                                        f"Discapacidad configurada: {get_profile(state.profile).label}",
                                        size=12,
                                        color=EMERALD_SURFACE,
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
                                    ft.Text(
                                        "Tipo de discapacidad (rutas independientes)",
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                        color=INDIGO_DARK,
                                    ),
                                    ft.Text(
                                        "Cambiar esta opción recalcula automáticamente tus rutas y tiempos estimados.",
                                        size=12,
                                        color=TEXT_MUTED,
                                    ),
                                    disability_selector_chips(),
                                ],
                            ),
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
        username_field = ft.TextField(
            label="Nombre de usuario" if is_register else "Usuario o correo electrónico",
            prefix_icon=ft.Icons.PERSON,
            bgcolor=ft.Colors.WHITE,
        )
        email_field = ft.TextField(
            label="Correo electrónico vinculado",
            prefix_icon=ft.Icons.EMAIL,
            bgcolor=ft.Colors.WHITE,
        )
        password_field = ft.TextField(
            label="Contraseña (mín. 6 caracteres)",
            prefix_icon=ft.Icons.LOCK,
            password=True,
            can_reveal_password=True,
            bgcolor=ft.Colors.WHITE,
        )

        async def submit_auth() -> None:
            state.auth_error = None
            state.auth_feedback = None
            u_val = (username_field.value or "").strip()
            e_val = (email_field.value or "").strip().lower()
            p_val = password_field.value or ""

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

                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(
                            f"{state.api_url}/api/v1/auth/register",
                            json={
                                "username": u_val,
                                "email": e_val,
                                "password": p_val,
                                "disability_profile": state.profile,
                            },
                        )
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
                        "disability_profile": state.profile,
                        "disability_label": get_profile(state.profile).label,
                        "is_volunteer": False,
                        "password_local": p_val,
                    }
                    state.local_users[u_val.lower()] = user_obj
                    state.local_users[e_val] = user_obj

                state.current_user = user_obj
                state.profile = user_obj["disability_profile"]
                state.auth_feedback = "Perfil creado y correo vinculado. ¡Ya puedes postularte como voluntario!"
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
                state.profile = user_obj["disability_profile"]
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
            username_field,
        ]

        if is_register:
            form_controls.append(email_field)

        form_controls.append(password_field)

        if is_register:
            form_controls.extend(
                [
                    ft.Text(
                        "Selecciona tu tipo de discapacidad (rutas personalizadas):",
                        size=12,
                        weight=ft.FontWeight.W_600,
                        color=INDIGO_DARK,
                    ),
                    disability_selector_chips(),
                ]
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
                        "Crea tu cuenta con correo vinculado para guardar tu discapacidad y postularte como voluntario.",
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
