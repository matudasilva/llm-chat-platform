"""ORQ-37 Gate A, T5 — AC37: the resolved-payload matrix, per provider.

AC6 asserts the generic invariants at `messages_for_provider`. That level
**cannot observe hoisting**: Bedrock lifts every system message out of the turn
list into `payload["system"]`, so a containment claim made only there would be
blind to the one transformation most able to break it. AC37 therefore asserts at
the *resolved payload* of each shipped adapter, because the same messages list
means three different things:

| Provider | Treatment | What must hold |
|---|---|---|
| Bedrock | hoists `system` into `payload["system"]` | the system block is exactly this ORQ's envelope; turns start at `user` |
| OpenAI  | roles inline in `input`, no hoisting        | the envelope is one system entry, first, and nowhere else |
| Stub    | reads `messages[-1]` only                   | prepending the envelope leaves the last element the user message |

Gate A covers the documental channel. The memory envelope arrives at B2 and its
row in this matrix is added there, against the same corpus.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.core.domain.provider import ProviderInput
from app.core.domain.rag_generation import RagGenerationContext, RagSource
from app.core.domain.types import ChatMessage
from app.core.providers.bedrock_provider import _build_payload as bedrock_payload
from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig
from app.core.providers.stub_provider import StubProvider
from tests.fixtures.adversarial_corpus import ADVERSARIAL_PAYLOADS

_USER_TURN = "what does the platform say about retrieval?"
_ALL = tuple(e.payload for e in ADVERSARIAL_PAYLOADS)


def _input(*contents: str) -> ProviderInput:
    context = RagGenerationContext(
        sources=tuple(
            RagSource(
                citation=f"S{i + 1}",
                document_id=uuid.uuid4(),
                chunk_id=uuid.uuid4(),
                rank=i + 1,
                content=content,
                truncated=False,
            )
            for i, content in enumerate(contents)
        )
    )
    return ProviderInput(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content=_USER_TURN)],
        metadata=context.provider_metadata,
    )


def _openai() -> OpenAIProvider:
    return OpenAIProvider(
        OpenAIProviderConfig(api_key="test-key", model="test-model", timeout_s=1.0)
    )


def _wire(payload: str) -> str:
    return json.dumps(payload, ensure_ascii=False)[1:-1]


def _contains(haystack: str, payload: str) -> bool:
    return payload in haystack or _wire(payload) in haystack


# --- Bedrock: the hoisting provider ---------------------------------------


def test_bedrock_hoists_exactly_one_system_block_and_it_is_our_envelope():
    payload = bedrock_payload(input=_input(*_ALL), model="anthropic.test")

    assert len(payload["system"]) == 1
    system_text = payload["system"][0]["text"]
    assert "untrusted evidence" in system_text
    assert "Retrieved sources (JSON):" in system_text


def test_bedrock_turn_list_holds_no_system_role_and_starts_at_user():
    payload = bedrock_payload(input=_input(*_ALL), model="anthropic.test")

    assert [m["role"] for m in payload["messages"]] == ["user"]
    assert payload["messages"][0]["content"] == [{"text": _USER_TURN}]


@pytest.mark.parametrize("entry", ADVERSARIAL_PAYLOADS, ids=lambda e: e.name)
def test_bedrock_keeps_every_payload_inside_the_hoisted_system_block(entry):
    """The hoist is the danger: it moves text to the highest-authority position
    in the prompt. What lands there must be only our envelope."""
    payload = bedrock_payload(input=_input(entry.payload), model="anthropic.test")

    assert _contains(payload["system"][0]["text"], entry.payload)
    for message in payload["messages"]:
        for block in message["content"]:
            assert not _contains(block["text"], entry.payload)


def test_bedrock_without_sources_emits_no_system_block_at_all():
    plain = ProviderInput(
        request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content=_USER_TURN)]
    )
    payload = bedrock_payload(input=plain, model="anthropic.test")
    assert "system" not in payload
    assert [m["role"] for m in payload["messages"]] == ["user"]


# --- OpenAI: inline roles, no hoisting -------------------------------------


def test_openai_renders_the_envelope_as_the_first_inline_system_entry():
    payload = _openai()._build_payload(_input(*_ALL))

    assert [entry["role"] for entry in payload["input"]] == ["system", "user"]
    assert "untrusted evidence" in payload["input"][0]["content"][0]["text"]
    assert payload["input"][1]["content"][0]["text"] == _USER_TURN


@pytest.mark.parametrize("entry", ADVERSARIAL_PAYLOADS, ids=lambda e: e.name)
def test_openai_keeps_every_payload_in_the_system_entry_only(entry):
    payload = _openai()._build_payload(_input(entry.payload))

    carriers = [
        item["role"]
        for item in payload["input"]
        if any(_contains(block["text"], entry.payload) for block in item["content"])
    ]
    assert carriers == ["system"]


def test_openai_without_sources_emits_no_system_entry():
    plain = ProviderInput(
        request_id=uuid.uuid4(), messages=[ChatMessage(role="user", content=_USER_TURN)]
    )
    payload = _openai()._build_payload(plain)
    assert [entry["role"] for entry in payload["input"]] == ["user"]


# --- Stub: reads messages[-1] ----------------------------------------------


@pytest.mark.asyncio
async def test_stub_behaviour_is_unchanged_by_prepending_the_envelope():
    """The stub echoes `messages[-1]`. Prepending a system message must leave
    the user turn last, so the envelope cannot become the stub's input."""
    stub = StubProvider()
    with_sources = await stub.generate(_input(*_ALL))
    plain = await stub.generate(
        ProviderInput(
            request_id=uuid.uuid4(),
            messages=[ChatMessage(role="user", content=_USER_TURN)],
        )
    )

    assert with_sources.content.endswith(_USER_TURN)
    assert plain.content.endswith(_USER_TURN)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ADVERSARIAL_PAYLOADS, ids=lambda e: e.name)
async def test_stub_output_never_carries_an_injection_payload(entry):
    result = await StubProvider().generate(_input(entry.payload))
    assert not _contains(result.content, entry.payload)


# --- The matrix is complete ------------------------------------------------


def test_all_three_shipped_providers_are_covered_here():
    """§Diseño 11 names exactly three. A fourth inherits the contract but not
    the evidence, and adding one is out of scope -- so this fails loudly if the
    shipped set grows without this matrix growing with it."""
    from app.core.domain import provider_factory

    source = (
        provider_factory.__file__
        and open(provider_factory.__file__, encoding="utf-8").read()
    )
    for name in ("BedrockProvider", "OpenAIProvider", "StubProvider"):
        assert name in source
    assert "DisabledProvider" in source  # not a generating provider; no payload to assert
