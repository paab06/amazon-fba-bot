# src/pipeline/shields.py
"""
Los 5 Escudos de Seguridad — Módulo 3

Cada escudo implementa ShieldBase.check().
El ShieldChain los ejecuta en orden de coste ascendente:
  1. Blacklist local         (0 API calls — O(1) set lookup)
  2. Marca == Seller BB      (0 API calls — datos ya en ResolvedProduct)
  3. Amazon en Buy Box       (0 API calls — datos ya en ResolvedProduct)
  4. Detector de masacres    (1 Keepa call)
  5. Gating SP-API           (1 SP-API call)

Ante cualquier error inesperado, el escudo descarta el producto
(fail-closed) y lo registra para revisión manual.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

from src.api.keepa_client import KeepaClient
from src.api.sp_api_client import SPAPIClient
from src.core.config import settings
from src.core.exceptions import PipelineDropError
from src.pipeline.ean_resolver import ResolvedProduct

log = structlog.get_logger(__name__)

# ── Constantes de negocio ──────────────────────────────────────────
_AMAZON_SELLER_NAMES = frozenset({
    "Amazon",
    "Amazon EU S.à r.l.",
    "Amazon.es",
    "Amazon Media EU S.à r.l.",
    "Warehouse Deals",                  # outlet de Amazon
})
_KEEPA_MASSACRE_WINDOW_DAYS = 90        # ventana de análisis
_KEEPA_MASSACRE_DROP_PCT    = 0.80      # caída >= 80% de vendedores FBA en 1 día


# ══════════════════════════════════════════════════════════════════
#  Protocolo base
# ══════════════════════════════════════════════════════════════════

class ShieldBase(ABC):
    """
    Interfaz que deben implementar todos los escudos.
    check() lanza PipelineDropError si el producto debe descartarse,
    o retorna None si pasa el escudo.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def check(self, product: ResolvedProduct) -> None:
        """
        Lanza PipelineDropError si el producto no pasa.
        Retorna None (implícitamente) si pasa.
        """


# ══════════════════════════════════════════════════════════════════
#  Escudo 1 — Blacklist de marcas peligrosas
# ══════════════════════════════════════════════════════════════════

class BrandBlacklistShield(ShieldBase):
    """
    Compara la marca del producto contra una lista local de marcas
    con historial de denuncias por IP, marca registrada o
    suspensiones de cuenta.

    El archivo JSON es un simple array de strings (case-insensitive):
        ["Nike", "Lego", "Apple", ...]

    Coste: O(1) — set lookup en memoria. Sin API calls.
    """

    name = "shield_1_brand_blacklist"

    def __init__(self, blacklist_path: str | Path) -> None:
        self._blacklist: frozenset[str] = self._load(Path(blacklist_path))
        log.info(
            "shield.blacklist.loaded",
            total_brands=len(self._blacklist),
            path=str(blacklist_path),
        )

    @staticmethod
    def _load(path: Path) -> frozenset[str]:
        if not path.exists():
            log.warning("shield.blacklist.missing", path=str(path))
            return frozenset()
        raw: list[str] = json.loads(path.read_text(encoding="utf-8"))
        return frozenset(b.strip().lower() for b in raw if b.strip())

    async def check(self, product: ResolvedProduct) -> None:
        brand_lower = product.brand.strip().lower()
        if brand_lower in self._blacklist:
            raise PipelineDropError(
                asin=product.asin,
                shield=self.name,
                reason=f"Marca '{product.brand}' en blacklist",
            )
        log.debug("shield.pass", shield=self.name, asin=product.asin)


# ══════════════════════════════════════════════════════════════════
#  Escudo 2 — Marca privada (brand == Buy Box seller)
# ══════════════════════════════════════════════════════════════════

class PrivateLabelShield(ShieldBase):
    """
    Detecta marcas privadas: si el nombre de la marca coincide
    exactamente con el nombre del vendedor de la Buy Box,
    es casi seguro que el fabricante vende directamente y
    defenderá su posición agresivamente (price war + denuncias).

    Coste: 0 API calls — usa datos ya disponibles en ResolvedProduct.
    Los datos de Buy Box (seller_name) deben haberse enriquecido
    antes de llamar a este escudo (ver ShieldChain._enrich).
    """

    name = "shield_2_private_label"

    async def check(self, product: ResolvedProduct) -> None:
        bb_seller = (product.buybox_seller_name or "").strip().lower()
        brand     = product.brand.strip().lower()

        if not bb_seller or not brand:
            # Sin datos suficientes → fail-closed
            raise PipelineDropError(
                asin=product.asin,
                shield=self.name,
                reason="No se pudo obtener seller o marca para comparar (fail-closed)",
            )

        if brand == bb_seller:
            raise PipelineDropError(
                asin=product.asin,
                shield=self.name,
                reason=(
                    f"Marca privada detectada: brand='{product.brand}' "
                    f"== buybox_seller='{product.buybox_seller_name}'"
                ),
            )
        log.debug("shield.pass", shield=self.name, asin=product.asin)


