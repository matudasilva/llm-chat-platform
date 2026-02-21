# app/core/domain/provider_errors.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderErrorKind(str, Enum):
    timeout = "timeout"
    auth = "auth"
    rate_limit = "rate_limit"
    upstream = "upstream"
    unknown = "unknown"


@dataclass(frozen=True)
class ProviderError(Exception):
    """
    Normalized provider failure raised by provider adapters.
    Must be safe to convert into a short client-facing message.
    """
    kind: ProviderErrorKind
    message: str

    def __str__(self) -> str:
        return self.message