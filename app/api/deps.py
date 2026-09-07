# app/api/deps.py
import asyncio
import logging
import uuid
from typing import Sequence

from fastapi import Request

from app.core.domain.chat_memory import ChatMemoryContext
from app.core.domain.conversation_history import (
    ConversationHistoryAssembler,
    ConversationNotFoundError,
    HistoryMessage,
)
from app.core.domain.conversation_turns import build_materialized_window
from app.core.domain.provider import ProviderPort
from app.core.domain.provider_factory import build_provider, build_provider_resolver
from app.core.domain.chat_service import ChatService
from app.core.domain.rag_generation import RagGenerationAugmentor, RagGenerationContext
from app.core.domain.retrieval_factory import build_retrieval_pipeline
from app.core.settings import settings
from app.http.middleware.tenant import get_tenant_id
from app.http.request_context import get_request_id
from app.http import pipeline_metrics
from app.infra.db.session import (
    get_history_sessionmaker,
    short_lived_history_session,
)
from app.infra.db.session import short_lived_rag_session
from app.services.conversation_history_adapter import SqlConversationHistoryAdapter
from app.services.conversation_query_service import ConversationQueryService
from app.schemas.chat import ChatRequest
from app.services.notion_write import NotionWriteService
from app.services.routing_signals import build_routing_context_builder

logger = logging.getLogger(__name__)


def get_provider() -> ProviderPort:
    return build_provider(settings)


def get_chat_service() -> ChatService:
    return ChatService(
        provider_resolver=build_provider_resolver(settings),
        routing_context_builder=build_routing_context_builder(settings),
        timeout_s=settings.provider_timeout_s,
    )


async def get_chat_rag_context(payload: ChatRequest, request: Request) -> RagGenerationContext:
    if not settings.chat_rag_augmentation_enabled:
        return RagGenerationContext()

    rid = get_request_id()
    request_id = uuid.UUID(rid) if rid else uuid.uuid4()
    try:
        async with short_lived_rag_session(request) as db:
            augmentor = RagGenerationAugmentor(
                pipeline=build_retrieval_pipeline(db, settings),
                timeout_s=settings.chat_rag_retrieval_timeout_s,
                max_sources=settings.chat_rag_max_sources,
                max_source_chars=settings.chat_rag_max_source_chars,
                max_context_chars=settings.chat_rag_max_context_chars,
            )
            return await augmentor.augment(request_id=request_id, query=payload.message)
    except Exception as exc:
        # Construction/session failures happen outside RagGenerationAugmentor,
        # but remain the same best-effort pre-generation boundary.
        RagGenerationAugmentor._log_degraded(
            request_id=request_id,
            reason=type(exc).__name__,
        )
        return RagGenerationContext()


async def get_chat_memory_context(
    payload: ChatRequest, request: Request
) -> ChatMemoryContext:
    """Assemble conversation memory OUTSIDE the write transaction.

    A FastAPI dependency, exactly like `get_chat_rag_context` above, and for
    the same structural reason: dependencies resolve **before** the handler
    body runs, so the assembly provably happens before `async with db.begin()`
    is entered on either path (`chat.py:134` streaming, `:258` non-streaming).
    AC11's Gate B1 half is therefore satisfied by construction rather than by
    reviewer discipline. Assembling inside the handler to reuse `db` would
    break it and would also put a best-effort read on the pool the atomic
    write needs (§Diseño 7).

    **It never raises.** The streaming path answers not-found as an SSE `error`
    frame on HTTP 200 (`chat.py:141-143`), never a 404, so a dependency raising
    `HTTPException` would convert that into a real 404 for streaming clients --
    an observable SSE-contract change (invariant 7). Every failure yields empty
    memory and the request proceeds.

    That is not the silent-empty ADR-011 §2 forbids. The port still raises
    `ConversationNotFoundError`; this layer catches it **distinctly** from the
    generic handler, records the outcome, and the route's own ownership guard
    re-checks against the database and answers in its existing shape on both
    paths.

    Ordering matters on the streaming path in a way response assertions cannot
    show: the provider is invoked at `chat.py:117`, **before** the guard at
    `:141`. So for a cross-tenant conversation the guard cannot stop memory
    from reaching the model -- only this function returning empty can. AC12
    captures `ProviderInput` for exactly that reason.
    """
    if not settings.conversation_history_enabled:
        return ChatMemoryContext()

    # The RAW payload value, never the handler's derived `conversation_id`.
    # `chat.py:71` does `payload.conversation_id or uuid.uuid4()`, and that
    # generated id is not persisted until inside the write transaction. Reading
    # the derived value would make every FIRST turn call `fetch_ordered` with a
    # nonexistent id, degrade through the not-found branch, and record
    # `conversation_not_found` for what is simply a new conversation -- one
    # wasted round-trip per first turn and a misleading outcome. ADR-011
    # requires skipping, not catching.
    conversation_id = payload.conversation_id
    if conversation_id is None:
        await _record_memory_outcome("skipped_first_turn")
        return ChatMemoryContext()

    tenant_id = get_tenant_id()
    rid = get_request_id()
    request_id = uuid.UUID(rid) if rid else uuid.uuid4()

    try:
        sessionmaker = get_history_sessionmaker(request)
        async with short_lived_history_session(sessionmaker) as db:
            assembler = ConversationHistoryAssembler(
                max_messages=settings.conversation_history_max_messages,
                max_chars=settings.conversation_history_max_chars,
            )
            adapter = SqlConversationHistoryAdapter(
                ConversationQueryService(db),
                max_rows=settings.conversation_history_max_rows,
            )
            partition, truncated, cap_reached = await asyncio.wait_for(
                _materialize_window(adapter, assembler, conversation_id, tenant_id),
                timeout=settings.conversation_history_timeout_s,
            )
    except ConversationNotFoundError:
        # Caught DISTINCTLY from the generic handler below (AC13). The two are
        # not the same event: this one is an ownership answer the route will
        # also produce, while the generic branch is a degradation.
        await _record_memory_outcome("conversation_not_found")
        return ChatMemoryContext()
    except asyncio.TimeoutError:
        await _record_memory_outcome("timeout")
        _log_memory_degraded(request_id=request_id, reason="timeout")
        return ChatMemoryContext()
    except Exception as exc:
        await _record_memory_outcome("error")
        _log_memory_degraded(request_id=request_id, reason=type(exc).__name__)
        return ChatMemoryContext()

    context = ChatMemoryContext.from_partition(
        partition, truncated=truncated, history_row_cap_reached=cap_reached
    )
    await _record_memory_outcome("empty" if context.is_empty else "ok")
    return context


