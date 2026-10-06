"""Retrieval-only arms over one pooled store; scope precedes every scorer."""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Callable, Sequence
from uuid import UUID

from app.core.domain import bm25_ranking
from app.core.domain.added_context_budget import enforce_added_context_cap
from app.core.domain.chat_memory import ChatMemoryContext, RetrievedMemoryEvent
from app.core.domain.context_packer import pack_recent_window
from app.core.domain.conversation_history import ConversationHistoryAssembler, HistoryMessage
from app.core.domain.conversation_turns import WindowPartition, build_materialized_window, group_turns
from app.core.domain.provider_prompt import render_memory_events_block
from app.core.domain.rag_generation import RagGenerationContext
from app.core.domain.retrieval_corpus import RetrievalCorpus
from app.core.domain.types import ChatMessage

from . import events
from .dataset import Case, Dataset, Message, Step
from .embedding_client import EmbeddingRequest, cosine
from .validate_pressure import declared_limits

Embed = Callable[[EmbeddingRequest], Sequence[float]]


@dataclass(frozen=True)
class RetrievalConfig:
    # A nonbinding engineering bound, not a parameter selected on dev scores.
    candidate_top_k: int = 10000
    similarity_threshold: float = 0.0
    final_top_n: int = 5

    def __post_init__(self) -> None:
        if (self.candidate_top_k < 1 or self.final_top_n < 1
                or self.final_top_n > self.candidate_top_k
                or not -1 <= self.similarity_threshold <= 1):
            raise ValueError('invalid retrieval configuration')


@dataclass(frozen=True)
class Item:
    tenant_id: str
    conversation_id: str
    item_id: str
    source_sequence: int
    content: str
    source_message_ids: tuple[str, ...]
    kind: str = 'turn'
    status: str = 'active'
    value: str | None = None
    effective_from: int = 0
    effective_until: int | None = None
    messages: tuple[Message, ...] = ()


@dataclass(frozen=True)
class PooledStore:
    items: tuple[Item, ...]

    def scoped(self, case: Case, step: Step) -> tuple[Item, ...]:
        """Filter the entire pool before materialization, embedding or scoring."""
        query_sequence = step.after_sequence + 1
        return tuple(item for item in self.items
                     if item.tenant_id == case.tenant_id
                     and item.conversation_id == case.conversation_id
                     and item.source_sequence < query_sequence
                     and item.status == 'active'
                     and item.effective_from < query_sequence
                     and (item.effective_until is None
                          or query_sequence <= item.effective_until))

    @classmethod
    def from_dataset(cls, dataset: Dataset, pool: dict) -> PooledStore:
        aliases = {v['id']: v['aliases'] for v in pool['values']}
        labels = {s['id']: s['labels'] for s in pool['slots']}
        items: list[Item] = []
        for case in dataset.cases:
            conversations = [(case.tenant_id, case.conversation_id, case.turns)] + [
                (c.tenant_id, c.conversation_id, c.turns) for c in case.canaries]
            for tenant, conversation, messages in conversations:
                by_sequence = {m.sequence: m for m in messages}
                for unit in group_turns(tuple(HistoryMessage(m.sequence, m.role, m.content)
                                             for m in messages)):
                    sources = tuple(by_sequence[m.sequence] for m in unit.messages)
                    items.append(Item(tenant, conversation, str(unit.first_sequence),
                                      max(m.sequence for m in sources), unit.document_text,
                                      tuple(m.message_id for m in sources), messages=sources))
            # Gold is authored as step snapshots, not an extraction transcript.
            # Do not infer a state between snapshots or backdate later labels.
            snapshots = sorted((s for s in case.steps if s.semantic),
                               key=lambda s: s.after_sequence)
            by_id = {m.message_id: m for m in case.turns}
            for index, step in enumerate(snapshots):
                until = snapshots[index + 1].after_sequence if index + 1 < len(snapshots) else None
                for value in step.gold_values:
                    items.append(Item(
                        case.tenant_id, case.conversation_id, f'{step.step_id}:{value}',
                        max(by_id[source].sequence for source in step.gold_source_message_ids),
                        f'{labels[case.slot][case.language]}: {aliases[value][case.language][0]}',
                        step.gold_source_message_ids, kind='fact',
                        value=aliases[value][case.language][0],
                        effective_from=step.after_sequence, effective_until=until))
            for canary in case.canaries:
                value = aliases[canary.value_id][case.language][0]
                items.append(Item(canary.tenant_id, canary.conversation_id,
                                  f'{canary.conversation_id}:fact', 1,
                                  f'{labels[case.slot][case.language]}: {value}',
                                  (canary.turns[0].message_id,), kind='fact', value=value))
        return cls(tuple(items))


@dataclass(frozen=True)
class Delivery:
    arm: str
    items: tuple[Item, ...]
    window: tuple[ChatMessage, ...]
    rendered_evidence: str
    budget_binding: bool
    facts_dropped: int


def rank_dense(items: Sequence[Item], *, case: Case, step: Step, embed: Embed,
               config: RetrievalConfig) -> tuple[Item, ...]:
    """The same pre-filter protects standalone callers and scorer spies."""
    scoped = PooledStore(tuple(items)).scoped(case, step)
    if not scoped:
        return ()
    if len(scoped) > config.candidate_top_k:
        raise ValueError('candidate_top_k would bind; increase the engineering bound')
    query = embed(EmbeddingRequest(step.question, case.tenant_id, case.conversation_id, 'query'))
    ranked = []
    for item in scoped:
        score = cosine(query, embed(EmbeddingRequest(item.content, item.tenant_id,
                                                     item.conversation_id, item.kind)))
        if not math.isfinite(score):
            raise ValueError('non-finite cosine')
        ranked.append((score, item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].source_sequence, pair[1].item_id))
    return tuple(item for score, item in ranked[:config.candidate_top_k]
                 if score >= config.similarity_threshold)[:config.final_top_n]


