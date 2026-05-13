# tests/test_financial_calc.py
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock
from src.pipeline.financial_calc import (
    FeeFetcher,
    BSRValidator,
    FinancialCalculator,
    FinancialResult,
    FinancialDropReason,
    FeeBreakdown,
)
from src.pipeline.shields import EnrichedProduct
from src.core.exceptions import PipelineDropError


# ── Helpers ────────────────────────────────────────────────────────

def _make_product(**kwargs) -> EnrichedProduct:
    defaults = dict(
        ean="1234567890123",
        asin="B000TEST01",
        buy_price=10.00,
        title="Test Product",
        brand="SafeBrand",
        sales_ranks=[{"rank": 5000, "category": "Electrónica"}],
        source_row=2,
        buybox_price=20.00,
        buybox_seller_name="DistribuidorSL",
        buybox_is_fba=True,
        fba_fee=0.0,
        referral_fee=0.0,
    )
    defaults.update(kwargs)
    return EnrichedProduct(**defaults)


def _make_fees_response(fba: float, referral: float) -> dict:
    return {
        "payload": {
            "FeesEstimateResult": {
                "FeesEstimate": {
                    "FeeDetailList": [
                        {"FeeType": "FBAFees",     "FinalFee": {"Amount": fba}},
                        {"FeeType": "ReferralFee", "FinalFee": {"Amount": referral}},
                    ]
                }
            }
        }
    }


