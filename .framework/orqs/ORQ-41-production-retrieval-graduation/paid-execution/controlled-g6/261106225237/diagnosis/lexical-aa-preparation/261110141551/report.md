# Prospective lexical-image A/A preparation result

**LEXICAL_AA_IMAGE_AMENDMENT_READY_FOR_APPROVAL**.
The preview workload/identity manifest is generated and locally validated; it
is **not executable** with the current approved harness.

| Item | Result |
|---|---|
| Both proposed image IDs | `sha256:775d925078229f173fc48a4b95d5ca1620cb518b46433ead60cec3440029b852` |
| Parent reference reconstructed by current harness | PASS, unprepared mode |
| New image accepted by current harness | Rejected: `Frozen plan drift: images` |
| Candidate delta versus fresh valid reference | Only both image values |
| Preview slots per arm | 720:400measured +320warmup |
| Future total local requests | 1,440:800measured +640warmup |
| Paired workers / concurrency / attempts / repetitions | 32 / 1 / 1 / 1 |
| Fresh preview request+conversation UUIDs | 1,440, paired across isolated arms |
| Historical plans checked / UUID overlap | 14 / 0 |
| Expected history projection per arm | 720conversations /17,280messages |
| Actual preparation/config/seed/readiness evidence | PENDING; no environment provisioned |
| Protected host source/config files unchanged | 505 |
| Docker/database/API/provider/external calls | 0 |
| Actual benchmark measurements / external spend | 0 / USD0 |

`prepare_candidate.py` uses the existing pure plan/sample constructors and
validator without monkeypatching. It checks exact block/warmup balance, business
case multiplicities, fixtures/history counts, UUID freshness, unchanged sources,
and the image guard's deliberate rejection. `validation-command.json` records
the exact P2 invocation. This is parent validation, not an independent review or
new pytest/performance run. P2 network audit is empty/absent.

Files generated: parent-reference/candidate plans, candidate fixtures,
image-identity amendment proposal, historical identity catalog,
environment-requirements checklist and validation/reproduction receipts. No
runtime/harness/test/P5/default pin/historical contract or artifact changed.
Only new preparation evidence and minimal planning/handoff references are added.

The concrete approval request and smallest two-file implementation surface are
in `proposal.md`. Do not call existing prepare/execute with the preview: the
base-contract pin remains authoritative until the amendment is approved and
strict harness support is implemented/reviewed. No new execution approval,
readiness PASS, service allocation or gate result is claimed.

Official G6 remains FAIL and paid admission remains blocked. Global ORQ-41
remains `In Progress / Implement / DECISION_FREEZE_PASS`.
