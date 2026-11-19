from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.domain.disabled_provider import DisabledProvider
from app.core.domain.provider_factory import _build_single_provider, _model_for_provider
from app.core.settings import Settings


def test_vertex_defaults_are_independent_and_disabled():
    cfg = Settings(gcp_project_id="reranker-project", gcp_rerank_location="us")
    assert (cfg.vertex_project_id, cfg.vertex_location, cfg.vertex_model, cfg.vertex_max_output_tokens) == (None, None, None, None)
    assert cfg.vertex_prompt_version == "v1"
    assert isinstance(_build_single_provider("vertex", cfg), DisabledProvider)


@pytest.mark.parametrize("field", ["provider", "fallback_provider"])
def test_vertex_cannot_be_selected_even_with_complete_settings(field):
    with pytest.raises(ValidationError):
        Settings(**{field: "vertex", "vertex_project_id": "p", "vertex_location": "us", "vertex_model": "m", "vertex_max_output_tokens": 100})


def test_vertex_factory_remains_disabled_with_complete_config():
    cfg = SimpleNamespace(vertex_project_id="p", vertex_location="us", vertex_model="m", vertex_max_output_tokens=100)
    provider = _build_single_provider("vertex", cfg)
    assert isinstance(provider, DisabledProvider)
    assert "lifecycle and cache" in provider.reason
    assert _model_for_provider("vertex", cfg) == "m"


@pytest.mark.parametrize("values", [
    {"vertex_project_id": " "}, {"vertex_location": " us"}, {"vertex_model": ""},
    {"vertex_prompt_version": ""}, {"vertex_max_output_tokens": 0},
    {"vertex_max_attempts": 0}, {"vertex_backoff_base_ms": -1},
    {"vertex_backoff_max_ms": -1}, {"vertex_backoff_base_ms": 3, "vertex_backoff_max_ms": 2},
    {"vertex_max_attempts": 6}, {"vertex_backoff_base_ms": 60001},
    {"vertex_backoff_max_ms": 60001}, {"vertex_max_output_tokens": True},
    {"vertex_max_output_tokens": 1.5}, {"vertex_max_output_tokens": 2.0},
])
def test_vertex_invalid_settings_are_rejected(values):
    with pytest.raises(ValidationError):
        Settings(**values)


def test_vertex_limits_accept_boundaries_and_integer_environment(monkeypatch):
    monkeypatch.setenv("VERTEX_MAX_OUTPUT_TOKENS", "123")
    cfg = Settings(vertex_max_attempts=5, vertex_backoff_base_ms=60000, vertex_backoff_max_ms=60000)
    assert cfg.vertex_max_output_tokens == 123
    assert cfg.vertex_max_attempts == 5
    assert cfg.vertex_backoff_max_ms == 60000


def test_existing_provider_limits_are_unchanged():
    cfg = Settings(openai_max_attempts=6, bedrock_max_attempts=6, openai_backoff_max_ms=60001, bedrock_backoff_max_ms=60001)
    assert cfg.openai_max_attempts == cfg.bedrock_max_attempts == 6
