from __future__ import annotations

import hashlib
import json
import logging
from typing import Sequence
from uuid import UUID

from app.core.domain.chat_types import ChatServiceResult
from app.core.domain.provider import ProviderResult
from app.core.domain.types import ChatMessage
from app.core.settings import settings
from app.infra.redis_client import redis_client

logger = logging.getLogger(__name__)


class ChatResponseCache:
    async def get(
        self, *, request_id: UUID, messages: Sequence[ChatMessage], tenant_id: str
    ) -> ChatServiceResult | None:
        key = self._cache_key(messages=messages, tenant_id=tenant_id)
        try:
            raw = await redis_client.get(key)
        except Exception:
            logger.warning(
                "chat_cache_error",
                extra={"event": "chat.cache.error", "operation": "read", "tenant_id": tenant_id},
                exc_info=True,
            )
            return None

        if not raw:
            logger.info("chat_cache_miss", extra={"event": "chat.cache.miss", "tenant_id": tenant_id})
            return None

        try:
            payload = json.loads(raw)
            provider_payload = payload["provider_result"]
            assistant_content = str(payload["assistant_content"])
            provider_result = ProviderResult(
                content=assistant_content,
                provider=str(provider_payload["provider"]),
                model_version=str(provider_payload["model_version"]),
                prompt_version=str(provider_payload["prompt_version"]),
                input_tokens=_as_int_or_none(provider_payload.get("input_tokens")),
                output_tokens=_as_int_or_none(provider_payload.get("output_tokens")),
                total_tokens=_as_int_or_none(provider_payload.get("total_tokens")),
                latency_ms=None,
            )
        except Exception:
            logger.warning(
                "chat_cache_error",
                extra={"event": "chat.cache.error", "operation": "decode", "tenant_id": tenant_id},
                exc_info=True,
            )
            return None

        logger.info("chat_cache_hit", extra={"event": "chat.cache.hit", "tenant_id": tenant_id})
        return ChatServiceResult(
            request_id=request_id,
            assistant_message=ChatMessage(role="assistant", content=assistant_content),
            provider_result=provider_result,
        )

    async def set(
        self, *, messages: Sequence[ChatMessage], result: ChatServiceResult, tenant_id: str
    ) -> None:
        key = self._cache_key(messages=messages, tenant_id=tenant_id)
        payload = {
            "assistant_content": result.assistant_message.content,
            "provider_result": {
                "provider": result.provider_result.provider,
                "model_version": result.provider_result.model_version,
                "prompt_version": result.provider_result.prompt_version,
                "input_tokens": result.provider_result.input_tokens,
                "output_tokens": result.provider_result.output_tokens,
                "total_tokens": result.provider_result.total_tokens,
            },
        }
        try:
            await redis_client.set(
                key,
                json.dumps(payload, separators=(",", ":")),
                ex=settings.chat_response_cache_ttl_s,
            )
        except Exception:
            logger.warning(
                "chat_cache_error",
                extra={"event": "chat.cache.error", "operation": "write", "tenant_id": tenant_id},
                exc_info=True,
            )

    def log_bypass(self, *, reason: str) -> None:
        logger.info("chat_cache_bypass", extra={"event": "chat.cache.bypass", "reason": reason})

    def _cache_key(self, *, messages: Sequence[ChatMessage], tenant_id: str) -> str:
        fingerprint = {
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "provider": settings.provider,
            "fallback_provider": settings.fallback_provider,
            "openai_model": settings.openai_model,
            "bedrock_model": settings.bedrock_model,
            "bedrock_prompt_version": settings.bedrock_prompt_version,
            "stub_provider_mode": settings.stub_provider_mode,
        }
        digest = hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return f"chat:response:{tenant_id}:{digest}"


def _as_int_or_none(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


_cache = ChatResponseCache()


def get_chat_response_cache() -> ChatResponseCache:
    return _cache
