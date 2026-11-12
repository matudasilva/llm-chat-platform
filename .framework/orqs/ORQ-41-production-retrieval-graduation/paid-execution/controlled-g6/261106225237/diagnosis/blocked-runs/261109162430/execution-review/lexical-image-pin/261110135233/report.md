# Reviewed lexical SQL image: local build and pin

2026-11-10. **LEXICAL_SQL_LOCAL_IMAGE_PINNED**.
Operator authorization: `autorizo imagen`. Scope ends with local image/source
identity verification. No A/A, formal G6, API request, campaign or deployment.

## Identity

- Tag: `orq41-local:lexical-sql-261110135233`.
- Immutable local image ID:
  `sha256:775d925078229f173fc48a4b95d5ca1620cb518b46433ead60cec3440029b852`.
- Parent: `sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707`.
- Platform: Linux/amd64. Existing Python and installed distributions retained.
- Approved adapter SHA-256:
  `81a41cba1227be5bceff0b34051b7f976b6a4db65a6853a51616935ff6b8b9b3`.
- Accepted source review receipt SHA-256:
  `982dd27f7730713ccf3a6f4b3e9e90eefd875567e7885dceb0ddfde24bef2f39`.
- Git HEAD: `c75fb707f5a8f236846131f0da8f5a0c23b9d969`.
  The dirty tree is fingerprinted separately; HEAD alone is not source identity.

This is a local content-addressed Docker image ID, not a registry repository
digest. Nothing was pushed; `RepoDigests` is empty. Historical tags, immutable
images and executed manifest pins remain unchanged.

## Build and validation

The retained context has exactly two files: a Dockerfile pinned to the existing
local parent ID and the reviewed adapter. Its only build instruction after
`FROM` is `COPY pgvector_store.py /app/app/core/providers/pgvector_store.py`.
No dependency installer, `RUN`, registry access, credentials or global `.env`
is included. Context bytes, authorization, source inventory and build command
are frozen before the sole build attempt. Logs and one-shot marker are retained.

`DOCKER_BUILDKIT=0` reuses the existing offline build procedure; the Docker CLI
reports a deprecation warning. No builder, dependency or infrastructure upgrade
was made in this scope.

The effective build command is retained in `build-manifest.json`:

```text
docker --host unix:///var/run/docker.sock build --pull=false --network=none -t orq41-local:lexical-sql-261110135233 <retained-context>
```

`validation-command.json` records the exact host P2 invocation. The
`parent-probe-command.json` and `candidate-probe-command.json` files record the
exact network-none, read-only, capability-dropped inventory commands.

Two ephemeral Python probes inspect parent/candidate source inventories,
distribution versions and Python identity, compile/import the real adapter,
and capture its SQL using an in-memory execute stub. They do not start the API,
open a database connection or call a generation/embedding/rerank provider.
Actual compiled SQL matches the previously reviewed original/candidate captures.

Checks passed:

- Exactly one changed application file: `core/providers/pgvector_store.py`.
- Candidate application membership and file hashes equal the current host app.
- Candidate adapter bytes equal the source tested/reviewed before this build.
- Parent rootfs layers are preserved with exactly one added COPY layer.
- Runtime configuration, Python and all installed distribution versions match.
- All 505 protected host source/config hashes remain unchanged during this step.
- P2 credential scrubbing, disabled dotenv/metadata discovery, loopback-only
  namespaces and network audit checks passed. No downloads or external calls.

The 239 real-PG tests and 40-plan/60-adapter proof belong to the preceding
source remediation and are inherited evidence, not newly executed image tests.
They were not repeated: the new image contains precisely the tested adapter
bytes on the same parent/runtime/dependency layers. Image verification here is
parent-executed inventory/import/SQL capture, not another independent review or
performance measurement.

## Disposition

External spend **USD 0**. Database/API/provider/external calls: zero. No existing
service was restarted, no new environment was provisioned, and no benchmark
or paid request was admitted. No app/P5/harness/DB/schema/grant/model/threshold/
accounting/global-env/dependency changes; no G9, Notion, commit, push or deploy.

The new standalone receipt pins an available candidate. It does not rewrite
historical/default harness image pins or make old frozen plans runnable again.
Next work is a prospective local calibration plan with this image and fresh,
reviewed source/config/fixture identities, followed by explicit execution
authorization. No such plan/run is prepared or admitted here.

Keep **AA_CALIBRATION_FAIL**, **CONTROLLED_G6_FAIL** and
**BLOCKED_CONTROLLED_G6_FAIL**. Global ORQ-41 remains
**In Progress / Implement / DECISION_FREEZE_PASS**.
