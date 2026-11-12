"""Test-instance dependency injection; never imported by production startup.

One installation per fresh process. Real session operations are delegated, not
simulated. All fault controls are Python objects owned by the local driver; no
administrative HTTP route or production setting is introduced.
"""
from __future__ import annotations

import asyncio
import contextvars
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .fixtures import HarnessError
from .transports import Barriers, ScopedProvider, with_purpose

_request = contextvars.ContextVar("g123_request", default=None)


class Lifecycle:
    def __init__(self):
        self.requests = []
        self.tasks = set()
        self.evidence_states = []
        self.sessions = []
        self.backend_pids = []
        self.closed_sessions = set()
        self.faults_triggered = []
        self.scenario_receipts = []

    @property
    def snapshots(self):
        # Take the snapshot after quiescence, not at HTTP headers/request.end:
        # a late observer write can still invalidate the retained state.
        return [state.snapshot() for state in self.evidence_states]

    async def quiesce(self, deadline):
        # No arbitrary sleeps: wait only for tasks actually created in a request
        # context. Newly created children are included on the next iteration.
        current = asyncio.current_task()
        while pending := [task for task in self.tasks if task is not current and not task.done()]:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise HarnessError("request-owned tasks exceeded cleanup bound")
            await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), remaining)
        if any(session.in_transaction() for session in self.sessions):
            raise HarnessError("business transaction remains active")
        if any(session not in self.closed_sessions for session in self.sessions):
            raise HarnessError("request-owned database session remains open")

    @contextmanager
    def track_tasks(self):
        loop = asyncio.get_running_loop()
        previous = loop.get_task_factory()

        def factory(loop, coro, **kwargs):
            task = previous(loop, coro, **kwargs) if previous else asyncio.Task(coro, loop=loop, **kwargs)
            context = kwargs.get("context")
            owner = context.get(_request) if context is not None else _request.get()
            if owner is not None:
                self.tasks.add(task)
            return task
        loop.set_task_factory(factory)
        try:
            yield
        finally:
            loop.set_task_factory(previous)


