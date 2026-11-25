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

Dated provider quota or throttle configuration and budget alerts for each
candidate are deferred by operator decision. They remain open evidence for the
spend-control criterion before any production enablement, as does reconciling
the estimates above against the provider invoice.
