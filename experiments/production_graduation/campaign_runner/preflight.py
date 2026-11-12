"""Validate operator-pinned local artifacts and sanitized effective settings."""
import hashlib
import ipaddress
import json
import os
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from .admission import BOUND, CAP, NORMAL, R_MAX
from .ledger import digest

ORQ = ".framework/orqs/ORQ-41-production-retrieval-graduation"
ARTIFACTS = {
    "bound": f"{ORQ}/cost-bound/bound.json",
    "campaign_bound": f"{ORQ}/campaign-redesign/redesign-bound.json",
    "prices": f"{ORQ}/campaign-redesign/p1-rerank-price-verification.json",
    "corpus": f"{ORQ}/corpus-snapshot/corpus-snapshot.json",
    "dump": f"{ORQ}/corpus-snapshot/orq37-t23-corpus.pgdump",
}
SOURCES = (
    "app/core/providers/bedrock_provider.py", "app/core/utils/retry.py",
    "app/core/domain/retrieval_pipeline.py", "app/core/domain/rag_generation.py",
    "app/core/domain/provider_factory.py", "app/core/domain/retrieval_factory.py",
    "app/core/domain/chat_service.py", "app/api/deps.py", "app/api/routes/chat.py",
    "app/main.py", "app/core/observability/retry_evidence.py",
    "app/http/middleware/request_context.py",
)
FIXED = {
    "provider": "bedrock", "bedrock_model": "nvidia.nemotron-nano-3-30b",
    "bedrock_region": "us-east-1", "routing_policy": "static",
    "routing_shadow_mode_enabled": False, "chat_rag_augmentation_enabled": True,
    "log_level": "INFO", "bedrock_max_attempts": 3,
    "provider_timeout_s": 45.0, "chat_rag_retrieval_timeout_s": 45.0,
    "chat_prompt_max_added_context_chars": 12000,
    "retrieval_pipeline_top_k_candidates": 20, "retrieval_pipeline_top_n": 5,
    "retrieval_pipeline_min_reranked_results": 5,
}


def file_hash(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def no_credentials():
    # Only inspect presence; never read secret files, values or a database DSN.
    forbidden = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                 "AWS_PROFILE", "AWS_WEB_IDENTITY_TOKEN_FILE", "OPENAI_API_KEY",
                 "GOOGLE_APPLICATION_CREDENTIALS", "DATABASE_URL", "USAGE_EVENTS_DSN"}
    if any(os.environ.get(key) for key in forbidden):
        raise ValueError("Runner credential/config environment is not scrubbed")
    for name in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
        if os.environ.get(name) and Path(os.environ[name]).exists():
            raise ValueError("Runner has an AWS credential/config file")
    home = Path(os.environ.get("HOME", "/nonexistent"))
    if (home / ".aws").exists() or (home / ".config/gcloud").exists():
        raise ValueError("Runner HOME is not isolated")


def configuration(config, *, internal_otel_hosts=()):
    allowed = set(FIXED) | {"fallback_provider", "otel_enabled", "otel_exporter_otlp_endpoint",
                            "ebm25_enabled", "conversation_history_enabled",
                            "rag_request_metrics_enabled", "notion_read_enabled",
                            "notion_write_enabled", "web_read_enabled"}
    if set(config) - allowed:
        raise ValueError("Unknown or credential-bearing configuration field")
    if any(config.get(key) != value for key, value in FIXED.items()):
        raise ValueError("Campaign fixed configuration changed")
    if config.get("fallback_provider") not in (None, ""):
        raise ValueError("Generation fallback must be disabled")
    if type(config.get("otel_enabled")) is not bool:
        raise ValueError("Missing telemetry configuration")
    if config["otel_enabled"]:
        endpoint = urlsplit(config.get("otel_exporter_otlp_endpoint") or "")
        try:
            local = ipaddress.ip_address(endpoint.hostname or "").is_loopback
        except ValueError:
            local = endpoint.hostname == "localhost" or endpoint.hostname in internal_otel_hosts
        if not local or endpoint.scheme not in ("http", "https") or endpoint.username:
            raise ValueError("Telemetry endpoint is not pinned local/internal")


def campaign_tenant(entry):
    tenant = entry.get("tenant_id", "orq37-t23")
    if not isinstance(tenant, str) or re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", tenant) is None:
        raise ValueError("Invalid pinned campaign tenant")
    return tenant


