"""Fail-closed secret/PII scan for fixtures and rendered payloads (AC22, AC35).

The corpus is synthetic, so the only sensitive-looking strings it may contain
are tokens of the synthetic-prohibited grammar. Anything else that looks like
a credential, a personal identifier, or an opaque encoded blob is a finding:
this scan runs before data is written into a pool and before every provider
dispatch, and a finding stops that dispatch.

Every limit is a named constant so `review-implementation` can check the
contract against the code rather than against prose (H7). Exceeding a limit
raises `ScanLimitError` -- a scan that could not finish is never a pass.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote_to_bytes

from app.scripts.guardrails_scan import (
    AWS_KEY_RE,
    LOCAL_PATH_RE,
    OPENAI_KEY_RE,
    SECRET_ASSIGNMENT_RE,
)

# The only permitted sensitive-looking token shape (spec §Diseño 3, G7).
SYNTHETIC_PROHIBITED_RE = re.compile(r"SYNTHETIC-PROHIBITED-[A-Z]{3,12}-[0-9a-f]{8}")

# Decoding contract. Order at each level: NFKC normalization, then scan, then
# percent-decoding, then base64 candidates, each decoded layer scanned
# recursively up to MAX_DECODE_DEPTH.
MAX_DECODE_DEPTH = 3
# Upper bound on total characters examined across all decoded layers, relative
# to the input and absolute. Guards against decompression-bomb style inputs.
MAX_EXPANSION_FACTOR = 4
MAX_EXPANSION_CHARS = 1_000_000
MAX_INPUT_CHARS = 2_000_000

BASE64_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/_-]{16,}={0,2}")
# Tokens that are legitimately long and base64-alphabet but not encodings:
# lowercase hex digests and UUIDs. Excluded from base64 decoding only; they are
# still scanned as plain text.
_HEX_TOKEN_RE = re.compile(r"[0-9a-f]+")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_PERCENT_RE = re.compile(r"%[0-9A-Fa-f]{2}")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<![\w-])\+?\d(?:[ .()-]?\d){8,14}(?![\w-])")
CARD_CANDIDATE_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
IBAN_CANDIDATE_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")

_PLAIN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_key", OPENAI_KEY_RE),
    ("aws_key", AWS_KEY_RE),
    ("secret_assignment", SECRET_ASSIGNMENT_RE),
    ("local_path", LOCAL_PATH_RE),
    ("email", EMAIL_RE),
    ("phone", PHONE_RE),
)


class ScanLimitError(RuntimeError):
    """The input exceeded a declared limit; the scan fails closed."""


@dataclass(frozen=True, slots=True)
class Finding:
    kind: str
    depth: int
    start: int
    end: int


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _iban_valid(candidate: str) -> bool:
    compact = candidate.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(char, 36)) for char in rearranged)
    return int(numeric) % 97 == 1


def _synthetic_spans(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in SYNTHETIC_PROHIBITED_RE.finditer(text)]


def _inside_synthetic(span: tuple[int, int], allowed: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(a_start <= start and end <= a_end for a_start, a_end in allowed)


def _scan_plain(text: str, depth: int) -> list[Finding]:
    allowed = _synthetic_spans(text)
    findings: list[Finding] = []

    def record(kind: str, span: tuple[int, int]) -> None:
        if not _inside_synthetic(span, allowed):
            findings.append(Finding(kind=kind, depth=depth, start=span[0], end=span[1]))

    # UUIDs are the dataset's own identifiers; their digit runs can pass a
    # Luhn check by chance, so numeric PII patterns never see them. Masking
    # preserves offsets, and the UUID shape itself carries no PII.
    numeric_view = _UUID_RE.sub(lambda match: " " * len(match.group()), text)

    for kind, pattern in _PLAIN_PATTERNS:
        view = numeric_view if kind == "phone" else text
        for match in pattern.finditer(view):
            if kind == "secret_assignment":
                # The key ("password: ") sits outside any token; judge the
                # assigned value alone, which is exempt only if it is exactly
                # a synthetic-prohibited token.
                record(kind, match.span("value"))
            else:
                record(kind, match.span())
    for match in CARD_CANDIDATE_RE.finditer(numeric_view):
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            record("card_number", match.span())
    for match in IBAN_CANDIDATE_RE.finditer(numeric_view):
        if _iban_valid(match.group()):
            record("iban", match.span())
    return findings


def _decode_base64(token: str) -> bytes | None:
    stripped = token.rstrip("=")
    if len(stripped) < 16:
        return None
    padded = stripped + "=" * (-len(stripped) % 4)
    altchars = b"-_" if ("-" in token or "_" in token) else None
    try:
        return base64.b64decode(padded, altchars=altchars, validate=True)
    except (binascii.Error, ValueError):
        return None


def _is_decoding_exempt(token: str) -> bool:
    """Tokens not treated as encodings: hex digests, UUIDs, and ordinary words.

    Real base64 of text almost always mixes cases and carries a digit, a
    symbol or padding; a long single-case word ("internationalization") or a
    CamelCase identifier without digits does not, and decoding those would
    turn ordinary prose into false `opaque_encoded_blob` findings.
    """
    if _HEX_TOKEN_RE.fullmatch(token) or _UUID_RE.fullmatch(token):
        return True
    has_upper = any(char.isupper() for char in token)
    has_lower = any(char.islower() for char in token)
    has_marker = any(char.isdigit() or char in "+/_-=" for char in token)
    return not (has_upper and has_lower and has_marker)


def scan_text(text: str) -> tuple[Finding, ...]:
    """All findings in `text`, including inside nested encodings.

    Raises `ScanLimitError` when an input or its decoded expansion exceeds a
    declared limit. A decoded base64 layer that is not valid UTF-8 is itself a
    finding (`opaque_encoded_blob`): a synthetic corpus has no reason to carry
    binary data, and content that cannot be read cannot be cleared.
    """
    if len(text) > MAX_INPUT_CHARS:
        raise ScanLimitError("input exceeds MAX_INPUT_CHARS")
    budget = min(MAX_EXPANSION_CHARS, MAX_EXPANSION_FACTOR * max(len(text), 1))
    findings: list[Finding] = []
    examined = 0

    def visit(layer: str, depth: int) -> None:
        nonlocal examined
        layer = unicodedata.normalize("NFKC", layer)
        if depth > 0:
            examined += len(layer)
            if examined > budget:
                raise ScanLimitError("decoded expansion exceeds the declared limit")
        findings.extend(_scan_plain(layer, depth))
        allowed = _synthetic_spans(layer)
        candidates = [
            match
            for match in BASE64_CANDIDATE_RE.finditer(layer)
            if not _is_decoding_exempt(match.group())
            and not _inside_synthetic(match.span(), allowed)
        ]
        if depth >= MAX_DECODE_DEPTH:
            if _PERCENT_RE.search(layer) or any(
                _decode_base64(match.group()) for match in candidates
            ):
                raise ScanLimitError("encoding nested deeper than MAX_DECODE_DEPTH")
            return
        if _PERCENT_RE.search(layer):
            decoded = unquote_to_bytes(layer)
            try:
                visit(decoded.decode("utf-8"), depth + 1)
            except UnicodeDecodeError:
                findings.append(Finding("opaque_encoded_blob", depth + 1, 0, len(layer)))
        for match in candidates:
            decoded = _decode_base64(match.group())
            if decoded is None:
                continue
            try:
                visit(decoded.decode("utf-8"), depth + 1)
            except UnicodeDecodeError:
                findings.append(Finding("opaque_encoded_blob", depth + 1, *match.span()))

    visit(text, 0)
    return tuple(findings)


def assert_clean(text: str) -> None:
    """Raise unless `text` is free of findings. The pre-dispatch entry point."""
    findings = scan_text(text)
    if findings:
        kinds = sorted({finding.kind for finding in findings})
        raise ValueError(f"payload scan failed: {', '.join(kinds)}")
