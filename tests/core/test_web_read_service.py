from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.services.web_read import (
    WebReadBlockedError,
    WebReadFetchError,
    WebReadService,
)


def _settings(**overrides):
    base = {
        "web_read_enabled": True,
        "web_read_allow_http": False,
        "web_read_allowed_domains": ["example.com"],
        "web_read_timeout_s": 2.0,
        "web_read_max_bytes": 1024,
        "web_read_max_chars": 200,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_read_url_rejects_disallowed_domain() -> None:
    service = WebReadService(_settings())

    with pytest.raises(WebReadBlockedError, match="domain is not allowed"):
        await service.read_url("https://blocked.example.org/page")


@pytest.mark.asyncio
async def test_read_url_rejects_http_when_disabled() -> None:
    service = WebReadService(_settings(web_read_allow_http=False))

    with pytest.raises(WebReadBlockedError, match="only https is allowed"):
        await service.read_url("http://example.com/page")


@pytest.mark.asyncio
async def test_read_url_rejects_unsupported_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WebReadService(_settings())

    class FakeStreamResponse:
        def __init__(self) -> None:
            self.headers = {"content-type": "application/pdf"}
            self.url = "https://example.com/doc.pdf"
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_bytes(self):
            yield b"%PDF-1.7"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method: str, url: str):
            assert method == "GET"
            assert url == "https://example.com/doc.pdf"
            return FakeStreamResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())

    with pytest.raises(WebReadBlockedError, match="unsupported content type"):
        await service.read_url("https://example.com/doc.pdf")


@pytest.mark.asyncio
async def test_read_url_extracts_html_text_and_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WebReadService(_settings(web_read_max_chars=80))

    html = b"""
    <html>
      <head><title>Example Title</title><style>.x{color:red}</style></head>
      <body>
        <script>console.log('ignore')</script>
        <main>Hello <b>world</b> from example.</main>
      </body>
    </html>
    """

    class FakeStreamResponse:
        def __init__(self) -> None:
            self.headers = {"content-type": "text/html; charset=utf-8"}
            self.url = "https://example.com/final"
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_bytes(self):
            yield html

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method: str, url: str):
            return FakeStreamResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = await service.read_url("https://example.com/start")

    assert result.url == "https://example.com/start"
    assert result.final_url == "https://example.com/final"
    assert result.content_type == "text/html"
    assert result.title == "Example Title"
    assert result.text == "Example Title Hello world from example."
    assert result.truncated is False


@pytest.mark.asyncio
async def test_read_url_rejects_redirects_to_disallowed_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WebReadService(_settings())

    class FakeStreamResponse:
        def __init__(self) -> None:
            self.headers = {"content-type": "text/plain"}
            self.url = "https://evil.example.net/final"
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_bytes(self):
            yield b"hello"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method: str, url: str):
            return FakeStreamResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())

    with pytest.raises(WebReadBlockedError, match="domain is not allowed"):
        await service.read_url("https://example.com/start")


@pytest.mark.asyncio
async def test_read_url_truncates_large_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WebReadService(_settings(web_read_max_bytes=8, web_read_max_chars=8))

    class FakeStreamResponse:
        def __init__(self) -> None:
            self.headers = {"content-type": "text/plain"}
            self.url = "https://example.com/data"
            self.status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def aiter_bytes(self):
            yield b"abcdefgh"
            yield b"ijklmnop"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method: str, url: str):
            return FakeStreamResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = await service.read_url("https://example.com/data")

    assert result.text == "abcdefgh"
    assert result.truncated is True


@pytest.mark.asyncio
async def test_read_url_wraps_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = WebReadService(_settings())

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method: str, url: str):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())

    with pytest.raises(WebReadFetchError, match="boom"):
        await service.read_url("https://example.com/page")
