---
orq: ORQ-25-rag-generation
authored_by: independent native subagent, fresh-context validation gate
executor: codex (GPT-5, fw-implement) — distinct from validator
updated: 2026-08-07
synced: true
---

## Resumen de revisión

- Resultado contra acceptance criteria → §Resultado por acceptance criterion
- Hallazgo que requiere decisión antes de cerrar → ninguno
- Evidencia clave → §Evidencia ejecutada

## Validator independence disclosure

Validation used the repository's native independent-review mechanism because no external reviewer
was configured for the implementation payload. The fresh-context validator did not edit files.
Round 1 returned `BLOCKED` with two findings; after the executor added fixes and regressions,
round 2 returned `APPROVED WITH NON-BLOCKING NOTES`, with no remaining blockers. This is neither
self-review nor reduced-independence review.

## Resultado por acceptance criterion

- AC1: PASS — settings tests prove inert defaults, positive bounds, the required application DB
  guard, and all eight combinations of the three independent flags. The validator also inspected
  the separate chat and retrieval endpoint gates.
- AC2: PASS — instrumented tests prove RAG session rollback and closure on success, exception, and
  timeout before `business_begin` or `provider_stream`.
- AC3: PASS — augmentor tests cover normalized rank/label order and all three budgets; shared
  prompt serialization reaches OpenAI and Bedrock generate/stream payloads, while Stub and both
  ChatService fallback branches preserve metadata.
- AC4: PASS — non-stream JSON and SSE `done` expose the exact citation/document/chunk/rank tuple
  used in provider metadata and never expose chunk content; empty paths expose `[]`.
- AC5: PASS — pipeline exceptions and timeouts return empty metadata and normal JSON/SSE generation
  continues.
- AC6: PASS — `token`/`done`/`error` remains the only SSE contract; partial emission does not
  trigger fallback, and retrieval finishes or degrades before streaming begins.
- AC7: PASS — chat business persistence remains the existing single transaction and RAG uses a
  separate short-lived session before it.
- AC8: PASS — enabled chat RAG performs zero cache reads/writes and records one explicit
  `rag_augmentation` bypass; disabled cache behavior remains covered by the existing suite.
- AC9: PASS — feedback predicates require successful assistant events owned through the tenant's
  Message; tests cover creation, repeat no-op, replacement, hidden `404`, ambiguous `409`, stable
  cardinality/status, and CORS. A real AsyncSession regression proves rollback does not leave an
  expired attribute access on the idempotent response path.
- AC10: PASS — the additive nullable migration and check constraint are reversible without a
  uniqueness assumption. The executor's real-Postgres upgrade/downgrade run passed; the independent
  validator also inspected the migration and environment-gated test, but could not rerun it because
  `RAG_TEST_DATABASE_URL` was absent from that review environment.
- AC11: PASS — log tests scan both `getMessage()` and every LogRecord field for query/chunk text,
  logging failure is non-invasive, and a Bedrock error carrying a RAG sentinel is normalized before
  it crosses ChatService. Raw upstream exception chaining is suppressed.
- AC12: PASS — no diff touches `retrieval_pipeline.py`, the reranker cascade/adapters,
  `experiments/reranking/`, ADR-006, or ADR-007.
- AC13: PASS — focused and full hermetic suites pass with no live provider dependency.
- AC14: PASS — affected README/LLD/appendix sections match delivery; all four changed SVGs parse and
  contain one title and one description. Constitution diagram refresh remains a non-blocking signal.
- AC15: PASS — ADR-008 and the reconciled ADR index ship with implementation, and the feedback route
  remains literally under `/chat` without writing Conversation or Message.

15/15 acceptance criteria independently verified PASS.

## Hallazgos

No blocking findings remain.

Round 1 identified two blockers that were fixed before closure:

1. The same-rating feedback branch rolled back before reading an ORM timestamp that rollback could
   expire. It now captures the timestamp first, with a real async-session regression.
2. Bedrock could preserve a free-form upstream message and raw chained exception capable of echoing
   prompt/RAG content. It now preserves normalized kind/code/status/retryability only and raises
   without the raw cause, with an end-to-end sentinel regression through ChatService.

Non-blocking notes from round 2:

- The eight-way flag test asserts configuration values; the validator separately inspected the
  simple independent route gates instead of issuing all endpoint combinations.
- Error/non-assistant feedback cases share the same exact query predicates and zero-match `404`
  behavior rather than separate named tests.
- Three Python 3.12+ SQLite datetime-adapter deprecation warnings and the pre-existing OpenAI
  async-iterator close warning remain; neither changes runtime assertions.
- CI evidence is unavailable for the uncommitted ORQ branch. Local hybrid checkpoint evidence is
  valid, and the branch is intentionally stopped before commit/merge for operator confirmation.

## Evidencia ejecutada

