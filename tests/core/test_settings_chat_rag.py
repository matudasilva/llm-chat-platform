from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def test_chat_rag_settings_are_inert_by_default() -> None:
    settings = Settings()

    assert settings.chat_rag_augmentation_enabled is False
    assert settings.chat_rag_retrieval_timeout_s == 30.0
    assert settings.chat_rag_max_sources == 5
    assert settings.chat_rag_max_source_chars == 4_000
    assert settings.chat_rag_max_context_chars == 12_000


def test_chat_rag_requires_the_rls_application_database_url() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL_APP is required"):
        Settings(chat_rag_augmentation_enabled=True)


def test_chat_rag_settings_parse_from_real_environment(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_RAG_AUGMENTATION_ENABLED", "true")
    monkeypatch.setenv("CHAT_RAG_RETRIEVAL_TIMEOUT_S", "7.5")
    monkeypatch.setenv("CHAT_RAG_MAX_SOURCES", "3")
    monkeypatch.setenv("CHAT_RAG_MAX_SOURCE_CHARS", "900")
    monkeypatch.setenv("CHAT_RAG_MAX_CONTEXT_CHARS", "2100")
    monkeypatch.setenv(
        "DATABASE_URL_APP",
        "postgresql+asyncpg://rag:secret@postgres/llmchat",
    )

    settings = Settings()

    assert settings.chat_rag_augmentation_enabled is True
    assert settings.chat_rag_retrieval_timeout_s == 7.5
    assert settings.chat_rag_max_sources == 3
    assert settings.chat_rag_max_source_chars == 900
    assert settings.chat_rag_max_context_chars == 2100


@pytest.mark.parametrize(
    "field",
    [
        "chat_rag_retrieval_timeout_s",
        "chat_rag_max_sources",
        "chat_rag_max_source_chars",
        "chat_rag_max_context_chars",
    ],
)
def test_chat_rag_bounds_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: 0})


@pytest.mark.parametrize("rag_enabled", [False, True])
@pytest.mark.parametrize("retrieval_enabled", [False, True])
@pytest.mark.parametrize("chat_enabled", [False, True])
def test_rag_flags_are_independent(
    rag_enabled: bool,
    retrieval_enabled: bool,
    chat_enabled: bool,
) -> None:
    settings = Settings(
        rag_enabled=rag_enabled,
        retrieval_pipeline_enabled=retrieval_enabled,
        chat_rag_augmentation_enabled=chat_enabled,
        DATABASE_URL_APP=(
            "postgresql+asyncpg://rag:secret@postgres/llmchat"
            if rag_enabled or chat_enabled
            else None
        ),
    )

    assert settings.rag_enabled is rag_enabled
    assert settings.retrieval_pipeline_enabled is retrieval_enabled
    assert settings.chat_rag_augmentation_enabled is chat_enabled
