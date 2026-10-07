"""The only path from this experiment to a paid embedding call.

Every dispatch passes, in order: cache lookup, privacy scan of the exact text
that would be sent, a spend-guard reservation, the call, then settlement with
the provider's reported usage. A cache hit reaches none of that, which is what
makes an offline replay free and byte-identical.

The provider adapter is the runtime's own `OpenAIEmbeddingProvider`
(experiments may import `app/`, never the reverse), so the experiment measures
the same client the platform uses rather than a second implementation.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from app.core.providers.openai_embedding_provider import (
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
)

from . import events, payload_scan
from .spend_guard import Pricing, SpendGuard, SpendGuardError

CACHE_SCHEMA = "orq39-embedding-cache-v1"
# UTF-8 bytes are a provable upper bound on token count, so the guard reserves
# against bytes rather than a tokenizer this experiment does not pin.
BYTES_PER_TOKEN_BOUND = 1


class OfflineCacheMiss(RuntimeError):
    """Replay mode asked for an embedding the cache does not hold."""


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    """What is embedded, and the scope that keys its cache entry.

    `tenant_id` and `conversation_id` are part of the key even though the
    vector does not depend on them: identical text under two tenants must not
    share a cache entry, so a cache hit can never cross a tenant boundary
    (spec F3).
    """

    text: str
    tenant_id: str
    conversation_id: str
    role: str  # "turn", "fact", or "query" -- provenance, also part of the key


class EmbeddingClient:
    def __init__(
        self,
        *,
        cache_dir: Path,
        guard: SpendGuard | None,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        api_key: str | None = None,
        offline: bool = False,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.dimensions = dimensions
        self.guard = guard
        self.offline = offline
        self._api_key = api_key
        self.calls = 0
        self.cache_hits = 0

    def _key(self, request: EmbeddingRequest) -> str:
        return events.sha256_hex(
            events.canonical_bytes(
                {
                    "schema": CACHE_SCHEMA,
                    "model": self.model,
                    "dimensions": self.dimensions,
                    "tenant_id": request.tenant_id,
                    "conversation_id": request.conversation_id,
                    "role": request.role,
                    "text": request.text,
                }
            )
        )

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def embed(self, request: EmbeddingRequest) -> tuple[float, ...]:
        key = self._key(request)
        path = self._cache_path(key)
        if path.exists():
            self.cache_hits += 1
            return tuple(json.loads(path.read_text())["vector"])
        if self.offline:
            raise OfflineCacheMiss(f"no cached embedding for {request.role} {key[:12]}")

        # Fail closed before anything leaves the process.
        payload_scan.assert_clean(request.text)
        if self.guard is None:
            raise SpendGuardError("a spend guard is required for a live dispatch")
        if not self._api_key:
            raise SpendGuardError("no API key: refusing to dispatch")

        payload_sha = events.sha256_hex(request.text.encode("utf-8"))
        reservation = self.guard.reserve(
            kind="embedding",
            max_input_tokens=len(request.text.encode("utf-8")) * BYTES_PER_TOKEN_BOUND,
            payload_sha256=payload_sha,
            logical_attempt=key,
        )
        provider = OpenAIEmbeddingProvider(
            OpenAIEmbeddingConfig(
                api_key=self._api_key,
                model=self.model,
                dimensions=self.dimensions,
                # One pre-registered transport retry (§Diseño 13), which the
                # reservation already priced as two provider calls.
                max_attempts=2,
            )
        )
        try:
            vector = asyncio.run(provider.embed_one(request.text))
        except Exception:
            self.guard.settle(reservation, status="failed", usage=None)
            raise
        # The adapter returns vectors only; usage is not exposed, so the
        # reservation stands as the charge -- the conservative direction.
        self.guard.settle(reservation, status="ok", usage=None)
        self.calls += 1
        vector = tuple(float(value) for value in vector)
        path.write_text(
            json.dumps(
                {
                    "schema": CACHE_SCHEMA,
                    "model": self.model,
                    "dimensions": self.dimensions,
                    "role": request.role,
                    "payload_sha256": payload_sha,
                    "vector": list(vector),
                },
                separators=(",", ":"),
            )
        )
        return vector

    def embed_all(self, requests: Sequence[EmbeddingRequest]) -> list[tuple[float, ...]]:
        """Sequential by design: the guard's invariant assumes one call at a time."""
        return [self.embed(request) for request in requests]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Exact cosine in memory -- no pgvector, no index (spec §No-alcance)."""
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        raise ValueError("cosine is undefined for a zero vector")
    return dot / (left_norm * right_norm)


def load_api_key(env_path: Path) -> str | None:
    """Read the key from a local .env without importing it into the process env."""
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY"):
            _, _, value = line.partition("=")
            return value.strip().strip('"').strip("'") or None
    return None


def usd(value: str) -> Decimal:
    return Decimal(value)


__all__ = [
    "EmbeddingClient",
    "EmbeddingRequest",
    "OfflineCacheMiss",
    "Pricing",
    "cosine",
    "load_api_key",
    "usd",
]
