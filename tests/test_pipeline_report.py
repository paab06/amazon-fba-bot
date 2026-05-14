# tests/test_pipeline_report.py
"""
Test que genera un reporte detallado del pipeline:
- Qué productos PASARON y por qué (chollos)
- Qué productos FALLARON y la razón exacta
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.pipeline.ingestor import read_csv, ProductInput
from src.pipeline.ean_resolver import EANResolver, ResolvedProduct
from src.pipeline.shields import BrandBlacklistShield, EnrichedProduct
from src.pipeline.financial_calc import FinancialCalculator
from src.core.exceptions import PipelineDropError


@pytest.fixture
def sample_csv_extended():
    """CSV con 6 productos para análisis detallado."""
    csv_content = """ean,buy_price
5901234123457,12.50
4006381333931,8.00
9780134685991,45.99
1234567890128,25.00
9999999999999,100.00
5555555555555,5.00
"""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    tmp.write(csv_content)
    tmp.close()
    yield Path(tmp.name)
    Path(tmp.name).unlink()


@pytest.fixture
def blacklist_file_extended():
    """Blacklist con marcas peligrosas."""
    data = ["Nike", "Apple", "Adidas", "ExpensiveBrand"]
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(data, tmp)
    tmp.close()
    yield Path(tmp.name)
    Path(tmp.name).unlink()


@pytest.fixture
def mock_sp_client_extended():
    """Mock de SP-API con productos variados."""
    client = AsyncMock()
    
    def _search_result(ean):
        """Retorna resultado según el EAN."""
        results = {
            "5901234123457": {
                "asin": "B000TEST01",
                "title": "Monitor 27\" Full HD",
                "brand": "SafeBrand",
                "rank": 5000,
                "category": "Electrónica",
            },
            "4006381333931": {
                "asin": "B000TEST02",
                "title": "Teclado Mecánico RGB",
                "brand": "TrustedBrand",
                "rank": 2000,
                "category": "Hogar y cocina",
            },
            "9780134685991": {
                "asin": "B000TEST03",
                "title": "Gafas de Sol Vintage",
                "brand": "Nike",  # ❌ Bloqueado por blacklist
                "rank": 100,
                "category": "Libros",
            },
            "1234567890128": {
                "asin": "B000TEST04",
                "title": "Mouse Inalámbrico",
                "brand": "LogitechClone",
                "rank": 50000,  # ❌ BSR muy alto
                "category": "Electrónica",
            },
            "9999999999999": {
                "asin": "B000TEST05",
                "title": "Laptop Gaming",
                "brand": "ExpensiveBrand",  # ❌ Bloqueado por blacklist
                "rank": 10,
                "category": "Electrónica",
            },
            "5555555555555": {
                "asin": "B000TEST06",
                "title": "Cable USB-C 2m",
                "brand": "CheapBrand",
                "rank": 1,  # ✅ Excelente
                "category": "Electrónica",
            },
        }
        
        if ean not in results:
            raise Exception(f"ASIN not found for {ean}")
        
        data = results[ean]
        return {
            "items": [{
                "asin": data["asin"],
                "summaries": [
                    {"itemName": data["title"], "brand": data["brand"]}
                ],
                "salesRanks": [
                    {"rank": data["rank"], "displayGroupRanks": [{"title": data["category"]}]}
                ],
            }]
        }
    
    async def mock_search(ean):
        return _search_result(ean)
    
    client.search_catalog_by_ean = AsyncMock(side_effect=mock_search)
    return client


@pytest.fixture
def mock_redis():
    """Mock de Redis."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    return redis


