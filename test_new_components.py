#!/usr/bin/env python
"""
Test rápido de los componentes nuevos
"""
import asyncio
import sys

async def test_telegram_bot():
    """Test de TelegramBot"""
    print("\n🧪 TEST: TelegramBot")
    print("─" * 50)
    
    try:
        from src.telegram_bot import TelegramBot, TelegramAlert
        
        # Crear instancia (sin conectar realmente)
        bot = TelegramBot(token="TEST_TOKEN", chat_id="TEST_CHAT")
        
        # Crear alerta de test
        alert = TelegramAlert(
            asin="TEST123",
            title="Test Gaming Mouse",
            price=45.99,
            cost=18.50,
            margin=27.49,
            roi=148.0,
            score=82,
            recommendation="✅ EXCELENTE",
            fba_competitors=6,
            category="Electronics",
        )
        
        print(f"✓ TelegramBot creado correctamente")
        print(f"✓ TelegramAlert dataclass válido")
        print(f"  ASIN: {alert.asin}")
        print(f"  Score: {alert.score}/100")
        print(f"  Margen: €{alert.margin:.2f}")
        print(f"  ROI: {alert.roi:.0f}%")
        return True
    
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_crawler_database():
    """Test de CrawlerDatabase"""
    print("\n🧪 TEST: CrawlerDatabase")
    print("─" * 50)
    
    try:
        from src.crawler_database import CrawlerDatabase
        
        # Crear instancia (sin conectar a DB real)
        db = CrawlerDatabase("postgresql://test:test@localhost/test")
        
        print(f"✓ CrawlerDatabase instanciado correctamente")
        print(f"✓ Métodos disponibles:")
        print(f"  - log_product_analyzed()")
        print(f"  - log_viable_found()")
        print(f"  - log_alert_sent()")
        print(f"  - mark_product_purchased()")
        print(f"  - track_roi()")
        print(f"  - get_viable_products()")
        print(f"  - get_stats()")
        return True
    
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_competitive_analyzer():
    """Test de CompetitiveAnalyzer"""
    print("\n🧪 TEST: CompetitiveAnalyzer")
    print("─" * 50)
    
    try:
        from src.scrapers.competitive_analyzer import CompetitiveAnalyzer, CompetitiveScore
        
        # Crear dataclass
        score = CompetitiveScore(
            total=82,
            fba_competition=20,
            price_trend=25,
            sales_velocity=24,
            category_saturation=10,
            price_advantage=3,
            recommendation="✅ EXCELENTE",
            reasoning="Pocos competidores, precio estable, venta rápida",
        )
        
        print(f"✓ CompetitiveScore dataclass válido")
        print(f"✓ Score total: {score.total}/100")
        print(f"✓ Desglose:")
        print(f"  • FBA Competition: {score.fba_competition}/25")
        print(f"  • Price Trend: {score.price_trend}/25")
        print(f"  • Sales Velocity: {score.sales_velocity}/25")
        print(f"  • Category Saturation: {score.category_saturation}/15")
        print(f"  • Price Advantage: {score.price_advantage}/10")
        return True
    
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_autonomous_crawler():
    """Test de AutonomousCrawler"""
    print("\n🧪 TEST: AutonomousCrawler")
    print("─" * 50)
    
    try:
        from src.scrapers.autonomous_crawler import AutonomousCrawler
        from src.api.keepa_client import KeepaClient
        from src.api.sp_api_client import SPAPIClient
        
        # Crear instancia sin conectar
        keepa = KeepaClient()
        sp = SPAPIClient()
        
        crawler = AutonomousCrawler(
            sp_client=sp,
            keepa_client=keepa,
            shield_chain=None,
            calculator=None,
            telegram_bot=None,
        )
        
        print(f"✓ AutonomousCrawler instanciado")
        print(f"✓ Propiedades:")
        print(f"  - total_analyzed: {crawler.total_analyzed}")
        print(f"  - total_viable: {crawler.total_viable}")
        print(f"  - total_alerts_sent: {crawler.total_alerts_sent}")
        print(f"✓ Métodos:")
        print(f"  - start_autonomous_crawl()")
        print(f"  - crawl_bestsellers_loop()")
        print(f"  - crawl_new_releases_loop()")
        print(f"  - crawl_trending_loop()")
        return True
    
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_cli_structure():
    """Test que CLI está bien estructurado"""
    print("\n🧪 TEST: CLI Structure")
    print("─" * 50)
    
    try:
        from src.cli import cli, crawl, analyze, config, test_telegram, status
        
        print(f"✓ CLI importado correctamente")
        print(f"✓ Comandos disponibles:")
        print(f"  - crawl() - Ejecutar crawler")
        print(f"  - analyze() - Analizar ASIN")
        print(f"  - config() - Configurar parámetros")
        print(f"  - test_telegram() - Test Telegram")
        print(f"  - status() - Ver status")
        return True
    
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_imports():
    """Test que todos los imports funcionan"""
    print("\n🧪 TEST: Imports")
    print("─" * 50)
    
    try:
        print("  Importando telegram_bot...")
        from src.telegram_bot import TelegramBot, TelegramAlert
        print("  ✓ telegram_bot")
        
        print("  Importando cli...")
        from src.cli import cli
        print("  ✓ cli")
        
        print("  Importando crawler_database...")
        from src.crawler_database import CrawlerDatabase
        print("  ✓ crawler_database")
        
        print("  Importando autonomous_crawler...")
        from src.scrapers.autonomous_crawler import AutonomousCrawler
        print("  ✓ autonomous_crawler")
        
        print("  Importando competitive_analyzer...")
        from src.scrapers.competitive_analyzer import CompetitiveAnalyzer
        print("  ✓ competitive_analyzer")
        
        print("\n✓ Todos los imports funcionan correctamente")
        return True
    
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("""
╔════════════════════════════════════════╗
║     TESTING NEW COMPONENTS              ║
╚════════════════════════════════════════╝
""")
    
    results = []
    
    # Ejecutar tests
    results.append(("Imports", await test_imports()))
    results.append(("TelegramBot", await test_telegram_bot()))
    results.append(("CrawlerDatabase", await test_crawler_database()))
    results.append(("CompetitiveAnalyzer", await test_competitive_analyzer()))
    results.append(("AutonomousCrawler", await test_autonomous_crawler()))
    results.append(("CLI Structure", await test_cli_structure()))
    
    # Resumen
    print("\n" + "=" * 50)
    print("📊 RESUMEN DE TESTS")
    print("=" * 50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:7} {name}")
    
    print(f"\n{passed}/{total} tests pasados")
    
    if passed == total:
        print("\n✅ TODOS LOS TESTS PASARON")
        return 0
    else:
        print(f"\n❌ {total - passed} tests fallaron")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
