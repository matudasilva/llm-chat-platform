"""The tracing seam (ORQ-37, Gate A, §Diseño 3).

The **only** module under ``app/`` that imports ``opentelemetry`` -- including
the provider/exporter bootstrap, which lives here as ``init_tracing`` rather
than in ``main.py`` so AC1's single-importer claim holds. The import is lazy
(inside ``init_tracing``), so neither the domain layer nor the hermetic test
suite requires the package to be installed.

Two properties are load-bearing, and the second is the one that is easy to miss:

* **The seam swallows its own failures.** A raising tracer or exporter must not
  change a byte of any response (invariants 4 and 9).
* **The seam cannot stall a request.** Invariant 9 is about *latency*, not only
  about errors: an exporter that blocks would extend ``/chat``'s response while
  raising nothing. Export is therefore asynchronous and batched, with a bounded
  queue that **drops** spans rather than blocking, and bounded export, init,
  flush and shutdown. AC2 tests a slow/hung exporter as well as a raising one.

Disabled by default (``otel_enabled=False``), matching every RAG flag: with it
off, ``span()`` is a no-op that allocates nothing beyond the context manager.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from app.core.observability.schema import ALLOWED_ATTRIBUTE_KEYS, is_allowed_attribute

logger = logging.getLogger("app.observability.tracing")

# Module state. `_tracer` being None is the no-op state and is the default.
_tracer: Any | None = None
_provider: Any | None = None
_lock = threading.Lock()

# Attribute keys the seam refused to emit, for AC4's assertion. Bounded so a
# misbehaving caller cannot grow it without limit.
_MAX_REJECTED = 256
_rejected_attribute_keys: list[str] = []


def _call_bounded(func, timeout_s: float, label: str) -> bool:
    """Run ``func`` on a daemon thread and abandon it after ``timeout_s``.

    Returns True only if it completed. A hung exporter therefore costs a
    bounded wait and a dropped result, never an unbounded block -- this is what
    makes "bounded init/flush/shutdown" a property rather than a hope. The
    thread is a daemon, so an abandoned call cannot keep the process alive.
    """
    done = threading.Event()

    def _run() -> None:
        try:
            func()
        except Exception:  # pragma: no cover - defensive, never reaches callers
            logger.debug("tracing.%s_failed", label, exc_info=True)
        finally:
            done.set()

    thread = threading.Thread(target=_run, name=f"tracing-{label}", daemon=True)
    thread.start()
    if not done.wait(timeout_s):
        logger.warning("tracing.%s_timeout", label, extra={"timeout_s": timeout_s})
        return False
    return True


def _record_rejected(key: str) -> None:
    if len(_rejected_attribute_keys) < _MAX_REJECTED:
        _rejected_attribute_keys.append(key)


def rejected_attribute_keys() -> tuple[str, ...]:
    """Keys dropped for not being in the declared schema (AC4 evidence)."""
    return tuple(_rejected_attribute_keys)


def reset_rejected_attribute_keys() -> None:
    _rejected_attribute_keys.clear()


def _filtered(attributes: dict[str, Any]) -> dict[str, Any]:
    """Drop every key absent from the declared schema.

    Dropping rather than raising is deliberate: the seam must never change
    behaviour (invariant 9). Dropping rather than emitting is also deliberate:
    the allow-list is what keeps content out of telemetry, and a key nobody
    declared is exactly the shape an accidental content leak takes.
    """
    kept: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if is_allowed_attribute(key):
            kept[key] = value
        else:
            _record_rejected(key)
    return kept


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Open a span, or do nothing at all.

    Yields the underlying span object when tracing is active and None when it
    is not, so callers can be written once and stay correct in both states.
    Never raises: every failure inside this function is logged at debug and
    swallowed. Exceptions raised by the *body* propagate untouched -- swallowing
    those would change behaviour, which is the opposite of the contract.
    """
    tracer = _tracer
    if tracer is None:
        yield None
        return

    try:
        manager = tracer.start_as_current_span(name)
        current = manager.__enter__()
    except Exception:
        logger.debug("tracing.span_start_failed", exc_info=True)
        yield None
        return

    try:
        for key, value in _filtered(attributes).items():
            try:
                current.set_attribute(key, value)
            except Exception:
                logger.debug("tracing.set_attribute_failed", exc_info=True)
    except Exception:
        logger.debug("tracing.attributes_failed", exc_info=True)

    try:
        yield current
    except BaseException as exc:
        try:
            manager.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            logger.debug("tracing.span_end_failed", exc_info=True)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception:
            logger.debug("tracing.span_end_failed", exc_info=True)


