"""Authenticated offline tokenizer loading and canonical event accounting."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
from typing import Protocol

from .model import Event

TOKENIZER_PACKAGE_VERSION = "0.12.0"
ENCODING_NAME = "o200k_base"
ASSET_URL = (
    "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
)
ASSET_SIZE_BYTES = 3_613_922
ASSET_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
ASSET_CACHE_KEY = hashlib.sha1(ASSET_URL.encode("utf-8"), usedforsecurity=False).hexdigest()


class Encoding(Protocol):
    def encode(
        self,
        text: str,
        *,
        allowed_special: set[str],
        disallowed_special: str,
    ) -> list[int]: ...


class TokenizerIntegrityError(RuntimeError):
    """The frozen local tokenizer contract is unavailable or mismatched."""


def canonical_event_text(event: Event) -> str:
    """Render an event using the exact ORQ-30 canonical JSON contract."""

    return (
        json.dumps(
            event.canonical_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_asset(cache_dir: Path) -> Path:
    """Validate the sole usable cache object before tiktoken can load it."""

    asset_path = cache_dir / ASSET_CACHE_KEY
    if not asset_path.is_file():
        raise TokenizerIntegrityError(f"authenticated tokenizer asset missing: {asset_path}")
    if asset_path.stat().st_size != ASSET_SIZE_BYTES:
        raise TokenizerIntegrityError("tokenizer asset size mismatch")
    if _sha256_file(asset_path) != ASSET_SHA256:
        raise TokenizerIntegrityError("tokenizer asset SHA-256 mismatch")
    return asset_path


def load_offline_encoding(cache_dir: Path) -> Encoding:
    """Load the frozen encoding only after local runtime and asset validation."""

    if platform.python_version() != "3.13.9":
        raise TokenizerIntegrityError("ORQ-30 requires Python 3.13.9")
    try:
        installed_version = importlib.metadata.version("tiktoken")
    except importlib.metadata.PackageNotFoundError as exc:
        raise TokenizerIntegrityError("tiktoken is not installed") from exc
    if installed_version != TOKENIZER_PACKAGE_VERSION:
        raise TokenizerIntegrityError(
            f"expected tiktoken {TOKENIZER_PACKAGE_VERSION}, got {installed_version}"
        )
    validate_asset(cache_dir)

    import os

    configured_cache = os.environ.get("TIKTOKEN_CACHE_DIR")
    if configured_cache != str(cache_dir.resolve()):
        raise TokenizerIntegrityError(
            "TIKTOKEN_CACHE_DIR must be the authenticated ORQ-30 cache path"
        )

    import tiktoken

    if not Path(tiktoken.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise TokenizerIntegrityError("tiktoken was loaded outside the dedicated runtime")
    encoding = tiktoken.get_encoding(ENCODING_NAME)
    if encoding.name != ENCODING_NAME:
        raise TokenizerIntegrityError("unexpected tokenizer encoding name")
    return encoding


def ordinary_token_ids(encoding: Encoding, text: str) -> tuple[int, ...]:
    if not isinstance(text, str):
        raise TypeError("tokenized input must be text")
    return tuple(
        encoding.encode(text, allowed_special=set(), disallowed_special="all")
    )


def token_count(encoding: Encoding, text: str) -> int:
    return len(ordinary_token_ids(encoding, text))


def event_token_count(encoding: Encoding, event: Event) -> int:
    return token_count(encoding, canonical_event_text(event))
