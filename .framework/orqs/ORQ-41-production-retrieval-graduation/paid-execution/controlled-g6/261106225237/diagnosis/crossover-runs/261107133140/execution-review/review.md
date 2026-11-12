# Independent crossover execution review

**DIAGNOSTIC_CROSSOVER_EXECUTION_INDEPENDENT_REVIEW_PASS**. No new BLOCKER/HIGH/MEDIUM finding in reviewed retained evidence. Diagnostic validity is separate from G6: official CONTROLLED_G6_FAIL and paid-admission block remain unchanged.

## Actual independent verification

Executed only `execution-review/independent_replay.py` using timeout15s/unshare-rn/env-i/P2/netguard. No API, Docker, SQL, network/provider operation or execution repetition by reviewer. The replay independently reconstructs phase/thread/request state and uses a sweep-point union algorithm instead of importing the production interval validator/analyzer. Source/protocol/plan/support/preparation and all16worker output hashes are bound to the approved plan bcd882d10e1bf57b359135dc7b2eb408c55eed8412dbf717aa6f097f016c4f4b.

Verified64 successful rows,32measured/32warmups,32unique canonical C1accounting UUIDs, exact sample/block/case/UUID metadata and sequential wall ordering. Native serialized rewrite/primary dispatch hashes and call purposes match across each paired arm. All1194events independently validated:170GCevents/85cycles,512SDKevents/128groups,512SQLevents/256groups. Phase/thread/context correlation, duplicate/backward protection and complete closure pass. Per-request clipping, component counts, per-kind and cross-kind unions, integer wall/CPU duration agree exactly with all64analysis rows. Warmups excluded from16paired measured deltas.

Every block delta, range/median, arm/order-stratum summary and all eight cell/category contrasts match. Source contrast is exactly arithmetic mean of the two signed C1-minus-C0 block differences. Order contrast is exactly half(C0-first difference minus C1-first difference); the first-arm lookup is specific to cell AND block. Four-cell contrast medians/ranges were independently checked.

| Cell | Combined source wall (ms) | Empty source wall (ms) |
|---|---:|---:|
| EN JSON | -18.3089475 | -11.727525 |
| EN SSE | -36.869137 | -15.421223 |
| ES JSON | -1.166751 | +9.305718 |
| ES SSE | -33.544711 | -17.351899 |

Four-cell median source wall contrasts:combined -25.92682925ms(range -36.869137 to -1.166751);empty -13.574374ms(range -17.351899 to +9.305718). Median order wall contrasts:combined -0.43770525ms,empty +1.8476905ms. Pooled paired wall medians C0-first -19.385754ms/C1-first -16.2750925ms. These differing summaries are not interchangeable.

## Persistence and isolation evidence

Inspected parent-executed read-only finalDB verifier source/receipt and matched source/hash/plan binding. Source checks exact768original history messages and UUIDs, exactly one new user+assistant exchange in each32conversation/arm,832total messages/arm, canonical unique newIDs; normalizes only64new generated message IDs/arm for paired content equality. P3/RLS/schema/settings remain equal. SQL execution belongs to parent, not reviewer. Retained guard audit absent/empty; reviewed memory transports and receipts report0external/providercalls and0paidspend. Empty audit is supporting evidence, not a general host-network attestation.

## Interpretation limits

ABBA/BAAB now includes both orders within each cell, reducing prior fixed order/cell confounding. Only two blocks and one measured semantic case/category/cell remain. Source/order formulas are descriptive contrasts; block/time/host-state effects and interactions can violate additive stable-effect assumptions. Negative contrasts, including all four combined cells, do not prove stable causal runtime gain, negate previous G6FAIL, establish a p95 ceiling or certify paid readiness. One empty cell is positive. SQL intervals include await/driver/pool/rescheduling, GC association is process-global, CPU covers allthreads, and overlapping components cannot be summed or subtracted into causal wait shares. Observer overhead remains.

No automatic rerun, runtime optimization, threshold relaxation or gate/state change is authorized by this review. Only reviewer script/report/receipt were created. Author report.md was inspected after the first independent replay: all eight rounded wall/CPU/order table rows agree with independently verified values. Its distinction between observed non-replication of the prior sign reversal and absence of causal proof is appropriate. A formal protocol amendment is only a proposal requiring separate prospective governance; no new gate or amendment is authorized by this review.
