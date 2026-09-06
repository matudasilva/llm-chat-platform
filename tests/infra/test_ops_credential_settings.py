"""ORQ-37 T7 — AC9 at the configuration layer.

The engine-identity tests in `test_operational_session.py` prove the wiring.
These prove the *setting* cannot be pointed at either existing credential in
the first place, which is where the mistake would actually be made: in an
`.env` file, not in code. Separate module because these are synchronous and
that file carries a module-wide `asyncio` mark.
"""
from __future__ import annotations

import pytest

# --- AC9 at the configuration layer ---------------------------------------
#
# The engine-identity tests above prove the wiring. These prove the *setting*
# cannot be pointed at either existing credential in the first place, which is
# where the mistake would actually be made — in an .env file, not in code.


def _build_settings(**overrides):
    from app.core.settings import Settings

    base = dict(
        app_env="test",
        DATABASE_URL="postgresql+asyncpg://primary/db",
        PRIMARY_PROVIDER="stub",
        FALLBACK_PROVIDER=None,
    )
    base.update(overrides)
    return Settings(**base)


def test_ops_url_may_be_unset() -> None:
    assert _build_settings().database_url_ops is None


def test_ops_url_rejected_when_equal_to_the_primary_credential() -> None:
    with pytest.raises(ValueError, match="least-privilege"):
        _build_settings(DATABASE_URL_OPS="postgresql+asyncpg://primary/db")


def test_ops_url_rejected_when_equal_to_the_rag_credential() -> None:
    with pytest.raises(ValueError, match="permission-denied"):
        _build_settings(
            DATABASE_URL_APP="postgresql+asyncpg://rag_app/db",
            DATABASE_URL_OPS="postgresql+asyncpg://rag_app/db",
        )


def test_a_distinct_ops_url_is_accepted() -> None:
    settings = _build_settings(
        DATABASE_URL_APP="postgresql+asyncpg://rag_app/db",
        DATABASE_URL_OPS="postgresql+asyncpg://chat_ops/db",
    )
    assert settings.database_url_ops == "postgresql+asyncpg://chat_ops/db"
    assert settings.database_url_ops != settings.database_url
    assert settings.database_url_ops != settings.database_url_app
