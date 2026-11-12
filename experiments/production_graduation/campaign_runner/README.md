# ORQ-41 P5 campaign runner

Campaign-only, serial harness. It is not imported by `app/`, does not provision
an environment, and reads no DB or usage credentials. Implementing this harness
does not authorize a paid campaign or change ORQ-41's Plan phase.

## Receipts and stops

One shared directory contains `ledger.jsonl`, `ledger.head` and the exclusive `runner.lock`.
Use that same ledger for every approved rerun; never delete, replace, truncate or
rotate it. Each economic receipt is canonical JSON, hash-chained and fsynced.
The atomically replaced/fsynced head detects whole-line tail removal or a missing
ledger. It may lag a durable append after a crash, but must point to a verified
prefix. Preserve both files; no local mechanism can detect removal/replacement
of the entire budget directory. The file and lock directory are also synced when
created. Newly created budget-directory components and their parents are synced
before admission; a durability failure sends no request. A stale lock requires
explicit operator removal after confirming the previous process is dead.
The lock retains its device/inode identity until release. A missing/replaced lock
fails cleanup without deleting its replacement. Append opens the ledger with
O_NOFOLLOW and compares fstat device/inode against the retained validated inode;
a changed file is refused before writing or advancing the head.

Before admission, cumulative conservative settlement plus USD 0.17269772 must
fit USD 5. Normal settlement is USD 0.02383748. Retry, evaluator, failed evidence
and unresolved requests settle at USD 0.17269772. Real usage reconciliation is
informational (`RECONCILED`, after close) and cannot lower admission accounting.
An admitted request left pending is settled at R_max on startup and its old
campaign closes FAILED; no request is automatically resumed or replaced.

S1 is the existing Bedrock `provider.retry` message, corroborated by exactly one
`campaign.retry_summary request_id=<UUID> retry_announced=true|false evidence_valid=true`
from `app.core.observability.retry_evidence` after request processing. Missing,
invalid, duplicate or contradictory receipts fail FAILED with R_max; provider
errors without visible retry evidence also fail closed. The receipt covers all
application retry announcements, including stream opening, but excludes SDK retries. S2 is only the correlated
`retrieval_pipeline.evaluator_triggered request_id=<UUID>` message. Call counts
never determine S2. Precedence is FAILED > S1 > S2. Admission stops after the
current request completes and its grace window drains; there is never another
request in flight to cancel. The absolute monotonic request deadline is 300 seconds,
checked around connection/send, every underlying HTTP receive (including headers
and chunk framing), and before accepting JSON/SSE completion. Expiry is unresolved,
settled at R_max and FAILED. localhost selects IPv4 loopback; use ::1 explicitly
for an IPv6-only API.
SSE done is a candidate barrier: validation continues to HTTP body EOF under that
same deadline, without waiting for TCP closure. Extra events, duplicate terminals
and incomplete fragments fail closed and settle R_max. Evaluator failure must
occur once, after activation and before correlated completion.

The existing pipeline completion now exposes
`retrieval_pipeline.completed request_id=<UUID> evaluator_triggered=true|false`.
Exactly one correlated receipt is required: false with no activation allows
continuation; true with activation stops S2. True without activation, false with
activation, or missing/invalid/duplicate completion fails closed. Missing activation
alone never proves non-execution. Both lost messages also fail closed.

The parser consumes the current text formatter, optionally prefixed by Docker
timestamps. Missing/duplicate pipeline completion, malformed windows, wrong or
duplicate activation UUIDs, evaluator failure without activation, source drift
and incomplete capture fail closed. This corroboration detects missing S2 activation;
it does not claim complete delivery of every other log event. Complete/exclusive
source pinning remains an operator precondition.

## Operator-pinned inputs

`manifest.json` has `entries`, ordered by zero-based `seq`. Each entry contains
`block`, `language`, `warmup` and a `/chat` `payload` (`message`, `stream`, optionally
`conversation_id`). The production manifest has 168 entries: EN-C1, EN-E1, ES-C1,
ES-E1 blocks; alternating paths, 20 measured plus one warm-up per path/block.
Each entry may pin `tenant_id` (ASCII letters/digits/underscore/hyphen, 1–64 characters). Omission retains the historical `orq37-t23` tenant; an explicit invalid value is refused before admission. The complete entry, including an explicit tenant, is bound by the manifest hash and request UUID. LocalAPI sends exactly that tenant in `X-Tenant-ID`. Use exact P3 tenants for document/combined cases and independently verified no-document tenants for history-only/empty cases; do not copy or relabel corpus rows.

Fixture preparation and paired case/conversation identities are operator inputs;
the runner neither seeds nor modifies the database outside `/chat`.

`pins.json` contains:

- `manifest_sha256`: SHA-256 of canonical JSON (use `ledger.digest(manifest)`).
- `files`: repository-relative path -> SHA-256 of bytes. Exactly the artifact
  paths in `preflight.ARTIFACTS` and runtime source paths in `preflight.SOURCES`.
  These include the price receipt, per-attempt and campaign bounds, P3 metadata
  and dump, and the logging/generation call graph including the S2 seam.
- `blocks`: ordered block -> `{config, container_id, image_id,
  corpus_fingerprint, exclusive_client: true}`. `config` uses the settings names
  in `preflight.FIXED`, plus empty `fallback_provider`, boolean `otel_enabled`,
  `otel_exporter_otlp_endpoint` and boolean `ebm25_enabled`. Optional sanitized
  history/metrics/Notion/web settings can also be pinned. Credentials are refused
  as configuration fields. `image_id` is the immutable Docker image ID.
- Optional `internal_otel_hosts`: prospectively pinned compose-internal collector
  hosts. Otherwise an enabled exporter must be loopback/localhost.

At every block entry LocalAPI reads sanitized effective settings and deployed
source hashes through local `docker exec`, plus image identity via `docker
inspect`. It compares them to the pinned vector. The corpus fingerprint and
exclusive-client assertion must already have been independently verified during
environment pinning; the runner intentionally cannot query the corpus DB.
Between blocks it pauses for the operator's controlled restart and confirmation,
then moves to the new pinned container's stdout. It never restarts a container.
This boundary recheck is not the G9 rollback drill.

The caller supplies a new campaign UUID only after explicit operator approval.
Closed campaign IDs are refused. Invoke only after execution authorization:

```bash
python -m experiments.production_graduation.campaign_runner.runner \
  --root /path/to/repo --directory /path/to/shared-budget-directory \
  --campaign-id <UUID> --manifest manifest.json --pins pins.json \
  --api http://127.0.0.1:8000 --measurements /path/to/shared-budget-directory/measurements
```

Paid CLI invocation requires `--measurements` and a `pins.client_measurements` object with exactly `schema: orq41-client-timing-v1`, `required: true`, `observer_sha256` (measurements.py bytes) and `transport_sha256` (runner.py bytes). Preflight checks both source hashes; the runner checks recorder campaign/manifest binding before opening/admitting requests. The existing injected driver remains available for deterministic simulations.

Optional LocalAPI observation timestamps the existing parser using monotonic nanoseconds: request origin, headers, first SSE event, first nonempty token frame, done, validated complete body. JSON TTFT is null. It creates one exclusive/no-follow/fsynced UUID receipt plus parent-directory fsync after parsing, before accepting completion; the same absolute deadline is checked again afterward. Missing/contradictory timing or record failure uses existing FAILED/R_max with no resend. No disk writes occur in the token parsing path. Failed HTTP/error receipts have null full_response_ms and a separate failure_observed_ms.

Measurement receipts are observations, not economic settlement or gate verdicts. Always join campaign/request IDs to the durable ledger: an observed successful payload can still settle unresolved if recording exceeds the deadline, cleanup fails or corroboration is invalid. Never infer campaign COMPLETE or TTFT from total latency, and never lower admission charges using measurements. P5 still computes no G6/G7 verdict.

Run with a scrubbed environment, empty HOME and no credential/config files.
No `.env` is loaded. The CLI accepts only a loopback HTTP API; it accesses no
provider endpoint. Provider credentials stay inside the isolated API container.
Its final JSON reports state, conservative settled USD and reasons. No gate
result is computed by P5, including after COMPLETE.
Any operational cleanup fault reports FAILED and a nonzero exit, preserving all
reasons and accounting. recorded_campaign_state reports a closure confirmed by
this run before such a fault; that durable receipt is never rewritten or reopened.
No economic writes are attempted after a durability fault. Startup never resends
recorded requests.

These path checks are local defenses, not protection against an actor modifying
the filesystem concurrently. Preserve a private budget directory, forbid other
writers, and remove stale locks only after confirming the owner is dead. Concurrent
changes between identity checks and unlink/write, deletion of the whole directory
or restoration of older files remain outside the supported operator workflow.

## Credential-free validation

The Runner's transport/pinning/log seams are injectable. `simulation=True` permits
a reduced manifest for local tests only; the CLI has no such switch. Tests use
the real configured formatter, actual Bedrock retry code with an injected fake
client, actual RetrievalPipeline activation with stub ports, and local Unix-socket
HTTP/SSE dry runs. No DB, cloud credentials or provider/network calls are needed.
P2 validation uses an empty network namespace and its existing socket audit guard.

The full 168-request worst-case replay settles 167 normal requests plus one
stopping request: USD 4.15355688, leaving USD 0.84644312 below the hard cap.
Independent review is required before any paid execution.