@pytest.mark.asyncio
async def test_pipeline_report_detailed(
    sample_csv_extended,
    blacklist_file_extended,
    mock_sp_client_extended,
    mock_redis,
    capsys,
):
    """
    Ejecuta el pipeline y muestra un reporte detallado de cada producto.
    """
    print("\n" + "="*80)
    print("REPORTE DEL PIPELINE - ANÁLISIS DE PRODUCTOS")
    print("="*80)
    
    # 1. INGESTIÓN
    print("\n[1] INGESTIÓN - Leyendo CSV...")
    products = []
    async for product in read_csv(sample_csv_extended):
        products.append(product)
    print(f"✓ {len(products)} productos leídos del CSV\n")
    
    # 2. RESOLUCIÓN DE EANs
    print("[2] RESOLUCIÓN - EAN → ASIN (SP-API mock)...")
    resolver = EANResolver(sp_client=mock_sp_client_extended, redis=mock_redis)
    resolved_products = []
    
    for product in products:
        try:
            resolved = await resolver.resolve(product)
            if resolved:
                resolved_products.append(resolved)
                print(f"  ✓ EAN {product.ean:15} → ASIN {resolved.asin:12} ({resolved.title[:30]}...)")
        except Exception as e:
            print(f"  ✗ EAN {product.ean:15} → ERROR: {str(e)[:50]}")
    
    print(f"\n✓ {len(resolved_products)} ASINs resueltos\n")
    
    # 3. VALIDACIÓN DE SHIELDS
    print("[3] SHIELDS - Validación de seguridad...")
    blacklist_shield = BrandBlacklistShield(blacklist_file_extended)
    
    passed_shields = []
    dropped_shields = []
    
    for resolved in resolved_products:
        try:
            await blacklist_shield.check(resolved)
            passed_shields.append(resolved)
            print(f"  ✅ PASA     {resolved.asin} | Brand: {resolved.brand:20} | BSR: {resolved.sales_ranks[0]['rank']:6}")
        except PipelineDropError as e:
            dropped_shields.append((resolved, str(e)))
            print(f"  ❌ DESCARTA {resolved.asin} | Razón: {e.reason[:60]}")
    
    print(f"\n✓ {len(passed_shields)} productos pasan shields")
    print(f"✗ {len(dropped_shields)} productos descartados\n")
    
    # 4. CÁLCULO FINANCIERO
    print("[4] FINANCIAL CALC - Análisis de rentabilidad...")
    calc = FinancialCalculator(sp_client=mock_sp_client_extended)
    
    accepted_deals = []
    dropped_financial = []
    
    for resolved in passed_shields:
        # Simular enriquecimiento con datos de Buy Box
        enriched = EnrichedProduct(
            ean=resolved.ean,
            asin=resolved.asin,
            buy_price=resolved.buy_price,
            title=resolved.title,
            brand=resolved.brand,
            sales_ranks=resolved.sales_ranks,
            source_row=resolved.source_row,
            buybox_price=29.99,  # Precio simulado de Buy Box
            buybox_seller_name="DistribuidorSL",
            buybox_is_fba=True,
            fba_fee=3.50,
            referral_fee=4.50,
        )
        
        result = await calc.evaluate(enriched)
        
        # Verificar si es un resultado válido o un drop
        if hasattr(result, 'drop_reason'):  # Es un drop
            dropped_financial.append((enriched, result.drop_reason))
            print(f"  ❌ {enriched.asin:12} | {enriched.title[:30]:30} | Razón: {result.drop_reason}")
        else:  # Es un resultado válido (chollos)
            net_profit = result.net_profit
            roi_pct = result.roi_pct
            accepted_deals.append((enriched, result))
            print(f"  💰 {enriched.asin:12} | {enriched.title[:30]:30} | Ganancia: €{net_profit:6.2f} | ROI: {roi_pct:6.1f}%")
    
    # 5. RESUMEN FINAL
    print("\n" + "="*80)
    print("RESUMEN FINAL")
    print("="*80)
    print(f"\n📊 ESTADÍSTICAS:")
    print(f"   Total CSV:         {len(products)}")
    print(f"   EANs resueltos:    {len(resolved_products)}")
    print(f"   Pasan shields:     {len(passed_shields)}")
    print(f"   Descartados:       {len(dropped_shields) + len(dropped_financial)}")
    print(f"   ✅ CHOLLOS ACEPTADOS: {len(accepted_deals)}")
    
    if accepted_deals:
        print(f"\n🏆 PRODUCTOS RECOMENDADOS (CHOLLOS):")
        total_profit = 0
        total_roi = 0
        for enriched, result in accepted_deals:
            print(f"   • {enriched.asin} - {enriched.title}")
            print(f"     Compra: €{enriched.buy_price:.2f} | Venta: €{enriched.buybox_price:.2f}")
            print(f"     Ganancia neta: €{result.net_profit:.2f} | ROI: {result.roi_pct:.1f}%")
            print(f"     BSR: {enriched.sales_ranks[0]['rank']} en {enriched.sales_ranks[0]['category']}")
            print()
            total_profit += result.net_profit
            total_roi += result.roi_pct
        
        print(f"   TOTAL POTENCIAL: €{total_profit:.2f} (ROI promedio: {total_roi/len(accepted_deals):.1f}%)")
    
    if dropped_shields + dropped_financial:
        print(f"\n⚠️  PRODUCTOS DESCARTADOS ({len(dropped_shields) + len(dropped_financial)}):")
        
        if dropped_shields:
            print(f"\n   Por Shields ({len(dropped_shields)}):")
            for resolved, reason in dropped_shields:
                print(f"     • {resolved.asin} ({resolved.brand}) - {reason[:70]}")
        
        if dropped_financial:
            print(f"\n   Por Financiero ({len(dropped_financial)}):")
            for enriched, reason in dropped_financial:
                print(f"     • {enriched.asin} - {reason[:70]}")
    
    print("\n" + "="*80 + "\n")
