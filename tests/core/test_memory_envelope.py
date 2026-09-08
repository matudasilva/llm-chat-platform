"""ORQ-37 T17 — the memory rendering envelope and ordering (AC6, D-6b).

D-6b's text is operator-approved verbatim; `test_envelope_text_matches_d6b_verbatim`
compares it programmatically against `spec.md`'s own code block, character for
character, so a future edit to either drifts loudly rather than silently.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_prompt import (
    MEMORY_SCHEMA_VERSION,
    _MEMORY_ENVELOPE_TEMPLATE,
    _validated_memory_events,
    messages_for_provider,
)
from app.core.domain.rag_generation import RAG_SCHEMA_VERSION
from app.core.domain.types import ChatMessage

SPEC = (
    Path(__file__).resolve().parents[2]
    / ".framework/orqs/ORQ-37-rag-in-production/spec.md"
)

CURRENT_MESSAGE = ChatMessage(role="user", content="current question")


def _memory_metadata(*events: tuple[int, str]) -> dict:
    return {
        "memory": {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "events": [{"event_id": eid, "content": content} for eid, content in events],
        }
    }


def _rag_metadata(*contents: str) -> dict:
    return {
        "rag": {
            "schema_version": RAG_SCHEMA_VERSION,
            "sources": [
                {
                    "citation": f"S{i + 1}",
                    "document_id": "11111111-1111-1111-1111-111111111111",
                    "chunk_id": "22222222-2222-2222-2222-222222222222",
                    "rank": i + 1,
                    "truncated": False,
                    "content": content,
                }
                for i, content in enumerate(contents)
            ],
        }
    }


# --- D-6b: the text itself ---------------------------------------------------


def test_envelope_text_matches_d6b_verbatim() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    start = spec.find("```\n  The following content is retrieved")
    assert start != -1, "D-6b block not found in spec.md"
    end = spec.find("```", start + 4)
    block = spec[start + 4 : end]
    lines = [line[2:] if line.startswith("  ") else line for line in block.split("\n")]
    spec_text = "\n".join(lines).rstrip("\n")

    rendered = _MEMORY_ENVELOPE_TEMPLATE.format(retrieved_memory="{retrieved_memory}")
    assert rendered == spec_text


def test_envelope_excludes_steering_phrases() -> None:
    # D-6b explicitly excludes these; a future "helpful" edit must not
    # reintroduce them.
    text = _MEMORY_ENVELOPE_TEMPLATE.lower()
    for phrase in (
        "prioritize this",
        "prefer recent evidence",
        "answer using",
        "ignore conflicting information",
    ):
        assert phrase not in text


def test_rag_instructions_are_untouched_by_the_memory_envelope() -> None:
    # D-6b's mechanism/text were decided separately from _RAG_INSTRUCTIONS;
    # adding the memory channel must not reword the existing one.
    from app.core.domain.provider_prompt import _RAG_INSTRUCTIONS

    assert "Answer using the retrieved sources when they are relevant." in _RAG_INSTRUCTIONS


# --- validation: mirrors _validated_sources' shape --------------------------


def test_validated_events_requires_the_exact_schema_version() -> None:
    metadata = _memory_metadata((1, "text"))
    metadata["memory"]["schema_version"] = "wrong-version"
    assert _validated_memory_events(metadata) is None


def test_validated_events_rejects_empty_list() -> None:
    metadata = {"memory": {"schema_version": MEMORY_SCHEMA_VERSION, "events": []}}
    assert _validated_memory_events(metadata) is None


def test_validated_events_rejects_extra_or_missing_keys() -> None:
    metadata = {
        "memory": {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "events": [{"event_id": 1, "content": "x", "extra": "field"}],
        }
    }
    assert _validated_memory_events(metadata) is None


def test_validated_events_rejects_non_int_event_id() -> None:
    metadata = {
        "memory": {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "events": [{"event_id": "1", "content": "x"}],
        }
    }
    assert _validated_memory_events(metadata) is None


def test_validated_events_rejects_bool_event_id() -> None:
    # isinstance(True, int) is True in Python -- must be excluded explicitly.
    metadata = {
        "memory": {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "events": [{"event_id": True, "content": "x"}],
        }
    }
    assert _validated_memory_events(metadata) is None


def test_no_memory_key_is_not_an_error() -> None:
    assert _validated_memory_events({"rag": {}}) is None
    assert _validated_memory_events(None) is None
    assert _validated_memory_events({}) is None


def test_valid_events_pass_through_unchanged() -> None:
    metadata = _memory_metadata((3, "gold turn"), (1, "distractor"))
    result = _validated_memory_events(metadata)
    assert result == [{"event_id": 3, "content": "gold turn"}, {"event_id": 1, "content": "distractor"}]


# --- messages_for_provider: ordering and the four channel combinations -----


def test_neither_channel_present_returns_messages_unchanged() -> None:
    result = messages_for_provider(ProviderInput(request_id=None, messages=(CURRENT_MESSAGE,)))
    assert result == (CURRENT_MESSAGE,)


def test_only_memory_present_emits_one_system_message() -> None:
    metadata = _memory_metadata((1, "evidence"))
    result = messages_for_provider(
        ProviderInput(request_id=None, messages=(CURRENT_MESSAGE,), metadata=metadata)
    )
    assert len(result) == 2
    assert result[0].role == "system"
    assert "memory_evidence" in result[0].content
    assert result[1] == CURRENT_MESSAGE


def test_only_rag_present_is_unchanged_from_before_t17() -> None:
    metadata = _rag_metadata("source text")
    result = messages_for_provider(
        ProviderInput(request_id=None, messages=(CURRENT_MESSAGE,), metadata=metadata)
    )
    assert len(result) == 2
    assert result[0].role == "system"
    assert "Retrieved sources (JSON)" in result[0].content
    assert "memory_evidence" not in result[0].content


def test_both_present_orders_memory_before_rag_before_conversation() -> None:
    metadata = {**_memory_metadata((1, "memory evidence")), **_rag_metadata("rag source")}
    result = messages_for_provider(
        ProviderInput(request_id=None, messages=(CURRENT_MESSAGE,), metadata=metadata)
    )
    assert len(result) == 3
    assert "memory_evidence" in result[0].content
    assert "Retrieved sources (JSON)" in result[1].content
    assert result[2] == CURRENT_MESSAGE


def test_memory_content_is_json_and_contains_exactly_the_given_events() -> None:
    metadata = _memory_metadata((5, "gold"), (2, "distractor"))
    result = messages_for_provider(
        ProviderInput(request_id=None, messages=(CURRENT_MESSAGE,), metadata=metadata)
    )
    match = re.search(r'<memory_evidence schema_version="1">\n(.*)\n</memory_evidence>', result[0].content, re.DOTALL)
    assert match
    payload = json.loads(match.group(1))
    assert payload == [{"event_id": 5, "content": "gold"}, {"event_id": 2, "content": "distractor"}]


def test_malformed_memory_metadata_emits_no_envelope() -> None:
    result = messages_for_provider(
        ProviderInput(
            request_id=None,
            messages=(CURRENT_MESSAGE,),
            metadata={"memory": {"schema_version": MEMORY_SCHEMA_VERSION}},  # no events
        )
    )
    assert result == (CURRENT_MESSAGE,)
