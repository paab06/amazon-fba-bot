# src/scrapers/autonomous_crawler.py
"""
Autonomous Crawler para Amazon.es — Búsqueda 24/7 sin Keywords

Ejecuta continuamente:
1. Bestsellers por categoría
2. New releases
3. Trending products
4. Smart scraping (cambios detectados)

Envía automáticamente al pipeline existente para análisis.
Sin intervención manual requerida.

Uso:
    crawler = AutonomousCrawler(sp_client, keepa_client, pipeline, postgres)
    await crawler.start_autonomous_crawl(duration_hours=24)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional

import structlog

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.core.config import settings
from src.pipeline.ingestor import ProductInput
from src.scrapers.keyword_scraper import ScrapedProduct

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════════
#  Configuración de Categorías para Amazon.es
# ══════════════════════════════════════════════════════════════════

ESPAÑA_CATEGORIES = [
    "Electronics",           # Accesorios tech
    "Home & Garden",         # Organización del hogar
    "Sports & Outdoors",     # Fitness/deportes
    "Gaming",                # Gaming peripherals
    "Toys & Games",          # Juegos (seasonal)
]

ESPAÑA_BESTSELLER_FILTERS = {
    "max_bsr": 50000,                    # Top 5% en categoría
    "price_range": (15, 200),            # €15-200 (rango de margen bueno)
    "min_reviews": 30,                   # Producto establecido
}

ESPAÑA_CRAWLER_PARAMS = {
    "bestseller_interval_hours": 4,      # Actualizar bestsellers cada 4 horas
    "new_releases_interval_hours": 2,    # Nuevos cada 2 horas
    "trending_interval_hours": 6,        # Trending cada 6 horas
}


# ══════════════════════════════════════════════════════════════════
#  Main Crawler
# ══════════════════════════════════════════════════════════════════

class AutonomousCrawler:
    """
    Crawlea Amazon.es automáticamente y envía viables a Telegram
    
    Arquitectura:
    1. Busca productos (Keepa API)
    2. Envía al pipeline existente
    3. Pipeline hace: Escudos + ROI + Competencia
    4. Resultados → Telegram alert
    
    Ventaja: Cero intervención manual después de start()
    """

    def __init__(
        self,
        sp_client: SPAPIClient,
        keepa_client: KeepaClient,
        shield_chain=None,
        calculator=None,
        telegram_bot=None,
    ) -> None:
        self._sp = sp_client
        self._keepa = keepa_client
        self._shield_chain = shield_chain
        self._calculator = calculator
        self._telegram = telegram_bot
        
        # Histórico de últimas búsquedas (evitar duplicados)
        self._seen_asins: set[str] = set()
        self._last_crawl_timestamp: dict[str, datetime] = {}
        
        # Stats
        self.total_analyzed = 0
        self.total_viable = 0
        self.total_alerts_sent = 0

    async def start_autonomous_crawl(
        self,
        duration_hours: int = 24,
        send_alerts: bool = True,
        analyzer=None,
    ) -> None:
        """
        Inicia crawling automático con error recovery
        
        Args:
            duration_hours: Cuantas horas correr (0 = indefinido)
            send_alerts: Enviar a Telegram viables encontrados
            analyzer: CompetitiveAnalyzer para scoring
        """
        self.analyzer = analyzer
        
        log.info(
            "crawler.autonomous.start",
            duration=duration_hours,
            categories=len(ESPAÑA_CATEGORIES),
            send_alerts=send_alerts,
        )

        # Crear tareas paralelas
        tasks = [
            self._retry_loop(self.crawl_bestsellers_loop, send_alerts),
            self._retry_loop(self.crawl_new_releases_loop, send_alerts),
            self._retry_loop(self.crawl_trending_loop, send_alerts),
        ]

        try:
            if duration_hours > 0:
                # Ejecutar por N horas
                await asyncio.wait_for(
                    asyncio.gather(*tasks),
                    timeout=duration_hours * 3600,
                )
            else:
                # Indefinido
                await asyncio.gather(*tasks)

        except asyncio.TimeoutError:
            log.info(
                "crawler.autonomous.timeout",
                hours=duration_hours,
                total_asins=len(self._seen_asins),
                viable_found=self.total_viable,
                alerts_sent=self.total_alerts_sent,
            )
        except asyncio.CancelledError:
            log.info("crawler.autonomous.cancelled")
            raise
    
    async def _retry_loop(self, coro_func, *args, max_retries: int = 3):
        """
        Ejecuta una corrutina con reintentos automáticos
        
        Si falla: espera 5min y reintenta (hasta 3 veces)
        """
        retry_count = 0
        
        while True:
            try:
                await coro_func(*args)
            except Exception as exc:
                retry_count += 1
                if retry_count > max_retries:
                    log.error("crawler.retry.max_exceeded", error=str(exc))
                    # Esperar 30min antes de reintentar
                    await asyncio.sleep(1800)
                    retry_count = 0
                else:
                    wait_time = 5 * 60 * retry_count  # 5min, 10min, 15min
                    log.warning(
                        "crawler.retry",
                        retry=retry_count,
                        wait_seconds=wait_time,
                        error=str(exc),
                    )
                    await asyncio.sleep(wait_time)

    async def crawl_bestsellers_loop(self, send_alerts: bool = True) -> None:
        """
        Crawlea bestsellers de cada categoría rotatoriamente
        
        Intervalo: Cada 4 horas (parametrizable)
        """
        interval = ESPAÑA_CRAWLER_PARAMS["bestseller_interval_hours"]

        while True:
            for category in ESPAÑA_CATEGORIES:
                try:
                    await self._crawl_category(
                        category=category,
                        crawl_type="bestsellers",
                        send_alerts=send_alerts,
                    )
                except Exception as exc:
                    log.warning(
                        "crawler.category.error",
                        category=category,
                        error=str(exc),
                    )

            log.info(
                "crawler.bestsellers.round_complete",
                interval_hours=interval,
            )
            await asyncio.sleep(interval * 3600)

    async def crawl_new_releases_loop(self, send_alerts: bool = True) -> None:
        """
        Crawlea nuevos releases (últimos 7 días)
        
        Intervalo: Cada 2 horas
        """
        interval = ESPAÑA_CRAWLER_PARAMS["new_releases_interval_hours"]

        while True:
            for category in ESPAÑA_CATEGORIES:
                try:
                    await self._crawl_category(
                        category=category,
                        crawl_type="new_releases",
                        send_alerts=send_alerts,
                    )
                except Exception as exc:
                    log.warning(
                        "crawler.new_releases.error",
                        category=category,
                        error=str(exc),
                    )

            log.info("crawler.new_releases.round_complete")
            await asyncio.sleep(interval * 3600)

    async def crawl_trending_loop(self, send_alerts: bool = True) -> None:
        """
        Crawlea trending/rising stars
        
        Intervalo: Cada 6 horas
        """
        interval = ESPAÑA_CRAWLER_PARAMS["trending_interval_hours"]

        while True:
            for category in ESPAÑA_CATEGORIES:
                try:
                    # Productos que subieron en BSR (ganando tracción)
                    products = await self._get_trending_products(category)
                    
                    for product in products:
                        await self._process_product(
                            product,
                            crawl_type="trending",
                            send_alerts=send_alerts,
                        )

                except Exception as exc:
                    log.warning(
                        "crawler.trending.error",
                        category=category,
                        error=str(exc),
                    )

            log.info("crawler.trending.round_complete")
            await asyncio.sleep(interval * 3600)

    async def _crawl_category(
        self,
        category: str,
        crawl_type: str,
        send_alerts: bool = True,
    ) -> None:
        """
        Crawlea una categoría específica
        
        Args:
            category: Nombre de categoría
            crawl_type: "bestsellers", "new_releases", "trending"
            send_alerts: Enviar a Telegram
        """
        log.info(
            f"crawler.{crawl_type}.start",
            category=category,
        )

        products = []

        if crawl_type == "bestsellers":
            products = await self._get_bestsellers(category)
        elif crawl_type == "new_releases":
            products = await self._get_new_releases(category)

        log.info(
            f"crawler.{crawl_type}.found",
            category=category,
            count=len(products),
        )

        for product in products:
            await self._process_product(
                product,
                crawl_type=crawl_type,
                send_alerts=send_alerts,
            )

            # Rate limiting (respetar Keepa limits)
            await asyncio.sleep(1)

    async def _get_bestsellers(self, category: str) -> list[dict]:
        """
        Obtiene bestsellers de Keepa con filtros
        
        Retorna: Lista de productos con ASIN, precio, etc.
        """
        try:
            # Keepa API: get_bestsellers (depends on your implementation)
            products = await self._keepa.get_bestsellers(
                category=category,
                max_bsr=ESPAÑA_BESTSELLER_FILTERS["max_bsr"],
                limit=100,
            )

            # Aplicar filtros adicionales
            filtered = [
                p
                for p in products
                if self._meets_filters(p, category)
            ]

            return filtered

        except Exception as exc:
            log.error("crawler.bestsellers.error", category=category, error=str(exc))
            return []

    async def _get_new_releases(self, category: str) -> list[dict]:
        """
        Obtiene nuevos releases (últimos 7 días)
        """
        try:
            # Implementar según Keepa API disponible
            products = await self._keepa.get_new_releases(
                category=category,
                days=7,
                limit=50,
            )

            filtered = [
                p for p in products
                if self._meets_filters(p, category)
            ]

            return filtered

        except Exception as exc:
            log.error("crawler.new_releases.error", category=category, error=str(exc))
            return []

    async def _get_trending_products(self, category: str) -> list[dict]:
        """
        Obtiene productos con mejora de BSR (trending)
        """
        try:
            # Productos que mejoraron BSR en últimos 7 días
            products = await self._keepa.get_trending_products(
                category=category,
                days=7,
                limit=50,
            )

            filtered = [
                p for p in products
                if self._meets_filters(p, category)
            ]

            return filtered

        except Exception as exc:
            log.error("crawler.trending.error", category=category, error=str(exc))
            return []

    async def _process_product(
        self,
        product: dict,
        crawl_type: str,
        send_alerts: bool = True,
    ) -> None:
        """
        Procesa 1 producto: Escudos → ROI → Competencia → Alert
        
        Pipeline:
        1. Validar básico (precio, reviews, etc)
        2. Pasar por escudos
        3. Calcular ROI
        4. Analizar competencia (score)
        5. Enviar alert a Telegram si viable
        """
        asin = product.get("asin")

        # Evitar procesar duplicados
        if asin in self._seen_asins:
            return

        self._seen_asins.add(asin)
        self.total_analyzed += 1

        price = product.get("current_price", 0)
        
        log.info(
            "crawler.process_product",
            asin=asin,
            crawl_type=crawl_type,
            price=price,
        )

        try:
            # PASO 1: Pasar por Escudos
            if not self._shield_chain:
                log.warning("crawler.no_shield_chain")
                return
            
            from src.pipeline.ingestor import ResolvedProduct
            
            resolved = ResolvedProduct(
                asin=asin,
                ean=None,
                title=product.get("title", "Unknown"),
                brand=product.get("brand", "Unknown"),
                price_amazon=price,
            )
            
            shield_result = await self._shield_chain.run(resolved)
            if not shield_result.passed:
                log.info(
                    "crawler.shield_drop",
                    asin=asin,
                    shield=shield_result.drop_shield,
                    reason=shield_result.drop_reason,
                )
                return
            
            # PASO 2: Calcular ROI
            if not self._calculator:
                log.warning("crawler.no_calculator")
                return
            
            financial = await self._calculator.evaluate(shield_result.product)
            
            if not financial or financial.get("type") == "shield_drop":
                log.info("crawler.financial_drop", asin=asin)
                return
            
            margin = financial.get("net_profit", 0)
            roi = financial.get("roi_pct", 0)
            
            # PASO 3: Analizar Competencia (Score)
            score_data = None
            if self.analyzer:
                try:
                    score_data = await self.analyzer.score_product(
                        asin=asin,
                        amazon_price=price,
                        cost_price=financial.get("buy_price", 0),
                        category=product.get("category", "Electronics"),
                    )
                except Exception as e:
                    log.warning("crawler.analyzer.error", error=str(e))
            
            self.total_viable += 1
            
            # PASO 4: Enviar Alert si viable
            if send_alerts and self._telegram:
                await self._send_viable_alert(
                    product=product,
                    financial=financial,
                    score_data=score_data,
                    crawl_type=crawl_type,
                )
                self.total_alerts_sent += 1

        except Exception as exc:
            log.error(
                "crawler.process_product.error",
                asin=asin,
                error=str(exc),
                exc_info=True,
            )
    
    async def _send_viable_alert(
        self,
        product: dict,
        financial: dict,
        score_data=None,
        crawl_type: str = "unknown",
    ) -> None:
        """
        Envía alert a Telegram con detalles completos
        """
        try:
            from src.telegram_bot import TelegramAlert
            
            asin = product.get("asin")
            title = product.get("title", "Unknown")[:60]
            price = product.get("current_price", 0)
            cost = financial.get("buy_price", 0)
            margin = financial.get("net_profit", 0)
            roi = financial.get("roi_pct", 0)
            
            score = score_data.total if score_data else 60
            recommendation = score_data.recommendation if score_data else "⚠️ REVISAR"
            
            alert = TelegramAlert(
                asin=asin,
                title=title,
                price=price,
                cost=cost,
                margin=margin,
                roi=roi,
                score=score,
                recommendation=recommendation,
                fba_competitors=score_data.fba_competition if score_data else 0,
                category=product.get("category", "Electronics"),
            )
            
            await self._telegram.send_alert(alert)
            
            log.info(
                "crawler.alert_sent",
                asin=asin,
                score=score,
                margin=margin,
            )

        except Exception as exc:
            log.error("crawler.telegram.error", error=str(exc))

    def _meets_filters(self, product: dict, category: str) -> bool:
        """
        Aplica filtros de España
        
        Retorna: True si pasa todos los filtros
        """
        price = product.get("current_price", 0)
        bsr = product.get("bsr", 999999)
        reviews = product.get("review_count", 0)

        # Filtro 1: Rango de precio
        price_min, price_max = ESPAÑA_BESTSELLER_FILTERS["price_range"]
        if not (price_min <= price <= price_max):
            return False

        # Filtro 2: BSR máximo
        if bsr > ESPAÑA_BESTSELLER_FILTERS["max_bsr"]:
            return False

        # Filtro 3: Reviews mínimas
        if reviews < ESPAÑA_BESTSELLER_FILTERS["min_reviews"]:
            return False

        return True


# ══════════════════════════════════════════════════════════════════
#  Helper Functions
# ══════════════════════════════════════════════════════════════════

async def quick_crawl_category(
    keepa_client: KeepaClient,
    category: str,
    limit: int = 50,
) -> AsyncIterator[dict]:
    """
    Crawl rápido de una categoría
    
    Uso:
        async for product in quick_crawl_category(keepa, "Electronics"):
            print(product)
    """
    products = await keepa_client.get_bestsellers(
        category=category,
        max_bsr=50000,
        limit=limit,
    )

    for product in products:
        yield product