class ObservedTransaction:
    def __init__(self, transaction, session, barriers, lifecycle):
        self.transaction, self.session = transaction, session
        self.barriers, self.lifecycle = barriers, lifecycle

    async def __aenter__(self):
        result = await self.transaction.__aenter__()
        try:
            pid = (await self.session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            self.lifecycle.backend_pids.append(pid)
            await self.barriers.hit("transaction_entered")
        except BaseException as exc:
            await self.transaction.__aexit__(type(exc), exc, exc.__traceback__)
            raise
        return result

    async def __aexit__(self, kind, value, traceback):
        # A cancelled barrier MUST still delegate rollback to SQLAlchemy.
        if kind is None:
            try:
                await self.barriers.hit("before_commit")
            except BaseException as exc:
                await self.transaction.__aexit__(type(exc), exc, exc.__traceback__)
                raise
        result = await self.transaction.__aexit__(kind, value, traceback)
        if kind is None:
            await self.barriers.hit("after_commit")
        return result


def session_class(barriers, lifecycle, *, flush_conflict=None):
    """flush_conflict injects a real duplicate row once, then calls real flush.

    The callback may add a fixture object but may not emulate flush/commit. A
    real PostgreSQL exception is required in the resulting gate evidence.
    """
    class ObservedSession(AsyncSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.business_flushes = 0
            self.conflict_used = False
            lifecycle.sessions.append(self)

        def begin(self):
            return ObservedTransaction(super().begin(), self, barriers, lifecycle)

        async def close(self):
            await super().close()
            lifecycle.closed_sessions.add(self)

        async def flush(self, objects=None):
            from app.models.message import Message, MessageRole
            user_pending = any(isinstance(item, Message) and item.role == MessageRole.user for item in self.new)
            await super().flush(objects)
            self.business_flushes += 1
            # A new conversation is flushed before the user message. Counting
            # flushes would inject at the wrong boundary for new conversations.
            if user_pending:
                await barriers.hit("after_user_flush")
                if flush_conflict is not None and not self.conflict_used:
                    self.conflict_used = True
                    flush_conflict(self)
                    try:
                        await super().flush()
                    except Exception as exc:
                        original = getattr(exc, "orig", None)
                        if getattr(original, "sqlstate", None) == "23505":
                            lifecycle.faults_triggered.append("flush_rejection")
                        raise
            await barriers.hit("after_flush")
    return ObservedSession


class NamespacedRedis:
    """Same Redis operations/TTL, scoped keys only; never flush shared cache."""
    def __init__(self, client, namespace):
        import re
        if not re.fullmatch(r"orq41:g123:[a-z0-9]{8,20}:c[01]:", namespace):
            raise HarnessError("invalid run cache namespace")
        self.client, self.namespace = client, namespace

    async def check_empty(self):
        async for _ in self.client.scan_iter(match=self.namespace + "*"):
            raise HarnessError("cache namespace collision")

    async def get(self, key):
        return await self.client.get(self.namespace + key)

    async def set(self, key, value, **kwargs):
        return await self.client.set(self.namespace + key, value, **kwargs)


class LocalASGI:
    def __init__(self, app, lifecycle, barriers):
        self.app, self.lifecycle, self.barriers = app, lifecycle, barriers

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        item = dict(task=asyncio.current_task(), started=asyncio.get_running_loop().time(),
                    completed=None, disconnect=None, events=[], outcome=None)
        self.lifecycle.requests.append(item)
        token = _request.set(item)
        sse = False
        pending = b""

        async def observed_receive():
            message = await receive()
            if message["type"] == "http.disconnect":
                item["disconnect"] = asyncio.get_running_loop().time()
                await self.barriers.hit("http_disconnect")
            return message

        async def observed_send(message):
            nonlocal sse, pending
            # Private synthetic payload tape. Headers are deliberately excluded.
            item["events"].append({key: message[key] for key in ("type", "status", "body", "more_body") if key in message})
            await self.barriers.hit("before_response_delivery")
            await send(message)
            if message["type"] == "http.response.start":
                sse = any(key.lower() == b"content-type" and value.startswith(b"text/event-stream") for key, value in message.get("headers", []))
            if sse and message["type"] == "http.response.body":
                pending += message.get("body", b"")
                while b"\n\n" in pending:
                    frame, pending = pending.split(b"\n\n", 1)
                    if frame.startswith(b"event: token\n") and b"\ndata: " in frame:
                        item["events"].append(dict(type="wire_token", at=asyncio.get_running_loop().time()))
                        await self.barriers.hit("wire_token")
            if message["type"] == "http.response.body" and message.get("body"):
                await self.barriers.hit("response_fragment")
        try:
            with self.lifecycle.track_tasks():
                await self.app(scope, observed_receive, observed_send)
            item["outcome"] = "returned"
        except BaseException as exc:
            item["outcome"] = type(exc).__name__
            raise
        finally:
            item["completed"] = asyncio.get_running_loop().time()
            _request.reset(token)


class LocalPorts:
    def __init__(self, fault="none", triggered=None):
        self.fault = fault
        self.triggered = triggered if triggered is not None else []

    async def embed_one(self, query):
        if self.fault in {"retrieval_error", "retrieval_timeout"}:
            self.triggered.append(self.fault)
            if self.fault.endswith("timeout"):
                await asyncio.Event().wait()
            raise RuntimeError("controlled retrieval failure")
        return [1.0] + [0.0] * 1535

    async def rerank(self, request):
        from app.core.domain.reranker import RankedDocument
        count = min(len(request.documents), request.top_n or len(request.documents))
        return [RankedDocument(index=index, rank=index + 1) for index in range(count)]


def install(app, *, provider, candidate, cache_namespace, barriers=None, flush_conflict=None, fault="none"):
    """Install once in a fresh, preflight-verified local API process.

    This does not start lifespan, connect to PostgreSQL, mutate settings or build
    an image. C0 remains importable without the candidate observer module.
    """
    if getattr(app.state, "g123_installed", False):
        raise HarnessError("one harness installation per process")
    from app.api import deps
    from app.core.domain.chat_service import ChatService
    from app.core.domain.retrieval_pipeline import RetrievalPipeline
    from app.core.providers.pgvector_store import PgVectorStore
    from app.core.settings import settings
    from app.services import chat_response_cache
    from .validate_g123 import check_config, check_p2

    check_p2()
    check_config(settings)

    barriers = barriers or Barriers()
    lifecycle = Lifecycle()
    cache = NamespacedRedis(chat_response_cache.redis_client, cache_namespace)
    chat_response_cache.redis_client = cache
    scoped = ScopedProvider(provider, candidate=candidate, barriers=barriers)
    app.dependency_overrides[deps.get_chat_service] = lambda: ChatService(provider=scoped, timeout_s=settings.provider_timeout_s)
    allowed_faults = {"none", "history_error", "history_timeout", "retrieval_error", "retrieval_timeout",
                      "episodic_error", "telemetry_error", "telemetry_timeout", "observer_error"}
    if fault not in allowed_faults:
        raise HarnessError("unsupported dependency fault")
    ports = LocalPorts(fault, lifecycle.faults_triggered)
    fault_active = [True]
    restorations = []

    def release_fault():
        fault_active[0] = False
        ports.fault = "none"
        for restore in restorations:
            restore()
        reset_provider = getattr(provider, "release_fault", None)
        if reset_provider is not None:
            reset_provider()
    lifecycle.release_fault = release_fault
    if fault in {"history_error", "history_timeout"}:
        class History(deps.SqlConversationHistoryAdapter):
            async def fetch_ordered(self, *args, **kwargs):
                if not fault_active[0]:
                    return await super().fetch_ordered(*args, **kwargs)
                lifecycle.faults_triggered.append(fault)
                if fault.endswith("timeout"):
                    await asyncio.Event().wait()
                raise RuntimeError("controlled history failure")
        deps.SqlConversationHistoryAdapter = History
    if fault == "episodic_error":
        original_rank = deps.rank_events
        def rank_fault(*args, **kwargs):
            lifecycle.faults_triggered.append(fault)
            raise RuntimeError("controlled episodic failure")
        deps.rank_events = rank_fault
        restorations.append(lambda: setattr(deps, "rank_events", original_rank))
    if fault in {"telemetry_error", "telemetry_timeout"}:
        from app.api.routes import chat
        original_metrics = chat._write_rag_request_metrics

        async def metrics_fault(*args, **kwargs):
            lifecycle.faults_triggered.append(fault)
            if fault.endswith("timeout"):
                await asyncio.Event().wait()
            raise RuntimeError("controlled metrics failure")
        chat._write_rag_request_metrics = metrics_fault
        restorations.append(lambda: setattr(chat, "_write_rag_request_metrics", original_metrics))

    def pipeline(db, cfg):
        value = RetrievalPipeline(provider=scoped, embedding=ports, vector_store=PgVectorStore(db), reranker=ports,
                                  top_k_candidates=cfg.retrieval_pipeline_top_k_candidates,
                                  top_n=cfg.retrieval_pipeline_top_n, min_reranked_results=cfg.retrieval_pipeline_min_reranked_results)
        value._rewrite = with_purpose(value._rewrite, "rewrite")
        value._evaluate = with_purpose(value._evaluate, "evaluator")
        return value
    deps.build_retrieval_pipeline = pipeline
    if candidate:
        from app.core.observability import context_evidence as c1
        original = c1.request_evidence

        @contextmanager
        def retain(instance_id, correlation_id):
            state = None
            try:
                with original(instance_id, correlation_id) as state:
                    yield state
            finally:
                if state is not None:
                    lifecycle.evidence_states.append(state)
        c1.request_evidence = retain
        if fault == "observer_error":
            original_add = c1.Evidence._add

            def add_fault(state, stage, data):
                if stage == "context.packed":
                    lifecycle.faults_triggered.append(fault)
                    raise RuntimeError("controlled observer failure")
                return original_add(state, stage, data)
            c1.Evidence._add = add_fault
            restorations.append(lambda: setattr(c1.Evidence, "_add", original_add))

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            engine = application.state.db_engine
            if engine.dialect.name != "postgresql":
                raise HarnessError("real gate API requires PostgreSQL")
            application.state.db_sessionmaker = async_sessionmaker(bind=engine, expire_on_commit=False,
                class_=session_class(barriers, lifecycle, flush_conflict=(
                    lambda session: flush_conflict(session) if fault_active[0] else None
                ) if flush_conflict is not None else None))
            # Preserve rag_app's TenantScopedSession class and maker kwargs.
            # Only track actual close/transaction state of the two read pools.
            def track_reader(maker):
                class Reader(maker.class_):
                    def __init__(self, *args, **kwargs):
                        super().__init__(*args, **kwargs)
                        lifecycle.sessions.append(self)

                    async def close(self):
                        await super().close()
                        lifecycle.closed_sessions.add(self)
                return async_sessionmaker(class_=Reader, **maker.kw)
            application.state.rag_db_sessionmaker = track_reader(application.state.rag_db_sessionmaker)
            application.state.ops_db_sessionmaker = track_reader(application.state.ops_db_sessionmaker)
            await cache.check_empty()
            try:
                with lifecycle.track_tasks():
                    yield
            finally:
                await lifecycle.quiesce(asyncio.get_running_loop().time() + 10)
                await scoped.quiesce()
    app.router.lifespan_context = lifespan
    app.state.g123_installed = True
    return LocalASGI(app, lifecycle, barriers), lifecycle, scoped


@asynccontextmanager
async def serve(asgi, *, startup_timeout):
    """Loopback-only real HTTP server for a separately authorized gate process.

    The caller imports the original app and installs dependencies once per fresh
    vector process. No Docker operation, schema creation or provider discovery
    occurs here; uvicorn runs that app's original lifespan through the wrapper.
    """
    import socket
    import uvicorn
    from .validate_g123 import check_p2

    check_p2()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(asgi, lifespan="on", access_log=False, log_config=None))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(startup_timeout):
            while not server.started:
                if task.done():
                    await task
                    raise HarnessError("local API startup failed")
                await asyncio.sleep(.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            async with asyncio.timeout(10):
                await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            sock.close()
