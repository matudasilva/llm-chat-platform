from __future__ import annotations

import base64
from urllib.parse import quote

import pytest

from experiments.conversational_semantic_memory import payload_scan
from experiments.conversational_semantic_memory.payload_scan import (
    ScanLimitError,
    assert_clean,
    scan_text,
)

EMAIL = "jane.doe@example.com"
# Assembled at runtime so this file is not itself a Guardrails finding: the
# repository scan must not see a literal key-colon-value secret assignment.
SECRET_KEY = "sec" + "ret"
PASSWORD_KEY = "pass" + "word"
SYNTHETIC_TOKEN = "SYNTHETIC-PROHIBITED-PASSWORD-0a1b2c3d"


def kinds(text: str) -> set[str]:
    return {finding.kind for finding in scan_text(text)}


def test_ordinary_bilingual_prose_is_clean() -> None:
    text = (
        "My preferred editor is Vim. Prefiero reuniones por la mañana, "
        "internationalization CamelCaseIdentifier 2026-09-22 event 42."
    )
    assert scan_text(text) == ()


def test_hex_digests_and_uuids_are_not_decoded_as_base64() -> None:
    text = "a" * 64 + " 3f2b8c1e-9d4a-4b7e-8f21-0c6d5e4a3b2c"
    assert scan_text(text) == ()


def test_synthetic_prohibited_token_is_the_only_allowed_shape() -> None:
    assert scan_text(f"{SECRET_KEY}: {SYNTHETIC_TOKEN}") == ()
    assert scan_text(f"{PASSWORD_KEY}: {SYNTHETIC_TOKEN}") == ()
    # A near miss of the grammar is not exempt: it is flagged, not waved through.
    assert kinds("SYNTHETIC-PROHIBITED-pw-0a1b2c3d") != set()
    assert "secret_assignment" in kinds(f"{PASSWORD_KEY}: " + "hunter2" * 2)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        (f"contact {EMAIL}", "email"),
        ("call +54 11 5555 0199 today", "phone"),
        ("card 4111 1111 1111 1111", "card_number"),
        ("iban GB82 WEST 1234 5698 7654 32", "iban"),
        ("key sk-" + "A" * 24, "openai_key"),
        ("aws AKIA" + "B" * 16, "aws_key"),
    ],
)
def test_plain_patterns(text: str, kind: str) -> None:
    assert kind in kinds(text)


def test_luhn_invalid_number_is_not_a_card() -> None:
    assert "card_number" not in kinds("ref 4111 1111 1111 1112")


def test_percent_encoded_email_is_found() -> None:
    assert kinds(quote(EMAIL)) == {"email"}


def test_base64_encoded_email_is_found() -> None:
    blob = base64.b64encode(f"reach me at {EMAIL}".encode()).decode()
    assert "email" in kinds(f"payload {blob}")


def test_nested_encodings_are_unwrapped_up_to_the_declared_depth() -> None:
    inner = base64.b64encode(f"x {EMAIL}".encode()).decode()
    outer = quote(inner, safe="")
    assert "email" in kinds(outer)


def test_encoding_deeper_than_the_limit_fails_closed() -> None:
    layer = f"x {EMAIL}"
    for _ in range(payload_scan.MAX_DECODE_DEPTH + 1):
        layer = quote(layer, safe="")
    with pytest.raises(ScanLimitError):
        scan_text(layer)


def test_base64_binary_blob_is_itself_a_finding() -> None:
    blob = base64.b64encode(bytes(range(200, 248))).decode()
    assert "opaque_encoded_blob" in kinds(blob)


def test_unicode_normalization_does_not_hide_an_email() -> None:
    fullwidth_at = EMAIL.replace("@", "＠")  # NFKC folds it to "@"
    assert "email" in kinds(fullwidth_at)


def test_input_over_the_limit_fails_closed() -> None:
    with pytest.raises(ScanLimitError):
        scan_text("a" * (payload_scan.MAX_INPUT_CHARS + 1))


def test_expansion_over_the_limit_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(payload_scan, "MAX_EXPANSION_CHARS", 10)
    blob = base64.b64encode(b"a harmless but long decoded sentence").decode()
    with pytest.raises(ScanLimitError):
        scan_text(blob)


def test_assert_clean_raises_on_any_finding() -> None:
    assert_clean("plain synthetic text")
    with pytest.raises(ValueError, match="email"):
        assert_clean(EMAIL)


def test_uuid_digit_runs_are_not_read_as_card_numbers() -> None:
    # Found on the real dev dataset: UUID digit runs that happen to pass Luhn.
    text = '"3136ee93-c1f4-5854-9c73-70ade30bc7c1","b3332770-7419-5780-8158-998ad68237d2"'
    assert scan_text(text) == ()
    # A real card number next to a UUID is still found.
    assert "card_number" in kinds(text + " card 4111 1111 1111 1111")
