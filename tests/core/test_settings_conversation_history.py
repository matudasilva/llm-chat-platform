from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def test_conversation_history_bounds_have_inert_defaults() -> None:
    settings = Settings()

    assert settings.conversation_history_max_messages == 20
    assert settings.conversation_history_max_chars == 12_000


def test_conversation_history_bounds_parse_from_real_environment(monkeypatch) -> None:
    monkeypatch.setenv("CONVERSATION_HISTORY_MAX_MESSAGES", "8")
    monkeypatch.setenv("CONVERSATION_HISTORY_MAX_CHARS", "3500")

    settings = Settings()

    assert settings.conversation_history_max_messages == 8
    assert settings.conversation_history_max_chars == 3500


@pytest.mark.parametrize(
    "field",
    [
        "conversation_history_max_messages",
        "conversation_history_max_chars",
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_conversation_history_bounds_must_be_positive(field: str, value: int) -> None:
    # A zero message cap would silently return empty history rather than fail.
    with pytest.raises(ValidationError):
        Settings(**{field: value})