# ══════════════════════════════════════════════════════════════════
#  Escudo 3 — Amazon en Buy Box
# ══════════════════════════════════════════════════════════════════

class AmazonBuyBoxShield(ShieldBase):
    """
    Si Amazon (o cualquiera de sus entidades) posee la Buy Box,
    competir es inviable: Amazon siempre gana en precio y
    suprime listings de terceros.

    Coste: 0 API calls adicionales — usa buybox_seller_name ya enriquecido.
    """

    name = "shield_3_amazon_buybox"

    async def check(self, product: ResolvedProduct) -> None:
        seller = (product.buybox_seller_name or "").strip()

        if not seller:
            raise PipelineDropError(
                asin=product.asin,
                shield=self.name,
                reason="Buy Box sin vendedor identificado (fail-closed)",
            )

        if seller in _AMAZON_SELLER_NAMES:
            raise PipelineDropError(
                asin=product.asin,
                shield=self.name,
                reason=f"Amazon en Buy Box: seller='{seller}'",
            )
        log.debug("shield.pass", shield=self.name, asin=product.asin)


# ══════════════════════════════════════════════════════════════════
#  Escudo 4 — Detector de masacres (Keepa)
# ══════════════════════════════════════════════════════════════════

class KeepaFBAMassacreShield(ShieldBase):
    """
    Una "masacre" ocurre cuando el número de vendedores FBA cae
    más de un 80% en un solo día en los últimos 90 días.
    Señala que Amazon o el brand owner purgó a todos los resellers
    de golpe — alta probabilidad de que vuelva a ocurrir.

    Keepa devuelve el histórico de 'fbaOfferCount' como lista de
    pares [timestamp_keepa, valor] donde timestamp_keepa es
    minutos desde 21 Jan 2011 00:00 UTC (época Keepa).

    Coste: 1 Keepa API call (consume ~1 token Keepa).
    """

    name = "shield_4_keepa_massacre"

    # Época Keepa: 21 Jan 2011 00:00:00 UTC en minutos Unix
    _KEEPA_EPOCH_MINUTES = 21564000

    def __init__(self, keepa_client: KeepaClient) -> None:
        self._keepa = keepa_client

    async def check(self, product: ResolvedProduct) -> None:
        try:
            history = await self._keepa.get_fba_seller_history(product.asin)
        except Exception as exc:
            log.error(
                "shield.keepa.error",
                asin=product.asin,
                error=str(exc),
            )
            raise PipelineDropError(
                asin=product.asin,
                shield=self.name,
                reason=f"Error al consultar Keepa (fail-closed): {exc}",
            )

        massacre = self._detect_massacre(history)
        if massacre:
            raise PipelineDropError(
                asin=product.asin,
                shield=self.name,
                reason=(
                    f"Masacre FBA detectada: caída de {massacre['drop_pct']:.0%} "
                    f"({massacre['before']} → {massacre['after']} vendedores) "
                    f"el {massacre['date']}"
                ),
            )
        log.debug("shield.pass", shield=self.name, asin=product.asin)

    def _detect_massacre(
        self, history: list[tuple[int, int]]
    ) -> Optional[dict]:
        """
        Analiza el histórico de conteo de vendedores FBA.
        history: lista de (keepa_timestamp_minutes, fba_seller_count)

        Devuelve un dict con detalles si detecta una masacre,
        o None si el producto es seguro.
        """
        import time
        from datetime import datetime, timezone, timedelta

        if len(history) < 2:
            return None

        # Filtrar solo los últimos N días
        now_minutes = int(time.time() / 60)
        cutoff = now_minutes - (_KEEPA_MASSACRE_WINDOW_DAYS * 24 * 60)
        window = [
            (ts, count)
            for ts, count in history
            if ts >= cutoff and count >= 0   # Keepa usa -1 para "sin dato"
        ]

        if len(window) < 2:
            return None

        # Buscar caídas abruptas entre días consecutivos
        for i in range(1, len(window)):
            ts_prev, count_prev = window[i - 1]
            ts_curr, count_curr = window[i]

            if count_prev == 0:
                continue   # evitar división por cero

            drop_pct = (count_prev - count_curr) / count_prev

            # ¿Ocurrió en un solo día (≤ 1440 minutos)?
            same_day = (ts_curr - ts_prev) <= 1440

            if same_day and drop_pct >= _KEEPA_MASSACRE_DROP_PCT:
                # Convertir timestamp Keepa a fecha legible
                ts_unix = (ts_curr + self._KEEPA_EPOCH_MINUTES) * 60
                date_str = datetime.fromtimestamp(
                    ts_unix, tz=timezone.utc
                ).strftime("%Y-%m-%d")

                return {
                    "drop_pct": drop_pct,
                    "before": count_prev,
                    "after": count_curr,
                    "date": date_str,
                }

        return None


