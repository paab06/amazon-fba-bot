# src/scrapers/__init__.py
"""
Scrapers Module — Descubrimiento automático de productos

Proporciona:
  - KeywordScraper: Búsqueda por keywords
  - CompetitorScraper: Análisis de competencia
  - PriceMonitor: Monitoreo continuo
  - ScraperOrchestrator: Coordinación completa
  - AutonomousCrawler: Búsqueda 24/7 en Amazon.es
  - CompetitiveAnalyzer: Análisis profundo de viabilidad
"""

from src.scrapers.autonomous_crawler import AutonomousCrawler
from src.scrapers.competitor_scraper import CompetitorScraper, CompetitorAnalysis
from src.scrapers.competitive_analyzer import CompetitiveAnalyzer, CompetitiveScore
from src.scrapers.keyword_scraper import KeywordScraper, ScrapedProduct
from src.scrapers.orchestrator import ScraperOrchestrator
from src.scrapers.price_monitor import PriceMonitor, PriceAlert, PriceSnapshot

__all__ = [
    "KeywordScraper",
    "ScrapedProduct",
    "CompetitorScraper",
    "CompetitorAnalysis",
    "PriceMonitor",
    "PriceAlert",
    "PriceSnapshot",
    "ScraperOrchestrator",
    "AutonomousCrawler",
    "CompetitiveAnalyzer",
    "CompetitiveScore",
]
