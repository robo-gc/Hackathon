"""Pruebas de la app móvil 100% Python (Flet) y verificación de cero archivos Java."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

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


def test_mobile_routes_clinics_volunteers_and_render() -> None:
    """Verifica rutas independientes, clínicas completas, voluntarios vacíos y renderizado Flet."""
    mobile_main = _load_mobile_module()

    assert len(mobile_main.PROFILES) == 5
    sugg_wheelchair = mobile_main.build_local_suggestions("silla_de_ruedas")
    sugg_auditivo = mobile_main.build_local_suggestions("auditivo")
    assert sugg_wheelchair[0]["route_name"] != sugg_auditivo[0]["route_name"]
    assert sugg_wheelchair[-1]["estimated_minutes"] != sugg_auditivo[-1]["estimated_minutes"]

    clinics = mobile_main.build_local_clinics("visual")
    assert len(clinics) >= 3
    assert all(c["requirements_to_bring"] for c in clinics)
    assert all(c["estimated_minutes"] > 0 for c in clinics)

    # Lista de voluntarios empieza vacía por defecto
    state = mobile_main.AppState()
    assert state.volunteers == []

    # Renderizado inicial en Flet 1.x sin errores
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