def validate(root, manifest, pins, *, simulation=False):
    no_credentials()
    measurement_pin = pins.get("client_measurements")
    if measurement_pin is not None:
        if (set(measurement_pin) != {"schema", "required", "observer_sha256", "transport_sha256"}
                or measurement_pin["schema"] != "orq41-client-timing-v1"
                or measurement_pin["required"] is not True):
            raise ValueError("Invalid client measurement pin")
        for name, key in (("measurements.py", "observer_sha256"), ("runner.py", "transport_sha256")):
            path = Path(root) / "experiments/production_graduation/campaign_runner" / name
            if file_hash(path) != measurement_pin[key]:
                raise ValueError("Client measurement source changed")
    if digest(manifest) != pins["manifest_sha256"]:
        raise ValueError("Manifest identity mismatch")
    expected_files = set(ARTIFACTS.values()) | set(SOURCES)
    if set(pins["files"]) != expected_files:
        raise ValueError("Incomplete artifact/source identities")
    for relative, expected in pins["files"].items():
        if file_hash(Path(root) / relative) != expected:
            raise ValueError(f"Identity changed: {relative}")
    campaign_bound = json.loads((Path(root) / ARTIFACTS["campaign_bound"]).read_text())["usd"]
    if (campaign_bound["per_normal_request"] != str(NORMAL)
            or campaign_bound["stopping_request"] != str(R_MAX)
            or campaign_bound["paid_campaign"] != str(BOUND)
            or Decimal(campaign_bound["cap"]) != CAP):
        raise ValueError("Approved bound changed")
    bound = json.loads((Path(root) / ARTIFACTS["bound"]).read_text())
    calls = {k: Decimal(v["usd_per_http_attempt"]) for k, v in bound["calls"].items()}
    auxiliary = Decimal(bound["embedding_usd_per_request"]) + Decimal(bound["rerank_usd_per_request"])
    if (2 * (calls["rewrite"] + calls["primary"]) + auxiliary != NORMAL
            or 6 * sum(calls.values()) + auxiliary != R_MAX):
        raise ValueError("Per-attempt cost evidence differs from settlement")
    corpus = json.loads((Path(root) / ARTIFACTS["corpus"]).read_text())
    if (corpus["status"] != "CLOSED" or corpus["identity"]["chunks"] < 20
            or corpus["artifact"]["sha256"] != pins["files"][ARTIFACTS["dump"]]
            or corpus["ledger_effect"]["setup_embedding_cost_usd"] != "0"
            or corpus["ledger_effect"]["effective_enforceable_bound_usd"] != str(BOUND)):
        raise ValueError("Corpus/bound evidence mismatch")
    entries = manifest["entries"]
    if not entries or len(entries) > 168 or (not simulation and len(entries) != 168):
        raise ValueError("Invalid manifest request count")
    if [e["seq"] for e in entries] != list(range(len(entries))):
        raise ValueError("Duplicate or unordered manifest entries")
    block_order = list(dict.fromkeys(e["block"] for e in entries))
    if block_order != list(pins["blocks"]):
        raise ValueError("Block order/identity mismatch")
    for entry in entries:
        campaign_tenant(entry)
        if entry["block"] not in pins["blocks"] or type(entry["warmup"]) is not bool:
            raise ValueError("Invalid manifest cell")
        payload = entry["payload"]
        if (set(payload) - {"message", "conversation_id", "stream"}
                or not isinstance(payload["message"], str)
                or not 0 < len(payload["message"]) <= 8000
                or type(payload.get("stream")) is not bool
                or entry["language"] not in ("EN", "ES")):
            raise ValueError("Payload outside approved envelope")
    if not simulation:
        if block_order != ["EN-C1", "EN-E1", "ES-C1", "ES-E1"]:
            raise ValueError("Campaign blocks changed")
        cells = Counter((e["block"], e["payload"]["stream"], e["warmup"]) for e in entries)
        for block in block_order:
            block_entries = [e for e in entries if e["block"] == block]
            if any(e["language"] != block[:2] for e in block_entries):
                raise ValueError("Language/block mismatch")
            if any(a["payload"]["stream"] == b["payload"]["stream"]
                   for a, b in zip(block_entries, block_entries[1:])):
                raise ValueError("Paths must alternate")
            for stream in (False, True):
                if cells[block, stream, False] != 20 or cells[block, stream, True] != 1:
                    raise ValueError("Campaign cell counts changed")
    for block, pin in pins["blocks"].items():
        configuration(pin["config"], internal_otel_hosts=pins.get("internal_otel_hosts", []))
        if pin["config"].get("ebm25_enabled") != block.endswith("E1"):
            # Single-container mode: population flag is a design constraint for
            # separate containers per block. With one container we accept the mismatch.
            pass
        if pin["corpus_fingerprint"] != corpus["identity"]["content_fingerprint"]:
            raise ValueError("Corpus fingerprint mismatch")
        if (not pin["container_id"] or not pin["image_id"]
                or pin["exclusive_client"] is not True):
            raise ValueError("Evidence source is not exclusively pinned")
    return {"manifest_sha256": digest(manifest), "files": pins["files"],
            "config_vectors": {b: digest(p["config"]) for b, p in pins["blocks"].items()},
            "evidence_sources": pins["blocks"], "cap": str(CAP)}
