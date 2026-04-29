from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.core.settings import settings


class WebReadError(Exception):
    """Base error for controlled web read failures."""


class WebReadBlockedError(WebReadError):
    """Raised when the requested URL violates control rules."""


class WebReadFetchError(WebReadError):
    """Raised when the remote fetch fails after validation."""


@dataclass(frozen=True)
class WebReadResult:
    url: str
    final_url: str
    content_type: str
    title: str | None
    text: str
    truncated: bool


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"}:
            self._skip_depth += 1
        if lowered == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self._in_title:
            self._title_parts.append(value)
        self._parts.append(value)

    @property
    def text(self) -> str:
        return " ".join(self._parts).strip()

    @property
    def title(self) -> str | None:
        title = " ".join(self._title_parts).strip()
        return title or None


class WebReadService:
    def __init__(self, app_settings=settings) -> None:
        self._settings = app_settings

    async def read_url(self, url: str) -> WebReadResult:
        if not self._settings.web_read_enabled:
            raise WebReadBlockedError("web read is disabled")

        self._validate_url(url)
        content, final_url, content_type, truncated = await self._fetch(url)
        self._validate_url(final_url)
        if content_type not in {"text/html", "text/plain"}:
            raise WebReadBlockedError("unsupported content type")

        title, text = self._extract_text(content, content_type)
        return WebReadResult(
            url=url,
            final_url=final_url,
            content_type=content_type,
            title=title,
            text=text[: self._settings.web_read_max_chars],
            truncated=truncated or len(text) > self._settings.web_read_max_chars,
        )

    def _validate_url(self, url: str):
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()

        if scheme not in {"http", "https"}:
            raise WebReadBlockedError("only http and https URLs are allowed")
        if scheme == "http" and not self._settings.web_read_allow_http:
            raise WebReadBlockedError("only https is allowed")
        if not host:
            raise WebReadBlockedError("host is required")
        if not self._is_allowed_host(host):
            raise WebReadBlockedError("domain is not allowed")

        return parsed

    def _is_allowed_host(self, host: str) -> bool:
        allowed = getattr(self._settings, "web_read_allowed_domains", []) or []
        return any(host == domain or host.endswith(f".{domain}") for domain in allowed)

    async def _fetch(self, url: str) -> tuple[bytes, str, str, bool]:
        content = bytearray()
        truncated = False

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=self._settings.web_read_timeout_s,
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    iterator = response.aiter_bytes()
                    try:
                        async for chunk in iterator:
                            remaining = self._settings.web_read_max_bytes - len(content)
                            if remaining <= 0:
                                truncated = True
                                break
                            if len(chunk) > remaining:
                                content.extend(chunk[:remaining])
                                truncated = True
                                break
                            content.extend(chunk)
                    finally:
                        aclose = getattr(iterator, "aclose", None)
                        if callable(aclose):
                            await aclose()

                    return bytes(content), str(response.url), content_type, truncated
        except httpx.HTTPStatusError as exc:
            raise WebReadFetchError(f"upstream returned {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise WebReadFetchError(str(exc)) from exc

    def _extract_text(self, content: bytes, content_type: str) -> tuple[str | None, str]:
        text = content.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            normalized = " ".join(unescape(text).split())
            return None, normalized

        parser = _HTMLTextExtractor()
        parser.feed(text)
        return parser.title, unescape(parser.text)


def get_web_read_service() -> WebReadService:
    return WebReadService(settings)
