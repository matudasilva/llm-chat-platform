# Minimal campaign tenant amendment — operator approval required

## Concrete incompatibility

Approved paid composition: 5 documental, 5 history-only, 5 combined and 5 empty-evidence identities per language, paired across C1/E1 and JSON/SSE, each with a fresh conversation. LocalAPI.send hardcodes X-Tenant-ID=orq37-t23 (campaign_runner/runner.py). P3 pins 2146 tenant-visible chunks for that tenant. PgVectorStore hybrid search has an unconditional semantic top-k leg; unrelated text does not establish empty retrieval. Thus fixed P3 tenant cannot represent history-only or empty-document fixtures without altering runtime behavior or data. Neither is authorized. Gate-validation synthetic fixtures cannot substitute for paid campaign cases.

## Smallest proposed change

Allow a non-secret tenant_id in each approved campaign manifest entry; strictly validate it in preflight and include it in the canonical manifest hash and request identity. LocalAPI uses only that pinned tenant in X-Tenant-ID. Positive-document/combined cases retain the exact P3 tenant and fingerprint; history-only/empty cases use predeclared no-document tenants, with paired fresh conversations and separately verified history. No source copying, new embeddings, runtime semantics, thresholds, models, concurrency, accounting or provider behavior change. Existing corpus remains unchanged. Extend focused parser/preflight/HTTP tests and request independent review before use; preserve P5 prior closure as historical, record amendment explicitly rather than silently edit it.

## Current safe preparation

request-slots.draft.json records 168 approved slots, but is not a runner manifest. No fabricated payload, conversation, tenant or pins claim is made. shared-budget is durably prepared; no economic ledger/request has been opened or admitted. Credential presence was checked locally without exposing values or making auth/network calls; presence is not validity.

Live target still needs exact image/config/source pins and a restricted provider-capable network topology. Existing network-none validation target and stubs remain unchanged. Credentials must be provided only to the API, never the runner. Any changed deployment identity must be checked against accepted source/config before admission.

Approval requested: the manifest/preflight/LocalAPI tenant amendment and focused independent validation only. Paid campaign authorization is already recorded; it does not waive this incompatibility or authorize silently changing P5.

## Operator authorization

Operator explicitly approved this amendment in conversation ("aprobado"). Scope is manifest/preflight/LocalAPI tenant handling, focused regression and independent review; no runtime change. Implementation keeps omission compatible with the historical P3 tenant, and strictly refuses any explicit invalid value.
