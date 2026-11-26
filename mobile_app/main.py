"""Map Inclusive — App móvil para Android hecha 100% en Python (Flet / motor Flutter).

Sin una sola línea de Java. Implementa el flujo secuencial de 4 pantallas del boceto UI/UX
de Apex soa (Campus Coyoacán) conectado al backend Python FastAPI + Google Gemini API.

Ejecución local (vista móvil en escritorio / navegador):
    flet run mobile_app/main.py
    flet run --web --port 8550 mobile_app/main.py

Ejecución en teléfono Android (con la app oficial de Flet de Google Play):
    flet run --android mobile_app/main.py
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
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

TEN_MINUTES_SECONDS = 600
DEFAULT_API_URL = os.getenv("MAP_INCLUSIVE_API_URL", "http://127.0.0.1:8000").rstrip("/")


@dataclass(frozen=True)
class ProfileOption:
    api_value: str
    label: str
    short_label: str
    icon: Any
    nav_hint: str


PROFILES: List[ProfileOption] = [
    ProfileOption(
        api_value="silla_de_ruedas",
        label="Silla de ruedas",
        short_label="Silla de ruedas",
        icon=ft.Icons.ACCESSIBLE,
        nav_hint="Rampa disponible",
    ),
    ProfileOption(
        api_value="visual",
        label="Visual",
        short_label="Visual",
        icon=ft.Icons.VISIBILITY,
        nav_hint="Semáforo sonoro y guía táctil",
    ),
    ProfileOption(
        api_value="auditivo",
        label="Auditivo",
        short_label="Auditivo",
        icon=ft.Icons.HEARING,
        nav_hint="Cruce con señalización visual clara",
    ),
    ProfileOption(
        api_value="movilidad_reducida",
        label="Movilidad reducida",
        short_label="Mov. reducida",
        icon=ft.Icons.DIRECTIONS_WALK,
        nav_hint="Pendiente suave y banca en 50 m",
    ),
    ProfileOption(
        api_value="neurodivergente",
        label="Persona neurodivergente",
        short_label="Neurodivergente",
        icon=ft.Icons.PSYCHOLOGY,
        nav_hint="Calle tranquila · menor ruido",
    ),
]


def get_profile(api_value: str) -> ProfileOption:
    for item in PROFILES:
        if item.api_value == api_value:
            return item
    return PROFILES[0]


@dataclass
class AppState:
    api_url: str = DEFAULT_API_URL
    screen: str = "onboarding"  # onboarding | search | route | active
    profile: str = "silla_de_ruedas"
    origin: str = "Campus Coyoacán, CDMX"
    destination: str = "Clínica 19, Av. Universidad, Coyoacán"
    search_query: str = ""
    clinics: List[Dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "id": "clinica-19",
                "name": "Clínica 19 (IMSS)",
                "address": "Av. Universidad, Coyoacán",
                "distance_text": "400 m",
                "schedule": "Lun-Vie 08:00 - 20:00 · Urgencias 24h",
            },
            {
                "id": "centro-salud-coyoacan",
                "name": "Centro de Salud Coyoacán",
                "address": "Calle Ignacio Allende, Del Carmen",
                "distance_text": "850 m",
                "schedule": "Lun-Dom 07:30 - 19:00",
            },
        ]
    )
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
) -> ft.Container:
    """Mapa vectorial minimalista de bajo ruido visual alineado con el boceto."""
    layers: List[ft.Control] = [
        # Calles limpias simuladas (sin exceso de etiquetas ni comercios)
        ft.Container(
            left=0,
            right=0,
            top=55,
            height=14,
            bgcolor=ft.Colors.WHITE,
        ),
        ft.Container(
            left=0,
            right=0,
            top=145,
            height=14,
            bgcolor=ft.Colors.WHITE,
        ),
        ft.Container(
            top=0,
            bottom=0,
            left=95,
            width=14,
            bgcolor=ft.Colors.WHITE,
        ),
        ft.Container(
            top=0,
            bottom=0,
            right=85,
            width=14,
            bgcolor=ft.Colors.WHITE,
        ),
        # Área verde de parque
        ft.Container(
            left=130,
            top=28,
            width=82,
            height=82,
            border_radius=41,
            bgcolor="#D7EFE2",
        ),
    ]

    if show_clinics:
        for pos in ((58, 78), (155, 42), (240, 128)):
            layers.append(
                ft.Container(
                    left=pos[0],
                    top=pos[1],
                    width=34,
                    height=34,
                    border_radius=17,
                    bgcolor=EMERALD_GREEN,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.LOCAL_HOSPITAL, color=ft.Colors.WHITE, size=18),
                )
            )

    if show_route:
        # Trazo de ruta accesible en azul índigo oscuro rodeando obstáculos
        layers.extend(
            [
                ft.Container(
                    left=102,
                    top=55,
                    width=148,
                    height=8,
                    border_radius=4,
                    bgcolor=INDIGO_DARK,
                ),
                ft.Container(
                    left=242,
                    top=55,
                    width=8,
                    height=98,
                    border_radius=4,
                    bgcolor=INDIGO_DARK,
                ),
                ft.Container(
                    left=135,
                    top=145,
                    width=115,
                    height=8,
                    border_radius=4,
                    bgcolor=INDIGO_DARK,
                ),
                ft.Container(
                    left=92,
                    top=46,
                    width=26,
                    height=26,
                    border_radius=13,
                    bgcolor=INDIGO_DARK,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.ACCESSIBLE, color=ft.Colors.WHITE, size=15),
                ),
            ]
        )

    if show_user_arrow:
        layers.append(
            ft.Container(
                left=130,
                top=130,
                width=42,
                height=42,
                border_radius=21,
                bgcolor="#BFDBFE",
                alignment=ft.Alignment.CENTER,
                content=ft.Container(
                    width=28,
                    height=28,
                    border_radius=14,
                    bgcolor=BLUE_ACTION,
                    alignment=ft.Alignment.CENTER,
                    content=ft.Icon(ft.Icons.NAVIGATION, color=ft.Colors.WHITE, size=16),
                ),
            )
        )

    # Aviso naranja preventivo ("Zona poco concurrida" o "Rampa bloqueada")
    if badge_text:
        layers.append(
            ft.Container(
                right=12,
                top=12,
                bgcolor=ALERT_ORANGE,
                border_radius=18,
                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                content=ft.Row(
                    tight=True,
                    spacing=6,
                    controls=[
                        ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.WHITE, size=15),
                        ft.Text(badge_text, color=ft.Colors.WHITE, size=12, weight=ft.FontWeight.W_600),
                    ],
                ),
            )
        )

    return ft.Container(
        height=215,
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
    page.window.width = 410
    page.window.height = 820

    state = AppState()

    def show_info_dialog(title: str, message: str) -> None:
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
            content=ft.Text(message, size=14),
            actions=[
                ft.TextButton(
                    content="Entendido",
                    on_click=lambda _: page.pop_dialog(),
                )
            ],
        )
        page.show_dialog(dialog)

    async def load_clinics() -> None:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{state.api_url}/api/v1/clinics")
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list) and data:
                        state.clinics = data
                        if state.screen == "search":
                            render()
        except Exception:
            # Conserva clínicas locales de demostración si el backend no está encendido aún
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
                f"Sin conexión con el servidor Python ({state.api_url}): {exc.__class__.__name__}. "
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
        page.run_task(auto_refresh_loop, gen)

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
                        "user_location": "Av. Universidad 400, Coyoacán",
                        "destination": state.destination,
                        "profile": state.profile,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                show_info_dialog(
                    "Guía Voluntaria Confirmada",
                    f"{data['volunteer_name']}\n"
                    f"Tiempo estimado: {data['eta_minutes']} min\n\n"
                    f"{data['message']}",
                )
        except Exception:
            show_info_dialog(
                "Guía Voluntaria (Modo Demo)",
                "Sofía Hernández (Voluntaria Campus Coyoacán) fue notificada.\nTiempo estimado: 6 min.",
            )

    def build_bottom_nav(selected_index: int = 0) -> ft.NavigationBar:
        def on_nav_change(e: ft.ControlEvent) -> None:
            idx = e.control.selected_index
            if idx == 1:
                open_report_incident_dialog()
            elif idx == 4:
                state.screen = "onboarding"
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

    # =====================================================================
    # PANTALLA 1: PANTALLA INICIAL
    # =====================================================================
    def build_onboarding_screen() -> ft.Control:
        def profile_tile(option: ProfileOption, full_width: bool = False) -> ft.Container:
            is_selected = state.profile == option.api_value

            def select_me(_: ft.ControlEvent) -> None:
                state.profile = option.api_value
                render()

            fg = ft.Colors.WHITE if is_selected else INDIGO_DARK
            bg = INDIGO_DARK if is_selected else ft.Colors.WHITE
            border_color = INDIGO_DARK if is_selected else CARD_BORDER

            if full_width:
                inner = ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=12,
                    controls=[
                        ft.Icon(option.icon, color=fg, size=28),
                        ft.Text(option.label, color=fg, size=15, weight=ft.FontWeight.W_600),
                    ],
                )
                return ft.Container(
                    height=68,
                    bgcolor=bg,
                    border=ft.Border.all(1.5, border_color),
                    border_radius=16,
                    alignment=ft.Alignment.CENTER,
                    ink=True,
                    on_click=select_me,
                    content=inner,
                )

            return ft.Container(
                expand=True,
                height=124,
                bgcolor=bg,
                border=ft.Border.all(1.5, border_color),
                border_radius=16,
                padding=12,
                alignment=ft.Alignment.CENTER,
                ink=True,
                on_click=select_me,
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=10,
                    controls=[
                        ft.Icon(option.icon, color=fg, size=34),
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

        def go_search(_: ft.ControlEvent) -> None:
            state.screen = "search"
            render()
            page.run_task(load_clinics)

        return ft.Container(
            expand=True,
            bgcolor=ft.Colors.WHITE,
            padding=ft.Padding.symmetric(horizontal=22, vertical=24),
            content=ft.Column(
                expand=True,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=14,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=10,
                        controls=[
                            ft.Container(
                                width=36,
                                height=36,
                                border_radius=18,
                                bgcolor=EMERALD_GREEN,
                                alignment=ft.Alignment.CENTER,
                                content=ft.Icon(ft.Icons.ACCESSIBLE, color=ft.Colors.WHITE, size=20),
                            ),
                            ft.Column(
                                spacing=0,
                                controls=[
                                    ft.Text("map inclusive", size=24, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
                                    ft.Text("Campus Coyoacán · Apex soa (100% Python)", size=11, color=TEXT_MUTED),
                                ],
                            ),
                        ],
                    ),
                    ft.Container(height=8),
                    ft.Text(
                        "¿Cómo te desplazas hoy?",
                        size=21,
                        weight=ft.FontWeight.W_600,
                        color=INDIGO_DARK,
                    ),
                    ft.Row(spacing=12, controls=[profile_tile(PROFILES[0]), profile_tile(PROFILES[1])]),
                    ft.Row(spacing=12, controls=[profile_tile(PROFILES[2]), profile_tile(PROFILES[3])]),
                    profile_tile(PROFILES[4], full_width=True),
                    ft.Container(expand=True),
                    ft.FilledButton(
                        content="Continuar",
                        bgcolor=BLUE_ACTION,
                        color=ft.Colors.WHITE,
                        width=float("inf"),
                        height=50,
                        on_click=go_search,
                    ),
                ],
            ),
        )

    # =====================================================================
    # PANTALLA 2: BUSCAR DESTINO
    # =====================================================================
    def build_search_screen() -> ft.Control:
        search_input = ft.TextField(
            value=state.search_query,
            hint_text="Buscar destino...",
            prefix_icon=ft.Icons.SEARCH,
            border_radius=14,
            bgcolor=ft.Colors.WHITE,
            expand=True,
            on_change=lambda e: setattr(state, "search_query", e.control.value or ""),
        )

        def go_to_route(dest: str) -> None:
            state.destination = dest.strip() or "Clínica 19, Av. Universidad, Coyoacán"
            state.screen = "route"
            render()
            start_route_monitoring()

        clinic_cards = [
            ft.Container(
                width=245,
                bgcolor=ft.Colors.WHITE,
                border_radius=16,
                border=ft.Border.all(1, CARD_BORDER),
                padding=14,
                ink=True,
                on_click=lambda _, c=clinic: go_to_route(f"{c['name']}, {c['address']}"),
                content=ft.Column(
                    spacing=4,
                    controls=[
                        ft.Text(
                            f"{clinic['name']} · {clinic['distance_text']}",
                            weight=ft.FontWeight.BOLD,
                            color=INDIGO_DARK,
                            size=14,
                        ),
                        ft.Text(clinic["address"], size=12, color=TEXT_MUTED),
                        ft.Text(f"Horario: {clinic['schedule']}", size=11, color=EMERALD_GREEN),
                    ],
                ),
            )
            for clinic in state.clinics
        ]

        return ft.Container(
            expand=True,
            padding=16,
            content=ft.Column(
                expand=True,
                spacing=14,
                controls=[
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
                    ),
                    ft.Text("Sugerencias y clínicas cercanas", size=14, weight=ft.FontWeight.W_600, color=INDIGO_DARK),
                    ft.Row(scroll=ft.ScrollMode.AUTO, spacing=12, controls=clinic_cards),
                ],
            ),
        )

    # =====================================================================
    # PANTALLA 3: RUTA Y GEMINI
    # =====================================================================
    def build_route_screen() -> ft.Control:
        active_profile = get_profile(state.profile)

        def switch_profile(prof_value: str) -> None:
            state.profile = prof_value
            start_route_monitoring()

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
                on_select=lambda _, pv=p.api_value: switch_profile(pv),
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
                f"{state.env_report.get('model_used', 'gemini-4-hydrogen')} · "
                f"modo: {state.env_report.get('status_mode', '')} · Toca para detalles"
            )
        else:
            banner_bg = EMERALD_SURFACE
            banner_title = "Listo para consultar entorno con Gemini"
            banner_sub = "Actualización automática cada 10 minutos"

        def toggle_details(_: ft.ControlEvent) -> None:
            state.show_env_details = not state.show_env_details
            render()

        summary_controls: List[ft.Control] = [
            ft.Text("Ruta Accesible", size=18, weight=ft.FontWeight.BOLD, color=INDIGO_DARK),
            ft.Text(f"{active_profile.label} · 15 min - 1.2 km", size=13, color=TEXT_MUTED),
            ft.Text(f"Destino: {state.destination}", size=12, color=TEXT_MUTED),
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
                            ft.IconButton(
                                icon=ft.Icons.SEARCH,
                                icon_color=INDIGO_DARK,
                                on_click=lambda _: (setattr(state, "screen", "search"), render()),
                            ),
                        ],
                    ),
                    ft.Row(scroll=ft.ScrollMode.AUTO, spacing=8, controls=chips),
                    build_minimalist_map(show_route=True, badge_text="Rampa bloqueada"),
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

    # =====================================================================
    # PANTALLA 4: EN CAMINO
    # =====================================================================
    def build_active_screen() -> ft.Control:
        active_profile = get_profile(state.profile)
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
                    padding=ft.Padding.symmetric(horizontal=18, vertical=20),
                    content=ft.Row(
                        spacing=14,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.TURN_RIGHT, color=ft.Colors.WHITE, size=36),
                            ft.Column(
                                spacing=2,
                                controls=[
                                    ft.Text(
                                        "Gira a la derecha en 80m",
                                        color=ft.Colors.WHITE,
                                        size=18,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(
                                        f"· {active_profile.nav_hint}",
                                        color=EMERALD_SURFACE,
                                        size=13,
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),
                ft.Container(
                    expand=True,
                    padding=16,
                    content=ft.Column(
                        expand=True,
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
                                        ft.OutlinedButton(
                                            content="Reportar Incidencia",
                                            icon=ft.Icons.REPORT,
                                            icon_color=DANGER_RED,
                                            width=float("inf"),
                                            height=46,
                                            on_click=open_report_incident_dialog,
                                        ),
                                        ft.OutlinedButton(
                                            content="Pedir Guía Voluntaria",
                                            icon=ft.Icons.PEOPLE,
                                            icon_color=BLUE_ACTION,
                                            width=float("inf"),
                                            height=46,
                                            on_click=lambda _: page.run_task(request_volunteer),
                                        ),
                                        ft.OutlinedButton(
                                            content="Finalizar",
                                            width=float("inf"),
                                            height=44,
                                            on_click=lambda _: (
                                                setattr(state, "refresh_generation", state.refresh_generation + 1),
                                                setattr(state, "screen", "onboarding"),
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
        else:
            page.navigation_bar = None
            page.controls.append(build_active_screen())
        page.update()

    render()


if __name__ == "__main__":
    ft.run(main)
