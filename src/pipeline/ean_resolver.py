# src/pipeline/ean_resolver.py
"""
EAN Resolver — Módulo 2
Convierte EAN/UPC → ASIN usando la Catalog Items API (v2022-04-01).

Estrategia de caché (Redis):
  - Key:   ean_resolver:{ean}
  - Value: JSON con asin, title, brand, sales_ranks
  - TTL:   7 días (los ASINs raramente cambian)

Si el EAN resuelve más de un ASIN (pack + unitario, por ej.)
se selecciona el resultado con mejor BSR en su categoría principal.
Si no resuelve ninguno, se descarta el producto con log WARNING.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Optional

import structlog
from aioredis import Redis

from src.api.sp_api_client import SPAPIClient
from src.core.exceptions import SPAPINotFoundError
from src.pipeline.ingestor import ProductInput

log = structlog.get_logger(__name__)

_CACHE_TTL = 60 * 60 * 24 * 7   # 7 días en segundos
_CACHE_PREFIX = "ean_resolver:"


@dataclass(slots=True)
class ResolvedProduct:
    """
    Producto con identidad Amazon confirmada.
    Este objeto viaja a través del resto del pipeline.
    """
    ean: str
    asin: str
    buy_price: float
    title: str
    brand: str
    # BSR por categoría: [{"rank": 42, "category": "Electrónica"}, ...]
    sales_ranks: list[dict] = field(default_factory=list)
    # Metadatos de trazabilidad
    source_row: int = 0


class EANResolver:
    """
    Resuelve EANs a ASINs con caché Redis y fallback a SP-API.

    Uso:
        resolver = EANResolver(sp_client, redis)
        product = await resolver.resolve(product_input)
    """

    def __init__(self, sp_client: SPAPIClient, redis: Redis) -> None:
        self._sp = sp_client
        self._redis = redis

    async def resolve(
        self, product_input: ProductInput
    ) -> Optional[ResolvedProduct]:
        """
        Resuelve un EAN. Devuelve None si no hay resultado válido
        (el pipeline lo descartará sin lanzar excepción).
        """
        ean = product_input.ean
        log.info("ean_resolver.start", ean=ean, row=product_input.source_row)

        # ── 1. Consultar caché ─────────────────────────────────────
        cached = await self._get_from_cache(ean)
        if cached:
            log.debug("ean_resolver.cache_hit", ean=ean)
            return ResolvedProduct(
                **cached,
                buy_price=product_input.buy_price,
                source_row=product_input.source_row,
            )

        # ── 2. Llamar SP-API ───────────────────────────────────────
        try:
            raw = await self._sp.search_catalog_by_ean(ean)
        except SPAPINotFoundError:
            log.warning("ean_resolver.not_found", ean=ean)
            return None
        except Exception as exc:
            log.error("ean_resolver.api_error", ean=ean, error=str(exc))
            return None

        # ── 3. Parsear resultados ──────────────────────────────────
        items: list[dict] = raw.get("items", [])
        if not items:
            log.warning("ean_resolver.no_items", ean=ean)
            return None

        best = self._select_best_item(items, ean)
        if best is None:
            return None

        # ── 4. Guardar en caché ────────────────────────────────────
        cache_payload = {
            "ean": ean,
            "asin": best["asin"],
            "title": best["title"],
            "brand": best["brand"],
            "sales_ranks": best["sales_ranks"],
        }
        await self._set_cache(ean, cache_payload)

        log.info(
            "ean_resolver.resolved",
            ean=ean,
            asin=best["asin"],
            title=best["title"][:60],
        )
        return ResolvedProduct(
            ean=ean,
            asin=best["asin"],
            buy_price=product_input.buy_price,
            title=best["title"],
            brand=best["brand"],
            sales_ranks=best["sales_ranks"],
            source_row=product_input.source_row,
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _select_best_item(
        self, items: list[dict], ean: str
    ) -> Optional[dict]:
        """
        Si hay varios ASINs para el mismo EAN (ej. pack + unidad),
        elegimos el que tenga el BSR más bajo (= más ventas)
        en su categoría principal.
        """
        parsed: list[dict] = []

        for item in items:
            asin = item.get("asin", "")
            if not asin:
                continue

            # summaries[0] contiene title y brand
            summaries = item.get("summaries", [])
            summary = summaries[0] if summaries else {}
            title = summary.get("itemName", "").strip()
            brand = summary.get("brand", "").strip()

            # salesRanks puede tener múltiples categorías
            raw_ranks: list[dict] = item.get("salesRanks", [])
            sales_ranks = [
                {
                    "rank": r.get("rank", 999_999),
                    "category": r.get("displayGroupRanks", [{}])[0].get(
                        "title", "Unknown"
                    ) if r.get("displayGroupRanks") else "Unknown",
                }
                for r in raw_ranks
            ]

            # BSR principal = rank más bajo entre todas las categorías
            best_rank = min(
                (r["rank"] for r in sales_ranks), default=999_999
            )

            parsed.append({
                "asin": asin,
                "title": title,
                "brand": brand,
                "sales_ranks": sales_ranks,
                "_best_rank": best_rank,
            })

        if not parsed:
            log.warning("ean_resolver.no_valid_asins", ean=ean)
            return None

        # Ordenar por mejor BSR; si hay empate, el primero gana
        parsed.sort(key=lambda x: x["_best_rank"])
        chosen = parsed[0]

        if len(parsed) > 1:
            log.info(
                "ean_resolver.multi_asin",
                ean=ean,
                total=len(parsed),
                chosen_asin=chosen["asin"],
                chosen_rank=chosen["_best_rank"],
            )

        # Limpiar key interna antes de devolver
        chosen.pop("_best_rank")
        return chosen

    async def _get_from_cache(self, ean: str) -> Optional[dict]:
        key = f"{_CACHE_PREFIX}{ean}"
        try:
            value = await self._redis.get(key)
            if value:
                return json.loads(value)
        except Exception as exc:
            # Si Redis falla, simplemente vamos a la API
            log.warning("ean_resolver.cache_read_error", ean=ean, error=str(exc))
        return None

    async def _set_cache(self, ean: str, payload: dict) -> None:
        key = f"{_CACHE_PREFIX}{ean}"
        try:
            await self._redis.setex(
                key, _CACHE_TTL, json.dumps(payload, ensure_ascii=False)
            )
        except Exception as exc:
            log.warning("ean_resolver.cache_write_error", ean=ean, error=str(exc))