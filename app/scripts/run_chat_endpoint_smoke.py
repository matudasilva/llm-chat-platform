from __future__ import annotations

import json
import os
import subprocess


API_URL = os.getenv("API_URL", "http://localhost:8001/chat")
PG_SERVICE = os.getenv("POSTGRES_SERVICE", "postgres")
PG_USER = os.getenv("POSTGRES_USER", "llmchat")
PG_DB = os.getenv("POSTGRES_DB", "llmchat")


def sh(cmd: str) -> str:
    return subprocess.check_output(["bash", "-lc", cmd], text=True)


def curl_post(payload: dict) -> tuple[int, str]:
    # devuelve (http_status, body)
    cmd = (
        f"curl -s -w '\\n%{{http_code}}' -X POST {API_URL} "
        f"-H 'Content-Type: application/json' "
        f"-d '{json.dumps(payload)}'"
    )
    out = sh(cmd)
    body, code = out.rsplit("\n", 1)
    return int(code), body


def psql_scalar(query: str) -> str:
    cmd = (
        f"docker compose exec -T {PG_SERVICE} "
        f"psql -U {PG_USER} -d {PG_DB} -tA -c \"{query}\""
    )
    return sh(cmd).strip()


def count_messages() -> int:
    return int(psql_scalar("select count(*) from messages;") or "0")


def last_usage_event() -> tuple[str, str | None, str | None]:
    row = psql_scalar(
        "select status, conversation_id::text, message_id::text "
        "from usage_events order by timestamp desc limit 1;"
    )
    status, conv_id, msg_id = row.split("|")
    return status, (conv_id or None), (msg_id or None)


def main() -> None:
    before = count_messages()

    # ---- OK path ----
    code, body = curl_post({"message": "hola"})
    assert code == 200, (code, body)
    r = json.loads(body)
    assert r["status"] == "success", r
    conv_id = r["conversation_id"]

    after_ok = count_messages()
    assert after_ok == before + 2, (before, after_ok)

    st, ev_conv, ev_msg = last_usage_event()
    assert st == "success", st
    assert ev_conv and ev_msg, (ev_conv, ev_msg)

    print("[OK] success path validated")

    # ---- ERROR path ----
    if os.getenv("STUB_PROVIDER_MODE") != "error":
        print("[SKIP] set STUB_PROVIDER_MODE=error to validate rollback path")
        return

    before_err = count_messages()
    code, body = curl_post({"message": "boom", "conversation_id": conv_id})
    assert code >= 500, (code, body)

    after_err = count_messages()
    assert after_err == before_err, (before_err, after_err)

    st, ev_conv, ev_msg = last_usage_event()
    assert st == "error", st
    assert ev_conv is None and ev_msg is None, (ev_conv, ev_msg)

    print("[OK] error path validated (rollback + best-effort usage_event)")


if __name__ == "__main__":
    main()
