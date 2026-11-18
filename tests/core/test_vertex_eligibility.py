from dataclasses import replace
from itertools import permutations
from types import SimpleNamespace

import pytest

from app.core.providers.vertex_eligibility import CandidateEligibility, CapabilityRecord
from app.core.domain.provider_factory import _build_single_provider
from app.core.domain.disabled_provider import DisabledProvider


RECORD = CapabilityRecord("synthetic-model", ["synthetic-project"], ["synthetic-location"],
                          100, ["stream", "non-stream"], "synthetic-label")
REQUEST = dict(project="synthetic-project", location="synthetic-location", model="synthetic-model",
               configured_output=100, requested_output=100, transport="stream")


def evaluate(records=(RECORD,), **changes):
    return CandidateEligibility(records).eligible(**(REQUEST | changes))


@pytest.mark.parametrize("transport", ["stream", "non-stream"])
def test_matching_synthetic_capabilities(transport):
    assert evaluate(transport=transport)


@pytest.mark.parametrize("field", ["project", "location", "model", "transport"])
@pytest.mark.parametrize("value", [None, "", " ", "unknown", [], {}])
def test_missing_invalid_or_unknown_dimensions(field, value):
    assert not evaluate(**{field: value})


@pytest.mark.parametrize("field", ["configured_output", "requested_output"])
@pytest.mark.parametrize("value", [None, 0, -1, True, False, 1.0, "1", 101, [], {}])
def test_invalid_or_above_output_bounds(field, value):
    assert not evaluate(**{field: value})


@pytest.mark.parametrize("field", ["configured_output", "requested_output"])
def test_output_bound_is_inclusive_independently(field):
    assert evaluate(**{field: 100})
    assert not evaluate(**{field: 101})


@pytest.mark.parametrize("records", [None, [], [None], {}, "invalid"])
def test_absent_or_invalid_records_fail_closed(records):
    assert not evaluate(records)


@pytest.mark.parametrize("field,value", [
    ("model", ""), ("model", []), ("certification_id", " "),
    ("max_output", True), ("max_output", 0), ("max_output", 1.0),
    ("projects", []), ("projects", ["bad/project"]), ("projects", [[]]),
    ("locations", []), ("locations", [[]]), ("transports", []),
    ("transports", [{}]), ("transports", "stream"),
])
def test_malformed_record_invalidates_snapshot(field, value):
    assert not evaluate([replace(RECORD, **{field: value})])


def test_duplicates_invalidate_every_order_even_for_different_locations():
    duplicate = replace(RECORD, locations=["other-location"])
    for records in permutations([RECORD, duplicate]):
        assert not evaluate(records)


def test_snapshot_is_independent_of_caller_mutations_and_order():
    projects, locations, transports = ["synthetic-project"], ["synthetic-location"], ["stream"]
    record = replace(RECORD, projects=projects, locations=locations, transports=transports)
    other = replace(RECORD, model="other-model")
    for records in permutations([record, other]):
        snapshot = CandidateEligibility(list(records))
        projects.clear()
        locations.clear()
        transports.clear()
        assert snapshot.eligible(**REQUEST)
        projects.append("synthetic-project")
        locations.append("synthetic-location")
        transports.append("stream")


def test_eligibility_does_not_enable_factory():
    assert evaluate()
    cfg = SimpleNamespace(vertex_project_id="synthetic-project", vertex_location="synthetic-location",
                          vertex_model="synthetic-model", vertex_max_output_tokens=100)
    assert isinstance(_build_single_provider("vertex", cfg), DisabledProvider)
