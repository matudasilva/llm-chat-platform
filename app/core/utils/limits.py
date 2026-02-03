from __future__ import annotations

def truncate(s: str, max_chars: int) -> str:
    if s is None:
        return s
    return s if len(s) <= max_chars else s[:max_chars]

def sanitize_error_message(msg: str, max_len: int) -> str:
    s = (msg or "").strip()
    if not s:
        return truncate("unknown error", max_len)
    return truncate(s, max_len)

