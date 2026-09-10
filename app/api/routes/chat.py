import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_chat_memory_context, get_chat_rag_context, get_chat_service
from app.core.domain.added_context_budget import enforce_added_context_cap
from app.core.domain.chat_memory import ChatMemoryContext
from app.core.domain.chat_service import ChatService
from app.core.domain.chat_types import ChatServiceResult
from app.core.domain.errors import ProviderExecutionError, ProviderTimeoutError
from app.core.domain.provider import ProviderResult
from app.core.domain.provider_errors import ProviderError
from app.core.domain.rag_generation import RagGenerationContext
from app.core.domain.types import ChatMessage
from app.core.settings import settings
from app.core.utils.limits import sanitize_error_message, truncate
from app.http.middleware.tenant import get_tenant_id
from app.http.request_context import get_request_id
from app.http import pipeline_metrics
from app.infra.db.session import get_db, get_history_sessionmaker, short_lived_history_session
from app.models.conversation import Conversation
from app.models.message import Message, MessageRole
from app.models.rag_request_metrics import RagRequestMetrics
from app.models.usage_event import UsageEvent
from app.schemas.chat import ChatRequest, ChatResponse, ChatStatus, RagSourceOut
from app.services.chat_response_cache import get_chat_response_cache

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


def _sse(event: str, data: str) -> str:
    # SSE format: event + one "data:" line per line of the payload + blank
    # line. split("\n") (not splitlines()) preserves an embedded blank line
    # and a trailing newline as their own "data:" line, both of which are
    # required for the client to reconstruct the payload exactly.
    data_lines = "\n".join(f"data: {line}" for line in data.split("\n"))
    return f"event: {event}\n{data_lines}\n\n"


def _sse_json(event: str, payload: dict) -> str:
    return _sse(event, json.dumps(payload, separators=(",", ":")))


def _error_provider_name(chat_service: ChatService) -> str:
    provider = getattr(chat_service, "_provider", None)
    for attr in ("provider", "provider_name"):
        value = getattr(provider, attr, None)
        if isinstance(value, str) and value:
            return value
    return settings.provider


def _cache_bypass_reason() -> str | None:
    """Why the response cache must not be consulted, or `None` if it may be.

    ADR-008 §5 bypasses the cache whenever chat RAG augmentation is on,
    because `_cache_key` does not include corpus or retrieved-source
    identity. **ADR-013 §9 extended that to `ebm25_enabled`** for exactly the
    same reason -- Mode B's out-of-window evidence travels in `metadata`,
    which the key does not fingerprint -- but the extension was documented
    and never implemented (H6/AC17). In the configuration
    `conversation_history_enabled=true, ebm25_enabled=true,
    chat_rag_augmentation_enabled=false` the cache stayed live, so an answer
    built on one evidence set could be served to a later request whose
    evidence differs.

    Single-sourced here because the previous code asked the question in three
    places -- two gates plus the streaming log -- and extending one without
    the others is how the read and write halves drift apart.
    """
    if settings.chat_rag_augmentation_enabled:
        return "rag_augmentation"
    if settings.ebm25_enabled:
        return "ebm25_memory"
    return None


async def _record_budget_outcome(outcome: str) -> None:
    """Record the combined-cap enforcement's own `memory_outcome` override.

    `async def` follows the same rule as `deps._record_memory_outcome`: AC26
    forbids sync collector writers outside `pipeline_metrics.py`, bluntly,
    because a copied context silently swallowing every field is invisible at
    runtime. Last-write-wins is intended here -- this runs after the memory
    dependency's own record and deliberately supersedes it, because trimming
    at the route can invalidate what the dependency concluded.
    """
    try:
        pipeline_metrics.record(memory_outcome=outcome)
    except Exception:  # pragma: no cover - defensive; telemetry never raises
        pass


