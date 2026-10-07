"""Set-based fact scores and explicit lifecycle expectations avoid model judging."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .dataset import Case, Step
from .extraction import ExtractionResult
from .facts import Fact, normalize_value


@dataclass(frozen=True)
class GoldFact:
    slot_key: str
    value: str
    source_role: str = 'user'
    eligible: bool = True
    prohibited: bool = False
    source_message_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class LifecycleExpectation:
    """An authored prior value's expected disposition at the scored snapshot."""
    slot_key: str
    value: str
    status: str
    successor_value: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ('superseded', 'retracted'):
            raise ValueError('expected supersession or retraction')
        if (self.status == 'superseded') != (self.successor_value is not None):
            raise ValueError('only supersession requires a successor value')


def gold_snapshot(case: Case, step: Step,
                  aliases: Mapping[str, Sequence[str]]) -> tuple[GoldFact, ...]:
    """Retain authored aliases and causal provenance instead of revealing keys."""
    if step not in case.steps:
        raise ValueError('step does not belong to case')
    if not step.semantic:
        raise ValueError('only semantic steps author current fact snapshots')
    return tuple(GoldFact(case.slot, aliases[value][0],
                          source_message_ids=step.gold_source_message_ids,
                          aliases=tuple(aliases[value])) for value in step.gold_values)


def lifecycle_gold(case: Case, step: Step,
                   aliases: Mapping[str, Sequence[str]]) -> tuple[GoldFact, ...]:
    """Recover stale provenance from authored snapshots or the initial assertion.

    The dataset grammar starts with a user assertion but does not author stale
    source ids. Fail closed unless that initial assertion contains a value alias.
    Never search arbitrary turns: hypothetical mentions are not assertions.
    """
    result = []
    for value in step.stale_values:
        sources = {source for prior in case.steps
                   if prior.after_sequence <= step.after_sequence and value in prior.gold_values
                   for source in prior.gold_source_message_ids}
        initial = min(case.turns, key=lambda m: m.sequence)
        if (not sources and initial.role == 'user' and initial.sequence <= step.after_sequence
                and any(normalize_value(alias) in normalize_value(initial.content)
                        for alias in aliases[value])):
            sources.add(initial.message_id)
        result.append(GoldFact(case.slot, aliases[value][0], eligible=False,
                               source_message_ids=tuple(sorted(sources)),
                               aliases=tuple(aliases[value])))
    return tuple(result)


