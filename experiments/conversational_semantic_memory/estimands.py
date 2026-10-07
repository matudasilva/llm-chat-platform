"""Case-cluster estimands keep bilingual steps and denominators explicit."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from random import Random
from statistics import mean
from typing import Sequence

CLASSES = ('correct', 'stale_answer', 'contaminated_answer', 'non_conforming',
           'abstain', 'incorrect')


@dataclass(frozen=True)
class Observation:
    conceptual_case_id: str
    language: str
    step_id: str
    arm: str
    classification: str
    semantic: bool
    h3: bool
    stale_eligible: bool

    def __post_init__(self) -> None:
        if self.classification not in CLASSES or self.language not in ('en', 'es'):
            raise ValueError('invalid observation')

    @property
    def correct(self) -> int:
        return int(self.classification == 'correct')

    @property
    def stale(self) -> int:
        return int(self.classification == 'stale_answer')

    def record(self) -> dict:
        row = asdict(self)
        row['class'] = row.pop('classification')
        return dict(row, correct=self.correct, stale=self.stale)


def case_values(rows: Sequence[Observation], estimand: str, arm: str,
                language: str | None = None) -> dict[str, float]:
    """Zero-eligible cases stay absent, rather than acquiring a zero score."""
    if estimand not in ('semantic', 'h3', 'stale'):
        raise ValueError('unknown estimand')
    seen = set()
    values: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        key = (row.conceptual_case_id, row.language, row.step_id, row.arm)
        if key in seen:
            raise ValueError('duplicate observation')
        seen.add(key)
        eligible = getattr(row, 'stale_eligible' if estimand == 'stale' else estimand)
        if row.arm == arm and (language is None or row.language == language) and eligible:
            values[row.conceptual_case_id].append(row.stale if estimand == 'stale' else row.correct)
    return {case: mean(flags) for case, flags in sorted(values.items())}


def _percentile(values: list[float], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def estimate(rows: Sequence[Observation], estimand: str, comparator: str, *,
             seed: int, resamples: int = 10_000) -> dict:
    """Resample paired case differences, never independent language or arm rows."""
    if resamples < 1:
        raise ValueError('positive resample count required')
    relevant = [r for r in rows if r.arm in ('C', comparator)]
    pairs: dict[tuple[str, str, str], list[Observation]] = defaultdict(list)
    for row in relevant:
        pairs[(row.conceptual_case_id, row.language, row.step_id)].append(row)
    for pair in pairs.values():
        if len(pair) != 2 or {r.arm for r in pair} != {'C', comparator}:
            raise ValueError('missing or duplicate paired arm')
        if len({(r.semantic, r.h3, r.stale_eligible) for r in pair}) != 1:
            raise ValueError('paired eligibility differs')
    for case in {r.conceptual_case_id for r in relevant}:
        if {r.language for r in relevant if r.conceptual_case_id == case} != {'en', 'es'}:
            raise ValueError('both languages required')
    left, right = (case_values(rows, estimand, arm) for arm in ('C', comparator))
    differences = {case: left[case] - right[case] for case in left}
    values = list(differences.values())
    rng = Random(seed)
    samples = sorted(mean(rng.choices(values, k=len(values))) for _ in range(resamples)) if values else []
    per_language = {}
    for language in ('en', 'es'):
        c, x = (case_values(rows, estimand, arm, language) for arm in ('C', comparator))
        per_language[language] = mean(c[k] - x[k] for k in c) if c else None
    eligible = 'stale_eligible' if estimand == 'stale' else estimand
    return {'estimand': estimand, 'comparator': comparator, 'seed': seed,
            'resamples': resamples, 'percentile_method': 'linear',
            'estimate': mean(values) if values else None,
            'ci95': [_percentile(samples, p) for p in (.025, .975)] if samples else None,
            'included_cases': len(values),
            'excluded_cases': len({r.conceptual_case_id for r in relevant}) - len(values),
            'eligible_steps_per_arm': {a: sum(getattr(r, eligible) for r in rows if r.arm == a)
                                       for a in ('C', comparator)},
            'arm_means': {'C': mean(left.values()) if left else None,
                          comparator: mean(right.values()) if right else None},
            'case_differences': differences, 'per_language': per_language}
