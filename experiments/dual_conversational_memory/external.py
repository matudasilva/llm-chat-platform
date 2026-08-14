from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import uuid4

import httpx

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_errors import ProviderError
from app.core.domain.types import ChatMessage
from app.core.providers.openai_embedding_provider import (
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
)
from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig

from .dataset import ConversationEvent
from .memory import SemanticFact, estimated_tokens, stable_hash
from .protocol import CallReservation, ExternalCallLedger


@dataclass(frozen=True, slots=True)
class GenerationResult:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int
    ttft_ms: float | None
    model: str


class DevelopmentOpenAIProvider(OpenAIProvider):
    """Experiment-only multi-message Responses adapter with a fixed output cap."""

    def __init__(self, config: OpenAIProviderConfig, *, max_output_tokens: int) -> None:
        super().__init__(config)
        self._max_output_tokens = max_output_tokens

    def _build_payload(self, input: ProviderInput) -> dict[str, Any]:
        return {
            "model": self._cfg.model,
            "input": [
                {"role": message.role, "content": message.content}
                for message in input.messages
            ],
            "max_output_tokens": self._max_output_tokens,
        }


async def generate_streamed(
    *,
    provider: DevelopmentOpenAIProvider,
    messages: Sequence[ChatMessage],
    ledger: ExternalCallLedger,
    model: str,
    step_id: str,
    arm: str,
) -> GenerationResult:
    call = ledger.reserve(kind="generation", model=model, step_id=step_id, arm=arm)
    start = time.monotonic()
    first_token: float | None = None
    try:
        session = await provider.stream(
            ProviderInput(request_id=uuid4(), messages=tuple(messages))
        )
        parts: list[str] = []
        async for part in session.chunks:
            if first_token is None:
                first_token = time.monotonic()
            parts.append(part)
        completed = await session.get_final_result()
        result = completed.provider_result
        latency_ms = int((time.monotonic() - start) * 1000)
        ledger.succeeded(
            call,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=float(latency_ms),
        )
        return GenerationResult(
            content="".join(parts) or completed.content,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            latency_ms=latency_ms,
            ttft_ms=None if first_token is None else (first_token - start) * 1000,
            model=result.model_version,
        )
    except Exception as exc:
        ledger.failed(
            call,
            error_kind=_error_kind(exc),
            duration_ms=(time.monotonic() - start) * 1000,
        )
        raise


async def embed_texts(
    *,
    texts: Sequence[str],
    api_key: str,
    model: str,
    dimensions: int,
    ledger: ExternalCallLedger,
    step_id: str,
) -> dict[str, tuple[float, ...]]:
    unique = tuple(dict.fromkeys(texts))
    call = ledger.reserve(
        kind="embedding_batch",
        model=model,
        step_id=step_id,
        arm=None,
    )
    token_estimate = sum(estimated_tokens(text) for text in unique)
    start = time.monotonic()
    provider = OpenAIEmbeddingProvider(
        OpenAIEmbeddingConfig(
            api_key=api_key,
            model=model,
            dimensions=dimensions,
            timeout_s=60.0,
            max_attempts=1,
        )
    )
    try:
        response = await provider.embed_many(unique)
        vectors = {
            stable_hash(text): tuple(float(value) for value in vector)
            for text, vector in zip(unique, response.vectors)
        }
        if len(vectors) != len(unique):
            raise ValueError("embedding response count differs from request")
        ledger.succeeded(
            call,
            input_tokens=None,
            output_tokens=None,
            estimated_tokens=token_estimate,
            duration_ms=(time.monotonic() - start) * 1000,
        )
        return vectors
    except Exception as exc:
        ledger.failed(
            call,
            error_kind=_error_kind(exc),
            duration_ms=(time.monotonic() - start) * 1000,
        )
        raise


