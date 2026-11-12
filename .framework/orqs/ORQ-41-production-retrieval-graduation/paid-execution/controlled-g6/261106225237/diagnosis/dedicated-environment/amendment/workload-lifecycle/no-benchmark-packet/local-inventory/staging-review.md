# Local inventory and staging review — 2026-11-12

Status: INVENTORY_COMPLETE_WITH_BLOCKERS; staging is not executable or authorized.
The user authorized read-only inventory and packet preparation only. No tests
were rerun; reuse the 26-PASS revalidation and bounded independent source review.

## Observed inputs

`inventory.json` records commands, host identity and allowlisted container fields.
`image-inspect.json` records the successful corrected image metadata query.
The first sandbox attempt could not access Docker/systemd; its zero rows were
not evidence of an empty host. The authorized unsandboxed retry observed 955
retained containers, four running, systemd cgroup driver/v2, Docker 29.1.3, and
46,929,838,080 free bytes on the filesystem containing `/var/lib` (not a Docker
quota or guaranteed allocation). Operator UID/GID is 1000:1000. Boot identity
is retained, but the inventory process is not a future controller identity.

All four proposed images are present by full immutable local ID. The worker
uses the lexical-image amendment identity 775d9250…; both synthetic plan image
arms must point to this same full ID for the existing HostBackend invariant.
This selection reuses the retained amendment as provenance, not as live approval.
No application/image source equivalence or runtime readiness was revalidated.
The complete IDs and metadata are in `staging-packet.json`.

Running baseline containers: orq41-paid-pg, orq41-env-pg, orq41-env-redis,
and orq41-env-otel. Their identities/resources are retained; none was changed.
Shared slices allow CPUs 0-31; orq41bench.slice is loaded but inactive. No loaded
orq41 unit was returned by list-units; this does not establish absence of all
installed unit files or root-owned run directories. CPU 0/2/4/6 report powersave,
EPP performance, 800000–5600000 bounds, no_turbo=0; these are an observation,
not an exclusive reservation. Root state ancestry is not traversable by UID1000.

The initial broad Docker console query exposed historical local credential-bearing
arguments. Those values are omitted from all retained artifacts. Subsequent
queries use explicit allowlists; no environment arrays, command lines, labels,
or credential files are retained. This disclosure does not claim the initial
console output was sanitized or removed.

## Blocking findings

1. Root state parent /var/lib/orq41-cpuset is 0700 root:root; controller UID/GID 1000 cannot traverse to receipts. No parent permission change authorized; per-run mode 0711 alone does not solve this.
2. Full root-state collision inventory inaccessible to UID 1000; no run ID or private path reserved.
3. Actual image interpreter/PID1/bootstrap execution untested; the optional exact isolated probe requires new approval.
4. Exact sealed installer and persistent controller launcher remain absent; no reviewed command packet exists for those host actions.
5. System slices currently allow CPUs 0-31; four existing containers are running. Exclusive reservation/restoration and its shared impact require separately bound execution permission.
6. Future run/container/volume/controller identities, credential file, final plan/manifest/deployment hash and execution authorization do not yet exist.
7. Docker CLI --entrypoint plus positional -I/-B cannot encode the required three-element Entrypoint. A structured local Docker API create request is now drafted with exact Entrypoint/Cmd; transport/version/error handling, mount timing and resulting inspect projection remain unreviewed/unexecuted.
8. Public socket directory must be created by the reviewed helper with exist_ok=False; staging must not precreate it to satisfy a mount. Bind mount validation timing and stopped-worker creation order remain to be demonstrated or resolved without source changes.

## Concrete next optional image probe — separate approval required

The JSON packet contains exact create, start/attach and narrow inspect argv.
The proposed name was absent in the captured inventory; it is not a future
container ID or a reservation. Recheck name absence and all pinned file/image
hashes immediately before any approved action. Create only once, record its real
ID, start only that exact new container, inspect its exit, and retain it stopped.
No deletion, retry, extra mounts, host PID/network namespace, credentials, ports,
app import, package install, pull or provider call is permitted. Image metadata
has no declared volumes, so this probe does not request a data volume. Limits:
64 MiB, 0.5 CPU, 32 PIDs, system.slice, user1000, read-only rootfs, all capabilities
dropped and no-new-privileges. It mounts only the pinned bootstrap and core files
read-only. Its inline command requires actual PID1 and loads the pinned core.

