"""The only path from this experiment to a paid chat-completion call.

Same contract as `embedding_client`: cache lookup, privacy scan of the exact
rendered payload, spend-guard reservation, dispatch, settlement. The
difference that matters for the budget is that this API reports `usage`, so
every call settles at its real cost and at most one reservation is ever open
-- without that, the byte-based worst-case reservations (about 4x actual)
would exhaust the stage's sub-cap long before the money did.

Used for both generation and fact extraction; `kind` separates them in the
ledger.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from . import events, payload_scan
from .spend_guard import Reservation, SpendGuard, SpendGuardError

CACHE_SCHEMA = "orq39-generation-cache-v1"
COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
# One pre-registered transport retry (spec §Diseño 13); the reservation prices
# both attempts, and a retry never becomes a second logical attempt.
MAX_ATTEMPTS = 2
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class GenerationError(RuntimeError):
    """The call failed after its one pre-registered retry."""


class OfflineCacheMiss(RuntimeError):
    """Replay mode asked for a completion the cache does not hold."""


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """One logical attempt: the exact messages, plus the scope that keys it."""

    messages: tuple[Mapping[str, str], ...]
    tenant_id: str
    conversation_id: str
    kind: str  # "generation" or "extraction" -- ledger and cache separation
    label: str  # step id, turn id: provenance only
    max_output_tokens: int
    temperature: float = 0.0
    response_format: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    usage: Mapping[str, int] | None
    cached: bool
    model: str


class GenerationClient:
    def __init__(
        self,
        *,
        cache_dir: Path,
        guard: SpendGuard | None,
        model: str,
        api_key: str | None = None,
        offline: bool = False,
        timeout_s: float = 60.0,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.guard = guard
        self.model = model
        self.offline = offline
        self.timeout_s = timeout_s
        self._api_key = api_key
        self.calls = 0
        self.cache_hits = 0

    def _body(self, request: GenerationRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.response_format is not None:
            body["response_format"] = dict(request.response_format)
        return body

    def _key(self, request: GenerationRequest) -> str:
        return events.sha256_hex(
            events.canonical_bytes(
                {
                    "schema": CACHE_SCHEMA,
                    "tenant_id": request.tenant_id,
                    "conversation_id": request.conversation_id,
                    "kind": request.kind,
                    "body": self._body(request),
                }
            )
        )

    def complete(self, request: GenerationRequest) -> GenerationResult:
        key = self._key(request)
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            self.cache_hits += 1
            cached = json.loads(path.read_text())
            return GenerationResult(
                text=cached["text"], usage=cached.get("usage"), cached=True, model=cached["model"]
            )
        if self.offline:
            raise OfflineCacheMiss(f"no cached completion for {request.kind} {key[:12]}")

        body = self._body(request)
        rendered = events.canonical_bytes(body).decode("utf-8")
        # Fail closed before anything leaves the process: the scanned bytes are
        # exactly the bytes that would be sent, and their digest is what the
        # ledger records (AC22).
        payload_scan.assert_clean(rendered)
        if self.guard is None:
            raise SpendGuardError("a spend guard is required for a live dispatch")
        if not self._api_key:
            raise SpendGuardError("no API key: refusing to dispatch")

        payload_sha = events.sha256_hex(rendered.encode("utf-8"))
        reservation = self.guard.reserve(
            kind=request.kind,
            max_input_tokens=len(rendered.encode("utf-8")),
            max_output_tokens=request.max_output_tokens,
            attempts=MAX_ATTEMPTS,
            payload_sha256=payload_sha,
            logical_attempt=key,
        )
        try:
            text, usage = self._dispatch(body)
        except Exception:
            self.guard.settle(reservation, status="failed", usage=None)
            raise
        # Settle at the reported cost; this is what keeps the sub-cap usable.
        self.guard.settle(reservation, status="ok", usage=usage)
        self.calls += 1
        path.write_text(
            json.dumps(
                {
                    "schema": CACHE_SCHEMA,
                    "model": self.model,
                    "payload_sha256": payload_sha,
                    "text": text,
                    "usage": dict(usage) if usage else None,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return GenerationResult(text=text, usage=usage, cached=False, model=self.model)

    def _dispatch(self, body: Mapping[str, Any]) -> tuple[str, Mapping[str, int] | None]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        last: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    response = client.post(COMPLETIONS_URL, headers=headers, json=dict(body))
                if response.status_code in RETRYABLE_STATUS and attempt < MAX_ATTEMPTS:
                    last = GenerationError(f"retryable status {response.status_code}")
                    continue
                if response.status_code != 200:
                    raise GenerationError(f"status {response.status_code}")
                payload = response.json()
                choice = payload["choices"][0]["message"]["content"]
                usage = payload.get("usage")
                return choice, usage if isinstance(usage, dict) else None
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if attempt >= MAX_ATTEMPTS:
                    break
        raise GenerationError(f"dispatch failed after {MAX_ATTEMPTS} attempts: {last}")


__all__ = [
    "GenerationClient",
    "GenerationRequest",
    "GenerationResult",
    "GenerationError",
    "OfflineCacheMiss",
]