def _matches(fact: Fact, gold: GoldFact) -> bool:
    return (gold.source_role == 'user'
            and bool(set(fact.source_message_ids) & set(gold.source_message_ids))
            and normalize_value(fact.value) in
            {normalize_value(value) for value in (gold.aliases or (gold.value,))})


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_extraction(facts: Sequence[Fact], gold: Sequence[GoldFact], *,
                     tenant_id: str, conversation_id: str,
                     user_message_ids: Sequence[str],
                     runs: Sequence[ExtractionResult] = (),
                     lifecycle: Sequence[LifecycleExpectation] = ()) -> dict[str, int | float | None]:
    """Score active facts; audit records supply exclusions and response failures.

    Duplicate rate is excess active normalized tuples / active records (not the
    frequency of successfully deduplicated assertions). Lifecycle denominators
    are authored expectations; absent expectations yield None, never success.
    Provenance requires all cited ids to be user-authored in the target scope.
    """
    active = [f for f in facts if f.status == 'active']
    eligible = [g for g in gold if g.eligible and not g.prohibited]
    prohibited = {normalize_value(g.value) for g in gold if g.prohibited}

    def scoped_match(fact: Fact, entry: GoldFact) -> bool:
        return (fact.tenant_id == tenant_id and fact.conversation_id == conversation_id
                and _matches(fact, entry))

    # Collapse alias-equivalent records for one authored slot, regardless of key.
    # Unmatched records keep their normalized tuple identity, as before.
    observed = set()
    matched = drifted = 0
    key_slots: dict[str, set[str]] = {}
    slot_keys: dict[str, set[str]] = {}
    for fact in active:
        matches = [i for i, entry in enumerate(eligible) if scoped_match(fact, entry)]
        if len(matches) > 1:
            raise ValueError('ambiguous gold provenance and value aliases')
        if matches:
            index = matches[0]
            entry = eligible[index]
            observed.add(('gold', index))
            matched += 1
            drifted += fact.slot_key != entry.slot_key
            key_slots.setdefault(fact.slot_key, set()).add(entry.slot_key)
            slot_keys.setdefault(entry.slot_key, set()).add(fact.slot_key)
        else:
            observed.add(('unmatched', fact.tenant_id, fact.conversation_id,
                          normalize_value(fact.slot_key), normalize_value(fact.value)))
    tp = sum(item[0] == 'gold' for item in observed)
    fp, fn = len(observed) - tp, len(eligible) - tp
    known_users = set(user_message_ids)
    provenance = sum(bool(f.source_message_ids) and set(f.source_message_ids) <= known_users
                     and f.tenant_id == tenant_id and f.conversation_id == conversation_id
                     for f in active)
    by_id = {f.fact_id: f for f in facts}

    def correct(expected: LifecycleExpectation) -> bool:
        prior_gold = [g for g in gold if g.slot_key == expected.slot_key
                      and normalize_value(expected.value) in
                      {normalize_value(v) for v in (g.aliases or (g.value,))}]
        candidates = [f for f in facts if any(scoped_match(f, g) for g in prior_gold)]
        for fact in candidates:
            if fact.status != expected.status:
                continue
            if expected.status == 'retracted':
                if fact.superseded_by is None:
                    return True
            else:
                successor = by_id.get(fact.superseded_by)
                if (successor is not None and successor.supersedes == fact.fact_id
                        and successor.tenant_id == fact.tenant_id
                        and successor.conversation_id == fact.conversation_id
                        and successor.source_sequence > fact.source_sequence
                        and any(g.slot_key == expected.slot_key
                                and normalize_value(expected.successor_value) in
                                {normalize_value(v) for v in (g.aliases or (g.value,))}
                                and scoped_match(successor, g) for g in gold)):
                    return True
        return False

    result: dict[str, int | float | None] = {
        'true_positive': tp, 'false_positive': fp, 'false_negative': fn,
        'precision': _ratio(tp, tp + fp), 'recall': _ratio(tp, tp + fn),
        'f1': _ratio(2 * tp, 2 * tp + fp + fn),
        'extracted_count': len(active),
        'matched_fact_count': matched, 'slot_key_drift_count': drifted,
        'slot_key_drift_rate': _ratio(drifted, matched),
        'slot_key_collision_count': sum(len(slots) > 1 for slots in key_slots.values())
                                    + sum(len(keys) > 1 for keys in slot_keys.values()),
        'duplicate_count': len(active) - len(observed),
        'duplicate_rate': _ratio(len(active) - len(observed), len(active)),
        'provenance_complete': provenance,
        'provenance_completeness': _ratio(provenance, len(active)),
        'non_conforming_count': sum(r.non_conforming_count for r in runs),
        'rejected_count': sum(r.rejected_count for r in runs),
    }
    # Gold values detect sensitive extractions even when the extractor renames a slot.
    result['prohibited_extraction_count'] = sum(
        op.value is not None and normalize_value(op.value) in prohibited
        for run in runs for op in run.operations) if runs else sum(
            normalize_value(f.value) in prohibited for f in active)
    for status, name in (('superseded', 'supersession'), ('retracted', 'retraction')):
        expected = [entry for entry in lifecycle if entry.status == status]
        count = sum(correct(entry) for entry in expected)
        result[f'{name}_correct'] = count
        result[f'{name}_expected'] = len(expected)
        result[f'{name}_correctness'] = _ratio(count, len(expected))
    return result


def aggregate_metrics(rows: Sequence[Mapping[str, int | float | None]]) -> dict[str, int | float | None]:
    """Micro-average snapshot counts; undefined denominators remain explicit."""
    counts = ('true_positive', 'false_positive', 'false_negative', 'extracted_count',
              'duplicate_count', 'matched_fact_count', 'slot_key_drift_count',
              'slot_key_collision_count', 'provenance_complete',
              'supersession_correct', 'supersession_expected', 'retraction_correct',
              'retraction_expected', 'prohibited_extraction_count',
              'non_conforming_count', 'rejected_count')
    result = {key: sum(int(row[key]) for row in rows) for key in counts}
    tp, fp, fn = (result[key] for key in counts[:3])
    result.update(precision=_ratio(tp, tp + fp), recall=_ratio(tp, tp + fn),
                  f1=_ratio(2 * tp, 2 * tp + fp + fn))
    for name, numerator, denominator in (
            ('duplicate_rate', 'duplicate_count', 'extracted_count'),
            ('slot_key_drift_rate', 'slot_key_drift_count', 'matched_fact_count'),
            ('provenance_completeness', 'provenance_complete', 'extracted_count'),
            ('supersession_correctness', 'supersession_correct', 'supersession_expected'),
            ('retraction_correctness', 'retraction_correct', 'retraction_expected')):
        result[name] = _ratio(result[numerator], result[denominator])
    return result
