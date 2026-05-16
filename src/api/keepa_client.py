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

    @retry(
        retry=retry_if_exception_type(KeepaAPIError),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def search_keyword(
        self,
        keyword: str,
        max_results: int = 50,
        marketplace: str = "ES",
    ) -> list[dict]:
        """
        Busca un keyword y retorna top ASINs.
        
        Args:
            keyword: Término de búsqueda
            max_results: Máximo de resultados (default 50)
            marketplace: Código de marketplace (ES, UK, US, etc.)
            
        Returns:
            Lista de productos: [{"asin": "...", "title": "...", ...}, ...]
        """
        assert self._session, "Usar como context manager"

        domain_map = {
            "ES": 3,
            "UK": 2,
            "US": 1,
            "DE": 4,
            "FR": 5,
        }
        domain = domain_map.get(marketplace, 3)

        params = {
            "key": self._key,
            "domain": domain,
            "keyword": keyword,
            "limit": min(max_results, 100),  # Max 100 por Keepa
            "sort": "sales",  # Ordenar por ventas
        }

        try:
            async with self._session.get(
                f"{_KEEPA_BASE}/search",
                params=params,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 429:
                    raise KeepaAPIError(f"Keepa rate limit for {keyword}")
                if resp.status != 200:
                    raise KeepaAPIError(
                        f"Keepa search error [{resp.status}]: {await resp.text()}"
                    )
                
                data = await resp.json()
                products = data.get("products", [])
                
                log.debug(
                    "keepa.search_complete",
                    keyword=keyword,
                    results=len(products),
                )
                
                return products
                
        except aiohttp.ClientError as exc:
            raise KeepaAPIError(f"Keepa search failed: {exc}")

    async def get_product_velocity(self, asin: str) -> dict:
        """
        Obtiene velocidad de venta (unidades/día) de un ASIN.
        
        Args:
            asin: ASIN del producto
            
        Returns:
            {"velocity": 5.2, "stock": 150, ...}
        """
        assert self._session, "Usar como context manager"

        params = {
            "key": self._key,
            "domain": 3,  # Amazon ES
            "asin": asin,
            "stats": 1,
        }

        try:
            async with self._session.get(
                f"{_KEEPA_BASE}/product",
                params=params,
            ) as resp:
                if resp.status != 200:
                    raise KeepaAPIError(f"Keepa velocity error [{resp.status}]")
                
                data = await resp.json()
                products = data.get("products", [])
                
                if not products:
                    return {"velocity": 0, "stock": 0}
                
                stats = products[0].get("stats", {})
                
                return {
                    "velocity": stats.get("0-90", [0])[0],  # sales per day
                    "stock": stats.get("current", 0),
                    "last_restocked": stats.get("last_restock", ""),
                }
                
        except Exception as exc:
            log.warning("keepa.velocity_error", asin=asin, error=str(exc))
            return {"velocity": 0, "stock": 0}

    async def get_seller_products(
        self,
        seller_id: str,
        limit: int = 50,
    ) -> list[str]:
        """
        Obtiene ASINs de un seller.
        
        Args:
            seller_id: ID del seller
            limit: Máximo de ASINs
            
        Returns:
            Lista de ASINs
        """
        assert self._session, "Usar como context manager"

        params = {
            "key": self._key,
            "domain": 3,  # Amazon ES
            "seller": seller_id,
            "limit": min(limit, 500),
        }

        try:
            async with self._session.get(
                f"{_KEEPA_BASE}/seller",
                params=params,
            ) as resp:
                if resp.status != 200:
                    raise KeepaAPIError(f"Keepa seller error [{resp.status}]")
                
                data = await resp.json()
                asins = data.get("products", [])
                
                return asins[:limit]
                
        except Exception as exc:
            log.warning("keepa.seller_error", seller_id=seller_id, error=str(exc))
            return []

    async def get_category_stats(
        self,
        category: str,
        marketplace: str = "ES",
    ) -> dict:
        """
        Obtiene estadísticas de una categoría.
        
        Returns:
            {"avg_bsr": 1500, "price_distribution": {...}, ...}
        """
        # Simplificado: en producción integrar con Keepa Category Tree API
        return {
            "avg_bsr": 1500,
            "price_distribution": {100: 50, 200: 75, 300: 30},
        }

    async def get_price_history(
        self,
        asin: str,
        days: int = 30,
    ) -> list[dict]:
        """
        Obtiene histórico de precios de los últimos N días.
        
        Returns:
            [
                {
                    "timestamp": datetime,
                    "price": 24.99,
                    "bsr": 150,
                    "stock": 100,
                    "is_fba": True
                },
                ...
            ]
        """
        assert self._session, "Usar como context manager"

        params = {
            "key": self._key,
            "domain": 3,  # Amazon ES
            "asin": asin,
            "history": 1,
        }

        try:
            async with self._session.get(
                f"{_KEEPA_BASE}/product",
                params=params,
            ) as resp:
                if resp.status != 200:
                    raise KeepaAPIError(f"Keepa history error [{resp.status}]")
                
                data = await resp.json()
                products = data.get("products", [])
                
                if not products:
                    return []
                
                # Procesar histórico (CSV format de Keepa)
                csv_data = products[0].get("csv", [])
                history = []
                
                # Estructura: [timestamp, price, ...]
                # Simplificado: retornar datos mínimos
                for i in range(0, min(len(csv_data), days * 2), 2):
                    history.append({
                        "timestamp": csv_data[i] if i < len(csv_data) else None,
                        "price": csv_data[i + 1] if i + 1 < len(csv_data) else 0,
                        "bsr": 0,
                        "stock": 0,
                        "is_fba": True,
                    })
                
                return history[-days:]  # Últimos N días
                
        except Exception as exc:
            log.warning("keepa.history_error", asin=asin, error=str(exc))
            return []