from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.domain.provider import ProviderInput, ProviderResult, ProviderStreamSession
from app.scripts.ingest_corpus import (
    LoadedDocument,
    _contextualize,
    build_search_texts,
    fingerprint,
    should_reindex,
)
from app.services.rag_chunking import RawChunk


class _FakeProvider:
    """No network, no postgres marker -- ProviderPort double for _contextualize."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.last_input: ProviderInput | None = None

    async def generate(self, input: ProviderInput) -> ProviderResult:
        self.last_input = input
        return ProviderResult(content=self._content, provider="fake", model_version="v1", prompt_version="v1")

    async def stream(self, input: ProviderInput) -> ProviderStreamSession:
        raise NotImplementedError


def test_fingerprint_combines_hash_and_mode() -> None:
    assert fingerprint("abc123", "plain") == "abc123:plain"


def test_should_reindex_true_when_no_existing_row() -> None:
    assert should_reindex(None, "abc123:plain") is True


def test_should_reindex_false_when_hash_and_mode_match() -> None:
    assert should_reindex("abc123:plain", "abc123:plain") is False


def test_should_reindex_true_when_content_hash_changes() -> None:
    assert should_reindex("abc123:plain", "def456:plain") is True


def test_should_reindex_true_when_indexing_mode_changes_same_hash() -> None:
    # ADR-006 §6: content_hash alone is not enough to decide idempotency.
    assert should_reindex("abc123:plain", "abc123:contextualized") is True


def test_build_search_texts_uses_text_alone_when_no_context() -> None:
    chunks = [RawChunk(text="original chunk text", section="foo")]
    result = build_search_texts(chunks, [None])
    assert result == ["original chunk text"]


def test_build_search_texts_prepends_context_when_present() -> None:
    chunks = [RawChunk(text="original chunk text", section="foo")]
    contexts = ["This chunk is from the foo function."]
    result = build_search_texts(chunks, contexts)
    assert result == ["This chunk is from the foo function.\noriginal chunk text"]
    # The original chunk text itself is never mutated by contextualization.
    assert chunks[0].text == "original chunk text"


@pytest.mark.asyncio
async def test_contextualize_sends_document_and_chunk_to_provider() -> None:
    provider = _FakeProvider(content="This is ADR-999, discussing the foo section.")
    document = LoadedDocument(
        source_path="docs/adr/999-example.md",
        doc_type="markdown",
        content="irrelevant full document text",
        content_hash="deadbeef",
    )
    chunk = RawChunk(text="the actual fragment text", section="Foo Section")

    result = await _contextualize(provider, document, chunk)

    assert result == "This is ADR-999, discussing the foo section."
    assert provider.last_input is not None
    user_message = provider.last_input.messages[-1]
    assert "docs/adr/999-example.md" in user_message.content
    assert "Foo Section" in user_message.content
    assert "the actual fragment text" in user_message.content