Independent round 2 reproduced:

```text
$ .venv/bin/pytest -q <focused ORQ-25 validation selection>
61 passed, 1 skipped, 3 warnings

$ .venv/bin/pytest -q
396 passed, 12 skipped, 4 warnings in 3.28s

$ .venv/bin/pytest --collect-only -q
408 tests collected

$ git diff --check
(no output; passed)

$ xmllint --noout <four changed architecture SVGs>
(no output; passed)
```

Executor evidence independently inspected:

```text
$ RAG_TEST_DATABASE_URL=<local development DSN> .venv/bin/pytest -q \
    tests/core/test_usage_event_feedback_migration.py
1 passed, 3 warnings

Post-test database state:
Alembic revision c4e9a1b2d3f4; feedback and feedback_updated_at columns present;
ck_usage_events_feedback present.
```

Framework gates and signals:

```text
$ python3 .framework/local-tools/fw_check_orq_checkpoint.py . \
    --orq ORQ-25-rag-generation
RESULT checkpoint=valid policy=hybrid orq=ORQ-25-rag-generation

$ python3 .framework/local-tools/fw_check_external_refs.py . \
    --orq ORQ-25-rag-generation
RESULTADO hallazgos=0 modo=orq report-only

$ python3 .framework/local-tools/fw_check_artifact_length.py . \
    --orq ORQ-25-rag-generation
CANDIDATO spec.md (330 lines, budget 240)
EXENTO implementation.md (evidence)

$ python3 .framework/local-tools/fw_check_diagram_refresh.py .
context.svg, architecture.svg, structural.svg, deployment.svg, behavior.svg, erd.svg:
refresh_pending=sí (architecture-signature signal)
```

The full independent validator transcript and raw tool outputs remain in this session's review
history under the ORQ-25 validation gate.

## Evidencia manual local adicional (2026-08-07)

Operator-driven local smoke validation completed after `fw-sync`, against the local Docker stack
(`api` on `http://localhost:8001`, `postgres` on `localhost:15432`, tenant `rag-demo`).

Manual execution evidence:

```text
$ .venv/bin/python -m app.scripts.ingest_corpus --tenant-id rag-demo --contextualize
INFO:__main__:ingest.summary
{'documents_seen': 124, 'documents_ingested': 124, 'documents_skipped': 0, 'chunks_ingested': 2146}

$ curl -sS -H 'X-Tenant-ID: rag-demo' -H 'Content-Type: application/json' \
    http://localhost:8001/rag/retrieve \
    -d '{"query":"How does ChatService build provider input?","top_n":5}'
200 OK; returned 5 ranked chunks, including:
- `app/core/domain/provider.py` (`ProviderInput.metadata`)
- `app/core/domain/chat_service.py` (`run()` / `stream_chat()` provider input construction)

$ curl -sS -H 'X-Tenant-ID: rag-demo' -H 'Content-Type: application/json' \
    http://localhost:8001/chat \
    -d '{"message":"Explain how ChatService builds provider input and cite the source files.","stream":false}'
200 OK; JSON response contained `assistant_content`, `assistant_message_id`, and `sources[5]`

$ curl -N -H 'X-Tenant-ID: rag-demo' -H 'Content-Type: application/json' \
    http://localhost:8001/chat \
    -d '{"message":"Explain how ChatService builds provider input and cite the source files.","stream":true}'
SSE emitted `token` events followed by one `done` event containing `sources[5]`

$ curl -sS -X PUT -H 'X-Tenant-ID: rag-demo' -H 'Content-Type: application/json' \
    http://localhost:8001/chat/messages/e5dbb248-ee32-4bba-9414-ff1c1746ff9e/feedback \
    -d '{"rating":"up"}'
200 OK; persisted `rating="up"`

$ curl -sS -X PUT -H 'X-Tenant-ID: rag-demo' -H 'Content-Type: application/json' \
    http://localhost:8001/chat/messages/e5dbb248-ee32-4bba-9414-ff1c1746ff9e/feedback \
    -d '{"rating":"up"}'
200 OK; idempotent retry returned the same `feedback_updated_at`

$ docker compose --env-file .env -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres \
    psql -U llmchat -d llmchat -c \
    "select message_id, provider, model_version, input_tokens, output_tokens, total_tokens, feedback, feedback_updated_at from usage_events order by timestamp desc limit 10;"
Observed Bedrock usage rows for the validated chat calls, including:
- `e5dbb248-ee32-4bba-9414-ff1c1746ff9e` → `1091/323/1414`, `feedback='up'`
- `bad2400a-3097-477b-984f-6b3f8572fdf9` → `1076/210/1286`
- `d9235ac5-740b-47c2-9727-b2e88086e966` → `1065/242/1307`
- `862a5958-20e8-4aad-9934-3938cec8ffc3` → `1039/188/1227`

$ Firefox + ../llm-chat-platform-web with tenant `rag-demo`
Network inspection showed:
- `OPTIONS http://localhost:8001/chat` → `200`
- `POST http://localhost:8001/chat` → `200`
- SSE response body emitted multiple `event: token` frames and a terminal `event: done`
- terminal `done` payload:
  `{"request_id":"44dd1a4d-72e5-4e44-be03-4d9c381e4241","conversation_id":"578b3ccb-a8a9-46d2-b74d-b1237a0f9582","user_message_id":"f20dc4cb-bc58-48b7-aa5a-32f926d1f49a","assistant_message_id":"35ac12a5-33f7-41fd-a6ef-1e06eb12bbb1","status":"success","sources":[{"citation":"S1","document_id":"e801b775-e99d-4b04-b5c9-7e6c900ae542","chunk_id":"7c0c95a4-1530-4943-9742-b2fa80dc322c","rank":1},{"citation":"S2","document_id":"e158593c-10bb-4b0f-964b-2104d60f42e0","chunk_id":"2660373a-5435-4c73-9d8e-692f40b6d353","rank":2},{"citation":"S3","document_id":"b84ff539-d597-4e35-a581-9cc8d053dd39","chunk_id":"33063cb9-2f43-4aa4-b61e-00fc1407e374","rank":3},{"citation":"S4","document_id":"b84ff539-d597-4e35-a581-9cc8d053dd39","chunk_id":"52ba44a2-efee-4674-9593-7c5b06efbc45","rank":4},{"citation":"S5","document_id":"b84ff539-d597-4e35-a581-9cc8d053dd39","chunk_id":"b54873a5-68f2-46dc-985d-f0428414098c","rank":5}]}`
