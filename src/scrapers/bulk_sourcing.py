from __future__ import annotations

import argparse
import asyncio
import csv
import io
from pathlib import Path
from typing import List

import aiofiles
import structlog

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.scrapers.orchestrator import ScraperOrchestrator

log = structlog.get_logger(__name__)


class BulkSourcing:
    def __init__(self, orchestrator: ScraperOrchestrator, sp_client: SPAPIClient, max_concurrency: int = 10) -> None:
        self._orchestrator = orchestrator
        self._sp = sp_client
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def find_external_buy_price(self, ean: str, title: str) -> float:
        """Placeholder async para precio de compra externo (Google Shopping, etc.)."""
        log.debug("bulk_sourcing.external_price_placeholder", ean=ean, title=title[:80])
        await asyncio.sleep(0)
        return 0.0

    async def resolve_asin_to_ean(self, asin: str) -> tuple[str, str] | None:
        """Convierte un ASIN a EAN y título usando SP-API."""
        try:
            return await self._sp.get_ean_from_asin(asin)
        except Exception as exc:
            log.warning("bulk_sourcing.asin_to_ean_failed", asin=asin, error=str(exc))
            return None

    async def process_asins(self, asins: List[str]) -> list[dict[str, float]]:
        """Resuelve ASINs a EANs y encuentra precios de compra válidos."""
        results: list[dict[str, float]] = []

        async def worker(asin: str) -> None:
            async with self._semaphore:
                resolved = await self.resolve_asin_to_ean(asin)
                if not resolved:
                    return

                ean, title = resolved
                buy_price = await self.find_external_buy_price(ean, title)
                if buy_price <= 0:
                    log.warning(
                        "bulk_sourcing.skip.no_buy_price",
                        asin=asin,
                        ean=ean,
                        title=title[:80],
                    )
                    return

                results.append({"ean": ean, "buy_price": buy_price})
                log.info(
                    "bulk_sourcing.product_ready",
                    asin=asin,
                    ean=ean,
                    buy_price=buy_price,
                )

        await asyncio.gather(*(worker(asin) for asin in asins))
        return results

    async def generate_input_csv(self, output_path: Path | str = "data/input.csv") -> Path:
        """Genera el archivo data/input.csv listo para el Ingestor."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        asins = await self._orchestrator.find_arbitrage_opportunities()
        log.info("bulk_sourcing.found_asins", asin_count=len(asins))

        if not asins:
            raise RuntimeError("No se encontraron ASINs en la consulta de arbitraje.")

        rows = await self.process_asins(asins)
        log.info("bulk_sourcing.processed_asins", valid_rows=len(rows))

        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=["ean", "buy_price"])
        writer.writeheader()
        writer.writerows(rows)

        async with aiofiles.open(output_path, mode="w", encoding="utf-8", newline="") as handle:
            await handle.write(csv_buffer.getvalue())

        log.info("bulk_sourcing.input_csv_generated", path=str(output_path), rows=len(rows))
        return output_path


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera data/input.csv usando Keepa Product Finder y SP-API."
    )
    parser.add_argument(
        "--output",
        default="data/input.csv",
        help="Ruta de salida del CSV de entrada.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        help="Máximo de consultas SP-API concurrentes.",
    )
    args = parser.parse_args()

    async with SPAPIClient() as sp_client, KeepaClient() as keepa_client:
        orchestrator = ScraperOrchestrator(sp_client, keepa_client, None)
        bulk_sourcing = BulkSourcing(orchestrator, sp_client, max_concurrency=args.concurrency)
        await bulk_sourcing.generate_input_csv(args.output)


if __name__ == "__main__":
    asyncio.run(main())
