# src/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr


class Settings(BaseSettings):
    """
    Todas las variables de entorno validadas y tipadas.
    Carga automáticamente desde .env en la raíz del proyecto.
    """
    model_config = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",       # ← añadir esta línea
)

    # ── SP-API credentials ─────────────────────────────────────────
    sp_api_refresh_token: SecretStr = Field(..., description="LWA Refresh Token")
    sp_api_client_id: SecretStr     = Field(..., description="LWA Client ID")
    sp_api_client_secret: SecretStr = Field(..., description="LWA Client Secret")
    sp_api_marketplace_id: str      = Field("A1RKKUPIHCS9HS", description="ES=A1RKKUPIHCS9HS")
    sp_api_region: str              = Field("eu-west-1")
    sp_api_endpoint: str            = Field("https://sellingpartnerapi-eu.amazon.com")
    sp_api_seller_id: str           = Field(..., description="Tu Seller ID de Amazon (ej: A1SELLER123XYZ)")

    # ── AWS credentials (para firmar peticiones SigV4) ─────────────
    aws_access_key_id: SecretStr     = Field(...)
    aws_secret_access_key: SecretStr = Field(...)
    aws_role_arn: str                = Field(..., description="IAM Role ARN con permisos SP-API")

    # ── Keepa ──────────────────────────────────────────────────────
    keepa_api_key: SecretStr = Field(...)

    # ── Base de datos ──────────────────────────────────────────────
    database_url: str = Field("postgresql+asyncpg://user:pass@localhost:5432/fba_bot")

    # ── Redis ──────────────────────────────────────────────────────
    redis_url: str = Field("redis://localhost:6379/0")

    # ── Pipeline ──────────────────────────────────────────────────
    min_roi_pct: float        = Field(20.0)
    bsr_top_pct: float        = Field(2.0)
    prep_shipping_fixed: float = Field(0.50)
    pipeline_concurrency: int  = Field(10, description="Workers simultáneos")

    # ── Google Sheets ──────────────────────────────────────────────
    google_sheets_id: str              = Field("")
    google_credentials_json_path: str  = Field("credentials/google_service_account.json")


# Singleton — importar desde aquí en todos los módulos
settings = Settings()