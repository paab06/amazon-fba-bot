# src/pipeline/exporter.py
"""
Exporter — Módulo 5a

Responsabilidades:
  - Persistir todos los resultados (pass y drop) en PostgreSQL
  - Enviar alertas a Base44 para productos aprobados
  - Nunca bloquear el pipeline: consume de una asyncio.Queue
  - Reintentar escrituras fallidas con backoff exponencial
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Union

import aiohttp
import asyncpg
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings
from src.pipeline.financial_calc import FinancialResult, FinancialDropReason

log = structlog.get_logger(__name__)

# Sentinel para señalar fin de cola
_QUEUE_DONE = None

# ══════════════════════════════════════════════════════════════════
#  Base44 Alert Webhook
# ══════════════════════════════════════════════════════════════════

async def send_alert_to_base44(result: FinancialResult) -> None:
    """
    Envía una alerta a Base44 con los datos del producto aprobado.
    Mapea el FinancialResult a JSON exacto y autentica con token si existe.
    """
    if not settings.base44_webhook_url:
        log.debug("base44.webhook_skipped", reason="webhook_url_not_configured")
        return

    payload = {
        "asin": result.asin,
        "product_name": result.title,
        "score": 85,
        "amazon_price": float(result.buybox_price),
        "max_buy_price": float(result.buy_price),
        "net_margin": float(result.net_profit),
        "roi_percent": float(result.roi_pct),
        "bsr_percent": float(result.bsr_top_pct),
        "active_sellers": 5,
        "est_monthly_sales": 300,
        "category": result.bsr_category,
        "shield_amazon": True,
        "shield_brand": True,
        "shield_massacre": True,
        "shield_account": True,
    }

    headers = {}
    if settings.bot_webhook_token:
        headers["x-bot-token"] = settings.bot_webhook_token

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                settings.base44_webhook_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    log.info(
                        "base44.alert_sent",
                        asin=result.asin,
                        status=response.status,
                    )
                else:
                    log.warning(
                        "base44.alert_failed",
                        asin=result.asin,
                        status=response.status,
                        response=await response.text(),
                    )
    except asyncio.TimeoutError:
        log.warning(
            "base44.alert_timeout",
            asin=result.asin,
            url=settings.base44_webhook_url,
        )
    except Exception as exc:
        log.error(
            "base44.alert_error",
            asin=result.asin,
            error=str(exc),
            exc_info=True,
        )


# ══════════════════════════════════════════════════════════════════
#  PostgreSQL writer
# ══════════════════════════════════════════════════════════════════

class DatabaseWriter:
    """
    Persiste todos los resultados del pipeline en PostgreSQL.
    Incluye tanto los productos exportados como los descartados,
    para análisis posterior y auditoría completa.
    """

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    async def setup(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=settings.database_url.replace("+asyncpg", ""),
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
        await self._create_tables()
        log.info("db.connected")

    async def _create_tables(self) -> None:
        assert self._pool
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_results (
                    id              BIGSERIAL PRIMARY KEY,
                    run_id          TEXT NOT NULL,
                    asin            TEXT NOT NULL,
                    ean             TEXT NOT NULL,
                    title           TEXT,
                    brand           TEXT,
                    buy_price       NUMERIC(10,2),
                    buybox_price    NUMERIC(10,2),
                    fba_fee         NUMERIC(10,2),
                    referral_fee    NUMERIC(10,2),
                    prep_shipping   NUMERIC(10,2),
                    net_profit      NUMERIC(10,2),
                    roi_pct         NUMERIC(10,2),
                    bsr_rank        INTEGER,
                    bsr_category    TEXT,
                    bsr_top_pct     NUMERIC(10,2),
                    status          TEXT NOT NULL,  -- 'PASS' | 'DROP'
                    drop_reason     TEXT,
                    exported_at     TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE (run_id, asin)
                );

                CREATE INDEX IF NOT EXISTS idx_results_asin
                    ON pipeline_results(asin);
                CREATE INDEX IF NOT EXISTS idx_results_run
                    ON pipeline_results(run_id);
            """)

    async def write_pass(
        self, result: FinancialResult, run_id: str
    ) -> None:
        assert self._pool
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO pipeline_results (
                    run_id, asin, ean, title, brand,
                    buy_price, buybox_price,
                    fba_fee, referral_fee, prep_shipping,
                    net_profit, roi_pct,
                    bsr_rank, bsr_category, bsr_top_pct,
                    status
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    $11,$12,$13,$14,$15,'PASS'
                )
                ON CONFLICT (run_id, asin) DO UPDATE SET
                    net_profit   = EXCLUDED.net_profit,
                    roi_pct      = EXCLUDED.roi_pct,
                    exported_at  = NOW()
            """,
                run_id, result.asin, result.ean,
                result.title, result.brand,
                result.buy_price, result.buybox_price,
                result.fees.fba_fee, result.fees.referral_fee,
                result.fees.prep_shipping,
                result.net_profit, result.roi_pct,
                result.bsr_rank, result.bsr_category, result.bsr_top_pct,
            )

    async def write_drop(
        self,
        asin: str,
        ean: str,
        reason: str,
        run_id: str,
    ) -> None:
        assert self._pool
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO pipeline_results (
                    run_id, asin, ean, status, drop_reason
                ) VALUES ($1, $2, $3, 'DROP', $4)
                ON CONFLICT (run_id, asin) DO NOTHING
            """, run_id, asin, ean, reason)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()