def _make_category_file(sizes: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(sizes, tmp)
    tmp.close()
    return Path(tmp.name)


# ══════════════════════════════════════════════════════════════════
#  FeeFetcher
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_fee_fetcher_uses_cached_fees():
    """Si el producto ya tiene fees, no debe llamar a la SP-API."""
    sp = AsyncMock()
    product = _make_product(fba_fee=3.50, referral_fee=1.80)

    fetcher = FeeFetcher(sp)
    fees = await fetcher.fetch(product)

    assert fees.fba_fee == 3.50
    assert fees.referral_fee == 1.80
    assert fees.prep_shipping == pytest.approx(0.50, abs=0.01)
    sp.get_my_fees_estimate.assert_not_called()


@pytest.mark.asyncio
async def test_fee_fetcher_calls_api_when_no_cache():
    sp = AsyncMock()
    sp.get_my_fees_estimate = AsyncMock(
        return_value=_make_fees_response(fba=4.20, referral=2.10)
    )
    product = _make_product(fba_fee=0.0, referral_fee=0.0)

    fetcher = FeeFetcher(sp)
    fees = await fetcher.fetch(product)

    assert fees.fba_fee == 4.20
    assert fees.referral_fee == 2.10
    sp.get_my_fees_estimate.assert_called_once_with(
        asin="B000TEST01", price=20.00
    )


@pytest.mark.asyncio
async def test_fee_fetcher_fails_closed_on_api_error():
    sp = AsyncMock()
    sp.get_my_fees_estimate = AsyncMock(side_effect=Exception("timeout"))
    product = _make_product()

    fetcher = FeeFetcher(sp)
    with pytest.raises(PipelineDropError) as exc_info:
        await fetcher.fetch(product)
    assert "fail-closed" in exc_info.value.reason.lower()


@pytest.mark.asyncio
async def test_fee_fetcher_fails_on_empty_fees():
    """Si la API devuelve fees vacíos, debe lanzar PipelineDropError."""
    sp = AsyncMock()
    sp.get_my_fees_estimate = AsyncMock(return_value={
        "payload": {
            "FeesEstimateResult": {
                "FeesEstimate": {"FeeDetailList": []}
            }
        }
    })
    product = _make_product()

    fetcher = FeeFetcher(sp)
    with pytest.raises(PipelineDropError) as exc_info:
        await fetcher.fetch(product)
    assert "parsear fees" in exc_info.value.reason.lower()


# ══════════════════════════════════════════════════════════════════
#  BSR Validator
# ══════════════════════════════════════════════════════════════════

def test_bsr_top_pct_calculation():
    path = _make_category_file({"Electrónica": 1_000_000})
    validator = BSRValidator(path)

    top_pct = validator.get_top_pct(rank=10_000, category="Electrónica")
    assert top_pct == pytest.approx(1.0, abs=0.01)


def test_bsr_valid_within_threshold():
    path = _make_category_file({"Electrónica": 1_000_000})
    validator = BSRValidator(path)

    # top 1% → válido con umbral del 2%
    valid, top_pct = validator.is_valid(rank=10_000, category="Electrónica")
    assert valid is True
    assert top_pct == pytest.approx(1.0, abs=0.01)


def test_bsr_invalid_outside_threshold():
    path = _make_category_file({"Electrónica": 1_000_000})
    validator = BSRValidator(path)

    # top 5% → inválido con umbral del 2%
    valid, top_pct = validator.is_valid(rank=50_000, category="Electrónica")
    assert valid is False
    assert top_pct == pytest.approx(5.0, abs=0.01)


def test_bsr_uses_fallback_for_unknown_category():
    path = _make_category_file({"Electrónica": 1_000_000})
    validator = BSRValidator(path)

    # Categoría desconocida → usa fallback 500_000
    valid, top_pct = validator.is_valid(rank=5_000, category="CategoríaNueva")
    # 5000/500000 = 1.0% → válido
    assert valid is True


# ══════════════════════════════════════════════════════════════════
#  FinancialCalculator — fórmula
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_calculator_passes_with_good_roi_and_bsr():
    """
    Buy=10, BB=20, FBA=3.50, Referral=1.80, Prep=0.50
    Net = 20 - (10 + 3.50 + 1.80 + 0.50) = 4.20
    ROI = (4.20 / 10) * 100 = 42% ✓
    BSR = 5000 / 850000 = 0.59% → top 2% ✓
    """
    sp = AsyncMock()
    sp.get_my_fees_estimate = AsyncMock(
        return_value=_make_fees_response(fba=3.50, referral=1.80)
    )
    path = _make_category_file({"Electrónica": 850_000})

    calc = FinancialCalculator(sp)
    calc._bsr_validator = BSRValidator(path)

    product = _make_product(
        buy_price=10.0,
        buybox_price=20.0,
        sales_ranks=[{"rank": 5_000, "category": "Electrónica"}],
    )
    result = await calc.evaluate(product)

    assert isinstance(result, FinancialResult)
    assert result.net_profit == pytest.approx(4.20, abs=0.01)
    assert result.roi_pct == pytest.approx(42.0, abs=0.1)
    assert result.bsr_top_pct == pytest.approx(0.59, abs=0.1)


@pytest.mark.asyncio
async def test_calculator_drops_on_low_roi():
    """
    Buy=10, BB=12, FBA=3.50, Referral=1.00, Prep=0.50
    Net = 12 - (10 + 3.50 + 1.00 + 0.50) = -3.00
    ROI = -30% ✗
    """
    sp = AsyncMock()
    sp.get_my_fees_estimate = AsyncMock(
        return_value=_make_fees_response(fba=3.50, referral=1.00)
    )
    path = _make_category_file({"Electrónica": 850_000})

    calc = FinancialCalculator(sp)
    calc._bsr_validator = BSRValidator(path)

    product = _make_product(
        buy_price=10.0,
        buybox_price=12.0,
        sales_ranks=[{"rank": 5_000, "category": "Electrónica"}],
    )
    result = await calc.evaluate(product)

    assert isinstance(result, FinancialDropReason)
    assert result.reason == "ROI_TOO_LOW"
    assert result.roi_pct < 0


@pytest.mark.asyncio
async def test_calculator_drops_on_bad_bsr():
    """
    ROI correcto pero BSR fuera del top 2%.
    rank=200_000 / 850_000 = 23.5% → fuera
    """
    sp = AsyncMock()
    sp.get_my_fees_estimate = AsyncMock(
        return_value=_make_fees_response(fba=2.00, referral=1.00)
    )
    path = _make_category_file({"Electrónica": 850_000})

    calc = FinancialCalculator(sp)
    calc._bsr_validator = BSRValidator(path)

    product = _make_product(
        buy_price=10.0,
        buybox_price=25.0,
        sales_ranks=[{"rank": 200_000, "category": "Electrónica"}],
    )
    result = await calc.evaluate(product)

    assert isinstance(result, FinancialDropReason)
    assert result.reason == "BSR_TOO_HIGH"


@pytest.mark.asyncio
async def test_calculator_drops_both_conditions():
    sp = AsyncMock()
    sp.get_my_fees_estimate = AsyncMock(
        return_value=_make_fees_response(fba=5.00, referral=2.00)
    )
    path = _make_category_file({"Electrónica": 850_000})

    calc = FinancialCalculator(sp)
    calc._bsr_validator = BSRValidator(path)

    product = _make_product(
        buy_price=10.0,
        buybox_price=11.0,    # ROI negativo
        sales_ranks=[{"rank": 500_000, "category": "Electrónica"}],  # BSR pésimo
    )
    result = await calc.evaluate(product)

    assert isinstance(result, FinancialDropReason)
    assert result.reason == "BOTH_ROI_TOO_LOW_AND_BSR_TOO_HIGH"


@pytest.mark.asyncio
async def test_calculator_handles_missing_bsr():
    """Sin datos de BSR → rank 999999 → DROP por BSR."""
    sp = AsyncMock()
    sp.get_my_fees_estimate = AsyncMock(
        return_value=_make_fees_response(fba=2.00, referral=1.00)
    )
    path = _make_category_file({"Electrónica": 850_000})

    calc = FinancialCalculator(sp)
    calc._bsr_validator = BSRValidator(path)

    product = _make_product(
        buy_price=10.0,
        buybox_price=25.0,
        sales_ranks=[],      # sin BSR
    )
    result = await calc.evaluate(product)

    assert isinstance(result, FinancialDropReason)
    assert "BSR" in result.reason


@pytest.mark.asyncio
async def test_calculator_selects_best_bsr_from_multiple_categories():
    """Con varios BSR, debe usar el de menor rank (categoría principal)."""
    sp = AsyncMock()
    sp.get_my_fees_estimate = AsyncMock(
        return_value=_make_fees_response(fba=2.00, referral=1.00)
    )
    path = _make_category_file({
        "Electrónica": 850_000,
        "Hogar y cocina": 1_200_000,
    })

    calc = FinancialCalculator(sp)
    calc._bsr_validator = BSRValidator(path)

    product = _make_product(
        buy_price=10.0,
        buybox_price=25.0,
        sales_ranks=[
            {"rank": 4_000,  "category": "Electrónica"},     # top 0.47% ✓
            {"rank": 300_000, "category": "Hogar y cocina"},  # top 25% ✗
        ],
    )
    result = await calc.evaluate(product)

    # Debe elegir Electrónica (rank 4000) como categoría principal
    assert isinstance(result, FinancialResult)
    assert result.bsr_category == "Electrónica"
    assert result.bsr_rank == 4_000