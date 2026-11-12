# Optimized C1 controlled G6 execution

**CONTROLLED_G6_FAIL_INDEPENDENTLY_VERIFIED**. One prospective execution of plan cdc785a3ccfb9538882d66f327e71c978ebc85e910cf2a0fa68e21ca6853fbf7.

840/840 local requests completed successfully: 800 measured and 40 warmups. Paired native serialized payload/call parity passed, with 420 unique candidate accounting contexts. Independent retained-row replay and a separate parent replay reproduce all hashes, identities, integer timing intervals and nearest-rank percentiles. No measured request was retried or replaced.

| Cell | C0 p95 ms | Optimized C1 p95 ms | Increment | Excess above allowed p95 ms | Result |
|---|---:|---:|---:|---:|---|
| EN json | 75.139 | 81.883 | +8.98% | 2.987 | FAIL |
| EN sse | 73.305 | 77.105 | +5.18% | 0.135 | FAIL |
| ES json | 79.390 | 85.783 | +8.05% | 2.424 | FAIL |
| ES sse | 70.150 | 77.309 | +10.21% | 3.652 | FAIL |

The +5% limit, original timing boundary, N=100 per arm/cell, W=5, R=1 and fixed balanced arm order were preserved. The optimized candidate is image sha256:4e68ccdca15b97f7fd573034c74575d88a156d21ca7f4ff2251affc5db55e707. Historical failures remain retained; cross-run values do not establish a causal optimization effect.

P2 isolation: credential-scrubbed host process in unshare -rn; workers share the network-none PostgreSQL namespace without published ports; existing socket guard and local provider transports were active. Audit files are absent/empty. Zero external/provider calls and USD 0 paid spend. No live absolute latency or TTFT result is claimed. The independent reviewer completed and retained receipt.json and review.md before its turn ended with a usage-limit error; their file hashes are verified. Prepared DB/config verification was executed read-only by parent and inspected by reviewer; no post-run DB projection is claimed here.

Validation: 28 author controls and 28 independent controls passed under P2 before admission. Read-only prepared DB verifier passed (420 conversations/9600 messages per arm, exact fixtures/P3/RLS/schema/config). Existing independent verifier.py and parent-replay.py replayed all 840 retained rows under P2 after execution. The parent replay initially reached the exclusive output guard because the independent receipt already existed; it did not overwrite that receipt, and was rerun with a separate output filename.

Source/runtime, P5, model, threshold, accounting and provider/retry behavior were unchanged during execution. Only the preparer image override and its focused tests changed before plan review. No campaign, Notion, commits or deployment. Global In Progress / Implement and DECISION_FREEZE_PASS remain; paid admission stays BLOCKED_CONTROLLED_G6_FAIL. Do not rerun this failed packet or select a faster repetition.

Evidence: result.json; eight c0/c1 worker receipts; independent-review.json; code-review/prepared-databases-verification.json; execution-review/receipt.json and review.md; execution-review/parent-replay-receipt.json.
