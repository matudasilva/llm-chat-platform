from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
import json
import os
from typing import Annotated, Any

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
    routing_policy: str = "static"
    routing_shadow_policy: str | None = None
    routing_shadow_mode_enabled: bool = False
    routing_shadow_timeout_ms: int = 25
    routing_message_length_cheap_max: int = 80
    routing_estimated_tokens_smart_min: int = 120
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
    chat_response_cache_ttl_s: int = 60

    # Defensive limits (hardening)
    max_request_bytes: int = 64 * 1024
    max_message_chars: int = 8_000
    max_assistant_chars: int = 8_000
    max_error_message_chars: int = 512

    # Staging protection (security follow-up, not a formal ORQ): shared-secret
    # header gate for public staging deploys. Empty default disables the
    # guard entirely (safe for local/dev). No alias needed — pydantic-settings
    # already maps this field to env var STAGING_KEY by default.
    staging_key: str = Field(default="")

    # CORS (ORQ-19.6): comma-separated allowed origins for the frontend.
    # Unset or blank falls back to the local dev default — there is no
    # "block all origins" mode via this variable.
    # NoDecode: without it, pydantic-settings tries to JSON-decode this env var
    # before the comma-separated-string validator below ever runs, crashing
    # startup the first time CORS_ALLOW_ORIGINS is set as a real OS env var
    # (found in ORQ-20.4 — existing tests only exercised the constructor-kwarg
    # path, not the real EnvSettingsSource path).
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])

    # RAG corpus (ORQ-21 / ADR-006): inert defaults so the hermetic test suite
    # is unaffected unless a test explicitly opts in. No alias/fallback to
    # database_url — see validate_rag_app_database_url below.
    rag_enabled: bool = False
    database_url_app: str | None = Field(default=None, alias="DATABASE_URL_APP")
    rag_embedding_dimensions: int = 1536

    # Isolated reranking benchmark (ORQ-22). Backend toggles are all inert by
    # default; these fields do not wire reranking into the application.
    reranker_aws_region: str = Field(
        # us-west-2, not ca-central-1: this is the region ORQ-22's actual
        # quality benchmark ran against (docs/reranking_benchmark.md).
        # ca-central-1 was only the fastest region in ORQ-22's separate,
        # unpaced latency probe — a latency data point, not the evidence
        # this production default activates (ORQ-23 spec.md §Design
        # decisions 1).
        default="us-west-2",
        validation_alias=AliasChoices("AWS_RERANK_REGION", "RERANKER_AWS_REGION"),
    )
    reranker_aws_model: str = Field(
        default="amazon.rerank-v1:0",
        validation_alias=AliasChoices("AWS_RERANK_MODEL", "RERANKER_AWS_MODEL"),
    )
    # GCP Vertex reranker (production, ORQ-24): primary backend in
    # CascadingRerankerAdapter as of ORQ-24 spec.md §Design decisions 1 —
    # no longer benchmark-only despite sitting next to the reranking_benchmark_*
    # toggles above (ORQ-22 origin). Distinct comment block from those on
    # purpose (design-review observation, ORQ-24 round 1).
    reranker_gcp_project: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GCP_PROJECT_ID", "RERANKER_GCP_PROJECT"),
    )
    reranker_gcp_location: str = Field(
        default="global",
        validation_alias=AliasChoices("GCP_RERANK_LOCATION", "RERANKER_GCP_LOCATION"),
    )
    reranker_gcp_model: str = Field(
        default="semantic-ranker-default-004",
        validation_alias=AliasChoices("GCP_RERANK_MODEL", "RERANKER_GCP_MODEL"),
    )
    reranker_qwen_model_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("QWEN_MODEL_ID", "RERANKER_QWEN_MODEL_ID"),
    )
    reranker_qwen_device: str = Field(
        default="cuda",
        validation_alias=AliasChoices("QWEN_DEVICE", "RERANKER_QWEN_DEVICE"),
    )
    reranking_benchmark_gcp_enabled: bool = False
    reranking_benchmark_aws_enabled: bool = False
    reranking_benchmark_qwen_enabled: bool = False
    reranking_benchmark_gcp_call_budget: int = 0
    reranking_benchmark_aws_pacing_s: float = 15.0

    # Evaluation metric store (ORQ-26 / ADR-009 decision 5). The harness owns an
    # `evaluation` schema through its own idempotent DDL, never an Alembic
    # revision, under a role distinct from both rag_app and the superuser. Inert
    # by default; nothing in the application reads it. Follows the precedent the
    # reranking_benchmark_* fields above already set for experiment settings.
    evaluation_store_url: str | None = Field(default=None, alias="EVALUATION_STORE_URL")

    # Retrieval pipeline (ORQ-23): rewrite -> retrieve -> rerank -> evaluator.
    # Inert by default so the hermetic suite is unaffected unless a test
    # explicitly opts in (same convention as rag_enabled). Distinct from the
    # reranking_benchmark_* toggles above, which stay ORQ-22-only.
    retrieval_pipeline_enabled: bool = False
    # Minimum number of reranked candidates required to skip the lightweight
    # evaluator call -- a rank/count-based signal only (spec.md §Design
    # decisions 5: never relevance_score, which ORQ-22 found incomparable
    # across backends). Fewer reranked results than this triggers the
    # evaluator.
    retrieval_pipeline_min_reranked_results: int = 5

    # ORQ-25: chat augmentation is independent from the read-only retrieval
    # endpoint and the corpus rollout flag. Disabled by default.
    chat_rag_augmentation_enabled: bool = False
    chat_rag_retrieval_timeout_s: float = 30.0
    chat_rag_max_sources: int = 5
    chat_rag_max_source_chars: int = 4_000
    chat_rag_max_context_chars: int = 12_000

    # ORQ-38: bounds for the conversation history substrate. Inert in this
    # ORQ -- nothing consumes the assembler yet; ORQ-37 re-derives them against
    # the production model's token accounting.
    conversation_history_max_messages: int = 20
    conversation_history_max_chars: int = 12_000

    # Controlled Web Read (MVP): read-only, bounded external fetch surface.
    web_read_enabled: bool = True
    web_read_allow_http: bool = False
    web_read_allowed_domains: list[str] = []
    web_read_timeout_s: float = 5.0
    web_read_max_bytes: int = 32 * 1024
    web_read_max_chars: int = 4_000

    # Controlled Notion Read via MCP (MVP): read-only, bounded context fetch via external MCP server.
    notion_read_enabled: bool = False
    notion_mcp_enabled: bool = False
    notion_mcp_server_command: str = "notion-mcp-read"
    notion_mcp_server_args: list[str] = []
    notion_mcp_server_cwd: str | None = None
    notion_mcp_timeout_s: float = 10.0
    notion_allowed_page_ids: list[str] = []

    # Controlled Notion Write (MVP): allowlisted writes with static validation.
    notion_write_enabled: bool = False
    notion_api_token: str | None = None
    notion_api_base_url: str = "https://api.notion.com/v1"
    notion_api_version: str = "2026-03-11"
    notion_write_timeout_s: float = 10.0
    notion_allowed_database_ids: list[str] = []
    notion_editable_fields: dict[str, dict[str, Any]] = {}
    notion_database_templates: dict[str, dict[str, Any]] = {}

    # Cost Awareness (MVP): provider-agnostic token pricing table (no external calls).
    # Unknown providers should be treated as 0.0 cost by the estimator.
    cost_rates_by_provider: dict[str, TokenRates] = {
        "stub": TokenRates(input_per_1k=0.0, output_per_1k=0.0),
    }

    def __init__(self, **data: Any) -> None:
        data = dict(data)
        for field_name, alias in (
            ("provider", "PRIMARY_PROVIDER"),
            ("fallback_provider", "FALLBACK_PROVIDER"),
        ):
            if alias in data:
                data.pop(field_name, None)
        super().__init__(**data)

    @field_validator("provider", "fallback_provider")
    @classmethod
    def validate_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"stub", "openai", "bedrock"}
        if value not in allowed:
            raise ValueError(f"provider must be one of: {sorted(allowed)}")
        return value

    @field_validator("routing_policy")
    @classmethod
    def validate_routing_policy(cls, value: str) -> str:
        allowed = {"static", "heuristic"}
        if value not in allowed:
            raise ValueError(f"routing_policy must be one of: {sorted(allowed)}")
        return value

    @field_validator("routing_shadow_policy")
    @classmethod
    def validate_routing_shadow_policy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"static", "heuristic"}
        if value not in allowed:
            raise ValueError(f"routing_shadow_policy must be one of: {sorted(allowed)}")
        return value

    @field_validator("provider_timeout_s")
    @classmethod
    def validate_provider_timeout_s(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("provider_timeout_s must be > 0")
        return value

    @field_validator("chat_rag_retrieval_timeout_s")
    @classmethod
    def validate_chat_rag_timeout_s(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("chat_rag_retrieval_timeout_s must be > 0")
        return value

    @field_validator(
        "chat_rag_max_sources",
        "chat_rag_max_source_chars",
        "chat_rag_max_context_chars",
    )
    @classmethod
    def validate_chat_rag_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("chat RAG limits must be > 0")
        return value

    @field_validator(
        "conversation_history_max_messages",
        "conversation_history_max_chars",
    )
    @classmethod
    def validate_conversation_history_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("conversation history limits must be > 0")
        return value

    @field_validator("web_read_timeout_s")
    @classmethod
    def validate_web_read_timeout_s(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("web_read_timeout_s must be > 0")
        return value

    @field_validator("notion_mcp_timeout_s")
    @classmethod
    def validate_notion_mcp_timeout_s(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("notion_mcp_timeout_s must be > 0")
        return value

    @field_validator("notion_mcp_server_command")
    @classmethod
    def validate_notion_mcp_server_command(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("notion_mcp_server_command must not be empty")
        return value.strip()

    @field_validator("notion_allowed_page_ids", mode="before")
    @classmethod
    def validate_notion_allowed_page_ids(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            # Parse CSV, normalize IDs (remove dashes for comparison)
            parts = [item.strip().replace("-", "") for item in value.split(",")]
            return [item for item in parts if item]
        if isinstance(value, list):
            return [str(item).strip().replace("-", "") for item in value if str(item).strip()]
        raise ValueError("notion_allowed_page_ids must be a list or comma-separated string")

    @field_validator("notion_api_token")
    @classmethod
    def validate_notion_api_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("notion_api_base_url")
    @classmethod
    def validate_notion_api_base_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("notion_api_base_url must not be empty")
        return value.strip().rstrip("/")

    @field_validator("notion_api_version")
    @classmethod
    def validate_notion_api_version(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("notion_api_version must not be empty")
        return value.strip()

    @field_validator("notion_allowed_database_ids", mode="before")
    @classmethod
    def validate_notion_allowed_database_ids(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            parts = [item.strip().replace("-", "") for item in value.split(",")]
            return [item for item in parts if item]
        if isinstance(value, list):
            return [str(item).strip().replace("-", "") for item in value if str(item).strip()]
        raise ValueError("notion_allowed_database_ids must be a list or comma-separated string")

    @field_validator("notion_editable_fields", "notion_database_templates", mode="before")
    @classmethod
    def validate_notion_mappings(cls, value):
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return {}
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                raise ValueError("mapping fields must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("mapping fields must be JSON objects")
            return parsed
        raise ValueError("mapping fields must be a dict or JSON object string")

    @field_validator("notion_write_timeout_s")
    @classmethod
    def validate_notion_write_timeout_s(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("notion_write_timeout_s must be > 0")
        return value

    @field_validator("reranking_benchmark_gcp_call_budget")
    @classmethod
    def validate_reranking_benchmark_gcp_call_budget(cls, value: int) -> int:
        if value < 0:
            raise ValueError("reranking_benchmark_gcp_call_budget must be >= 0")
        return value

    @field_validator("reranking_benchmark_aws_pacing_s")
    @classmethod
    def validate_reranking_benchmark_aws_pacing_s(cls, value: float) -> float:
        if value < 0:
            raise ValueError("reranking_benchmark_aws_pacing_s must be >= 0")
        return value

    @field_validator("retrieval_pipeline_min_reranked_results")
    @classmethod
    def validate_retrieval_pipeline_min_reranked_results(cls, value: int) -> int:
        if value < 1:
            raise ValueError("retrieval_pipeline_min_reranked_results must be >= 1")
        return value

    @field_validator("web_read_allowed_domains", mode="before")
    @classmethod
    def validate_web_read_allowed_domains(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            parts = [item.strip().lower() for item in value.split(",")]
            return [item for item in parts if item]
        if isinstance(value, list):
            return [str(item).strip().lower() for item in value if str(item).strip()]
        raise ValueError("web_read_allowed_domains must be a list or comma-separated string")

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def validate_cors_allow_origins(cls, value):
        default = ["http://localhost:5173"]
        if value is None or value == "":
            return default
        if isinstance(value, str):
            parts = [item.strip() for item in value.split(",") if item.strip()]
            return parts or default
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            return parts or default
        raise ValueError("cors_allow_origins must be a list or comma-separated string")

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

    @field_validator(
        "max_request_bytes",
        "max_message_chars",
        "max_assistant_chars",
        "max_error_message_chars",
        "web_read_max_bytes",
        "web_read_max_chars",
        "chat_response_cache_ttl_s",
        "routing_shadow_timeout_ms",
        "routing_message_length_cheap_max",
        "routing_estimated_tokens_smart_min",
    )
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

    @model_validator(mode="after")
    def validate_rag_app_database_url(self) -> "Settings":
        # ADR-006 §2 / spec.md §Design decisions 4: DATABASE_URL_APP must never
        # silently fall back to the superuser database_url — that would make
        # every RLS policy inert without anything failing loudly.
        if (self.rag_enabled or self.chat_rag_augmentation_enabled) and not self.database_url_app:
            raise ValueError(
                "DATABASE_URL_APP is required when RAG_ENABLED or CHAT_RAG_AUGMENTATION_ENABLED is true"
            )
        return self

    @model_validator(mode="after")
    def validate_evaluation_store_url(self) -> "Settings":
        # ADR-009 decision 5: the store must never be the superuser database.
        # That is the direction this drifts in — the superuser DSN is already in
        # the environment and it works, so a harness that "just needs a
        # connection" would silently gain write access to business data.
        #
        # database_url_app is deliberately NOT rejected here. rag_app is
        # under-privileged, not over-privileged: it cannot CREATE SCHEMA, so
        # pointing the store at it fails loudly at DDL time rather than
        # succeeding dangerously. Guarding it would be guarding the wrong
        # direction.
        if self.evaluation_store_url and self.evaluation_store_url == self.database_url:
            raise ValueError(
                "EVALUATION_STORE_URL must not equal the application database URL; "
                "the evaluation store requires its own non-superuser role (ADR-009)"
            )
        return self

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


_settings_env_file = os.getenv("APP_SETTINGS_ENV_FILE", ".env")
settings = Settings(_env_file=_settings_env_file or None)
