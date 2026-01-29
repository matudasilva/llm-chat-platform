from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .provider import ProviderResult

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ChatServiceResult:
    """
    Output of the DB-agnostic orchestration layer.
    """
    request_id: UUID
    assistant_message: ChatMessage
    provider_result: ProviderResult
