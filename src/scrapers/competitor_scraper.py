# src/scrapers/competitor_scraper.py
"""
Competitor Scraper — Análisis de Productos de Competidores

Responsabilidades:
  - Obtener ASINs de competidores/sellers
  - Analizar sus productos
  - Identificar oportunidades (gaps en portfolio)
  - Trackear precios competitivos
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional

import structlog

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.core.exceptions import SPAPINotFoundError
from src.scrapers.keyword_scraper import ScrapedProduct

log = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class CompetitorAnalysis:
    """Análisis de producto competidor"""
    asin: str
    competitor_seller: str
    competitor_price: float
    our_price_threshold: float  # Precio máximo que podemos pedir
    price_advantage: float  # Margen disponible
    stock_level: int
    last_restocked: str  # ISO datetime
    velocity: float  # Unidades/día (estimado)


class CompetitorScraper:
    """
    Analiza productos de competidores y vendedores.
    
    Uso:
        scraper = CompetitorScraper(sp_client, keepa_client)
        analysis = await scraper.analyze_competitors("B07XYZ123")
    """

    def __init__(
        self,
        sp_client: SPAPIClient,
        keepa_client: KeepaClient,
    ) -> None:
        """
        Args:
            sp_client: Cliente SP-API
            keepa_client: Cliente Keepa
        """
        self._sp = sp_client
        self._keepa = keepa_client

    async def analyze_competitors(
        self,
        asin: str,
    ) -> Optional[CompetitorAnalysis]:
        """
        Analiza competidores de un ASIN específico.
        
        Args:
            asin: ASIN a analizar
            
        Returns:
            CompetitorAnalysis con datos de competencia
            
        Obtiene:
        - Precios de competidores en Buy Box
        - Histórico de precios (Keepa)
        - Velocidad de venta (estimado)
        - Niveles de stock
        """
        log.info("competitor_scraper.analyze", asin=asin)

        try:
            # ── 1. Obtener datos de vendedores (SP-API) ────────────────
            offers = await self._sp.get_item_offers(asin=asin)
            
            if not offers:
                log.warning("competitor_scraper.no_offers", asin=asin)
                return None

            # ── 2. Análisis de precios ─────────────────────────────────
            buybox_price = offers.get("buybox_price", 0)
            
            # Top 5 competidores
            competitors = offers.get("offers", [])[:5]
            
            if not competitors:
                log.warning("competitor_scraper.no_competitors", asin=asin)
                return None

            # Precio promedio de competidores
            competitor_prices = [
                c.get("price", 0) for c in competitors
                if c.get("seller_name") != "Amazon"
            ]
            
            if competitor_prices:
                avg_competitor_price = sum(competitor_prices) / len(competitor_prices)
            else:
                avg_competitor_price = buybox_price

            # ── 3. Análisis de velocidad (Keepa) ───────────────────────
            keepa_data = await self._keepa.get_product_velocity(asin)
            velocity = keepa_data.get("velocity", 0)
            
            # ── 4. Calcular ventaja de precio ───────────────────────────
            # Nuestro threshold: 5-10% bajo precio promedio
            our_threshold = avg_competitor_price * 0.95
            price_advantage = our_threshold - buybox_price

            analysis = CompetitorAnalysis(
                asin=asin,
                competitor_seller=offers.get("buybox_seller", "Unknown"),
                competitor_price=avg_competitor_price,
                our_price_threshold=our_threshold,
                price_advantage=max(0, price_advantage),
                stock_level=keepa_data.get("stock", 0),
                last_restocked=keepa_data.get("last_restocked", ""),
                velocity=velocity,
            )

            log.info(
                "competitor_scraper.analyzed",
                asin=asin,
                avg_price=avg_competitor_price,
                velocity=velocity,
            )
            
            return analysis

        except SPAPINotFoundError:
            log.warning("competitor_scraper.asin_not_found", asin=asin)
            return None
        except Exception as exc:
            log.error(
                "competitor_scraper.error",
                asin=asin,
                error=str(exc),
            )
            return None

    async def analyze_seller(
        self,
        seller_id: str,
        max_asins: int = 50,
    ) -> AsyncIterator[ScrapedProduct]:
        """
        Analiza los productos de un seller competidor.
        
        Args:
            seller_id: ID del seller en Amazon
            max_asins: Cantidad máxima de ASINs a analizar
            
        Yields:
            ScrapedProduct con datos del seller
            
        Nota: Requiere datos de Keepa de seller profile
        """
        log.info("competitor_scraper.analyze_seller", seller_id=seller_id)

        try:
            # ── Obtener ASINs del seller (via Keepa) ───────────────────
            seller_asins = await self._keepa.get_seller_products(
                seller_id=seller_id,
                limit=max_asins,
            )

            for asin in seller_asins:
                try:
                    # Obtener datos del ASIN
                    offers = await self._sp.get_item_offers(asin=asin)
                    
                    if not offers:
                        continue

                    # Crear producto scrapeado
                    product = ScrapedProduct(
                        asin=asin,
                        title=offers.get("title", "Unknown"),
                        brand=offers.get("brand", "Unknown"),
                        current_price=offers.get("buybox_price", 0),
                        estimated_buy_price=offers.get("buybox_price", 0) * 0.8,
                        bsr_rank=offers.get("bsr", 999999),
                        bsr_category=offers.get("category", ""),
                        review_count=offers.get("review_count", 0),
                        rating=offers.get("rating", 0.0),
                        data_source=f"competitor_seller:{seller_id}",
                    )
                    
                    yield product

                except Exception as exc:
                    log.warning(
                        "competitor_scraper.seller_item_error",
                        seller_id=seller_id,
                        asin=asin,
                        error=str(exc),
                    )
                    continue

        except Exception as exc:
            log.error(
                "competitor_scraper.seller_error",
                seller_id=seller_id,
                error=str(exc),
            )

    async def find_pricing_gaps(
        self,
        category: str,
        marketplace: str = "ES",
    ) -> AsyncIterator[dict]:
        """
        Identifica gaps de precios en una categoría.
        
        Yields:
            {
                "category": "Electronics",
                "price_range": (10, 50),
                "gap_size": 20,  # Brecha identificada
                "avg_bsr": 1500,
                "opportunity_level": "HIGH"  # HIGH, MEDIUM, LOW
            }
        """
        log.info(
            "competitor_scraper.find_gaps",
            category=category,
            marketplace=marketplace,
        )

        try:
            # ── Obtener análisis de categoría de Keepa ─────────────────
            category_data = await self._keepa.get_category_stats(
                category=category,
                marketplace=marketplace,
            )

            if not category_data:
                log.warning("competitor_scraper.no_category_data", category=category)
                return

            # ── Analizar distribución de precios ───────────────────────
            price_distribution = category_data.get("price_distribution", {})
            
            # Identificar gaps
            price_points = sorted(price_distribution.keys())
            
            for i in range(len(price_points) - 1):
                current = float(price_points[i])
                next_point = float(price_points[i + 1])
                gap = next_point - current
                
                # Umbral: gap > 20% indica oportunidad
                if gap > current * 0.20:
                    yield {
                        "category": category,
                        "price_range": (current, next_point),
                        "gap_size": gap,
                        "avg_bsr": category_data.get("avg_bsr", 0),
                        "opportunity_level": "HIGH" if gap > 30 else "MEDIUM",
                    }

        except Exception as exc:
            log.error(
                "competitor_scraper.gap_analysis_error",
                category=category,
                error=str(exc),
            )
