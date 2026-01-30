from app.core.settings import settings


def test_chat_rejects_blank_message(client):
    resp = client.post("/chat", json={"message": "   "})
    assert resp.status_code == 422


def test_chat_rejects_message_too_long(client):
    msg = "a" * (settings.MAX_MESSAGE_CHARS + 1)
    resp = client.post("/chat", json={"message": msg})
    assert resp.status_code == 422
