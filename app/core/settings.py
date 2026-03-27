from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


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

    # Providers
    provider: str = Field(default="stub", validation_alias=AliasChoices("PRIMARY_PROVIDER", "PROVIDER", "provider"))
    fallback_provider: str | None = Field(default=None, validation_alias=AliasChoices("FALLBACK_PROVIDER", "fallback_provider"))
    provider_timeout_s: float = 30.0

    stub_provider_mode: str = "ok"
    stub_simulated_latency_ms: int = 0

    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_max_attempts: int = 3
    openai_backoff_base_ms: int = 200
    openai_backoff_max_ms: int = 2000

    bedrock_region: str | None = None
    bedrock_model: str | None = None
    bedrock_prompt_version: str = "v1"
    bedrock_max_attempts: int = 3
    bedrock_backoff_base_ms: int = 200
    bedrock_backoff_max_ms: int = 2000

    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    # Defensive limits (hardening)
    max_request_bytes: int = 64 * 1024
    max_message_chars: int = 8_000
    max_assistant_chars: int = 8_000
    max_error_message_chars: int = 512

    # Cost Awareness (MVP): provider-agnostic token pricing table (no external calls).
    # Unknown providers should be treated as 0.0 cost by the estimator.
    cost_rates_by_provider: dict[str, TokenRates] = {
        "stub": TokenRates(input_per_1k=0.0, output_per_1k=0.0),
    }

    @field_validator("provider", "fallback_provider")
    @classmethod
    def validate_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"stub", "openai", "bedrock"}
        if value not in allowed:
            raise ValueError(f"provider must be one of: {sorted(allowed)}")
        return value

    @field_validator("provider_timeout_s")
    @classmethod
    def validate_provider_timeout_s(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("provider_timeout_s must be > 0")
        return value

    @field_validator("stub_provider_mode")
    @classmethod
    def validate_stub_provider_mode(cls, value: str) -> str:
        allowed = {"ok", "error"}
        if value not in allowed:
            raise ValueError(f"stub_provider_mode must be one of: {sorted(allowed)}")
        return value

    @field_validator("stub_simulated_latency_ms")
    @classmethod
    def validate_stub_simulated_latency_ms(cls, value: int) -> int:
        if value < 0:
            raise ValueError("stub_simulated_latency_ms must be >= 0")
        return value

    @field_validator("openai_max_attempts", "bedrock_max_attempts")
    @classmethod
    def validate_provider_max_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("provider max attempts must be >= 1")
        return value

    @field_validator("openai_backoff_base_ms", "bedrock_backoff_base_ms")
    @classmethod
    def validate_provider_backoff_base_ms(cls, value: int) -> int:
        if value < 0:
            raise ValueError("provider backoff base ms must be >= 0")
        return value

    @field_validator("openai_backoff_max_ms", "bedrock_backoff_max_ms")
    @classmethod
    def validate_provider_backoff_max_ms(cls, value: int) -> int:
        if value < 0:
            raise ValueError("provider backoff max ms must be >= 0")
        return value

    @field_validator("max_request_bytes", "max_message_chars", "max_assistant_chars", "max_error_message_chars")
    @classmethod
    def validate_positive_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("limit values must be > 0")
        return value

    @model_validator(mode="after")
    def validate_backoff_relationship(self) -> "Settings":
        if self.openai_backoff_max_ms < self.openai_backoff_base_ms:
            raise ValueError("openai_backoff_max_ms must be >= openai_backoff_base_ms")
        if self.bedrock_backoff_max_ms < self.bedrock_backoff_base_ms:
            raise ValueError("bedrock_backoff_max_ms must be >= bedrock_backoff_base_ms")
        return self

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


settings = Settings()
