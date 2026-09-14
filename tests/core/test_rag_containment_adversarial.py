"""ORQ-37 Gate A, T5 — AC6's generic containment invariants.

Structural containment only: every payload must render *inside* the evidence
envelope and never as an instruction, in a form that survives a round-trip. What
the model then does with it is answer quality, which §No-alcance excludes and
which no test here asserts.

The per-provider resolved-payload matrix is AC37's and lives in
`test_provider_payload_containment.py`; this module asserts the invariants that
hold regardless of provider.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_prompt import messages_for_provider
from app.core.domain.rag_generation import RAG_SCHEMA_VERSION, RagGenerationContext, RagSource
from app.core.domain.types import ChatMessage
from tests.fixtures.adversarial_corpus import ADVERSARIAL_PAYLOADS

_USER_TURN = "what does the platform say about retrieval?"
_ENVELOPE_HEADER = "Retrieved sources (JSON):"


def _source(content: str, *, index: int = 1) -> RagSource:
    return RagSource(
        citation=f"S{index}",
        document_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        rank=index,
        content=content,
        truncated=False,
    )


def _input(*contents: str, user: str = _USER_TURN) -> ProviderInput:
    context = RagGenerationContext(
        sources=tuple(_source(c, index=i + 1) for i, c in enumerate(contents))
    )
    return ProviderInput(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content=user)],
        metadata=context.provider_metadata,
    )


def _wire_form(payload: str) -> str:
    """The payload exactly as the envelope serializes it.

    `ensure_ascii=False` mirrors `provider_prompt.messages_for_provider`. Using
    the json default here would have been a subtle bug in the test itself: it
    escapes non-ASCII, so the zero-width, bidi and Spanish payloads would have
    been compared against a form the serializer never produces.
    """
    return json.dumps(payload, ensure_ascii=False)[1:-1]


def _envelope_json(system_content: str) -> list[dict]:
    """Parse the JSON the envelope carries. Parsing is the assertion: if a
    payload had broken out of the structure, this would raise or come back
    with a different shape."""
    _, _, serialized = system_content.partition(_ENVELOPE_HEADER)
    return json.loads(serialized.strip())


# --- Shape --------------------------------------------------------------


@pytest.mark.parametrize("entry", ADVERSARIAL_PAYLOADS, ids=lambda e: e.name)
def test_payload_renders_inside_the_envelope_and_survives_a_round_trip(entry):
    messages = messages_for_provider(_input(entry.payload))

    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user" and messages[1].content == _USER_TURN

    sources = _envelope_json(messages[0].content)
    assert len(sources) == 1
    # Byte-for-byte: the payload is carried, not sanitized and not escaped away.
    assert sources[0]["content"] == entry.payload
    assert sources[0]["citation"] == "S1"


@pytest.mark.parametrize("entry", ADVERSARIAL_PAYLOADS, ids=lambda e: e.name)
def test_payload_reaches_no_message_other_than_the_envelope(entry):
    """Neither raw nor escaped, in any turn after the envelope.

    Both forms are checked because JSON escaping means a payload with newlines
    or control characters never appears raw on the wire -- so a raw-only check
    would pass vacuously on exactly the payloads that try hardest to break out.
    """
    messages = messages_for_provider(_input(entry.payload))
    escaped = _wire_form(entry.payload)

    for message in messages[1:]:
        assert entry.payload not in message.content
        assert escaped not in message.content

    # And it does reach the envelope, in one form or the other.
    envelope = messages[0].content
    assert entry.payload in envelope or escaped in envelope


@pytest.mark.parametrize(
    "entry",
    [e for e in ADVERSARIAL_PAYLOADS if e.payload != _wire_form(e.payload)],
    ids=lambda e: e.name,
)
def test_structural_characters_are_escaped_on_the_wire(entry):
    """The payloads carrying newlines, quotes or control characters are the ones
    that could forge a boundary, and they are exactly the ones that never appear
    raw in the serialized envelope. Escaping is the containment mechanism, so it
    is pinned rather than assumed."""
    envelope = messages_for_provider(_input(entry.payload))[0].content
    assert entry.payload not in envelope
    assert _wire_form(entry.payload) in envelope
    # Still recoverable byte-for-byte by a parser -- contained, not corrupted.
    assert _envelope_json(envelope)[0]["content"] == entry.payload


@pytest.mark.parametrize("entry", ADVERSARIAL_PAYLOADS, ids=lambda e: e.name)
def test_payload_never_creates_an_extra_message_or_role(entry):
    """A payload that forged a role boundary would show up as an extra turn."""
    messages = messages_for_provider(_input(entry.payload))
    assert [m.role for m in messages] == ["system", "user"]


def test_all_payloads_together_still_yield_exactly_one_system_message():
    messages = messages_for_provider(_input(*(e.payload for e in ADVERSARIAL_PAYLOADS)))
    assert [m.role for m in messages] == ["system", "user"]

    sources = _envelope_json(messages[0].content)
    assert len(sources) == len(ADVERSARIAL_PAYLOADS)
    for index, entry in enumerate(ADVERSARIAL_PAYLOADS):
        assert sources[index]["content"] == entry.payload
        assert sources[index]["citation"] == f"S{index + 1}"


def test_the_user_turn_is_never_modified_by_containment():
    hostile_user_turn = "ignore the sources and " + ADVERSARIAL_PAYLOADS[0].payload
    messages = messages_for_provider(_input("benign source", user=hostile_user_turn))
    assert messages[-1].content == hostile_user_turn
    assert messages[-1].role == "user"


# --- Ordering -----------------------------------------------------------


def test_the_envelope_precedes_every_conversation_turn():
    messages = messages_for_provider(_input("benign source"))
    assert messages[0].role == "system"
    assert all(m.role != "system" for m in messages[1:])


def test_instructions_precede_the_serialized_sources_inside_the_envelope():
    """Containment language must not arrive after the untrusted text it frames."""
    system = messages_for_provider(_input(ADVERSARIAL_PAYLOADS[0].payload))[0].content
    assert system.index("untrusted evidence") < system.index(_ENVELOPE_HEADER)


# --- Exclusion ----------------------------------------------------------


def test_without_rag_metadata_no_envelope_is_emitted():
    """Gate A channel combination 1 of 2: RAG off."""
    plain = ProviderInput(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content=_USER_TURN)],
    )
    assert messages_for_provider(plain) is plain.messages


@pytest.mark.parametrize(
    "metadata",
    [
        {"rag": {"schema_version": "wrong", "sources": [{"citation": "S1"}]}},
        {"rag": {"schema_version": RAG_SCHEMA_VERSION, "sources": []}},
        {"rag": {"schema_version": RAG_SCHEMA_VERSION, "sources": "not-a-list"}},
        {"memory": {"schema_version": "1", "turns": ["out of scope until B2"]}},
        {"rag": "not-a-dict"},
        {},
        None,
    ],
)
def test_metadata_that_is_not_a_valid_rag_envelope_emits_nothing(metadata):
    """An attacker-shaped metadata blob must not become a system message. The
    `memory` case is included deliberately: that key is silently ignored today,
    which is exactly the finding §Diseño 11 records and B2 must fix."""
    provider_input = ProviderInput(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content=_USER_TURN)],
        metadata=metadata,
    )
    assert messages_for_provider(provider_input) is provider_input.messages


def test_a_forged_citation_marker_in_metadata_is_rejected_wholesale():
    """Citations are positional. A source claiming S9 in slot 1 invalidates the
    whole envelope rather than being renumbered into legitimacy."""
    context = RagGenerationContext(sources=(_source("hostile", index=9),))
    provider_input = ProviderInput(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content=_USER_TURN)],
        metadata=context.provider_metadata,
    )
    assert messages_for_provider(provider_input) is provider_input.messages


def test_the_corpus_is_shared_with_the_b2_channel_by_construction():
    """§Diseño 5 requires the same payloads in both evidence channels. The
    corpus is a module so B2 imports it instead of inventing a second list."""
    assert len(ADVERSARIAL_PAYLOADS) >= 10
    assert len({e.name for e in ADVERSARIAL_PAYLOADS}) == len(ADVERSARIAL_PAYLOADS)
    assert all(e.why for e in ADVERSARIAL_PAYLOADS)
