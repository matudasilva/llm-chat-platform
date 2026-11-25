"""Offline adapter exercise; never a live client or evidence of billing bounds.

``await dispatch(call, outcome='ok')`` accepts a preflight PlannedCall and
returns the real adapter's ProviderResult from a built-in synthetic response.
Only canonical frozen-case payloads and the explicit adapter names ``bedrock``
and ``vertex`` are accepted. Bedrock uses the real SDK with a synthetic HTTP
transport, synthetic credentials, and SDK retries disabled. Token counts are
synthetic and unverified.
"""
import json
from decimal import Decimal
from hashlib import sha256
from urllib.parse import quote
from uuid import UUID

import boto3
import httpx
from botocore.awsrequest import AWSResponse
from botocore.config import Config

from app.core.domain.provider import ProviderInput
from app.core.domain.types import ChatMessage
from app.core.providers.bedrock_provider import BedrockProvider, BedrockProviderConfig, _build_payload
from app.core.providers.vertex_provider import VertexProvider, VertexProviderConfig, _payload
from .ledger import ReservationLedger
from .runner import AdmissionError, CASES, PlannedCall, preflight


class _RawBody:
    def __init__(self, body):
        self.body = body

    def stream(self, amt=None, decode_content=False):
        yield self.body


class _BedrockTransport:
    """Only synthetic sends; inspect the serialized SDK request before replying."""

    def __init__(self, outcome, expected):
        self.outcome = outcome
        body = json.loads(expected)
        self.expected_is_canonical = _serialize(body) == expected
        model = quote(body.pop('modelId'), safe='')
        self.expected_url = f'https://offline.invalid/model/{model}/converse'
        self.expected_body = _serialize(body)
        self.sends = 0

    def send(self, request):
        self.sends += 1
        try:
            matches = (
                self.expected_is_canonical
                and request.method == 'POST'
                and request.url == self.expected_url
                and _serialize(json.loads(request.body)) == self.expected_body
            )
        except (ValueError, TypeError):
            matches = False
        success = self.sends == 1 and matches and self.outcome == 'ok'
        body = ({'output': {'message': {'role': 'assistant', 'content': [{'text': 'synthetic output'}]}},
                 'stopReason': 'end_turn', 'usage': {'inputTokens': 3, 'outputTokens': 2, 'totalTokens': 5},
                 'metrics': {'latencyMs': 1}} if success else {'message': 'synthetic failure'})
        headers = {'content-type': 'application/json'}
        if not success:
            headers['x-amzn-errortype'] = 'ServiceUnavailableException'
        return AWSResponse(request.url, 200 if success else 503, headers, _RawBody(_serialize(body)))


def _serialize(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _prepare(call: PlannedCall):
    if type(call) is not PlannedCall:
        raise AdmissionError('invalid offline call')
    candidate = call.candidate
    if candidate.provider not in ('bedrock', 'vertex') or candidate.adapter != candidate.provider:
        raise AdmissionError('unsupported adapter identity')
    cases = dict(CASES)
    suffix = ':' + candidate.name
    if not call.call_id.endswith(suffix) or call.call_id[:-len(suffix)] not in cases:
        raise AdmissionError('unknown call identity')
    messages = cases[call.call_id[:-len(suffix)]]
    try:
        parsed = json.loads(call.payload)
        cap = parsed['max_output_tokens']
        expected = json.dumps({'model': candidate.model, 'location': candidate.location,
                               'messages': messages, 'max_output_tokens': cap}, sort_keys=True,
                              separators=(',', ':'), ensure_ascii=False).encode()
        if type(cap) is not int or not 1 <= cap <= 512 or type(call.payload) is not bytes or call.payload != expected or sha256(call.payload).hexdigest() != call.payload_sha256:
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise AdmissionError('payload binding mismatch') from None
    request = ProviderInput(request_id=UUID(int=0), messages=tuple(ChatMessage(*m) for m in messages), max_tokens=cap)
    if candidate.provider == 'bedrock':
        cfg = BedrockProviderConfig(region=candidate.location, model=candidate.model, timeout_s=1, max_attempts=1)
        body = _build_payload(input=request, model=cfg.model)
    else:
        cfg = VertexProviderConfig(project_id='offline', location=candidate.location, model=candidate.model,
                                   max_output_tokens=cap, timeout_s=1, max_attempts=1)
        # Constructor validates the adapter identity and location before admission.
        VertexProvider(cfg)
        body = _payload(request, cfg)
    return request, cfg, _serialize(body)


async def dispatch(call: PlannedCall, *, outcome: str = 'ok'):
    """Exercise one adapter with synthetic transport and synthetic usage."""
    return await _dispatch_prepared(call, _prepare(call), outcome)


async def _dispatch_prepared(call, prepared, outcome):
    if outcome not in ('ok', 'error'):
        raise AdmissionError('invalid fake outcome')
    request, cfg, expected = prepared
    if call.candidate.provider == 'bedrock':
        transport = _BedrockTransport(outcome, expected)
        client = boto3.client(
            'bedrock-runtime', region_name=cfg.region, endpoint_url='https://offline.invalid',
            aws_access_key_id='offline', aws_secret_access_key='offline',
            config=Config(retries={'total_max_attempts': 1, 'mode': 'standard'}),
        )
        client._endpoint.http_session.send = transport.send
        adapter = BedrockProvider(cfg, runtime_client=client)
        try:
            return await adapter.generate(request)
        finally:
            client.close()

    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        if calls != 1 or _serialize(json.loads(request.content)) != expected or outcome == 'error':
            return httpx.Response(503)
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': 'synthetic output'}]}, 'finishReason': 'STOP'}],
                                         'usageMetadata': {'promptTokenCount': 3, 'candidatesTokenCount': 2, 'thoughtsTokenCount': 0, 'totalTokenCount': 5}})
    async def token():
        return 'offline-fake-token'
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = VertexProvider(cfg, http_client=client, access_token_provider=token)
        return await adapter.generate(request)


