# Restore import/seal failure

Operator attempt failed at sealed() before entering store.lock or changing CPU.
Cause: importing helper.py via importlib generated a root-owned __pycache__
directory; original sealed() correctly refuses non-regular state entries. This
was created by our restore script, not evidence of a provider/runtime change.

Captured seal-failure-journal.tar and metadata inventory. Helper9025, baseline
and all16 core records remain byte-identical to final-journal.tar. Host remains
unverified/partly restricted, original watchdog still cannot handle init.scope
transient override. No new host mutation or workload/provider call this turn.

Correction: -B plus sys.dont_write_bytecode=True before import. Under the original
maintenance locks, verify only the exact known root cache filename, content SHA,
file/directory type/owner/mode and move it to a unique root-owned quarantine
outside the sealed state. Unknown content, symlink or collision is untouched.
fsync both parent entries, allow recovery after interrupted rename, preserve cache
bytes as evidence. Original helper/sealed validation is unchanged and still runs.
No broad rm or exception in the seal guard. Earlier failed script retained as
restore-local.seal-failed.sh. Validation: 11 focused author +11 independent tests PASS; full helper/seal
regression212/212 PASS under P2. restore-review-round3 PASS. Live recovery remains
pending operator execution; no host CPU mutation occurred in this correction.
