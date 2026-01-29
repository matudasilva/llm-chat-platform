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
    cmd = (
        f"curl --max-time 5 --connect-timeout 2 "
        f"-s -w '\\n%{{http_code}}' -X POST {API_URL} "
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
    assert os.getenv("STUB_PROVIDER_MODE") == "error", (
        "Run with STUB_PROVIDER_MODE=error in host to enable assertions"
    )

    before = count_messages()

    # Forzar fallo del provider (api debe estar en STUB_PROVIDER_MODE=error)
    code, body = curl_post({"message": "boom"})
    assert code >= 500, (code, body)

    after = count_messages()
    assert after == before, (before, after)

    st, ev_conv, ev_msg = last_usage_event()
    assert st == "error", st
    assert ev_conv is None and ev_msg is None, (ev_conv, ev_msg)

    print("[OK] error path validated (rollback + best-effort usage_event)")


if __name__ == "__main__":
    main()
