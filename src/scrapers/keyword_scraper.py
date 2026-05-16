# src/scrapers/keyword_scraper.py
"""
Keyword Scraper — Módulo de Descubrimiento de Productos

Responsabilidades:
  - Buscar keywords en Keepa
  - Extraer ASINs de top sellers
  - Filtrar por criterios de negocio
  - Generar CSV de candidatos
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Optional

import structlog

from src.api.keepa_client import KeepaClient
from src.core.config import settings
from src.core.exceptions import KeepaAPIError

log = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class ScrapedProduct:
    """Producto descubierto por scraper"""
    asin: str
    title: str
    brand: str
    current_price: float
    estimated_buy_price: float  # Calculado: precio actual - margen
    bsr_rank: int
    bsr_category: str
    review_count: int
    rating: float
    data_source: str  # 'keyword_search', 'competitor', 'monitor'


class KeywordScraper:
    """
    Busca keywords en Keepa y extrae ASINs viables.
    
    Uso:
        scraper = KeywordScraper(keepa_client)
        async for product in scraper.search("gaming mouse"):
            print(product.asin, product.title)
    """

    def __init__(self, keepa_client: KeepaClient) -> None:
        """
        Args:
            keepa_client: Cliente Keepa para queries
        """
        self._keepa = keepa_client

    async def search_keyword(
        self,
        keyword: str,
        max_results: int = 50,
        min_bsr: Optional[int] = None,
        max_price: Optional[float] = None,
    ) -> AsyncIterator[ScrapedProduct]:
        """
        Busca un keyword y emite productos viables.
        
        Args:
            keyword: Término de búsqueda (ej: "gaming mouse")
            max_results: Cantidad máxima de resultados (default: 50)
            min_bsr: Filtro BSR mínimo (ej: 5000 = top 1%)
            max_price: Filtro precio máximo
            
        Yields:
            ScrapedProduct si pasa filtros básicos
            
        Ejemplo:
            async for product in scraper.search_keyword("mouse gaming"):
                print(f"{product.asin}: {product.title} - €{product.current_price}")
        """
        log.info(
            "keyword_scraper.start",
            keyword=keyword,
            max_results=max_results,
        )

        try:
            # ── 1. Buscar en Keepa ────────────────────────────────────
            results = await self._keepa.search_keyword(
                keyword=keyword,
                max_results=max_results,
                marketplace="ES",  # Amazon Spain
            )
            
            if not results:
                log.warning("keyword_scraper.no_results", keyword=keyword)
                return

            # ── 2. Procesar resultados ─────────────────────────────────
            for idx, item in enumerate(results):
                try:
                    # Validar datos básicos
                    if not item.get("asin") or not item.get("title"):
                        continue

                    bsr = item.get("bsr", 999999)
                    price = item.get("amazon_price", 0)
                    
                    # Aplicar filtros
                    if min_bsr and bsr > min_bsr:
                        log.debug(
                            "keyword_scraper.filter.bsr",
                            asin=item["asin"],
                            bsr=bsr,
                            threshold=min_bsr,
                        )
                        continue

                    if max_price and price > max_price:
                        log.debug(
                            "keyword_scraper.filter.price",
                            asin=item["asin"],
                            price=price,
                            max=max_price,
                        )
                        continue

                    # ── 3. Calcular precio estimado de compra ───────────
                    # Estimación: precio_actual - (precio_actual * margen)
                    # Margen típico: 15-25% del precio de venta
                    margin_pct = 0.20
                    estimated_buy_price = price * (1 - margin_pct)

                    product = ScrapedProduct(
                        asin=item["asin"],
                        title=item["title"],
                        brand=item.get("brand", "Unknown"),
                        current_price=price,
                        estimated_buy_price=estimated_buy_price,
                        bsr_rank=bsr,
                        bsr_category=item.get("category", ""),
                        review_count=item.get("review_count", 0),
                        rating=item.get("rating", 0.0),
                        data_source="keyword_search",
                    )
                    
                    log.debug(
                        "keyword_scraper.found",
                        asin=product.asin,
                        title=product.title[:50],
                        price=product.current_price,
                    )
                    
                    yield product

                except Exception as exc:
                    log.warning(
                        "keyword_scraper.item_error",
                        keyword=keyword,
                        error=str(exc),
                    )
                    continue

            log.info("keyword_scraper.complete", keyword=keyword)

        except KeepaAPIError as exc:
            log.error(
                "keyword_scraper.keepa_error",
                keyword=keyword,
                error=str(exc),
            )
            raise

    async def batch_search(
        self,
        keywords: list[str],
        max_results_per_keyword: int = 30,
    ) -> AsyncIterator[ScrapedProduct]:
        """
        Busca múltiples keywords de forma secuencial.
        
        Args:
            keywords: Lista de términos de búsqueda
            max_results_per_keyword: Resultados por keyword
            
        Yields:
            ScrapedProduct
            
        Nota: Respeta rate limits de Keepa entre búsquedas
        """
        log.info(
            "keyword_scraper.batch_start",
            keyword_count=len(keywords),
        )
        
        for keyword in keywords:
            async for product in self.search_keyword(
                keyword=keyword,
                max_results=max_results_per_keyword,
            ):
                yield product
                
        log.info("keyword_scraper.batch_complete")

    async def export_to_csv(
        self,
        products: list[ScrapedProduct],
        output_path: str | Path = "data/scraped_products.csv",
    ) -> None:
        """
        Exporta productos scrapeados a CSV (formato compatible con pipeline).
        
        Args:
            products: Lista de ScrapedProduct
            output_path: Ruta de salida
            
        CSV generado tiene columnas: ean, buy_price
        (usa EAN = ASIN para mantener compatibilidad)
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["ean", "buy_price", "asin", "title", "source"],
            )
            writer.writeheader()
            
            for product in products:
                writer.writerow({
                    "ean": product.asin,  # Usar ASIN como EAN
                    "buy_price": round(product.estimated_buy_price, 2),
                    "asin": product.asin,
                    "title": product.title,
                    "source": product.data_source,
                })
        
        log.info(
            "keyword_scraper.exported",
            count=len(products),
            path=str(output_path),
        )


