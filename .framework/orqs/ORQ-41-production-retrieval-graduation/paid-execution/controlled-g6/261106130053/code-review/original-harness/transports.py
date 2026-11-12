"""Memory-only native adapter transports and explicit invocation scopes.

The baseline path never imports the candidate observer. Script content is chosen
by named purpose, never by provider-call count or prompt inspection.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import struct
import zlib
from contextlib import contextmanager
from dataclasses import dataclass

from .fixtures import HarnessError

_purpose = contextvars.ContextVar("g123_purpose", default="primary")
_invocation = contextvars.ContextVar("g123_invocation", default=None)


@dataclass(frozen=True)
class Reply:
    text: str
    chunks: tuple[str, ...] = ()
    failure: str = "none"

    def __post_init__(self):
        if self.chunks and "".join(self.chunks) != self.text:
            raise HarnessError("script chunks must equal final content exactly")
        if self.failure not in {"none", "before", "after_token"}:
            raise HarnessError("invalid provider fault")


class Tape:
    """Baseline-owned raw transport tape; never treated as candidate receipts."""
    def __init__(self):
        self.bodies = []
        self.sends = []

    def sent(self, body, *, adapter):
        from app.http.request_context import get_request_instance_id, get_telemetry_correlation_id
        raw = body.encode() if isinstance(body, str) else bytes(body)
        self.bodies.append(raw)
        self.sends.append(dict(adapter=adapter, purpose=_purpose.get(), invocation=_invocation.get(),
                               sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
                               instance_id=get_request_instance_id(), correlation_id=get_telemetry_correlation_id()))


class Barriers:
    """Named one-shot fault points, controlled by the local test driver only."""
    def __init__(self, held=()):
        self.held = frozenset(held)
        self.reached = {}
        self.released = {}
        self.timeline = []
        self.waiters = {}

    async def hit(self, name):
        self.timeline.append((name, asyncio.get_running_loop().time()))
        self.reached.setdefault(name, asyncio.Event()).set()
        if name in self.held:
            # Middleware may run the route in a child of the exterior ASGI
            # task. Retain the actual blocked owner and its request identity.
            from .local_api import _request
            task = asyncio.current_task()
            record = dict(request=_request.get(), cancelled=asyncio.Event())
            waiters = self.waiters.setdefault(name, {})
            waiters[task] = record
            try:
                await self.released.setdefault(name, asyncio.Event()).wait()
            except asyncio.CancelledError:
                record['cancelled'].set()
                raise
            finally:
                del waiters[task]

    async def wait(self, name, timeout=10):
        await asyncio.wait_for(self.reached.setdefault(name, asyncio.Event()).wait(), timeout)

    def release(self, name):
        self.released.setdefault(name, asyncio.Event()).set()


class ScriptedProvider:
    """G3 port only. G1/G2 positive delivery requires a native adapter instead."""
    def __init__(self, replies, barriers=None):
        self.replies = dict(replies)
        self.barriers = barriers or Barriers()
        self.fault_events = []

    def reply(self):
        try:
            return self.replies[_purpose.get()]
        except KeyError as exc:
            raise HarnessError("unscripted invocation purpose") from exc

    def release_fault(self):
        from dataclasses import replace
        self.replies = {purpose: replace(reply, failure="none") for purpose, reply in self.replies.items()}

    async def generate(self, value):
        from app.core.domain.provider import ProviderResult
        await self.barriers.hit(f"{_purpose.get()}_provider_wait")
        reply = self.reply()
        if reply.failure != "none":
            self.fault_events.append("before")
            raise RuntimeError("controlled local provider failure")
        return ProviderResult(content=reply.text, provider="stub", model_version="g123-local",
                              prompt_version="g123-v1", input_tokens=1, output_tokens=1, total_tokens=2)

    async def stream(self, value):
        from app.core.domain.provider import ProviderStreamResult, ProviderStreamSession, ProviderResult
        await self.barriers.hit(f"{_purpose.get()}_provider_wait")
        reply = self.reply()
        if reply.failure == "before":
            self.fault_events.append("before")
            raise RuntimeError("controlled local provider failure")

        async def chunks():
            for index, chunk in enumerate(reply.chunks or (reply.text,)):
                yield chunk
                await self.barriers.hit("after_token" if index == 0 else "stream_token")
                if reply.failure == "after_token":
                    self.fault_events.append("after_token")
                    raise RuntimeError("controlled partial stream failure")

        async def final():
            result = ProviderResult(content=reply.text, provider="stub", model_version="g123-local", prompt_version="g123-v1")
            return ProviderStreamResult(content=reply.text, provider_result=result)
        return ProviderStreamSession(chunks=chunks(), get_final_result=final)


class ScopedProvider:
    """Keep one explicit invocation alive through the real streaming finalizer.

    Streaming is driven in one owned task so ContextVar tokens never cross ASGI
    tasks. A bounded queue applies backpressure; the task is tracked for cleanup.
    A failed initial provider.stream is raised before returning a session.
    """
    def __init__(self, provider, *, candidate, barriers=None):
        self.provider, self.candidate = provider, candidate
        self.barriers = barriers or Barriers()
        self.tasks = set()
        self.serial = 0

    @contextmanager
    def scope(self):
        self.serial += 1
        token = _invocation.set(self.serial)
        try:
            if self.candidate:
                from app.core.observability import context_evidence as c1
                from .capture import application_attempts
                purpose_token = c1._purpose.set(_purpose.get())
                try:
                    with application_attempts(), c1.invocation():
                        yield
                finally:
                    c1._purpose.reset(purpose_token)
            else:
                yield
        finally:
            _invocation.reset(token)

    async def generate(self, value):
        with self.scope():
            await self.barriers.hit("before_dispatch")
            if _purpose.get() == "primary":
                await self.barriers.hit("primary_before_dispatch")
            return await self.provider.generate(value)

    async def stream(self, value):
        from app.core.domain.provider import ProviderStreamSession
        queue = asyncio.Queue(maxsize=1)
        ready = asyncio.get_running_loop().create_future()
        end = object()

        async def worker():
            try:
                with self.scope():
                    await self.barriers.hit("before_dispatch")
                    if _purpose.get() == "primary":
                        await self.barriers.hit("primary_before_dispatch")
                    session = await self.provider.stream(value)
                    ready.set_result(None)
                    async for chunk in session.chunks:
                        await queue.put(("chunk", chunk))
                    result = await session.get_final_result()
                    await queue.put(("final", result))
            except asyncio.CancelledError:
                if not ready.done():
                    ready.cancel()
                raise
            except BaseException as exc:
                if not ready.done():
                    ready.set_exception(exc)
                else:
                    await queue.put(("error", exc))

        task = asyncio.create_task(worker())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        final_result = end
        try:
            await ready
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

        async def chunks():
            nonlocal final_result
            try:
                while True:
                    kind, item = await queue.get()
                    if kind == "error":
                        raise item
                    if kind == "final":
                        final_result = item
                        await task
                        break
                    yield item
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        async def final():
            if final_result is end:
                raise HarnessError("stream final requested before chunks completed")
            return final_result
        return ProviderStreamSession(chunks=chunks(), get_final_result=final)

    async def quiesce(self):
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks))


def with_purpose(fn, name):
    async def wrapped(*args, **kwargs):
        token = _purpose.set(name)
        try:
            return await fn(*args, **kwargs)
        finally:
            _purpose.reset(token)
    return wrapped


def event_frame(name, value):
    headers = b""
    for key, value_text in ((":message-type", "event"), (":event-type", name), (":content-type", "application/json")):
        key, value_text = key.encode(), value_text.encode()
        headers += bytes([len(key)]) + key + b"\x07" + struct.pack(">H", len(value_text)) + value_text
    body = json.dumps(value).encode()
    prelude = struct.pack(">II", 16 + len(headers) + len(body), len(headers))
    message = prelude + struct.pack(">I", zlib.crc32(prelude)) + headers + body
    return message + struct.pack(">I", zlib.crc32(message))


class Raw:
    def __init__(self, data):
        self.data = data

    def stream(self, amt=None, decode_content=False):
        yield self.data

    def close(self):
        pass


def native_provider(adapter, capture, replies, *, fault="none"):
    """Construct actual adapters with a terminal memory transport, no socket IO.

    Returns (provider, close). Fixed dummy SDK credentials are local serializer
    inputs only; metadata/credential discovery and HTTP proxies are not used.
    """
    import httpx
    if fault not in {"none", "serialize", "after_dispatch"}:
        raise HarnessError("unsupported native transport fault")
    active_fault = [fault]
    fault_events = []

    def reply():
        try:
            result = replies[_purpose.get()]
        except KeyError as exc:
            raise HarnessError("unscripted native purpose") from exc
        if result.failure != "none":
            raise HarnessError("native fault must be injected at explicit transport boundary")
        return result

    if adapter == "openai":
        from app.core.providers.openai_provider import OpenAIProvider, OpenAIProviderConfig

        def send(request):
            capture.sent(request.content, adapter="openai")
            if active_fault[0] == "after_dispatch":
                fault_events.append("after_dispatch")
                raise httpx.ReadError("controlled post-dispatch failure")
            value = reply()
            result = dict(model="g123-local", output=[dict(type="message", role="assistant", content=[dict(type="output_text", text=value.text)])],
                          usage=dict(input_tokens=1, output_tokens=1, total_tokens=2))
            if json.loads(request.content).get("stream"):
                events = [dict(type="response.output_text.delta", delta=chunk) for chunk in value.chunks or (value.text,)]
                events.append(dict(type="response.completed", response=result))
                return httpx.Response(200, text="".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events),
                                      headers={"content-type": "text/event-stream"})
            return httpx.Response(200, json=result)
        client = httpx.AsyncClient(base_url="http://127.0.0.1:9", transport=httpx.MockTransport(send), trust_env=False)
        provider = OpenAIProvider(OpenAIProviderConfig(api_key="local-only", model="g123-local", timeout_s=5, max_attempts=1), http_client=client)
        if fault == "serialize":
            original_payload = provider._build_payload
            def bad_payload(_):
                fault_events.append("serialize")
                return {"invalid": object()}
            provider._build_payload = bad_payload

        def release_fault():
            active_fault[0] = "none"
            if fault == "serialize":
                provider._build_payload = original_payload
        provider.release_fault = release_fault
        provider.fault_events = fault_events
        return provider, client.aclose
    if adapter != "bedrock":
        raise HarnessError("unsupported native adapter")
    import boto3
    from botocore.awsrequest import AWSResponse
    from botocore.config import Config
    from app.core.providers.bedrock_provider import BedrockProvider, BedrockProviderConfig

    class Session:
        def send(self, request):
            capture.sent(request.body, adapter="bedrock")
            if active_fault[0] == "after_dispatch":
                fault_events.append("after_dispatch")
                raise OSError("controlled post-dispatch failure")
            value = reply()
            if request.url.endswith("converse-stream"):
                frames = [("messageStart", dict(role="assistant"))]
                frames += [("contentBlockDelta", dict(delta=dict(text=chunk), contentBlockIndex=0)) for chunk in value.chunks or (value.text,)]
                frames += [("messageStop", dict(stopReason="end_turn")), ("metadata", dict(usage=dict(inputTokens=1, outputTokens=1, totalTokens=2), metrics=dict(latencyMs=1)))]
                return AWSResponse(request.url, 200, {"content-type": "application/vnd.amazon.eventstream"}, Raw(b"".join(event_frame(*frame) for frame in frames)))
            body = dict(output=dict(message=dict(role="assistant", content=[dict(text=value.text)])),
                        usage=dict(inputTokens=1, outputTokens=1, totalTokens=2), stopReason="end_turn")
            return AWSResponse(request.url, 200, {"content-type": "application/json"}, Raw(json.dumps(body).encode()))

        def close(self):
            pass
    client = boto3.client("bedrock-runtime", region_name="us-east-1", endpoint_url="http://127.0.0.1:9",
                          aws_access_key_id="local-only", aws_secret_access_key="local-only",
                          config=Config(retries={"total_max_attempts": 1}))
    client._endpoint.http_session = Session()
    # Candidate attempt hooks are not injected into C0.
    if capture.__class__.__name__ == "Capture":
        from .capture import sdk_attempts
        sdk_attempts(client)
    provider = BedrockProvider(BedrockProviderConfig(region="us-east-1", model="g123-local", timeout_s=5, max_attempts=1))
    provider._build_client = lambda: client
    if fault == "serialize":
        # This is an existing module-level adapter seam, isolated to the fresh
        # fault process. No production source or settings are edited.
        from app.core.providers import bedrock_provider
        original = bedrock_provider._build_payload

        def bad_payload(**kwargs):
            fault_events.append("serialize")
            payload = original(**kwargs)
            return {**payload, "messages": object()}
        bedrock_provider._build_payload = bad_payload

    def release_fault():
        active_fault[0] = "none"
        if fault == "serialize":
            bedrock_provider._build_payload = original
    provider.release_fault = release_fault
    provider.fault_events = fault_events

    async def close():
        client.close()
        if fault == "serialize":
            bedrock_provider._build_payload = original
    return provider, close
