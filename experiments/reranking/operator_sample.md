# ORQ-22 operator label sample

Dataset SHA-256:
`a5a52e4e6484652edecfa871b048d646da2db2b20c51c6d17157cd23f444bdcb`.

Sampling rule: every fifth dataset row starting at row 1. This selects 12/60 rows (20%) before any
benchmark arm runs. Candidate rankings and reranker outputs are intentionally omitted from this
sheet so approval evaluates the independent ground truth only.

| Query | Language | Frozen query | Grade 2 source | Grade 1 supporting source |
|---|---|---|---|---|
| q001 | en | What are the non-negotiable request-path and persistence invariants of the LLM chat platform? | `docs/lld_llm_chat_platform_live_doc.md` | — |
| q006 | es | ¿Por qué el proyecto priorizó capacidades antes que construir el orquestador de ejecución? | `docs/adr/001-capabilities-first-over-execution-orchestrator.md` | — |
| q011 | en | Where is tenant scoping enforced for conversation read endpoints? | `docs/adr/004-tenant-scoping-read-endpoints.md` | `app/services/conversation_query_service.py` |
| q016 | es | ¿Qué modelo de embeddings, dimensión vectorial, estrategia RLS y diseño híbrido se eligieron para RAG? | `docs/adr/006-rag-corpus-embeddings-and-rls.md` | `app/core/providers/pgvector_store.py` |
| q021 | en | What validation and allowlisting rules protect Notion write operations? | `docs/notion_write_safety_contract.md` | `app/core/notion_write_validator.py` |
| q026 | es | ¿Cómo distingue la plataforma errores de timeout, autenticación, rate limit, bad request y upstream? | `docs/error_decision_table.md` | `app/core/domain/provider_errors.py` |
| q031 | en | What provider-neutral request, response, usage, and streaming types define the provider contract? | `app/core/domain/provider.py` | `app/core/domain/types.py` |
| q036 | es | ¿Cómo maneja el adaptador Bedrock la invocación del modelo, eventos de streaming y política de retry? | `app/core/providers/bedrock_provider.py` | `app/core/utils/retry.py` |
| q041 | en | How does the ASGI tenant middleware choose a tenant and propagate it with ContextVar? | `app/http/middleware/tenant.py` | `docs/adr/003-multitenancy-transversal-foundation.md` |
| q046 | es | ¿Cómo fusiona PgVectorStore la búsqueda semántica y por palabras mediante reciprocal rank fusion? | `app/core/providers/pgvector_store.py` | `app/core/domain/vector_store.py` |
| q051 | en | How are conversation list and detail queries tenant-scoped and ordered? | `app/services/conversation_query_service.py` | `app/api/routes/conversations.py` |
| q056 | es | ¿Cómo construye el cliente de escritura Notion requests autenticados de actualización y creación? | `app/services/notion_write_client.py` | `app/services/notion_write.py` |

## Gate status

- Status: pending operator approval
- Approved by: pending
- Approved at: pending
- Approval applies to the frozen hash above; any dataset change invalidates this sign-off.
