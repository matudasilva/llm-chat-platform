import asyncio
import json
import subprocess
import threading
from types import SimpleNamespace

import pytest
from google.auth import exceptions as auth_errors
from requests import exceptions as request_errors

from app.core.domain.provider_errors import ProviderError, ProviderErrorKind
from app.core.providers.google_adc import GoogleAdcAccessTokenProvider


class Credentials:
    valid = False
    token = None

    def __init__(self):
        self.calls = 0

    def refresh(self, request):
        self.calls += 1
        request("url", timeout=999)
        self.token = "test"
        self.valid = True


@pytest.mark.asyncio
async def test_lazy_scoped_discovery_refresh_and_cached_token():
    creds = Credentials()
    calls = []
    def loader(*, scopes, request):
        calls.append({"scopes": scopes})
        request("discovery", timeout=999)
        return creds, "ignored-project"
    provider = GoogleAdcAccessTokenProvider(2, credentials_loader=loader, request_factory=lambda: lambda *a, **kw: calls.append(kw))
    assert calls == []
    assert await provider() == "test"
    assert await provider() == "test"
    assert calls == [{"scopes": ("https://www.googleapis.com/auth/cloud-platform",)}, {"timeout": 2}, {"timeout": 2}]
    assert creds.calls == 1


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_overlap_refresh():
    started, release = threading.Event(), threading.Event()
    creds = Credentials()

    def loader(**kwargs):
        started.set()
        release.wait(2)
        return creds, None

    provider = GoogleAdcAccessTokenProvider(1, credentials_loader=loader, request_factory=lambda: lambda *a, **kw: None)
    first = asyncio.create_task(provider())
    assert await asyncio.to_thread(started.wait, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(provider())
    await asyncio.sleep(0)
    release.set()
    assert await second == "test"
    assert creds.calls == 1


@pytest.mark.asyncio
async def test_timeout_preserves_single_inflight_work():
    started, release = threading.Event(), threading.Event()
    creds = Credentials()
    loads = []

    def loader(**kwargs):
        loads.append(1)
        started.set()
        release.wait(2)
        return creds, None

    provider = GoogleAdcAccessTokenProvider(0.03, credentials_loader=loader, request_factory=lambda: lambda *a, **kw: None)
    try:
        with pytest.raises(ProviderError) as error:
            await provider()
        assert error.value.kind == ProviderErrorKind.timeout
        with pytest.raises(ProviderError):
            await provider()
        assert loads == [1]
    finally:
        release.set()
    await asyncio.sleep(0.02)
    assert await provider() == "test"


@pytest.mark.asyncio
async def test_auth_failure_is_terminal_and_secret_safe():
    def loader(**kwargs):
        raise RuntimeError("sensitive credential detail")

    provider = GoogleAdcAccessTokenProvider(1, credentials_loader=loader)
    with pytest.raises(ProviderError) as error:
        await provider()
    assert error.value.kind == ProviderErrorKind.auth
    assert not error.value.retryable
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        GoogleAdcAccessTokenProvider(timeout)


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [True, False])
@pytest.mark.filterwarnings("ignore:The load_credentials_from_file method is deprecated:DeprecationWarning")
async def test_local_adc_file_refresh_is_cli_free(tmp_path, monkeypatch, explicit):
    path = tmp_path / "application_default_credentials.json"
    path.write_text(json.dumps({"type": "authorized_user", "client_id": "fake", "client_secret": "fake", "refresh_token": "fake"}))
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    if explicit:
        monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(path))
    else:
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    def no_subprocess(*args, **kwargs):
        raise AssertionError("subprocess must not be used")
    monkeypatch.setattr(subprocess, "Popen", no_subprocess)
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status=200, data=b'{"access_token":"fake-token","expires_in":3600}', headers={})
    provider = GoogleAdcAccessTokenProvider(2, request_factory=lambda: request)
    assert await provider() == "fake-token"
    assert calls and all(call["timeout"] == 2 for call in calls)


@pytest.mark.asyncio
async def test_missing_local_adc_uses_attached_identity(tmp_path, monkeypatch):
    from google.auth import compute_engine

    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("unexpected subprocess"))
    creds = Credentials()
    monkeypatch.setattr(compute_engine, "Credentials", lambda *, scopes: creds)
    provider = GoogleAdcAccessTokenProvider(1, request_factory=lambda: lambda *a, **kw: None)
    assert await provider() == "test"


@pytest.mark.asyncio
async def test_executable_federation_is_rejected_before_library_load(tmp_path, monkeypatch):
    import google.auth

    path = tmp_path / "adc.json"
    path.write_text(json.dumps({"source_credentials": {"credential_source": {"executable": {"command": "fake"}}}}))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(path))
    monkeypatch.setattr(google.auth, "load_credentials_from_file", lambda *a, **kw: pytest.fail("unexpected library load"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("unexpected subprocess"))
    with pytest.raises(ProviderError) as error:
        await GoogleAdcAccessTokenProvider(1)()
    assert error.value.kind == ProviderErrorKind.auth


@pytest.mark.asyncio
@pytest.mark.parametrize(("exc", "kind", "retryable"), [
    (auth_errors.TimeoutError("secret"), ProviderErrorKind.timeout, True),
    (request_errors.Timeout("secret"), ProviderErrorKind.timeout, True),
    (auth_errors.TransportError("secret"), ProviderErrorKind.network, True),
    (request_errors.ConnectionError("secret"), ProviderErrorKind.network, True),
    (auth_errors.RefreshError("secret", retryable=True), ProviderErrorKind.network, True),
    (auth_errors.RefreshError("secret"), ProviderErrorKind.auth, False),
])
async def test_normalized_credential_errors(exc, kind, retryable):
    def loader(**kwargs):
        raise exc
    with pytest.raises(ProviderError) as error:
        await GoogleAdcAccessTokenProvider(1, credentials_loader=loader)()
    assert error.value.kind == kind
    assert error.value.retryable is retryable
    assert "secret" not in str(error.value)


@pytest.mark.asyncio
async def test_injected_provider_error_does_not_expose_credentials():
    def loader(**kwargs):
        raise ProviderError(kind=ProviderErrorKind.network, message="secret token", provider="secret", retryable=True, error_code="secret")
    with pytest.raises(ProviderError) as error:
        await GoogleAdcAccessTokenProvider(1, credentials_loader=loader)()
    assert error.value.kind == ProviderErrorKind.network
    assert error.value.retryable
    assert "secret" not in repr(error.value)
