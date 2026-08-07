from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.responses import StreamingResponse

import app.api.routes.chat as chat_routes
from app.core.domain.chat_service import ChatServiceStreamSession, StreamChatResult
from app.core.domain.chat_types import ChatServiceResult
from app.core.domain.provider import ProviderResult
from app.core.domain.rag_generation import RagGenerationContext, RagSource
from app.core.domain.types import ChatMessage
from app.schemas.chat import ChatRequest


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Session:
    def __init__(self) -> None:
        self.objects = []

    def begin(self):
        return _Transaction()

    def add(self, obj) -> None:
        self.objects.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model, key):
        return next(
            (obj for obj in self.objects if isinstance(obj, model) and obj.id == key),
            None,
        )


class _Cache:
    def __init__(self) -> None:
        self.reads = 0
        self.writes = 0
        self.bypasses = []

    async def get(self, **kwargs):
        self.reads += 1

    async def set(self, **kwargs):
        self.writes += 1

    def log_bypass(self, *, reason):
        self.bypasses.append(reason)


class _ChatService:
    def __init__(self) -> None:
        self.metadata = None

    async def run(self, *, request_id, messages, provider_metadata=None):
        self.metadata = provider_metadata
        return ChatServiceResult(
            request_id=request_id,
            assistant_message=ChatMessage(role="assistant", content="answer [S1]"),
            provider_result=ProviderResult(
                content="answer [S1]",
                provider="stub",
                model_version="stub-v1",
                prompt_version="v1",
            ),
        )

    async def stream_chat(self, *, request_id, messages, provider_metadata=None):
        self.metadata = provider_metadata

        async def chunks() -> AsyncIterator[str]:
            yield "answer "
            yield "[S1]"

        async def final() -> StreamChatResult:
            return StreamChatResult(
                request_id=request_id,
                assistant_message=ChatMessage(role="assistant", content="answer [S1]"),
                provider_result=None,
            )

        return ChatServiceStreamSession(chunks=chunks(), get_final_result=final)


def _context() -> RagGenerationContext:
    return RagGenerationContext(
        sources=(
            RagSource(
                citation="S1",
                document_id=uuid.uuid4(),
                chunk_id=uuid.uuid4(),
                rank=1,
                content="bounded source text",
                truncated=False,
            ),
        )
    )


async def _events(response: StreamingResponse) -> list[tuple[str, object]]:
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)
    events = []
    current = None
    for line in body.splitlines():
        if line.startswith("event: "):
            current = line.removeprefix("event: ")
        elif line.startswith("data: ") and current:
            raw = line.removeprefix("data: ")
            events.append((current, raw if current == "token" else json.loads(raw)))
    return events


@pytest.mark.asyncio
async def test_non_streaming_chat_passes_metadata_returns_sources_and_bypasses_cache(
    monkeypatch,
) -> None:
    cache = _Cache()
    service = _ChatService()
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", True)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache)

    context = _context()
    response = await chat_routes.chat(
        ChatRequest(message="question"),
        db=_Session(),
        chat_service=service,
        rag_context=context,
    )

    assert response.assistant_content == "answer [S1]"
    source = context.sources[0]
    assert [item.model_dump(mode="json") for item in response.sources] == [
        {
            "citation": source.citation,
            "document_id": str(source.document_id),
            "chunk_id": str(source.chunk_id),
            "rank": source.rank,
        }
    ]
    assert service.metadata["rag"]["sources"][0]["content"] == "bounded source text"
    assert cache.reads == 0
    assert cache.writes == 0
    assert cache.bypasses == ["rag_augmentation"]


@pytest.mark.asyncio
async def test_streaming_chat_keeps_event_contract_and_adds_sources_to_done(monkeypatch) -> None:
    cache = _Cache()
    service = _ChatService()
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", True)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", lambda: cache)

    context = _context()
    response = await chat_routes.chat(
        ChatRequest(message="question", stream=True),
        db=_Session(),
        chat_service=service,
        rag_context=context,
    )
    events = await _events(response)

    assert [event for event, _ in events] == ["token", "token", "done"]
    done = next(payload for event, payload in events if event == "done")
    source = context.sources[0]
    assert done["sources"] == [
        {
            "citation": source.citation,
            "document_id": str(source.document_id),
            "chunk_id": str(source.chunk_id),
            "rank": source.rank,
        }
    ]
    assert "content" not in done["sources"][0]
    assert cache.bypasses == ["rag_augmentation"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_enabled_chat_continues_without_metadata_when_retrieval_returns_no_sources(
    monkeypatch, stream
) -> None:
    service = _ChatService()
    monkeypatch.setattr(chat_routes.settings, "chat_rag_augmentation_enabled", True)
    monkeypatch.setattr(chat_routes, "get_chat_response_cache", _Cache)

    response = await chat_routes.chat(
        ChatRequest(message="question", stream=stream),
        db=_Session(),
        chat_service=service,
        rag_context=RagGenerationContext(),
    )

    assert service.metadata is None
    if stream:
        events = await _events(response)
        assert [event for event, _ in events] == ["token", "token", "done"]
        done = next(payload for event, payload in events if event == "done")
        assert done["sources"] == []
    else:
        assert response.assistant_content == "answer [S1]"
        assert response.sources == []
