#!/usr/bin/env python3
"""
Test Monitor con Base44 — Script de Prueba

Ejecuta el scraper de tiendas, simula precios de Amazon y envía resultados
a Base44 sin necesidad de APIs reales (Keepa, SP-API).

Flujo:
  1. Scrapeé una tienda (o usa el CSV existente)
  2. Mock de precios de Amazon (precio_tienda * 2.5)
  3. Genera datos enriquecidos simulados (ASIN, BSR, etc.)
  4. Calcula financieros con precios ficticios
  5. Envía a Base44 via webhook
"""

import asyncio
import csv
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import httpx
import structlog
from bs4 import BeautifulSoup

# Imports locales
sys.path.insert(0, str(Path(__file__).parent))

from src.core.config import settings
from src.core.logger import setup_logging
from src.pipeline.financial_calc import FinancialResult, FeeBreakdown
from src.scrapers.monitor_tiendas import scrape_all_urls, clean_ean, clean_price

log = structlog.get_logger(__name__)

# ════════════════════════════════════════════════════════════════════
#  Mock Data Generators
# ════════════════════════════════════════════════════════════════════

AMAZON_CATEGORIES = [
    "Electrónica",
    "Juguetes",
    "Hogar",
    "Deportes",
    "Libros",
    "Bebé",
    "Moda",
    "Accesorios",
]


def generate_fake_asin() -> str:
    """Genera un ASIN fake para pruebas."""
    return "B" + "".join(str(random.randint(0, 9)) for _ in range(9))


def generate_mock_amazon_price(buy_price: float) -> float:
    """
    Simula precio de Amazon como múltiplo del precio de compra.
    Rango realista: 2.0x a 3.5x del precio de tienda.
    """
    multiplier = random.uniform(2.0, 3.5)
    amazon_price = buy_price * multiplier
    # Redondea a .99 o .95 (psicología de precios)
    base = int(amazon_price)
    return base + (0.99 if random.random() > 0.5 else 0.95)


def generate_mock_bsr() -> int:
    """Genera un BSR (Best Seller Rank) fake."""
    return random.randint(500, 50000)


def _ean13_from_12(base_12: str) -> str:
    """Completa dígito de control EAN-13 (12 primeros dígitos numéricos)."""
    rev = base_12[::-1]
    total = sum(int(rev[i]) * (3 if i % 2 == 0 else 1) for i in range(12))
    check = (10 - (total % 10)) % 10
    return base_12 + str(check)


def fallback_mock_tienda_products() -> list[dict]:
    """
    Productos ficticios con el mismo shape que el monitor de tiendas.
    Útil cuando el scrape devuelve 403/0 resultados (anti-bot) o para pruebas offline.
    EANs de 13 dígitos válidos; precios tipo outlet.
    """
    return [
        {
            "ean": "5901234123457",
            "buy_price": 12.90,
            "store": "Carrefour",
            "title": "Pack snacks surtido (simulado monitor)",
        },
        {
            "ean": "4006381333931",
            "buy_price": 24.50,
            "store": "El Corte Inglés",
            "title": "Accesorio hogar liquidación (simulado)",
        },
        {
            "ean": _ean13_from_12("303792016135"),
            "buy_price": 8.99,
            "store": "FNAC",
            "title": "Consumible outlet (simulado)",
        },
        {
            "ean": _ean13_from_12("841234567890"),
            "buy_price": 45.00,
            "store": "MediaMarkt",
            "title": "Gadget tech outlet (simulado)",
        },
        {
            "ean": _ean13_from_12("841000000001"),
            "buy_price": 6.49,
            "store": "Worten",
            "title": "Cable / periférico (simulado)",
        },
    ]


# ════════════════════════════════════════════════════════════════════
#  Scrape + Mock + Financial Calc
# ════════════════════════════════════════════════════════════════════


async def run_test_scrape(urls: list[str], max_products: int = 5) -> list[dict]:
    """
    Scrapeé URLs reales y retorna productos con datos reales de tienda.
    """
    log.info("Iniciando scrape de prueba", urls_count=len(urls))

    async with httpx.AsyncClient() as client:
        from src.scrapers.monitor_tiendas import scrape_url

        products = []
        for url in urls[:3]:  # Limita a las primeras 3 tiendas
            try:
                result = await scrape_url(client, url)
                products.extend(result)
                if len(products) >= max_products:
                    break
            except Exception as e:
                log.error("Error en scrape", url=url, error=str(e))

    log.info("Productos scrapeados", count=len(products))
    return products[:max_products]


def enrich_with_mock_amazon(
    tienda_products: list[dict],
) -> list[dict]:
    """
    Enriquece productos de tienda con datos ficticios de Amazon.
    """
    enriched = []

    for product in tienda_products:
        ean = product["ean"]
        buy_price = product["buy_price"]

        # Genera datos falsos pero realistas
        amazon_price = generate_mock_amazon_price(buy_price)
        asin = generate_fake_asin()
        bsr = generate_mock_bsr()
        category = random.choice(AMAZON_CATEGORIES)

        enriched.append(
            {
                "ean": ean,
                "buy_price": buy_price,
                "asin": asin,
                "amazon_price": amazon_price,
                "bsr": bsr,
                "category": category,
                "title": product.get("title") or f"Producto {ean}",
                "brand": product.get("store") or "Test Brand",
            }
        )

    log.info("Productos enriquecidos con mock Amazon", count=len(enriched))
    return enriched


