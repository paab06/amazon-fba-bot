# tests/test_sp_api_client.py
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from src.api.sp_api_client import LWATokenManager, SPAPIClient
from src.core.exceptions import SPAPIAuthError, SPAPIRateLimitError


@pytest.mark.asyncio
async def test_lwa_token_refresh_success():
    mock_session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "access_token": "Atza|test_token",
        "expires_in": 3600,
    })
    mock_session.post = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))

    manager = LWATokenManager()
    token = await manager.get_token(mock_session)

    assert token == "Atza|test_token"
    assert manager._is_valid()


@pytest.mark.asyncio
async def test_lwa_token_refresh_failure():
    mock_session = MagicMock()
    mock_resp = AsyncMock()
    mock_resp.status = 400
    mock_resp.text = AsyncMock(return_value='{"error":"invalid_grant"}')
    mock_session.post = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))

    manager = LWATokenManager()
    with pytest.raises(SPAPIAuthError, match="LWA token refresh failed"):
        await manager.get_token(mock_session)


@pytest.mark.asyncio
async def test_rate_limiter_throttles():
    from src.core.rate_limiter import RateLimiter
    import time

    limiter = RateLimiter(rate=10.0, burst=2, name="test")
    start = time.monotonic()
    # Consumimos el burst (2 tokens gratis) + 1 más que debe esperar ~0.1 s
    for _ in range(3):
        await limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.08  # al menos 80 ms de espera