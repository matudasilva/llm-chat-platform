# ADR-012: RAG in Production — Observability, History Substrate Hardening, and Per-Request Metrics

**Date:** 2026-09-08
**Status:** Accepted
**ORQ reference:** ORQ-37
**Superseded by / Supersedes:** Amends ADR-008 §3, ADR-011 §Diseño 6 (`total_available`)

---

## Context

ORQ-37 puts conversation history and documental RAG into continuous production
use for the first time, and adds a controlled evaluation of a second retrieval
channel (E-BM25, recorded separately in ADR-013). Gate A and Gate B1 needed
observability, dependency, dashboard, hardening, tuning-evidence, and
per-request-metrics decisions that touch three existing ADRs and one
constitution document. This ADR records the ones that are not specific to the
BM25 port itself.

## Decision

1. **OpenTelemetry as a runtime dependency (D-1).** `opentelemetry-api`,
   `opentelemetry-sdk`, and `opentelemetry-exporter-otlp-proto-http` are
   pinned in `app/requirements.txt`/`.lock` (all three released in lockstep,
   version `1.44.0`). `app/core/observability/tracing.py` is the only module
   under `app/` importing `opentelemetry`, and it does so lazily inside
   `init_tracing()`. Disabled by default (`otel_enabled=False`); a tracer
   double raising on every span, and separately a slow/hung exporter, must
   leave `/chat` and `/retrieval` responses identical to a tracing-disabled
   run (AC2). This is the dependency `tech-stack.md` did not previously
   record; it is updated in this change.

2. **The `(conversation_id, sequence)` index, and the corrected strength of
   `total_available`.** ADR-011 §Diseño 6 states `fetch_ordered` "reads the
   full conversation and bounds afterwards, so `total_available` is
   meaningful." ORQ-37 adds `conversation_history_max_rows` (default 2 000),
   enforced in SQL as `ORDER BY sequence DESC LIMIT n`, re-sorted ascending.
   Under that cap, **`total_available` means rows available within the cap**,
   not the true total. This narrows ADR-011's claim; the narrowing is
   declared here rather than left as an undeclared divergence. The additive
   `ix_messages_conversation_id_sequence` index (migration `d29e6a1f4c87`)
   discharges only the `(conversation_id, sequence)` half of ADR-011's
   disclosed index debt — the half naming `tenant_id` remains undischarged.
   `EXPLAIN`/latency evidence at two conversation lengths (5 000 and 50 000
   rows) is recorded in `.framework/orqs/ORQ-37-rag-in-production/implementation.md`
   and `ac15-explain-evidence.txt`.

3. **The cache-key sentence in `tech-stack.md` is corrected, not vindicated.**
   `tech-stack.md` claimed cache keys "fingerprint the full conversation
   history, not just the last message." The recent-window turns enter the
   messages list the cache key already fingerprints, so the key covers the
   **bounded window**, never the full history a long conversation may hold.
   The sentence is corrected to state what is actually enforced.

4. **A dedicated `rag_request_metrics` table, sibling to `usage_events`,
   correlated advisorily on `request_id`.** Chosen over extending
   `UsageEvent` because rollback-without-destructive-migration means "stop
   writing rows, table stays inert," while removing columns later is
   destructive, and because `UsageEvent` already carries its own disclosed
   `tenant_id` debt that this table does not inherit — `tenant_id` is a
   column here. Identity is server-side: `request_instance_id` (the `uuid4`
   minted in `RequestContextMiddleware`) is `NOT NULL UNIQUE`; `request_id`
   (the client-suppliable correlation header) is indexed but never unique, so
   a replayed header cannot corrupt attribution. Grants are split exactly:
   the runtime role (`chat_ops`) holds `INSERT` only and can neither read the
   table back nor delete from it; a separate, operator-held
   `chat_ops_retention` role — never referenced in the application's own
   configuration — holds `SELECT`/`DELETE` and nothing else. `rag_request_metrics_enabled`
   defaults `false`, matching the repository's uniform flag convention.

5. **The operational retention contract, with all six required terms, and its
   residual risk disclosed rather than mitigated.** Enforcement is a
   documented, manually-run parameterized `DELETE` (published in
   `docs/observability/rag_request_metrics_retention.md`), exactly as a
   migration is run — never a scheduler, cron entry, lease, watchdog, or
   background worker. The six terms:

   | Term | Value |
   |---|---|
   | Window | `rag_request_metrics_retention_days`, default 30 days |
   | Owner | a named operator role, assigned before production enablement — not "the team" |
   | Procedure | the published statement, run explicitly |
   | Maximum cadence | at least once every 7 days |
   | Maximum tolerated delay | 37 days (window plus one cadence period) — an operator-auditable breach threshold, not application-enforced |
   | Evidence of execution | a retention log entry per run: timestamp, operator, rows deleted, oldest surviving `created_at` |

   The contract gates **enablement**, not **continuation**: production
   enablement of `rag_request_metrics_enabled` requires the contract to exist
   with an assigned owner and a first logged execution, or privacy readiness
   fails and the flag stays `false`. ORQ-37 adds no mechanism that detects a
   missed run or fails closed past the 37-day threshold — after a first
   logged execution, rows can accumulate indefinitely with every acceptance
   criterion in the spec still green. This is a **residual operational risk**
   (R19), carried by the contract's named owner, not closed by this ORQ, and
   no artifact produced by it may describe retention as automatic or
   runtime-enforced.

