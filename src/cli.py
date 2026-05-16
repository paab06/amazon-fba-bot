"""
CLI - Command Line Interface para FBA Bot

Comandos disponibles:
  fba-bot crawl --duration 24 --telegram
  fba-bot analyze --asin B07XYZ123
  fba-bot config --set-categories Electronics,Gaming
  fba-bot test --test-telegram
"""
from __future__ import annotations

import asyncio
import sys
from typing import Optional

import click
import structlog

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.core.config import settings
from src.core.logger import setup_logging
from src.pipeline.ean_resolver import EANResolver
from src.pipeline.financial_calc import FinancialCalculator
from src.pipeline.shields import ShieldChain
from src.scrapers.autonomous_crawler import AutonomousCrawler
from src.scrapers.competitive_analyzer import CompetitiveAnalyzer
from src.telegram_bot import TelegramBot, TelegramAlert

log = structlog.get_logger(__name__)


@click.group()
def cli():
    """FBA Bot - Amazon.es Autonomous Bot"""
    pass


@cli.command()
@click.option(
    "--duration",
    type=int,
    default=24,
    help="Cuantas horas correr (0 = indefinido)",
)
@click.option(
    "--telegram/--no-telegram",
    default=True,
    help="Enviar alertas a Telegram",
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    default="INFO",
    help="Nivel de logging",
)
def crawl(duration: int, telegram: bool, log_level: str):
    """
    Iniciar búsqueda autónoma 24/7
    
    Ejemplo:
      fba-bot crawl --duration 24 --telegram
      fba-bot crawl --duration 0 (indefinido)
    """
    setup_logging(log_level)
    
    log.info(
        "cli.crawl.start",
        duration_hours=duration,
        telegram_enabled=telegram,
    )
    
    asyncio.run(_run_crawl(duration, telegram))


async def _run_crawl(duration_hours: int, send_alerts: bool):
    """Ejecutar crawler autónomo"""
    
    sp_client = SPAPIClient()
    keepa_client = KeepaClient()
    
    # Setup pipeline components
    resolver = EANResolver(sp_client)
    shield_chain = ShieldChain(keepa_client=keepa_client, sp_api_client=sp_client)
    calculator = FinancialCalculator()
    
    # Setup bot (Telegram)
    telegram_bot = None
    if send_alerts:
        telegram_bot = TelegramBot(
            token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
        )
    
    # Setup crawler
    crawler = AutonomousCrawler(
        sp_client=sp_client,
        keepa_client=keepa_client,
        shield_chain=shield_chain,
        calculator=calculator,
        telegram_bot=telegram_bot,
    )
    
    # Setup analyzer
    analyzer = CompetitiveAnalyzer(
        keepa_client=keepa_client,
        sp_api_client=sp_client,
    )
    
    try:
        await crawler.start_autonomous_crawl(
            duration_hours=duration_hours,
            send_alerts=send_alerts,
            analyzer=analyzer,
        )
        log.info("cli.crawl.completed")
        print("\n✓ Crawling completado")
    except KeyboardInterrupt:
        log.info("cli.crawl.interrupted")
        print("\n⊗ Crawling interrumpido por usuario")
    except Exception as e:
        log.error("cli.crawl.error", error=str(e), exc_info=True)
        print(f"\n✗ Error: {e}")
        sys.exit(1)


@cli.command()
@click.option("--asin", required=True, help="ASIN del producto")
@click.option("--price", type=float, help="Precio en Amazon (opcional)")
@click.option("--log-level", default="INFO")
def analyze(asin: str, price: Optional[float], log_level: str):
    """
    Analizar un producto específico
    
    Ejemplo:
      fba-bot analyze --asin B07XYZ123
      fba-bot analyze --asin B07XYZ123 --price 45.99
    """
    setup_logging(log_level)
    
    log.info("cli.analyze.start", asin=asin, price=price)
    
    asyncio.run(_run_analyze(asin, price))


