from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol, Sequence
from uuid import UUID

from .types import ChatMessage
from typing import AsyncIterator


@dataclass(frozen=True, slots=True)
class ProviderInput:
    """
    ProviderInput is a pure-domain request object.

    Rules:
    - Must not depend on FastAPI, SQLAlchemy, or DB models.
    - Designed to be stable across provider implementations.
    """
    request_id: UUID
    messages: Sequence[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """
    ProviderResult is a pure-domain response object.

    Notes:
    - It intentionally does NOT include DB foreign keys (conversation_id, message_id).
    - status is NOT a provider concern; it is a request/write-path concern.
    """
    content: str

    provider: str
    model_version: str
    prompt_version: str

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None

    # Debug-only payload (should not be persisted by default).
    raw: dict[str, Any] | None = None


class ProviderPort(Protocol):
    """
    Async-first port.

    Providers that are sync can be wrapped later via an adapter (e.g. asyncio.to_thread),
    without contaminating the domain contract.
    """
    async def generate(self, input: ProviderInput) -> ProviderResult:
        ...
        
    def stream(self, input: ProviderInput) -> AsyncIterator[str]:
        ...
