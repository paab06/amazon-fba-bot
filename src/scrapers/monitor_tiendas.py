"""
Monitor de Tiendas — Script asíncrono autónomo

Scrape de múltiples URLs de liquidaciones/outlets para extraer EANs y precios
de oferta. Consolida los datos, escribe en data/input_sample.csv e invoca
automáticamente el pipeline principal.

Características:
  - Scraping asíncrono con httpx
  - Extracción de EAN (13 dígitos) y precios limpios
  - Manejo de excepciones por URL (continúa si una falla)
  - Auto-invocación del pipeline (src/main.py)
"""
from __future__ import annotations

import asyncio
import csv
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import structlog
from bs4 import BeautifulSoup

log = structlog.get_logger(__name__)

# ════════════════════════════════════════════════════════════════════
#  URLs Mutable — Tiendas de Liquidaciones/Outlets
# ════════════════════════════════════════════════════════════════════

MONITOR_URLS: list[str] = [
    # Prueba 1: Carrefour outlet (España)
    "https://www.carrefour.es/supermercado/ofertas",
    # Prueba 2: El Corte Inglés liquidaciones
    "https://www.elcorteingles.es/bazar/liquidacion/",
    # Prueba 3: Amazon Warehouse Deals
    "https://www.amazon.es/s?k=warehouse+deals&i=warehouse-deals",
]

# ════════════════════════════════════════════════════════════════════
#  Cleaners
# ════════════════════════════════════════════════════════════════════


def clean_ean(raw_ean: str) -> Optional[str]:
    """Extrae 13 dígitos numéricos del string. Retorna None si no hay 13."""
    digits_only = re.sub(r"\D", "", raw_ean.strip())
    if len(digits_only) == 13:
        return digits_only
    return None


def clean_price(raw_price: str) -> Optional[float]:
    """Limpia símbolo de moneda y convierte coma a punto decimal."""
    # Elimina símbolos de moneda y espacios
    cleaned = re.sub(r"[€$£\s]", "", raw_price.strip())
    # Reemplaza coma decimal por punto
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


# ════════════════════════════════════════════════════════════════════
#  Scraper
# ════════════════════════════════════════════════════════════════════


async def scrape_url(client: httpx.AsyncClient, url: str) -> list[dict]:
    """
    Scrape una URL individual.

    Retorna lista de dicts: [{"ean": "...", "buy_price": 12.50}, ...]
    """
    products = []

    try:
        log.info("Scrapeando URL", url=url)
        response = await client.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Búsqueda genérica de EAN y precios en atributos comunes
        # (En realidad, necesitarías adaptar estos selectores a cada tienda)
        product_items = soup.find_all(
            class_=re.compile(r"product|item|offer", re.IGNORECASE)
        )

        for item in product_items:
            # Busca patrón de EAN en atributos o contenido
            ean_elem = item.find(attrs={"data-ean": True})
            if not ean_elem:
                # Intenta en el texto
                item_text = item.get_text()
                ean_match = re.search(r"\b(\d{12,14})\b", item_text)
                if ean_match:
                    raw_ean = ean_match.group(1)
                else:
                    continue
            else:
                raw_ean = ean_elem.get("data-ean", "")

            clean_ean_val = clean_ean(raw_ean)
            if not clean_ean_val:
                continue

            # Busca precio
            price_elem = item.find(class_=re.compile(r"price|offer-price", re.IGNORECASE))
            if not price_elem:
                # Intenta en el texto
                price_text = item.get_text()
                price_match = re.search(r"(?:€|\$|£)?\s*(\d+[,\.]\d{2})", price_text)
                if price_match:
                    raw_price = price_match.group(0)
                else:
                    continue
            else:
                raw_price = price_elem.get_text()

            clean_price_val = clean_price(raw_price)
            if clean_price_val is None:
                continue

            products.append(
                {
                    "ean": clean_ean_val,
                    "buy_price": clean_price_val,
                }
            )

        log.info("Productos extraídos", url=url, count=len(products))

    except httpx.HTTPError as e:
        log.error("Error HTTP al scrapeando URL", url=url, error=str(e))
    except Exception as e:
        log.error("Error inesperado al scrapear URL", url=url, error=str(e))

    return products


async def scrape_all_urls(urls: list[str]) -> list[dict]:
    """Scrape múltiples URLs concurrentemente con manejo de excepciones."""
    all_products = []

    async with httpx.AsyncClient() as client:
        tasks = [scrape_url(client, url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                log.error("Excepción en scrape", url=url, error=str(result))
                continue
            all_products.extend(result)

    return all_products


# ════════════════════════════════════════════════════════════════════
#  CSV Writer
# ════════════════════════════════════════════════════════════════════


def write_csv(products: list[dict], output_path: str | Path) -> None:
    """Consolida productos y escribe data/input_sample.csv."""
    # Deduplicación por EAN (mantiene la última ocurrencia)
    ean_map = {}
    for product in products:
        ean_map[product["ean"]] = product["buy_price"]

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["ean", "buy_price"])
        writer.writeheader()

        for ean, price in ean_map.items():
            writer.writerow({"ean": ean, "buy_price": f"{price:.2f}"})

    log.info("CSV escrito", path=str(output_path), products_count=len(ean_map))


# ════════════════════════════════════════════════════════════════════
#  Pipeline Invocation
# ════════════════════════════════════════════════════════════════════


def invoke_pipeline(csv_path: str | Path) -> None:
    """Invoca src/main.py con el CSV generado vía subprocess."""
    csv_path = Path(csv_path).resolve()
    project_root = Path(__file__).parent.parent.parent

    main_script = project_root / "src" / "main.py"

    if not main_script.exists():
        log.error("main.py no encontrado", path=str(main_script))
        return

    try:
        log.info("Invocando pipeline", main_script=str(main_script), csv=str(csv_path))
        result = subprocess.run(
            [sys.executable, str(main_script)],
            env={**__import__("os").environ, "INPUT_CSV": str(csv_path)},
            check=True,
            capture_output=False,
        )
        log.info("Pipeline completado", return_code=result.returncode)
    except subprocess.CalledProcessError as e:
        log.error("Pipeline falló", return_code=e.returncode, error=str(e))
    except Exception as e:
        log.error("Error al invocar pipeline", error=str(e))


# ════════════════════════════════════════════════════════════════════
#  Main
# ════════════════════════════════════════════════════════════════════


async def main(
    urls: Optional[list[str]] = None,
    output_csv: str | Path = "data/input_sample.csv",
) -> None:
    """
    Punto de entrada principal.

    Scrape → Consolida → Escribe CSV → Invoca pipeline
    """
    if urls is None:
        urls = MONITOR_URLS

    log.info("Iniciando monitor de tiendas", urls_count=len(urls), timestamp=datetime.utcnow().isoformat())

    # 1. Scrape
    products = await scrape_all_urls(urls)
    log.info("Scrape completado", total_products=len(products))

    if not products:
        log.warning("No se extrajeron productos")
        return

    # 2. Escribe CSV
    output_csv = Path(__file__).parent.parent.parent / output_csv
    write_csv(products, output_csv)

    # 3. Invoca pipeline
    invoke_pipeline(output_csv)

    log.info("Monitor de tiendas completado")


if __name__ == "__main__":
    asyncio.run(main())
