from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.web_read import read_web_page
from app.main import app
from app.schemas.web_read import WebReadOut
from app.services.web_read import WebReadBlockedError, WebReadFetchError, WebReadResult


class _FakeReader:
    def __init__(self, result: WebReadResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    async def read_url(self, url: str) -> WebReadResult:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def test_web_read_route_is_registered() -> None:
    assert any(route.path == "/web-read" for route in app.routes)


@pytest.mark.asyncio
async def test_web_read_returns_result() -> None:
    result = await read_web_page(
        url="https://example.com/page",
        reader=_FakeReader(
            result=WebReadResult(
                url="https://example.com/page",
                final_url="https://example.com/page",
                content_type="text/plain",
                title=None,
                text="hello world",
                truncated=False,
            )
        ),
    )

    assert isinstance(result, WebReadOut)
    assert result.model_dump() == {
        "url": "https://example.com/page",
        "final_url": "https://example.com/page",
        "content_type": "text/plain",
        "title": None,
        "text": "hello world",
        "truncated": False,
    }


@pytest.mark.asyncio
async def test_web_read_returns_403_for_blocked_urls() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await read_web_page(
            url="https://blocked.example.org",
            reader=_FakeReader(error=WebReadBlockedError("domain is not allowed")),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "domain is not allowed"


@pytest.mark.asyncio
async def test_web_read_returns_502_for_fetch_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await read_web_page(
            url="https://example.com/page",
            reader=_FakeReader(error=WebReadFetchError("upstream unavailable")),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "upstream unavailable"
