"""Prove source-turn exclusion with the real arm A window primitives, offline."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import UUID

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
                     chat_prompt_max_added_context_chars: int) -> dict:
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
              event_log: Path = paths.EVENTS_LOG) -> dict:
    checks_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {'check': 'out_of_window', 'scope': 'dev', 'passed': False, 'steps': [],
                    'limits': declared_limits()}
    try:
        digest_before = events.file_sha256(dataset_path)
        dataset = load_dataset(dataset_path)
        result['dataset_sha256'] = digest_before
        for case in dataset.cases:
            for step in case.steps:
                if step.semantic:
                    result['steps'].append(asyncio.run(check_step(case, step, **result['limits'])))
        if events.file_sha256(dataset_path) != digest_before:
            raise ValueError('dataset changed during pressure check')
        result['semantic_steps'] = len(result['steps'])
        result['passed'] = bool(result['steps']) and all(s['passed'] for s in result['steps'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['error'] = str(exc)
    output = checks_dir / 'out-of-window-check-dev.json'
    output.write_bytes(events.canonical_bytes(result) + b'\n')
    if 'dataset_sha256' in result:
        events.append(event_log, 'oow_check_dev', {'result_sha256': events.file_sha256(output),
                                                 'dataset_sha256': result['dataset_sha256'],
                                                 'passed': result['passed']})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', choices=['out_of_window'], required=True)
    parser.add_argument('--scope', choices=['dev'], required=True)
    parser.add_argument('--events-log', type=Path, default=paths.EVENTS_LOG)
    args = parser.parse_args()
    return 0 if run_check(event_log=args.events_log)['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
