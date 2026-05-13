# src/api/keepa_client.py
"""
Keepa Client — wrapper mínimo async para el Escudo 4.
Solo expone get_fba_seller_history() que devuelve
el histórico de vendedores FBA como lista de tuplas
(keepa_timestamp_minutes, fba_seller_count).
"""
from __future__ import annotations

import aiohttp
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.config import settings
from src.core.exceptions import KeepaAPIError

log = structlog.get_logger(__name__)

_KEEPA_BASE = "https://api.keepa.com"


class KeepaClient:

    def __init__(self) -> None:
        self._key = settings.keepa_api_key.get_secret_value()
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "KeepaClient":
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        return self

    async def __aexit__(self, *_):
        if self._session:
            await self._session.close()

    @retry(
        retry=retry_if_exception_type(KeepaAPIError),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def get_fba_seller_history(
        self, asin: str
    ) -> list[tuple[int, int]]:
        """
        Devuelve el histórico de conteo de vendedores FBA.
        Keepa codifica la serie temporal como lista plana:
          [ts0, val0, ts1, val1, ...]
        donde ts es minutos desde la época Keepa.
        """
        assert self._session, "Usar como context manager"

        params = {
            "key": self._key,
            "domain": 3,          # Amazon.es = 3
            "asin": asin,
            "stats": 0,
            "offers": 20,
            "history": 1,
        }

        async with self._session.get(
            f"{_KEEPA_BASE}/product", params=params
        ) as resp:
            if resp.status == 429:
                raise KeepaAPIError("Keepa rate limit — reintentando")
            if resp.status != 200:
                raise KeepaAPIError(
                    f"Keepa error [{resp.status}]: {await resp.text()}"
                )
            data = await resp.json()

        products: list[dict] = data.get("products", [])
        if not products:
            raise KeepaAPIError(f"Keepa: sin datos para ASIN {asin}")

        # csv[10] = NEW_FBA_OFFERS_COUNT en la API de Keepa
        csv_data: list = products[0].get("csv", [])
        fba_series_raw: list[int] | None = (
            csv_data[10] if len(csv_data) > 10 else None
        )

        if not fba_series_raw:
            log.warning("keepa.no_fba_series", asin=asin)
            return []

        # Desempaquetar lista plana → lista de tuplas (ts, count)
        it = iter(fba_series_raw)
        return [
            (ts, count)
            for ts, count in zip(it, it)
            if count != -1   # -1 = sin dato en Keepa
        ]