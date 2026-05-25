#!/usr/bin/env python
"""
Punto de entrada: Doble Flujo 24/7 (Dual Flow Scheduler)

Ejecuta el orquestador que intercala:
- Flujo 1: Monitor de Tiendas (08:00, 20:00)
- Flujo 2: Crawler Autónomo (en huecos)

Uso:
    python start_dual_flow.py                              # Configuración por defecto
    python start_dual_flow.py --monitor "06:00" "18:00"   # Personalizar horarios
    python start_dual_flow.py --cooldown 600              # Cambiar rate limit cooldown

Señales:
    SIGTERM / SIGINT (Ctrl+C): Apagado graceful
"""

import asyncio
import sys
from pathlib import Path

import click

# Agregar raíz del proyecto al path
sys.path.insert(0, str(Path(__file__).parent))

from src.core.logger import setup_logging
from src.scrapers.scheduler import DualFlowScheduler

# ════════════════════════════════════════════════════════════════════
#  CLI Configuration
# ════════════════════════════════════════════════════════════════════


@click.command()
@click.option(
    "--monitor",
    multiple=True,
    default=["08:00", "20:00"],
    help="Horarios de ejecución Flujo 1 (formato HH:MM). Múltiples: --monitor 08:00 --monitor 20:00",
    type=str,
)
@click.option(
    "--cooldown",
    default=300,
    help="Cooldown entre Flujo 1 y Flujo 2 en segundos (rate limit protection)",
    type=int,
)
@click.option(
    "--max-runtime",
    default=60,
    help="Timeout máximo para Flujo 1 en minutos",
    type=int,
)
@click.option(
    "--no-telegram",
    is_flag=True,
    default=False,
    help="Desactivar notificaciones Telegram",
)
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    help="Nivel de logging",
)
def main(
    monitor: tuple[str, ...],
    cooldown: int,
    max_runtime: int,
    no_telegram: bool,
    log_level: str,
) -> None:
    """
    Inicia el orquestador de Doble Flujo.
    
    El sistema ejecutará automáticamente:
    - FLUJO 1 (Monitor de Tiendas) en los horarios especificados
    - FLUJO 2 (Crawler) en los huecos restantes
    
    Ambos flujos se manejan automáticamente sin intervención.
    """
    # Setup logging
    setup_logging(log_level)

    # Convertir monitor a lista (click múltiple retorna tuple vacía si no se especifica)
    monitor_list = list(monitor) if monitor else ["08:00", "20:00"]

    # Banner
    click.echo("""
╔════════════════════════════════════════════════════════════════════╗
║      FBA Bot - Doble Flujo Automatizado (Dual Flow Scheduler)     ║
║                          24/7 Híbrido                            ║
╚════════════════════════════════════════════════════════════════════╝
""")

    click.echo(f"""
⚙️  CONFIGURACIÓN:

  Flujo 1 (Monitor de Tiendas):
    📅 Horarios: {', '.join(monitor_list)}
    ⏱️  Timeout máximo: {max_runtime} minutos

  Flujo 2 (Crawler Autónomo):
    🤖 Automático en huecos
    ⏸️  Pausa durante Flujo 1

  Rate Limit Protection:
    🔒 Cooldown: {cooldown} segundos (entre Flujo 1 y Flujo 2)

  Notifications:
    {"📱 Telegram: Activado" if not no_telegram else "🔇 Telegram: Desactivado"}

  Logging:
    📋 Nivel: {log_level}

""")

    click.echo("🚀 Iniciando orquestador...\n")

    # Crear y ejecutar scheduler
    try:
        scheduler = DualFlowScheduler(
            monitor_times=monitor_list,
            rate_limit_cooldown_seconds=cooldown,
            max_monitor_runtime_minutes=max_runtime,
            telegram_enabled=not no_telegram,
        )

        # Ejecutar el loop async
        asyncio.run(scheduler.start())

    except KeyboardInterrupt:
        click.echo("\n\n✓ Apagado solicitado por usuario")
        sys.exit(0)

    except Exception as e:
        click.echo(f"\n\n✗ Error fatal: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
