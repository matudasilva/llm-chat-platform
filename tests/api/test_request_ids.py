
#tests/api/test_request_ids.py

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_chat_response_request_id_matches_header():
    client = TestClient(app)

    r = client.post("/chat", json={"message": "hello"})
    assert r.status_code == 200

    header_rid = r.headers.get("x-request-id")
    assert header_rid is not None

    body = r.json()
    assert body["request_id"] == header_rid