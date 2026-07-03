from __future__ import annotations

import logging

import httpx
import pytest


@pytest.mark.asyncio
async def test_ui_still_works_but_logs_a_deprecation_warning(
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.api.routes.ui"):
        r = await client.get("/ui")

    assert r.status_code == 200
    assert any("deprecated_endpoint_used" in record.message for record in caplog.records)
