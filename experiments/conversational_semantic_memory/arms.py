"""Assembly preserves the retrieval packer's exact rendered-character budget."""
from __future__ import annotations

from app.core.domain.provider_prompt import render_memory_events_block

from .dataset import decode_json
from .generation_client import GenerationRequest
from .retrieval import Delivery

ARMS = ('A', 'B', 'C', 'C-ORACLE', 'GOLD-CONTEXT')
ANSWER_MAX_OUTPUT_TOKENS = 256
ANSWER_CONTRACT = """Return only strict JSON with exactly two fields:
{"decision":"answer"|"abstain","values":["string"]}
Use decision answer with the requested values, or decision abstain with an empty values array
when the available evidence is insufficient. Do not add fields, Markdown, or explanations."""


def _validate_envelope(rendered: str) -> None:
    """Never allow caller-supplied framing to become a second system policy."""
    empty = render_memory_events_block([])
    prefix, suffix = empty.split('[]')
    if not rendered.startswith(prefix) or not rendered.endswith(suffix):
        raise ValueError('delivery must use the existing memory envelope')
    events = decode_json(rendered[len(prefix):-len(suffix)])
    if not isinstance(events, list) or any(
            not isinstance(event, dict) or set(event) != {'event_id', 'content'}
            or type(event['event_id']) is not int or not isinstance(event['content'], str)
            for event in events):
        raise ValueError('invalid memory event schema')
    if render_memory_events_block(events) != rendered:
        raise ValueError('delivery must use canonical memory rendering')


def answer_request(delivery: Delivery, *, tenant_id: str, conversation_id: str,
                   question: str, label: str) -> GenerationRequest:
    """All five arms consume already selected, budgeted content without reranking.

    C and C-ORACLE share the fact serialization supplied by pack_delivery;
    GOLD-CONTEXT supplies gold source turns through that same evidence path.
    An empty evidence channel is omitted, as in the runtime renderer, so no
    unbudgeted empty envelope is added after packing.
    """
    if delivery.arm not in ARMS:
        raise ValueError('unknown arm')
    if any(i.tenant_id != tenant_id or i.conversation_id != conversation_id
           for i in delivery.items):
        raise ValueError('delivery scope mismatch')
    rendered = delivery.rendered_evidence
    if rendered:
        _validate_envelope(rendered)
    if any(message.role not in ('user', 'assistant') for message in delivery.window):
        raise ValueError('window must contain ordinary conversation messages')
    messages = ({'role': 'system', 'content': ANSWER_CONTRACT},
                *(({'role': 'system', 'content': rendered},) if rendered else ()),
                *({'role': m.role, 'content': m.content} for m in delivery.window),
                {'role': 'user', 'content': question})
    return GenerationRequest(messages=messages, tenant_id=tenant_id,
                             conversation_id=conversation_id, kind='generation', label=label,
                             max_output_tokens=ANSWER_MAX_OUTPUT_TOKENS, temperature=0,
                             response_format={'type': 'json_object'})
