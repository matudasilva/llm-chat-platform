# Minimal lexical-query computation remediation — awaiting approval

**PROPOSED_AWAITING_INDEPENDENT_REVIEW_AND_OPERATOR_APPROVAL**.
No app source, candidate query or new measurement has been changed/executed.

## Evidence and intended change

The twenty matched-mode observations show higher generic execution times in all
ten cases, concentrated in the keyword filter retaining parameterized
plainto_tsquery. The custom plan holds a literal tsquery. The earlier real-driver
probe selected generic after five calls. This supports testing a computational
change without replacing the technology stack, disabling C1 or forcing custom
in runtime. It does not certify the historical A/A label gap's cause.

Candidate to review: compute the same plainto_tsquery('english', :query_text)
once for the statement, then reuse its value for the keyword WHERE and both
ts_rank expressions. A one-row MATERIALIZED CTE placed after the unchanged
semantic CTE is the smallest candidate to validate:

    lexical_query AS MATERIALIZED (
        SELECT plainto_tsquery('english', :query_text) AS terms
    ),

The keyword CTE would reference lexical_query.terms through a CROSS JOIN rather
than repeating the function. This is a proposal, not a proven implementation:
local plans must demonstrate the intended evaluation placement. No SQL is
executed by this document.

Preserve all five ORDER BY/id tiebreakers, both CTE limits/window ranks, RRF_K60,
semantic vector search, English text-search configuration, arguments/results,
metadata, tenant context and RLS. No index/schema, cache/driver/pool policy,
global setting, feature flag, model, threshold or new dependency. One retrieval
SELECT remains one SELECT/roundtrip. No provider/domain/route contract change.
Exception/empty-tenant behavior must also remain equivalent; changing expression
evaluation placement must not introduce a functional difference.

## Smallest implementation surface after approval

1. app/core/providers/pgvector_store.py — SQL string only, if proof succeeds.
2. tests/core/test_pgvector_query_equivalence.py — new real-PostgreSQL semantic
   regression using the frozen previous SQL as a reference, plus the existing
   test_pgvector_store_determinism.py/RLS suites without weakening assertions.
3. Minimal ORQ evidence/plan references; candidate source/image pin only after
   review. Do not modify P5, domain services, /chat, SSE, retries or persistence.

ADRs006 and009 constrain isolation and exact tie/membership policy; those
decisions are preserved. No new architecture, control plane or cache mechanism.
Escalate any wider change before implementation.

## Required proof before accepting a runtime change

- Begin with an isolated candidate SQL fixture, then compare ordered chunk IDs,
  document IDs, text/metadata and exact RRF scores against the frozen original,
  under custom and generic modes on a disposable real-PG corpus.
- Include positive lexical-only matches, semantic-only/overlapping groups,
  forced score/membership ties, empty/stopword/punctuation/quoted queries,
  EN/ES, top_k boundaries and no/unknown/other tenant scopes. The current
  ES zero-keyword-match observations alone are insufficient.
- Check error/empty-corpus/empty-tenant parity; any changed result/error/isolation
  is a failure, not justification to relax the contract.
- Verify the generic plan's lexical value is produced once outside the
  per-chunk filter, retaining cardinalities/ranking. No percentage threshold
  waiver or correction of original timing. Query rewrites need measured proof.
- Validate actual SQLAlchemy/asyncpg parameter inference and normal auto-cache
  warmup with no /chat/providers; freeze exact diagnostic volume and identities
  before any new performance observation. Use P2, local PG/stubs, no credentials
  for external services and no external calls. External spendUSD0.
- Run focused equivalence/determinism/RLS tests first, then only affected local
  regressions. Do not rerun unrelated closed gates or change fixtures to pass.
- Independent review before accepting the patch/new source pin. No automatic
  image build, A/A, formal G6 or paid campaign; each needs the existing scoped
  authorization/source review discipline.

Current authorization ends with the completed20-query diagnostic. Approval is
needed for this limited runtime SQL remediation and its local tests, preceded
by independent review of the finding/proposal. No implementation is authorized
by this proposal. Preserve all original FAILs and the paid block.
