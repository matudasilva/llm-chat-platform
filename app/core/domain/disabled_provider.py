from __future__ import annotations

from dataclasses import dataclass

from .provider import ProviderInput, ProviderPort, ProviderResult
from .provider_errors import ProviderError, ProviderErrorKind


@dataclass(frozen=True)
class DisabledProvider(ProviderPort):
    """
    Provider placeholder used when a real provider is selected but not configured
    (e.g., missing API key). The app must still boot.
    """
    provider_name: str
    reason: str

    async def generate(self, _input: ProviderInput) -> ProviderResult:
        # Keep this message safe: it can end up exposed via ChatService -> ProviderExecutionError.
        raise ProviderError(
            kind=ProviderErrorKind.auth,
            message=f"{self.provider_name} provider not configured",
        )