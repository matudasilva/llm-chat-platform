"""Declared emission schema for tracing (ORQ-37, Gate A).

This module is a **data artifact**, not logic. It is the single source for
two consumers that must not drift apart: AC4's allow-list assertion over
exported spans, and AC5's check that every field the dashboard artifact
references actually exists.

The rule it encodes (§Diseño 3, extending ORQ-23 AC8 from logs to spans):
attributes are **content-free**. No key here may ever carry a query, a chunk,
a message, a prompt or a provider response -- only counts, durations, flags,
identifiers and classified outcomes. Adding a key that can hold user or corpus
text is a schema change that AC4 is designed to fail on.
"""

from __future__ import annotations

# --- Span names -----------------------------------------------------------
# One span per real stage. Five, not three: `_rewrite` and `_evaluate` are
# provider round-trips that would otherwise be invisible and unattributable in
# cost (§Diseño 3).
REQUEST_SPAN = "request"

RAG_SPAN_NAMES: frozenset[str] = frozenset(
    {
        "rag.rewrite",
        "rag.retrieve",
        "rag.rerank",
        "rag.evaluate",
        "rag.generate",
    }
)

# Gate B1 onwards (both modes) and Mode B only, respectively.
MEMORY_SPAN_NAMES: frozenset[str] = frozenset({"memory.assemble", "memory.rank"})

SPAN_NAMES: frozenset[str] = frozenset({REQUEST_SPAN}) | RAG_SPAN_NAMES | MEMORY_SPAN_NAMES

# --- Attribute keys -------------------------------------------------------
# Request identity. `request.instance_id` is the server-generated uuid4 minted
# in RequestContextMiddleware and is ALWAYS present. `request.correlation_id`
# carries the inbound X-Request-ID only when it passed validation -- it is
# client-controlled, so it is correlation metadata and never identity
# (§Diseño 3, AC32). Nothing carries a bare `request_id`.
IDENTITY_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "request.instance_id",
        "request.correlation_id",
    }
)

# Stage-level attributes. Counts, flags, classifications and durations only.
STAGE_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "rag.candidate_count",
        "rag.ranked_count",
        "rag.top_k_candidates",
        "rag.top_n",
        "rag.fallback_used",
        "rag.evaluator_triggered",
        "rag.evaluator_verdict",
        "rag.rewrite_outcome",
        "rag.retrieval_outcome",
        "rag.evaluate_outcome",
        "rag.generation_outcome",
        "memory.mode",
        "memory.outcome",
        "memory.window_turn_count",
        "memory.corpus_turn_count",
        "memory.selected_count",
        "memory.history_truncated",
        "memory.history_row_cap_reached",
        "provider.name",
        "provider.model",
    }
# `stage.duration_ms` is deliberately NOT declared: a span already carries its
# own start and end, so an attribute duplicating it would mean adding timing
# code at every call site for information the exporter already has. Duration is
# read from the span, and AC5's dashboard must reference it that way rather than
# as an emitted field.
)

ALLOWED_ATTRIBUTE_KEYS: frozenset[str] = IDENTITY_ATTRIBUTES | STAGE_ATTRIBUTES


def is_allowed_attribute(key: str) -> bool:
    """Whether ``key`` may be emitted as a span attribute."""
    return key in ALLOWED_ATTRIBUTE_KEYS
