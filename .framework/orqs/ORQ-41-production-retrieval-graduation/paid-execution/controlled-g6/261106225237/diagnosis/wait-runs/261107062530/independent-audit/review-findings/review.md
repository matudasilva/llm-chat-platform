# Initial wait/GC evidence finding

MEDIUM WAITS-R1: the original validate_intervals permits a completed GC identity
to recur without checking its prior start/stop timestamps. A complete cycle
(start11, stop12) duplicated exactly is accepted twice; a later tape entry with
the same identity (start9, stop10) is also accepted. Two valid SDK groups and one
valid SQL group make validate_request_intervals accept either malformed trace.
This contradicts the prospective duplicate/out-of-order evidence rejection rule.

The two deterministic probes run under bounded P2 and pass their assertions
demonstrating the initial defect. Original source SHA256 is
`29aa26fa2f31c2d2c5329ba2eddb2df6c966428ab65812a2199901c3993f34b1`,
independently matched against the preserved initial plan. No API or thread work
was executed. The required minimum fix is GC-per-identity completed-cycle timing
validation while allowing legitimate later collections at the same thread/gen.

Chronology: the first retained source-copy attempt raced with the author's fix
and captured already-remediated source. Two inverse counterexample assertions
then failed because the new validator rejected the traces. Those source/metadata/
XML artifacts remain named during-remediation. The authentic original source
was subsequently obtained from initial-review/wait_observer.py, checked against
the initial frozen hash, and the two original counterexamples replayed against
that preserved source. No original failure or source was rewritten.

The author fixed the issue before any request, preserved the original packet,
and re-froze source/protocol/plan. Final review is recorded separately; this
finding is resolved only for the final reviewed plan, not erased from history.
