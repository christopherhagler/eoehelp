"""Application settings, sourced entirely from the environment.

Secrets are injected by the platform (AWS Secrets Manager in deployed environments,
a local .env file in development) and never committed. See docs/adr/0003.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = "local"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://eoehelp:eoehelp@localhost:5432/eoehelp"
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # Signs access tokens. Rotating this invalidates every outstanding access token,
    # which is the intended emergency lever; refresh tokens are DB-backed and survive.
    jwt_secret: SecretStr = SecretStr("dev-only-insecure-secret-do-not-use-in-production")
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900  # 15 min; held in memory by the SPA
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30
    magic_link_ttl_seconds: int = 900

    # Envelope-encrypts free-text clinical columns. Must be a 32-byte urlsafe-base64 key.
    # In AWS this is a KMS-backed data key; locally it is generated for the dev DB only.
    field_encryption_key: SecretStr = SecretStr("ZGV2LW9ubHktMzJieXRlLWtleS1mb3ItbG9jYWwh")

    app_base_url: str = "http://localhost:4200"
    api_base_url: str = "http://localhost:8000"

    smtp_host: str = "localhost"
    smtp_port: int = 1025  # Mailhog in local dev; SES SMTP in deployed environments
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = False
    email_from: str = "no-reply@eoehelp.org"

    # Packaged-food data, called from the server only. Open Food Facts asks every
    # client to identify itself with a contact; anonymous clients get throttled.
    food_data_user_agent: str = "eoehelp/{version} (https://eoehelp.org; security@eoehelp.org)"
    openfoodfacts_url: str = "https://world.openfoodfacts.org"
    openfoodfacts_search_url: str = "https://search.openfoodfacts.org"
    usda_fdc_url: str = "https://api.nal.usda.gov/fdc/v1"
    # DEMO_KEY allows about 30 requests an hour: enough to develop against, not to
    # run on. Production refuses to start with it.
    usda_fdc_api_key: SecretStr = SecretStr("DEMO_KEY")
    food_data_timeout_seconds: float = 6.0
    # Launch is US-only, so search prefers products sold there.
    food_data_country: str = "en:united-states"

    # NoDecode: pydantic-settings would otherwise JSON-parse a list-typed env var
    # before validators run, so a plain comma-separated value fails at startup.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:4200"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, v: str) -> str:
        # The sync driver fails deep inside SQLAlchemy with a confusing error;
        # catching it at startup is much cheaper to diagnose.
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use the postgresql+asyncpg driver")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def enforce_production_safety(self) -> None:
        """Fail fast rather than boot production with development defaults.

        A dev JWT secret in production is a total authentication bypass, so this
        refuses to start instead of logging a warning nobody reads.
        """
        if not self.is_production:
            return
        insecure = []
        if "dev-only" in self.jwt_secret.get_secret_value():
            insecure.append("jwt_secret")
        if "dev-only" in self.field_encryption_key.get_secret_value():
            insecure.append("field_encryption_key")
        if self.debug:
            insecure.append("debug")
        if self.usda_fdc_api_key.get_secret_value() == "DEMO_KEY":
            insecure.append("usda_fdc_api_key")
        if insecure:
            raise RuntimeError(
                f"Refusing to start in production with insecure settings: {', '.join(insecure)}"
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.enforce_production_safety()
    return settings
