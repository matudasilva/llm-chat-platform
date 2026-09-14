"""Request-scoped metrics collector (ORQ-37 §Diseño 6).

`RagGenerationContext` is `frozen=True, slots=True` with one field and cannot
carry metrics, so accumulation happens here instead: a request-scoped
`ContextVar`, the same mechanism `request_id` and `tenant_id` already use.

**This collects; it does not persist.** The `rag_request_metrics` table, the
migration and the two post-transaction write sites are T14's. Until then the
snapshot is read by nothing but tests, which is deliberate -- a collector that
is already correct when the write site arrives is easier to trust than one
written at the same moment as its first consumer.

Two constraints shape the API:

* **Never raises.** Telemetry is best-effort (invariant 4); a collector that
  could throw would put the write path at risk of a metrics bug.
* **Writers must be `async def`.** FastAPI runs a *sync* dependency in a
  threadpool under a **copied** context, where `ContextVar.set()` does not
  propagate back. A sync dependency writing here would appear to work and
  silently lose every field. AC26 asserts this at the dependency definitions.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

_collector_var: ContextVar[Optional["PipelineMetricsCollector"]] = ContextVar(
    "pipeline_metrics_collector", default=None
)


class PipelineMetricsCollector:
    """Accumulates one request's pipeline facts. Content-free by construction."""

    __slots__ = ("_fields", "request_instance_id", "correlation_id")

    def __init__(
        self, *, request_instance_id: str, correlation_id: str | None = None
    ) -> None:
        self.request_instance_id = request_instance_id
        self.correlation_id = correlation_id
        self._fields: dict[str, Any] = {}

    def record(self, **fields: Any) -> None:
        """Merge fields. Last write wins; `None` values are ignored."""
        try:
            for key, value in fields.items():
                if value is not None:
                    self._fields[key] = value
        except Exception:  # pragma: no cover - defensive; must never raise
            pass

    def snapshot(self) -> dict[str, Any]:
        """The accumulated row, identity included. A copy, so a later `record`
        cannot mutate something a caller already took."""
        return {
            "request_instance_id": self.request_instance_id,
            "request_id": self.correlation_id,
            **self._fields,
        }


def init_collector(
    *, request_instance_id: str, correlation_id: str | None = None
) -> tuple["PipelineMetricsCollector", object]:
    collector = PipelineMetricsCollector(
        request_instance_id=request_instance_id, correlation_id=correlation_id
    )
    return collector, _collector_var.set(collector)


def reset_collector(token: object) -> None:
    try:
        _collector_var.reset(token)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover - defensive
        pass


def get_collector() -> Optional["PipelineMetricsCollector"]:
    """The current request's collector, or None outside a request."""
    return _collector_var.get()


def record(**fields: Any) -> None:
    """Record on the current collector if there is one. Never raises.

    A no-op outside a request rather than an error: a caller reached from both
    a request and a script should not need to know which it is in.
    """
    collector = _collector_var.get()
    if collector is not None:
        collector.record(**fields)
