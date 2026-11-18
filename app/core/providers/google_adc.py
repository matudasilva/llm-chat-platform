"""Lazy, bounded ADC access for the Vertex adapter."""

from __future__ import annotations

import asyncio
import json
import math
import os
from collections.abc import Callable
from typing import Any

from app.core.domain.provider_errors import ProviderError, ProviderErrorKind

_SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)


def _load_file(path: str, *, scopes: tuple[str, ...], request: Any) -> tuple[Any, Any]:
    import google.auth

    # ADC files are deployment-controlled. Reject executable federation before
    # handing the configuration to the library, including nested source creds.
    with open(path, encoding="utf-8") as file:
        info = json.load(file)

    def contains_executable(value: Any) -> bool:
        if isinstance(value, dict):
            return "executable" in value or any(contains_executable(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_executable(item) for item in value)
        return False

    if contains_executable(info):
        raise ValueError("executable credentials are unsupported")
    return google.auth.load_credentials_from_file(path, scopes=scopes, request=request)


def _load_adc(*, scopes: tuple[str, ...], request: Any) -> tuple[Any, Any]:
    """Load local ADC or attached identity without invoking Cloud SDK discovery."""
    from google.auth import compute_engine

    explicit = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if explicit:
        return _load_file(explicit, scopes=scopes, request=request)
    config = os.environ.get("CLOUDSDK_CONFIG")
    if config is None:
        if os.name == "nt":
            config = os.path.join(os.environ.get("APPDATA", os.path.join(os.environ.get("SystemDrive", "C:"), "\\")), "gcloud")
        else:
            config = os.path.join(os.path.expanduser("~"), ".config", "gcloud")
    path = os.path.join(config, "application_default_credentials.json")
    if os.path.isfile(path):
        return _load_file(path, scopes=scopes, request=request)
    return compute_engine.Credentials(scopes=scopes), None


def _normalize_failure(exc: Exception) -> ProviderError:
    from google.auth import exceptions as auth_errors
    from requests import exceptions as request_errors

    chain = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    if any(isinstance(e, (TimeoutError, auth_errors.TimeoutError, request_errors.Timeout)) for e in chain):
        kind = ProviderErrorKind.timeout
    elif any(isinstance(e, (auth_errors.TransportError, request_errors.ConnectionError)) for e in chain):
        kind = ProviderErrorKind.network
    elif isinstance(exc, auth_errors.RefreshError) and exc.retryable:
        kind = ProviderErrorKind.network
    else:
        kind = ProviderErrorKind.auth
    return ProviderError(kind=kind, message="Vertex credentials unavailable", provider="vertex", retryable=kind != ProviderErrorKind.auth)


class GoogleAdcAccessTokenProvider:
    """Discover and refresh credentials only on demand, off the event loop.

    A timed-out or cancelled caller does not cancel its underlying thread. Other
    callers share that work until it ends, preventing overlapping refreshes.
    """

    def __init__(
        self,
        timeout_s: float,
        *,
        credentials_loader: Callable[..., Any] | None = None,
        request_factory: Callable[[], Any] | None = None,
    ) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("timeout_s must be finite and > 0")
        self._timeout_s = timeout_s
        self._credentials_loader = credentials_loader
        self._request_factory = request_factory
        self._credentials: Any = None
        self._task: asyncio.Task[str] | None = None

    async def __call__(self) -> str:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(asyncio.to_thread(self._load_token))
            # Retrieve exceptions even if every waiting caller is cancelled.
            self._task.add_done_callback(self._consume_exception)
        try:
            return await asyncio.wait_for(asyncio.shield(self._task), self._timeout_s)
        except TimeoutError:
            raise ProviderError(
                kind=ProviderErrorKind.timeout,
                message="Vertex credential refresh timed out",
                provider="vertex",
                retryable=True,
            ) from None
        except ProviderError as exc:
            raise ProviderError(
                kind=exc.kind,
                message="Vertex credentials unavailable",
                provider="vertex",
                retryable=exc.retryable,
            ) from None
        except Exception as exc:
            raise _normalize_failure(exc) from None

    @staticmethod
    def _consume_exception(task: asyncio.Task[str]) -> None:
        if not task.cancelled():
            task.exception()

    def _load_token(self) -> str:
        if self._credentials is None or not self._credentials.valid:
            if self._request_factory is None:
                from google.auth.transport.requests import Request

                request = Request()
            else:
                request = self._request_factory()

            def bounded_request(*args: Any, **kwargs: Any) -> Any:
                kwargs["timeout"] = self._timeout_s
                return request(*args, **kwargs)

        if self._credentials is None:
            if self._credentials_loader is None:
                loader = _load_adc
            else:
                loader = self._credentials_loader
            self._credentials, _ = loader(scopes=_SCOPES, request=bounded_request)
        credentials = self._credentials
        if not credentials.valid:
            credentials.refresh(bounded_request)
        if not credentials.valid or not isinstance(credentials.token, str) or not credentials.token:
            raise ValueError("credentials did not provide a valid token")
        return credentials.token
