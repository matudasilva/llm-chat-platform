# ORQ-27 Gate 1 — offline conversational-memory experiment

This directory implements only the offline Gate 1 experiment approved on 2026-08-12. It does not
modify the production `/chat` path, schema, dependency injection, cache, providers, tenant
middleware, JSON/SSE lifecycle, or documentary RAG.

The central comparison is teacher-forced fixed-prefix replay:

- **A:** current user message;
- **B:** bounded history replay;
- **C:** recent-message window;
- **D1:** recent window plus exact episodic retrieval queried by the current user message; and
- **D2-JSON:** the same memory strategy queried by canonical JSON containing bounded recent context
  plus the current user message; and
- **D2-TEXT:** the same memory strategy queried by deterministic labelled text containing the same
  bounded recent context plus the current user message.

Candidate generations are scored but never appended to later prefixes or indexed. The dataset
advances with the same versioned reference transcript for every arm.

## Current checkpoint

Gate 1 completed with a valid `NO_GO` held-out verdict on 2026-08-12. The approved run used D1,
three repetitions per step, and the conversation as the bootstrap unit. It completed on its first
attempt with 433/433 API calls successful, complete generation usage, and zero tenant/conversation
isolation failures. The attempt ledger is terminal and prevents another run under this registration.

The development pilot selected this candidate:

```json
{"chunk_max_chars":1000,"chunk_overlap_chars":0,"recent_window_max_messages":2,"retrieval_top_k_chunks":6,"similarity_threshold":0.2}
```

The development rule proposes D1 as the primary query. D2-TEXT improved retrieval and ambiguous
recall but did not surpass D1's overall recall, consistency, or cost. The selected candidate is:

```json
{"chunk_max_chars":1000,"chunk_overlap_chars":80,"recent_window_max_messages":2,"retrieval_top_k_chunks":6,"similarity_threshold":0.5}
```

The held-out D1 arm improved recall over C by 0.3472 and reduced logical API cost versus B by 37.12%,
but failed four conjunctive clauses: recall and consistency loss versus B, ambiguous-follow-up
recall, and p95 TTFT regression. Gate 1 is therefore `NO_GO`; Gate 2 and Gate 3 remain unauthorized.

## Files

| Path | Purpose |
|---|---|
| `data/*.jsonl` | Versioned synthetic development and held-out transcript fixtures. |
| `data/dataset_manifest.json` | Split hashes and counts. |
| `registration.json` | Signed, frozen held-out decision contract and attempt policy. |
| `dataset.py` / `build_dataset.py` | Strict schema validation and deterministic dataset build. |
| `memory.py` | Chunking, query building, exact cosine retrieval, and fair context composition. |
| `metrics.py` / `costs.py` | Message-level retrieval, answer, latency, and API-cost metrics. |
| `providers.py` | Experiment-only `ProviderPort` adapter for multi-message OpenAI replay. |
| `execution.py` | Content-free append-only potentially billable-call ledger. |
| `run_experiment.py` | Guarded calibration and held-out runner. |
| `analyze_development.py` | Reproducible pilot analysis and threshold proposal. |
| `analyze_heldout.py` | Reconciles the frozen run, registration, attempt ledger, and API ledger. |
| `runs/*.json` | Append-only raw development and held-out evidence. |
| `development-analysis.json` | Machine-readable calibration analysis. |
| `development-report.md` | Human-readable calibration report. |
| `heldout-analysis.json` | Machine-readable Gate 1 decision evidence. |
| `heldout-report.md` | Human-readable Gate 1 held-out report. |

## Reproduction

Rebuild and validate the synthetic dataset:

```bash
python3 -m experiments.conversational_memory.build_dataset
pytest -q tests/experiments/test_conversational_memory_dataset.py \
  tests/experiments/test_conversational_memory_core.py \
  tests/experiments/test_conversational_memory_metrics_and_guards.py
```

Run development calibration. This requires `OPENAI_API_KEY` and makes embedding calls; add
`--with-generation` to execute A/B/C/D1/D2-JSON/D2-TEXT managed-model responses:

```bash
python3 -m experiments.conversational_memory.run_experiment --phase development
python3 -m experiments.conversational_memory.run_experiment \
  --phase development --with-generation
```

Regenerate the development analysis from an explicit append-only run:

```bash
python3 -m experiments.conversational_memory.analyze_development \
  --run experiments/conversational_memory/runs/<development-run>.json
```

The historical held-out command was:

```bash
python3 -m experiments.conversational_memory.run_experiment \
  --phase heldout --with-generation
```

It must not be run again. The terminal attempt ledger now makes the runner reject it.

Regenerate and reconcile the held-out report without invoking a provider:

```bash
python3 -m experiments.conversational_memory.analyze_heldout \
  --run experiments/conversational_memory/runs/heldout-2026-08-12T224320.447316+0000-99ab1c40-9ca4-4029-b23e-c50bc012fa37.json
```

The runner requires an explicitly approved, signed registration and every instrument path to be
committed and unmodified before it reads the held-out dataset. The primary recall improvement over C
must meet both its unrounded point threshold and a conversation-clustered one-sided 95% lower bound
greater than zero. Every other registered quality, cost, retrieval, slice, latency, TTFT, echo, and
break-even criterion uses its unrounded point estimate. All design criteria are conjunctive: every
clause must pass for `GO`; any failure is `NO_GO`.

An incomplete run is `INVALID_RUN`, never a design verdict. One complete replacement is allowed only
when the first attempt ends in a pre-registered accidental provider timeout, network/upstream error,
rate limit, or missing required usage. Partial answers are never reused; the replacement receives a
new run ID and reruns the full split. Auth/config/instrument errors, operator interruption, an
unresolved attempt, and a second invalid attempt are not repeatable. A tenant or conversation leak
is an immediate, non-repeatable `NO_GO`. Physical calls from an invalid attempt remain in the
append-only ledger. `GO`, `NO_GO`, and `INVALID_RUN` do not authorize Gate 2 automatically.

## Measurement boundaries

- Embedding usage is the pinned `ceil(UTF-8 bytes / 4)` estimate because `EmbeddingResult` exposes
  no usage metadata. Missing executed usage remains `null`, never zero.
- Generation usage uses actual `ProviderResult` fields when returned.
- Logical D1, D2-JSON, and D2-TEXT costs each pay a complete standalone index and query cost even
  when physical vectors are shared by the experiment.
- API charges, retrieval CPU time, latency, and storage growth remain separate dimensions.
- Token reduction is an operational-efficiency proxy, not a joule or CO2e measurement.
- Semantic memory, cross-conversation memory, documentary reasoning traces, and production runtime
  integration remain outside Gate 1.

## Production-adapter discrepancy

The unchanged production OpenAI Responses serializer encodes every role as an `input_text` content
item. The first development replay containing an assistant-history message returned HTTP 400. The
Responses input-message contract permits string content for assistant history, so Gate 1 uses the
experiment-only serializer in `providers.py`. No production adapter was changed. A Gate 2 OpenAI
history path would require an explicit design review and regression coverage; Gate 1 does not
authorize that change.

Pricing used in the dated registration comes from the official OpenAI model pages for
[`gpt-4o-mini`](https://developers.openai.com/api/docs/models/gpt-4o-mini) and
[`text-embedding-3-small`](https://developers.openai.com/api/docs/models/text-embedding-3-small).
