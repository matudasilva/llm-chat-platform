from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
import unittest

from experiments.long_context_conversational_memory.model import EvaluationStep, Event, Message
from experiments.long_context_conversational_memory.replay import (
    IsolationChallenge,
    IsolationViolation,
    PromptFraming,
    ReplayIntegrityError,
    build_bm25_context,
    build_bounded_history,
    build_evaluation_step_audit,
    contextual_query_tokens,
    rank_bm25,
    validate_isolation_challenge,
)
from experiments.long_context_conversational_memory.tokenization import (
    canonical_event_text,
    load_offline_encoding,
)


def event(
    event_id: str,
    sequence: int,
    content: str,
    *,
    tenant: str = "TENANT_A",
    conversation: str = "CONVERSATION_A",
    role: str = "user",
) -> Event:
    return Event(
        tenant_id=tenant,
        conversation_id=conversation,
        event_id=event_id,
        event_sequence=sequence,
        messages=(Message(f"MESSAGE_{event_id}", role, content),),
    )


def step(events: tuple[Event, ...], question: str = "Where is TARGET_NONCE?") -> EvaluationStep:
    gold_event = events[0]
    return EvaluationStep(
        step_id="STEP_0",
        step_type="primary_out_of_window_one",
        tenant_id="TENANT_A",
        conversation_id="CONVERSATION_A",
        language="en",
        current_question=question,
        authoritative_events=events,
        gold_event_ids=frozenset({gold_event.event_id}),
        gold_message_ids=frozenset({gold_event.messages[0].message_id}),
        gold_atoms=frozenset({"TARGET_NONCE"}),
    )


FRAMING = PromptFraming(
    system_and_fixed_prefix="SYSTEM\n",
    current_question_prefix="QUESTION\n",
    current_question_suffix="\n",
)
CHALLENGE = IsolationChallenge(
    wrong_tenant_canary_event_id="CANARY_TENANT",
    wrong_tenant_sentinel_nonce="WRONG_TENANT_NONCE",
    wrong_conversation_canary_event_id="CANARY_CONVERSATION",
    wrong_conversation_sentinel_nonce="WRONG_CONVERSATION_NONCE",
)
ROOT = Path(__file__).resolve().parents[2]
MANIFEST = (
    ROOT
    / ".framework/orqs/ORQ-30-long-context-conversational-memory/experiment-manifest.json"
)


