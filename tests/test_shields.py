# tests/test_shields.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.pipeline.shields import (
    BrandBlacklistShield,
    PrivateLabelShield,
    AmazonBuyBoxShield,
    KeepaFBAMassacreShield,
    GatingShield,
    ShieldChain,
    EnrichedProduct,
)
from src.core.exceptions import PipelineDropError
from src.pipeline.ean_resolver import ResolvedProduct
import json, tempfile
from pathlib import Path


# ── Helpers ────────────────────────────────────────────────────────

def _make_enriched(**kwargs) -> EnrichedProduct:
    defaults = dict(
        ean="1234567890123",
        asin="B000TEST01",
        buy_price=10.0,
        title="Test Product",
        brand="TestBrand",
        sales_ranks=[{"rank": 5000, "category": "Electrónica"}],
        source_row=2,
        buybox_price=25.0,
        buybox_seller_name="SomeThirdPartySeller",
        buybox_is_fba=True,
        fba_fee=3.50,
        referral_fee=1.80,
    )
    defaults.update(kwargs)
    return EnrichedProduct(**defaults)


def _make_blacklist_file(brands: list[str]) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(brands, tmp)
    tmp.close()
    return Path(tmp.name)


# ══════════════════════════════════════════════════════════════════
#  Escudo 1 — Blacklist
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_shield1_drops_blacklisted_brand():
    path = _make_blacklist_file(["Nike", "Apple", "Lego"])
    shield = BrandBlacklistShield(path)
    product = _make_enriched(brand="Nike")

    with pytest.raises(PipelineDropError) as exc_info:
        await shield.check(product)
    assert "blacklist" in exc_info.value.reason.lower()
    assert exc_info.value.shield == "shield_1_brand_blacklist"


@pytest.mark.asyncio
async def test_shield1_is_case_insensitive():
    path = _make_blacklist_file(["Nike"])
    shield = BrandBlacklistShield(path)
    product = _make_enriched(brand="NIKE")

    with pytest.raises(PipelineDropError):
        await shield.check(product)


@pytest.mark.asyncio
async def test_shield1_passes_clean_brand():
    path = _make_blacklist_file(["Nike", "Apple"])
    shield = BrandBlacklistShield(path)
    product = _make_enriched(brand="SomeSafeBrand")

    await shield.check(product)   # no debe lanzar


@pytest.mark.asyncio
async def test_shield1_handles_missing_file():
    shield = BrandBlacklistShield("/nonexistent/path.json")
    product = _make_enriched(brand="Nike")

    # Sin blacklist, ninguna marca debe bloquearse
    await shield.check(product)


# ══════════════════════════════════════════════════════════════════
#  Escudo 2 — Marca privada
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_shield2_drops_private_label():
    shield = PrivateLabelShield()
    product = _make_enriched(brand="MarcaDirecta", buybox_seller_name="MarcaDirecta")

    with pytest.raises(PipelineDropError) as exc_info:
        await shield.check(product)
    assert "privada" in exc_info.value.reason.lower()


@pytest.mark.asyncio
async def test_shield2_passes_different_brand_seller():
    shield = PrivateLabelShield()
    product = _make_enriched(brand="Philips", buybox_seller_name="DistribuidorXYZ")

    await shield.check(product)


@pytest.mark.asyncio
async def test_shield2_fails_closed_on_empty_seller():
    shield = PrivateLabelShield()
    product = _make_enriched(brand="SomeBrand", buybox_seller_name="")

    with pytest.raises(PipelineDropError) as exc_info:
        await shield.check(product)
    assert "fail-closed" in exc_info.value.reason.lower()


# ══════════════════════════════════════════════════════════════════
#  Escudo 3 — Amazon en Buy Box
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("seller", [
    "Amazon",
    "Amazon EU S.à r.l.",
    "Amazon.es",
    "Warehouse Deals",
])
async def test_shield3_drops_amazon_variants(seller):
    shield = AmazonBuyBoxShield()
    product = _make_enriched(buybox_seller_name=seller)

    with pytest.raises(PipelineDropError) as exc_info:
        await shield.check(product)
    assert "amazon" in exc_info.value.reason.lower()


@pytest.mark.asyncio
async def test_shield3_passes_third_party():
    shield = AmazonBuyBoxShield()
    product = _make_enriched(buybox_seller_name="MiTienda SL")

    await shield.check(product)


# ══════════════════════════════════════════════════════════════════
#  Escudo 4 — Keepa Massacre
# ══════════════════════════════════════════════════════════════════

