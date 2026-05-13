# src/main.py
"""
Orquestador principal — Módulo 5b

Ejecuta el pipeline completo:
  1. Lee CSV → ingest_queue
  2. N workers consumen ingest_queue:
       EANResolver → ShieldChain → FinancialCalculator → results_queue
  3. Exporter consume results_queue → Sheets + DB

Características:
  - Concurrencia configurable via settings.pipeline_concurrency
  - Barra de progreso en consola (tqdm)
  - Resumen final con estadísticas completas
  - Manejo de señales SIGINT/SIGTERM para shutdown limpio
  - Un único punto de entrada: main()
"""
from __future__ import annotations

import asyncio
import signal
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aioredis
import structlog
from tqdm.asyncio import tqdm

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.core.config import settings
from src.core.exceptions import PipelineDropError
from src.core.logger import setup_logging
from src.pipeline.ean_resolver import EANResolver
from src.pipeline.exporter import Exporter
from src.pipeline.financial_calc import FinancialCalculator, FinancialResult
from src.pipeline.ingestor import ProductInput, read_csv
from src.pipeline.shields import ShieldChain

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════
#  Worker
# ══════════════════════════════════════════════════════════════════

class PipelineWorker:
    """
    Un worker procesa un ProductInput completo:
    EAN → ASIN → Escudos → Cálculo financiero → results_queue

    Todos los errores quedan registrados sin interrumpir el pipeline.
    """

    def __init__(
        self,
        worker_id: int,
        resolver: EANResolver,
        shield_chain: ShieldChain,
        calculator: FinancialCalculator,
        results_queue: asyncio.Queue,
    ) -> None:
        self.worker_id = worker_id
        self._resolver = resolver
        self._shields = shield_chain
        self._calc = calculator
        self._results_q = results_queue

    async def process(self, product_input: ProductInput) -> None:
        asin = "UNKNOWN"
        ean  = product_input.ean

        try:
            # ── Paso 1: EAN → ASIN ────────────────────────────────
            resolved = await self._resolver.resolve(product_input)
            if resolved is None:
                log.warning(
                    "worker.ean_not_resolved",
                    worker=self.worker_id,
                    ean=ean,
                )
                await self._results_q.put({
                    "type": "shield_drop",
                    "asin": ean,       # usamos EAN como ID cuando no hay ASIN
                    "ean": ean,
                    "shield": "ean_resolver",
                    "reason": "EAN no encontrado en el catálogo de Amazon",
                })
                return

            asin = resolved.asin

            # ── Paso 2: Los 5 Escudos ─────────────────────────────
            shield_result = await self._shields.run(resolved)
            if not shield_result.passed:
                await self._results_q.put({
                    "type": "shield_drop",
                    "asin": asin,
                    "ean": ean,
                    "shield": shield_result.drop_shield,
                    "reason": shield_result.drop_reason,
                })
                return

            # ── Paso 3: Cálculo financiero ────────────────────────
            financial = await self._calc.evaluate(shield_result.product)
            await self._results_q.put(financial)

        except Exception as exc:
            log.error(
                "worker.unexpected_error",
                worker=self.worker_id,
                ean=ean,
                asin=asin,
                error=str(exc),
                exc_info=True,
            )
            # Registrar como drop para trazabilidad
            await self._results_q.put({
                "type": "shield_drop",
                "asin": asin,
                "ean": ean,
                "shield": "worker_error",
                "reason": f"Error inesperado: {exc}",
            })


# ══════════════════════════════════════════════════════════════════
#  Pool de workers
# ══════════════════════════════════════════════════════════════════

async def _worker_loop(
    worker_id: int,
    ingest_queue: asyncio.Queue,
    results_queue: asyncio.Queue,
    resolver: EANResolver,
    shield_chain: ShieldChain,
    calculator: FinancialCalculator,
    progress: tqdm,
    shutdown_event: asyncio.Event,
) -> None:
    """
    Loop de un worker. Consume ingest_queue hasta que esté
    vacía o se active el shutdown_event.
    """
    worker = PipelineWorker(
        worker_id=worker_id,
        resolver=resolver,
        shield_chain=shield_chain,
        calculator=calculator,
        results_queue=results_queue,
    )

    while not shutdown_event.is_set():
        try:
            product_input: ProductInput = ingest_queue.get_nowait()
        except asyncio.QueueEmpty:
            # Cola vacía: esperar brevemente antes de volver a intentar
            # para no hacer busy-wait
            await asyncio.sleep(0.1)
            continue

        await worker.process(product_input)
        ingest_queue.task_done()
        progress.update(1)

    log.debug("worker.stopped", worker_id=worker_id)


# ══════════════════════════════════════════════════════════════════
#  Pipeline runner
# ══════════════════════════════════════════════════════════════════