class _PrefetchedHistoryPort:
    """Hands the assembler rows already fetched, so the DB is read once.

    §Diseño 8 step 1 groups the **full** SQL-bounded `fetch_ordered` output,
    while the assembler returns only its bounded slice. Both are needed, and a
    second `fetch_ordered` call would be a second query against a conversation
    that may have changed between them -- the window and the grouped set would
    then come from different snapshots.

    Kept here rather than pushed into `ConversationHistoryAssembler`: ORQ-38
    owns that class and its bounds are ADR-011's, which this ORQ explicitly
    does not amend.
    """

    __slots__ = ("_messages",)

    def __init__(self, messages: Sequence[HistoryMessage]) -> None:
        self._messages = messages

    async def fetch_ordered(self, conversation_id, tenant_id):
        return self._messages


async def _materialize_window(adapter, assembler, conversation_id, tenant_id):
    """Fetch once, bound with ADR-011's rules, then snap and filter (T10/T12)."""
    # The real adapter first: this is the call that raises
    # `ConversationNotFoundError` for a conversation the tenant does not own,
    # and -- since T12 -- the call that applies the SQL row cap
    # (`conversation_history_max_rows`), not the assembler.
    all_messages = await adapter.fetch_ordered(conversation_id, tenant_id)
    assembled = await assembler.assemble(
        _PrefetchedHistoryPort(all_messages), conversation_id, tenant_id
    )
    partition = build_materialized_window(
        all_messages=all_messages, bounded_messages=assembled.messages
    )
    # AC36: the cap is reached when the SQL read returned exactly the limit --
    # not "close to it", since a shorter conversation legitimately returns
    # fewer rows than the cap without ever having been bounded.
    cap_reached = len(all_messages) == settings.conversation_history_max_rows
    return partition, assembled.truncated, cap_reached


async def _record_memory_outcome(outcome: str) -> None:
    # Uses only the collector T8 already shipped. Nothing here writes a row:
    # the `rag_request_metrics` table and its write sites are T14's.
    #
    # `async def` although every caller is already async and a sync helper
    # would work today: AC26's scan forbids *any* sync writer outside
    # `pipeline_metrics.py`, deliberately bluntly, because the failure it
    # guards against -- a copied context silently swallowing every field -- is
    # invisible at runtime. Keeping that rule unarguable is worth an `await`.
    pipeline_metrics.record(memory_outcome=outcome)


def _log_memory_degraded(*, request_id: uuid.UUID, reason: str) -> None:
    try:
        logger.warning(
            "chat_memory.degraded",
            extra={
                "event": "chat_memory.degraded",
                "request_id": str(request_id),
                "reason": reason,
            },
        )
    except Exception:
        pass


def get_notion_write_service() -> NotionWriteService:
    return NotionWriteService(settings)
