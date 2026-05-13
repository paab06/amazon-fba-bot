# tests/conftest.py
"""
Fixtures compartidos entre todos los módulos de test.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


# ── Redis mock ─────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get    = AsyncMock(return_value=None)
    redis.setex  = AsyncMock(return_value=True)
    redis.close  = AsyncMock()
    return redis


# ── SP-API client mock ─────────────────────────────────────────────

@pytest.fixture
def mock_sp_client():
    return AsyncMock()


# ── Keepa client mock ──────────────────────────────────────────────

@pytest.fixture
def mock_keepa_client():
    keepa = AsyncMock()
    keepa.get_fba_seller_history = AsyncMock(return_value=[])
    return keepa


# ── Archivos de datos temporales ───────────────────────────────────

@pytest.fixture
def blacklist_path():
    """Blacklist vacía por defecto — sobreescribir en tests que la necesiten."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump([], tmp)
    tmp.close()
    return Path(tmp.name)


@pytest.fixture
def category_sizes_path():
    sizes = {
        "Electrónica": 850_000,
        "Hogar y cocina": 1_200_000,
        "Deportes y aire libre": 600_000,
        "Unknown": 500_000,
    }
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(sizes, tmp)
    tmp.close()
    return Path(tmp.name)


# ── ProductInput de ejemplo ────────────────────────────────────────

@pytest.fixture
def sample_product_input():
    from src.pipeline.ingestor import ProductInput
    return ProductInput(ean="5901234123457", buy_price=12.50, source_row=2)


# ── ResolvedProduct de ejemplo ─────────────────────────────────────

@pytest.fixture
def sample_resolved_product():
    from src.pipeline.ean_resolver import ResolvedProduct
    return ResolvedProduct(
        ean="5901234123457",
        asin="B000TEST01",
        buy_price=12.50,
        title="Producto de prueba",
        brand="SafeBrand",
        sales_ranks=[{"rank": 5_000, "category": "Electrónica"}],
        source_row=2,
    )


# ── EnrichedProduct de ejemplo ─────────────────────────────────────

@pytest.fixture
def sample_enriched_product():
    from src.pipeline.shields import EnrichedProduct
    return EnrichedProduct(
        ean="5901234123457",
        asin="B000TEST01",
        buy_price=12.50,
        title="Producto de prueba",
        brand="SafeBrand",
        sales_ranks=[{"rank": 5_000, "category": "Electrónica"}],
        source_row=2,
        buybox_price=25.00,
        buybox_seller_name="DistribuidorSL",
        buybox_is_fba=True,
        fba_fee=3.50,
        referral_fee=1.80,
    )