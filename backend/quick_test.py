"""Prueba corta por terminal para Map Inclusive + Gemini Interactions API.

Ejemplos de uso:
    # 1) Una sola consulta rápida (usa GEMINI_API_KEY si existe, o modo demo si no)
    python3 backend/quick_test.py

    # 2) Probar otro perfil y destino
    python3 backend/quick_test.py --profile neurodivergente --destination "Parque Centenario, Coyoacán"

    # 3) Probar ciclo automático (por defecto cada 600 s = 10 min; usa --interval 15 para demo rápida)
    python3 backend/quick_test.py --loop --interval 15
"""

from __future__ import annotations

import argparse
import json
import time
from dotenv import load_dotenv

from gemini_service import GeminiEnvironmentService
from models import AccessibilityProfile, EnvironmentCheckRequest


def run_once(
    service: GeminiEnvironmentService,
    origin: str,
    destination: str,
    profile: AccessibilityProfile,
    force_refresh: bool,
) -> None:
    req = EnvironmentCheckRequest(
        origin=origin,
        destination=destination,
        profile=profile,
        force_refresh=force_refresh,
    )
    result = service.check_environment(req)
    print("\n" + "=" * 68)
    print(f"Map Inclusive · Actualizado con Gemini ({result.status_mode} | modelo: {result.model_used})")
    print(f"Perfil: {result.profile_label} | Riesgo: {result.nivel_riesgo.value.upper()}")
    print(f"Ruta:   {result.origin} -> {result.destination}")
    print(f"Banner: {result.banner_resumen}")
    print("-" * 68)
    print(f"Clima:       {result.clima}")
    print(f"Bloqueos:    {'; '.join(result.bloqueos)}")
    print(f"Transporte:  {'; '.join(result.transporte_afectado)}")
    print(f"Incidencias: {'; '.join(result.incidencias_accesibilidad)}")
    print(f"Zonas aviso: {'; '.join(result.zonas_riesgo)}")
    print("Recomendaciones:")
    for tip in result.recomendaciones_perfil:
        print(f"  * {tip}")
    if result.fuentes:
        print("Fuentes (Google Search Grounding):")
        for src in result.fuentes:
            print(f"  - {src.title}: {src.url}")
    print(f"Próxima actualización automática: en {result.next_refresh_minutes} min")
    print("=" * 68)


def main() -> None:
    load_dotenv("backend/.env")
    load_dotenv()

    parser = argparse.ArgumentParser(description="Prueba corta de Map Inclusive con Gemini API")
    parser.add_argument("--origin", default="Campus Coyoacán, CDMX")
    parser.add_argument("--destination", default="Clínica 19, Av. Universidad, Coyoacán, CDMX")
    parser.add_argument(
        "--profile",
        choices=[p.value for p in AccessibilityProfile],
        default=AccessibilityProfile.SILLA_DE_RUEDAS.value,
    )
    parser.add_argument("--json", action="store_true", help="Imprime el JSON completo para Android")
    parser.add_argument("--loop", action="store_true", help="Ejecuta actualizaciones periódicas")
    parser.add_argument(
        "--interval",
        type=int,
        default=600,
        help="Segundos entre actualizaciones en modo --loop (600 = 10 min)",
    )
    args = parser.parse_args()

    service = GeminiEnvironmentService()
    profile = AccessibilityProfile(args.profile)

    if args.json:
        req = EnvironmentCheckRequest(
            origin=args.origin,
            destination=args.destination,
            profile=profile,
            force_refresh=True,
        )
        print(json.dumps(service.check_environment(req).model_dump(), ensure_ascii=False, indent=2))
        return

    if not args.loop:
        run_once(service, args.origin, args.destination, profile, force_refresh=True)
        return

    print(f"Iniciando monitoreo periódico cada {args.interval}s (Ctrl+C para detener)...")
    try:
        while True:
            run_once(service, args.origin, args.destination, profile, force_refresh=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitoreo detenido por el usuario.")


if __name__ == "__main__":
    main()
