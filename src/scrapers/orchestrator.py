# src/scrapers/orchestrator.py
"""
Scraper Orchestrator — Orquesta todos los scrapers

Responsabilidades:
  - Integrar scrapers con pipeline principal
  - Generar CSVs desde diferentes fuentes
  - Coordinar búsquedas (keywords, competidores)
  - Ejecutar monitoreo continuo
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import structlog

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.core.config import settings
from src.scrapers.competitor_scraper import CompetitorScraper
from src.scrapers.keyword_scraper import KeywordScraper, ScrapedProduct
from src.scrapers.price_monitor import PriceMonitor

log = structlog.get_logger(__name__)


class ScraperOrchestrator:
    """
    Coordina todos los scrapers y genera CSVs para el pipeline.
    
    Flujo:
    1. Buscar por keywords → [Productos]
    2. Analizar competencia → [Más Productos]
    3. Monitorear watchlist → [Alertas]
    4. Generar CSV → Pasar a pipeline principal
    
    Uso:
        orchestrator = ScraperOrchestrator(sp_client, keepa_client, redis)
        csv_path = await orchestrator.scrape_and_generate_csv(
            keywords=["gaming mouse", "keyboard"],
            output_path="data/discovered.csv"
        )
        # Luego:
        # fba-bot data/discovered.csv
    """

    def __init__(
        self,
        sp_client: SPAPIClient,
        keepa_client: KeepaClient,
        redis,
    ) -> None:
        """
        Args:
            sp_client: Cliente SP-API
            keepa_client: Cliente Keepa
            redis: Cliente Redis
        """
        self._sp = sp_client
        self._keepa = keepa_client
        self._redis = redis
        
        self.keyword_scraper = KeywordScraper(keepa_client)
        self.competitor_scraper = CompetitorScraper(sp_client, keepa_client)
        self.price_monitor = PriceMonitor(sp_client, keepa_client, redis)

    async def scrape_keywords(
        self,
        keywords: list[str],
        max_results_per_keyword: int = 30,
    ) -> AsyncIterator[ScrapedProduct]:
        """
        Busca keywords y emite productos.
        
        Args:
            keywords: Lista de términos de búsqueda
            max_results_per_keyword: Resultados por keyword
            
        Yields:
            ScrapedProduct
        """
        log.info(
            "scraper_orchestrator.search_keywords",
            count=len(keywords),
        )

        async for product in self.keyword_scraper.batch_search(
            keywords=keywords,
            max_results_per_keyword=max_results_per_keyword,
        ):
            yield product

    async def scrape_and_generate_csv(
        self,
        keywords: list[str] | None = None,
        competitor_asins: list[str] | None = None,
        output_path: str | Path = "data/discovered_products.csv",
        max_results: int = 200,
    ) -> Path:
        """
        Ejecuta scraping completo y genera CSV.
        
        Args:
            keywords: Keywords a buscar
            competitor_asins: ASINs de competencia a analizar
            output_path: Ruta de salida del CSV
            max_results: Máximo total de productos
            
        Returns:
            Path del CSV generado
            
        Ejemplo:
            csv_path = await orchestrator.scrape_and_generate_csv(
                keywords=["gaming mouse", "keyboard", "headphone"],
                competitor_asins=["B07XYZ123"],
            )
            # csv_path = Path("data/discovered_products.csv")
        """
        log.info(
            "scraper_orchestrator.generate_csv",
            keywords=keywords or [],
            competitors=len(competitor_asins or []),
            output=str(output_path),
        )

        products = []

        # ── 1. Buscar por keywords ─────────────────────────────────────
        if keywords:
            async for product in self.scrape_keywords(
                keywords=keywords,
                max_results_per_keyword=30,
            ):
                products.append(product)
                
                if len(products) >= max_results:
                    log.info("scraper_orchestrator.reached_max_results")
                    break

        # ── 2. Analizar competencia ────────────────────────────────────
        if competitor_asins and len(products) < max_results:
            for asin in competitor_asins:
                try:
                    async for product in self.competitor_scraper.analyze_seller(
                        seller_id=asin,
                        max_asins=20,
                    ):
                        products.append(product)
                        
                        if len(products) >= max_results:
                            log.info("scraper_orchestrator.reached_max_results")
                            break

                except Exception as exc:
                    log.warning(
                        "scraper_orchestrator.competitor_error",
                        asin=asin,
                        error=str(exc),
                    )

        # ── 3. Exportar CSV ────────────────────────────────────────────
        if products:
            await self.keyword_scraper.export_to_csv(
                products=products,
                output_path=output_path,
            )
            
            log.info(
                "scraper_orchestrator.csv_generated",
                count=len(products),
                path=str(output_path),
            )
        else:
            log.warning("scraper_orchestrator.no_products_found")

        return Path(output_path)

    async def start_monitoring(
        self,
        watchlist_asins: list[str],
        check_interval_minutes: int = 60,
    ) -> None:
        """
        Inicia monitoreo continuo de una watchlist.
        
        Args:
            watchlist_asins: ASINs a monitorear
            check_interval_minutes: Intervalo entre chequeos (default: 1 hora)
            
        Nota: Esta función corre indefinidamente.
        Para detener, usar task.cancel()
        
        Ejemplo:
            task = asyncio.create_task(
                orchestrator.start_monitoring(
                    watchlist_asins=["B07XYZ123", "B08ABC456"],
                    check_interval_minutes=30
                )
            )
            # ... más tarde ...
            task.cancel()
        """
        log.info(
            "scraper_orchestrator.start_monitoring",
            count=len(watchlist_asins),
            interval_minutes=check_interval_minutes,
        )

        # Agregar a watchlist
        await self.price_monitor.add_to_watchlist(watchlist_asins)

        try:
            while True:
                # Chequear watchlist
                alerts = await self.price_monitor.check_watchlist()
                
                if alerts:
                    log.info(
                        "scraper_orchestrator.alerts_generated",
                        count=len(alerts),
                    )
                    
                    for alert in alerts:
                        log.warning(
                            "scraper_orchestrator.price_alert",
                            asin=alert.asin,
                            type=alert.alert_type,
                            action=alert.action_suggested,
                            change_pct=alert.change_pct,
                        )

                # Esperar siguiente chequeo
                await asyncio.sleep(check_interval_minutes * 60)

        except asyncio.CancelledError:
            log.info("scraper_orchestrator.monitoring_stopped")
            raise

    async def get_recommendations(
        self,
        strategy: str = "balanced",  # balanced, aggressive, conservative
    ) -> list[dict]:
        """
        Obtiene recomendaciones basadas en monitoring.
        
        Args:
            strategy: Estrategia de recomendación
                - balanced: ROI 25-40%
                - aggressive: ROI 15-25% (riesgo mayor)
                - conservative: ROI 40%+ (muy seguro)
        
        Returns:
            Lista de recomendaciones con action items
            
        Ejemplo:
            recs = await orchestrator.get_recommendations()
            for rec in recs:
                print(f"BUY: {rec['asin']} - {rec['reason']}")
        """
        log.info("scraper_orchestrator.get_recommendations", strategy=strategy)

        alerts = await self.price_monitor.get_pending_alerts()
        recommendations = []

        for alert in alerts:
            if alert.action_suggested in ["BUY_NOW", "BUY_OPPORTUNITY"]:
                recommendations.append({
                    "action": "BUY",
                    "asin": alert.asin,
                    "reason": f"{alert.alert_type}: {alert.change_pct:.1f}%",
                    "urgency": "HIGH" if "NOW" in alert.action_suggested else "MEDIUM",
                    "price_change": alert.change_pct,
                })
            elif alert.action_suggested == "WAIT":
                recommendations.append({
                    "action": "WAIT",
                    "asin": alert.asin,
                    "reason": f"{alert.alert_type}: Esperar caída futura",
                    "urgency": "LOW",
                })

        log.info(
            "scraper_orchestrator.recommendations_ready",
            count=len(recommendations),
        )

        return recommendations


# ══════════════════════════════════════════════════════════════════
#  Funciones helper para uso rápido
# ══════════════════════════════════════════════════════════════════

async def quick_search(
    sp_client: SPAPIClient,
    keepa_client: KeepaClient,
    keywords: list[str],
) -> Path:
    """
    Helper: Búsqueda rápida por keywords y genera CSV.
    
    Uso:
        csv_path = await quick_search(
            sp_client, keepa_client,
            keywords=["gaming mouse", "keyboard"]
        )
    """
    orchestrator = ScraperOrchestrator(sp_client, keepa_client, None)
    
    return await orchestrator.scrape_and_generate_csv(
        keywords=keywords,
        output_path="data/quick_search_results.csv",
    )