# ══════════════════════════════════════════════════════════════════
#  Escudo 5 — Gating SP-API
# ══════════════════════════════════════════════════════════════════

class GatingShield(ShieldBase):
    """
    Comprueba si nuestra cuenta tiene permiso para listar
    ese ASIN en condición 'new_new' (nuevo).

    La Listings Restrictions API devuelve:
      - [] (lista vacía)  → sin restricciones → PASS
      - [{reasons: [...]}] → restringido      → DROP

    Razones comunes de restricción:
      - APPROVAL_REQUIRED  → necesita factura del fabricante
      - ASIN_NOT_APPLICABLE → ASIN no existe en este marketplace
      - Si 'reasonCode' contiene 'APPROVAL' → requiere aprobación

    Coste: 1 SP-API call (getListingsRestrictions).
    """

    name = "shield_5_gating"

    # Códigos que indican restricción dura (no recuperable sin gestión manual)
    _HARD_BLOCK_CODES = frozenset({
        "APPROVAL_REQUIRED",
        "ASIN_NOT_APPLICABLE",
        "NOT_ELIGIBLE",
    })

    def __init__(self, sp_client: SPAPIClient, seller_id: str) -> None:
        self._sp = sp_client
        self._seller_id = seller_id

    async def check(self, product: ResolvedProduct) -> None:
        try:
            response = await self._sp.get_listings_restrictions(
                asin=product.asin,
                seller_id=self._seller_id,
                condition_type="new_new",
            )
        except Exception as exc:
            log.error(
                "shield.gating.error",
                asin=product.asin,
                error=str(exc),
            )
            raise PipelineDropError(
                asin=product.asin,
                shield=self.name,
                reason=f"Error al consultar restricciones (fail-closed): {exc}",
            )

        restrictions: list[dict] = response.get("restrictions", [])

        if not restrictions:
            log.debug("shield.pass", shield=self.name, asin=product.asin)
            return

        # Recopilar todos los códigos de razón para el log
        reason_codes: list[str] = []
        for restriction in restrictions:
            for reason in restriction.get("reasons", []):
                code = reason.get("reasonCode", "UNKNOWN")
                reason_codes.append(code)

        log.info(
            "shield.gating.restricted",
            asin=product.asin,
            reason_codes=reason_codes,
        )

        raise PipelineDropError(
            asin=product.asin,
            shield=self.name,
            reason=f"ASIN restringido para venta en 'new': {reason_codes}",
        )


# ══════════════════════════════════════════════════════════════════
#  ResolvedProduct enriquecido (añadir campos de Buy Box)
# ══════════════════════════════════════════════════════════════════

# Extendemos el dataclass del Módulo 2 añadiendo los campos
# que necesitan los escudos 2 y 3. Se rellenan en ShieldChain._enrich()
from dataclasses import dataclass as _dc

@_dc(slots=True)
class EnrichedProduct(ResolvedProduct):
    """
    ResolvedProduct + datos de Buy Box obtenidos de la Pricing API.
    Es el objeto que circula a partir del Módulo 3.
    """
    buybox_price: float        = 0.0
    buybox_seller_name: str    = ""
    buybox_is_fba: bool        = False
    fba_fee: float             = 0.0
    referral_fee: float        = 0.0


# ══════════════════════════════════════════════════════════════════
#  ShieldChain — orquestador
# ══════════════════════════════════════════════════════════════════

@dataclass
class ShieldResult:
    passed: bool
    product: Optional[EnrichedProduct] = None
    drop_shield: Optional[str]         = None
    drop_reason: Optional[str]         = None


