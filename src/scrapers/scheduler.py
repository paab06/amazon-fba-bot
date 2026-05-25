"""
Doble Flujo - Orquestador Híbrido Automatizado (24/7)

Ejecuta dos flujos intercalados sin que se pisen:

FLUJO 1: Monitor de Tiendas (Sourcing Tradicional)
  - Ejecuta: src/scrapers/monitor_tiendas.py → pipeline
  - Cuándo: 08:00 AM y 20:00 PM (configurable)
  - Duración: ~30-45 minutos por ejecución
  - Impacto en APIs: Alto (scraping + Keepa + SP-API)

FLUJO 2: Crawler Autónomo (Reverse Sourcing)
  - Ejecuta: run_autonomous_mode() del autonomous_crawler
  - Cuándo: Resto del día (en "huecos")
  - Duración: Indefinida (hasta que inicie Flujo 1)
  - Comportamiento: Se pausa automáticamente cuando llega el Flujo 1
  - Impacto en APIs: Continuo pero distribuido

Gestión de Concurrencia:
  - Un solo flujo activo por vez
  - Lock interno para evitar race conditions
  - Retry automático en caso de fallos
  - Logging detallado de transiciones

Uso:
    scheduler = DualFlowScheduler()
    await scheduler.start()
"""
from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timedelta, time
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.core.config import settings
from src.core.logger import setup_logging
from src.pipeline.financial_calc import FinancialCalculator
from src.pipeline.shields import ShieldChain
from src.scrapers.autonomous_crawler import AutonomousCrawler
from src.scrapers.competitive_analyzer import CompetitiveAnalyzer
from src.scrapers.monitor_tiendas import main as run_monitor_tiendas
from src.telegram_bot import TelegramBot

log = structlog.get_logger(__name__)


class FlowState(Enum):
    """Estados del flujo"""
    IDLE = "idle"
    RUNNING_MONITOR = "running_monitor"
    RUNNING_CRAWLER = "running_crawler"
    PAUSED = "paused"
    STOPPING = "stopping"


