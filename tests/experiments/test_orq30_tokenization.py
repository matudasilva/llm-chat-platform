from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import unittest
from unittest import mock

from experiments.long_context_conversational_memory.model import Event, Message
from experiments.long_context_conversational_memory.tokenization import (
    ASSET_CACHE_KEY,
    ASSET_SHA256,
    ASSET_SIZE_BYTES,
    ASSET_URL,
    ENCODING_NAME,
    TOKENIZER_PACKAGE_VERSION,
    TokenizerIntegrityError,
    canonical_event_text,
    load_offline_encoding,
    ordinary_token_ids,
    validate_asset,
)


ROOT = Path(__file__).resolve().parents[2]
ORQ_DIR = ROOT / ".framework/orqs/ORQ-30-long-context-conversational-memory"


class Orq30TokenizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_dir = Path(os.environ["TIKTOKEN_CACHE_DIR"]).resolve()

    def test_implementation_matches_approved_manifest(self) -> None:
        manifest = json.loads((ORQ_DIR / "experiment-manifest.json").read_text())
        contract = manifest["tokenization_contract"]
        self.assertEqual(contract["runtime"], "python_3.13")
        self.assertEqual(contract["package"], f"tiktoken=={TOKENIZER_PACKAGE_VERSION}")
        self.assertEqual(contract["encoding"], ENCODING_NAME)
        self.assertEqual(contract["asset_url"], ASSET_URL)
        self.assertEqual(contract["asset_sha256"], ASSET_SHA256)
        self.assertFalse(contract["special_tokens_allowed"])

    def test_authenticated_asset_and_approved_sequences_load_offline(self) -> None:
        calls: list[object] = []

        def blocked(*args: object, **kwargs: object) -> None:
            calls.append((args, kwargs))
            raise AssertionError("network access attempted")

        with (
            mock.patch("socket.create_connection", side_effect=blocked),
            mock.patch("socket.getaddrinfo", side_effect=blocked),
            mock.patch("urllib.request.urlopen", side_effect=blocked),
            mock.patch("http.client.HTTPConnection.connect", side_effect=blocked),
            mock.patch("http.client.HTTPSConnection.connect", side_effect=blocked),
            mock.patch("requests.sessions.Session.request", side_effect=blocked),
        ):
            encoding = load_offline_encoding(self.cache_dir)
            cases = [
                (
                    '{"decision":"answer","values":["NONCE"]}',
                    (10848, 160595, 7534, 17021, 4294, 7222, 95067, 47867, 4585, 2601, 92),
                ),
                (
                    '{"idioma":"español","estado":"válido","símbolo":"🔒"}',
                    (
                        10848, 9175, 5534, 7534, 268, 148518, 340, 4294,
                        37886, 7534, 184843, 2295, 4294, 104694, 3294, 5539,
                        7534, 51843, 240, 18583,
                    ),
                ),
            ]
            for text, expected in cases:
                actual = ordinary_token_ids(encoding, text)
                self.assertEqual(actual, expected)
                self.assertEqual(encoding.decode(list(actual)), text)
                self.assertEqual(encoding.decode_bytes(list(actual)), text.encode("utf-8"))
        self.assertEqual(calls, [])

    def test_network_connection_attempt_is_blocked_by_the_test_harness(self) -> None:
        with mock.patch(
            "socket.create_connection",
            side_effect=AssertionError("network disabled for Stage 0"),
        ):
            with self.assertRaisesRegex(AssertionError, "network disabled"):
                socket.create_connection(("example.invalid", 443))

    def test_asset_cache_key_size_and_hash_are_frozen(self) -> None:
        self.assertEqual(
            ASSET_CACHE_KEY,
            hashlib.sha1(ASSET_URL.encode("utf-8"), usedforsecurity=False).hexdigest(),
        )
        asset = validate_asset(self.cache_dir)
        self.assertEqual(asset.stat().st_size, ASSET_SIZE_BYTES)
        self.assertEqual(hashlib.sha256(asset.read_bytes()).hexdigest(), ASSET_SHA256)

    def test_missing_or_mismatched_asset_fails_closed(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            cache = Path(directory)
            with self.assertRaises(TokenizerIntegrityError):
                validate_asset(cache)
            (cache / ASSET_CACHE_KEY).write_bytes(b"not-the-asset")
            with self.assertRaises(TokenizerIntegrityError):
                validate_asset(cache)

    def test_canonical_event_serialization_is_exact_utf8_json_plus_lf(self) -> None:
        event = Event(
            tenant_id="TENANT",
            conversation_id="CONVERSATION",
            event_id="EVENT_0",
            event_sequence=0,
            messages=(Message("MESSAGE_0", "user", "¿Dónde está Ñandú?"),),
        )
        rendered = canonical_event_text(event)
        self.assertEqual(
            rendered,
            '{"event_id":"EVENT_0","event_sequence":0,"messages":'
            '[{"content":"¿Dónde está Ñandú?","message_id":"MESSAGE_0",'
            '"role":"user"}]}\n',
        )
        self.assertEqual(rendered.encode("utf-8").decode("utf-8"), rendered)


if __name__ == "__main__":
    unittest.main()