class ShieldChain:
    """
    Ejecuta los 5 escudos en orden sobre un ResolvedProduct.

    Antes de aplicar los escudos 2 y 3, enriquece el producto
    con datos de Buy Box (una sola llamada a getItemOffers).

    Uso:
        chain = ShieldChain(sp_client, keepa_client, seller_id, blacklist_path)
        result = await chain.run(resolved_product)
        if result.passed:
            # enviar a financial_calc
    """

    def __init__(
        self,
        sp_client: SPAPIClient,
        keepa_client: KeepaClient,
        seller_id: str,
        blacklist_path: str | Path = "data/brand_blacklist.json",
    ) -> None:
        self._sp = sp_client
        self._shields: list[ShieldBase] = [
            BrandBlacklistShield(blacklist_path),        # Escudo 1 — sin API
            PrivateLabelShield(),                        # Escudo 2 — sin API
            AmazonBuyBoxShield(),                        # Escudo 3 — sin API
            KeepaFBAMassacreShield(keepa_client),        # Escudo 4 — Keepa
            GatingShield(sp_client, seller_id),          # Escudo 5 — SP-API
        ]

    async def run(self, product: ResolvedProduct) -> ShieldResult:
        log.info("shield_chain.start", asin=product.asin)

        # ── Enriquecer con Buy Box antes de los escudos 2 y 3 ─────
        try:
            enriched = await self._enrich(product)
        except PipelineDropError as exc:
            # Si no podemos obtener datos de Buy Box → fail-closed
            return ShieldResult(
                passed=False,
                drop_shield="shield_0_enrichment",
                drop_reason=str(exc),
            )

        # ── Ejecutar escudos en secuencia ──────────────────────────
        for shield in self._shields:
            try:
                await shield.check(enriched)
            except PipelineDropError as exc:
                log.info(
                    "shield_chain.drop",
                    asin=product.asin,
                    shield=exc.shield,
                    reason=exc.reason,
                )
                return ShieldResult(
                    passed=False,
                    drop_shield=exc.shield,
                    drop_reason=exc.reason,
                )
            except Exception as exc:
                # Error inesperado → fail-closed
                log.error(
                    "shield_chain.unexpected_error",
                    asin=product.asin,
                    shield=shield.name,
                    error=str(exc),
                    exc_info=True,
                )
                return ShieldResult(
                    passed=False,
                    drop_shield=shield.name,
                    drop_reason=f"Error inesperado (fail-closed): {exc}",
                )

        log.info("shield_chain.pass", asin=product.asin)
        return ShieldResult(passed=True, product=enriched)

    async def _enrich(self, product: ResolvedProduct) -> EnrichedProduct:
        """
        Llama a getItemOffers para obtener Buy Box price y seller.
        Construye un EnrichedProduct con los datos obtenidos.
        Lanza PipelineDropError si no hay Buy Box activa.
        """
        response = await self._sp.get_item_offers(product.asin, "New")

        # Parsear la respuesta de Pricing API v0
        summary = (
            response
            .get("payload", {})
            .get("Summary", {})
        )
        buybox_prices: list[dict] = summary.get("BuyBoxPrices", [])
        buybox_eligible: list[dict] = summary.get("BuyBoxEligibleOffers", [])

        if not buybox_prices:
            raise PipelineDropError(
                asin=product.asin,
                shield="shield_0_enrichment",
                reason="Sin Buy Box activa en este marketplace",
            )

        # El primer elemento es la Buy Box ganadora
        bb = buybox_prices[0]
        bb_price = float(
            bb.get("LandedPrice", {}).get("Amount", 0)
            or bb.get("ListingPrice", {}).get("Amount", 0)
        )
        bb_condition = bb.get("condition", "New")

        # Obtener seller de la Buy Box desde las ofertas individuales
        offers: list[dict] = (
            response.get("payload", {}).get("Offers", [])
        )
        bb_seller_name = ""
        bb_is_fba = False

        for offer in offers:
            if offer.get("IsBuyBoxWinner", False):
                bb_seller_name = (
                    offer.get("SellerFeedbackRating", {}).get("SellerDisplayName", "")
                    or offer.get("SellerId", "")
                )
                bb_is_fba = offer.get("IsFulfilledByAmazon", False)
                break

        if not bb_seller_name:
            raise PipelineDropError(
                asin=product.asin,
                shield="shield_0_enrichment",
                reason="No se pudo identificar al vendedor de la Buy Box (fail-closed)",
            )

        # Construir EnrichedProduct copiando todos los campos
        return EnrichedProduct(
            ean=product.ean,
            asin=product.asin,
            buy_price=product.buy_price,
            title=product.title,
            brand=product.brand,
            sales_ranks=product.sales_ranks,
            source_row=product.source_row,
            buybox_price=bb_price,
            buybox_seller_name=bb_seller_name,
            buybox_is_fba=bb_is_fba,
        )