def calculate_mock_financials(product: dict) -> Optional[FinancialResult]:
    """
    Calcula financieros usando precios simulados.
    """
    buy_price = product["buy_price"]
    amazon_price = product["amazon_price"]  # BuyBox price
    ean = product["ean"]
    asin = product["asin"]

    # Calcula fees estimados (Amazon España)
    referral_fee_pct = 0.15  # ~15% para electrónica/hogar
    fba_fee = 3.50  # Estimado para peso medio
    referral_fee = amazon_price * referral_fee_pct
    prep_shipping = 0.50  # Settings default

    fees = FeeBreakdown(
        fba_fee=fba_fee,
        referral_fee=referral_fee,
        prep_shipping=prep_shipping,
    )

    net_profit = amazon_price - (buy_price + fees.total)
    roi_pct = (net_profit / buy_price * 100) if buy_price > 0 else 0

    # Calcula BSR top percentage (simulado)
    bsr_top_pct = random.uniform(0.5, 5.0)

    # Crea FinancialResult
    result = FinancialResult(
        asin=asin,
        ean=ean,
        title=product.get("title", f"Producto {ean}"),
        brand=product.get("brand", "Unknown"),
        source_row=0,
        buy_price=buy_price,
        buybox_price=amazon_price,
        fees=fees,
        net_profit=net_profit,
        roi_pct=roi_pct,
        bsr_rank=product.get("bsr", 5000),
        bsr_category=product.get("category", "Electronics"),
        bsr_category_size=100000,
        bsr_top_pct=bsr_top_pct,
        buybox_seller_name="Amazon EU S.À.R.L.",
        buybox_is_fba=True,
    )

    log.info(
        "Financials calculados",
        asin=asin,
        roi_pct=f"{roi_pct:.2f}%",
        net_profit=f"€{net_profit:.2f}",
    )

    return result


# ════════════════════════════════════════════════════════════════════
#  Send to Base44
# ════════════════════════════════════════════════════════════════════


async def send_to_base44(result: FinancialResult) -> bool:
    """
    Envía un FinancialResult a Base44 via webhook.
    """
    if not settings.base44_webhook_url:
        log.warning("base44_webhook_url no configurada en .env")
        return False

    payload = {
        "asin": result.asin,
        "product_name": result.title,
        "score": 85,
        "amazon_price": float(result.buybox_price),
        "max_buy_price": float(result.buy_price),
        "net_margin": float(result.net_profit),
        "roi_percent": float(result.roi_pct),
        "bsr_percent": float(result.bsr_top_pct),
        "active_sellers": random.randint(2, 8),
        "est_monthly_sales": random.randint(100, 500),
        "category": result.bsr_category,
        "shield_amazon": True,
        "shield_brand": True,
        "shield_massacre": True,
        "shield_account": True,
    }

    headers = {}
    if settings.bot_webhook_token:
        headers["x-bot-token"] = settings.bot_webhook_token

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                settings.base44_webhook_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status == 200:
                    log.info(
                        "✅ Enviado a Base44",
                        asin=result.asin,
                        status=response.status,
                    )
                    return True
                else:
                    response_text = await response.text()
                    log.warning(
                        "❌ Base44 respondió con error",
                        asin=result.asin,
                        status=response.status,
                        response=response_text[:200],
                    )
                    return False

    except asyncio.TimeoutError:
        log.error("⏱️ Timeout al enviar a Base44", asin=result.asin)
        return False
    except Exception as e:
        log.error("❌ Error enviando a Base44", asin=result.asin, error=str(e))
        return False


# ════════════════════════════════════════════════════════════════════
#  Main Test
# ════════════════════════════════════════════════════════════════════


async def main():
    """
    Flujo principal de prueba:
      1. Scrape de tiendas reales
      2. Mock de precios de Amazon
      3. Calcula financieros
      4. Envía a Base44
    """
    setup_logging()

    log.info("=" * 70)
    log.info("🚀 INICIANDO TEST: MONITOR + MOCK AMAZON + BASE44")
    log.info("=" * 70)

    # 1. Scrape
    log.info("\n📊 FASE 1: Scrapeando tiendas reales...")
    from src.scrapers.monitor_tiendas import MONITOR_URLS

    tienda_products = await run_test_scrape(MONITOR_URLS, max_products=5)

    if not tienda_products:
        log.warning(
            "Sin productos del scrape (p. ej. 403 anti-bot); "
            "usando filas simuladas de tiendas oficiales para la prueba Base44"
        )
        tienda_products = fallback_mock_tienda_products()
    else:
        log.info("Productos extraídos del scrape de tiendas", count=len(tienda_products))

    # 2. Enriquece con mock Amazon
    log.info("\n🤖 FASE 2: Generando precios ficticios de Amazon...")
    enriched = enrich_with_mock_amazon(tienda_products)

    # 3. Calcula financieros
    log.info("\n💰 FASE 3: Calculando financieros...")
    financials = []
    for product in enriched:
        result = calculate_mock_financials(product)
        if result:
            financials.append(result)

    # 4. Envía a Base44
    log.info("\n📤 FASE 4: Enviando resultados a Base44...")
    successful = 0
    for result in financials:
        if await send_to_base44(result):
            successful += 1
        await asyncio.sleep(0.5)  # Rate limit

    log.info("\n" + "=" * 70)
    log.info(f"✅ TEST COMPLETADO")
    log.info(f"   Productos scrapeados: {len(tienda_products)}")
    log.info(f"   Enviados a Base44: {successful}/{len(financials)}")
    log.info("=" * 70)

    # Muestra resumen en formato tabla
    log.info("\n📋 RESUMEN DE PRODUCTOS:")
    for result in financials:
        log.info(
            f"  {result.asin} | "
            f"Compra: €{result.buy_price:.2f} | "
            f"Amazon: €{result.buybox_price:.2f} | "
            f"ROI: {result.roi_pct:.1f}% | "
            f"Margen: €{result.net_profit:.2f}"
        )


if __name__ == "__main__":
    asyncio.run(main())
