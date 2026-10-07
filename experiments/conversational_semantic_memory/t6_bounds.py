"""Prospective T6 acceptance and compositional bounds, independent of tokenizers.

These helpers do not certify a construction plan or authorize any dispatch.
Historical extraction and cost calculations deliberately remain untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import httpx

from .cost_bound import CostBoundUnavailable
from .dataset import Case, Message
from .events import canonical_bytes
from .extraction import (
    Complete, EXTRACTOR_VERSION, EXTRACTION_MAX_OUTPUT_TOKENS,
    ExtractionResult, extract_turn,
)
from .facts import FactStore
from .generation_client import GenerationRequest, GenerationResult

# An approved acceptance allowance, never a tokenizer maximum or historical fact.
T6_EXTRACTION_RESPONSE_BYTES = 131072
assert T6_EXTRACTION_RESPONSE_BYTES == EXTRACTION_MAX_OUTPUT_TOKENS * 128


class T6ExtractionStopped(RuntimeError):
    """A response-bound violation must escape the parser and stop the session."""


def accept_response(result: GenerationResult) -> GenerationResult:
    """Check the whole decoded completion before the unchanged parser sees it."""
    try:
        size = len(result.text.encode('utf-8', errors='strict'))
    except UnicodeError as exc:
        raise T6ExtractionStopped('extraction response is not strict UTF-8') from exc
    if size > T6_EXTRACTION_RESPONSE_BYTES:
        raise T6ExtractionStopped('extraction response exceeds 131072 bytes')
    return result


class T6Extractor:
    """Own a fresh causal store and latch a bound failure across future calls.

    The caller must record the exception and stop the entire T6 run. Settlement
    of a live completion belongs to the existing client, before this check.
    Cache hits pass through the identical acceptance check. No repair is made.
    """

    def __init__(self, case: Case, complete: Complete) -> None:
        self.case = case
        self.complete = complete
        self.store = FactStore(case.tenant_id, case.conversation_id, EXTRACTOR_VERSION)
        self.stopped = False

    def _complete(self, request: GenerationRequest) -> GenerationResult:
        try:
            return accept_response(self.complete(request))
        except T6ExtractionStopped:
            self.stopped = True
            raise

    def extract(self, turn: Message) -> ExtractionResult:
        if self.stopped:
            raise T6ExtractionStopped('T6 extraction session is stopped')
        result = extract_turn(self.store, self.case, turn, self._complete)
        self.store = result.store
        return result


def _count(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise CostBoundUnavailable(f'missing or invalid {name}')
    return value


@dataclass(frozen=True)
class ResponseBounds:
    operations: int
    key_bytes: int
    value_bytes: int


def response_bounds(provenance_bytes_min: int = 1) -> ResponseBounds:
    """Use a demonstrated provenance minimum, never assume UUID-shaped IDs.

    A minimal assertion object costs 82 + P bytes, plus one comma per object;
    the surrounding facts object costs 11 bytes after that comma accounting.
    Strings are nonempty; JSON unescaping cannot increase their UTF-8 bytes.
    """
    p = _count(provenance_bytes_min, 'provenance_bytes_min')
    if p == 0:
        raise CostBoundUnavailable('provenance must be nonempty')
    r = T6_EXTRACTION_RESPONSE_BYTES
    return ResponseBounds(max(0, (r - 11) // (83 + p)),
                          max(0, r - 93 - p), max(0, r - 93 - p))


def active_slots_json_bytes(prior_responses: int) -> int:
    """Charge each surviving pair to its source response, not O times K or V.

    In compact ensure_ascii=False JSON, a key:value pair plus its comma costs
    no more than its originating assertion object. Pairs from one response
    therefore cost at most R in total. Existing apply() stores keys/values
    unchanged; dedup keeps an old pair, and retraction removes a pair. Adding
    braces gives 2 + jR, including the initially empty store. This bounds the
    request-visible active dictionary, not all audit/provenance records.
    """
    return 2 + _count(prior_responses, 'prior_responses') * T6_EXTRACTION_RESPONSE_BYTES


def extraction_payload_bytes(prior_responses: int, user_turn_bytes: int,
                             message_id: str) -> int:
    """The exact fixed shell includes the ID and empty active-dictionary braces.

    A JSON string needs at most six serialized bytes per input UTF-8 byte.
    The active dictionary is already serialized: add its aggregate growth
    once, without escaping each slot independently at its individual maximum.
    """
    shell = len(canonical_bytes({'turn': {'message_id': message_id, 'content': ''},
                                 'active_slots': {}}))
    return (shell + 6 * _count(user_turn_bytes, 'user_turn_bytes')
            + active_slots_json_bytes(prior_responses) - 2)


def full_request_bytes(request: GenerationRequest, model: str,
                       dynamic_content_bytes: Mapping[int, int]) -> int:
    """Cover both canonical guard bytes and actual HTTP JSON body serialization.

    All fixed fields remain in the measured shell. Only named content strings
    are replaced by empty strings, then charged at six bytes per UTF-8 byte.
    Callers must prove the supplied bounds and the message topology separately.
    HTTP headers and response-envelope bytes are not model input text.
    Constructing httpx.Request performs serialization only, without a client.
    """
    messages = [dict(message) for message in request.messages]
    total = 0
    for index, bound in dynamic_content_bytes.items():
        if type(index) is not int or not 0 <= index < len(messages):
            raise CostBoundUnavailable('invalid dynamic message index')
        total += _count(bound, 'content_bytes')
        messages[index]['content'] = ''
    body = {'model': model, 'messages': messages, 'temperature': request.temperature,
            'max_tokens': request.max_output_tokens}
    if request.response_format is not None:
        body['response_format'] = dict(request.response_format)
    canonical = len(canonical_bytes(body))
    wire = len(httpx.Request('POST', 'https://offline.invalid', json=body).content)
    return max(canonical, wire) + 6 * total