# ══════════════════════════════════════════════════════════════════
#  Utilidades de búsqueda comunes
# ══════════════════════════════════════════════════════════════════

# Categorías populares por país
POPULAR_KEYWORDS = {
    "ES": {
        "electronics": [
            "gaming mouse",
            "mechanical keyboard",
            "USB-C cable",
            "portable charger",
            "wireless speaker",
        ],
        "home": [
            "kitchen organizer",
            "bed sheets",
            "bath towel",
            "storage box",
            "desk lamp",
        ],
        "fitness": [
            "yoga mat",
            "resistance bands",
            "dumbbells",
            "exercise bike",
            "jump rope",
        ],
    }
}


async def search_trending_keywords(
    keepa_client: KeepaClient,
    category: str = "electronics",
    marketplace: str = "ES",
) -> list[ScrapedProduct]:
    """
    Busca keywords trending en una categoría.
    
    Args:
        keepa_client: Cliente Keepa
        category: Categoría (electronics, home, fitness)
        marketplace: Marketplace (ES, UK, US, etc.)
        
    Returns:
        Lista de products trending
        
    Ejemplo:
        products = await search_trending_keywords(keepa, "electronics", "ES")
    """
    keywords = POPULAR_KEYWORDS.get(marketplace, {}).get(category, [])
    
    if not keywords:
        log.warning(
            "search_trending.no_keywords",
            category=category,
            marketplace=marketplace,
        )
        return []
    
    scraper = KeywordScraper(keepa_client)
    all_products = []
    
    async for product in scraper.batch_search(
        keywords=keywords,
        max_results_per_keyword=20,
    ):
        all_products.append(product)
    
    return all_products
