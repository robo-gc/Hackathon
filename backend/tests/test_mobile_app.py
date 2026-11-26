"""Pruebas de la app móvil 100% Python (Flet) y verificación de cero archivos Java."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

REPO_ROOT = Path(__file__).resolve().parents[2]
MOBILE_MAIN_PATH = REPO_ROOT / "mobile_app" / "main.py"


import sys


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


def test_mobile_app_renders_without_errors() -> None:
    """Verifica perfiles, mapa y renderizado inicial en Flet 1.x."""
    mobile_main = _load_mobile_module()
    assert len(mobile_main.PROFILES) == 5
    assert mobile_main.get_profile("neurodivergente").label == "Persona neurodivergente"

    map_widget = mobile_main.build_minimalist_map(
        show_route=True,
        badge_text="Rampa bloqueada",
        show_clinics=True,
        show_user_arrow=True,
    )
    assert map_widget is not None

    # Simula un ft.Page mínimo para verificar que main(page) construye la Pantalla 1 sin errores
    updates = {"count": 0}
    controls: List[Any] = []
    fake_page = SimpleNamespace(
        title="",
        bgcolor="",
        padding=0,
        window=SimpleNamespace(width=0, height=0),
        controls=controls,
        navigation_bar=None,
        update=lambda: updates.__setitem__("count", updates["count"] + 1),
        run_task=lambda *a, **kw: None,
        show_dialog=lambda d: None,
        pop_dialog=lambda: None,
    )
    mobile_main.main(fake_page)
    assert len(fake_page.controls) == 1
    assert updates["count"] == 1
