# Seeded paid fixtures independent review

**SEEDED_PAID_FIXTURES_INDEPENDENT_REVIEW_PASS**. Reviewer `/root/g9_final_distinct_reviewer` authored verify_seeded.py independently of the seeder. The parent executed the unchanged independent verifier with approved local Docker access under P2; this reviewer inspected its receipt, current verifier hash and all168 per-conversation results against prospective fixture IDs/message counts. This is delegated execution of independent verification code, not a claim that the reviewer directly issued the Docker SQL commands.

Every conversation UUID/tenant and every ordered message role/content/owner matches the approved prospective fixtures:168 conversations,3840 messages;3840 valid unique generated message UUIDs and strictly increasing positive sequence values. Extra conversations, extra/missing messages, wrong content, role, order or cross-tenant owner would fail. Per-conversation actual ID/order/content hashes are retained, with no raw contents in the receipt. Prospective message UUIDs were not specified: their generated validity/uniqueness and actual projection identity are verified, not compared against invented prospective UUIDs.

P3 is unchanged:124 documents/2146 chunks, expected fingerprint and full authoritative content projection hash match. rag_app sees124/2146 only for orq37-t23, and zero documents/chunks for all four history/empty tenants, empty context and unknown tenant. No new history-table RLS is claimed; existing operational-history isolation architecture and baseline grants are preserved. Target image/resources/internal network/no published ports match accepted preparation identities. Full fixture population was stable before and after verification.

## Exact schema discrepancy disposition

Initial strict schema assertion failed and was retained in schema-difference.txt. It exposed only the `ck_usage_events_feedback` dump/restore rendering:

- Cast `ARRAY[varchar 'up', varchar 'down']` to text[].
- Construct `ARRAY[CAST(varchar 'up' AS text), CAST(varchar 'down' AS text)]`.

Elementwise cast distribution yields exactly the same text[] values and equality/null semantics. The verifier permits only those two exact known full constraint lines, each present once; all remaining normalized DDL/grants/policies must be byte-identical. No broad SQL normalization or constraint omission was introduced. Both actual catalog expressions were evaluated in READ ONLY transactions against11 null/valid/case/whitespace/invalid controls; identical truth tables allow only null/up/down. Database locales match. Raw/normalized dump hashes and both expression hashes/truth tables are retained in seeded-verification.json. Schema parity here means this precisely demonstrated semantic equivalence, not an assertion that the two dump byte streams match. No DB/schema was changed to obtain PASS.

The independently authored verifier used only Docker inspection/pg_dump and PostgreSQL SELECT/COPY inside BEGIN READ ONLY / ROLLBACK plus transaction-local role/tenant context. No data/schema writes, API requests, model/providers, external network or paid spend. It was reexecuted after the narrowly reviewed verification-only schema adjustment, never by reseeding application fixtures. Original initialization failure and resume-empty preparation remain historical evidence, not failed paid requests.

## Remaining paid readiness gap

LocalAPI.execute/Completion does not retain the first-content arrival timestamp. Existing final UTC windows/total request latency/provider emission booleans cannot reconstruct streaming TTFT. Current seeded fixture PASS does not close G6 measurement readiness, target API/provider-capable network pins, controlled C1/C0 latency population, or post-campaign G7 usage reconciliation. See measurement-gap.md and the proposed client-measurement amendment. Approval is required before implementing that new harness-only observation scope. No paid sample was admitted by this review; the earlier P5 economic/STOP closure is preserved separately.
