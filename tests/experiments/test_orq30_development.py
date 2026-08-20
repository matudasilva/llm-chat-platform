from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments.long_context_conversational_memory.development import (
    AMENDED_DEVELOPMENT_REQUESTS,
    DEVELOPMENT_CONVERSATIONS,
    DEVELOPMENT_REQUESTS,
    build_amended_development_requests,
    build_development_dataset,
    build_development_requests,
    dataset_json,
    write_development_dataset,
)
from experiments.long_context_conversational_memory.tokenization import load_offline_encoding
from experiments.long_context_conversational_memory import run_development


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".framework/cache/orq-30/tiktoken"


class Orq30DevelopmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["TIKTOKEN_CACHE_DIR"] = str(CACHE.resolve())
        cls.encoding = load_offline_encoding(CACHE)
        cls.dataset = build_development_dataset(cls.encoding)

    def test_private_deterministic_balanced_dataset_has_registered_shape(self) -> None:
        self.assertEqual(len(self.dataset), DEVELOPMENT_CONVERSATIONS)
        self.assertEqual(sum(item.language == "en" for item in self.dataset), 8)
        self.assertEqual(sum(item.language == "es" for item in self.dataset), 8)
        self.assertTrue(all(len(item.steps) == 4 for item in self.dataset))
        self.assertTrue(all(8_192 <= sum(len(self.encoding.encode(__import__('json').dumps(event.canonical_payload(), ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n', allowed_special=set(), disallowed_special='all')) for event in item.events) <= 16_384 for item in self.dataset))

    def test_every_primary_has_real_b_pressure_and_effective_canaries(self) -> None:
        requests = build_development_requests(self.encoding, self.dataset)
        self.assertEqual(len(requests), DEVELOPMENT_REQUESTS)
        for request in requests:
            if request.arm_id == "B":
                self.assertLessEqual(request.context.total_input_tokens, 4_608)
            if request.arm_id == "E-BM25":
                self.assertLessEqual(request.context.total_input_tokens, 4_608)
        primaries = [step for item in self.dataset for step in item.steps if step.is_primary]
        self.assertEqual(len(primaries), 32)
        for step in primaries:
            self.assertTrue(step.gold_atoms)

    def test_amended_development_is_exactly_paired_b_and_e_bm25(self) -> None:
        requests = build_amended_development_requests(self.encoding, self.dataset)
        self.assertEqual(len(requests), AMENDED_DEVELOPMENT_REQUESTS)
        self.assertEqual({request.arm_id for request in requests}, {"B", "E-BM25"})

    def test_serialization_is_repeatable_and_local_write_is_hash_bound(self) -> None:
        first = dataset_json(self.dataset)
        second = dataset_json(build_development_dataset(self.encoding))
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "development.json"
            digest = write_development_dataset(path, self.dataset)
            self.assertEqual(digest, hashlib.sha256(first).hexdigest())
            self.assertEqual(path.read_bytes(), first)

    def test_runner_persists_validated_reservation_before_transport(self) -> None:
        prepared = SimpleNamespace(
            arm_id="B",
            step=SimpleNamespace(
                step_id="STEP_PRE_DISPATCH",
                step_type="primary_out_of_window_one",
                gold_atoms=frozenset({"NONCE"}),
            ),
            context=SimpleNamespace(prompt_text="synthetic prompt"),
            request_parameter_hash="0" * 64,
            conversation_index=0,
        )
        response_payload = {
            "choices": [{"message": {"content": '{"decision":"answer","values":["NONCE"]}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

        class Response:
            status = 200

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self) -> bytes:
                import json

                return json.dumps(response_payload).encode("utf-8")

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "run"

            def transport(_: object, *, timeout: int) -> Response:
                self.assertEqual(timeout, 60)
                ledger_path = output_dir / "attempt-ledger.jsonl"
                self.assertTrue(ledger_path.is_file(), "transport was reachable before reservation persistence")
                rows = ledger_path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(rows), 1)
                self.assertIn('"attempt_id":"development:STEP_PRE_DISPATCH:B:1"', rows[0])
                return Response()

            with (
                mock.patch.object(run_development, "_configured_api_key", return_value="test-key"),
                mock.patch.object(run_development, "load_offline_encoding", return_value=object()),
                mock.patch.object(run_development, "build_development_dataset", return_value=()),
                mock.patch.object(run_development, "build_amended_development_requests", return_value=[prepared]),
                mock.patch.object(run_development, "write_development_dataset", return_value="a" * 64),
                mock.patch.object(run_development, "AMENDED_DEVELOPMENT_REQUESTS", 1),
                mock.patch.object(run_development, "urlopen", side_effect=transport) as urlopen,
            ):
                summary = run_development.execute(output_dir, CACHE, replacement=True)

            finalized = (output_dir / "attempt-ledger.jsonl").read_text(encoding="utf-8")
            registration = (output_dir / "run-registration.json").read_text(encoding="utf-8")

        self.assertEqual(summary["attempts_recorded"], 1)
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn('"reported_usage_or_null":{"input_tokens":1,"output_tokens":1}', finalized)
        self.assertIn('"phase":"development_replacement"', registration)
        self.assertIn('"prior_development_reserved_cost_usd":"0.2703360"', registration)


if __name__ == "__main__":
    unittest.main()
    build_amended_development_requests,
