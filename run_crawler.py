#!/usr/bin/env python
"""
Script simple para correr el crawler autónomo

Uso:
  python run_crawler.py           # 24 horas con Telegram
  python run_crawler.py 0         # Indefinido
  python run_crawler.py 48        # 48 horas
"""

import asyncio
import sys

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.core.logger import setup_logging
from src.pipeline.ean_resolver import EANResolver
from src.pipeline.exporter import Exporter
from src.pipeline.financial_calc import FinancialCalculator
from src.pipeline.shields import ShieldChain
from src.scrapers.autonomous_crawler import AutonomousCrawler
from src.scrapers.competitive_analyzer import CompetitiveAnalyzer
from src.telegram_bot import TelegramBot
from src.core.config import settings


async def main():
    setup_logging("INFO")
    
    # Parámetros
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    send_alerts = True
    
    print(f"""
╔════════════════════════════════════════╗
║  FBA Bot - Autonomous Crawler (España) ║
╚════════════════════════════════════════╝

⚙️  CONFIGURACIÓN:
   Duración: {duration} horas {'(Indefinido)' if duration == 0 else ''}
   Telegram: {'Activado' if send_alerts else 'Desactivado'}
   
""")
    
    # Setup
    sp_client = SPAPIClient()
    keepa_client = KeepaClient()
    
    # Pipeline
    shield_chain = ShieldChain(keepa_client=keepa_client, sp_api_client=sp_client)
    calculator = FinancialCalculator()
    exporter = Exporter()
    
    # Telegram
    telegram_bot = None
    if send_alerts:
        try:
            telegram_bot = TelegramBot(
                token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
            )
            print("✓ Telegram conectado\n")
        except Exception as e:
            print(f"⚠️  Telegram no disponible: {e}\n")
            send_alerts = False
    
    # Crawler
    crawler = AutonomousCrawler(
        sp_client=sp_client,
        keepa_client=keepa_client,
        shield_chain=shield_chain,
        calculator=calculator,
        telegram_bot=telegram_bot,
    )
    
    # Analyzer
    analyzer = CompetitiveAnalyzer(
        keepa_client=keepa_client,
        sp_api_client=sp_client,
    )
    
    print("🚀 INICIANDO CRAWLER...\n")
    
    try:
        await crawler.start_autonomous_crawl(
            duration_hours=duration,
            send_alerts=send_alerts,
            analyzer=analyzer,
        )
        
        print(f"""

✓ RESUMEN FINAL:
   Productos analizados: {crawler.total_analyzed}
   Viables encontrados: {crawler.total_viable}
   Alertas enviadas: {crawler.total_alerts_sent}
""")
        
    except KeyboardInterrupt:
        print(f"""

⊗ INTERRUMPIDO POR USUARIO

Resumen:
   Productos analizados: {crawler.total_analyzed}
   Viables encontrados: {crawler.total_viable}
   Alertas enviadas: {crawler.total_alerts_sent}
""")
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        raise
    finally:
        await exporter.teardown()


if __name__ == "__main__":
    asyncio.run(main())
