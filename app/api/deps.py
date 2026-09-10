# app/api/deps.py
import asyncio
import dataclasses
import logging
import uuid
from typing import Sequence

from fastapi import Request

from app.core.domain.bm25_ranking import pack_selected_events, query_tokens, rank_events
from app.core.domain.chat_memory import ChatMemoryContext, RetrievedMemoryEvent
from app.core.domain.conversation_history import (
    ConversationHistoryAssembler,
    ConversationNotFoundError,
    HistoryMessage,
)
from app.core.domain.context_packer import pack_recent_window
from app.core.domain.conversation_turns import build_materialized_window
from app.core.domain.retrieval_corpus import RetrievalCorpus
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

    # T13: a FIRST pass at the hard cap, over the two contributors this
    # dependency can see. It is deliberately NOT the authority: the documental
    # RAG channel is a separate dependency invisible from here, so the
    # combined cap of §Diseño 7 is enforced once, over all three contributors,
    # in `added_context_budget.enforce_added_context_cap`, called from the
    # route immediately before the prompt is assembled. Two earlier attempts
    # to enforce it from inside this function were both incomplete for that
    # structural reason. What remains here is a bound on this channel alone,
    # which keeps Mode B's selection below from ranking against an unbounded
    # window; the route may trim further, and its result is what ships.
    # This call is identical whether `ebm25_enabled` is on or off, which is
    # what keeps AC16's byte-identity claim true by construction.
    packed = pack_recent_window(
        context.messages, max_chars=settings.chat_prompt_max_added_context_chars
    )
    context = dataclasses.replace(
        context,
        messages=packed.messages,
        truncated=context.truncated or packed.truncated,
    )

    # T18: Mode B, gated on `ebm25_enabled`. Built from the SAME `partition`
    # T10 already produced -- never a second grouping pass. Off by default,
    # so Mode A's outcome/prompt are exactly B1's, unchanged by any of this.
    #
    # `mode_b_outcome`, once set, OVERRIDES the window's own "ok"/"empty"
    # outcome below -- it is the more specific, Mode-B fact about the same
    # request. Tracked explicitly rather than calling `_record_memory_outcome`
    # twice, which would let the final unconditional call silently clobber
    # whichever of these two fired (`record()` is last-write-wins).
    mode_b_outcome: str | None = None
    if settings.ebm25_enabled:
        corpus = RetrievalCorpus.from_partition(partition)
        if corpus.is_empty:
            # §Diseño 8's first inert state: the snapped window already
            # covers the whole conversation, so there is nothing left to
            # retrieve.
            mode_b_outcome = "no_out_of_window_corpus"
            await _record_ebm25_selected_count(0)
        else:
            remaining_budget = settings.chat_prompt_max_added_context_chars - sum(
                len(m.content) for m in context.messages
            )
            ranked = rank_events(corpus.events, query_tokens(payload.message))
            selected, _ = pack_selected_events(ranked, max_chars=max(remaining_budget, 0))
            if not selected:
                # §Diseño 8's second inert state: evidence existed and was
                # ranked, but the budget -- after the window took its
                # (protected) share -- left no room for any of it.
                mode_b_outcome = "budget_starved"
                await _record_ebm25_selected_count(0)
            else:
                context = dataclasses.replace(
                    context,
                    retrieved_events=tuple(
                        RetrievedMemoryEvent(event_id=event.event_id, content=event.document_text)
                        for event in selected
                    ),
                )
                await _record_ebm25_selected_count(len(selected))

    # R1 (independent re-validation, 2026-09-09): a reduction this function
    # performs itself must be reported, exactly like one the route's
    # enforcement performs. `packed.truncated` is set only under cap
    # pressure, so it is precisely "the hard cap cost this request context".
    #
    # It takes precedence over the Mode B outcomes deliberately: the earlier
    # version recorded `ok`/`no_out_of_window_corpus` after having already
    # dropped 600 characters of window to the same cap, which is the stale
    # telemetry N2 fixed one layer up and this leaves standing one layer
    # down.
    #
    # **The precedence costs a diagnostic distinction, stated plainly rather
    # than explained away.** An earlier version of this comment claimed
    # `ebm25_selected_count` keeps Mode B's inertness recoverable; independent
    # re-validation refuted that. That counter separates "selected something"
    # from "selected nothing" -- it does NOT separate "window trimmed, corpus
    # empty" from "window trimmed, corpus existed but lost the budget". Both
    # now record `budget_starved` with a count of 0 and are indistinguishable
    # in telemetry. The trade is accepted knowingly: hiding a cap-driven
    # reduction behind `no_out_of_window_corpus` was the defect; losing the
    # ability to tell two inert Mode B shapes apart is the price, and
    # recovering it would need a field this ORQ is not chartered to add.
    if packed.truncated:
        await _record_memory_outcome("budget_starved")
    elif mode_b_outcome is not None:
        await _record_memory_outcome(mode_b_outcome)
    else:
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
    # R2 (independent re-validation, 2026-09-09): `truncated` is derived from
    # the FINAL materialized window, not from `assembled.truncated`.
    #
    # The assembler's flag describes an INTERMEDIATE state. §Diseño 8's
    # turn-snap runs after it and can put back exactly what it dropped: with
    # `conversation_history_max_messages=1` over `[user, assistant]`, the
    # assembler drops the `user` message and the snap restores it, so both
    # messages ship intact while the flag still claimed a truncation. That is
    # a false positive against AC14's "whenever a turn is dropped or
    # truncated" -- which is a *whenever*, not an *at least whenever*.
    #
    # Recomputing it here keeps ADR-011 §6's own definition
    # (`total_available > len(messages)`) and simply applies it to the window
    # that actually results, which is the thing `history_truncated` describes.
    truncated = len(partition.window) < len(all_messages)
    return partition, truncated, cap_reached


async def _record_ebm25_selected_count(count: int) -> None:
    # T18: 0 for both inert states; N for a successful Mode B selection.
    pipeline_metrics.record(ebm25_selected_count=count)


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
