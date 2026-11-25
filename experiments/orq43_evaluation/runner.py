"""Offline-only planning for the frozen ORQ-43 comparison.

This module has no provider dispatch, network, or CLI entry point. Its plans are
not authorization or evidence that any real model's billing is bounded.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
from hashlib import sha256
import json
from pathlib import Path
from typing import Protocol

PROTOCOL = Path(__file__).resolve().parents[2] / '.framework/orqs/ORQ-43-manual-model-catalog/design/t2-frozen-evaluation-protocol.md'
PROTOCOL_SHA256 = 'da2023036a50ad3d08b25ea2d15edfc17ebcb7f4a832cff9c5ad9f29d18bd6ab'
CASES = (
    ('CHAT-EN-01', (('user', 'For my next question, remember this schedule: the repair desk is open Tuesday through Friday from 09:00 to 17:00. It is closed on Monday.'), ('assistant', 'Understood. I will use that schedule.'), ('user', 'Which weekdays is it open, and what are the hours? Answer in one short English sentence.'))),
    ('CHAT-ES-01', (('user', 'Para mi próxima pregunta, recuerda este horario: la oficina de entregas abre de lunes a jueves de 08:30 a 16:30. Cierra los viernes.'), ('assistant', 'Entendido. Tendré en cuenta ese horario.'), ('user', '¿Qué días y a qué horas abre? Responde en una oración breve en español.'))),
    ('RAG-EN-01', (('system', 'Answer only from the retrieved passage. If the passage does not state a requested fact, say that it is not stated. Do not add outside facts.\n\n<retrieved_context>\nNorthside Repair Workshop: check-in is at 08:45. The session begins at 09:00. Bring gloves. The passage does not state a fee.\n</retrieved_context>'), ('user', 'When is check-in, what should I bring, and does the passage state a fee? Answer in one short English sentence.'))),
    ('RAG-ES-01', (('system', 'Responde solo con la información del pasaje recuperado. Si el pasaje no indica un dato solicitado, di que no lo indica. No agregues información externa.\n\n<retrieved_context>\nCentro Sur: la inscripción es a las 10:00. El taller empieza a las 10:30. Hay que llevar tijeras. El pasaje no indica el costo.\n</retrieved_context>'), ('user', '¿A qué hora es la inscripción, qué debo llevar y el pasaje indica el costo? Responde en una oración breve en español.'))),
)

CASES_SHA256 = 'da968401ee68006a1bf880e6f837b511bd58f598fdd1ba46215a9d9e883cae1e'

class AdmissionError(ValueError):
    """A bound or identity could not be established."""

@dataclass(frozen=True)
class Candidate:
    name: str
    provider: str
    model: str
    location: str
    adapter: str
    counter: str
    input_rate: str
    output_rate: str
    price_expires: datetime

@dataclass(frozen=True)
class Manifest:
    run_id: str
    fixture_sha256: str
    candidates: tuple[Candidate, ...]
    input_cap: int
    output_cap: int
    ceiling_usd: str
    # Prices are USD per million tokens, rounded upward per call to this quantum.
    rounding_usd: str
    billing_terms: str

@dataclass(frozen=True)
class Count:
    payload_sha256: str
    tokens: int

class VerifiedCounter(Protocol):
    """Injected offline counter; caller is responsible for independent verification."""
    def count(self, candidate: Candidate, payload: bytes) -> Count: ...

@dataclass(frozen=True)
class PlannedCall:
    call_id: str
    candidate: Candidate
    payload: bytes
    payload_sha256: str
    input_tokens: int
    reservation_usd: Decimal

@dataclass(frozen=True)
class Plan:
    manifest_sha256: str
    run_id: str
    calls: tuple[PlannedCall, ...]
    reservation_usd: Decimal


def _decimal(value: str, *, positive: bool = False) -> Decimal:
    if type(value) is not str or len(value) > 64:
        raise AdmissionError('invalid decimal')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise AdmissionError('invalid decimal') from exc
    if not result.is_finite() or result < 0 or (positive and result == 0) or result.adjusted() > 20 or result.as_tuple().exponent < -18:
        raise AdmissionError('decimal outside supported bounds')
    return result


def _identifier(value: str) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= 200 and value == value.strip()


def preflight(manifest: Manifest, counter: VerifiedCounter, *, now: datetime, _count_payload=None) -> Plan:
    """Prepare immutable offline test payloads; never dispatches anything.

    Counting and prices are only hypothetical here: no real adapter payload or
    provider framing has been verified, and this plan cannot enable live calls.
    """
    if type(manifest) is not Manifest or not _identifier(manifest.run_id):
        raise AdmissionError('invalid manifest or run ID')
    cases_bytes = json.dumps(CASES, ensure_ascii=False, separators=(',', ':')).encode()
    if sha256(cases_bytes).hexdigest() != CASES_SHA256:
        raise AdmissionError('frozen cases mismatch')
    if manifest.fixture_sha256 != PROTOCOL_SHA256 or sha256(PROTOCOL.read_bytes()).hexdigest() != PROTOCOL_SHA256:
        raise AdmissionError('frozen protocol mismatch')
    if type(manifest.candidates) is not tuple or not 1 <= len(manifest.candidates) <= 2:
        raise AdmissionError('invalid candidates')
    if type(manifest.input_cap) is not int or not 1 <= manifest.input_cap <= 4000 or type(manifest.output_cap) is not int or not 1 <= manifest.output_cap <= 512:
        raise AdmissionError('invalid token caps')
    if manifest.billing_terms != 'offline-token-only-usd-per-million':
        raise AdmissionError('unsupported billing terms')
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise AdmissionError('timezone required')
    ceiling = _decimal(manifest.ceiling_usd, positive=True)
    quantum = _decimal(manifest.rounding_usd, positive=True)
    digits = quantum.as_tuple().digits
    exponent = quantum.as_tuple().exponent
    while digits[-1] == 0:
        digits = digits[:-1]
        exponent += 1
    if digits != (1,):
        raise AdmissionError('rounding quantum must be a power of ten')
    quantum = Decimal((0, (1,), exponent))
    names = set()
    for candidate in manifest.candidates:
        if type(candidate) is not Candidate or any(not _identifier(v) for v in (candidate.name, candidate.provider, candidate.model, candidate.location, candidate.adapter, candidate.counter)):
            raise AdmissionError('invalid candidate')
        if candidate.name in names:
            raise AdmissionError('duplicate candidate')
        names.add(candidate.name)
        if not isinstance(candidate.price_expires, datetime) or candidate.price_expires.tzinfo is None or candidate.price_expires.utcoffset() is None or candidate.price_expires <= now:
            raise AdmissionError('expired or invalid pricing')
        _decimal(candidate.input_rate)
        _decimal(candidate.output_rate)
    # Bind all admission-relevant fields, including expiry and prices.
    serial = {'run_id': manifest.run_id, 'fixture_sha256': manifest.fixture_sha256, 'input_cap': manifest.input_cap, 'output_cap': manifest.output_cap, 'ceiling_usd': manifest.ceiling_usd, 'rounding_usd': manifest.rounding_usd, 'billing_terms': manifest.billing_terms, 'candidates': [{**c.__dict__, 'price_expires': c.price_expires.isoformat()} for c in manifest.candidates]}
    manifest_hash = sha256(json.dumps(serial, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    calls = []
    with localcontext() as ctx:
        ctx.prec = 100
        for candidate in manifest.candidates:
            for case_id, messages in CASES:
                payload = json.dumps({'model': candidate.model, 'location': candidate.location, 'messages': messages, 'max_output_tokens': manifest.output_cap}, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
                digest = sha256(payload).hexdigest()
                call_id = f'{case_id}:{candidate.name}'
                count_payload = payload if _count_payload is None else _count_payload(call_id, candidate, payload, digest)
                count_digest = sha256(count_payload).hexdigest()
                try:
                    count = counter.count(candidate, count_payload)
                except Exception as exc:
                    raise AdmissionError('counter failed') from exc
                if type(count) is not Count or count.payload_sha256 != count_digest or type(count.tokens) is not int or not 0 <= count.tokens <= manifest.input_cap:
                    raise AdmissionError('invalid or unbound count')
                cost = (Decimal(count.tokens) * _decimal(candidate.input_rate) + Decimal(manifest.output_cap) * _decimal(candidate.output_rate)) / Decimal(1_000_000)
                cost = cost.quantize(quantum, rounding=ROUND_CEILING)
                calls.append(PlannedCall(call_id, candidate, payload, digest, count.tokens, cost))
        total = sum((c.reservation_usd for c in calls), Decimal(0))
    if total > ceiling:
        raise AdmissionError('ceiling exceeded')
    return Plan(manifest_hash, manifest.run_id, tuple(calls), total)
