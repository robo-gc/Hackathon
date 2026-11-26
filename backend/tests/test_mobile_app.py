"""Pruebas de la app móvil 100% Python (Flet) y verificación de cero archivos Java."""

from __future__ import annotations

import base64
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


def test_mobile_multi_disability_siren_avatar_and_all_screens() -> None:
    """Verifica multi-discapacidad, sirena WAV, avatar con foto, historial y todas las pantallas."""
    mobile_main = _load_mobile_module()

    # 1) Múltiples discapacidades generan rutas combinadas y tiempos distintos
    sugg_single = mobile_main.build_local_suggestions(["auditivo"])
    sugg_multi = mobile_main.build_local_suggestions(["silla_de_ruedas", "visual", "neurodivergente"])
    assert len(sugg_multi[0]["disabilities"]) == 3
    assert sugg_multi[-1]["estimated_minutes"] > sugg_single[-1]["estimated_minutes"]

    # 2) Sirena WAV sintetizada en memoria correctamente (RIFF WAVE header)
    wav_bytes = mobile_main.generate_alert_siren_wav()
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"
    assert len(wav_bytes) > 10_000

    # 3) Avatar renderiza foto real en base64 y fallback sin foto
    sample_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode("ascii")
    assert mobile_main.build_face_avatar(sample_b64, size=60) is not None
    assert mobile_main.build_face_avatar(None, size=60) is not None

    # 4) Lista de voluntarios empieza vacía e historial tiene registros iniciales
    state = mobile_main.AppState()
    assert state.volunteers == []
    assert len(state.incidents) >= 2

    # 5) Renderizado de todas las pestañas de la app Flet sin errores
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

    # Ir a Explorar rutas -> recorrer las 5 pestañas (Mapa, Incidencias, Clínicas, Voluntarios, Perfil)
    onboarding_col = fake_page.controls[0].content
    for ctrl in onboarding_col.controls:
        if hasattr(ctrl, "content") and ctrl.content == "Continuar al mapa":
            ctrl.on_click(None)
            break
    assert fake_page.navigation_bar is not None

    for tab_idx in (1, 2, 3, 4, 0):
        fake_page.navigation_bar.on_change(
            SimpleNamespace(control=SimpleNamespace(selected_index=tab_idx))
        )
        assert len(fake_page.controls) == 1
