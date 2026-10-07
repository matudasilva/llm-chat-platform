"""Paired source coverage is independent of staleness and answer generation."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean
from typing import Sequence

from app.core.domain.conversation_history import HistoryMessage
from app.core.domain.conversation_turns import group_turns

from .dataset import Case, Step, normalize
from .retrieval import Delivery


def isolation_counts(case: Case, delivery: Delivery) -> dict[str, int]:
    return {'cross_tenant': sum(i.tenant_id != case.tenant_id for i in delivery.items),
            'cross_conversation': sum(i.conversation_id != case.conversation_id
                                      for i in delivery.items)}


def coverage(case: Case, step: Step, delivery: Delivery,
             aliases: dict[str, Sequence[str]]) -> int:
    """Require full source turns or matching active facts, never absence of stale data."""
    if not step.semantic or not step.gold_source_message_ids:
        raise ValueError('coverage requires a semantic step with gold provenance')
    items = tuple(i for i in delivery.items if i.tenant_id == case.tenant_id
                  and i.conversation_id == case.conversation_id)
    if delivery.arm in ('A', 'B'):
        by_sequence = {m.sequence: m.message_id for m in case.turns}
        source_ids = set(step.gold_source_message_ids)
        required = {by_sequence[m.sequence] for unit in group_turns(tuple(
            HistoryMessage(m.sequence, m.role, m.content) for m in case.turns
            if m.sequence <= step.after_sequence))
                    if any(by_sequence[m.sequence] in source_ids for m in unit.messages)
                    for m in unit.messages}
        delivered = {source for item in items if item.kind == 'turn'
                     for source in item.source_message_ids}
        return int(required <= delivered)
    if delivery.arm not in ('C', 'C-ORACLE'):
        raise ValueError('unknown arm')
    valid = tuple(i for i in items if i.kind == 'fact' and i.status == 'active'
                  and i.source_sequence <= step.after_sequence
                  and i.effective_from <= step.after_sequence
                  and (i.effective_until is None or step.after_sequence < i.effective_until))
    # Require every source and value; a partially supported multi-source fact
    # cannot receive full credit. Current fixtures contain one gold value.
    gold_aliases = {normalize(a) for value in step.gold_values for a in aliases[value]}
    matching = tuple(i for i in valid if i.value is not None and normalize(i.value) in gold_aliases)
    return int(all(any(source in i.source_message_ids for i in matching)
                   for source in step.gold_source_message_ids)
               and all(any(i.value is not None and normalize(i.value) in
                           {normalize(a) for a in aliases[value]} for i in matching)
                       for value in step.gold_values))


@dataclass(frozen=True)
class Observation:
    conceptual_case_id: str
    language: str
    lexical_stratum: str
    step_id: str
    arm: str
    coverage: int
    cross_tenant: int = 0
    cross_conversation: int = 0


def delta_cov(rows: Sequence[Observation]) -> float:
    paired: dict[tuple[str, str, str], dict[str, int]] = defaultdict(dict)
    for row in rows:
        if row.arm in ('A', 'C-ORACLE'):
            key = (row.conceptual_case_id, row.language, row.step_id)
            if row.arm in paired[key]:
                raise ValueError('duplicate paired observation')
            paired[key][row.arm] = row.coverage
    cases: dict[str, list[int]] = defaultdict(list)
    for (case, language, _), arms in paired.items():
        if set(arms) != {'A', 'C-ORACLE'}:
            raise ValueError('missing paired arm')
        cases[case].append(arms['C-ORACLE'] - arms['A'])
    if not cases:
        raise ValueError('no semantic observations')
    return mean(mean(steps) for steps in cases.values())


def summarize(rows: Sequence[Observation]) -> dict:
    return {
        'per_arm_coverage': {arm: mean(r.coverage for r in rows if r.arm == arm)
                             for arm in sorted({r.arm for r in rows})},
        'delta_cov': delta_cov(rows),
        'delta_cov_per_language': {language: delta_cov([r for r in rows if r.language == language])
                                   for language in sorted({r.language for r in rows})},
        'delta_cov_per_stratum': {stratum: delta_cov([r for r in rows if r.lexical_stratum == stratum])
                                  for stratum in sorted({r.lexical_stratum for r in rows})},
        'isolation_counts': {arm: {
            'cross_tenant': sum(r.cross_tenant for r in rows if r.arm == arm),
            'cross_conversation': sum(r.cross_conversation for r in rows if r.arm == arm)}
            for arm in sorted({r.arm for r in rows})},
    }
