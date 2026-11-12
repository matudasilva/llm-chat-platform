# Transient runtime path correction

The new administrative helper freezes each shared unit's runtime property path
from its captured `Transient=yes|no` classification before mutation. Invalid or
changed classification fails closed. The actual transient `init.scope` path is
`/run/systemd/transient/init.scope.d/50-AllowedCPUs.conf`.

The original helper and failed run 261110205521 are retained unchanged. Its
baseline restoration and access revocation remain verified; its drill remains FAIL.

Validation: `sh run-tests.sh` from this directory: 215 author tests passed and
215 independent tests passed under a credential-free, network-isolated sandbox.
See `review.json`, `review.md` and `evidence/`. The operator-local procedure has
separate static review in `operator-procedure-review.json` and `.md`.

## Live validation completed

`sh run-local-drill.sh` is an operator-terminal procedure requiring local sudo.
It pins helper SHA 8064e669e1921475167fb70fb73d3746cb4c034fa02fe207c7ffa749346b2be2,
creates fresh run 261111015223, prepares/applies/reads back/recovers/verifies,
and archives the journal. It grants no persistent sudoers access. Recovery and
verification are attempted even if apply or readback fails. The helper's existing
independent recovery watchdog is preserved. Never replay a failed apply.

The operator executed the command successfully. Independent archive replay and
actual host readback passed; see `operator-execution-261111015223/completion.json`
and `live-review.json`. ADMIN-LIVE-R1 is closed for normal apply/recovery. The
original failed drill remains retained. Watchdog interruption was not injected,
and this result does not establish benchmark environment readiness. No benchmark or provider workload
is included. G6 remains FAIL and paid admission remains blocked. No application,
P5, model, threshold, accounting, schema or global environment change.
