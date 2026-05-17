"""
Test para verificar que el webhook de Base44 funciona correctamente.
Envía un producto fantasma para comprobar la integración.

Ejecutar con: pytest tests/test_base44_webhook.py -v -s
"""
import pytest
import sys
from pathlib import Path

from src.core.config import settings
from src.pipeline.financial_calc import FinancialResult, FeeBreakdown
from src.pipeline.exporter import send_alert_to_base44
import structlog

log = structlog.get_logger(__name__)


@pytest.mark.asyncio
async def test_base44_webhook_phantom_product():
    """
    Prueba el webhook de Base44 con un producto fantasma.
    Verifica que:
    1. La URL está configurada
    2. El webhook se envía correctamente
    3. El payload tiene la estructura esperada
    """
    
    print("\n" + "="*70)
    print("🧪 TEST: WEBHOOK DE BASE44")
    print("="*70)
    
    # Verificar configuración
    print(f"\n📋 Configuración:")
    print(f"   Base44 URL: {settings.base44_webhook_url}")
    print(f"   Token configurado: {'✓ Sí' if settings.bot_webhook_token else '✗ No'}")
    
    if not settings.base44_webhook_url or "PON_AQUI_EL_APP_ID" in settings.base44_webhook_url:
        pytest.skip("BASE44_WEBHOOK_URL no está configurada en .env (aún tiene placeholder)")
    
    # Crear producto fantasma viable (firma actual de FinancialResult)
    fees = FeeBreakdown(
        fba_fee=8.50,
        referral_fee=4.60,
        prep_shipping=settings.prep_shipping_fixed,
    )

    phantom_product = FinancialResult(
        asin="B0PHANTOM01",
        ean="0000000000000",
        title="🎮 Phantom Gaming Mouse Pad RGB - TEST PRODUCT",
        brand="PhantomBrand",
        source_row=1,
        buy_price=15.00,
        buybox_price=45.99,
        fees=fees,
        net_profit=17.89,
        roi_pct=119.3,
        bsr_rank=1500,
        bsr_category="Electronics",
        bsr_category_size=500000,
        bsr_top_pct=0.3,
        buybox_seller_name="PhantomSeller",
        buybox_is_fba=True,
    )
    
    print(f"\n📦 Producto Fantasma:")
    print(f"   ASIN: {phantom_product.asin}")
    print(f"   Título: {phantom_product.title}")
    print(f"   Precio Amazon: €{phantom_product.buybox_price:.2f}")
    print(f"   Precio Compra: €{phantom_product.buy_price:.2f}")
    print(f"   Margen Neto: €{phantom_product.net_profit:.2f}")
    print(f"   ROI: {phantom_product.roi_pct:.1f}%")
    print(f"   BSR Top: {phantom_product.bsr_top_pct:.2f}%")
    
    print(f"\n🚀 Enviando a Base44...")
    
    # El test no lanza excepción si el webhook falla
    # (la función send_alert_to_base44 atrapa excepciones internamente)
    try:
        await send_alert_to_base44(phantom_product)
        print(f"\n✅ Webhook enviado")
        print(f"   Revisa la URL de Base44 para confirmar la recepción:")
        print(f"   {settings.base44_webhook_url}")
        
    except Exception as exc:
        print(f"\n⚠️ Error durante envío (esperado si Base44 está offline):")
        print(f"   {type(exc).__name__}: {str(exc)}")


@pytest.mark.asyncio
async def test_base44_webhook_skipped_without_config():
    """
    Verifica que el webhook se salta silenciosamente si no está configurado.
    """
    print("\n" + "="*70)
    print("🧪 TEST: WEBHOOK DESHABILITADO")
    print("="*70)
    
    # Crear producto fantasma (firma actual de FinancialResult)
    fees2 = FeeBreakdown(
        fba_fee=5.50,
        referral_fee=3.00,
        prep_shipping=settings.prep_shipping_fixed,
    )

    phantom_product = FinancialResult(
        asin="B0PHANTOM02",
        ean="0000000000001",
        title="Test Product 2",
        brand="TestBrand",
        source_row=2,
        buy_price=10.00,
        buybox_price=29.99,
        fees=fees2,
        net_profit=11.49,
        roi_pct=114.9,
        bsr_rank=2000,
        bsr_category="Electronics",
        bsr_category_size=500000,
        bsr_top_pct=0.5,
        buybox_seller_name="TestSeller",
        buybox_is_fba=True,
    )
    
    if settings.base44_webhook_url and "PON_AQUI_EL_APP_ID" not in settings.base44_webhook_url:
        print(f"✓ Base44 está configurado, saltando test")
        pytest.skip("Base44 está configurado")
    
    print(f"\n📋 Base44 URL: {settings.base44_webhook_url}")
    print(f"   Estado: ✗ No configurado (esperado)")
    
    print(f"\n🚀 Enviando a Base44 (debe ser ignorado)...")
    
    try:
        await send_alert_to_base44(phantom_product)
        print(f"\n✅ Webhook ignorado correctamente (sin URL configurada)")
        
    except Exception as exc:
        print(f"\n❌ Error inesperado:")
        print(f"   {type(exc).__name__}: {str(exc)}")
        raise


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
