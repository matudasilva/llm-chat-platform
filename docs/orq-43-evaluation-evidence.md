# ORQ-43 model comparison evidence

## Scope

On 2026-11-25, an operator-approved isolated comparison ran four synthetic
English and Spanish chat and fixed-context cases against each of Nemotron Nano
3 30B on Bedrock (`us-east-1`) and Gemini 3.5 Flash-Lite on Vertex (`global`).
The cases and rubric are preserved in the local ORQ-43 frozen protocol. The
RAG-style cases supplied fixed passages and did not exercise retrieval.
No model was activated in production as part of this comparison.

The operator accepted the Nemotron lifecycle exception for this comparison
and an estimated reservation instead of a proven provider billing ceiling.
Neither exception satisfies the general lifecycle or hard-cost criteria.
One human reviewer scored all responses blind: each received 10/10 against
the frozen rubric. This four-case sample does not establish general quality or
a production model ranking. A second human review was not recorded.

## Observations

| Model | Input tokens | Output tokens | Mean reported latency | Estimated token cost (USD) |
|---|---:|---:|---:|---:|
| Nemotron Nano 3 30B | 452 | 115 reported | 573.25 ms | 0.00005472 |
| Gemini 3.5 Flash-Lite | 361 | 99 derived | 1,276.5 ms | 0.00035580 |
| Total | 813 | 214 | — | 0.00041052 |

For the text-only Gemini requests without tools, output was derived as reported
total minus reported input. It combines visible and reasoning tokens; the
separate breakdown was unavailable. Costs use the recorded public token rates,
exclude taxes and other charges, and are estimates rather than an invoice.
Bedrock result identity was the configured model, not a provider-reported
version; Vertex reported the requested model. Four observations per model do
not establish a representative latency distribution.

The original attempt stopped after the first Gemini response because output
usage was unknown to the evaluator. Following an isolated correction and
operator authorization, a one-shot continuation executed only the three
previously unsent Gemini cases. Original and continuation ledgers, full
responses and blind mapping are retained privately under the local ORQ record;
they are not included in this document. The evaluator and its focused tests
are separate from the application runtime.

## Spend controls and accepted risk

On 2026-11-25 the operator accepted the risk that provider-side reasoning
tokens for the manual candidates are not bounded before the call. No hard
pre-call spend ceiling is claimed. Observed usage is recorded for every
evaluation call, and the request output cap and message-size limit apply on the
manual `/chat` path.

### Controls recorded on 2026-11-26

| Control | Evidence | Limits |
|---|---|---|
| Bedrock quota, Nemotron Nano 3 30B on-demand, `us-east-1` | Service Quotas CLI output: 100 requests and 100,000,000 tokens per minute, not adjustable | Account quota, not a spend ceiling |
| Bedrock budget | Monthly cost budget of USD 5, Bedrock filter, alerts at 80% and 100%, no automatic action | Covers all Bedrock use in the account; alert delivery untested |
| Vertex quota, `gemini-3.5-flash-lite` | No fixed per-model request quota found; the model uses Standard PayGo with usage tiers | Usage tier not verified; no quota is not unlimited capacity |
| Vertex budget | Monthly alerts-only budget of USD 5 for the project, alerts at 80% and 100%, spend cap disabled | Alert delivery untested |
| Request limits on manual `/chat` | Deterministic tests: oversized body and over-long message with `model_id` are rejected before any session or provider is reached; the catalog output cap reaches the adapter in both stream modes | Hermetic tests only |

### Invoice reconciliation, 2026-11-25

The estimate above covers only the eight evaluation calls. Provider invoices
also include fifteen manual-selection calls made through a local `/chat`
instance and one short streaming probe per candidate. Reconstructing all three
sources explains about 79% of the Nemotron cost and about 88% of the Gemini
cost at the recorded rates. The unexplained remainder is roughly 21 input and
213 output tokens for Nemotron and 12 input and 112 output tokens for Gemini.
Possible causes include unreported reasoning tokens or unrecorded failed calls,
but the available exports carry no token counts or request identifiers, so the
cause is not established. Bedrock also shows spend on a different model, the
application default, which is outside this comparison. Because workloads
differ, the invoice does not support a cost ranking of the candidates. Further
evidence would be provider token metrics for the same day.

Quota and budget entries are operator-reported configuration, not an export in
this repository. Production enablement of either candidate remains a separate
operator decision.
