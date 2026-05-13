# src/pipeline/exporter.py
"""
Exporter — Módulo 5a

Responsabilidades:
  - Exportar FinancialResult a Google Sheets en batches
  - Persistir todos los resultados (pass y drop) en PostgreSQL
  - Nunca bloquear el pipeline: consume de una asyncio.Queue
  - Reintentar escrituras fallidas con backoff exponencial
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Union

import asyncpg
import gspread_asyncio
import structlog
from google.oauth2.service_account import Credentials
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings
from src.pipeline.financial_calc import FinancialResult, FinancialDropReason

log = structlog.get_logger(__name__)

# Sentinel para señalar fin de cola
_QUEUE_DONE = None

# Batch size para escrituras en Sheets
_SHEETS_BATCH_SIZE = 50

# Cabecera del Google Sheet
_SHEETS_HEADER = [
    "ASIN", "EAN", "Title", "Brand",
    "Buy Price (€)", "BuyBox Price (€)",
    "FBA Fee (€)", "Referral Fee (€)", "Prep/Ship (€)",
    "Net Profit (€)", "ROI (%)",
    "BSR Rank", "BSR Category", "BSR Top %",
    "BuyBox Seller", "BuyBox FBA",
    "Exported At",
]


# ══════════════════════════════════════════════════════════════════
#  Google Sheets writer
# ══════════════════════════════════════════════════════════════════

class SheetsWriter:
    """
    Escribe FinancialResult en Google Sheets en batches.
    Usa gspread_asyncio para operaciones no bloqueantes.
    """

    def __init__(self) -> None:
        self._agcm: gspread_asyncio.AsyncioGspreadClientManager | None = None
        self._worksheet = None
        self._pending: list[list] = []

    async def setup(self) -> None:
        """Inicializa la conexión y asegura que existe la cabecera."""
        def _get_credentials():
            scopes = [
                "https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive",
            ]
            return Credentials.from_service_account_file(
                settings.google_credentials_json_path,
                scopes=scopes,
            )

        self._agcm = gspread_asyncio.AsyncioGspreadClientManager(
            _get_credentials
        )
        agc = await self._agcm.authorize()
        spreadsheet = await agc.open_by_key(settings.google_sheets_id)

        # Usar primera hoja o crearla si no existe
        try:
            self._worksheet = await spreadsheet.get_worksheet(0)
        except Exception:
            self._worksheet = await spreadsheet.add_worksheet(
                title="FBA Results", rows=10000, cols=len(_SHEETS_HEADER)
            )

        # Escribir cabecera si la hoja está vacía
        all_values = await self._worksheet.get_all_values()
        if not all_values:
            await self._worksheet.append_row(
                _SHEETS_HEADER, value_input_option="RAW"
            )
            log.info("sheets.header_written")

    async def append(self, result: FinancialResult) -> None:
        """Añade una fila al buffer pendiente."""
        row = [
            result.asin,
            result.ean,
            result.title[:100],          # truncar títulos largos
            result.brand,
            result.buy_price,
            result.buybox_price,
            result.fees.fba_fee,
            result.fees.referral_fee,
            result.fees.prep_shipping,
            result.net_profit,
            result.roi_pct,
            result.bsr_rank,
            result.bsr_category,
            result.bsr_top_pct,
            result.buybox_seller_name,
            "Sí" if result.buybox_is_fba else "No",
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        ]
        self._pending.append(row)

        if len(self._pending) >= _SHEETS_BATCH_SIZE:
            await self.flush()

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=60),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def flush(self) -> None:
        """Escribe el buffer pendiente en Sheets y lo vacía."""
        if not self._pending or self._worksheet is None:
            return

        batch = self._pending.copy()
        self._pending.clear()

        await self._worksheet.append_rows(
            batch, value_input_option="USER_ENTERED"
        )
        log.info("sheets.flushed", rows=len(batch))


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
        self._sheets = SheetsWriter()
        self._db = DatabaseWriter()
        self.stats = {"pass": 0, "drop": 0, "errors": 0}

    async def setup(self) -> None:
        await asyncio.gather(
            self._sheets.setup(),
            self._db.setup(),
        )
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

        # Flush final de cualquier batch pendiente en Sheets
        await self._sheets.flush()

    async def _process(
        self,
        item: Union[FinancialResult, FinancialDropReason, dict],
    ) -> None:
        try:
            if isinstance(item, FinancialResult):
                await asyncio.gather(
                    self._sheets.append(item),
                    self._db.write_pass(item, self.run_id),
                )
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