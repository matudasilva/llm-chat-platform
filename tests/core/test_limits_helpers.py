from app.core.utils.limits import truncate, sanitize_error_message


def test_truncate_returns_original_when_shorter_than_limit() -> None:
    assert truncate("abc", 10) == "abc"


def test_truncate_clamps_to_limit() -> None:
    assert truncate("abcdef", 3) == "abc"


def test_truncate_handles_exact_limit() -> None:
    assert truncate("abcd", 4) == "abcd"


def test_truncate_handles_zero_limit() -> None:
    assert truncate("abc", 0) == ""


def test_sanitize_error_message_returns_original_when_shorter_than_limit() -> None:
    assert sanitize_error_message("boom", 10) == "boom"


def test_sanitize_error_message_truncates_to_limit() -> None:
    msg = "x" * 100
    out = sanitize_error_message(msg, 10)
    assert out == "x" * 10


def test_sanitize_error_message_handles_empty() -> None:
    out = sanitize_error_message("", 10)
    assert out == "unknown er"
    assert len(out) <= 10



def test_sanitize_error_message_fallback_respects_limit() -> None:
    out = sanitize_error_message("", 3)
    assert len(out) <= 3