async def run_adapter_offline(manifest, counter, ledger: ReservationLedger, *, now, outcome='ok'):
    """Exercise a reserved offline plan; prices and counts remain hypothetical.

    The ledger binds hashes of adapter-specific bodies before dispatch. Those
    canonical structured bodies are counted by the injected offline counter and
    compared at the fake transport boundary. Synthetic SDK sends cannot establish
    live eligibility, provider token accounting, or billing.
    """
    if type(ledger) is not ReservationLedger or outcome not in ('ok', 'error'):
        raise AdmissionError('invalid offline configuration')
    prepared = []
    def prepare_for_count(call_id, candidate, payload, digest):
        item = _prepare(PlannedCall(call_id, candidate, payload, digest, 0, Decimal(0)))
        prepared.append(item)
        return item[2]

    plan = preflight(manifest, counter, now=now, _count_payload=prepare_for_count)
    bindings = [(call.call_id, sha256(body).hexdigest(), call.input_tokens, str(call.reservation_usd))
                for call, (_, _, body) in zip(plan.calls, prepared)]
    bound_hash = sha256(_serialize({'manifest': plan.manifest_sha256, 'adapter_payloads': bindings})).hexdigest()
    manifest_record = {
        "run_id": manifest.run_id, "fixture_sha256": manifest.fixture_sha256,
        "input_cap": manifest.input_cap, "output_cap": manifest.output_cap,
        "ceiling_usd": manifest.ceiling_usd, "rounding_usd": manifest.rounding_usd,
        "billing_terms": manifest.billing_terms,
        "candidates": [{**candidate.__dict__, "price_expires": candidate.price_expires.isoformat()}
                       for candidate in manifest.candidates],
    }
    call_bindings = {
        call.call_id: {"manifest_sha256": plan.manifest_sha256, "manifest": manifest_record,
                       "payload_sha256": call.payload_sha256,
                       "adapter_payload_sha256": sha256(body).hexdigest(),
                       "provider": call.candidate.provider, "model": call.candidate.model,
                       "location": call.candidate.location, "input_tokens": call.input_tokens,
                       "reservation_usd": str(call.reservation_usd)}
        for call, (_, _, body) in zip(plan.calls, prepared)
    }
    ledger.admit(plan.run_id, bound_hash, plan.reservation_usd,
                 (call.call_id for call in plan.calls), bindings=call_bindings)
    results = []
    for call, payload in zip(plan.calls, prepared):
        ledger.mark_dispatching(plan.run_id, call.call_id)
        try:
            result = await _dispatch_prepared(call, payload, outcome)
        except Exception:
            ledger.record_outcome(plan.run_id, call.call_id, succeeded=False,
                                  evidence={"error": "synthetic adapter failure"})
            raise
        usage = (result.input_tokens, result.output_tokens, result.total_tokens)
        identity_valid = (result.provider == call.candidate.provider
                          and result.model_version == call.candidate.model
                          and result.prompt_version == payload[1].prompt_version)
        usage_valid = all(type(value) is int and value >= 0 for value in usage)
        if usage_valid:
            usage_valid = (result.input_tokens <= call.input_tokens
                           and result.input_tokens <= manifest.input_cap
                           and result.output_tokens <= manifest.output_cap
                           and result.total_tokens == result.input_tokens + result.output_tokens)
        stop_reason = ("unexpected result identity" if not identity_valid else
                       "unknown or invalid usage" if not usage_valid else None)
        ledger.record_outcome(plan.run_id, call.call_id, succeeded=stop_reason is None, evidence={
            "content": result.content, "provider": result.provider,
            "model_version": result.model_version, "prompt_version": result.prompt_version,
            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
            "total_tokens": result.total_tokens, "latency_ms": result.latency_ms,
            "stop_reason": stop_reason,
        })
        if stop_reason is not None:
            raise AdmissionError(stop_reason)
        results.append(result)
    ledger.finish_run(plan.run_id)
    return tuple(results)