class Orq30ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.encoding = load_offline_encoding(Path(os.environ["TIKTOKEN_CACHE_DIR"]).resolve())

    def test_b_stops_at_first_nonfitting_event_and_never_splits_or_skips(self) -> None:
        old_small = event("OLD_SMALL", 0, "old compact event")
        nonfitting = event("NONFITTING", 1, "middle " + "x " * 5_000)
        newest = event("NEWEST", 2, "newest compact event")
        target_step = step((old_small, nonfitting, newest))
        packed, selection = build_bounded_history(target_step, self.encoding, FRAMING)
        self.assertEqual([item.event_id for item in selection.included], ["NEWEST"])
        self.assertEqual(
            [item.event_id for item in selection.excluded], ["OLD_SMALL", "NONFITTING"]
        )
        self.assertTrue(selection.truncated)
        self.assertEqual(
            packed.prompt_text,
            canonical_event_text(newest) + FRAMING.render(target_step.current_question),
        )
        self.assertTrue(
            packed.prompt_text.endswith(FRAMING.render(target_step.current_question))
        )
        self.assertLessEqual(packed.historical_tokens, 4_096)

    def test_b_renders_accepted_events_chronologically(self) -> None:
        events = (event("E0", 0, "alpha"), event("E1", 1, "beta"))
        packed, selection = build_bounded_history(step(events), self.encoding, FRAMING)
        self.assertEqual(selection.included, events)
        self.assertTrue(packed.prompt_text.startswith(canonical_event_text(events[0])))
        self.assertIn(canonical_event_text(events[1]), packed.prompt_text)

    def test_contextual_query_uses_only_question_and_deduplicates_in_order(self) -> None:
        events = (
            event("E0", 0, "first user"),
            event("E1", 1, "assistant ignored", role="assistant"),
            event("E2", 2, "second user"),
            event("E3", 3, "latest user"),
        )
        self.assertEqual(
            contextual_query_tokens(step(events, "Current current QUESTION question")),
            ("current", "question"),
        )

    def test_bm25_query_and_packing_match_the_amended_manifest(self) -> None:
        contract = json.loads(MANIFEST.read_text(encoding="utf-8"))["bm25_contract"]
        self.assertEqual(
            contract["query"],
            "current_question_only_first_occurrence_of_each_lexical_token_preserving_source_order",
        )
        self.assertFalse(contract["query_duplicate_terms_count_repeatedly"])
        self.assertEqual(
            contract["retrieval_candidates"],
            "exclude_recent_event_ids_then_scan_ranked_events_until_five_complete_events_fit_or_ranking_exhausts",
        )
        self.assertEqual(
            contract["retrieved_packing"],
            "greedy_rank_order_include_if_complete_event_fits_else_skip_without_consuming_delivery_slot",
        )

    def test_retrieval_packing_skips_nonfitting_ranked_events_without_consuming_top_k(self) -> None:
        oversized = event("OVERSIZED", 0, "needle " * 4_000)
        accepted = tuple(
            event(f"FIT_{index}", index + 1, f"needle candidate {index}")
            for index in range(5)
        )
        barrier = event("BARRIER", 6, "barrier " + "z " * 2_000)
        recent = event("RECENT", 7, "recent compact")
        target_step = step((oversized, *accepted, barrier, recent), "needle")
        wrong_tenant = event(
            "CANARY_TENANT", 0, "needle WRONG_TENANT_NONCE", tenant="TENANT_B"
        )
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "needle WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        packed, _, ranked = build_bm25_context(
            target_step,
            self.encoding,
            FRAMING,
            shared_events=(*target_step.authoritative_events, wrong_tenant, wrong_conversation),
            isolation_challenge=CHALLENGE,
        )
        self.assertEqual(ranked[0].event.event_id, "OVERSIZED")
        self.assertEqual(packed.retrieved_event_ids[0], "FIT_0")
        self.assertEqual(
            packed.retrieved_event_ids,
            tuple(event.event_id for event in accepted),
        )

    def test_bm25_is_reproducible_and_ties_use_sequence_then_utf8_id(self) -> None:
        documents = (
            event("ÉVENT", 2, "needle equal"),
            event("B_EVENT", 1, "needle equal"),
            event("A_EVENT", 1, "needle equal"),
        )
        first = rank_bm25(
            documents,
            ("needle",),
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
        )
        second = rank_bm25(
            documents,
            ("needle",),
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
        )
        self.assertEqual(first, second)
        self.assertEqual(
            [item.event.event_id for item in first], ["A_EVENT", "B_EVENT", "ÉVENT"]
        )

    def test_scope_filter_precedes_statistics_ranking_and_delivery(self) -> None:
        target_old = event("TARGET_OLD", 0, "needle TARGET_NONCE")
        target_recent = event("TARGET_RECENT", 1, "recent ordinary")
        wrong_tenant = event(
            "CANARY_TENANT",
            0,
            "needle needle needle WRONG_TENANT_NONCE",
            tenant="TENANT_B",
        )
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "needle needle needle WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        target_step = step((target_old, target_recent), "needle")
        packed, audit, ranked = build_bm25_context(
            target_step,
            self.encoding,
            FRAMING,
            shared_events=(target_old, target_recent, wrong_tenant, wrong_conversation),
            isolation_challenge=CHALLENGE,
        )
        self.assertEqual(audit.shared_prefilter_corpus_count, 4)
        self.assertEqual(audit.wrong_tenant_prefilter_count, 1)
        self.assertEqual(audit.wrong_conversation_prefilter_count, 1)
        self.assertTrue(audit.canaries_absent_postfilter)
        self.assertNotIn("CANARY_TENANT", [item.event.event_id for item in ranked])
        self.assertNotIn("CANARY_CONVERSATION", [item.event.event_id for item in ranked])
        delivered_ids = [item.event_id for item in packed.delivered_events]
        self.assertEqual(len(delivered_ids), len(set(delivered_ids)))
        self.assertTrue(set(packed.recent_event_ids).isdisjoint(packed.retrieved_event_ids))

    def test_recent_ids_are_removed_before_bm25_statistics_and_ranking(self) -> None:
        old_one = event("OLD_ONE", 0, "needle alpha")
        old_two = event("OLD_TWO", 1, "needle beta beta")
        barrier = event("BARRIER", 2, "filler " * 2_000)
        recent = event("RECENT", 3, "recent compact")
        wrong_tenant = event(
            "CANARY_TENANT", 0, "needle WRONG_TENANT_NONCE", tenant="TENANT_B"
        )
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "needle WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        target_step = step((old_one, old_two, barrier, recent), "needle")
        _, _, ranked = build_bm25_context(
            target_step,
            self.encoding,
            FRAMING,
            shared_events=(
                old_one,
                old_two,
                barrier,
                recent,
                wrong_tenant,
                wrong_conversation,
            ),
            isolation_challenge=CHALLENGE,
        )
        expected = rank_bm25(
            (old_one, old_two, barrier),
            contextual_query_tokens(target_step),
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
        )
        self.assertEqual(ranked, expected)
        self.assertNotIn("RECENT", [item.event.event_id for item in ranked])

    def test_any_cross_scope_delivery_fails_closed(self) -> None:
        target = event("TARGET", 0, "target")
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "canary WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        wrong_tenant = event(
            "CANARY_TENANT", 0, "canary WRONG_TENANT_NONCE", tenant="TENANT_B"
        )
        with self.assertRaises(IsolationViolation):
            validate_isolation_challenge(
                (target, wrong_tenant, wrong_conversation),
                tenant_id="TENANT_A",
                conversation_id="CONVERSATION_A",
                challenge=CHALLENGE,
                current_question="canary",
                authoritative_events=(target,),
                delivered_events=(wrong_tenant,),
            )

    def test_evaluation_step_audit_derives_real_long_context_pressure(self) -> None:
        gold = event("GOLD", 0, "needle CURRENT_NONCE " + "old " * 9_000)
        recent = event("RECENT", 1, "recent compact evidence")
        target_step = EvaluationStep(
            step_id="STEP_AUDIT",
            step_type="primary_out_of_window_one",
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
            language="en",
            current_question="needle",
            authoritative_events=(gold, recent),
            gold_event_ids=frozenset({"GOLD"}),
            gold_message_ids=frozenset({"MESSAGE_GOLD"}),
            gold_atoms=frozenset({"CURRENT_NONCE"}),
            superseded_atoms=frozenset({"SUPERSEDED_NONCE"}),
        )
        wrong_tenant = event(
            "CANARY_TENANT",
            0,
            "needle WRONG_TENANT_NONCE",
            tenant="TENANT_B",
        )
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "needle WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        scope_audit = validate_isolation_challenge(
            (gold, recent, wrong_tenant, wrong_conversation),
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
            challenge=CHALLENGE,
            current_question=target_step.current_question,
            authoritative_events=target_step.authoritative_events,
        )
        audit = build_evaluation_step_audit(
            target_step,
            self.encoding,
            scope_audit=scope_audit,
            delivered_sources_by_arm={"B": (recent,)},
        )
        self.assertEqual(audit.b_useful_history_capacity_tokens, 4_096)
        self.assertTrue(audit.b_truncated)
        self.assertTrue(audit.all_required_gold_outside_b)
        self.assertEqual(audit.b_excluded_event_ids, ("GOLD",))
        with self.assertRaises(ValueError):
            replace(
                audit,
                shared_prefilter_corpus_count=1,
                wrong_tenant_prefilter_count=0,
                wrong_conversation_prefilter_count=0,
                wrong_tenant_canary_event_id="",
                wrong_conversation_canary_event_id="",
            )
        with self.assertRaises(ValueError):
            replace(
                audit,
                delivered_source_ids_by_arm=(
                    ("E-BM25", (audit.wrong_tenant_canary_event_id,)),
                ),
                canaries_absent_delivered_sources=True,
            )

    def test_step_audit_derives_recent_and_no_evidence_controls(self) -> None:
        recent_gold = event("RECENT_GOLD", 0, "needle CURRENT_NONCE")
        wrong_tenant = event(
            "CANARY_TENANT", 0, "needle WRONG_TENANT_NONCE", tenant="TENANT_B"
        )
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "needle WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        recent_step = EvaluationStep(
            step_id="RECENT_STEP",
            step_type="recent_evidence_control",
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
            language="en",
            current_question="needle",
            authoritative_events=(recent_gold,),
            gold_event_ids=frozenset({"RECENT_GOLD"}),
            gold_message_ids=frozenset({"MESSAGE_RECENT_GOLD"}),
            gold_atoms=frozenset({"CURRENT_NONCE"}),
        )
        scope = validate_isolation_challenge(
            (recent_gold, wrong_tenant, wrong_conversation),
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
            challenge=CHALLENGE,
            current_question="needle",
            authoritative_events=(recent_gold,),
        )
        recent_audit = build_evaluation_step_audit(
            recent_step,
            self.encoding,
            scope_audit=scope,
            delivered_sources_by_arm={"B": (recent_gold,)},
        )
        self.assertFalse(recent_audit.all_required_gold_outside_b)

        no_evidence_step = EvaluationStep(
            step_id="NO_EVIDENCE_STEP",
            step_type="no_evidence_distractor_isolation_control",
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
            language="en",
            current_question="needle",
            authoritative_events=(recent_gold,),
            abstention_required=True,
        )
        no_evidence_audit = build_evaluation_step_audit(
            no_evidence_step,
            self.encoding,
            scope_audit=scope,
            delivered_sources_by_arm={"B": (recent_gold,)},
        )
        self.assertTrue(no_evidence_audit.abstention_required)
        self.assertEqual(no_evidence_audit.gold_event_ids, ())

    def test_same_id_substitution_is_rejected_before_bm25(self) -> None:
        original = event("TARGET", 0, "needle original")
        substituted = event("TARGET", 0, "needle altered")
        wrong_tenant = event(
            "CANARY_TENANT", 0, "needle WRONG_TENANT_NONCE", tenant="TENANT_B"
        )
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "needle WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        with self.assertRaises(ReplayIntegrityError):
            build_bm25_context(
                step((original,), "needle"),
                self.encoding,
                FRAMING,
                shared_events=(substituted, wrong_tenant, wrong_conversation),
                isolation_challenge=CHALLENGE,
            )

    def test_canaries_must_be_lexical_and_have_distinct_sentinels(self) -> None:
        target = event("TARGET", 0, "needle target")
        wrong_tenant = event(
            "CANARY_TENANT", 0, "unrelated WRONG_TENANT_NONCE", tenant="TENANT_B"
        )
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "needle WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        with self.assertRaises(ReplayIntegrityError):
            validate_isolation_challenge(
                (target, wrong_tenant, wrong_conversation),
                tenant_id="TENANT_A",
                conversation_id="CONVERSATION_A",
                challenge=CHALLENGE,
                current_question="needle",
                authoritative_events=(target,),
            )

        embedded_sentinel = event(
            "CANARY_TENANT",
            0,
            "needle XWRONG_TENANT_NONCEY",
            tenant="TENANT_B",
        )
        with self.assertRaises(ReplayIntegrityError):
            validate_isolation_challenge(
                (target, embedded_sentinel, wrong_conversation),
                tenant_id="TENANT_A",
                conversation_id="CONVERSATION_A",
                challenge=CHALLENGE,
                current_question="needle",
                authoritative_events=(target,),
            )

    def test_canary_must_reuse_all_non_nonce_question_terms(self) -> None:
        target = event("TARGET", 0, "Where is TARGET_NONCE")
        wrong_tenant = event(
            "CANARY_TENANT", 0, "Where WRONG_TENANT_NONCE", tenant="TENANT_B"
        )
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "Where is WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        with self.assertRaises(ReplayIntegrityError):
            validate_isolation_challenge(
                (target, wrong_tenant, wrong_conversation),
                tenant_id="TENANT_A",
                conversation_id="CONVERSATION_A",
                challenge=CHALLENGE,
                current_question="Where is TARGET_NONCE?",
                authoritative_events=(target,),
            )

    def test_unknown_step_types_and_evidence_bearing_abstention_are_rejected(self) -> None:
        source = event("SOURCE", 0, "source")
        common = dict(
            step_id="INVALID_STEP",
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
            language="en",
            current_question="question",
            authoritative_events=(source,),
        )
        with self.assertRaises(ValueError):
            EvaluationStep(step_type="primary_out_of_window_three", **common)
        with self.assertRaises(ValueError):
            EvaluationStep(
                step_type="recent_evidence_control",
                gold_event_ids=frozenset({"SOURCE"}),
                abstention_required=True,
                **common,
            )
        with self.assertRaises(ValueError):
            EvaluationStep(
                step_type="recent_evidence_control",
                gold_event_ids=frozenset({"SOURCE"}),
                gold_atoms=frozenset({"lowercase-invalid"}),
                **common,
            )

    def test_step_audit_rejects_unregistered_cross_scope_delivery(self) -> None:
        target = event("TARGET", 0, "needle CURRENT_NONCE")
        wrong_tenant = event(
            "CANARY_TENANT", 0, "needle WRONG_TENANT_NONCE", tenant="TENANT_B"
        )
        wrong_conversation = event(
            "CANARY_CONVERSATION",
            0,
            "needle WRONG_CONVERSATION_NONCE",
            conversation="CONVERSATION_B",
        )
        unregistered = event(
            "UNREGISTERED_WRONG_TENANT",
            0,
            "needle OTHER_SCOPE_NONCE",
            tenant="TENANT_C",
        )
        target_step = EvaluationStep(
            step_id="RECENT_TARGET",
            step_type="recent_evidence_control",
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
            language="en",
            current_question="needle",
            authoritative_events=(target,),
            gold_event_ids=frozenset({"TARGET"}),
            gold_message_ids=frozenset({"MESSAGE_TARGET"}),
            gold_atoms=frozenset({"CURRENT_NONCE"}),
        )
        scope = validate_isolation_challenge(
            (target, wrong_tenant, wrong_conversation),
            tenant_id="TENANT_A",
            conversation_id="CONVERSATION_A",
            challenge=CHALLENGE,
            current_question="needle",
            authoritative_events=(target,),
        )
        with self.assertRaises(IsolationViolation):
            build_evaluation_step_audit(
                target_step,
                self.encoding,
                scope_audit=scope,
                delivered_sources_by_arm={"E-BM25": (unregistered,)},
            )


if __name__ == "__main__":
    unittest.main()