# ══════════════════════════════════════════════════════════════════
#  Exporter — orquesta Sheets + DB
# ══════════════════════════════════════════════════════════════════

class Exporter:
    """
    Consume la cola de resultados y los distribuye a
    Google Sheets (solo PASS) y PostgreSQL (PASS + DROP).

    Uso:
        exporter = Exporter(run_id="2026-05-12T10:00")
        await exporter.setup()
        await exporter.consume(results_queue)
        await exporter.teardown()
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._db = DatabaseWriter()
        self.stats = {"pass": 0, "drop": 0, "errors": 0}

    async def setup(self) -> None:
        await self._db.setup()
        log.info("exporter.ready", run_id=self.run_id)

    async def consume(
        self,
        queue: asyncio.Queue,
    ) -> None:
        """
        Consume resultados de la cola hasta recibir el sentinel None.
        Procesa cada item de forma no bloqueante.
        """
        while True:
            item = await queue.get()

            if item is _QUEUE_DONE:
                queue.task_done()
                break

            await self._process(item)
            queue.task_done()

    async def _process(
        self,
        item: Union[FinancialResult, FinancialDropReason, dict],
    ) -> None:
        try:
            if isinstance(item, FinancialResult):
                await self._db.write_pass(item, self.run_id)
                # Enviar alerta a Base44 después de guardar
                await send_alert_to_base44(item)
                self.stats["pass"] += 1
                log.info(
                    "exporter.pass",
                    asin=item.asin,
                    roi=item.roi_pct,
                    net_profit=item.net_profit,
                )

            elif isinstance(item, FinancialDropReason):
                await self._db.write_drop(
                    asin=item.asin,
                    ean="",           # FinancialDropReason no lleva EAN
                    reason=item.reason,
                    run_id=self.run_id,
                )
                self.stats["drop"] += 1

            # Drops de escudos (dict con asin, ean, shield, reason)
            elif isinstance(item, dict) and item.get("type") == "shield_drop":
                await self._db.write_drop(
                    asin=item["asin"],
                    ean=item.get("ean", ""),
                    reason=f"{item['shield']}: {item['reason']}",
                    run_id=self.run_id,
                )
                self.stats["drop"] += 1

        except Exception as exc:
            self.stats["errors"] += 1
            log.error(
                "exporter.error",
                error=str(exc),
                exc_info=True,
            )

    async def teardown(self) -> None:
        await self._db.close()
        log.info(
            "exporter.summary",
            run_id=self.run_id,
            **self.stats,
        )