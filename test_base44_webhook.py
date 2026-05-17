#!/usr/bin/env python3
"""
Test para verificar que el webhook de Base44 funciona correctamente.
Envía un producto fantasma para comprobar la integración.
"""
import asyncio
import sys
from pathlib import Path

# Agregar src al path
sys.path.insert(0, str(Path(__file__).parent))

from src.core.config import settings
from src.core.logger import setup_logging
from src.pipeline.financial_calc import FinancialResult
from src.pipeline.exporter import send_alert_to_base44
import structlog

log = structlog.get_logger(__name__)


async def test_base44_webhook():
    """
    Prueba el webhook de Base44 con un producto fantasma.
    """
    setup_logging("INFO")
    
    print("\n" + "="*70)
    print("🧪 TEST: WEBHOOK DE BASE44")
    print("="*70)
    
    # Verificar configuración
    print(f"\n📋 Configuración:")
    print(f"   Base44 URL: {settings.base44_webhook_url}")
    print(f"   Token configurado: {'✓ Sí' if settings.bot_webhook_token else '✗ No'}")
    
    if not settings.base44_webhook_url:
        print("\n❌ ERROR: BASE44_WEBHOOK_URL no está configurada en .env")
        print("   Por favor, configura BASE44_WEBHOOK_URL en tu archivo .env")
        return False
    
    # Crear producto fantasma viable
    phantom_product = FinancialResult(
        asin="B0PHANTOM01",
        ean="0000000000000",
        title="🎮 Phantom Gaming Mouse Pad RGB - TEST PRODUCT",
        brand="PhantomBrand",
        category="Electronics",
        price_amazon=45.99,
        buy_price=15.00,
        bsr_rank=1500,
        bsr_category="Electronics",
        bsr_top_pct=0.3,
        buybox_price=45.99,
        buybox_seller_name="PhantomSeller",
        buybox_is_fba=True,
        fba_fee=8.50,
        referral_fee=4.60,
        net_profit=17.89,
        roi_pct=119.3,
        scraped_at="2024-05-17T10:30:00",
        data_source="test_webhook",
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
    
    try:
        await send_alert_to_base44(phantom_product)
        print(f"\n✅ ÉXITO: Webhook enviado correctamente")
        print(f"   Revisa la URL de Base44 para confirmar la recepción:")
        print(f"   {settings.base44_webhook_url}")
        return True
        
    except Exception as exc:
        print(f"\n❌ ERROR al enviar webhook:")
        print(f"   {type(exc).__name__}: {str(exc)}")
        log.error(
            "test.base44_webhook.error",
            error=str(exc),
            exc_info=True,
        )
        return False


async def main():
    """Punto de entrada."""
    success = await test_base44_webhook()
    
    print("\n" + "="*70)
    if success:
        print("✅ TEST COMPLETADO - Webhook enviado correctamente")
    else:
        print("❌ TEST FALLIDO - Verifica la configuración")
    print("="*70 + "\n")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