def pack_delivery(arm: str, window: tuple[ChatMessage, ...], window_items: Sequence[Item],
                  episodic: Sequence[Item], facts: Sequence[Item], *, question: str,
                  max_chars: int) -> Delivery:
    """Place facts first so tail-first enforcement drops episodic evidence first."""
    selected = tuple(facts) + tuple(episodic)
    memory = ChatMemoryContext(messages=window, retrieved_events=tuple(
        RetrievedMemoryEvent(int(item.item_id) if item.kind == 'turn' else
                             max((int(i.item_id) for i in episodic), default=0) + index + 1,
                             item.content if item.kind == 'turn' else events.canonical_bytes({
                                 'statement': item.content, 'value': item.value,
                                 'source_message_ids': item.source_message_ids,
                                 'status': item.status,
                             }).decode('utf-8')) for index, item in enumerate(selected)))
    before = sum(len(m.content) for m in window) + (len(render_memory_events_block(
        [e.provider_dict() for e in memory.retrieved_events])) if selected else 0)
    packed, _, _ = enforce_added_context_cap(memory_context=memory,
        rag_context=RagGenerationContext(), current_message=question, max_chars=max_chars)
    retained = selected[:len(packed.retrieved_events)]
    # Packing keeps a suffix of turns, possibly truncating its final pair.
    # Identity follows positions; repeated text cannot impersonate a source.
    original_messages = tuple(m for item in window_items for m in item.messages)
    suffix = original_messages[len(original_messages) - len(packed.messages):] if packed.messages else ()
    complete_ids = {m.message_id for m, delivered in zip(suffix, packed.messages)
                    if m.role == delivered.role and m.content == delivered.content}
    complete_window = tuple(item for item in window_items
                            if set(item.source_message_ids) <= complete_ids)
    rendered = render_memory_events_block([e.provider_dict() for e in packed.retrieved_events]) if retained else ''
    return Delivery(arm, complete_window + retained, packed.messages, rendered,
                    before > max_chars, len(facts) - sum(i.kind == 'fact' for i in retained))


async def _partition(items: Sequence[Item], case: Case,
                     limits: dict[str, int]) -> WindowPartition:
    messages = tuple(HistoryMessage(m.sequence, m.role, m.content)
                     for item in items for m in item.messages)

    class History:
        async def fetch_ordered(self, conversation_id: UUID,
                                tenant_id: str) -> tuple[HistoryMessage, ...]:
            if str(conversation_id) != case.conversation_id or tenant_id != case.tenant_id:
                raise ValueError('scope mismatch')
            return messages

    bounded = await ConversationHistoryAssembler(
        max_messages=limits['conversation_history_max_messages'],
        max_chars=limits['conversation_history_max_chars']).assemble(
            History(), UUID(case.conversation_id), case.tenant_id)
    return build_materialized_window(all_messages=messages, bounded_messages=bounded.messages)


def retrieve(store: PooledStore, case: Case, step: Step, embed: Embed,
             config: RetrievalConfig = RetrievalConfig(), *,
             limits: dict[str, int] | None = None) -> tuple[Delivery, ...]:
    limits = declared_limits() if limits is None else limits
    cap = limits['chat_prompt_max_added_context_chars']
    scoped = store.scoped(case, step)
    turns = sorted((i for i in scoped if i.kind == 'turn'), key=lambda i: i.source_sequence)
    partition = asyncio.run(_partition(turns, case, limits))
    window = pack_recent_window(tuple(ChatMessage(role=m.role, content=m.content)
                                     for m in partition.window), max_chars=cap).messages
    by_id = {int(i.item_id): i for i in turns}
    window_items = tuple(by_id[u.first_sequence] for u in partition.window_units)
    # Match identity to the already packed suffix before final enforcement.
    window_items = window_items[len(window_items) - len(window) // 2:] if window else ()
    corpus = RetrievalCorpus.from_partition(partition)
    selected, _ = bm25_ranking.pack_selected_events(
        bm25_ranking.rank_events(corpus.events, bm25_ranking.query_tokens(step.question)),
        max_chars=max(0, cap - sum(len(m.content) for m in window)))
    episodic = tuple(by_id[e.event_id] for e in selected)
    dense = rank_dense(tuple(by_id[e.event_id] for e in corpus.events), case=case,
                       step=step, embed=embed, config=config)
    facts = rank_dense(tuple(i for i in scoped if i.kind == 'fact'), case=case,
                       step=step, embed=embed, config=config)
    # Reuse A's BM25_TOP_K (5 accepted turns) and skip-and-continue character
    # budget so dense ranking cannot grant B a larger evidence allowance.
    corpus_by_id = {e.event_id: e for e in corpus.events}
    dense_selected, _ = bm25_ranking.pack_selected_events(tuple(
        bm25_ranking.RankedEvent(corpus_by_id[int(i.item_id)], 0.0) for i in dense),
        max_chars=max(0, cap - sum(len(m.content) for m in window)))
    dense_evidence = tuple(by_id[e.event_id] for e in dense_selected)
    return tuple(pack_delivery(arm, window, window_items, evidence, semantic,
                              question=step.question, max_chars=cap)
                 for arm, evidence, semantic in (
                     ('A', episodic, ()), ('B', dense_evidence, ()), ('C-ORACLE', episodic, facts)))
