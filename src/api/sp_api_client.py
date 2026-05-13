# src/api/sp_api_client.py
"""
SP-API Client — Módulo 1
Responsabilidades:
  - Obtener y refrescar tokens LWA (Login with Amazon) de forma automática
  - Firmar cada request con AWS Signature Version 4 (SigV4)
  - Rate limiting por endpoint (Throttle Budgets SP-API)
  - Retry con backoff exponencial (tenacity)
  - Métodos de negocio: get_item_offers, get_competitive_pricing,
    check_restrictions, get_my_fees_estimate
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from src.core.config import settings
from src.core.exceptions import (
    SPAPIAuthError,
    SPAPIRateLimitError,
    SPAPINotFoundError,
    SPAPIServerError,
)
from src.core.rate_limiter import RateLimiter

log = structlog.get_logger(__name__)

# ── Throttle budgets (burst / restore rate) según docs SP-API ─────
# https://developer-docs.amazon.com/sp-api/docs/usage-plans-and-rate-limits
_RATE_LIMITS: dict[str, tuple[int, float]] = {
    "getItemOffers":           (5, 0.1),   # burst=5, 1 req / 10 s
    "getCompetitivePricing":   (5, 0.1),
    "getListingsRestrictions": (5, 0.5),   # burst=5, 1 req / 2 s
    "getMyFeesEstimate":       (1, 0.1),   # 1 burst, 1 req / 10 s
    "searchCatalogItems":      (5, 1.0),   # 1 rps
    "default":                 (2, 0.5),
}


class LWATokenManager:
    """
    Gestiona el ciclo de vida del Access Token de LWA.
    - Thread-safe gracias a asyncio.Lock
    - Refresca el token 60 s antes de que expire
    """

    LWA_ENDPOINT = "https://api.amazon.com/auth/o2/token"
    # Margen de seguridad antes del vencimiento (segundos)
    REFRESH_BUFFER = 60

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self, session: aiohttp.ClientSession) -> str:
        """Devuelve un token válido, refrescando si es necesario."""
        async with self._lock:
            if self._is_valid():
                return self._access_token  # type: ignore[return-value]
            await self._refresh(session)
            return self._access_token  # type: ignore[return-value]

    def _is_valid(self) -> bool:
        return (
            self._access_token is not None
            and time.monotonic() < self._expires_at - self.REFRESH_BUFFER
        )

    async def _refresh(self, session: aiohttp.ClientSession) -> None:
        log.info("lwa.token.refresh", reason="expired_or_first_call")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": settings.sp_api_refresh_token.get_secret_value(),
            "client_id": settings.sp_api_client_id.get_secret_value(),
            "client_secret": settings.sp_api_client_secret.get_secret_value(),
        }
        async with session.post(self.LWA_ENDPOINT, data=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise SPAPIAuthError(
                    f"LWA token refresh failed [{resp.status}]: {body}"
                )
            data = await resp.json()

        self._access_token = data["access_token"]
        expires_in: int = data.get("expires_in", 3600)
        self._expires_at = time.monotonic() + expires_in
        log.info("lwa.token.refreshed", expires_in=expires_in)


class SigV4Signer:
    """
    Firma HTTP requests con AWS Signature Version 4.
    Solo depende de stdlib — sin boto3 en el hot path.
    """

    ALGORITHM = "AWS4-HMAC-SHA256"
    SERVICE = "execute-api"

    def __init__(self) -> None:
        self._ak = settings.aws_access_key_id.get_secret_value()
        self._sk = settings.aws_secret_access_key.get_secret_value()
        self._region = settings.sp_api_region

    def sign(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes = b"",
    ) -> dict[str, str]:
        """
        Añade los headers Authorization, x-amz-date y x-amz-security-token.
        Devuelve el dict de headers completo y firmado.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")

        # ── Canonical request ──────────────────────────────────────
        canonical_uri = quote(parsed.path or "/", safe="/-_.~")
        canonical_qs = self._canonical_query(parsed.query)
        headers["x-amz-date"] = amz_date
        payload_hash = hashlib.sha256(body).hexdigest()
        headers["x-amz-content-sha256"] = payload_hash

        signed_headers_keys = sorted(k.lower() for k in headers)
        canonical_headers = "".join(
            f"{k}:{headers[k]}\n"
            for k in sorted(headers, key=str.lower)
        )
        signed_headers_str = ";".join(signed_headers_keys)

        canonical_request = "\n".join([
            method.upper(),
            canonical_uri,
            canonical_qs,
            canonical_headers,
            signed_headers_str,
            payload_hash,
        ])

        # ── String to sign ─────────────────────────────────────────
        credential_scope = f"{date_stamp}/{self._region}/{self.SERVICE}/aws4_request"
        string_to_sign = "\n".join([
            self.ALGORITHM,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ])

        # ── Signing key ────────────────────────────────────────────
        signing_key = self._make_signing_key(date_stamp)
        signature = hmac.new(
            signing_key,
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()

        # ── Authorization header ───────────────────────────────────
        headers["Authorization"] = (
            f"{self.ALGORITHM} "
            f"Credential={self._ak}/{credential_scope}, "
            f"SignedHeaders={signed_headers_str}, "
            f"Signature={signature}"
        )
        return headers

    @staticmethod
    def _canonical_query(query: str) -> str:
        if not query:
            return ""
        params = sorted(
            (k, v)
            for part in query.split("&")
            for k, _, v in [part.partition("=")]
        )
        return "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in params)

    def _make_signing_key(self, date_stamp: str) -> bytes:
        def _sign(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode(), hashlib.sha256).digest()

        return _sign(
            _sign(
                _sign(
                    _sign(f"AWS4{self._sk}".encode(), date_stamp),
                    self._region,
                ),
                self.SERVICE,
            ),
            "aws4_request",
        )


class SPAPIClient:
    """
    Cliente principal de SP-API.

    Uso:
        async with SPAPIClient() as client:
            offers = await client.get_item_offers("B08N5WRWNW", "New")
    """

    BASE_URL = settings.sp_api_endpoint
    MARKETPLACE_ID = settings.sp_api_marketplace_id

    def __init__(self) -> None:
        self._token_manager = LWATokenManager()
        self._signer = SigV4Signer()
        self._rate_limiters: dict[str, RateLimiter] = {}
        self._session: aiohttp.ClientSession | None = None

    # ── Context manager ────────────────────────────────────────────

    async def __aenter__(self) -> "SPAPIClient":
        connector = aiohttp.TCPConnector(
            limit=20,
            ttl_dns_cache=300,
            ssl=True,
        )
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()

    # ── Internal request machinery ─────────────────────────────────

    def _get_rate_limiter(self, operation: str) -> RateLimiter:
        if operation not in self._rate_limiters:
            burst, rate = _RATE_LIMITS.get(operation, _RATE_LIMITS["default"])
            self._rate_limiters[operation] = RateLimiter(
                rate=rate, burst=burst, name=operation
            )
        return self._rate_limiters[operation]

    @retry(
        retry=retry_if_exception_type((SPAPIRateLimitError, SPAPIServerError)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(log, "warning"),  # type: ignore[arg-type]
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        path: str,
        operation: str,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        """
        Método base con:
        - Rate limiting por operación
        - Firma SigV4 automática
        - Inyección del token LWA
        - Retry exponencial en 429 / 5xx
        - Logging estructurado de cada request
        """
        assert self._session, "Usar como context manager: async with SPAPIClient()"

        await self._get_rate_limiter(operation).acquire()

        token = await self._token_manager.get_token(self._session)
        url = f"{self.BASE_URL}{path}"
        if params:
            url += "?" + urlencode(params)

        body_bytes = json.dumps(body).encode() if body else b""
        headers: dict[str, str] = {
            "x-amz-access-token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "host": self.BASE_URL.replace("https://", ""),
        }
        headers = self._signer.sign(method, url, headers, body_bytes)

        log.debug(
            "sp_api.request",
            method=method,
            path=path,
            operation=operation,
            params=params,
        )

        async with self._session.request(
            method, url, headers=headers, data=body_bytes or None
        ) as resp:
            return await self._handle_response(resp, operation)

    @staticmethod
    async def _handle_response(
        resp: aiohttp.ClientResponse, operation: str
    ) -> dict:
        status = resp.status
        raw = await resp.text()

        log.debug("sp_api.response", status=status, operation=operation)

        if status == 200:
            return json.loads(raw)
        if status == 404:
            raise SPAPINotFoundError(f"[{operation}] 404: {raw}")
        if status == 429:
            retry_after = float(resp.headers.get("x-amzn-RateLimit-Limit", "1"))
            log.warning("sp_api.rate_limit", operation=operation, retry_after=retry_after)
            await asyncio.sleep(retry_after)
            raise SPAPIRateLimitError(f"[{operation}] 429 Too Many Requests")
        if status >= 500:
            raise SPAPIServerError(f"[{operation}] {status}: {raw}")
        # 4xx no recuperable
        raise SPAPIAuthError(f"[{operation}] {status}: {raw}")

    # ── Métodos de negocio ─────────────────────────────────────────

    async def get_item_offers(
        self, asin: str, item_condition: str = "New"
    ) -> dict:
        """
        Pricing API — obtiene ofertas activas para un ASIN.
        Devuelve Buy Box price, vendedor y condición.
        """
        return await self._request(
            "GET",
            f"/products/pricing/v0/items/{asin}/offers",
            operation="getItemOffers",
            params={
                "MarketplaceId": self.MARKETPLACE_ID,
                "ItemCondition": item_condition,
            },
        )

    async def get_competitive_pricing(self, asin: str) -> dict:
        """
        Competitive pricing — BSR por categoría incluido.
        """
        return await self._request(
            "GET",
            "/products/pricing/v0/competitivePrice",
            operation="getCompetitivePricing",
            params={
                "MarketplaceId": self.MARKETPLACE_ID,
                "Asins": asin,
            },
        )

    async def get_listings_restrictions(
        self, asin: str, seller_id: str, condition_type: str = "new_new"
    ) -> dict:
        """
        Escudo 5 — comprueba si mi cuenta puede vender ese ASIN en 'new'.
        """
        return await self._request(
            "GET",
            "/listings/2021-08-01/restrictions",
            operation="getListingsRestrictions",
            params={
                "asin": asin,
                "sellerId": seller_id,
                "marketplaceIds": self.MARKETPLACE_ID,
                "conditionType": condition_type,
            },
        )

    async def get_my_fees_estimate(
        self,
        asin: str,
        price: float,
        currency: str = "EUR",
    ) -> dict:
        """
        Fees API — FBA Fee + Referral Fee para un precio dado.
        """
        body = {
            "FeesEstimateRequest": {
                "MarketplaceId": self.MARKETPLACE_ID,
                "IsAmazonFulfilled": True,
                "PriceToEstimateFees": {
                    "ListingPrice": {"CurrencyCode": currency, "Amount": price},
                    "Shipping":     {"CurrencyCode": currency, "Amount": 0.0},
                },
            }
        }
        return await self._request(
            "POST",
            f"/products/fees/v0/items/{asin}/feesEstimate",
            operation="getMyFeesEstimate",
            body=body,
        )

    async def search_catalog_by_ean(self, ean: str) -> dict:
        """
        Catalog Items API v2022 — resuelve EAN → ASIN.
        """
        return await self._request(
            "GET",
            "/catalog/2022-04-01/items",
            operation="searchCatalogItems",
            params={
                "identifiers": ean,
                "identifiersType": "EAN",
                "marketplaceIds": self.MARKETPLACE_ID,
                "includedData": "identifiers,summaries,salesRanks",
            },
        )