Expected result: process exit0 and PID1_PINNED_CORE_OK with the known offline
digest. A missing interpreter, bootstrap failure, timeout or nonzero exit is a
failed probe, not permission to alter the image or retry. The start/attach call
must have a bounded observation window (30s); timeout leaves a possibly running
container for explicit reconciliation, not automatic kill/removal. Probe success
would not validate the socket, services, installer, lifecycle or G6.

```sh
docker create --pull=never --name orq41-synthetic-bootstrap-probe-261112125713 --network=none --restart=no --read-only --cap-drop=ALL --security-opt=no-new-privileges --user=1000:1000 --cgroup-parent=system.slice --cpus=0.5 --memory=67108864 --memory-swap=67108864 --pids-limit=32 --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/dedicated-environment/amendment/workload-lifecycle/no-benchmark-packet/synthetic_bootstrap.py,dst=/orq41-synthetic/synthetic_bootstrap.py,readonly --mount type=bind,src=/home/matias/Cursor/llm-chat-platform/experiments/production_graduation/gate_validation/dedicated_lifecycle.py,dst=/orq41-synthetic/core.py,readonly --entrypoint=/usr/local/bin/python3 sha256:775d925078229f173fc48a4b95d5ca1620cb518b46433ead60cec3440029b852 -I -B -c 'import os,runpy; assert os.getpid()==1; core=runpy.run_path('"'"'/orq41-synthetic/synthetic_bootstrap.py'"'"')['"'"'load_lifecycle'"'"'](); print('"'"'PID1_PINNED_CORE_OK'"'"',core.digest({'"'"'case'"'"':'"'"'offline'"'"'}))'
docker start --attach orq41-synthetic-bootstrap-probe-261112125713
docker inspect --format '{"Id":{{json .Id}},"Image":{{json .Image}},"Status":{{json .State.Status}},"ExitCode":{{json .State.ExitCode}}}' orq41-synthetic-bootstrap-probe-261112125713
```

## Full staging actions — blocked drafts, not runnable commands

The JSON packet fixes image IDs, a structured local Docker API request for the
worker (including the exact three-element Entrypoint and separate Cmd),
HostBackend resource arguments, names/mount
shapes and intended service commands. Angle-bracket tokens are intentionally
unbound inputs, not invented identifiers. Do not substitute them or run these
commands before the blocking findings are resolved and the resulting packet
is independently reviewed and explicitly approved.

Required order: approve and freeze a fresh run namespace; prepare new private
PostgreSQL credentials and named disposable volumes with exclusive collision
checks; create stopped PostgreSQL and capture its full ID; create stopped Redis
and collector sharing that exact namespace; create the stopped worker with an
admissible exact entrypoint; bind real controller/boot/worker identities; render
and seal the plan/manifest/sources/journal; verify every owner/mode/hash/mount;
then stop for deployment-hash-bound execution approval. No service starts belong
to this staging scope. Fresh DB initialization should remain minimal for the
synthetic lifecycle; no benchmark fixtures or historical credentials are copied.
PGDATA must be `/var/lib/postgresql/data`; exact private env/storage creation and
collector configuration ownership must enter the eventual reviewed installer.

No root chmod, ACL, install, systemd or recovery commands are offered as approved:
these depend on the unresolved parent traversal and installer design. Changing
the existing root parent requires explicit shared-impact review and permission.
Do not make the controller root simply to hide the traversal issue. Do not build
a new image, modify the reviewed author_manifest contract, or bypass the blocked
provisioner. The drafted local API request resolves the metadata shape on paper;
it still requires review and observed inspect evidence after approved staging. Resolving these issues is a separate
bounded preparation increment before full staging can be approved safely.

## Stop and decision

No containers/volumes/services were created, started, stopped or deleted. No
host configuration, code, app/P5, reviewed lifecycle, benchmark/campaign, network
provider, Notion or commit action occurred. No staging or runtime PASS is claimed.
**G6 remains FAIL; paid execution remains BLOCKED.**

Recommended next authorization: offline preparation/review of the exact worker
creation and sealed-installer/controller-access solution. The optional isolated
image probe may be approved separately; neither approval authorizes full staging
or lifecycle execution. All residual resources must be preserved on failure.