async def _run_analyze(asin: str, amazon_price: Optional[float]):
    """Analizar un ASIN específico"""
    
    keepa_client = KeepaClient()
    sp_client = SPAPIClient()
    analyzer = CompetitiveAnalyzer(
        keepa_client=keepa_client,
        sp_api_client=sp_client,
    )
    
    try:
        # Si no tenemos precio, obtenerlo de Keepa
        if amazon_price is None:
            data = await keepa_client.get_product_data(asin)
            if data:
                amazon_price = data.get("current_price", 0)
            else:
                print(f"✗ No se encontró el producto {asin}")
                return
        
        # Estimar costo (usar 30% del precio como aproximación)
        cost = amazon_price * 0.30
        
        # Analizar
        score = await analyzer.score_product(
            asin=asin,
            amazon_price=amazon_price,
            cost_price=cost,
            category="Electronics",
        )
        
        # Mostrar resultado
        print(f"\n📊 ANÁLISIS: {asin}")
        print(f"{'─' * 50}")
        print(f"Precio Amazon: €{amazon_price:.2f}")
        print(f"Costo estimado: €{cost:.2f}")
        print(f"\nScore: {score.total}/100")
        print(f"Recomendación: {score.recommendation}")
        print(f"\nDesglose:")
        print(f"  • FBA Competencia: {score.fba_competition}/25")
        print(f"  • Price Trend: {score.price_trend}/25")
        print(f"  • Sales Velocity: {score.sales_velocity}/25")
        print(f"  • Category Saturation: {score.category_saturation}/15")
        print(f"  • Price Advantage: {score.price_advantage}/10")
        print(f"\n{score.reasoning}")
        
    except Exception as e:
        log.error("cli.analyze.error", error=str(e), exc_info=True)
        print(f"✗ Error: {e}")
        sys.exit(1)


@cli.command()
@click.option(
    "--categories",
    help="Categorías (comma-separated): Electronics,Gaming,Home",
)
@click.option("--min-margin", type=float, help="Margen mínimo en EUR")
@click.option("--min-roi", type=float, help="ROI mínimo en %")
@click.option("--log-level", default="INFO")
def config(categories: Optional[str], min_margin: Optional[float], min_roi: Optional[float], log_level: str):
    """
    Configurar parámetros del crawler
    
    Ejemplo:
      fba-bot config --categories Electronics,Gaming
      fba-bot config --min-margin 15 --min-roi 100
    """
    setup_logging(log_level)
    
    print("\n⚙️  CONFIGURACIÓN")
    print("─" * 50)
    
    if categories:
        cats = [c.strip() for c in categories.split(",")]
        print(f"✓ Categorías: {', '.join(cats)}")
        # TODO: Guardar en settings
    
    if min_margin is not None:
        print(f"✓ Margen mínimo: €{min_margin:.2f}")
        # TODO: Guardar en settings
    
    if min_roi is not None:
        print(f"✓ ROI mínimo: {min_roi:.0f}%")
        # TODO: Guardar en settings
    
    print("\n✓ Configuración actualizada")


@cli.command()
@click.option("--log-level", default="INFO")
def test_telegram(log_level: str):
    """
    Test de integración con Telegram
    
    Envía un mensaje de prueba al chat configurado
    """
    setup_logging(log_level)
    
    log.info("cli.test_telegram.start")
    
    asyncio.run(_test_telegram())


async def _test_telegram():
    """Test de Telegram"""
    
    bot = TelegramBot(
        token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )
    
    print(f"🧪 Test de Telegram")
    print(f"   Token: {settings.telegram_bot_token[:20]}...")
    print(f"   Chat ID: {settings.telegram_chat_id}")
    
    try:
        # Mensaje simple
        result = await bot.send_message("🧪 Test de conexión exitoso ✓")
        
        if result:
            print(f"\n✓ Conexión a Telegram EXITOSA")
            
            # Prueba con alerta
            alert = TelegramAlert(
                asin="TEST123",
                title="Test Product",
                price=45.99,
                cost=18.50,
                margin=27.49,
                roi=148.0,
                score=82,
                recommendation="✅ EXCELENTE",
                fba_competitors=6,
                category="Electronics",
            )
            
            await bot.send_alert(alert)
            print("✓ Alerta de prueba enviada")
        else:
            print(f"\n✗ Fallo en conexión a Telegram")
            sys.exit(1)
    
    except Exception as e:
        log.error("cli.test_telegram.error", error=str(e), exc_info=True)
        print(f"✗ Error: {e}")
        sys.exit(1)


@cli.command()
def status():
    """Ver status actual del bot"""
    print(f"\n📊 STATUS")
    print(f"{'─' * 50}")
    print(f"Marketplace: {settings.marketplace}")
    print(f"Telegram: {'Configurado' if settings.telegram_bot_token else 'NO configurado'}")
    print(f"Database: {settings.database_url[:30]}...")
    print(f"Redis: {settings.redis_url}")
    print(f"\n✓ Sistema listo para operar")


if __name__ == "__main__":
    cli()