async def run_pipeline(csv_path: str | Path) -> dict:
    """
    Ejecuta el pipeline completo y devuelve un dict con estadísticas.
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + \
             f"_{uuid.uuid4().hex[:6]}"
    log.info("pipeline.start", run_id=run_id, csv=str(csv_path))

    # ── Setup de shutdown limpio ───────────────────────────────────
    shutdown_event = asyncio.Event()

    def _handle_signal(sig):
        log.warning("pipeline.shutdown_signal", signal=sig)
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig.name)
        except NotImplementedError:
            # Windows no soporta add_signal_handler
            pass

    # ── Leer CSV y medir total de filas ───────────────────────────
    log.info("pipeline.ingesting", csv=str(csv_path))
    all_inputs: list[ProductInput] = [
        p async for p in read_csv(csv_path)
    ]
    total = len(all_inputs)
    log.info("pipeline.total_products", count=total)

    if total == 0:
        log.warning("pipeline.empty_csv")
        return {"run_id": run_id, "total": 0, "pass": 0, "drop": 0}

    # ── Colas ─────────────────────────────────────────────────────
    ingest_queue: asyncio.Queue  = asyncio.Queue()
    results_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

    for item in all_inputs:
        await ingest_queue.put(item)

    # ── Clientes externos ──────────────────────────────────────────
    async with (
        SPAPIClient()   as sp_client,
        KeepaClient()   as keepa_client,
    ):
        redis = await aioredis.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )

        resolver     = EANResolver(sp_client, redis)
        shield_chain = ShieldChain(
            sp_client=sp_client,
            keepa_client=keepa_client,
            seller_id=settings.sp_api_seller_id,
        )
        calculator   = FinancialCalculator(sp_client)
        exporter     = Exporter(run_id=run_id)
        await exporter.setup()

        # ── Barra de progreso ──────────────────────────────────────
        progress = tqdm(
            total=total,
            desc="Pipeline FBA",
            unit="producto",
            colour="green",
        )

        # ── Lanzar workers + exporter concurrentemente ─────────────
        worker_tasks = [
            asyncio.create_task(
                _worker_loop(
                    worker_id=i,
                    ingest_queue=ingest_queue,
                    results_queue=results_queue,
                    resolver=resolver,
                    shield_chain=shield_chain,
                    calculator=calculator,
                    progress=progress,
                    shutdown_event=shutdown_event,
                ),
                name=f"worker-{i}",
            )
            for i in range(settings.pipeline_concurrency)
        ]

        exporter_task = asyncio.create_task(
            exporter.consume(results_queue),
            name="exporter",
        )

        # ── Esperar a que la cola de ingesta se vacíe ──────────────
        await ingest_queue.join()

        # Señalar a los workers que paren
        shutdown_event.set()
        await asyncio.gather(*worker_tasks, return_exceptions=True)

        # Señalar al exporter que no hay más resultados
        await results_queue.put(None)   # sentinel
        await exporter_task

        progress.close()
        await redis.close()
        await exporter.teardown()

    stats = {
        "run_id":  run_id,
        "total":   total,
        "pass":    exporter.stats["pass"],
        "drop":    exporter.stats["drop"],
        "errors":  exporter.stats["errors"],
        "roi_min": settings.min_roi_pct,
        "bsr_top": settings.bsr_top_pct,
    }

    log.info("pipeline.complete", **stats)
    _print_summary(stats)
    return stats


# ══════════════════════════════════════════════════════════════════
#  Resumen en consola
# ══════════════════════════════════════════════════════════════════

def _print_summary(stats: dict) -> None:
    total  = stats["total"]
    passed = stats["pass"]
    drop   = stats["drop"]
    rate   = (passed / total * 100) if total else 0

    print("\n" + "═" * 52)
    print(f"  Amazon FBA Bot — Resumen de ejecución")
    print("═" * 52)
    print(f"  Run ID        : {stats['run_id']}")
    print(f"  Total leídos  : {total}")
    print(f"  ✓ Exportados  : {passed}  ({rate:.1f}%)")
    print(f"  ✗ Descartados : {drop}")
    print(f"  ⚠ Errores     : {stats['errors']}")
    print(f"  Filtros       : ROI ≥ {stats['roi_min']}% | BSR top {stats['bsr_top']}%")
    print("═" * 52 + "\n")


# ══════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Amazon FBA Bot — Online Arbitrage Pipeline"
    )
    parser.add_argument(
        "--csv",
        type=str,
        default="data/input_sample.csv",
        help="Ruta al CSV de productos (ean,buy_price)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    setup_logging(level=args.log_level)

    try:
        asyncio.run(run_pipeline(csv_path=args.csv))
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        sys.exit(0)


if __name__ == "__main__":
    main()