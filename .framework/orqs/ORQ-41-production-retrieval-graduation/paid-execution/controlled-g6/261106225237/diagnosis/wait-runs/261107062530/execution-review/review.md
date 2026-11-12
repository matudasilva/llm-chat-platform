# Independent execution review — wait/GC diagnostic

Status: **DIAGNOSTIC_WAITS_EXECUTION_INDEPENDENT_REVIEW_PASS**. This is a descriptive diagnostic review, not G6 PASS or permission for another execution. No new BLOCKER/HIGH/MEDIUM finding in the retained evidence reviewed.

## Verification actually performed

The reviewer executed `execution-review/independent_replay.py` once as a pure retained-file replay under `timeout 15s unshare -rn env -i`, with P2 netguard, scrubbed credentials and Python bytecode disabled. No API, Docker, SQL, network or provider operation was performed by the reviewer. The standalone replay uses its own event state machine and sweep-point union algorithm rather than the harness validator/analyzer functions. The script and receipt retain exact hashes.

All eight worker receipt hashes, prospective final plan/source/support bindings, row metadata and UUID derivations match. There are exactly 40 successful rows: 32 measured and eight warmups; five per arm/language/protocol cell, 20 unique candidate accounting instances, no duplicate sample/arm rows and preserved serial ordering. Native rewrite/primary dispatch purposes and serialized payload hashes match paired inputs. Candidate closed-chain validity was checked by the reviewed worker; raw chains are not separately retained, so this review does not claim a second raw chain replay.

The replay reconstructed all 892 raw events: 320 SDK events (80 complete groups), 320 SQL events (160 groups), 92 GC events (46 cycles). Identity, request/context correlation, phase/thread order, repeated-GC ordering, complete closure and coverage passed. Every interval was independently clipped to ASGI ingress/serialized primary dispatch. Per-kind union, cross-kind union, counts and integer CPU/wall differences match all 40 analysis rows exactly. Cross-kind union never exceeds the wall interval. Warmups were excluded from the 16 paired comparisons; all category ranges, medians, arm medians and eight-pair order strata match analysis.json.

## Checked descriptive numbers

| Paired C1 minus C0 median (ms) | Combined (8 pairs) | Empty (8 pairs) |
|---|---:|---:|
| Wall | -7.814806 | -8.529583 |
| Whole-process CPU | -4.2833985 | -6.671464 |
| SQL interval union | -5.8725645 | -4.247753 |
| GC union | +0.085813 | 0 |
| SDK queue union | -0.053883 | -0.0072575 |

C0-first wall median is -10.623564 ms; C1-first is +17.903914 ms. Measured maxima (C0/C1) are GC union 1.346541/0.730394 ms, SDK queue 0.878444/0.845454 ms and SDK return 0.572009/0.399778 ms. Author report.md's rounded numbers and stated limitations are consistent with these retained observations. No reporting correction is required.

## Database and isolation evidence

The reviewer inspected `verify_final_databases.py` and its parent-executed PASS receipt and verified their hashes/bindings. The script uses read-only transactions, checks exact 384 original history rows/IDs, exactly one new user/assistant exchange per conversation, canonical unique generated IDs, and normalizes only those new IDs for paired content equality. The receipt records 20 conversations/424 messages per arm, unchanged P3 fingerprint/RLS/schema/effective configuration. This is parent-executed SQL evidence, not a reviewer database connection. The retained P2 guard audit is absent/empty, worker transports are reviewed local stubs, and retained receipts report zero external calls/paid spend. An empty guard audit alone is not a general network attestation.

## Limits and next decision

Order strata are confounded with language/protocol, fixed process sequence and host time; the sign association establishes no causal order effect. SQL spans include driver/pool/await/rescheduling; SDK handoffs do not cover all scheduling, GC association is process-global, and CPU covers all threads. Observer overhead remains. Overlapping spans cannot be added or interpreted as causal shares, and wall-minus-CPU is not a wait measurement. The small combined/empty diagnostic population is not the official G6 population and cannot certify the +5% criterion or invalidate historical failures.

The proposed prospectively frozen within-cell crossover is a reasonable next design for approval, not an executed experiment or an authorized automatic rerun. No runtime optimization or threshold waiver follows from this review. **Official CONTROLLED_G6_FAIL and the paid-admission block remain unchanged.** No source, planning, runtime, gate result, provider behavior, model, threshold or accounting change was made by this reviewer.
