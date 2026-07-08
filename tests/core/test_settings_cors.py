import pytest

from app.core.settings import Settings


def test_cors_allow_origins_reads_comma_separated_string_from_real_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression test (ORQ-20.4): the constructor-kwarg tests below never
    # exercised pydantic-settings' real env-var parsing path, which used to
    # crash with a SettingsError trying to JSON-decode a comma-separated
    # string before this field's own validator ran.
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://example.vercel.app,http://localhost:5173")
    settings = Settings()
    assert settings.cors_allow_origins == ["https://example.vercel.app", "http://localhost:5173"]


def test_cors_allow_origins_defaults_to_local_dev_origin() -> None:
    settings = Settings()
    assert settings.cors_allow_origins == ["http://localhost:5173"]


def test_cors_allow_origins_blank_string_falls_back_to_default() -> None:
    settings = Settings(cors_allow_origins="")
    assert settings.cors_allow_origins == ["http://localhost:5173"]


def test_cors_allow_origins_parses_comma_separated_string() -> None:
    settings = Settings(cors_allow_origins="http://localhost:5173,http://localhost:4000")
    assert settings.cors_allow_origins == ["http://localhost:5173", "http://localhost:4000"]


def test_cors_allow_origins_strips_whitespace_and_drops_empty_entries() -> None:
    settings = Settings(cors_allow_origins=" http://localhost:5173 , , http://localhost:4000 ")
    assert settings.cors_allow_origins == ["http://localhost:5173", "http://localhost:4000"]


def test_cors_allow_origins_accepts_a_list_directly() -> None:
    settings = Settings(cors_allow_origins=["http://localhost:5173", " http://localhost:4000 "])
    assert settings.cors_allow_origins == ["http://localhost:5173", "http://localhost:4000"]


def test_cors_allow_origins_empty_list_falls_back_to_default() -> None:
    settings = Settings(cors_allow_origins=[])
    assert settings.cors_allow_origins == ["http://localhost:5173"]
