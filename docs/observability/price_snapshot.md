# Frozen price snapshot (ORQ-37, AC31)

**Date:** 2026-09-12 · **Currency:** USD · **Unit:** per 1M tokens

Frozen by operator decision so that AC31's measurement campaign quotes a fixed
set of prices rather than whatever a provider published on the day a run
happened. The authoritative copy is `PRICE_SNAPSHOT` in
`app/core/utils/costs.py`; this document records the same numbers with their
sources. If the two ever disagree, the code is what produced the measurements.

## Generation — used by `estimated_cost_usd`

| Provider | Model | Input | Cached input | Output |
|---|---|---|---|---|
| `openai` | `gpt-4.1-mini` | 0.40 | 0.10 | 1.60 |
| `bedrock` | `nvidia.nemotron-nano-12b-v2` (`us-east-1`) | 0.06 | — | 0.23 |
| `stub` | — | 0 | — | 0 |

## Embeddings — recorded, NOT used

| Provider | Model | Input |
|---|---|---|
| `openai` | `text-embedding-3-small` | 0.02 |

`estimated_cost_usd` is **generation cost only**. Embedding calls happen inside
the retrieval pipeline and never reach the metrics writer, and they do not
differentiate Mode A from Mode B — Mode B's ranking is lexical and the
documental channel is identical in both — so including them would add the same
constant to both sides of Gate B2's comparison. The rate is recorded here for
whoever later measures ingestion cost, which is a different question.

## What the snapshot deliberately does not do

**Cached input is recorded and unused.** `ProviderResult` exposes no
cached-token count, so there is nothing to apply the reduced rate to. Every
observed input token is charged at the full input rate, which cannot understate
cost. Using it would require a new field on the provider contract.

**An unpriced `(provider, model)` pair yields `None`, never `0.0`.** The column
then stays NULL, which states "no price for this pair". A measured `0.0` — the
stub provider's true cost — is a different statement and is persisted as `0.0`.
Collapsing the two is what would let a campaign report zeros as measurements.

**Pricing is keyed by `(provider, model)`, not by provider.** A per-provider
rate applies itself to whichever model happens to be configured; the pair key
is what makes a model change show up as a missing price instead of a confident
wrong number.

## Sources

- OpenAI `gpt-4.1-mini`: official OpenAI API pricing documentation.
- OpenAI `text-embedding-3-small`: official OpenAI API pricing documentation.
- `nvidia.nemotron-nano-12b-v2`: official Amazon Bedrock pricing page, `us-east-1`.