```

Interpretation:

- Retrieval wiring, chat augmentation, structured citations, SSE completion semantics, and
  feedback persistence all passed in a real local environment.
- `usage_events` stored real Bedrock token counts for the validated augmented-chat requests.
- The separate `llm-chat-platform-web` frontend successfully consumed the local backend via CORS,
  streamed the answer over SSE, and exposed the final structured `sources` payload in browser
  network inspection.
- PostgreSQL emitted a collation-version mismatch warning during direct `psql` inspection; this
  was non-blocking and unrelated to ORQ-25 behavior.

## Presupuesto de longitud (señal, no gate)

`spec.md` is a `CANDIDATO` at 330 lines against the 240-line heuristic budget for 15 ACs.
`implementation.md` and this validation evidence are exempt. The excess reflects the approved
design-first contract and review resolutions; it is a form-review candidate for `fw-replan`, not
a closure blocker.

## Refresh de diagramas (señal, no gate)

All six Constitution diagrams are recorded as `refresh_pending: sí` in
`.framework/constitution/diagrams/INDEX.md`. This is report-only; regeneration belongs to a later
`fw-replan`. The four hand-authored repository architecture SVGs affected by ORQ-25 were updated
and validated in this ORQ.

## Learning candidates (for fw-replan)

- Provider adapters must treat upstream free-form exception messages and chained causes as possible
  prompt-content channels. Candidate scope: framework-reusable telemetry guidance; medium confidence.
- Async ORM rollback can expire state even on a read/no-op response path; capture response values
  before rollback and exercise the behavior with a real AsyncSession. Candidate scope:
  framework-reusable persistence testing; medium confidence.

## Governance sync (fw-sync, 2026-08-07)

The operator explicitly invoked `fw-sync`. Targets were resolved exclusively from the configured
canonical names and local-only concrete refs; no destination was rediscovered and no historical
Notion page was used.

Secret sanitization ran before every external write using the framework core patterns for private
keys, provider tokens, authorization/API-key/secret assignments, and long credential-like values.
All three payloads passed. Destination queries then confirmed the exact project/ORQ properties
after creation.

| Target | Provider | Result | Payload digest |
|---|---|---|---|
| ORQ Dashboard | Notion | synced | `sha256:c61f21d79dc8e6e45d8a6ae66b7db70e124a8ff108fd02223605676dc79ddc3f` |
| Framework Learning / Insights — provider-error channel | Notion | synced | `sha256:a457b476c4f0e318b4b4ce1263b8b36961611413df66636a4f50779938d229dc` |
| Framework Learning / Insights — ORM rollback pattern | Notion | synced | `sha256:d04647f1e1f449b6a69f2062dfb5c6d5761852f38340a59a3cc97d9232bc7059` |

The dashboard records local closure, 15/15 AC PASS, two reusable learnings, and the explicit next
step of committing/merging and verifying CI. It does not claim a closure commit or merge. Both
learnings are `Captured` and reusable. Prompt Library and Master Project Document are not declared
`governance_sync.targets` in the V3 project configuration, so `fw-sync` did not write or rediscover
them. No consumer repository was touched.
