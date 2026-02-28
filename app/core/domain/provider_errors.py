from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ProviderErrorKind(str, Enum):
    timeout = "timeout"
    network = "network"
    auth = "auth"
    rate_limit = "rate_limit"
    bad_request = "bad_request"
    upstream = "upstream"
    unknown = "unknown"


@dataclass
class ProviderError(Exception):
    """
    Normalized provider failure raised by provider adapters.

    Requirements:
    - Safe to convert into a short client-facing message (no sensitive payloads).
    - Contains minimal metadata to support retry decisions and structured logging.
    """
    kind: ProviderErrorKind
    message: str
    provider: str = "unknown"
    http_status: Optional[int] = None
    retryable: bool = False
    error_code: Optional[str] = None  # provider-specific code if available

    def __str__(self) -> str:
        return self.message


def is_retryable(err: Exception) -> bool:
    return isinstance(err, ProviderError) and err.retryable