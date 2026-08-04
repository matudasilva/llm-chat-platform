# ORQ-22 reranking benchmark

- Dataset SHA-256: `a5a52e4e6484652edecfa871b048d646da2db2b20c51c6d17157cd23f444bdcb`
- Measurement window: 2026-08-04T16:13:30.857129+00:00 to 2026-08-04T17:52:22.838517+00:00
- Host: Linux 7.0.0-28-generic / x86_64 / Python 3.13.14
- GCP region/location: global
- AWS region: us-west-2
- Candidate recall@30 ceiling: 0.8417
- AWS pacing finding: Preparation finding: 8 rapid Bedrock Rerank calls throttled all tested regions; 4-second spacing with retries still failed; approximately 15-second spacing succeeded.
- Cross-provider latency is indicative only and is not a ranking criterion.
- Relevant means grade >= 1 for MRR@10 and HitRate@5; NDCG@10 uses grades 0/1/2.

## Metric table

| Arm | NDCG@10 | MRR@10 | HitRate@5 | p50 ms | p95 ms | samples | error rate | cost / 1K |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| aws (errors at pacing 15.0s) | 0.5188 | 0.6738 | 0.8500 | 1588.19 | 1816.53 | 180 | 0.0000 | 1.0 (AWS Price List Bulk API, publication 2026-07-23) |
| baseline | 0.4460 | 0.6615 | 0.8167 | 0.00 | 0.00 | 60 | 0.0000 | 0.0 |
| gcp | 0.5320 | 0.6780 | 0.8333 | 939.70 | 2478.55 | 180 | 0.0000 | unverified |

## Language splits

### aws

| Language | NDCG@10 | MRR@10 | HitRate@5 |
|---|---:|---:|---:|
| en | 0.4987 | 0.6618 | 0.8000 |
| es | 0.5388 | 0.6858 | 0.9000 |

### baseline

| Language | NDCG@10 | MRR@10 | HitRate@5 |
|---|---:|---:|---:|
| en | 0.4449 | 0.6551 | 0.7667 |
| es | 0.4472 | 0.6678 | 0.8667 |

### gcp

| Language | NDCG@10 | MRR@10 | HitRate@5 |
|---|---:|---:|---:|
| en | 0.5006 | 0.6570 | 0.8333 |
| es | 0.5634 | 0.6990 | 0.8333 |

## Programmatic paired-bootstrap decisions

| Left | Right | Metric | Difference | 95% CI | Outcome |
|---|---|---|---:|---|---|
| aws | baseline | ndcg_at_10 | 0.0727 | [0.0145, 0.1301] | aws |
| aws | baseline | mrr_at_10 | 0.0124 | [-0.0796, 0.1016] | tie |
| aws | baseline | hit_rate_at_5 | 0.0333 | [-0.0500, 0.1167] | tie |
| aws | gcp | ndcg_at_10 | -0.0132 | [-0.0742, 0.0424] | tie |
| aws | gcp | mrr_at_10 | -0.0041 | [-0.0934, 0.0819] | tie |
| aws | gcp | hit_rate_at_5 | 0.0167 | [-0.0833, 0.1167] | tie |
| baseline | gcp | ndcg_at_10 | -0.0859 | [-0.1468, -0.0282] | gcp |
| baseline | gcp | mrr_at_10 | -0.0165 | [-0.0968, 0.0660] | tie |
| baseline | gcp | hit_rate_at_5 | -0.0167 | [-0.1167, 0.0833] | tie |

## Recommendation

AWS and GCP tie on every pre-registered quality metric. Retain the ADR-006 incumbent AWS backend for the production follow-up; this benchmark provides no quality evidence for a provider switch.

## Backend stability (second live run, first 20 rows)

| Arm | Queries | Mean Kendall tau | Top-1 changes |
|---|---:|---:|---:|
| aws | 20 | 1.0000 | 0 |
| gcp | 20 | 1.0000 | 0 |

## Omissions and limits

- qwen: Live arm deferred: the host NVIDIA driver was unavailable; the operator approved baseline + GCP + AWS as sufficient for the production decision.
- A tie is a valid result whenever the paired bootstrap CI contains zero.
- The table supports only the metric-specific outcomes shown above; it does not support a latency-based provider ranking or a shared relevance-score threshold.
