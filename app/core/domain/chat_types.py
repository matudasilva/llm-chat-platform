from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .types import ChatMessage
from .provider import ProviderResult


@dataclass(frozen=True, slots=True)
class ChatServiceResult:
    request_id: UUID
    assistant_message: ChatMessage
    provider_result: ProviderResult
