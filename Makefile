check-guardrails:
	python -m app.scripts.guardrails_scan

diagram-render-chat-flow:
	mmdc -p puppeteer-config.json -i docs/working/diagrams/architecture/chat-flow-architecture-v1.mmd -o docs/rendered/architecture/chat-flow-architecture-v1.svg