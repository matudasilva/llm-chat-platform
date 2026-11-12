# Approved lexical-image binding implementation

**IMPLEMENTED_AWAITING_SOURCE_REVIEW**, 2026-11-10.
Authorization in this directory binds the approved image-only proposal and exact
source/image review chain. No calibration, formal G6 or paid execution authorized.

Technical changes are limited to `blocked_latency.py` and its existing focused
test module. The old contract/default image pair is unchanged. A new optional
image binding accepts only the exact hash-pinned operator approval, image receipt,
parent, SQL source review and application inventory. Both labels use the same
approved new image. A binding is reconstructed strictly; missing/extra/changed,
mixed-image and receipt/source drift are rejected before Docker/SQL. The support
manifest includes the approved chain and app-source hashes. It is not a general
image override or a change to the runtime/provider.

Preparation requires a separate environment authorization with this exact binding
and a distinct harness source-review receipt matching both current technical
files. The prepared receipt retains that review digest; execution preflight
rechecks it in addition to the existing exact-plan review and execution approval.
No execution permission is created here. The source review must finish before
real environment preparation.

P2 in the pinned775image: focused checks53PASS; regression219PASS/0skip in12.58s
across blocked-A/A, AA, controlled-G6 and cleanup suites. The first focused run
had44PASS/1failure because a new test omitted synthetic prepared configuration
hashes; the test fixture was corrected. The failed XML is retained. Unit tests
include memory-native JSON/SSE operations and synthetic controller receipts,
not a real calibration or real deployed API/provider operation.

New guards cover approval/receipt/inventory/source policy and hash drift,
missing/unknown/mixed binding fields, preservation of every old protocol guard,
review-before-service ordering, and valid/failed/cleanup/observation/no-resend
controller simulations with both old and new image profiles. Synthetic
hash-consistent receipt doubles explicitly rebind the expected approval hash
inside unit tests; real repository approval/receipt files remain read-only.

Seventeen existing core function ASTs are unchanged, including samples,
aggregation, resource/DB evidence, worker environment and execute. Worker bytes
and timing callbacks are unchanged. Of505 protected sources/configs,503 are
unchanged; only the two authorized technical files differ. App/P5/global-env,
model/threshold/accounting/schema/grants, retry/SSE/persistence unchanged.

Exact commands, source patch and validation hashes are retained here. Parent
executed the tests; distinct review is still pending at this snapshot. No real
database/provider/external operation, environment preparation, paid spend, new
image, G9, Notion or commit occurred. USD0; preserve all historical FAILs and
In Progress / Implement / DECISION_FREEZE_PASS.
