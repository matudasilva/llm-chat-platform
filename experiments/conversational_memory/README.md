# ORQ-27 Gate 1 — offline conversational-memory experiment

This directory implements only the offline Gate 1 experiment approved on 2026-08-12. It does not
modify the production `/chat` path, schema, dependency injection, cache, providers, tenant
middleware, JSON/SSE lifecycle, or documentary RAG.

The central comparison is teacher-forced fixed-prefix replay:

- **A:** current user message;
- **B:** bounded history replay;
- **C:** recent-message window;
- **D1:** recent window plus exact episodic retrieval queried by the current user message; and
- **D2:** the same memory strategy queried by canonical bounded recent context plus the current
  user message.

Candidate generations are scored but never appended to later prefixes or indexed. The dataset
advances with the same versioned reference transcript for every arm.

## Current checkpoint

Development/calibration is complete. Held-out execution is intentionally blocked until the
operator approves the proposed frozen parameters, primary query variant, repetitions, thresholds,
and paired decision rule in `development-analysis.json`; the updated registration must then be
signed, committed, and clean.

The development pilot selected this candidate:

```json
{"chunk_max_chars":1000,"chunk_overlap_chars":0,"recent_window_max_messages":2,"retrieval_top_k_chunks":6,"similarity_threshold":0.2}
```

D1 is proposed as the primary query variant. Development results are not a GO/STOP decision.

## Files

| Path | Purpose |
|---|---|
| `data/*.jsonl` | Versioned synthetic development and held-out transcript fixtures. |
| `data/dataset_manifest.json` | Split hashes and counts. |
| `registration.json` | Calibration grid and the not-yet-signed held-out decision contract. |
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
`--with-generation` to execute A/B/C/D1/D2 managed-model responses:

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

Held-out remains fail-closed:

```bash
python3 -m experiments.conversational_memory.run_experiment --phase heldout
# RESULT gate1=blocked reason=heldout registration is not approved
```

After operator approval, `registration.json` must freeze the selected candidate/query,
repetitions, all thresholds, and signature. The runner then additionally requires every instrument
path to be committed and unmodified before it reads the held-out dataset.

## Measurement boundaries

- Embedding usage is the pinned `ceil(UTF-8 bytes / 4)` estimate because `EmbeddingResult` exposes
  no usage metadata. Missing executed usage remains `null`, never zero.
- Generation usage uses actual `ProviderResult` fields when returned.
- Logical D1 and D2 costs each pay a complete standalone index and query cost even when physical
  vectors are shared by the experiment.
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
