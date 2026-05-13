# src/core/rate_limiter.py
"""
Token bucket rate limiter asíncrono.
Cada endpoint SP-API tiene su propio bucket aislado.
"""
import asyncio
import time
import structlog

log = structlog.get_logger(__name__)


class RateLimiter:
    """
    Token bucket: permite ráfagas cortas (burst) y luego
    se recupera a una tasa constante (rate tokens/segundo).
    """

    def __init__(self, rate: float, burst: int, name: str = "default") -> None:
        self.rate = rate        # tokens que se añaden por segundo
        self.burst = burst      # capacidad máxima del bucket
        self.name = name
        self._tokens: float = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return
            # Necesitamos esperar hasta tener suficientes tokens
            deficit = tokens - self._tokens
            wait = deficit / self.rate
            log.debug(
                "rate_limiter.wait",
                operation=self.name,
                wait_seconds=round(wait, 2),
            )
        await asyncio.sleep(wait)
        async with self._lock:
            self._refill()
            self._tokens = max(0.0, self._tokens - tokens)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            float(self.burst),
            self._tokens + elapsed * self.rate,
        )
        self._last_refill = now