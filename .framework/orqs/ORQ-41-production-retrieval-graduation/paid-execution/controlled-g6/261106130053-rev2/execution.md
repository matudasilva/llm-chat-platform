# Controlled G6 execution result

**CONTROLLED_G6_FAIL**. All840 local requests completed successfully;800measured+40warmups. No external/provider calls or paid spend. Native serialized payloads and call counts match across paired sources.

| Cell | C0 p95 ms | C1 p95 ms | Increment | Result |
|---|---:|---:|---:|---|
| EN json | 80.236 | 88.975 | +10.89% | FAIL (limit +5%) |
| EN sse | 70.654 | 79.400 | +12.38% | FAIL (limit +5%) |
| ES json | 78.821 | 85.851 | +8.92% | FAIL (limit +5%) |
| ES sse | 74.143 | 81.397 | +9.78% | FAIL (limit +5%) |

Frozen plan, source/config/hash identities and raw per-request receipts are retained. No automatic rerun or best-result selection occurred. This is a controlled relative-preparation gate failure, not a live absolute-latency measurement. Successful functional requests and payload parity do not waive the +5% requirement.

The paid campaign remains blocked. The design freeze and authorization are not execution readiness or graduation. Next: independent result verification, then a separately scoped performance diagnosis/remediation proposal; no app/P5/threshold/model/accounting changes are authorized by this result.

Controller process exit0 indicates the driver completed and wrote a result; the authoritative gate status is CONTROLLED_G6_FAIL. No PASS is inferred from the shell exit code.
