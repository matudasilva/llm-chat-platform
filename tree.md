.
├── AGENTS.md
├── app
│   ├── alembic
│   │   ├── env.py
│   │   ├── README
│   │   ├── script.py.mako
│   │   └── versions
│   │       ├── 3a8de89a9ee7_preserve_chain_noop.py
│   │       ├── 4b29d461d571_add_conversation_and_message.py
│   │       ├── 52491fe56521_merge_heads_3a8de_742cef.py
│   │       ├── 56edddae02d1_add_usage_event.py
│   │       ├── 742cef87b944_create_conversations_and_messages.py
│   │       ├── 8cb367cad8b4_init.py
│   │       ├── 9bc36b28b8eb_describe_change.py
│   │       ├── d4dd07072605_create_usage_events.py
│   │       ├── eee251fdccda_preserve_chain_noop.py
│   │       └── ef64dc6ccefd_create_usage_events.py
│   ├── alembic.ini
│   ├── api
│   │   ├── deps.py
│   │   ├── __init__.py
│   │   ├── ops.py
│   │   ├── router.py
│   │   ├── routes
│   │   │   ├── chat.py
│   │   │   ├── conversations.py
│   │   │   ├── __init__.py
│   │   │   ├── notion_read.py
│   │   │   ├── notion_write.py
│   │   │   ├── ui.py
│   │   │   ├── usage_events.py
│   │   │   └── web_read.py
│   │   └── runtime_ops.py
│   ├── core
│   │   ├── domain
│   │   │   ├── chat_service.py
│   │   │   ├── chat_types.py
│   │   │   ├── disabled_provider.py
│   │   │   ├── errors.py
│   │   │   ├── __init__.py
│   │   │   ├── provider_errors.py
│   │   │   ├── provider_factory.py
│   │   │   ├── provider.py
│   │   │   ├── routing
│   │   │   │   ├── heuristic_routing_policy.py
│   │   │   │   ├── __init__.py
│   │   │   │   ├── routing_policy.py
│   │   │   │   ├── routing_types.py
│   │   │   │   └── static_routing_policy.py
│   │   │   └── types.py
│   │   ├── __init__.py
│   │   ├── notion_write_validator.py
│   │   ├── providers
│   │   │   ├── bedrock_provider.py
│   │   │   ├── __init__.py
│   │   │   ├── openai_provider.py
│   │   │   ├── resilient_provider.py
│   │   │   └── stub_provider.py
│   │   ├── settings.py
│   │   └── utils
│   │       ├── costs.py
│   │       ├── limits.py
│   │       └── retry.py
│   ├── http
│   │   ├── middleware
│   │   │   ├── request_context.py
│   │   │   ├── request_size_limit.py
│   │   │   └── structured_logging.py
│   │   └── request_context.py
│   ├── infra
│   │   ├── db
│   │   │   ├── base.py
│   │   │   ├── __init__.py
│   │   │   └── session.py
│   │   ├── db.py
│   │   ├── redis_client.py
│   │   └── schemas
│   │       ├── conversations.py
│   │       ├── trace.py
│   │       └── usage_events.py
│   ├── main.py
│   ├── models
│   │   ├── conversation.py
│   │   ├── __init__.py
│   │   ├── message.py
│   │   └── usage_event.py
│   ├── pytest.ini
│   ├── reports
│   ├── requirements-dev.txt
│   ├── requirements.lock
│   ├── requirements.txt
│   ├── schemas
│   │   ├── chat.py
│   │   ├── conversations.py
│   │   ├── notion_read.py
│   │   ├── notion_write.py
│   │   └── web_read.py
│   ├── scripts
│   │   ├── export_usage_events.py
│   │   ├── guardrails_scan.py
│   │   ├── run_chat_endpoint_error_smoke.py
│   │   ├── run_chat_endpoint_smoke.py
│   │   ├── run_cost_report.py
│   │   ├── run_stub_chat.py
│   │   └── run_stub_determinism.py
│   ├── services
│   │   ├── chat_response_cache.py
│   │   ├── conversation_query_service.py
│   │   ├── notion_read_client.py
│   │   ├── notion_read.py
│   │   ├── notion_write_client.py
│   │   ├── notion_write.py
│   │   ├── readiness.py
│   │   ├── routing_signals.py
│   │   ├── trace.py
│   │   ├── usage_events.py
│   │   ├── usage_logger.py
│   │   └── web_read.py
│   ├── static
│   │   └── chat.html
│   └── tests
│       └── core
├── CLAUDE.md
├── conftest.py
├── demo_notion_write.ipynb
├── demo_read_capabilities.ipynb
├── docker-compose.dev.yml
├── docker-compose.yml
├── Dockerfile
├── docs
│   ├── adr
│   │   ├── 001-capabilities-first-over-execution-orchestrator.md
│   │   ├── 002-orq17-phase0-closure-resequencing.md
│   │   ├── README.md
│   │   └── template.md
│   ├── error_decision_table.md
│   ├── external_read_capabilities.md
│   ├── lld_apendix.md
│   ├── lld_llm_chat_platform_live_doc.md
│   ├── notion_write_safety_analysis.md
│   ├── notion_write_safety_contract.md
│   ├── private
│   │   ├── ANALISIS_ESTADO_PROYECTO_2026-06-25.md
│   │   ├── ORQ-16-BLOCKER-REPORT.md
│   │   ├── PROJECT_STATE_ANALYSIS_2026-06-25.md
│   │   └── Proyecto_LLM_Chat_Platform_V1.1.pdf
│   ├── rendered
│   │   └── architecture
│   │       ├── module-boundaries-architecture-v1.svg
│   │       ├── provider-abstraction-architecture-v1.svg
│   │       └── streaming-fallback-sequence-v1.svg
│   ├── troubleshooting_external_read.md
│   ├── v1_1_closure.md
│   └── working
│       └── diagrams
│           ├── AGENTS.md
│           ├── architecture
│           │   ├── chat-flow-architecture-v1.mmd
│           │   ├── chat-flow-architecture-v2.mmd
│           │   ├── module-boundaries-architecture-v1.mmd
│           │   ├── provider-abstraction-architecture-v1.mmd
│           │   └── streaming-fallback-sequence-v1.mmd
│           ├── runtime
│           └── sequences
├── external
├── Makefile
├── puppeteer-config.example.json
├── puppeteer-config.json
├── pyproject.toml
├── pytest.ini
├── README.md
├── reports
├── scripts
│   ├── dev_down.py
│   ├── dev_status.py
│   ├── dev_up.py
│   ├── smoke_read_endpoints.py
│   └── trace_request.py
├── tests
│   ├── api
│   │   ├── test_chat_guardrails.py
│   │   ├── test_chat_response_cache.py
│   │   ├── test_chat_streaming.py
│   │   ├── test_chat_telemetry_best_effort.py
│   │   ├── test_conversations_read_endpoints.py
│   │   ├── test_health_readyz.py
│   │   ├── test_notion_read_endpoint.py
│   │   ├── test_notion_write_endpoint.py
│   │   ├── test_request_ids.py
│   │   ├── test_request_size_limit.py
│   │   ├── test_structured_logging.py
│   │   └── test_web_read_endpoint.py
│   ├── conftest.py
│   ├── core
│   │   ├── test_bedrock_provider.py
│   │   ├── test_chat_service_contract.py
│   │   ├── test_chat_service_provider_error.py
│   │   ├── test_chat_service_routing.py
│   │   ├── test_chat_service_timeout.py
│   │   ├── test_costs.py
│   │   ├── test_heuristic_routing_policy.py
│   │   ├── test_limits_helpers.py
│   │   ├── test_notion_read_client.py
│   │   ├── test_notion_read_service.py
│   │   ├── test_notion_write_client.py
│   │   ├── test_notion_write_safety.py
│   │   ├── test_notion_write_service.py
│   │   ├── test_openai_provider_logging.py
│   │   ├── test_openai_provider.py
│   │   ├── test_openai_provider_retry.py
│   │   ├── test_provider_factory.py
│   │   ├── test_provider_factory_routing.py
│   │   ├── test_resilient_provider.py
│   │   ├── test_retry.py
│   │   ├── test_routing_signals.py
│   │   ├── test_settings_provider_config.py
│   │   ├── test_static_routing_policy.py
│   │   ├── test_stub_provider_contract.py
│   │   └── test_web_read_service.py
│   ├── test_cost_report_pipeline.py
│   └── test_guardrails_scan.py
└── tree.md

40 directories, 183 files
