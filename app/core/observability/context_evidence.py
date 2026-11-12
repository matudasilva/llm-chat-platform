"""Bounded, content-free C1 observations. Never participates in business decisions."""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 10000
_current = ContextVar("context_evidence", default=None)
_purpose = ContextVar("context_evidence_purpose", default="primary")
_invocation = ContextVar("context_evidence_invocation", default=None)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def text_receipt(key, text, *, original_chars=None, occurrence=0, **fields):
    return dict(key=str(key), occurrence=occurrence, start=0, end=len(text), chars=len(text),
                original_chars=len(text) if original_chars is None else original_chars,
                bytes=len(text.encode()), sha256=digest(text.encode()), **fields)


class Evidence:
    def __init__(self, instance_id, correlation_id):
        self.lock = threading.RLock()
        self.instance_id = str(instance_id)
        self.correlation_id = correlation_id
        self.valid = True
        self.closed = False
        self.records = []
        self.size = 0
        self.items = 0
        self.window = []
        self.scope = None
        self.documents = {}
        self.invocations = 0
        self.add("request.start", dict(instance_id=self.instance_id, correlation_id=correlation_id))

    def add(self, stage, data):
        with self.lock:
            self._add(stage, data)

    def _add(self, stage, data):
        if self.closed:
            self.valid = False
            return
        def count(value):
            if isinstance(value, list):
                return len(value) + sum(count(v) for v in value)
            if isinstance(value, dict):
                return sum(count(v) for v in value.values())
            return 0
        item_count = count(data)
        record = dict(ordinal=len(self.records), stage=stage, data=data,
                      invocation=_invocation.get(), purpose=_purpose.get(),
                      previous=self.records[-1]["hash"] if self.records else "0" * 64)
        raw = encoded(record)
        if self.items + item_count + 1 > MAX_ITEMS or self.size + len(raw) > MAX_BYTES:
            self.valid = False
            return
        record["hash"] = digest(raw)
        self.records.append(record)
        self.size += len(raw)
        self.items += item_count + 1

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(dict(instance_id=self.instance_id,
                                      correlation_id=self.correlation_id,
                                      valid=self.valid, closed=self.closed,
                                      records=self.records, count=len(self.records)))


def observe(stage, builder):
    """Evaluate even field access inside the best-effort boundary."""
    state = _current.get()
    if state is None:
        return
    try:
        with state.lock:
            if not state.valid or state.closed:
                state.valid = False
                return
            data = builder(state)
            if data is not None:
                state.add(stage, data)
    except Exception:
        state.valid = False


@contextmanager
def request_evidence(instance_id, correlation_id):
    state = token = None
    try:
        state = Evidence(instance_id, correlation_id)
        token = _current.set(state)
    except Exception:
        pass
    outcome = "returned"
    try:
        yield state
    except BaseException:
        outcome = "aborted"
        raise
    finally:
        if state is not None:
            try:
                with state.lock:
                    state.add("request.end", dict(outcome=outcome, valid=state.valid,
                                                 checkpoints=[r["stage"] for r in state.records],
                                                 invocations=state.invocations))
                    state.closed = True
            except Exception:
                state.valid = False
                state.closed = True
        if token is not None:
            _current.reset(token)


@contextmanager
def invocation():
    """Harness entrypoint scope; independent of retry/call counting."""
    state = _current.get()
    token = None
    if state is not None:
        try:
            state.invocations += 1
            token = _invocation.set(state.invocations)
            observe("invocation.start", lambda _: {})
        except Exception:
            state.valid = False
    outcome = "returned"
    try:
        yield _invocation.get()
    except BaseException as exc:
        outcome = type(exc).__name__
        raise
    finally:
        observe("invocation.end", lambda _: {"outcome": outcome})
        if token is not None:
            _invocation.reset(token)


def purpose(name):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            token = None
            try:
                token = _purpose.set(name)
            except Exception:
                observe("purpose.invalid", lambda _: 1 / 0)
            try:
                return await fn(*args, **kwargs)
            finally:
                if token is not None:
                    _purpose.reset(token)
        return wrapped
    return decorate


def bind_scope(resolve):
    def build(state):
        tenant, conversation = resolve()
        scope = dict(tenant_sha256=digest(str(tenant).encode()),
                     conversation=str(conversation) if conversation else None)
        if state.scope is not None:
            if scope != state.scope:
                state.valid = False
            return None
        state.scope = scope
        return scope
    observe("scope", build)


def documents(stage, chunks, ranked=False):
    def build(_):
        items = []
        occurrences = {}
        for value in chunks:
            chunk = value.chunk if ranked else value
            key = str(chunk.chunk_id)
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            items.append(text_receipt(chunk.chunk_id, chunk.text, occurrence=occurrence,
                                      document_id=str(chunk.document_id)))
            if len(items) > MAX_ITEMS:
                raise ValueError("receipt limit")
        return dict(items=items)
    observe(stage, build)


def source_projection(result, sources):
    def build(state):
        original = {str(v.chunk.chunk_id): len(v.chunk.text) for v in result.chunks}
        items = [text_receipt(v.chunk_id, v.content,
                          original_chars=original[str(v.chunk_id)], citation=v.citation,
                          document_id=str(v.document_id)) for v in sources]
        occurrences = {}
        for item in items:
            item["occurrence"] = occurrences.get(item["key"], 0)
            occurrences[item["key"]] = item["occurrence"] + 1
        state.documents = {v["citation"]: v for v in items}
        return dict(items=items)
    observe("documents.projected", build)


