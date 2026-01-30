import uuid
import pytest

from app.core.domain.types import ChatMessage
from app.core.domain.provider import ProviderInput
from app.core.providers.stub_provider import StubProvider



@pytest.mark.asyncio
async def test_stub_provider_is_deterministic_for_same_request_id_and_input() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="ok")

    request_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    messages = [ChatMessage(role="user", content="Hola, probando determinismo.")]

    inp = ProviderInput(request_id=request_id, messages=messages)

    r1 = await provider.generate(inp)
    r2 = await provider.generate(inp)

    assert r1.content == r2.content
    assert r1.provider == "stub"
    assert r1.model_version
    assert r1.prompt_version


@pytest.mark.asyncio
async def test_stub_provider_changes_output_for_different_request_id() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="ok")

    messages = [ChatMessage(role="user", content="Hola, probando determinismo.")]

    inp1 = ProviderInput(
        request_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        messages=messages,
    )
    inp2 = ProviderInput(
        request_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        messages=messages,
    )

    r1 = await provider.generate(inp1)
    r2 = await provider.generate(inp2)

    assert r1.content != r2.content


@pytest.mark.asyncio
async def test_stub_provider_error_mode_raises() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="error")

    inp = ProviderInput(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content="Esto debería fallar.")],
    )

    with pytest.raises(RuntimeError, match="simulated error"):
        await provider.generate(inp)


@pytest.mark.asyncio
async def test_stub_provider_metrics_are_coherent() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="ok")

    inp = ProviderInput(
        request_id=uuid.uuid4(),
        messages=[ChatMessage(role="user", content="uno dos tres")],
    )

    r = await provider.generate(inp)

    assert isinstance(r.input_tokens, int) and r.input_tokens >= 0
    assert isinstance(r.output_tokens, int) and r.output_tokens >= 0

    # total_tokens should be coherent when both are present
    assert r.total_tokens == r.input_tokens + r.output_tokens
