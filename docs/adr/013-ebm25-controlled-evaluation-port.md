# ADR-013: E-BM25 Controlled Production Evaluation — Port, Mode B, and Honesty Controls

**Date:** 2026-09-08
**Status:** Accepted
**ORQ reference:** ORQ-37
**Superseded by / Supersedes:** Amends ADR-008 §5

---

## Context

`experiments/long_context_conversational_memory` produced E-BM25 as one arm of
an offline evaluation. ORQ-37 ports its ranking and selection into `app/`
behind a flag (`ebm25_enabled`), for controlled production evaluation under
uncertainty — not because the offline result was a production validation.
This ADR is the one non-negotiable place that premise is recorded outside
`spec.md`, and it records every divergence between the ported code and the
experiment, so a future reader can tell "reimplemented differently on
purpose" from "silently drifted."

**The premise, verbatim, on one line so a plain `grep -F` finds it regardless
of how either file happens to be soft-wrapped:**

E-BM25 is being integrated for controlled production evaluation under uncertainty, not because it has been scientifically confirmed.

A failed production gate resolves to disabled or reverted, never "never
integrated." ORQ-35 produced no `GO`/`NO_GO`.

## Decision

1. **Reimplemented, not imported.** `app/core/domain/bm25_ranking.py` and
   `app/core/domain/conversation_turns.py` reproduce the experiment's
   `rank_bm25`/`_pack_retrieved_events`/total-grouping-rule logic from
   scratch. No module under `app/` imports from `experiments/`
   (`grep -rn -e '^[[:space:]]*import experiments' -e '^[[:space:]]*from experiments' app/`
   returns clean).

2. **Total grouping rule (§Diseño 9), total on arbitrary input.** Walk
   messages in ascending `sequence`; a `user` message opens a turn and the
   immediately following `assistant` message closes it; any other transition
   (a second consecutive `user`, a leading `assistant`, a `system` row, an
   odd tail) emits a singleton. `document_text` is `"\n".join(contents)` in
   every case, reproducing `Event.document_text()`. Landed in
   `conversation_turns.py` (Gate B1, T10) rather than alongside the ranking
   port (T16, Gate B2) by operator decision, because the recent window's
   turn-snap needs the same rule at Gate B1 — snapping is a Gate B1 property
   of the window, not a Mode B behaviour — and T16 reuses the identical
   primitive rather than a second implementation that could disagree with it
   about what a turn is.

3. **Four divergences from the experiment, each declared:**

   | Divergence | Experiment | Port |
   |---|---|---|
   | Document unit | `Event`, joining every message of an exchange | `TurnUnit`/`CorpusEvent`, via the same total grouping rule |
   | Tie-break | `(-score, event_sequence, event_id.encode("utf-8"))` | `(-score, event_id)` — `event_id` is already `min(sequence) of the turn`, unique per conversation snapshot, so the byte-ordered third key has no counterpart and is not needed for totality |
   | Query tokens | Deduped then capped at 256, in that order | Identical order, reproduced exactly (`bm25_ranking.query_tokens`) |
   | Packing budget | Token budget (`E_RETRIEVED_TOKEN_BUDGET`, via a tokenizer encoding) | **Character** budget, matching this ORQ's combined-budget design throughout (§Diseño 7). `BM25_TOP_K` is still checked *before* the size test, and an oversized event is skipped (not a `break`) so a later, smaller one can still be admitted — the exact control flow of `_pack_retrieved_events`, substituted onto `len(document_text)` |

   `filter_event_scope`'s tenant/conversation filtering has no analogue
   either: `fetch_ordered` already returns exactly one owned conversation
   (ADR-011 §2), so the corpus this ranks is scoped before it reaches the
   port.

4. **The four BM25 constants equal the experiment by value:**
   `BM25_QUERY_TOKEN_CAP=256`, `BM25_TOP_K=5`, `BM25_K1=1.2`, `BM25_B=0.75`
   (`replay.py:19-22`). Parity is proven by constructing both representations
   — `CorpusEvent` (port) and `Event` (experiment) — from the same
   `group_turns` output over the same message fixtures, so a mismatch would
   reflect a genuine algorithmic difference, not a fixture-authoring one.
   Ordering and scores match exactly across four fixtures covering a
   split-turn-and-odd-tail, a `system` row, a consecutive same-role run, and
   a single-message conversation.

5. **Mode B's combined-budget priority: the window is protected, evidence
   yields.** §Diseño 7's drop order is explicit — out-of-window retrieved
   evidence drops before any recent-window turn. The recent window is packed
   first, against the full combined cap; evidence is ranked and packed
   against only what remains. An earlier design note (recorded in T13's own
   implementation, then corrected) assumed the opposite priority; the
   correction is recorded here so the reasoning is not lost to a stale
   comment.

6. **Two named inert states, each distinctly recorded.** An empty corpus
   (the snapped window already covers the whole conversation) records
   `memory_outcome=no_out_of_window_corpus`; evidence that existed and was
   ranked but received no budget after the window's protected share records
   `memory_outcome=budget_starved`. Both record `ebm25_selected_count=0`. A
   Mode B integration that changes nothing is exactly the failure this
   distinction exists to make visible rather than silently absorbed into
   "ok".

