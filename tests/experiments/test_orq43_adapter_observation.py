"""Offline observations at the adapter dispatch boundary, not SDK network retries."""

import json
from uuid import uuid4

import httpx
import pytest

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_errors import ProviderError
from app.core.domain.types import ChatMessage
from app.core.providers.bedrock_provider import BedrockProvider, BedrockProviderConfig, _build_payload
from app.core.providers.vertex_provider import VertexProvider, VertexProviderConfig, _payload


def _input():
    return ProviderInput(
        request_id=uuid4(),
        messages=(ChatMessage("system", "Instructions"), ChatMessage("user", "Question"),
                  ChatMessage("assistant", "Previous answer"), ChatMessage("user", "Follow-up")),
        max_tokens=37,
    )


@pytest.mark.asyncio
async def test_bedrock_generate_observes_payload_and_one_adapter_attempt():
    class Client:
        def __init__(self):
            self.calls = []

        def converse(self, **payload):
            self.calls.append(payload)
            raise TimeoutError("offline retryable failure")

    client = Client()
    cfg = BedrockProviderConfig(region="us-east-1", model="test-model", timeout_s=1, max_attempts=1)
    request = _input()
    with pytest.raises(ProviderError) as error:
        await BedrockProvider(cfg, runtime_client=client).generate(request)

    assert error.value.retryable
    assert len(client.calls) == 1
    actual = client.calls[0]
    assert actual == _build_payload(input=request, model=cfg.model)
    assert actual["system"] == [{"text": "Instructions"}]
    assert [message["role"] for message in actual["messages"]] == ["user", "assistant", "user"]
    assert actual["inferenceConfig"]["maxTokens"] == 37


@pytest.mark.asyncio
async def test_vertex_generate_observes_payload_and_one_transport_attempt():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    async def token():
        return "offline-token"

    cfg = VertexProviderConfig(project_id="test-project", location="us-central1", model="test-model",
                               max_output_tokens=25, timeout_s=1, max_attempts=1)
    request = _input()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as error:
            await VertexProvider(cfg, http_client=client, access_token_provider=token).generate(request)

    assert error.value.retryable
    assert len(calls) == 1
    actual = json.loads(calls[0].content)
    assert actual == _payload(request, cfg)
    assert actual["systemInstruction"] == {"parts": [{"text": "Instructions"}]}
    assert [message["role"] for message in actual["contents"]] == ["user", "model", "user"]
    assert actual["generationConfig"]["maxOutputTokens"] == 25
