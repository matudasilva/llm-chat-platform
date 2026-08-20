"""Deterministic private development data and request preparation for ORQ-30."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

from .model import EvaluationStep, Event, Message
from .replay import (
    IsolationChallenge,
    PackedContext,
    PromptFraming,
    build_bm25_context,
    build_bounded_history,
    build_evaluation_step_audit,
    lexical_tokens,
)
from .tokenization import Encoding, canonical_event_text, event_token_count, token_count


DEVELOPMENT_CONVERSATIONS = 16
DEVELOPMENT_STEPS_PER_CONVERSATION = 4
DEVELOPMENT_ARMS = ("A", "B", "E-BM25", "ORACLE-GOLD")
DEVELOPMENT_REQUESTS = 256
AMENDED_DEVELOPMENT_ARMS = ("B", "E-BM25")
AMENDED_DEVELOPMENT_REQUESTS = 128
DEVELOPMENT_MIN_PREFIX_TOKENS = 8_192
DEVELOPMENT_MAX_PREFIX_TOKENS = 16_384

SYSTEM_INSTRUCTIONS = (
    "Return exactly one UTF-8 JSON object and no surrounding text. "
    "Use only the supplied conversation evidence. The only allowed shapes are "
    '{"decision":"answer","values":["NONCE"]} or '
    '{"decision":"abstain","values":[]}. '
    "For a question without evidence, return the exact abstention object."
)
FRAMING = PromptFraming(
    system_and_fixed_prefix=SYSTEM_INSTRUCTIONS + "\nCONVERSATION:\n",
    current_question_prefix="\nQUESTION:\n",
    current_question_suffix="\nRESPONSE:\n",
)


@dataclass(frozen=True, slots=True)
class DevelopmentConversation:
    conversation_index: int
    language: str
    events: tuple[Event, ...]
    steps: tuple[EvaluationStep, ...]
    shared_events_by_step: tuple[tuple[Event, ...], ...]
    isolation_challenges: tuple[IsolationChallenge, ...]


@dataclass(frozen=True, slots=True)
class PreparedDevelopmentRequest:
    conversation_index: int
    step: EvaluationStep
    arm_id: str
    context: PackedContext
    request_parameter_hash: str


def _event(
    tenant: str,
    conversation: str,
    event_id: str,
    sequence: int,
    user: str,
    assistant: str,
) -> Event:
    return Event(
        tenant_id=tenant,
        conversation_id=conversation,
        event_id=event_id,
        event_sequence=sequence,
        messages=(
            Message(f"{event_id}_U", "user", user),
            Message(f"{event_id}_A", "assistant", assistant),
        ),
    )


def _filler_text(encoding: Encoding, *, conversation_index: int, sequence: int) -> str:
    """Produce a deterministic neutral event of roughly 700 ordinary tokens."""

    atom = (
        f"conversation {conversation_index} archive segment {sequence} confirms routine "
        "planning notes, neutral logistics, ordinary scheduling, and non-answering context. "
    )
    text = ""
    while token_count(encoding, text) < 690:
        text += atom
    return text


def _language_questions(language: str) -> tuple[str, str, str, str]:
    if language == "en":
        return (
            "What is the current atlas verification code?",
            "What is the current beacon verification code?",
            "What is the recent harbor verification code?",
            "What is the current orchard verification code?",
        )
    return (
        "¿Cuál es el código de verificación actual de atlas?",
        "¿Cuál es el código de verificación actual de beacon?",
        "¿Cuál es el código de verificación reciente de harbor?",
        "¿Cuál es el código de verificación actual de orchard?",
    )


def _canary(
    *,
    tenant: str,
    conversation: str,
    event_id: str,
    sentinel: str,
    question: str,
) -> Event:
    question_terms = " ".join(lexical_tokens(question))
    return _event(
        tenant,
        conversation,
        event_id,
        99_000,
        f"{question_terms} competing memory request",
        f"{question_terms} competing memory answer {sentinel}",
    )


def _conversation(encoding: Encoding, conversation_index: int) -> DevelopmentConversation:
    language = "en" if conversation_index < 8 else "es"
    tenant = f"DEV_TENANT_{conversation_index:02d}"
    conversation = f"DEV_CONVERSATION_{conversation_index:02d}"
    atlas_old = f"ATLAS_OLD_{conversation_index:02d}"
    atlas_current = f"ATLAS_CURRENT_{conversation_index:02d}"
    beacon_old = f"BEACON_OLD_{conversation_index:02d}"
    beacon_current = f"BEACON_CURRENT_{conversation_index:02d}"
    harbor_current = f"HARBOR_CURRENT_{conversation_index:02d}"
    events: list[Event] = [
        _event(tenant, conversation, f"DEV_{conversation_index:02d}_E00", 0,
               "Record the previous atlas verification code.", f"The previous atlas code is {atlas_old}."),
        _event(tenant, conversation, f"DEV_{conversation_index:02d}_E01", 1,
               "Correct the atlas verification code.", f"The current atlas code replaces it with {atlas_current}."),
        _event(tenant, conversation, f"DEV_{conversation_index:02d}_E02", 2,
               "Record the previous beacon verification code.", f"The previous beacon code is {beacon_old}."),
        _event(tenant, conversation, f"DEV_{conversation_index:02d}_E03", 3,
               "Correct the beacon verification code.", f"The current beacon code replaces it with {beacon_current}."),
    ]
    for sequence in range(4, 15):
        filler = _filler_text(encoding, conversation_index=conversation_index, sequence=sequence)
        events.append(_event(
            tenant,
            conversation,
            f"DEV_{conversation_index:02d}_E{sequence:02d}",
            sequence,
            filler,
            filler,
        ))
    events.append(_event(
        tenant,
        conversation,
        f"DEV_{conversation_index:02d}_E15",
        15,
        "Record the latest harbor verification code.",
        f"The current harbor code is {harbor_current}.",
    ))
    prefix = tuple(events)
    prefix_tokens = sum(event_token_count(encoding, event) for event in prefix)
    if not DEVELOPMENT_MIN_PREFIX_TOKENS <= prefix_tokens <= DEVELOPMENT_MAX_PREFIX_TOKENS:
        raise ValueError("development prefix token count is outside the frozen range")

    questions = _language_questions(language)
    gold_rows = (
        ("primary_out_of_window_one", (prefix[1],), frozenset({atlas_current}), frozenset({atlas_old})),
        ("primary_out_of_window_two", (prefix[3],), frozenset({beacon_current}), frozenset({beacon_old})),
        ("recent_evidence_control", (prefix[15],), frozenset({harbor_current}), frozenset()),
        ("no_evidence_distractor_isolation_control", (), frozenset(), frozenset()),
    )
    steps: list[EvaluationStep] = []
    shared_by_step: list[tuple[Event, ...]] = []
    challenges: list[IsolationChallenge] = []
    for step_index, (step_type, gold_events, gold_atoms, superseded) in enumerate(gold_rows):
        step_id = f"DEV_{conversation_index:02d}_S{step_index:02d}"
        step = EvaluationStep(
            step_id=step_id,
            step_type=step_type,
            tenant_id=tenant,
            conversation_id=conversation,
            language=language,
            current_question=questions[step_index],
            authoritative_events=prefix,
            gold_event_ids=frozenset(event.event_id for event in gold_events),
            gold_message_ids=frozenset(message.message_id for event in gold_events for message in event.messages),
            gold_atoms=gold_atoms,
            superseded_atoms=superseded,
            abstention_required=not gold_atoms,
        )
        wrong_tenant_id = f"DEV_{conversation_index:02d}_S{step_index:02d}_WRONG_TENANT"
        wrong_conversation_id = f"DEV_{conversation_index:02d}_S{step_index:02d}_WRONG_CONVERSATION"
        challenge = IsolationChallenge(
            wrong_tenant_canary_event_id=wrong_tenant_id,
            wrong_tenant_sentinel_nonce=f"WRONG_TENANT_{conversation_index:02d}_{step_index:02d}",
            wrong_conversation_canary_event_id=wrong_conversation_id,
            wrong_conversation_sentinel_nonce=f"WRONG_CONVERSATION_{conversation_index:02d}_{step_index:02d}",
        )
        shared_by_step.append(prefix + (
            _canary(
                tenant=f"OTHER_TENANT_{conversation_index:02d}",
                conversation=conversation,
                event_id=wrong_tenant_id,
                sentinel=challenge.wrong_tenant_sentinel_nonce,
                question=step.current_question,
            ),
            _canary(
                tenant=tenant,
                conversation=f"OTHER_CONVERSATION_{conversation_index:02d}",
                event_id=wrong_conversation_id,
                sentinel=challenge.wrong_conversation_sentinel_nonce,
                question=step.current_question,
            ),
        ))
        steps.append(step)
        challenges.append(challenge)
    return DevelopmentConversation(
        conversation_index=conversation_index,
        language=language,
        events=prefix,
        steps=tuple(steps),
        shared_events_by_step=tuple(shared_by_step),
        isolation_challenges=tuple(challenges),
    )


def build_development_dataset(encoding: Encoding) -> tuple[DevelopmentConversation, ...]:
    """Build exactly the private, deterministic 16-conversation development split."""

    dataset = tuple(_conversation(encoding, index) for index in range(DEVELOPMENT_CONVERSATIONS))
    if sum(conversation.language == "en" for conversation in dataset) != 8:
        raise AssertionError("development language balance drifted")
    if sum(len(conversation.steps) for conversation in dataset) != 64:
        raise AssertionError("development step count drifted")
    return dataset


def _a_context(step: EvaluationStep, encoding: Encoding) -> PackedContext:
    prompt = FRAMING.render(step.current_question)
    overhead = token_count(encoding, prompt)
    if overhead > 512:
        raise ValueError("A framing exceeds its frozen input ceiling")
    return PackedContext("A", (), 0, overhead, prompt)


def _oracle_context(step: EvaluationStep, encoding: Encoding) -> PackedContext:
    gold_ids = set(step.gold_event_ids)
    gold_events = tuple(event for event in step.authoritative_events if event.event_id in gold_ids)
    history = "".join(canonical_event_text(event) for event in gold_events)
    framing = FRAMING.render(step.current_question)
    historical = token_count(encoding, history)
    overhead = token_count(encoding, framing)
    if historical + overhead > 3_072:
        raise ValueError("ORACLE-GOLD exceeds its frozen input ceiling")
    return PackedContext("ORACLE-GOLD", gold_events, historical, overhead, history + framing)


def api_request_body(prompt: str) -> bytes:
    """Canonical OpenAI Chat Completions request bytes, excluding credentials."""

    return json.dumps(
        {
            "model": "gpt-4o-mini-2024-07-18",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "top_p": 1,
            "max_tokens": 256,
            "n": 1,
            "stream": False,
            "store": False,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _request_hash(prompt: str) -> str:
    payload = api_request_body(prompt)
    return hashlib.sha256(payload).hexdigest()


def build_development_requests(
    encoding: Encoding,
    dataset: Iterable[DevelopmentConversation],
    *,
    arms: tuple[str, ...] = DEVELOPMENT_ARMS,
) -> tuple[PreparedDevelopmentRequest, ...]:
    """Derive all frozen contexts and request hashes before any external dispatch."""

    prepared: list[PreparedDevelopmentRequest] = []
    for conversation in dataset:
        for step_index, step in enumerate(conversation.steps):
            b_context, _ = build_bounded_history(step, encoding, FRAMING)
            e_context, scope_audit, _ = build_bm25_context(
                step,
                encoding,
                FRAMING,
                shared_events=conversation.shared_events_by_step[step_index],
                isolation_challenge=conversation.isolation_challenges[step_index],
            )
            contexts = {
                "A": _a_context(step, encoding),
                "B": b_context,
                "E-BM25": e_context,
                "ORACLE-GOLD": _oracle_context(step, encoding),
            }
            build_evaluation_step_audit(
                step,
                encoding,
                scope_audit=scope_audit,
                delivered_sources_by_arm={
                    arm_id: context.delivered_events for arm_id, context in contexts.items()
                },
            )
            for arm_id in arms:
                context = contexts[arm_id]
                cap = 512 if arm_id == "A" else 3_072 if arm_id == "ORACLE-GOLD" else 4_608
                if context.total_input_tokens > cap:
                    raise ValueError(f"{arm_id} request exceeds its frozen token ceiling")
                prepared.append(PreparedDevelopmentRequest(
                    conversation.conversation_index,
                    step,
                    arm_id,
                    context,
                    _request_hash(context.prompt_text),
                ))
    if not arms or any(arm not in DEVELOPMENT_ARMS for arm in arms):
        raise ValueError("development request arms are outside the frozen MVE")
    if len(prepared) != DEVELOPMENT_CONVERSATIONS * DEVELOPMENT_STEPS_PER_CONVERSATION * len(arms):
        raise AssertionError("development request count drifted")
    return tuple(prepared)


def build_amended_development_requests(
    encoding: Encoding, dataset: Iterable[DevelopmentConversation]
) -> tuple[PreparedDevelopmentRequest, ...]:
    """Prepare the separately authorized 128-attempt B/E-BM25 amendment pass."""

    prepared = build_development_requests(
        encoding, dataset, arms=AMENDED_DEVELOPMENT_ARMS
    )
    if len(prepared) != AMENDED_DEVELOPMENT_REQUESTS:
        raise AssertionError("amended development request count drifted")
    return prepared


def dataset_json(dataset: Iterable[DevelopmentConversation]) -> bytes:
    """Canonical local-only development dataset serialization."""

    rows = []
    for conversation in dataset:
        rows.append({
            "conversation_index": conversation.conversation_index,
            "language": conversation.language,
            "events": [event.canonical_payload() for event in conversation.events],
            "steps": [
                {
                    "step_id": step.step_id,
                    "step_type": step.step_type,
                    "tenant_id": step.tenant_id,
                    "conversation_id": step.conversation_id,
                    "language": step.language,
                    "current_question": step.current_question,
                    "gold_event_ids": sorted(step.gold_event_ids),
                    "gold_message_ids": sorted(step.gold_message_ids),
                    "gold_atoms": sorted(step.gold_atoms),
                    "superseded_atoms": sorted(step.superseded_atoms),
                    "abstention_required": step.abstention_required,
                }
                for step in conversation.steps
            ],
            "isolation_challenges": [
                {
                    "wrong_tenant_canary_event_id": challenge.wrong_tenant_canary_event_id,
                    "wrong_tenant_sentinel_nonce": challenge.wrong_tenant_sentinel_nonce,
                    "wrong_conversation_canary_event_id": challenge.wrong_conversation_canary_event_id,
                    "wrong_conversation_sentinel_nonce": challenge.wrong_conversation_sentinel_nonce,
                }
                for challenge in conversation.isolation_challenges
            ],
        })
    return (json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write_development_dataset(path: Path, dataset: Iterable[DevelopmentConversation]) -> str:
    payload = dataset_json(dataset)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return hashlib.sha256(payload).hexdigest()
