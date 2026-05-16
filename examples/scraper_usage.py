# examples/scraper_usage.py
"""
Ejemplos Prácticos de Uso de los Scrapers

Copiar y adaptar estos scripts para usar los nuevos scrapers.
"""

import asyncio
from pathlib import Path

from src.main import (
    run_scraper_by_keywords,
    run_scraper_analyze_competitors,
    run_full_discovery,
    run_monitoring,
    run_pipeline,
)


# ═══════════════════════════════════════════════════════════════════
#  EJEMPLO 1: Búsqueda Simple por Keywords
# ═══════════════════════════════════════════════════════════════════

async def example_1_keyword_search():
    """
    Búsqueda simple: Gaming products
    
    Usa:
        python -c "import asyncio; from examples.scraper_usage import example_1_keyword_search; asyncio.run(example_1_keyword_search())"
    """
    print("=" * 70)
    print("EJEMPLO 1: Búsqueda Simple por Keywords")
    print("=" * 70)
    
    keywords = [
        "gaming mouse",
        "mechanical keyboard",
        "wireless headset",
    ]
    
    print(f"\n🔍 Buscando {len(keywords)} keywords...")
    
    csv = await run_scraper_by_keywords(
        keywords=keywords,
        output_csv="data/gaming_products.csv",
        max_results=100
    )
    
    print(f"✓ CSV generado: {csv}")
    
    print("\n📊 Analizando productos...")
    stats = await run_pipeline(csv)
    
    print(f"\n📈 RESULTADOS:")
    print(f"  Total procesados: {stats['total']}")
    print(f"  ✓ Viables: {stats['pass']}")
    print(f"  ✗ Descartados: {stats['drop']}")
    print(f"  ⚠️  Errores: {stats['errors']}")


# ═══════════════════════════════════════════════════════════════════
#  EJEMPLO 2: Análisis de Competencia
# ═══════════════════════════════════════════════════════════════════

async def example_2_competitor_analysis():
    """
    Analiza productos de competidores conocidos.
    
    Nota: Reemplaza los seller IDs con sellers reales.
    """
    print("=" * 70)
    print("EJEMPLO 2: Análisis de Competencia")
    print("=" * 70)
    
    # IMPORTANTE: Reemplaza estos con seller IDs reales
    competitor_sellers = [
        "AXXXXXXXXXXXXXXXX",  # Seller 1
        "BXXXXXXXXXXXXXXXX",  # Seller 2
    ]
    
    print(f"\n🕵️ Analizando {len(competitor_sellers)} competidores...")
    
    csv = await run_scraper_analyze_competitors(
        competitor_seller_ids=competitor_sellers,
        output_csv="data/competitor_analysis.csv"
    )
    
    print(f"✓ CSV generado: {csv}")
    
    print("\n📊 Analizando productos...")
    stats = await run_pipeline(csv)
    
    print(f"\n📈 RESULTADOS:")
    print(f"  Total procesados: {stats['total']}")
    print(f"  ✓ Viables: {stats['pass']}")


# ═══════════════════════════════════════════════════════════════════
#  EJEMPLO 3: Discovery Completo (Keywords + Competencia)
# ═══════════════════════════════════════════════════════════════════

async def example_3_full_discovery():
    """
    Discovery total: búsqueda de keywords + análisis de competencia.
    
    Esto es más potente que ejemplo 1 o 2 solos.
    """
    print("=" * 70)
    print("EJEMPLO 3: Discovery Completo")
    print("=" * 70)
    
    keywords = [
        "usb-c cable",
        "wireless charger",
        "power bank 20000mah",
        "portable phone stand",
    ]
    
    competitor_ids = [
        "AXXXXXXXXXXXXXXXX",
        "BXXXXXXXXXXXXXXXX",
    ]
    
    print(f"\n🔍 Ejecutando discovery completo:")
    print(f"   • {len(keywords)} keywords")
    print(f"   • {len(competitor_ids)} competidores")
    
    csv = await run_full_discovery(
        keywords=keywords,
        competitor_ids=competitor_ids,
        output_csv="data/full_discovery.csv"
    )
    
    print(f"✓ CSV generado: {csv}")
    print(f"⏳ Este proceso puede tomar 5-10 minutos...")
    
    print("\n📊 Analizando todos los productos descubiertos...")
    stats = await run_pipeline(csv)
    
    print(f"\n📈 RESULTADOS FINALES:")
    print(f"  Total descubiertos: {stats['total']}")
    print(f"  ✓ Viables (ready to buy): {stats['pass']}")
    print(f"  ✗ Descartados: {stats['drop']}")
    print(f"  ROI mínimo: {stats['roi_min']}%")


# ═══════════════════════════════════════════════════════════════════
#  EJEMPLO 4: Monitoreo Continuo
# ═══════════════════════════════════════════════════════════════════

