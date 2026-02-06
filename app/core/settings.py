from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel, Field

class TokenRates(BaseModel):
    # Cost per 1K tokens, expressed in your chosen currency unit (e.g., USD).
    input_per_1k: float = 0.0
    output_per_1k: float = 0.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    app_env: str = "development"

    # Postgres
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "llmchat"
    postgres_user: str = "llmchat"
    postgres_password: str = "__CHANGEME__"

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # Defensive limits (hardening)
    MAX_REQUEST_BYTES: int = 64 * 1024          # 64 KiB
    MAX_MESSAGE_CHARS: int = 8_000
    MAX_ASSISTANT_CHARS: int = 8_000
    MAX_ERROR_MESSAGE_CHARS: int = 512
    PROVIDER_TIMEOUT_S: float = 12.0

    # Cost Awareness (MVP): provider-agnostic token pricing table (no external calls).
    # Unknown providers should be treated as 0.0 cost by the estimator.
    cost_rates_by_provider: dict[str, TokenRates] = {
        "stub": TokenRates(input_per_1k=0.0, output_per_1k=0.0),
    }

settings = Settings()
