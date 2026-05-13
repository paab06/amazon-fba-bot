# tests/test_ean_resolver.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.pipeline.ean_resolver import EANResolver, ResolvedProduct
from src.pipeline.ingestor import ProductInput
from src.core.exceptions import SPAPINotFoundError

# ── Fixtures ───────────────────────────────────────────────────────

def _make_api_response(asins: list[dict]) -> dict:
    """Construye una respuesta fake de Catalog Items API."""
    items = []
    for a in asins:
        items.append({
            "asin": a["asin"],
            "summaries": [{"itemName": a["title"], "brand": a["brand"]}],
            "salesRanks": [
                {"rank": a["rank"], "displayGroupRanks": [{"title": a["cat"]}]}
            ],
        })
    return {"items": items}


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)   # cache miss por defecto
    redis.setex = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_sp_client():
    return AsyncMock()


@pytest.fixture
def resolver(mock_sp_client, mock_redis):
    return EANResolver(sp_client=mock_sp_client, redis=mock_redis)


@pytest.fixture
def product_input():
    return ProductInput(ean="5901234123457", buy_price=12.50, source_row=2)


# ── Tests ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_single_asin(resolver, mock_sp_client, product_input):
    mock_sp_client.search_catalog_by_ean.return_value = _make_api_response([
        {"asin": "B08N5WRWNW", "title": "Test Product", "brand": "TestBrand",
         "rank": 1500, "cat": "Electrónica"}
    ])

    result = await resolver.resolve(product_input)

    assert isinstance(result, ResolvedProduct)
    assert result.asin == "B08N5WRWNW"
    assert result.brand == "TestBrand"
    assert result.buy_price == 12.50
    assert result.sales_ranks[0]["rank"] == 1500


@pytest.mark.asyncio
async def test_resolve_picks_best_bsr_on_multi_asin(resolver, mock_sp_client, product_input):
    """Con dos ASINs para el mismo EAN, elige el de menor BSR."""
    mock_sp_client.search_catalog_by_ean.return_value = _make_api_response([
        {"asin": "B000001", "title": "Pack 6u", "brand": "Brand",
         "rank": 80_000, "cat": "Hogar"},
        {"asin": "B000002", "title": "Unidad", "brand": "Brand",
         "rank": 1_200, "cat": "Hogar"},
    ])

    result = await resolver.resolve(product_input)

    assert result is not None
    assert result.asin == "B000002"   # el de menor rank


@pytest.mark.asyncio
async def test_resolve_returns_none_on_not_found(resolver, mock_sp_client, product_input):
    mock_sp_client.search_catalog_by_ean.side_effect = SPAPINotFoundError("404")

    result = await resolver.resolve(product_input)

    assert result is None


@pytest.mark.asyncio
async def test_resolve_uses_cache(resolver, mock_redis, mock_sp_client, product_input):
    """Si hay cache hit, no debe llamar a la SP-API."""
    import json
    mock_redis.get.return_value = json.dumps({
        "ean": "5901234123457",
        "asin": "B_CACHED",
        "title": "Cached Product",
        "brand": "CachedBrand",
        "sales_ranks": [{"rank": 500, "category": "Electrónica"}],
    })

    result = await resolver.resolve(product_input)

    assert result.asin == "B_CACHED"
    mock_sp_client.search_catalog_by_ean.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_fallback_if_redis_down(
    resolver, mock_redis, mock_sp_client, product_input
):
    """Si Redis lanza excepción, el resolver debe continuar hacia la API."""
    mock_redis.get.side_effect = ConnectionError("Redis down")
    mock_sp_client.search_catalog_by_ean.return_value = _make_api_response([
        {"asin": "B000003", "title": "Fallback Product", "brand": "FBrand",
         "rank": 3000, "cat": "Cocina"}
    ])

    result = await resolver.resolve(product_input)

    assert result is not None
    assert result.asin == "B000003"