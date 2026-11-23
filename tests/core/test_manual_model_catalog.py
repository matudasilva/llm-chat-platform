import json
from dataclasses import FrozenInstanceError

import pytest

from app.core.domain.manual_model_catalog import parse_manual_model_catalog


ALLOWED = frozenset({("bedrock", "example.model-v1", "us-east-1"), ("vertex", "example-model-v1", "us-central1")})


def entry(**changes):
    result = {
        "id": "example", "enabled": True, "display_name": "Example model",
        "description": "A test model", "provider": "bedrock", "model": "example.model-v1",
        "location": "us-east-1", "max_output_tokens": 1024,
    }
    result.update(changes)
    return result


def parse(items):
    return parse_manual_model_catalog(json.dumps(items), allowed_models=ALLOWED)


def test_empty_catalog_and_safe_enabled_projection():
    assert parse_manual_model_catalog().entries == ()
    catalog = parse([entry(), entry(id="disabled", enabled=False), entry(id="vertex", provider="vertex", model="example-model-v1", location="us-central1")])
    assert [item.id for item in catalog.display()] == ["example", "vertex"]
    assert catalog.resolve("disabled") is None
    assert catalog.resolve("unknown") is None
    assert set(catalog.display()[0].__slots__) == {"id", "display_name", "description"}
    with pytest.raises(FrozenInstanceError):
        catalog.entries[0].enabled = False


@pytest.mark.parametrize("changes", [
    {"id": "Bad ID"}, {"enabled": 1}, {"display_name": "<script>"},
    {"description": "bad\ntext"}, {"provider": "openai"}, {"model": "other"},
    {"location": "us-west-2"}, {"max_output_tokens": 0},
    {"max_output_tokens": 65537}, {"max_output_tokens": True}, {"extra": "value"},
])
def test_invalid_entry_rejects_whole_catalog(changes):
    with pytest.raises(ValueError):
        parse([entry(), entry(id="second", **changes) if "id" not in changes else entry(**changes)])


def test_duplicate_ids_include_disabled_entries():
    with pytest.raises(ValueError):
        parse([entry(), entry(enabled=False)])


@pytest.mark.parametrize("raw", ["{", "{}", "null", '[{"id": "missing"}]', '[{"id":"a","id":"b"}]'])
def test_malformed_catalog_fails_closed(raw):
    with pytest.raises(ValueError):
        parse_manual_model_catalog(raw, allowed_models=ALLOWED)


def test_generation_is_a_coherent_deeply_immutable_snapshot():
    from app.core.domain.manual_model_catalog import build_chat_generation
    from app.core.settings import Settings

    configuration = Settings(_env_file=None, manual_model_catalog_json=json.dumps([entry()]),
                             manual_model_allowlist_json=json.dumps([list(next(iter(ALLOWED - {("vertex", "example-model-v1", "us-central1")})))]))
    generation = build_chat_generation(configuration)
    configuration.cors_allow_origins.append("https://changed.example")
    configuration.provider = "openai"
    assert generation.settings.provider == "stub"
    assert "https://changed.example" not in generation.settings.cors_allow_origins
    assert generation.catalog.resolve("example") is not None
    with pytest.raises(TypeError):
        generation.settings.cost_rates_by_provider["new"] = 1
    with pytest.raises((FrozenInstanceError, TypeError)):
        generation.settings.cost_rates_by_provider["stub"].input_per_1k = 3


def test_generation_rejects_malformed_configuration_and_disabled_vertex_gate():
    from app.core.domain.manual_model_catalog import build_chat_generation
    from app.core.settings import Settings

    with pytest.raises(ValueError):
        build_chat_generation(Settings(_env_file=None, manual_model_allowlist_json="{"))
    vertex = entry(provider="vertex", model="example-model-v1", location="us-central1")
    cfg = Settings(_env_file=None, manual_model_catalog_json=json.dumps([vertex]),
                   manual_model_allowlist_json=json.dumps([["vertex", "example-model-v1", "us-central1"]]))
    with pytest.raises(ValueError):
        build_chat_generation(cfg)
    cfg.manual_vertex_enabled = True
    with pytest.raises(ValueError):
        build_chat_generation(cfg)
    cfg.vertex_project_id = "example-project"
    assert build_chat_generation(cfg).catalog.resolve("example") is not None


@pytest.mark.asyncio
async def test_application_startup_rejects_invalid_catalog_before_database_init(monkeypatch):
    from fastapi import FastAPI
    import app.main as main

    monkeypatch.setattr(main.settings, "manual_model_catalog_json", "{")
    monkeypatch.setattr(main, "init_db", lambda app: pytest.fail("database initialized before catalog validation"))
    with pytest.raises(ValueError):
        async with main.lifespan(FastAPI()):
            pytest.fail("application started with malformed catalog")


def test_supported_vertex_locations_match_adapter():
    from app.core.domain.manual_model_catalog import _VERTEX_LOCATIONS
    from app.core.providers.vertex_provider import _REGIONS

    assert _VERTEX_LOCATIONS == _REGIONS | {"global", "us", "eu"}


@pytest.mark.parametrize("enabled", [True, False])
def test_all_entries_must_have_adapter_compatible_locations(enabled):
    from app.core.domain.manual_model_catalog import build_chat_generation
    from app.core.settings import Settings

    for provider, model, location in [("vertex", "example-model-v1", "invalid1"),
                                      ("bedrock", "example.model-v1", "invalid")]:
        item = entry(provider=provider, model=model, location=location, enabled=enabled)
        cfg = Settings(_env_file=None, manual_model_catalog_json=json.dumps([item]),
                       manual_model_allowlist_json=json.dumps([[provider, model, location]]),
                       manual_vertex_enabled=True, vertex_project_id="example-project")
        with pytest.raises(ValueError):
            build_chat_generation(cfg)
