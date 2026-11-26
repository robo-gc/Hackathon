"""Pruebas de la app móvil 100% Python (Flet) y verificación de cero archivos Java."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import flet as ft

REPO_ROOT = Path(__file__).resolve().parents[2]
MOBILE_MAIN_PATH = REPO_ROOT / "mobile_app" / "main.py"


def _load_mobile_module() -> Any:
    spec = importlib.util.spec_from_file_location("map_inclusive_mobile", MOBILE_MAIN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_no_java_or_jvm_files_in_repo() -> None:
    """Garantiza que no haya ningún archivo Java/Kotlin/Gradle en el proyecto."""
    forbidden_suffixes = {".java", ".kt", ".kts", ".gradle", ".jar", ".class"}
    found = [
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.rglob("*")
        if p.is_file()
        and ".git" not in p.parts
        and ".venv" not in p.parts
        and p.suffix.lower() in forbidden_suffixes
    ]
    assert found == [], f"Se encontraron archivos prohibidos JVM/Java: {found}"


def test_themes_waze_sheet_voice_steps_and_all_screens() -> None:
    """Verifica Modo Día/Noche, Waze BottomSheet, pasos por voz/visual, sirena WAV y pantallas."""
    mobile_main = _load_mobile_module()

    # 1) Contraste en Modo Día y Modo Noche
    light = mobile_main.get_theme(False)
    dark = mobile_main.get_theme(True)
    assert light.input_text != light.input_bg
    assert dark.input_text != dark.input_bg
    assert light.bg != dark.bg

    # 2) Categorías estilo Waze (3x3 = 9 categorías)
    assert len(mobile_main.WAZE_INCIDENT_CATEGORIES) == 9

    # 3) Instrucciones paso a paso diferentes por discapacidad y SIN audio para auditivo
    steps_wheelchair = mobile_main.build_local_navigation_steps("Clínica 19", ["silla_de_ruedas"])
    steps_visual = mobile_main.build_local_navigation_steps("Clínica 19", ["visual"])
    steps_auditivo = mobile_main.build_local_navigation_steps("Clínica 19", ["auditivo"])
    assert len(steps_wheelchair) == 4
    assert steps_wheelchair[0]["spoken_text"] != steps_visual[0]["spoken_text"]
    assert all(s["spoken_text"] != "" for s in steps_visual)
    assert all(s["spoken_text"] == "" for s in steps_auditivo)

    # 4) Sirena WAV sintetizada en memoria
    wav_bytes = mobile_main.generate_alert_siren_wav()
    assert wav_bytes[:4] == b"RIFF" and wav_bytes[8:12] == b"WAVE"

    # 5) Avatar con foto real base64 y fallback
    sample_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode("ascii")
    assert mobile_main.build_face_avatar(light, sample_b64, size=60) is not None
    assert mobile_main.build_face_avatar(dark, None, size=60) is not None

    # 6) Renderizado completo: tema claro -> modo noche -> pestañas -> Waze BottomSheet -> ruta simulada
    opened_dialogs: List[Any] = []
    fake_page = SimpleNamespace(
        title="",
        bgcolor="",
        theme_mode=None,
        padding=0,
        window=SimpleNamespace(width=0, height=0),
        controls=[],
        navigation_bar=None,
        update=lambda: None,
        run_task=lambda *a, **kw: None,
        show_dialog=lambda d: opened_dialogs.append(d),
        pop_dialog=lambda: opened_dialogs.pop() if opened_dialogs else None,
    )
    mobile_main.main(fake_page)
    assert fake_page.theme_mode == ft.ThemeMode.LIGHT

    # Cambiar a Modo Noche desde el botón en encabezado de Pantalla Inicial
    header_row = fake_page.controls[0].content.controls[0]
    theme_toggle_btn = header_row.controls[1].controls[0]
    theme_toggle_btn.on_click(None)
    assert fake_page.theme_mode == ft.ThemeMode.DARK

    # Ir al mapa y recorrer las 5 pestañas en Modo Noche
    for ctrl in fake_page.controls[0].content.controls:
        if getattr(ctrl, "content", None) == "Continuar al mapa":
            ctrl.on_click(None)
            break
    assert fake_page.navigation_bar is not None

    for tab_idx in (1, 2, 3, 4, 0):
        fake_page.navigation_bar.on_change(SimpleNamespace(control=SimpleNamespace(selected_index=tab_idx)))
        assert len(fake_page.controls) == 1

    # Abrir la ventana estilo Waze ("¿Qué ves?") desde la pestaña Incidencias
    fake_page.navigation_bar.on_change(SimpleNamespace(control=SimpleNamespace(selected_index=1)))
    report_btn = fake_page.controls[0].content.controls[1]
    report_btn.on_click(None)
    assert len(opened_dialogs) == 1
    assert isinstance(opened_dialogs[0], ft.BottomSheet)
