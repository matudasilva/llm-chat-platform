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

The first development/calibration pass is complete. A subsequent senior methodological review
suspended held-out approval before any held-out execution. The revised pre-registration is pending
because the statistical unit must be conversation-clustered, quality/irrelevance margins require
revision, and the development ambiguity slice exposed a scoring-label defect. Held-out remains
fail-closed until the corrected development instrument is rerun, explicitly approved, signed,
committed, and unmodified.

The development pilot selected this candidate:

```json
{"chunk_max_chars":1000,"chunk_overlap_chars":0,"recent_window_max_messages":2,"retrieval_top_k_chunks":6,"similarity_threshold":0.2}
```

D1 remains the first-pass primary-query proposal. The final development iteration compares D1,
D2-JSON, and D2-TEXT under a predeclared lexicographic selection rule; no query strategy is frozen.
Development results remain calibration evidence, not a GO/STOP decision.

## Files

| Path | Purpose |
|---|---|
| `data/*.jsonl` | Versioned synthetic development and held-out transcript fixtures. |
| `data/dataset_manifest.json` | Split hashes and counts. |
| `registration.json` | Revised held-out decision proposal; unsigned while methodology is reviewed. |
| `dataset.py` / `build_dataset.py` | Strict schema validation and deterministic dataset build. |
| `memory.py` | Chunking, query building, exact cosine retrieval, and fair context composition. |
| `metrics.py` / `costs.py` | Message-level retrieval, answer, latency, and API-cost metrics. |
| `providers.py` | Experiment-only `ProviderPort` adapter for multi-message OpenAI replay. |
| `execution.py` | Content-free append-only potentially billable-call ledger. |
| `run_experiment.py` | Guarded calibration and held-out runner. |
| `analyze_development.py` | Reproducible pilot analysis and threshold proposal. |
| `runs/*.json` | Append-only raw development evidence. |
| `development-analysis.json` | Machine-readable calibration analysis. |
| `development-report.md` | Human-readable calibration report. |

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

Held-out remains fail-closed and requires managed generation:

```bash
python3 -m experiments.conversational_memory.run_experiment \
  --phase heldout --with-generation
```

The runner requires an explicitly approved, signed registration and every instrument path to be
committed and unmodified before it reads the held-out dataset. It evaluates all registered numeric
thresholds, the fixed-seed conversation-clustered paired-bootstrap confidence rule, isolation,
complete step/arm/repetition coverage, API-call outcomes, and usage completeness. Every clause must
pass for `GO`; otherwise the result is `STOP`. Neither result authorizes Gate 2 automatically.

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