async def _write_rag_request_metrics(
    request: Request,
    *,
    tenant_id: str,
    generation_outcome: str,
    provider_result: ProviderResult | None,
    memory_context: ChatMemoryContext,
    total_latency_ms: int,
) -> None:
    """The single post-transaction write site's logic, shared by both paths (T14).

    Runs on the OPERATIONAL session (`chat_ops`, INSERT-only on this table per
    the split grants of `e4b7f21c9a06`) -- never the primary session, which the
    atomic write already used and released by the time this runs. Never
    raises: telemetry is best-effort (invariant 4) and must not put the
    request at risk of a metrics bug.

    Identity is server-side: `request_instance_id`/`request_id` come from the
    collector's snapshot -- the `RequestContextMiddleware`-minted identity
    (§Diseño 3) -- never from this function's own `request_id` local, which is
    the OLDER, client-influenced fallback the near-collision note in
    `request_context.py` warns about.

    `mode` reflects `settings.ebm25_enabled` at write time (H1/AC18 fix,
    2026-09-08) -- the same, only gate Mode B has anywhere in this codebase
    (`deps.py:255`), read fresh here rather than threaded through
    `memory_context`. It marks the **active configuration** for this
    request, not whether Mode B's ranking actually selected evidence: that
    finer distinction already has its own columns
    (`memory_outcome`/`ebm25_selected_count`), and folding it into `mode`
    too would make them redundant. Originally hardcoded `"A"` because
    `ebm25_enabled` did not exist until T18 shipped it -- a documented
    placeholder that outlived the flag it was waiting for.
    `rewrite_calls`/`retrieve_calls`/`rerank_calls`/
    `evaluate_calls`/`generate_calls`/`fallback_used`/`ebm25_selected_count`
    have no producer yet -- those columns exist per §Diseño 6's full schema
    but stay NULL until a later task wires them, which is not scope creep:
    writing to modules outside `chat.py`/`deps.py` is exactly what T14 does
    not do.
    """
    if not settings.rag_request_metrics_enabled:
        return
    if request is None:
        return
    collector = pipeline_metrics.get_collector()
    if collector is None:
        return
    snapshot = collector.snapshot()
    raw_instance_id = snapshot.get("request_instance_id")
    if not raw_instance_id:
        return
    try:
        request_instance_id = uuid.UUID(str(raw_instance_id))
        raw_request_id = snapshot.get("request_id")
        correlation_request_id = uuid.UUID(str(raw_request_id)) if raw_request_id else None
        sessionmaker = get_history_sessionmaker(request)
        async with short_lived_history_session(sessionmaker) as db:
            async with db.begin():
                db.add(
                    RagRequestMetrics(
                        id=uuid.uuid4(),
                        request_instance_id=request_instance_id,
                        request_id=correlation_request_id,
                        tenant_id=tenant_id,
                        mode="B" if settings.ebm25_enabled else "A",
                        memory_outcome=snapshot.get("memory_outcome"),
                        generation_outcome=generation_outcome,
                        input_tokens=(
                            provider_result.input_tokens if provider_result else None
                        ),
                        output_tokens=(
                            provider_result.output_tokens if provider_result else None
                        ),
                        total_latency_ms=total_latency_ms,
                        history_truncated=memory_context.truncated,
                        history_row_cap_reached=memory_context.history_row_cap_reached,
                    )
                )
    except Exception:
        # Telemetry must never break /chat. A raised exception here is
        # swallowed exactly like the existing UsageEvent writes.
        pass


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    # `Request | None = None`, not a bare required `Request`: FastAPI still
    # injects the real ASGI request via this type annotation regardless of
    # the default, and the default is what lets every existing direct
    # unit-call test -- the same convention `rag_context`/`memory_context`
    # already use for calls that bypass DI -- keep calling `chat(...)`
    # without constructing one. `_write_rag_request_metrics` treats `None`
    # as "skip the write" (T14).
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
    chat_service: ChatService = Depends(get_chat_service),
    rag_context: RagGenerationContext = Depends(get_chat_rag_context),
    memory_context: ChatMemoryContext = Depends(get_chat_memory_context),
) -> ChatResponse:
    start = time.perf_counter()
    rid = get_request_id()
    request_id = uuid.UUID(rid) if rid else uuid.uuid4()
    tenant_id = get_tenant_id()

    status = ChatStatus.error
    error_message: str | None = None
    # T14: set at each terminal point; the write-site finally reads it.
    generation_outcome: str | None = None
    metrics_provider_result: ProviderResult | None = None
    is_new_conversation = payload.conversation_id is None
    conversation_id = payload.conversation_id or uuid.uuid4()
    user_message_id: uuid.UUID | None = None
    assistant_message_id: uuid.UUID | None = None
    assistant_content: str | None = None
    cache = get_chat_response_cache()
    if not isinstance(rag_context, RagGenerationContext):
        # Direct unit calls bypass FastAPI dependency resolution.
        rag_context = RagGenerationContext()
    if not settings.chat_rag_augmentation_enabled:
        # The route remains fail-closed if a dependency override supplies
        # context while the independent rollout flag is disabled.
        rag_context = RagGenerationContext()
    if not isinstance(memory_context, ChatMemoryContext):
        # Direct unit calls bypass FastAPI dependency resolution.
        memory_context = ChatMemoryContext()
    if not settings.conversation_history_enabled:
        # The same fail-closed reset the RAG channel has, for the independent
        # memory flag: an override must not be able to inject memory into the
        # prompt while the rollout flag is off.
        memory_context = ChatMemoryContext()
    # H2/AC14: the ONE point where the combined added-context cap is enforced.
    # It runs here, after both fail-closed resets and before anything reads
    # either context, because this is the only place all three contributors
    # are visible at once -- the memory dependency cannot see the documental
    # channel, and enforcing it from there left the cap breachable twice.
    # Both /chat paths consume the single `provider_metadata` assembled below,
    # so one call covers streaming and non-streaming by construction.
    memory_context, rag_context, budget_outcome = enforce_added_context_cap(
        memory_context=memory_context,
        rag_context=rag_context,
        current_message=payload.message,
        max_chars=settings.chat_prompt_max_added_context_chars,
    )
    if budget_outcome is not None:
        # Recorded here rather than in the domain function: the outcome the
        # memory dependency recorded earlier is stale once this trims what it
        # selected, and leaving a stale telemetry field standing is precisely
        # the defect H1 was.
        await _record_budget_outcome(budget_outcome)
    # Prior turns precede the current message. They enter the messages list
    # rather than `metadata`, so `_cache_key` fingerprints them by
    # construction (§Diseño 7) -- two conversations sharing a last user
    # message no longer collide on either cache gate.
    memory_messages = list(memory_context.messages)
    # T18: the two metadata sources are independent optional dicts, merged
    # into one -- `metadata["rag"]` (documental) and `metadata["memory"]`
    # (Mode B out-of-window evidence) coexist as sibling keys, and
    # `messages_for_provider` (T17) renders whichever are present, in its own
    # fixed order. `None` when neither channel has anything to contribute,
    # unchanged from before T18.
    provider_metadata = {
        **(memory_context.provider_metadata or {}),
        **(rag_context.provider_metadata or {}),
    } or None
    public_sources = [
        RagSourceOut(
            citation=source.citation,
            document_id=source.document_id,
            chunk_id=source.chunk_id,
            rank=source.rank,
        )
        for source in rag_context.sources
    ]

    if getattr(payload, "stream", False):
        cache.log_bypass(reason=_cache_bypass_reason() or "streaming")

        async def event_generator() -> AsyncIterator[str]:
            generation_outcome: str | None = None
            metrics_provider_result: ProviderResult | None = None
            logger.info(
                "chat_streaming_start request_id=%s conversation_id=%s is_new=%s",
                str(request_id),
                str(conversation_id),
                str(is_new_conversation),
            )
            start_stream = time.perf_counter()
            chunks: list[str] = []

            try:
                # 1) Stream from provider (no DB, no transaction)
                stream_kwargs: dict[str, Any] = {
                    "request_id": request_id,
                    "messages": [
                        *memory_messages,
                        ChatMessage(role="user", content=payload.message),
                    ],
                }
                if provider_metadata is not None:
                    stream_kwargs["provider_metadata"] = provider_metadata
                stream_session = await chat_service.stream_chat(**stream_kwargs)

                async for chunk in stream_session.chunks:
                    yield _sse("token", chunk)

                stream_result = await stream_session.get_final_result()

                # 2) Persist AFTER provider finishes (single atomic transaction)
                assistant_text = stream_result.assistant_message.content
                assistant_content_final = truncate(
                    assistant_text,
                    settings.max_assistant_chars,
                )

                user_msg_id = uuid.uuid4()
                assistant_msg_id = uuid.uuid4()

                async with db.begin():
                    # Conversation: create or validate (tenant-scoped)
                    if is_new_conversation:
                        conv = Conversation(id=conversation_id, tenant_id=tenant_id)
                        db.add(conv)
                        await db.flush()
                    else:
                        conv = await db.get(Conversation, conversation_id)
                        if conv is None or conv.tenant_id != tenant_id:
                            generation_outcome = "not_found"
                            yield _sse_json("error", {"error_kind": "not_found"})
                            return

                    # Persist user message
                    db.add(
                        Message(
                            id=user_msg_id,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                            role=MessageRole.user,
                            content=payload.message,
                        )
                    )
                    await db.flush()

                    # Persist assistant message
                    db.add(
                        Message(
                            id=assistant_msg_id,
                            conversation_id=conversation_id,
                            tenant_id=tenant_id,
                            role=MessageRole.assistant,
                            content=assistant_content_final,
                        )
                    )
                    await db.flush()

                    # Usage event best-effort (success)
                    latency_ms = max(0, int((time.perf_counter() - start_stream) * 1000))

                    provider_result = (
                        stream_result.provider_result.provider_result
                        if stream_result.provider_result is not None
                        else None
                    )
                    metrics_provider_result = provider_result
                    generation_outcome = "ok"

                    try:
                        db.add(
                            UsageEvent(
                                id=uuid.uuid4(),
                                provider=(
                                    provider_result.provider if provider_result else "unknown"
                                ),
                                model_version=(
                                    provider_result.model_version
                                    if provider_result
                                    else "unknown"
                                ),
                                prompt_version=(
                                    provider_result.prompt_version
                                    if provider_result
                                    else "unknown"
                                ),
                                status=ChatStatus.success.value,
                                request_id=request_id,
                                latency_ms=(
                                    provider_result.latency_ms
                                    if provider_result
                                    and provider_result.latency_ms is not None
                                    else latency_ms
                                ),
                                error_message=None,
                                conversation_id=None,
                                message_id=assistant_msg_id,
                                input_tokens=(
                                    provider_result.input_tokens if provider_result else None
                                ),
                                output_tokens=(
                                    provider_result.output_tokens if provider_result else None
                                ),
                                total_tokens=(
                                    provider_result.total_tokens if provider_result else None
                                ),
                            )
                        )
                    except Exception:
                        pass

                # 3) Done
                yield _sse_json(
                    "done",
                    {
                        "request_id": str(request_id),
                        "conversation_id": str(conversation_id),
                        "user_message_id": str(user_msg_id),
                        "assistant_message_id": str(assistant_msg_id),
                        "status": "success",
                        "sources": [source.model_dump(mode="json") for source in public_sources],
                    },
                )

            except ProviderError as e:
                generation_outcome = "error"
                yield _sse_json(
                    "error",
                    {
                        "error_kind": getattr(e.kind, "value", str(e.kind)),
                        "retryable": bool(getattr(e, "retryable", False)),
                    },
                )
                return
            except Exception:
                generation_outcome = "error"
                logger.exception(
                    "chat_streaming_unhandled_error request_id=%s conversation_id=%s",
                    str(request_id),
                    str(conversation_id),
                )
                yield _sse_json("error", {"error_kind": "internal"})
                return
            finally:
                # AC18 outcome 8: on client disconnect the generator is
                # finalized under cancellation, and any unshielded `await`
                # here can be aborted before it completes. `asyncio.shield`
                # lets the write survive that -- best-effort, zero-or-one row,
                # per the weaker contract outcome 8 carries. Every other
                # outcome (1-7) reaches this normally and the write is
                # effectively synchronous.
                try:
                    await asyncio.shield(
                        asyncio.wait_for(
                            _write_rag_request_metrics(
                                request,
                                tenant_id=tenant_id,
                                generation_outcome=generation_outcome or "cancelled",
                                provider_result=metrics_provider_result,
                                memory_context=memory_context,
                                total_latency_ms=max(
                                    0, int((time.perf_counter() - start_stream) * 1000)
                                ),
                            ),
                            timeout=settings.rag_request_metrics_timeout_s,
                        )
                    )
                except Exception:
                    pass

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    try:
        cache_write_result: ChatServiceResult | None = None
        # Single transaction: either everything is persisted, or nothing is.
        _messages = [*memory_messages, ChatMessage(role="user", content=payload.message)]
        async with db.begin():
            # 1) Conversation: create or validate (tenant-scoped)
            if is_new_conversation:
                conv = Conversation(id=conversation_id, tenant_id=tenant_id)
                db.add(conv)
                await db.flush()
            else:
                conv = await db.get(Conversation, conversation_id)
                if conv is None or conv.tenant_id != tenant_id:
                    generation_outcome = "not_found"
                    raise HTTPException(status_code=404, detail="conversation_id not found")

            # 2) Persist user message
            user_msg = Message(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                role=MessageRole.user,
                content=payload.message,
            )
            db.add(user_msg)
            await db.flush()
            user_message_id = user_msg.id

            # 3) Execute model (via ChatService)
            service_result = None
            bypass_reason = _cache_bypass_reason()
            if bypass_reason is not None:
                cache.log_bypass(reason=bypass_reason)
            else:
                service_result = await cache.get(
                    request_id=request_id, messages=_messages, tenant_id=tenant_id
                )
            if service_result is None:
                run_kwargs: dict[str, Any] = {
                    "request_id": request_id,
                    "messages": _messages,
                }
                if provider_metadata is not None:
                    run_kwargs["provider_metadata"] = provider_metadata
                service_result = await chat_service.run(**run_kwargs)
                if _cache_bypass_reason() is None:
                    cache_write_result = service_result

            assistant_content = truncate(
                service_result.assistant_message.content,
                settings.max_assistant_chars,
            )
            provider_result = service_result.provider_result

            # 4) Persist assistant message
            assistant_msg = Message(
                id=uuid.uuid4(),
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                role=MessageRole.assistant,
                content=assistant_content,
            )
            db.add(assistant_msg)
            await db.flush()
            assistant_message_id = assistant_msg.id

            status = ChatStatus.success
            generation_outcome = "ok"
            metrics_provider_result = provider_result

            # 5) UsageEvent WITH valid FKs (best-effort)
            latency_ms = max(0, int((time.perf_counter() - start) * 1000))

            def _as_int_or_zero(v) -> int:
                try:
                    return max(0, int(v or 0))
                except Exception:
                    return 0

            input_tokens = _as_int_or_zero(provider_result.input_tokens)
            output_tokens = _as_int_or_zero(provider_result.output_tokens)
            total_tokens = _as_int_or_zero(provider_result.total_tokens)

            # Telemetry must never break the request.
            try:
                ev = UsageEvent(
                    id=uuid.uuid4(),
                    provider=provider_result.provider,
                    model_version=provider_result.model_version,
                    prompt_version=provider_result.prompt_version,
                    status=status.value,
                    request_id=request_id,
                    latency_ms=latency_ms,
                    error_message=None,
                    conversation_id=None,
                    message_id=assistant_message_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )
                db.add(ev)
            except Exception:
                pass

        # commit OK (exit db.begin)
        if cache_write_result is not None:
            await cache.set(messages=_messages, result=cache_write_result, tenant_id=tenant_id)

        return ChatResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            assistant_content=assistant_content,
            sources=public_sources,
            status=status,
            error_message=None,
        )

    except HTTPException:
        raise

    except (ProviderTimeoutError, ProviderExecutionError) as e:
        generation_outcome = "timeout" if isinstance(e, ProviderTimeoutError) else "error"
        error_message = sanitize_error_message(str(e), settings.max_error_message_chars)

        try:
            await db.rollback()
        except Exception:
            pass

        latency_ms = max(0, int((time.perf_counter() - start) * 1000))

        try:
            async with db.begin():
                db.add(
                    UsageEvent(
                        id=uuid.uuid4(),
                        provider=_error_provider_name(chat_service),
                        model_version="local",
                        prompt_version="v0",
                        status=ChatStatus.error.value,
                        request_id=request_id,
                        latency_ms=latency_ms,
                        error_message=error_message,
                        conversation_id=None,
                        message_id=None,
                    )
                )
        except Exception:
            pass

        return ChatResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            user_message_id=None,
            assistant_message_id=None,
            assistant_content=None,
            status=ChatStatus.error,
            error_message=error_message,
        )

    except Exception as e:
        generation_outcome = "error"

        logger.exception(
            "chat_unhandled_error request_id=%s conversation_id=%s",
            str(request_id),
            str(conversation_id),
        )
        error_message = sanitize_error_message("internal error", settings.max_error_message_chars)

        try:
            await db.rollback()
        except Exception:
            pass

        latency_ms = max(0, int((time.perf_counter() - start) * 1000))

        try:
            async with db.begin():
                db.add(
                    UsageEvent(
                        id=uuid.uuid4(),
                        provider=_error_provider_name(chat_service),
                        model_version="local",
                        prompt_version="v0",
                        status=ChatStatus.error.value,
                        request_id=request_id,
                        latency_ms=latency_ms,
                        error_message=sanitize_error_message(str(e), settings.max_error_message_chars),
                        conversation_id=None,
                        message_id=None,
                    )
                )
        except Exception:
            pass

        return ChatResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            user_message_id=None,
            assistant_message_id=None,
            assistant_content=None,
            status=ChatStatus.error,
            error_message=error_message,
        )

    finally:
        try:
            await asyncio.wait_for(
                _write_rag_request_metrics(
                    request,
                    tenant_id=tenant_id,
                    generation_outcome=generation_outcome or "error",
                    provider_result=metrics_provider_result,
                    memory_context=memory_context,
                    total_latency_ms=max(0, int((time.perf_counter() - start) * 1000)),
                ),
                timeout=settings.rag_request_metrics_timeout_s,
            )
        except Exception:
            pass
