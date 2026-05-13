# src/pipeline/financial_calc.py
"""
Calculadora Financiera — Módulo 4

Fórmula:
  Beneficio Neto = BuyBox Price
                 - (Precio Compra + FBA Fee + Referral Fee + Prep/Shipping fijo)
  ROI            = (Beneficio Neto / Precio Compra) * 100

Criterios de exportación (ambos deben cumplirse):
  - ROI >= settings.min_roi_pct          (defecto: 20%)
  - BSR en el top N% de su categoría    (defecto: top 2%)

El top N% del BSR se valida contra los totales de productos
por categoría de Amazon ES, que se mantienen en un JSON local
actualizado periódicamente.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import structlog

from src.api.sp_api_client import SPAPIClient
from src.core.config import settings
from src.core.exceptions import PipelineDropError
from src.pipeline.shields import EnrichedProduct

log = structlog.get_logger(__name__)

# ── Totales de productos por categoría (Amazon ES) ─────────────────
# Fuente: estimaciones públicas + Keepa category tree
# Actualizar trimestralmente ejecutando: scripts/refresh_category_sizes.py
_DEFAULT_CATEGORY_SIZES_PATH = Path("data/category_sizes.json")

# Fallback si una categoría no está en el JSON local
_DEFAULT_CATEGORY_SIZE = 500_000


# ══════════════════════════════════════════════════════════════════
#  Data classes de output
# ══════════════════════════════════════════════════════════════════

@dataclass(slots=True, frozen=True)
class FeeBreakdown:
    fba_fee: float
    referral_fee: float
    prep_shipping: float

    @property
    def total(self) -> float:
        return self.fba_fee + self.referral_fee + self.prep_shipping


@dataclass(slots=True, frozen=True)
class FinancialResult:
    """
    Producto aprobado con todos los números calculados.
    Este es el objeto que se exporta a Google Sheets / DB.
    """
    # Identidad
    asin: str
    ean: str
    title: str
    brand: str
    source_row: int

    # Precios
    buy_price: float
    buybox_price: float

    # Fees
    fees: FeeBreakdown

    # Resultados financieros
    net_profit: float
    roi_pct: float

    # BSR
    bsr_rank: int
    bsr_category: str
    bsr_category_size: int
    bsr_top_pct: float          # ej: 1.2 → top 1.2% de su categoría

    # Metadatos
    buybox_seller_name: str
    buybox_is_fba: bool


@dataclass(slots=True)
class FinancialDropReason:
    asin: str
    buy_price: float
    buybox_price: float
    net_profit: float
    roi_pct: float
    bsr_rank: int
    bsr_top_pct: float
    reason: str                 # "ROI_TOO_LOW" | "BSR_TOO_HIGH" | "BOTH"


# ══════════════════════════════════════════════════════════════════
#  Fee Fetcher
# ══════════════════════════════════════════════════════════════════

class FeeFetcher:
    """
    Obtiene FBA Fee + Referral Fee desde la SP-API (Product Fees API).

    Si el producto ya tiene fees pre-calculados en EnrichedProduct
    (ej: cacheados de una llamada anterior), los reutiliza para
    ahorrar API calls.

    Los fees se obtienen para el precio actual de la Buy Box,
    que es el escenario realista de venta.
    """

    def __init__(self, sp_client: SPAPIClient) -> None:
        self._sp = sp_client

    async def fetch(self, product: EnrichedProduct) -> FeeBreakdown:
        # Si ya tenemos fees del enriquecimiento, reutilizarlos
        if product.fba_fee > 0 and product.referral_fee > 0:
            log.debug(
                "fee_fetcher.cache_hit",
                asin=product.asin,
                fba_fee=product.fba_fee,
                referral_fee=product.referral_fee,
            )
            return FeeBreakdown(
                fba_fee=product.fba_fee,
                referral_fee=product.referral_fee,
                prep_shipping=settings.prep_shipping_fixed,
            )

        log.debug("fee_fetcher.api_call", asin=product.asin)
        try:
            response = await self._sp.get_my_fees_estimate(
                asin=product.asin,
                price=product.buybox_price,
            )
        except Exception as exc:
            log.error(
                "fee_fetcher.error",
                asin=product.asin,
                error=str(exc),
            )
            raise PipelineDropError(
                asin=product.asin,
                shield="financial_calc",
                reason=f"No se pudieron obtener fees (fail-closed): {exc}",
            )

        return self._parse_fees(response, product.asin)

    @staticmethod
    def _parse_fees(response: dict, asin: str) -> FeeBreakdown:
        """
        Extrae FBA Fee y Referral Fee de la respuesta de
        getMyFeesEstimate. La estructura anidada de SP-API
        requiere navegación defensiva.
        """
        try:
            estimate = (
                response
                .get("payload", {})
                .get("FeesEstimateResult", {})
                .get("FeesEstimate", {})
            )
            fee_list: list[dict] = estimate.get("FeeDetailList", [])

            fba_fee = 0.0
            referral_fee = 0.0

            for fee in fee_list:
                fee_type = fee.get("FeeType", "")
                amount = float(
                    fee.get("FinalFee", {}).get("Amount", 0)
                )
                if fee_type == "FBAFees":
                    fba_fee = amount
                elif fee_type == "ReferralFee":
                    referral_fee = amount

            if fba_fee == 0.0 and referral_fee == 0.0:
                raise ValueError("Fees vacíos en la respuesta")

            return FeeBreakdown(
                fba_fee=fba_fee,
                referral_fee=referral_fee,
                prep_shipping=settings.prep_shipping_fixed,
            )

        except (KeyError, TypeError, ValueError) as exc:
            raise PipelineDropError(
                asin=asin,
                shield="financial_calc",
                reason=f"Error al parsear fees de SP-API: {exc}",
            )


# ══════════════════════════════════════════════════════════════════
#  BSR Validator
# ══════════════════════════════════════════════════════════════════

class BSRValidator:
    """
    Valida que el BSR del producto esté en el top N% de su categoría.

    Carga los tamaños de categoría desde un JSON local:
        {
          "Electrónica": 850000,
          "Hogar y cocina": 1200000,
          "Deportes y aire libre": 600000,
          ...
        }

    Si la categoría no está en el JSON, usa _DEFAULT_CATEGORY_SIZE
    como fallback conservador.
    """

    def __init__(
        self,
        category_sizes_path: Path = _DEFAULT_CATEGORY_SIZES_PATH,
    ) -> None:
        self._sizes: dict[str, int] = self._load(category_sizes_path)

    @staticmethod
    def _load(path: Path) -> dict[str, int]:
        if not path.exists():
            log.warning(
                "bsr_validator.sizes_missing",
                path=str(path),
                fallback=_DEFAULT_CATEGORY_SIZE,
            )
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        log.info("bsr_validator.loaded", categories=len(data))
        return {k.lower().strip(): int(v) for k, v in data.items()}

    def get_top_pct(self, rank: int, category: str) -> float:
        """
        Devuelve el percentil superior del BSR.
        Ej: rank=5000, category_size=500000 → top 1.0%
        Un valor MENOR es MEJOR (top 1% > top 5%).
        """
        size = self._sizes.get(category.lower().strip(), _DEFAULT_CATEGORY_SIZE)
        if size <= 0:
            return 100.0
        return (rank / size) * 100.0

    def is_valid(self, rank: int, category: str) -> tuple[bool, float]:
        """
        Retorna (válido, top_pct).
        válido = True si top_pct <= settings.bsr_top_pct
        """
        top_pct = self.get_top_pct(rank, category)
        return top_pct <= settings.bsr_top_pct, top_pct


# ══════════════════════════════════════════════════════════════════
#  Financial Calculator
# ══════════════════════════════════════════════════════════════════

class FinancialCalculator:
    """
    Orquesta el cálculo completo para un EnrichedProduct.

    Uso:
        calc = FinancialCalculator(sp_client)
        result = await calc.evaluate(enriched_product)
        # result es FinancialResult o FinancialDropReason
    """

    def __init__(self, sp_client: SPAPIClient) -> None:
        self._fee_fetcher = FeeFetcher(sp_client)
        self._bsr_validator = BSRValidator()

    async def evaluate(
        self, product: EnrichedProduct
    ) -> FinancialResult | FinancialDropReason:
        """
        Calcula ROI y valida BSR. Devuelve FinancialResult si pasa,
        FinancialDropReason si no — nunca lanza excepción de negocio.
        """
        log.info("financial_calc.start", asin=product.asin)

        # ── 1. Obtener fees ────────────────────────────────────────
        fees = await self._fee_fetcher.fetch(product)

        # ── 2. Calcular beneficio neto y ROI ──────────────────────
        net_profit, roi_pct = self._calculate(
            buybox_price=product.buybox_price,
            buy_price=product.buy_price,
            fees=fees,
        )

        # ── 3. Validar BSR ─────────────────────────────────────────
        primary_rank, primary_category = self._get_primary_bsr(product)
        bsr_valid, bsr_top_pct = self._bsr_validator.is_valid(
            primary_rank, primary_category
        )

        # ── 4. Logging detallado ───────────────────────────────────
        log.info(
            "financial_calc.result",
            asin=product.asin,
            buy_price=product.buy_price,
            buybox_price=product.buybox_price,
            fba_fee=fees.fba_fee,
            referral_fee=fees.referral_fee,
            prep_shipping=fees.prep_shipping,
            net_profit=round(net_profit, 2),
            roi_pct=round(roi_pct, 2),
            bsr_rank=primary_rank,
            bsr_category=primary_category,
            bsr_top_pct=round(bsr_top_pct, 2),
            roi_ok=roi_pct >= settings.min_roi_pct,
            bsr_ok=bsr_valid,
        )

        # ── 5. Decisión de exportar ────────────────────────────────
        roi_ok = roi_pct >= settings.min_roi_pct
        drop_reason = self._drop_reason(roi_ok, bsr_valid)

        if drop_reason:
            log.info(
                "financial_calc.drop",
                asin=product.asin,
                reason=drop_reason,
                roi_pct=round(roi_pct, 2),
                bsr_top_pct=round(bsr_top_pct, 2),
            )
            return FinancialDropReason(
                asin=product.asin,
                buy_price=product.buy_price,
                buybox_price=product.buybox_price,
                net_profit=round(net_profit, 2),
                roi_pct=round(roi_pct, 2),
                bsr_rank=primary_rank,
                bsr_top_pct=round(bsr_top_pct, 2),
                reason=drop_reason,
            )

        log.info("financial_calc.pass", asin=product.asin)
        return FinancialResult(
            asin=product.asin,
            ean=product.ean,
            title=product.title,
            brand=product.brand,
            source_row=product.source_row,
            buy_price=product.buy_price,
            buybox_price=product.buybox_price,
            fees=fees,
            net_profit=round(net_profit, 2),
            roi_pct=round(roi_pct, 2),
            bsr_rank=primary_rank,
            bsr_category=primary_category,
            bsr_category_size=self._bsr_validator._sizes.get(
                primary_category.lower().strip(), _DEFAULT_CATEGORY_SIZE
            ),
            bsr_top_pct=round(bsr_top_pct, 2),
            buybox_seller_name=product.buybox_seller_name,
            buybox_is_fba=product.buybox_is_fba,
        )

    # ── Helpers privados ───────────────────────────────────────────

    @staticmethod
    def _calculate(
        buybox_price: float,
        buy_price: float,
        fees: FeeBreakdown,
    ) -> tuple[float, float]:
        """
        Aplica la fórmula de negocio:
          Net Profit = BuyBox - (Buy + FBA + Referral + Prep)
          ROI        = (Net Profit / Buy Price) * 100
        """
        net_profit = buybox_price - (buy_price + fees.total)
        roi_pct = (net_profit / buy_price) * 100 if buy_price > 0 else 0.0
        return net_profit, roi_pct

    @staticmethod
    def _get_primary_bsr(product: EnrichedProduct) -> tuple[int, str]:
        """
        Extrae el BSR principal: el de menor rank numérico
        (= más relevante comercialmente).
        Si no hay datos de BSR, devuelve rank 999999 para que
        falle la validación de forma determinista.
        """
        if not product.sales_ranks:
            return 999_999, "Unknown"

        best = min(product.sales_ranks, key=lambda r: r.get("rank", 999_999))
        return best.get("rank", 999_999), best.get("category", "Unknown")

    @staticmethod
    def _drop_reason(roi_ok: bool, bsr_ok: bool) -> str | None:
        if not roi_ok and not bsr_ok:
            return "BOTH_ROI_TOO_LOW_AND_BSR_TOO_HIGH"
        if not roi_ok:
            return "ROI_TOO_LOW"
        if not bsr_ok:
            return "BSR_TOO_HIGH"
        return None