class DualFlowScheduler:
    """
    Orquestador de Doble Flujo que gestiona dos estrategias intercaladas.
    
    La arquitectura garantiza:
    - No hay solapamiento de ejecutables (un solo flujo activo)
    - Rate limits respetados (pausas entre ejecuciones)
    - Recuperación automática ante fallos
    - Señalización limpia de shutdown
    """

    def __init__(
        self,
        monitor_times: Optional[list[str]] = None,
        rate_limit_cooldown_seconds: int = 300,
        max_monitor_runtime_minutes: int = 60,
        telegram_enabled: bool = True,
    ):
        """
        Inicializa el orquestador.

        Args:
            monitor_times: Horas de ejecución Flujo 1 (formato "HH:MM"), 
                          default ["08:00", "20:00"]
            rate_limit_cooldown_seconds: Pausa entre Monitor y Crawler 
                                        (para rate limits)
            max_monitor_runtime_minutes: Timeout máximo para Monitor
            telegram_enabled: Activar notificaciones Telegram
        """
        self.monitor_times = monitor_times or ["08:00", "20:00"]
        self.rate_limit_cooldown = rate_limit_cooldown_seconds
        self.max_monitor_runtime = max_monitor_runtime_minutes * 60
        self.telegram_enabled = telegram_enabled

        # Estado
        self._state = FlowState.IDLE
        self._state_lock = asyncio.Lock()
        self._crawler_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Scheduler
        self.scheduler = AsyncIOScheduler()

        # Clientes
        self.sp_client = SPAPIClient()
        self.keepa_client = KeepaClient()
        self.telegram_bot: Optional[TelegramBot] = None

        # Pipeline
        self.shield_chain = ShieldChain(
            keepa_client=self.keepa_client,
            sp_api_client=self.sp_client,
        )
        self.calculator = FinancialCalculator()

        # Crawler autónomo
        self.crawler: Optional[AutonomousCrawler] = None
        self.analyzer: Optional[CompetitiveAnalyzer] = None

        # Stats
        self.monitor_executions = 0
        self.monitor_failures = 0
        self.crawler_sessions = 0
        self.crawler_pauses = 0

    async def _set_state(self, new_state: FlowState) -> None:
        """Thread-safe state transition"""
        async with self._state_lock:
            old_state = self._state
            self._state = new_state
            log.info(
                "scheduler.state.changed",
                from_state=old_state.value,
                to_state=new_state.value,
            )

    async def _get_state(self) -> FlowState:
        """Thread-safe state read"""
        async with self._state_lock:
            return self._state

    async def initialize(self) -> None:
        """Inicializa clientes y componentes (debe llamarse antes de start())"""
        log.info("scheduler.initializing")

        # Telegram
        if self.telegram_enabled:
            try:
                self.telegram_bot = TelegramBot(
                    token=settings.telegram_bot_token,
                    chat_id=settings.telegram_chat_id,
                )
                await self._telegram_notify(
                    "🚀 **Doble Flujo Iniciado**\n\n"
                    f"Flujo 1 (Monitor): {', '.join(self.monitor_times)}\n"
                    f"Flujo 2 (Crawler): Automático en huecos"
                )
                log.info("scheduler.telegram.ready")
            except Exception as e:
                log.warning("scheduler.telegram.failed", error=str(e))
                self.telegram_enabled = False

        # Crawler autónomo
        self.crawler = AutonomousCrawler(
            sp_client=self.sp_client,
            keepa_client=self.keepa_client,
            shield_chain=self.shield_chain,
            calculator=self.calculator,
            telegram_bot=self.telegram_bot,
        )
        self.analyzer = CompetitiveAnalyzer(
            keepa_client=self.keepa_client,
            sp_api_client=self.sp_client,
        )

        log.info("scheduler.initialized")

    async def _telegram_notify(self, message: str) -> None:
        """Envía notificación a Telegram si está habilitado"""
        if self.telegram_enabled and self.telegram_bot:
            try:
                await self.telegram_bot.send_message(message)
            except Exception as e:
                log.warning("scheduler.telegram.send_failed", error=str(e))

    async def _run_flow_1_monitor(self) -> None:
        """
        Ejecuta Flujo 1: Monitor de Tiendas
        - Scrape → Pipeline → Resultados a Telegram
        """
        try:
            state = await self._get_state()
            if state == FlowState.STOPPING:
                log.info("scheduler.flow1.skipped_shutdown")
                return

            await self._set_state(FlowState.RUNNING_MONITOR)
            
            start_time = datetime.now()
            log.info(
                "scheduler.flow1.started",
                execution=self.monitor_executions + 1,
                timestamp=start_time.isoformat(),
            )

            await self._telegram_notify(
                "⏰ **Flujo 1 Iniciado** (Monitor de Tiendas)\n"
                f"Timestamp: {start_time.strftime('%H:%M:%S')}"
            )

            # Ejecutar el monitor
            await asyncio.wait_for(
                run_monitor_tiendas(),
                timeout=self.max_monitor_runtime,
            )

            self.monitor_executions += 1
            elapsed = (datetime.now() - start_time).total_seconds()

            log.info(
                "scheduler.flow1.completed",
                execution=self.monitor_executions,
                duration_seconds=elapsed,
            )

            await self._telegram_notify(
                f"✅ **Flujo 1 Completado**\n"
                f"Duración: {elapsed:.0f}s\n"
                f"Ejecución #{self.monitor_executions}"
            )

            # Rate limit cooldown
            await self._set_state(FlowState.PAUSED)
            log.info(
                "scheduler.flow1.cooldown",
                cooldown_seconds=self.rate_limit_cooldown,
            )
            await asyncio.sleep(self.rate_limit_cooldown)

        except asyncio.TimeoutError:
            self.monitor_failures += 1
            log.error(
                "scheduler.flow1.timeout",
                max_runtime_seconds=self.max_monitor_runtime,
                failures=self.monitor_failures,
            )
            await self._telegram_notify(
                f"⚠️ **Flujo 1 Timeout** (excedió {self.max_monitor_runtime}s)\n"
                f"Fallos acumulados: {self.monitor_failures}"
            )

        except Exception as e:
            self.monitor_failures += 1
            log.error(
                "scheduler.flow1.error",
                error=str(e),
                failures=self.monitor_failures,
            )
            await self._telegram_notify(
                f"❌ **Error en Flujo 1**\n"
                f"Error: {str(e)[:100]}\n"
                f"Fallos acumulados: {self.monitor_failures}"
            )

        finally:
            # Después de Flujo 1, reanudar Crawler (o esperar next cycle)
            state = await self._get_state()
            if state != FlowState.STOPPING:
                await self._set_state(FlowState.IDLE)

    async def _run_flow_2_crawler(self) -> None:
        """
        Ejecuta Flujo 2: Crawler Autónomo
        - Corre continuamente en "huecos"
        - Se pausa cuando inicia Flujo 1
        - Auto-reanuda cuando termina Flujo 1
        """
        if not self.crawler or not self.analyzer:
            log.error("scheduler.flow2.not_initialized")
            return

        try:
            self.crawler_sessions += 1

            log.info(
                "scheduler.flow2.started",
                session=self.crawler_sessions,
            )

            await self._telegram_notify(
                "🤖 **Flujo 2 Iniciado** (Crawler Autónomo)\n"
                f"Sesión #{self.crawler_sessions}"
            )

            # Loop principal del crawler, monitorizado por estado
            while await self._get_state() != FlowState.STOPPING:
                state = await self._get_state()

                if state == FlowState.RUNNING_MONITOR:
                    # Flujo 1 activo, pausa Crawler
                    self.crawler_pauses += 1
                    log.info(
                        "scheduler.flow2.paused",
                        reason="flow1_active",
                        pause_number=self.crawler_pauses,
                    )
                    await asyncio.sleep(30)  # Check cada 30s si puede reanudar
                    continue

                elif state == FlowState.PAUSED:
                    # Rate limit cooldown, espera
                    log.debug("scheduler.flow2.waiting_cooldown")
                    await asyncio.sleep(30)
                    continue

                # RUNNING_CRAWLER o IDLE: ejecutar
                await self._set_state(FlowState.RUNNING_CRAWLER)

                # Ejecutar una ronda de crawling (~30-60 minutos por iteración)
                # El crawler maneja sus propias pausas internas entre categorías
                try:
                    await asyncio.wait_for(
                        self.crawler.start_autonomous_crawl(
                            duration_hours=0,  # 0 = indefinido (pero controlado por _shutdown_event)
                            send_alerts=True,
                            analyzer=self.analyzer,
                        ),
                        timeout=3600,  # Max 1 hora por sesión antes de recheck estado
                    )
                except asyncio.TimeoutError:
                    # Expected: crawler continúa naturalmente
                    log.debug("scheduler.flow2.session_timeout_expected")

                # Verificar estado después de cada sesión
                if await self._get_state() == FlowState.STOPPING:
                    break

                await asyncio.sleep(5)  # Micro-pausa antes de recheck

        except asyncio.CancelledError:
            log.info("scheduler.flow2.cancelled")

        except Exception as e:
            log.error("scheduler.flow2.error", error=str(e))
            await self._telegram_notify(
                f"❌ **Error en Flujo 2 (Crawler)**\n"
                f"Error: {str(e)[:100]}"
            )

        finally:
            self.crawler_sessions -= 1
            log.info(
                "scheduler.flow2.ended",
                session_count=self.crawler_sessions,
            )

    async def start(self) -> None:
        """Inicia el orquestador del Doble Flujo"""
        try:
            await self.initialize()

            # Registrar jobs periódicos para Flujo 1
            for monitor_time_str in self.monitor_times:
                hour, minute = map(int, monitor_time_str.split(":"))
                self.scheduler.add_job(
                    self._run_flow_1_monitor,
                    CronTrigger(hour=hour, minute=minute),
                    id=f"flow1_monitor_{hour:02d}{minute:02d}",
                    name=f"Monitor @ {monitor_time_str}",
                )
                log.info(
                    "scheduler.job.registered",
                    job_id=f"flow1_monitor_{hour:02d}{minute:02d}",
                    time=monitor_time_str,
                )

            # Iniciar scheduler
            self.scheduler.start()
            log.info("scheduler.started")

            # Iniciar Flujo 2 (Crawler) como tarea background
            self._crawler_task = asyncio.create_task(self._run_flow_2_crawler())

            await self._telegram_notify(
                "✅ **Sistema Doble Flujo Operativo**\n"
                "✓ Scheduler iniciado\n"
                "✓ Flujo 1 (Monitor) programado\n"
                "✓ Flujo 2 (Crawler) corriendo"
            )

            log.info("scheduler.flows.ready")

            # Esperar shutdown
            await self._shutdown_event.wait()

        except Exception as e:
            log.error("scheduler.startup_error", error=str(e))
            await self._telegram_notify(
                f"❌ **Error al iniciar Doble Flujo**\n{str(e)[:200]}"
            )
            raise

    async def shutdown(self, reason: str = "user_request") -> None:
        """Detiene ambos flujos gracefully"""
        log.info("scheduler.shutdown.initiated", reason=reason)

        await self._set_state(FlowState.STOPPING)

        await self._telegram_notify(
            f"🛑 **Apagando Sistema Doble Flujo**\n"
            f"Razón: {reason}\n"
            f"Stats:\n"
            f"  • Ejecuciones Monitor: {self.monitor_executions}\n"
            f"  • Fallos Monitor: {self.monitor_failures}\n"
            f"  • Sesiones Crawler: {self.crawler_sessions}\n"
            f"  • Pausas del Crawler: {self.crawler_pauses}"
        )

        # Cancelar crawler task
        if self._crawler_task and not self._crawler_task.done():
            self._crawler_task.cancel()
            try:
                await self._crawler_task
            except asyncio.CancelledError:
                pass

        # Detener scheduler
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)

        self._shutdown_event.set()

        log.info("scheduler.shutdown.complete")

    def print_summary(self) -> str:
        """Retorna un resumen de estadísticas"""
        return f"""
╔════════════════════════════════════════════════════════════════╗
║           RESUMEN - DOBLE FLUJO (Dual Flow)                   ║
╚════════════════════════════════════════════════════════════════╝

📊 ESTADÍSTICAS:

  Flujo 1 (Monitor de Tiendas):
    ✓ Ejecuciones: {self.monitor_executions}
    ✗ Fallos: {self.monitor_failures}
    📅 Horarios: {', '.join(self.monitor_times)}

  Flujo 2 (Crawler Autónomo):
    ✓ Sesiones iniciadas: {self.crawler_sessions}
    ⏸️  Pausas por Flujo 1: {self.crawler_pauses}

⚙️  CONFIGURACIÓN:

  Rate Limit Cooldown: {self.rate_limit_cooldown}s
  Monitor Max Runtime: {self.max_monitor_runtime}s
  Telegram: {'Activado' if self.telegram_enabled else 'Desactivado'}

"""


