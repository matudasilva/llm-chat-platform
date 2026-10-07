"""Hand-computed case means expose accidental step or language weighting."""
import pytest

from experiments.conversational_semantic_memory.estimands import Observation, estimate


def fixture_rows():
    rows = []
    # Case a: C semantic 3/4, A 1/4; case b: C 0/2, A 2/2.
    for case, flags in [('a', [(1, 0), (1, 1)]), ('b', [(0, 1)])]:
        for language in ('en', 'es'):
            for index, (c, a) in enumerate(flags):
                if case == 'a' and language == 'es':
                    c, a = (1, 0) if index == 0 else (0, 0)
                for arm, flag in [('C', c), ('A', a), ('B', a)]:
                    rows.append(Observation(case, language, str(index), arm,
                                            'correct' if flag else 'incorrect', True, False, False))
    # Only case a contributes to H3 and stale. C H3 = 1/2, A = 1.
    # Stale denominator is two, not the ten semantic/H3 rows per arm.
    for language in ('en', 'es'):
        for arm in ('A', 'B', 'C'):
            cls = 'stale_answer' if arm == 'C' and language == 'es' else 'correct'
            rows.append(Observation('a', language, 'history', arm, cls, False, True, True))
    return rows


def test_golden_fixture_estimands():
    rows = fixture_rows()
    for comparator in ('A', 'B'):
        result = estimate(rows, 'semantic', comparator, seed=39)
        assert result['case_differences'] == {'a': .5, 'b': -1}
        assert result['estimate'] == -.25
        assert result['ci95'] == [-1, .5]
        assert result['resamples'] == 10_000 and result['seed'] == 39
        assert result['per_language'] == {'en': -.25, 'es': -.25}
    h3 = estimate(rows, 'h3', 'A', seed=39)
    assert h3['estimate'] == -.5 and h3['ci95'] == [-.5, -.5]
    assert h3['excluded_cases'] == 1
    stale = estimate(rows, 'stale', 'A', seed=39)
    assert stale['estimate'] == .5 and stale['ci95'] == [.5, .5]
    assert stale['eligible_steps_per_arm'] == {'C': 2, 'A': 2}
    assert stale['arm_means'] == {'C': .5, 'A': 0}
    assert stale['per_language'] == {'en': 0, 'es': 1}
    assert stale['excluded_cases'] == 1


def test_empty_eligibility_is_undefined_and_pairing_is_required():
    rows = [r for r in fixture_rows() if r.semantic]
    result = estimate(rows, 'stale', 'A', seed=1)
    assert result['estimate'] is None and result['ci95'] is None
    assert result['excluded_cases'] == 2
    with pytest.raises(ValueError, match='paired arm'):
        estimate(rows[1:], 'semantic', 'A', seed=1)
    with pytest.raises(ValueError, match='both languages'):
        estimate([r for r in rows if r.language == 'en'], 'semantic', 'A', seed=1)


def test_observation_binary_flags_follow_class_precedence():
    row = Observation('a', 'en', 's', 'C', 'contaminated_answer', True, False, True)
    assert row.record()['class'] == 'contaminated_answer'
    assert row.correct == row.stale == 0
