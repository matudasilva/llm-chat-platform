# Direct C1 old/new comparison prospective independent review

**C1_COPY_COMPARISON_HARNESS_REVIEW_PASS** for final plan
`248e9fb62ff98c54f3590b487b078413d4397dac6035ef4ddfde74916b0f9bc9`.
Scope is the separately authorized40-request local diagnostic, never a G6 PASS.

Both arms use Capture, candidate=True installation, scoped invocation/application
attempt tracking, native SDK attempt hooks and candidate_evidence validation.
The old arm is not C0 or a lightweight Tape control: it is immutable C1 image7417,
compared directly with the reviewed one-file C1 overlay4e68. env_for('c1','C1') is
used in both arms. Cache c0/c1 suffixes only distinguish private Redis namespaces;
they do not select runtime or evidence semantics. Exact same paired request/
conversation IDs and histories are installed in distinct fresh databases.

Independently checked that the ingress/send clock helper ASTs exactly match the
reviewed aggregate worker. Wall-then-process-CPU start and CPU-then-wall end
preserve the original endpoint before primary Capture bookkeeping. Original
capture, hash/attempt/evidence and functional response/deadline/cleanup checks
remain active in both arms. No fine profiler or observer disabling is installed.

Four focused controls independently passed under P2; XML review-tests.xml. They
cover paired counts/order, missing-review refusal before Docker, incompatible
packet rejection and candidate installation. Static inspection additionally
confirmed Capture construction and required candidate_evidence in both arms.
No actual API, SQL, Docker, provider operation or code fix was performed by the
reviewer. The cache_dir warning is from pytest's disabled cache plugin.

Final ordering is old/new for EN JSON and ES SSE, new/old for EN SSE and ES JSON.
Each image runs first once per language and once per protocol. The author changed
this prospectively before execution to remove the initial perfect protocol/order
confounding; initial plan/preparation and initial reviewer test XML are retained.
Samples, fixtures, databases and images did not change in that amendment. Fixed
counterbalancing still does not eliminate host jitter or every time/cell effect.

The frozen protocol specifies all16 measured pair deltas, category/cell medians
and ranges, sign counts and order strata; it invents no performance PASS threshold.
Four measured category pairs and eight warmup requests are diagnostic only.
Mixed/small results must remain inconclusive and cannot justify a formal gate
rerun or paid admission automatically. Process CPU includes background threads;
do not subtract it from wall to infer waits or correct historical p95.

Final source/support/protocol/test hashes and plan/fixture/preparation bindings
match. The immutable pin and both complete app inventories identify only the
previously reviewed context_evidence.py delta. Parent read-only prepared-data
verification confirms exact20 conversations/384 messages per arm, P3/RLS/schema
and normalized effective config parity using both actual C1 images. Parent
executed that verifier; reviewer inspected source/receipt only.

Controller requires an exact-plan review receipt and preserves a durable global
execution-started marker before any worker start. No automatic resume/resend is
available after partial failure. Image/resource/topology and pristine fresh-data
hashes are checked before admission. No execution marker/result existed at review.
No BLOCKER/HIGH/MEDIUM defect was identified in this prospective scope. Original
CONTROLLED_G6_FAIL, thresholds, P5 and paid-admission block remain unchanged.