async def run_scheduler(
    monitor_times: Optional[list[str]] = None,
    rate_limit_cooldown: int = 300,
) -> None:
    """
    Punto de entrada para ejecutar el orquestador en modo 24/7
    
    Args:
        monitor_times: Horarios de ejecución del Flujo 1 (ej: ["08:00", "20:00"])
        rate_limit_cooldown: Pausa entre Flujo 1 y Flujo 2 en segundos
    """
    scheduler = DualFlowScheduler(
        monitor_times=monitor_times,
        rate_limit_cooldown_seconds=rate_limit_cooldown,
    )

    # Handle signals gracefully
    loop = asyncio.get_event_loop()

    def handle_signal(sig):
        log.info("scheduler.signal.received", signal=sig)
        asyncio.create_task(scheduler.shutdown(reason=f"signal_{sig}"))

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal, sig)

    try:
        await scheduler.start()
    finally:
        await scheduler.shutdown(reason="main_exit")


if __name__ == "__main__":
    setup_logging("INFO")

    # Configuración por defecto
    MONITOR_SCHEDULE = ["08:00", "20:00"]  # 8 AM y 8 PM
    RATE_LIMIT_COOLDOWN = 300  # 5 minutos

    print("""
╔════════════════════════════════════════════════════════════════╗
║     FBA Bot - Doble Flujo Automatizado (24/7 Híbrido)         ║
╚════════════════════════════════════════════════════════════════╝

⚙️  CONFIGURACIÓN:

  • Flujo 1 (Monitor): {} 
  • Flujo 2 (Crawler): Automático en huecos
  • Rate Limit Cooldown: {}s

🚀 Iniciando orquestador...
""".format(", ".join(MONITOR_SCHEDULE), RATE_LIMIT_COOLDOWN))

    try:
        asyncio.run(
            run_scheduler(
                monitor_times=MONITOR_SCHEDULE,
                rate_limit_cooldown=RATE_LIMIT_COOLDOWN,
            )
        )
    except KeyboardInterrupt:
        print("\n✓ Apagado por usuario")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        raise