def set_attribute(current: Any, key: str, value: Any) -> None:
    """Set one attribute on an open span, honouring the schema. Never raises."""
    if current is None or value is None:
        return
    if not is_allowed_attribute(key):
        _record_rejected(key)
        return
    try:
        current.set_attribute(key, value)
    except Exception:
        logger.debug("tracing.set_attribute_failed", exc_info=True)


def is_enabled() -> bool:
    """Whether the seam currently emits anything."""
    return _tracer is not None


def configure_for_testing(tracer: Any | None, provider: Any | None = None) -> None:
    """Install a tracer double (AC2/AC3/AC4). Test seam, not a runtime path."""
    global _tracer, _provider
    with _lock:
        _tracer = tracer
        _provider = provider


def init_tracing(app: Any | None = None, *, config: Any | None = None) -> bool:
    """Bootstrap the provider and exporter from settings. Never raises.

    Returns True when tracing became active. Runs in the FastAPI lifespan, and
    lives here rather than in ``main.py`` so that ``opentelemetry`` has exactly
    one importer under ``app/`` (AC1).
    """
    global _tracer, _provider

    if config is None:
        from app.core.settings import settings as config

    if not getattr(config, "otel_enabled", False):
        logger.info("tracing.disabled")
        return False

    try:
        # Lazy, and the only import of the package in the codebase.
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError:
        # A missing package leaves the seam inert rather than breaking start-up:
        # observability is additive and must never be a boot dependency.
        logger.warning("tracing.sdk_unavailable")
        return False

    endpoint = getattr(config, "otel_exporter_otlp_endpoint", None)
    if not endpoint:
        # The export target is pure configuration; no endpoint is committed
        # (tech-stack.md §Constraints, public repository).
        logger.warning("tracing.endpoint_not_configured")
        return False

    provider_holder: dict[str, Any] = {}

    def _build() -> None:
        resource = Resource.create(
            {"service.name": getattr(config, "otel_service_name", "llm-chat-platform")}
        )
        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint),
            max_queue_size=getattr(config, "otel_max_queue_size", 2048),
            max_export_batch_size=getattr(config, "otel_max_export_batch_size", 512),
            schedule_delay_millis=getattr(config, "otel_schedule_delay_ms", 5000),
            export_timeout_millis=getattr(config, "otel_export_timeout_ms", 10000),
        )
        provider.add_span_processor(processor)
        provider_holder["provider"] = provider
        provider_holder["tracer"] = provider.get_tracer("app.observability")

    if not _call_bounded(
        _build, float(getattr(config, "otel_init_timeout_s", 5.0)), "init"
    ):
        return False
    if "tracer" not in provider_holder:
        logger.warning("tracing.init_failed")
        return False

    with _lock:
        _provider = provider_holder["provider"]
        _tracer = provider_holder["tracer"]

    if app is not None:
        try:
            app.state.tracing_enabled = True
        except Exception:
            logger.debug("tracing.app_state_failed", exc_info=True)

    logger.info("tracing.enabled")
    return True


def shutdown_tracing(app: Any | None = None, *, config: Any | None = None) -> None:
    """Flush and shut down, each under its own bound. Never raises."""
    global _tracer, _provider

    if config is None:
        from app.core.settings import settings as config

    provider = _provider
    with _lock:
        _tracer = None
        _provider = None

    if provider is None:
        return

    _call_bounded(
        lambda: provider.force_flush(),
        float(getattr(config, "otel_flush_timeout_s", 5.0)),
        "flush",
    )
    _call_bounded(
        lambda: provider.shutdown(),
        float(getattr(config, "otel_shutdown_timeout_s", 5.0)),
        "shutdown",
    )


__all__ = [
    "ALLOWED_ATTRIBUTE_KEYS",
    "configure_for_testing",
    "init_tracing",
    "is_enabled",
    "rejected_attribute_keys",
    "reset_rejected_attribute_keys",
    "set_attribute",
    "shutdown_tracing",
    "span",
]
