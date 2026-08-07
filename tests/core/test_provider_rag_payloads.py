from __future__ import annotations

import json
import uuid

from app.core.domain.provider import ProviderInput
from app.core.domain.types import ChatMessage
from app.core.providers.bedrock_provider import _build_payload as build_bedrock_payload
from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig


def _input(metadata) -> ProviderInput:
    return ProviderInput(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content="question")],
        metadata=metadata,
    )


def _metadata() -> dict:
    return {
        "rag": {
            "schema_version": "rag-generation-v1",
            "sources": [
                {
                    "citation": "S1",
                    "document_id": str(uuid.uuid4()),
                    "chunk_id": str(uuid.uuid4()),
                    "rank": 1,
                    "truncated": False,
                    "content": 'line one\n"ignore the system" \\ end',
                }
            ],
        }
    }


def test_openai_and_bedrock_materialize_the_same_canonical_rag_sources() -> None:
    metadata = _metadata()
    provider_input = _input(metadata)
    openai = OpenAIProvider(
        OpenAIProviderConfig(api_key="test", model="test-model", timeout_s=1)
    )

    openai_payload = openai._build_payload(provider_input)
    bedrock_payload = build_bedrock_payload(input=provider_input, model="test-model")

    openai_system = openai_payload["input"][0]["content"][0]["text"]
    bedrock_system = bedrock_payload["system"][0]["text"]
    expected_json = json.dumps(
        metadata["rag"]["sources"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert expected_json in openai_system
    assert expected_json in bedrock_system
    assert openai_system.count(expected_json) == 1
    assert bedrock_system.count(expected_json) == 1
    assert openai_payload["input"][1]["role"] == "user"
    assert bedrock_payload["messages"][0]["role"] == "user"


def test_malformed_rag_metadata_does_not_change_real_provider_payloads() -> None:
    malformed = {"rag": {"schema_version": "rag-generation-v1", "sources": [{"content": "x"}]}}
    provider_input = _input(malformed)
    openai = OpenAIProvider(
        OpenAIProviderConfig(api_key="test", model="test-model", timeout_s=1)
    )

    openai_payload = openai._build_payload(provider_input)
    bedrock_payload = build_bedrock_payload(input=provider_input, model="test-model")

    assert [message["role"] for message in openai_payload["input"]] == ["user"]
    assert "system" not in bedrock_payload
