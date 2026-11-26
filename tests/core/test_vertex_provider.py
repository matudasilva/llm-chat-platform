import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app.core.domain.provider import ProviderInput
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.domain.types import ChatMessage
from app.core.providers.vertex_provider import VertexProvider, VertexProviderConfig


def request(*messages, **kwargs):
    return ProviderInput(request_id=uuid4(), messages=messages or (ChatMessage("user", "hi"),), **kwargs)


def cfg(**kwargs):
    values = dict(project_id="project", location="global", model="model", max_output_tokens=100,
                  timeout_s=1, max_attempts=2, backoff_base_ms=0, backoff_max_ms=0)
    return VertexProviderConfig(**(values | kwargs))


async def token():
    return "private-token"


def event(data):
    return b"data: " + json.dumps(data, ensure_ascii=False).encode() + b"\n\n"


def candidate(text=None, reason=None, **extra):
    value = {"content": {"parts": ([{"text": text}] if text is not None else []) + extra.get("parts", [])}}
    if reason:
        value["finishReason"] = reason
    return {"candidates": [value]}


class Bytes(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks, self.closed = iter(chunks), False
    def __aiter__(self):
        return self
    async def __anext__(self):
        try:
            chunk = next(self.chunks)
        except StopIteration:
            raise StopAsyncIteration from None
        if isinstance(chunk, Exception):
            raise chunk
        return chunk
    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_generate_payload_usage_and_safe_results():
    async def handler(req):
        payload = json.loads(req.content)
        assert payload["systemInstruction"]["parts"] == [{"text": "first"}, {"text": "second"}]
        assert payload["contents"] == [{"role": "user", "parts": [{"text": "hi"}]}, {"role": "model", "parts": [{"text": "prior"}]}]
        assert payload["generationConfig"]["maxOutputTokens"] == 40
        return httpx.Response(200, json={**candidate("visible", "STOP", parts=[{"text": "secret", "thought": True}, {"functionCall": {"name": "x"}}]),
                                        "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4, "thoughtsTokenCount": 2, "totalTokenCount": 9}, "modelVersion": "actual"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = VertexProvider(cfg(), http_client=client, access_token_provider=token)
        result = await p.generate(request(ChatMessage("system", "first"), ChatMessage("system", "second"), ChatMessage("user", "hi"), ChatMessage("assistant", "prior"), max_tokens=40))
    assert (result.content, result.model_version, result.input_tokens, result.output_tokens, result.total_tokens, result.raw) == ("visible", "actual", 3, 6, 9, {"model_version_source": "provider"})


@pytest.mark.asyncio
async def test_missing_reasoning_and_total_remain_unknown():
    async def handler(req):
        return httpx.Response(200, json={**candidate("x", "MAX_TOKENS"), "usageMetadata": {"candidatesTokenCount": 3}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await VertexProvider(cfg(), http_client=client, access_token_provider=token).generate(request())
    assert result.output_tokens is None and result.total_tokens is None


@pytest.mark.asyncio
async def test_missing_thoughts_counter_derives_output_from_total_minus_prompt():
    async def handler(req):
        return httpx.Response(200, json={**candidate("x", "STOP"), "usageMetadata": {"promptTokenCount": 12, "totalTokenCount": 25}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await VertexProvider(cfg(), http_client=client, access_token_provider=token).generate(request())
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (12, 13, 25)


@pytest.mark.asyncio
async def test_reject_controls_interleaving_and_invalid_endpoint():
    p = VertexProvider(cfg(), access_token_provider=token)
    for inp in (request(temperature=0.5), request(max_tokens=0), request(ChatMessage("user", "x"), ChatMessage("system", "late"))):
        with pytest.raises(ProviderError) as err:
            await p.generate(inp)
        assert err.value.kind == ProviderErrorKind.bad_request
    with pytest.raises(ProviderError):
        VertexProvider(cfg(location="evil.example"))
    assert "aiplatform.us.rep.googleapis.com" in VertexProvider(cfg(location="us")).url
    assert "europe-west1-aiplatform.googleapis.com" in VertexProvider(cfg(location="europe-west1")).url


@pytest.mark.asyncio
async def test_incremental_utf8_multiline_usage_after_finish_and_close():
    gate = asyncio.Event()
    first = event(candidate("é"))
    final = event(candidate("!", "STOP"))
    usage = b'data: {"usageMetadata":\n' + b'data: {"promptTokenCount": 2, "candidatesTokenCount": 3, "thoughtsTokenCount": 1, "totalTokenCount": 6}}\n\n'
    class Gated(Bytes):
        async def __aiter__(self):
            yield first[:first.index(b'\xc3') + 1]
            yield first[first.index(b'\xc3') + 1:]
            await gate.wait()
            yield final + usage
    stream = Gated([])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))) as client:
        session = await VertexProvider(cfg(), http_client=client, access_token_provider=token).stream(request())
        assert await anext(session.chunks) == "é"
        waiter = asyncio.create_task(session.get_final_result())
        await asyncio.sleep(0)
        assert not waiter.done()
        gate.set()
        assert [x async for x in session.chunks] == ["!"]
        result = await waiter
        assert (result.content, result.provider_result.output_tokens, result.provider_result.total_tokens) == ("é!", 4, 6)
        await session.chunks.aclose()
        assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [event(candidate("partial")), event(candidate("x", "SAFETY")), b"data: invalid\n\n", event({"promptFeedback": {"blockReason": "SAFETY"}})])
async def test_stream_failures_never_final_success(data):
    stream = Bytes([data])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))) as client:
        session = await VertexProvider(cfg(), http_client=client, access_token_provider=token).stream(request())
        with pytest.raises(ProviderError):
            async for _ in session.chunks:
                pass
        with pytest.raises(ProviderError):
            await session.get_final_result()
        assert stream.closed


