# Proposed diagnostic: compare custom and generic plans with actual driver types

**PROPOSED_AWAITING_OPERATOR_APPROVAL**. Design only; no query or setting change.

The completed driver diagnostic observed five custom then25generic selections,
with generic combined calls taking19.529-24.140ms despite no C1/SSE/provider work.
It did not inspect either mode's execution plan under matched conditions or
certify the historical A/A cause. The preceding psql probe used a different
explicit parameter signature; reuse the newly captured actual signature instead.

## Smallest next comparison

- New disposable PG-only clone, same pinned image/schema/P3/roles/locale/settings,
  same fixed ANALYZE/preflight proof; no original environment/database mutation.
- Same ten ES document/combined cases and values, one execution per case/mode:
  **20 hybrid SELECT executions total**, C=1, no retries/repeats/extra warmups.
- Exact captured compiled-query.sql with argument order embedding/top_k/query/rrf,
  PREPARE parameter types vector,bigint,text,bigint. Preserve SQL/query policy,
  data, RLS tenant and top_k20/rrf60. No app/adapter/source modification.
- For each case, use two fresh read-only rag_app sessions. In one transaction
  SET LOCAL plan_cache_mode=force_custom_plan; in the other force_generic_plan.
  These are deliberately controlled diagnostic interventions only; normal
  runtime/campaign mode remains auto. No ALTER SYSTEM, global/role defaults or
  .env change. Each connection ends with rollback and disconnect.
- Fix mode order before execution: custom first for case pairs1,3,5,7,9,
  generic first for2,4,6,8,10. Keep the existing document01/combined01 through
  document05/combined05 case order. Do not select a favorable repetition.
- One EXPLAIN(ANALYZE,BUFFERS,SETTINGS,FORMAT JSON) EXECUTE per case/mode, bounded
  by statement30s/lock5s. Retain exact SQL/parameter hashes, inferred-type lineage,
  role/tenant/read-only/settings, selected-mode counters and full plans/raw logs.
- Stop new admissions on unresolved/ambiguous infrastructure or identity errors;
  retain every admitted/error case and never resend. Preserve data/markers.

## What this can and cannot decide

Compare node structure, filter expressions, rows/loops, buffers/spills and
server planning/execution. Inclusive node times are not additive. Do not assume
repeated plainto_tsquery or any other mechanism without plan evidence.
Require semantic input identity and expected output cardinality/RLS in both modes;
execution completeness is a diagnostic result, not a latency/G6 PASS threshold.

A mode-dependent result would support a specific SQL-path hypothesis. It would
not prove the original8.42% label difference or justify silently forcing custom
in production/calibration. Any SQL rewrite, index, cache policy or app change
requires a separate minimal proposal, semantic regression tests and approval.
No further A/A, campaign, provider, G9, Notion or commit.

External/provider spendUSD0; only local CPU/disk. No image download/dependency.
Keep all historical FAILs, CONTROLLED_G6_FAIL and BLOCKED_CONTROLLED_G6_FAIL.

Approval requested only for preparing/freezing and executing this one20-query
read-only local diagnostic, including the two transaction-local forced plan modes.
