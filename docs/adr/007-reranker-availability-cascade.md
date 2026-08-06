# ADR-007: Reranker Availability — GCP Primary, AWS Fallback Cascade

**Date:** 2026-08-06
**Status:** Accepted
**ORQ reference:** ORQ-24
**Superseded by / Supersedes:** Amends ADR-006 (§reranker backend choice) without superseding it —
ADR-006's AWS incumbent, confirmed by ORQ-22's tied-quality benchmark, remains correct on quality
grounds; this ADR addresses availability, a dimension ADR-006 did not evaluate.

---

## Context

ORQ-23's golden-set regression (`implementation.md` Task 4) observed real AWS Bedrock Rerank
throttling — 6 of 20 calls (30%) fell back to RRF order despite 16s pacing (~4 calls/min). The
ORQ-23 closure pass investigated this with real AWS Service Quotas API calls
(`.framework/orqs/ORQ-23-retrieval-pipeline/aws_quota_finding.md`) and found the account's applied
quota for `amazon.rerank-v1:0` (`L-AAB0080F`) is **2 requests/minute, `QuotaAppliedAtLevel:
ACCOUNT`, `Adjustable: false`** — confirmed identical in both `us-west-2` and `ca-central-1`, so
the constraint is account-wide, not tied to region choice. This is half the golden set's own
pacing rate and is not self-service raisable via the Service Quotas console.

ORQ-22's benchmark already found AWS, GCP, and local Qwen tied on every pre-registered quality
metric (`docs/reranking_benchmark.md`), so quality does not favor either cloud backend. ORQ-23
already ships a production-usable `GcpReranker` adapter and settings
(`reranker_gcp_project`/`reranker_gcp_location`/`reranker_gcp_model`), unused in production before
this ADR.

## Decision

Make **GCP Vertex the primary production reranker**, with **AWS Bedrock as an automatic
availability fallback**, via a new `CascadingRerankerAdapter` (`app/core/providers/
cascading_reranker.py`, ORQ-24) that implements the existing `RerankerPort` contract.
`RetrievalPipeline` (ORQ-23) requires no change — it receives a `RerankerPort` and has no
knowledge that a cascade happens beneath it.

The cascade triggers on a `TransientRerankerError` from GCP, or on a narrowly-scoped defensive
catch of any other exception from the GCP call specifically (design-review finding: unlike
`AwsReranker`, `GcpReranker` has no blanket exception-normalization catch — fixing that inside the
existing adapter was ruled out of scope, so `CascadingRerankerAdapter` closes the gap at its own
boundary instead). A `TerminalRerankerError` from GCP (broken credentials, invalid project) is
GCP's own "configuration fault" signal and propagates directly without trying AWS, since AWS
cannot fix a GCP configuration problem. If AWS also fails, its `RerankerError` propagates so
`RetrievalPipeline`'s existing RRF fallback (unchanged since ORQ-23) still applies.

No new GCP production settings were added — `reranker_gcp_*` were already production-usable
fields from ORQ-23, only unused until this ADR activated them as the default primary.

## Consequences

### Positive

- Removes a hard, non-adjustable 2 req/min ceiling as the effective throughput limit of the
  retrieval pipeline's reranking step — GCP becomes primary specifically because it has no
  equivalent observed constraint.
- No quality regression risk: ORQ-22's tied benchmark means switching primary backends does not
  trade off relevance.
- `RetrievalPipeline` and both existing adapters (`AwsReranker`, `GcpReranker`) are untouched —
  the change is fully contained in a new adapter plus one factory function.
- AWS is retained as a genuine fallback, not discarded — the account still benefits from AWS's
  2 req/min of headroom during a GCP outage, and ADR-006's quality rationale for AWS is preserved
  as evidence, not overturned.

### Negative / Trade-offs

- GCP becomes the primary dependency for production reranking without its own quota ceiling
  having been formally verified the way AWS's was (ORQ-23 closure pass) — Risk R1 in ORQ-24
  spec.md flags this as a signal for ORQ-25's evaluation harness to monitor, not a blocker here.
- `GcpReranker`'s lack of a blanket exception-normalization catch (unlike `AwsReranker`) remains
  unfixed in the adapter itself; `CascadingRerankerAdapter`'s defensive boundary catch mitigates
  the operational risk but does not correct the underlying asymmetry between the two adapters.
- One more layer of indirection in the reranking call path (cascade → primary/fallback) versus a
  single direct adapter call.

## Alternatives Considered

### Alternative A: Accept the fallback, document the risk in ADR-006

Keep AWS as the sole production reranker; add a risk note to ADR-006 accepting RRF-fallback
degradation as sufficient for production. Discarded once ORQ-23's closure pass quantified the
actual quota (2 req/min, account-level, not adjustable) — a hard ceiling well below plausible
interactive traffic from even a single active tenant, not a artifact of an unpaced test burst.

### Alternative B: Request an AWS quota increase

`Adjustable: false` on `L-AAB0080F` rules out a self-service Service Quotas increase; would
require an AWS Support case with no guaranteed outcome or timeline. Not pursued as the primary
path given GCP's already-tied quality and already-built adapter made an immediate architectural
fix available without waiting on AWS support.

### Alternative C: AWS primary, GCP fallback (reversed cascade)

Rejected — this does not address the actual constraint. AWS's quota problem is upstream of any
call ordering; making AWS primary keeps the 2 req/min ceiling as the pipeline's effective limit
regardless of what backs it up.

## Evidence

- `.framework/orqs/ORQ-23-retrieval-pipeline/aws_quota_finding.md` — real AWS Service Quotas API
  output, both `us-west-2` and `ca-central-1`.
- `docs/reranking_benchmark.md` — ORQ-22's tied-quality benchmark evidence.
- `.framework/orqs/ORQ-24-reranker-availability-cascade/spec.md` — full design, including the
  design-review finding on `GcpReranker`'s exception-normalization gap and its mitigation.
- `app/core/providers/cascading_reranker.py` — implementation.
- `tests/core/test_cascading_reranker.py` — unit and end-to-end test coverage of all cascade
  branches (primary success, transient/terminal/unnormalized GCP failure, both-fail propagation,
  content-free telemetry).
