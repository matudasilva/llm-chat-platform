"""Check source exclusion and budget pressure with real arm A primitives offline."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import UUID

from app.core.domain import bm25_ranking
from app.core.domain.added_context_budget import enforce_added_context_cap
from app.core.domain.chat_memory import ChatMemoryContext, RetrievedMemoryEvent
from app.core.domain.provider_prompt import render_memory_events_block
from app.core.domain.rag_generation import RagGenerationContext
from app.core.domain.retrieval_corpus import RetrievalCorpus
from app.core.domain.conversation_history import ConversationHistoryAssembler, HistoryMessage
from app.core.domain.conversation_turns import build_materialized_window
from app.core.domain.context_packer import pack_recent_window
from app.core.domain.types import ChatMessage
from app.core.settings import Settings

from . import events, paths
from .dataset import Case, Step, load_dataset


def declared_limits() -> dict[str, int]:
    """Read the declared experiment baseline without loading runtime environment."""
    return {name: Settings.model_fields[name].default for name in (
        'conversation_history_max_messages', 'conversation_history_max_chars',
        'chat_prompt_max_added_context_chars')}


async def check_step(case: Case, step: Step, *, conversation_history_max_messages: int,
                     conversation_history_max_chars: int,
                     chat_prompt_max_added_context_chars: int, check: str = 'out_of_window') -> dict:
    messages = tuple(HistoryMessage(m.sequence, m.role, m.content)
                     for m in case.turns if m.sequence <= step.after_sequence)

    class OfflineHistory:
        async def fetch_ordered(self, conversation_id: UUID, tenant_id: str) -> tuple[HistoryMessage, ...]:
            if str(conversation_id) != case.conversation_id or tenant_id != case.tenant_id:
                raise ValueError('scope mismatch')
            return messages

    bounded = await ConversationHistoryAssembler(
        max_messages=conversation_history_max_messages,
        max_chars=conversation_history_max_chars,
    ).assemble(OfflineHistory(), UUID(case.conversation_id), case.tenant_id)
    partition = build_materialized_window(all_messages=messages, bounded_messages=bounded.messages)
    packed = pack_recent_window([ChatMessage(role=m.role, content=m.content) for m in partition.window],
                                max_chars=chat_prompt_max_added_context_chars)
    if check == 'budget_binding':
        corpus = RetrievalCorpus.from_partition(partition)
        ranked = bm25_ranking.rank_events(corpus.events, bm25_ranking.query_tokens(step.question))
        selected, _ = bm25_ranking.pack_selected_events(
            ranked, max_chars=max(0, chat_prompt_max_added_context_chars
                                  - sum(len(m.content) for m in packed.messages)))
        memory = ChatMemoryContext(messages=packed.messages, retrieved_events=tuple(
            RetrievedMemoryEvent(e.event_id, e.document_text) for e in selected))
        # Measure the actual input to final enforcement, after BM25 packing,
        # including the evidence envelope; corpus size alone cannot pass.
        pre_cap = sum(len(m.content) for m in memory.messages) + (
            len(render_memory_events_block([e.provider_dict() for e in memory.retrieved_events]))
            if memory.retrieved_events else 0)
        delivered, _, _ = enforce_added_context_cap(
            memory_context=memory, rag_context=RagGenerationContext(),
            current_message=step.question, max_chars=chat_prompt_max_added_context_chars)
        conditions = {
            'budget_binds': pre_cap > chat_prompt_max_added_context_chars,
            'selection_is_real': len(delivered.retrieved_events) < len(corpus.events),
            'evidence_is_not_starved': bool(delivered.retrieved_events),
        }
        return {'conceptual_case_id': case.conceptual_case_id, 'language': case.language,
                'conversation_id': case.conversation_id, 'step_id': step.step_id,
                'corpus_units': len(corpus.events),
                'corpus_chars': sum(len(e.document_text) for e in corpus.events),
                'delivered_units': len(delivered.retrieved_events),
                'window_chars': sum(len(m.content) for m in packed.messages),
                'pre_cap_chars': pre_cap, 'cap': chat_prompt_max_added_context_chars,
                'conditions': conditions, 'passed': all(conditions.values())}
    source_sequences = {m.sequence for m in case.turns if m.message_id in step.gold_source_message_ids}
    source_units = [unit for unit in partition.grouped
                    if any(m.sequence in source_sequences for m in unit.messages)]
    window_sequences = {m.sequence for m in partition.window}
    overlaps = sorted({m.sequence for unit in source_units for m in unit.messages} & window_sequences)
    # Check copied source content too: a later restatement must not smuggle the
    # evidence into the packed window after its original turn was excluded.
    delivered = [m.sequence for m in messages if m.sequence in source_sequences
                 and any(m.content in recent.content for recent in packed.messages)]
    return {'conceptual_case_id': case.conceptual_case_id, 'language': case.language,
            'step_id': step.step_id, 'source_sequences': sorted(source_sequences),
            'window_sequences': sorted(window_sequences), 'overlap_sequences': overlaps,
            'delivered_source_sequences': delivered, 'passed': not overlaps and not delivered}


def run_check(*, dataset_path: Path = paths.DEV_DATASET, checks_dir: Path = paths.CHECKS_DIR,
              event_log: Path = paths.EVENTS_LOG, check: str = 'out_of_window') -> dict:
    if check not in ('out_of_window', 'budget_binding'):
        raise ValueError('unknown pressure check')
    checks_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {'check': check, 'scope': 'dev', 'passed': False, 'steps': [],
                    'limits': declared_limits()}
    try:
        digest_before = events.file_sha256(dataset_path)
        dataset = load_dataset(dataset_path)
        result['dataset_sha256'] = digest_before
        for case in dataset.cases:
            for step in case.steps:
                if step.semantic:
                    result['steps'].append(asyncio.run(check_step(case, step, check=check, **result['limits'])))
        if events.file_sha256(dataset_path) != digest_before:
            raise ValueError('dataset changed during pressure check')
        result['semantic_steps'] = len(result['steps'])
        result['passed'] = bool(result['steps']) and all(s['passed'] for s in result['steps'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['error'] = str(exc)
    output = checks_dir / ('budget-binding-dev.json' if check == 'budget_binding'
                           else 'out-of-window-check-dev.json')
    output.write_bytes(events.canonical_bytes(result) + b'\n')
    if 'dataset_sha256' in result:
        event_type = 'budget_binding_dev' if check == 'budget_binding' else 'oow_check_dev'
        events.append(event_log, event_type, {'result_sha256': events.file_sha256(output),
                                             'dataset_sha256': result['dataset_sha256'],
                                             'passed': result['passed']})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', choices=['out_of_window', 'budget_binding', 'all'], required=True)
    parser.add_argument('--scope', choices=['dev'], required=True)
    parser.add_argument('--events-log', type=Path, default=paths.EVENTS_LOG)
    args = parser.parse_args()
    checks = ('out_of_window', 'budget_binding') if args.check == 'all' else (args.check,)
    results = [run_check(event_log=args.events_log, check=check) for check in checks]
    return 0 if all(result['passed'] for result in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