@pytest.mark.asyncio
async def test_retry_before_emission_and_never_after_emission():
    calls = 0
    async def handler(req):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, stream=Bytes([event(candidate("x")), httpx.ReadError("private")]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        s = await VertexProvider(cfg(), http_client=client, access_token_provider=token).stream(request())
        assert await anext(s.chunks) == "x"
        with pytest.raises(ProviderError) as err:
            await anext(s.chunks)
        assert err.value.kind == ProviderErrorKind.network and err.value.retryable
        assert calls == 2


@pytest.mark.asyncio
async def test_auth_and_status_errors_are_safe_and_terminal():
    calls = 0
    async def bad_token():
        nonlocal calls
        calls += 1
        raise ValueError("secret")
    p = VertexProvider(cfg(), access_token_provider=bad_token)
    with pytest.raises(ProviderError) as e:
        await p.generate(request())
    assert e.value.kind == ProviderErrorKind.auth and "secret" not in str(e.value) and calls == 1
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(403, text="secret"))) as client:
        with pytest.raises(ProviderError) as e:
            await VertexProvider(cfg(), http_client=client, access_token_provider=token).generate(request())
        assert e.value.kind == ProviderErrorKind.auth and e.value.http_status == 403 and not e.value.retryable


@pytest.mark.asyncio
async def test_close_before_pull_and_cancel_during_acquisition_unblocks_final():
    started = asyncio.Event()
    calls = 0
    async def blocked_token():
        nonlocal calls
        calls += 1
        started.set()
        await asyncio.Event().wait()
    p = VertexProvider(cfg(), access_token_provider=blocked_token)
    s = await p.stream(request())
    waiter = asyncio.create_task(s.get_final_result())
    await s.chunks.aclose()
    await s.chunks.aclose()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, 1)
    assert calls == 0
    s = await p.stream(request())
    pull = asyncio.create_task(anext(s.chunks))
    await started.wait()
    waiter = asyncio.create_task(s.get_final_result())
    await s.chunks.aclose()
    with pytest.raises(asyncio.CancelledError):
        await pull
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, 1)


@pytest.mark.asyncio
async def test_midstream_close_releases_response_and_final_waiter():
    stream = Bytes([event(candidate("first")), event(candidate("second", "STOP"))])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))) as client:
        s = await VertexProvider(cfg(), http_client=client, access_token_provider=token).stream(request())
        assert await anext(s.chunks) == "first"
        waiter = asyncio.create_task(s.get_final_result())
        await s.chunks.aclose()
        await s.chunks.aclose()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiter, 1)
        assert stream.closed