def history(stage, messages):
    observe(stage, lambda _: dict(items=[text_receipt(m.sequence, m.content, role=m.role)
                                         for m in messages]))


def _copy_window_receipts(receipts):
    # Immutable scalar fields need independent containers, not recursive copying.
    if type(receipts) is list and len({id(row) for row in receipts}) == len(receipts) and all(
        type(row) is dict and all(type(key) is str and type(value) in (str, int, bool, type(None))
                                 for key, value in row.items())
        for row in receipts
    ):
        return [row.copy() for row in receipts]
    return copy.deepcopy(receipts)


def window_materialized(partition):
    def build(state):
        if len(partition.window) > MAX_ITEMS:
            raise ValueError("window observation limit")
        state.window = [text_receipt(m.sequence, m.content, role=m.role)
                        for m in partition.window]
        return dict(items=_copy_window_receipts(state.window))
    observe("window.materialized", build)


def packed_window(fn):
    @wraps(fn)
    def wrapped(messages, *args, **kwargs):
        result = fn(messages, *args, **kwargs)
        def build(state):
            previous = state.window
            if len(previous) != len(messages):
                raise ValueError("missing window identity")
            offset = len(messages) - len(result.messages)
            kept = []
            for index, message in enumerate(result.messages, offset):
                original = messages[index]
                receipt = previous[index]
                if not original.content.startswith(message.content):
                    raise ValueError("non-prefix truncation")
                if receipt["sha256"] != digest(original.content.encode()):
                    raise ValueError("window identity mismatch")
                kept.append(text_receipt(receipt["key"], message.content,
                            original_chars=receipt["original_chars"], role=message.role))
            state.window = kept
            return dict(items=_copy_window_receipts(kept), removed=[r["key"] for r in previous[:offset]])
        observe("window.pack", build)
        return result
    return wrapped


def episodic(stage, events, *, ranked=False):
    def build(_):
        items = []
        for value in events:
            event = value.event if ranked else value
            spans = [text_receipt(m.sequence, m.content, role=m.role) for m in event.unit.messages]
            items.append(text_receipt(event.event_id, event.document_text, spans=spans,
                                      separator="newline"))
        return dict(items=items)
    observe(stage, build)


def final_cap(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        result = fn(*args, **kwargs)
        def build(state):
            memory, rag, outcome = result
            if not memory.messages:
                state.window = []
            if len(state.window) != len(memory.messages):
                raise ValueError("missing packed identity")
            for item, message in zip(state.window, memory.messages):
                if item["sha256"] != digest(message.content.encode()):
                    raise ValueError("packed span mismatch")
            return dict(window=_copy_window_receipts(state.window),
                        documents=[text_receipt(s.chunk_id, s.content, citation=s.citation,
                                   document_id=str(s.document_id),
                                   original_chars=state.documents[s.citation]["original_chars"],
                                   occurrence=state.documents[s.citation]["occurrence"]) for s in rag.sources],
                        episodic=[text_receipt(e.event_id, e.content) for e in memory.retrieved_events],
                        dropped_documents=[s.citation for s in kwargs["rag_context"].sources
                                           if s.citation not in {v.citation for v in rag.sources}],
                        dropped_episodic=[str(e.event_id) for e in kwargs["memory_context"].retrieved_events
                                         if e.event_id not in {v.event_id for v in memory.retrieved_events}],
                        outcome=outcome, cap=kwargs["max_chars"],
                        current_message_sha256=digest(kwargs["current_message"].encode()))
        observe("context.packed", build)
        return result
    return wrapped


def rendered(fn):
    @wraps(fn)
    def wrapped(input):
        result = fn(input)
        observe("prompt.rendered", lambda _: dict(items=[text_receipt(i, m.content, role=m.role)
                                                         for i, m in enumerate(result)]))
        return result
    return wrapped


def outcome(stage):
    def decorate(fn):
        @wraps(fn)
        async def wrapped(value, *args, **kwargs):
            observe(stage, lambda _: {"outcome": value})
            return await fn(value, *args, **kwargs)
        return wrapped
    return decorate


def prompt_mapping(input, memory_events, sources, prefix_count):
    def build(state):
        memory = memory_events or []
        docs = sources or []
        mappings = []
        for index, item in enumerate(memory):
            mappings.append(dict(channel="episodic", key=str(item["event_id"]),
                                 message_index=0, item_index=index, field="content",
                                 sha256=digest(item["content"].encode())))
        for index, item in enumerate(docs):
            mappings.append(dict(channel="documents", key=str(item["chunk_id"]),
                                 citation=item["citation"], message_index=int(bool(memory)),
                                 item_index=index, field="content",
                                 sha256=digest(item["content"].encode())))
        if _purpose.get() == "primary":
            for index, item in enumerate(state.window):
                if item["sha256"] != digest(input.messages[index].content.encode()):
                    raise ValueError("rendered window identity mismatch")
                mappings.append(dict(channel="window", key=item["key"],
                                     message_index=prefix_count + index, field="content",
                                     sha256=item["sha256"]))
        return dict(mappings=mappings)
    observe("prompt.mapping", build)
