# src/core/exceptions.py

class FBABotBaseError(Exception):
    """Raíz de todas las excepciones del bot."""

class SPAPIAuthError(FBABotBaseError):
    """Fallo de autenticación LWA o SigV4."""

class SPAPIRateLimitError(FBABotBaseError):
    """429 — backoff y reintentar."""

class SPAPINotFoundError(FBABotBaseError):
    """404 — ASIN no encontrado o no en este marketplace."""

class SPAPIServerError(FBABotBaseError):
    """5xx — error en el servidor de Amazon."""

class KeepaAPIError(FBABotBaseError):
    """Error genérico de Keepa."""

class PipelineDropError(FBABotBaseError):
    """El producto fue descartado por algún escudo."""
    def __init__(self, asin: str, shield: str, reason: str):
        self.asin = asin
        self.shield = shield
        self.reason = reason
        super().__init__(f"[DROP] ASIN={asin} Shield={shield}: {reason}")