class SemanticExtractor:
    _SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "fact_key": {"type": "string"},
                        "value": {"type": "string"},
                        "value_type": {"type": "string"},
                        "source_role": {"type": "string", "enum": ["user", "assistant"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "status": {"type": "string", "enum": ["active", "superseded", "disputed", "expired", "revoked", "deleted"]},
                        "supersedes_event_ids": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["fact_key", "value", "value_type", "source_role", "confidence", "status", "supersedes_event_ids"],
                },
            }
        },
        "required": ["facts"],
    }

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        prompt_version: str,
        ledger: ExternalCallLedger,
        timeout_s: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._prompt_version = prompt_version
        self._ledger = ledger
        self._timeout_s = timeout_s

    async def extract(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        event: ConversationEvent,
    ) -> tuple[SemanticFact, ...]:
        call = self._ledger.reserve(
            kind="semantic_extraction",
            model=self._model,
            step_id=event.event_id,
            arm="semantic-index",
        )
        prompt = (
            "Extract reusable current conversational facts from this single confirmed synthetic "
            "transcript event. Include only direct user assertions or explicit user corrections. "
            "Do not convert assistant hypotheticals, assistant acknowledgements, instructions, "
            "credentials, secrets, medical data, or protected data into facts. Use stable snake_case "
            "fact_key values. For a correction, return only the new effective value and status active; "
            "copy any explicitly supplied superseded event IDs. Return an empty facts array when no "
            "eligible fact exists.\n\n"
            f"event_id={event.event_id}\nevent_sequence={event.sequence}\n{event.text}"
        )
        payload = {
            "model": self._model,
            "input": [{"role": "user", "content": prompt}],
            "max_output_tokens": 300,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "orq29_semantic_facts",
                    "strict": True,
                    "schema": self._SCHEMA,
                }
            },
        }
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(
                base_url="https://api.openai.com",
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout_s,
            ) as client:
                response = await client.post("/v1/responses", json=payload)
            response.raise_for_status()
            body = response.json()
            raw = _response_text(body)
            decoded = json.loads(raw)
            usage = body.get("usage") or {}
            facts = tuple(
                SemanticFact(
                    fact_id=stable_hash(
                        f"{tenant_id}:{conversation_id}:{event.event_id}:{item['fact_key']}:{self._prompt_version}"
                    ),
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    fact_key=str(item["fact_key"]),
                    value=str(item["value"]),
                    value_type=str(item["value_type"]),
                    source_event_id=event.event_id,
                    source_message_ids=tuple(message.message_id for message in event.messages),
                    source_role=str(item["source_role"]),
                    confidence=float(item["confidence"]),
                    effective_sequence=event.sequence,
                    status=str(item["status"]),
                    supersedes_event_ids=tuple(str(value) for value in item["supersedes_event_ids"]),
                    extractor_version=self._prompt_version,
                )
                for item in decoded["facts"]
            )
            self._ledger.succeeded(
                call,
                input_tokens=_safe_int(usage.get("input_tokens")),
                output_tokens=_safe_int(usage.get("output_tokens")),
                duration_ms=(time.monotonic() - start) * 1000,
            )
            return facts
        except Exception as exc:
            self._ledger.failed(
                call,
                error_kind=_error_kind(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )
            raise


def curated_facts(
    *,
    tenant_id: str,
    conversation_id: str,
    events: Sequence[ConversationEvent],
) -> tuple[SemanticFact, ...]:
    result: list[SemanticFact] = []
    for event in events:
        for fact in event.gold_facts:
            if not fact.eligible or fact.prohibited:
                continue
            result.append(
                SemanticFact(
                    fact_id=stable_hash(f"curated:{conversation_id}:{event.event_id}:{fact.fact_key}"),
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    fact_key=fact.fact_key,
                    value=fact.value,
                    value_type=fact.value_type,
                    source_event_id=event.event_id,
                    source_message_ids=tuple(message.message_id for message in event.messages),
                    source_role=fact.source_role,
                    confidence=1.0,
                    effective_sequence=event.sequence,
                    status=fact.status,
                    supersedes_event_ids=fact.supersedes_event_ids,
                    extractor_version="curated-track-r-v1",
                )
            )
    return tuple(result)


def _response_text(body: Mapping[str, Any]) -> str:
    for output in body.get("output", []):
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    return text
    raise ValueError("semantic extraction response has no output text")


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _error_kind(exc: Exception) -> str:
    if isinstance(exc, ProviderError):
        return str(exc.kind)
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http_{exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return "network"
    return type(exc).__name__