@pytest.mark.asyncio
async def test_pre_emission_transport_retry_and_default_output_cap():
    calls = 0
    async def handler(req):
        nonlocal calls
        calls += 1
        assert json.loads(req.content)["generationConfig"]["maxOutputTokens"] == 100
        if calls == 1:
            raise httpx.ConnectError("secret", request=req)
        return httpx.Response(200, stream=Bytes([event(candidate("ok", "STOP"))]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        s = await VertexProvider(cfg(), http_client=client, access_token_provider=token).stream(request(max_tokens=200))
        assert [chunk async for chunk in s.chunks] == ["ok"]
        assert (await s.get_final_result()).content == "ok"
        assert calls == 2


@pytest.mark.asyncio
async def test_close_during_http_acquisition_cancels_and_unblocks_waiter():
    entered, released = asyncio.Event(), asyncio.Event()
    async def handler(req):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            released.set()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        s = await VertexProvider(cfg(), http_client=client, access_token_provider=token).stream(request())
        pull = asyncio.create_task(anext(s.chunks))
        await entered.wait()
        waiter = asyncio.create_task(s.get_final_result())
        await s.chunks.aclose()
        assert released.is_set()
        with pytest.raises(asyncio.CancelledError):
            await pull
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiter, 1)


@pytest.mark.asyncio
async def test_canonical_memory_rag_and_history_order():
    metadata = {
        "memory": {"schema_version": "rag-memory-v1", "events": [{"event_id": 1, "content": "memory evidence"}]},
        "rag": {"schema_version": "rag-generation-v1", "sources": [{"citation": "S1", "document_id": "11111111-1111-1111-1111-111111111111", "chunk_id": "22222222-2222-2222-2222-222222222222", "rank": 1, "truncated": False, "content": "rag evidence"}]},
    }
    async def handler(req):
        payload = json.loads(req.content)
        systems = payload["systemInstruction"]["parts"]
        assert len(systems) == 2
        assert "memory evidence" in systems[0]["text"] and "rag evidence" in systems[1]["text"]
        assert [item["role"] for item in payload["contents"]] == ["user", "model", "user"]
        return httpx.Response(200, json=candidate("ok", "STOP"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        p = VertexProvider(cfg(), http_client=client, access_token_provider=token)
        result = await p.generate(request(ChatMessage("user", "old"), ChatMessage("assistant", "answer"), ChatMessage("user", "new"), metadata=metadata))
        assert result.content == "ok"


@pytest.mark.parametrize("changes", [
    {"timeout_s": float("nan")}, {"timeout_s": float("inf")}, {"timeout_s": True},
    {"timeout_s": -1}, {"timeout_s": "1"}, {"max_output_tokens": True},
    {"max_output_tokens": 1.5}, {"max_output_tokens": 0}, {"max_attempts": False},
    {"max_attempts": 1.5}, {"max_attempts": 0}, {"max_attempts": 6},
    {"backoff_base_ms": True}, {"backoff_base_ms": 0.5}, {"backoff_base_ms": -1},
    {"backoff_max_ms": False}, {"backoff_max_ms": 1.5}, {"backoff_max_ms": 60001},
    {"backoff_base_ms": 5, "backoff_max_ms": 4},
])
def test_invalid_direct_configuration_is_safe_bad_request(changes):
    with pytest.raises(ProviderError) as err:
        VertexProvider(cfg(**changes))
    assert err.value.kind == ProviderErrorKind.bad_request
    assert not err.value.retryable


@pytest.mark.asyncio
async def test_compressed_sse_is_rejected_and_closed_without_decoding_or_retry():
    import gzip
    stream = Bytes([gzip.compress(event(candidate("x", "STOP")))])
    calls = 0
    async def handler(req):
        nonlocal calls
        calls += 1
        assert req.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=stream)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        s = await VertexProvider(cfg(), http_client=client, access_token_provider=token).stream(request())
        with pytest.raises(ProviderError) as err:
            await anext(s.chunks)
        assert err.value.kind == ProviderErrorKind.unknown and not err.value.retryable
        with pytest.raises(ProviderError):
            await s.get_final_result()
        assert stream.closed and calls == 1


@pytest.mark.asyncio
async def test_cancelled_close_continues_cleanup_and_later_close_joins_it():
    closing, release = asyncio.Event(), asyncio.Event()
    class BlockingClose(Bytes):
        async def aclose(self):
            closing.set()
            await release.wait()
            self.closed = True
    stream = BlockingClose([event(candidate("first"))])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, stream=stream))) as client:
        s = await VertexProvider(cfg(), http_client=client, access_token_provider=token).stream(request())
        assert await anext(s.chunks) == "first"
        waiter = asyncio.create_task(s.get_final_result())
        closer = asyncio.create_task(s.chunks.aclose())
        await asyncio.wait_for(closing.wait(), 1)
        closer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closer
        second_closer = asyncio.create_task(s.chunks.aclose())
        await asyncio.sleep(0)
        assert not stream.closed and not second_closer.done() and not waiter.done()
        release.set()
        await asyncio.wait_for(second_closer, 1)
        assert stream.closed
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(waiter, 1)


@pytest.mark.asyncio
async def test_generate_latency_includes_auth_request_and_retries(monkeypatch):
    import app.core.providers.vertex_provider as vertex_module
    times = iter([10.0, 12.75])
    monkeypatch.setattr(vertex_module, "_monotonic", lambda: next(times))
    calls = 0
    async def handler(req):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=candidate("done", "STOP"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await VertexProvider(cfg(), http_client=client, access_token_provider=token).generate(request())
    assert calls == 2 and result.latency_ms == 2750


@pytest.mark.asyncio
async def test_token_provider_normalized_error_never_exposes_credential_message():
    calls = 0
    async def bad_token():
        nonlocal calls
        calls += 1
        raise ProviderError(kind=ProviderErrorKind.timeout, message="private credential secret", provider="custom", http_status=504, retryable=True, error_code="private-token")
    p = VertexProvider(cfg(max_attempts=1), access_token_provider=bad_token)
    with pytest.raises(ProviderError) as err:
        await p.generate(request())
    error = err.value
    assert error.kind == ProviderErrorKind.timeout and error.retryable and error.http_status == 504
    assert error.provider == "vertex" and error.error_code is None and "private" not in str(error)
    assert calls == 1