async def example_4_monitoring():
    """
    Monitorea ASINs del portfolio en tiempo real.
    
    Detecta:
    - Price drops >= 10%
    - Price surges >= 15%
    - BSR improvements >= 20%
    - Restocks
    """
    print("=" * 70)
    print("EJEMPLO 4: Monitoreo Continuo")
    print("=" * 70)
    
    # ASINs actuales en el portfolio
    portfolio_asins = [
        "B07XXXXXXXXX1",
        "B08XXXXXXXXX2",
        "B09XXXXXXXXX3",
        "B0AXXXXXXXXX4",
        "B0BXXXXXXXXX5",
    ]
    
    print(f"\n📊 Monitoreando {len(portfolio_asins)} ASINs")
    print(f"   Intervalo: cada 30 minutos")
    print(f"   Duración: 24 horas")
    print(f"   (Presiona Ctrl+C para detener)\n")
    
    await run_monitoring(
        watchlist_asins=portfolio_asins,
        check_interval_minutes=30,
        duration_hours=24
    )
    
    print("\n✓ Monitoreo completado")


# ═══════════════════════════════════════════════════════════════════
#  EJEMPLO 5: Búsqueda Iterativa (Recomendado para Desarrollo)
# ═══════════════════════════════════════════════════════════════════

async def example_5_iterative_discovery():
    """
    Búsqueda iterativa: pequeñas sesiones de discovery.
    
    Útil para:
    - Testing
    - Validar palabras clave
    - Ajustar parámetros
    """
    print("=" * 70)
    print("EJEMPLO 5: Búsqueda Iterativa")
    print("=" * 70)
    
    keyword_batches = [
        ["gaming mouse", "gaming keyboard"],
        ["usb-c cable", "power adapter"],
        ["phone stand", "tablet holder"],
    ]
    
    all_stats = []
    
    for i, batch in enumerate(keyword_batches, 1):
        print(f"\n🔄 Iteración {i}/{len(keyword_batches)}")
        print(f"   Keywords: {batch}")
        
        # Generar CSV único por batch
        csv = await run_scraper_by_keywords(
            keywords=batch,
            output_csv=f"data/batch_{i}.csv",
            max_results=50
        )
        
        # Analizar
        stats = await run_pipeline(csv)
        all_stats.append(stats)
        
        print(f"   ✓ {stats['pass']} viables encontrados")
        
        # Esperar entre batches (respetar rate limits)
        if i < len(keyword_batches):
            print(f"   ⏳ Esperando 30 segundos antes del siguiente batch...")
            await asyncio.sleep(30)
    
    # Resumen final
    print("\n" + "=" * 70)
    print("RESUMEN TOTAL")
    print("=" * 70)
    
    total_viable = sum(s['pass'] for s in all_stats)
    total_processed = sum(s['total'] for s in all_stats)
    
    print(f"Total procesados: {total_processed}")
    print(f"Total viables: {total_viable}")
    print(f"Ratio: {total_viable/total_processed*100:.1f}% viables")


# ═══════════════════════════════════════════════════════════════════
#  EJEMPLO 6: Pipeline desde CSV Existente
# ═══════════════════════════════════════════════════════════════════

async def example_6_analyze_existing_csv():
    """
    Si ya tienes un CSV de scrapers, analízalo directamente.
    
    Útil cuando:
    - El scraping falló a mitad
    - Quieres re-analizar resultados
    - Tienes datos de fuente externa
    """
    print("=" * 70)
    print("EJEMPLO 6: Analizar CSV Existente")
    print("=" * 70)
    
    csv_path = Path("data/discovered_products.csv")
    
    if not csv_path.exists():
        print(f"⚠️  CSV no encontrado: {csv_path}")
        print("   Primero ejecuta: await run_scraper_by_keywords(['mouse'])")
        return
    
    print(f"\n📊 Analizando: {csv_path}")
    
    stats = await run_pipeline(csv_path)
    
    print(f"\n📈 RESULTADOS:")
    print(f"  Total: {stats['total']}")
    print(f"  ✓ Viables: {stats['pass']}")
    print(f"  ✗ Descartados: {stats['drop']}")


# ═══════════════════════════════════════════════════════════════════
#  MAIN: Seleccionar ejemplos
# ═══════════════════════════════════════════════════════════════════

async def main():
    """
    Menú para seleccionar ejemplos.
    
    Uso:
        python examples/scraper_usage.py
    """
    
    print("\n🎯 EJEMPLOS DE SCRAPER")
    print("=" * 70)
    print("1. Búsqueda Simple por Keywords")
    print("2. Análisis de Competencia")
    print("3. Discovery Completo (Keywords + Competencia)")
    print("4. Monitoreo Continuo")
    print("5. Búsqueda Iterativa")
    print("6. Analizar CSV Existente")
    print("=" * 70)
    
    choice = input("\nSelecciona un ejemplo (1-6): ").strip()
    
    examples = {
        "1": example_1_keyword_search,
        "2": example_2_competitor_analysis,
        "3": example_3_full_discovery,
        "4": example_4_monitoring,
        "5": example_5_iterative_discovery,
        "6": example_6_analyze_existing_csv,
    }
    
    if choice not in examples:
        print("❌ Selección inválida")
        return
    
    example_fn = examples[choice]
    
    try:
        await example_fn()
    except KeyboardInterrupt:
        print("\n\n⏹️  Ejemplo interrumpido por usuario")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nPosibles soluciones:")
        print("1. Verificar que Redis está corriendo: docker-compose up -d redis")
        print("2. Verificar que PostgreSQL está corriendo: docker-compose up -d db")
        print("3. Verificar variables de entorno en .env")
        print("4. Ver más detalles en DEPLOYMENT_AND_TROUBLESHOOTING.md")


if __name__ == "__main__":
    asyncio.run(main())