7. **`ebm25_enabled: bool = False`, matching this repository's uniform flag
   convention.** Mode A and Mode B share provider, model, generation config,
   the `rag` key, the messages list, reranker identity, and fallback policy —
   identical in both modes. Toggling the flag changes only the `memory`
   metadata key and nothing else, verified by a `ProviderInput` comparison
   over a fixed request. With the flag off, the rendered prompt is
   byte-identical to the baseline frozen at Gate B1's close — the
   materialized, turn-snapped, well-formedness-filtered window — because Mode
   A is not a second, separately-maintained code path: `ebm25_enabled=false`
   simply skips the Mode B block entirely.

8. **Rollback is the same toggle.** Flipping `ebm25_enabled` to `false`
   restores Mode A with no migration executed and no data removed;
   `alembic current` is identical before, during, and after the flag changes
   (verified live against a running database — flipping a `Settings` boolean
   touches no schema and issues no database statement at all). The
   `rag_request_metrics` table and its index stay inert.

9. **ADR-008 §5 is amended: the chat-response-cache bypass extends to
   `ebm25_enabled`.** ADR-008 §5 bypasses the cache whenever chat RAG
   augmentation is enabled, because its key does not include corpus or
   retrieved-source identity. `_cache_key` fingerprints the messages list
   (which covers the recent window by construction) but not `metadata`,
   where retrieved out-of-window evidence travels. In the configuration
   `conversation_history_enabled=true, ebm25_enabled=true,
   chat_rag_augmentation_enabled=false`, the cache would otherwise be live
   and could serve an answer built on one evidence set to a later request
   whose evidence differs — exactly the failure ADR-008 §5 already
   legislated against for the documental channel. The bypass is extended to
   cover it.

10. **Honesty controls (§Diseño 12).** No artifact this ORQ produces —
    document, ADR, dashboard panel, log message, commit message — may
    describe the integration as validation, confirmation, or evidence that
    E-BM25 works, matched case-insensitively as whole words within 80
    characters of `E-BM25`, against a fixed enumerated list (`validated`,
    `validates`, `validation`, `confirmed`, `confirms`, `confirmatory`,
    `proven`, `proves`, `demonstrated`, `established`, `verified effective`,
    `shown to work`, `evidence that it works`), with two scoped exceptions:
    the premise sentence itself (containing "scientifically confirmed" as
    part of a negation) and any sentence stating E-BM25 is *not* validated or
    confirmed. Mode B's own metrics are operational telemetry for a future
    comparison, not a result. The mechanical sweep against this list is
    ORQ-37's T21.

## Consequences

### Positive

- A future reader can verify parity against the experiment directly — the
  divergence table above is exhaustive, not a pointer to "see the diff."
- Mode B's two failure modes are distinguishable from success and from each
  other in the metrics themselves, not inferable after the fact from an
  absence of rows.
- The premise sentence appearing verbatim in exactly two places (`spec.md`,
  this ADR) means no artifact can describe E-BM25's status without either
  matching one of those two sentences or tripping the honesty sweep.

### Negative / Trade-offs

- The character-budget divergence means Mode B's admitted-evidence set is not
  directly comparable, item-for-item, to the experiment's own token-budgeted
  runs — a future cost/quality comparison must account for the different
  budget unit.
- Two inert states sharing one `memory_outcome` field with B1's existing
  values (`ok`, `empty`, `conversation_not_found`, `timeout`, `error`,
  `skipped_first_turn`) means the field's cardinality grows; a consumer that
  enumerated the old set exhaustively needs updating.
- The cache bypass extension means Mode B traffic never benefits from
  response caching at all, by design — correctness over hit-rate, the same
  trade-off ADR-008 §5 already accepted for the documental channel.

## Alternatives Considered

### Import `experiments/` directly and wrap it

Rejected: would couple `app/` to a module tree with its own evaluation-only
invariants (isolation challenges, canary tokens, teacher-forced replay
semantics) that have no meaning in production, and would violate the
boundary AC23 exists to enforce.

### Keep the experiment's token budget by adding a tokenizer dependency

Rejected: this ORQ's combined added-context budget (`chat_prompt_max_added_context_chars`)
is characters throughout, matching the ceiling documental RAG already had. A
second, token-based sub-budget for one channel only would make the combined
cap incoherent — two different units competing for one number.

### Give the retrieved-evidence budget priority over the recent window

Considered and rejected per §Diseño 7's explicit drop order: the window is
the conversation's own recent turns; evidence is a Mode B addition. Dropping
the addition before the conversation's own recent context is the stated
priority, not an implementation choice.

## Evidence

- ORQ: `.framework/orqs/ORQ-37-rag-in-production/spec.md` (§Objetivo carries
  the premise sentence verbatim; §Diseño 8, §Diseño 9, §Diseño 10 carry the
  full design)
- Implementation record: `.framework/orqs/ORQ-37-rag-in-production/implementation.md`
  (T10, T15, T16, T17, T18, T19 entries)
- Parity tests: `tests/core/test_bm25_ranking.py`
- Rollback evidence: `tests/infra/test_ebm25_rollback.py`,
  `tests/api/test_ebm25_rollback_behavior.py`
- Amends: `docs/adr/008-rag-generation-and-feedback-boundaries.md` §5 (cache
  bypass extended to `ebm25_enabled`)
- Related: ADR-012 (observability, history substrate, per-request metrics;
  the ADR-008 §3 amendment)
