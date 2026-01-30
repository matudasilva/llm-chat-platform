from __future__ import annotations

def truncate(s: str, max_chars: int) -> str:
    if s is None:
        return s
    return s if len(s) <= max_chars else s[:max_chars]

def sanitize_error_message(s: str, max_chars: int) -> str:
    if not s:
        return "unknown error"
    one_line = " ".join(str(s).split())
    return truncate(one_line, max_chars)