def _make_keepa_series(entries: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return entries


@pytest.mark.asyncio
async def test_shield4_detects_massacre():
    """Caída del 90% en un día → DROP."""
    import time
    now_min = int(time.time() / 60)
    series = [
        (now_min - 100, 50),   # 50 vendedores
        (now_min - 50,  5),    # → 5 vendedores en < 1 día (caída 90%)
    ]
    keepa = AsyncMock()
    keepa.get_fba_seller_history = AsyncMock(return_value=series)
    shield = KeepaFBAMassacreShield(keepa)
    product = _make_enriched()

    with pytest.raises(PipelineDropError) as exc_info:
        await shield.check(product)
    assert "masacre" in exc_info.value.reason.lower()


@pytest.mark.asyncio
async def test_shield4_passes_gradual_decline():
    """Caída gradual a lo largo de semanas → PASS."""
    import time
    now_min = int(time.time() / 60)
    day = 1440
    series = [
        (now_min - 60 * day, 50),
        (now_min - 45 * day, 40),
        (now_min - 30 * day, 32),
        (now_min - 15 * day, 28),
        (now_min - 1  * day, 24),
    ]
    keepa = AsyncMock()
    keepa.get_fba_seller_history = AsyncMock(return_value=series)
    shield = KeepaFBAMassacreShield(keepa)
    product = _make_enriched()

    await shield.check(product)


@pytest.mark.asyncio
async def test_shield4_fails_closed_on_keepa_error():
    keepa = AsyncMock()
    keepa.get_fba_seller_history = AsyncMock(
        side_effect=Exception("Keepa timeout")
    )
    shield = KeepaFBAMassacreShield(keepa)
    product = _make_enriched()

    with pytest.raises(PipelineDropError) as exc_info:
        await shield.check(product)
    assert "fail-closed" in exc_info.value.reason.lower()


# ══════════════════════════════════════════════════════════════════
#  Escudo 5 — Gating
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_shield5_passes_unrestricted_asin():
    sp = AsyncMock()
    sp.get_listings_restrictions = AsyncMock(return_value={"restrictions": []})
    shield = GatingShield(sp, seller_id="A1SELLER123")
    product = _make_enriched()

    await shield.check(product)


@pytest.mark.asyncio
async def test_shield5_drops_restricted_asin():
    sp = AsyncMock()
    sp.get_listings_restrictions = AsyncMock(return_value={
        "restrictions": [{
            "reasons": [{"reasonCode": "APPROVAL_REQUIRED",
                         "message": "Requiere factura del fabricante"}]
        }]
    })
    shield = GatingShield(sp, seller_id="A1SELLER123")
    product = _make_enriched()

    with pytest.raises(PipelineDropError) as exc_info:
        await shield.check(product)
    assert "APPROVAL_REQUIRED" in exc_info.value.reason


@pytest.mark.asyncio
async def test_shield5_fails_closed_on_api_error():
    sp = AsyncMock()
    sp.get_listings_restrictions = AsyncMock(
        side_effect=Exception("SP-API timeout")
    )
    shield = GatingShield(sp, seller_id="A1SELLER123")
    product = _make_enriched()

    with pytest.raises(PipelineDropError) as exc_info:
        await shield.check(product)
    assert "fail-closed" in exc_info.value.reason.lower()


# ══════════════════════════════════════════════════════════════════
#  ShieldChain — integración
# ══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_chain_stops_at_first_drop():
    """El chain debe parar en el primer escudo que falla."""
    path = _make_blacklist_file(["BlockedBrand"])

    sp = AsyncMock()
    # El enriquecimiento devuelve datos válidos
    sp.get_item_offers = AsyncMock(return_value={
        "payload": {
            "Summary": {"BuyBoxPrices": [{"LandedPrice": {"Amount": 25.0}}]},
            "Offers": [{
                "IsBuyBoxWinner": True,
                "SellerFeedbackRating": {"SellerDisplayName": "ThirdPartySeller"},
                "IsFulfilledByAmazon": True,
            }],
        }
    })
    keepa = AsyncMock()
    keepa.get_fba_seller_history = AsyncMock(return_value=[])

    chain = ShieldChain(
        sp_client=sp,
        keepa_client=keepa,
        seller_id="A1SELLER",
        blacklist_path=path,
    )

    resolved = ResolvedProduct(
        ean="123", asin="B000X", buy_price=10.0,
        title="Test", brand="BlockedBrand",
        sales_ranks=[], source_row=1,
    )

    result = await chain.run(resolved)

    assert result.passed is False
    assert result.drop_shield == "shield_1_brand_blacklist"
    # Keepa y Gating no deben haberse llamado
    keepa.get_fba_seller_history.assert_not_called()
    sp.get_listings_restrictions.assert_not_called()


@pytest.mark.asyncio
async def test_chain_full_pass():
    """Producto limpio que pasa los 5 escudos."""
    path = _make_blacklist_file(["Nike"])

    sp = AsyncMock()
    sp.get_item_offers = AsyncMock(return_value={
        "payload": {
            "Summary": {"BuyBoxPrices": [{"LandedPrice": {"Amount": 30.0}}]},
            "Offers": [{
                "IsBuyBoxWinner": True,
                "SellerFeedbackRating": {"SellerDisplayName": "DistribuidorSL"},
                "IsFulfilledByAmazon": True,
            }],
        }
    })
    sp.get_listings_restrictions = AsyncMock(return_value={"restrictions": []})

    keepa = AsyncMock()
    keepa.get_fba_seller_history = AsyncMock(return_value=[])

    chain = ShieldChain(
        sp_client=sp,
        keepa_client=keepa,
        seller_id="A1SELLER",
        blacklist_path=path,
    )

    resolved = ResolvedProduct(
        ean="123", asin="B000CLEAN", buy_price=10.0,
        title="Clean Product", brand="SafeBrand",
        sales_ranks=[{"rank": 1000, "category": "Hogar"}],
        source_row=1,
    )

    result = await chain.run(resolved)

    assert result.passed is True
    assert result.product is not None
    assert result.product.asin == "B000CLEAN"
    assert result.product.buybox_price == 30.0