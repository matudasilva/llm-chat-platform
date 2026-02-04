# tests/api/test_request_size_limit.py
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.settings import settings


def test_payload_over_max_request_bytes_returns_413() -> None:
    client = TestClient(app)

    oversized = b"a" * (settings.MAX_REQUEST_BYTES + 1)

    r = client.post(
        "/chat",
        content=oversized,
        headers={"Content-Type": "application/json"},
    )

    assert r.status_code == 413
    assert r.json() == {"detail": "Payload too large"}