6. **ADR-008 §3 is amended: "one canonical system message" becomes two, in a
   fixed order.** ORQ-37 adds a second envelope, for retrieved out-of-window
   conversation evidence (§Diseño 11, ADR-013 §Mode B). When both the
   documental (`rag`) and conversational (`memory`) channels are present, the
   memory envelope precedes the `rag` envelope, and both precede the
   conversation turns — enforced by construction in `messages_for_provider`
   (`app/core/domain/provider_prompt.py`), not by a sort. The envelope text
   for the new channel was approved verbatim by the operator (D-6b,
   2026-09-04) and is reproduced exactly; adding a second envelope for a new
   channel is structural containment, not prompt tuning, and the two
   decisions (mechanism, text) were made separately for that reason.

## Consequences

### Positive

- Tracing, the dashboard artifact, and the tuning-evidence machinery exist
  without changing `/chat`'s behavior when disabled, verified under
  tracer-raising and exporter-hang fault injection.
- The SQL row bound turns an unbounded history read into a provably bounded
  one, with the plan-shape and latency evidence to show the index is actually
  used (`Index Scan Backward`, no sort step, at 50 000 rows).
- Per-request metrics exist as a real table with a real, least-privilege
  write path, ready for Gate B2 traffic and future cost/quality comparison,
  without granting the request path any read or delete capability over its
  own writes.
- The retention contract is stated at its real strength — a gate condition on
  enablement — rather than implied as continuous enforcement it cannot
  provide without new runtime machinery this ORQ was directed not to add.

### Negative / Trade-offs

- `total_available`'s narrowed meaning is a second, ORQ-37-specific reading
  layered onto ADR-011's original claim; a future reader of ADR-011 alone
  would miss it without following this amendment.
- The retention contract's residual risk (R19) is real and disclosed, not
  closed: unbounded accumulation past 37 days is possible and undetected by
  anything in the running system.
- Two system-message envelopes instead of one adds a second thing every
  future provider adapter must hoist/inline correctly, and a second ordering
  invariant to preserve.

## Alternatives Considered

### Extend `UsageEvent` instead of a new table

Rejected: dilutes a per-generation-call billing record with mostly-NULL
pipeline columns, and inherits `UsageEvent`'s own disclosed `tenant_id` debt.
Rollback would require a destructive column removal rather than simply
stopping writes to an inert table.

### An application-enforced retention scheduler

Rejected by operator directive: no scheduler, cron entry, lease, watchdog, or
background worker is introduced anywhere in this ORQ. The operational
contract is the alternative — auditable, but not self-enforcing.

### Route the memory envelope through the existing `metadata["rag"]` key

Rejected: `messages_for_provider` validates `metadata["rag"]` against
`RAG_SCHEMA_VERSION` and a fixed required-keys shape; conflating the two
channels into one key would either break that validation or silently merge
two different trust/content contracts into one envelope, defeating the
containment boundary a second, distinctly-schemed envelope exists to hold.

## Evidence

- ORQ: `.framework/orqs/ORQ-37-rag-in-production/spec.md`
- Implementation record: `.framework/orqs/ORQ-37-rag-in-production/implementation.md`
  (T1–T4, T7, T8, T9, T11, T12, T13, T14, T17 entries)
- AC15 EXPLAIN/latency evidence: `.framework/orqs/ORQ-37-rag-in-production/ac15-explain-evidence.txt`
- Retention statement: `docs/observability/rag_request_metrics_retention.md`
- Dashboard artifact: `docs/observability/dashboard.json`
- Amends: `docs/adr/008-rag-generation-and-feedback-boundaries.md` §3 (one
  canonical system message becomes two, in a fixed order)
- Amends: `docs/adr/011-conversation-history-substrate.md` §Diseño 6
  (`total_available` narrowed to "available within the cap" under the new SQL
  row bound)
- Amends: `.framework/constitution/tech-stack.md` (cache-key sentence
  corrected to the bounded window, not the full conversation history)
- Related: ADR-013 (the E-BM25 port itself, Mode B, and the ADR-008 §5
  amendment)
