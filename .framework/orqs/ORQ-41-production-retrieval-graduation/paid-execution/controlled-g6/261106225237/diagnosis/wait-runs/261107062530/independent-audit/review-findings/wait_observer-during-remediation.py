"""Bounded diagnostic intervals; never installed by production startup."""
import gc
import threading
import time
from contextvars import ContextVar

owner = ContextVar('diagnostic_wait_owner', default=None)


class WaitObserver:
    def __init__(self, limit=256):
        self.limit = limit
        self.lock = threading.RLock()
        self.active = None
        self.events = []
        self.valid = True
        self.serial = 0

    def begin(self, request_id):
        with self.lock:
            if self.active is not None:
                raise ValueError('Overlapping diagnostic requests')
            self.active, self.events, self.valid = request_id, [], True

    def mark(self, kind, phase, identity):
        # Observation failures invalidate the diagnostic, never the request.
        try:
            at = time.monotonic_ns()
            thread = threading.get_ident()
            context_owner = owner.get()
            with self.lock:
                if self.active is None:
                    return
                if len(self.events) >= self.limit:
                    self.valid = False
                    return
                if kind != 'gc' and context_owner != self.active:
                    self.valid = False
                self.events.append(dict(kind=kind, phase=phase, identity=identity,
                    at_ns=at, thread=thread, request_id=self.active,
                    context_owner=context_owner))
        except Exception:
            self.valid = False

    def next_id(self):
        with self.lock:
            self.serial += 1
            return self.serial

    def gc_callback(self, phase, info):
        self.mark('gc', phase, f'{threading.get_ident()}:{info["generation"]}')

    def finish(self):
        with self.lock:
            events, valid = list(self.events), self.valid
            self.active = None
            return events, valid

    def install(self, provider):
        from sqlalchemy.ext.asyncio import AsyncSession
        original_sql, original_client = AsyncSession.execute, provider._call_client
        observer = self

        async def execute(session, *args, **kwargs):
            if owner.get() is None:
                return await original_sql(session, *args, **kwargs)
            identity = observer.next_id()
            observer.mark('sql', 'start', identity)
            try:
                return await original_sql(session, *args, **kwargs)
            finally:
                observer.mark('sql', 'stop', identity)

        async def call_client(fn, **kwargs):
            identity = observer.next_id()
            observer.mark('sdk', 'queued', identity)
            def entered(**values):
                observer.mark('sdk', 'entered', identity)
                try:
                    return fn(**values)
                finally:
                    observer.mark('sdk', 'exited', identity)
            try:
                return await original_client(entered, **kwargs)
            finally:
                observer.mark('sdk', 'returned', identity)

        AsyncSession.execute = execute
        provider._call_client = call_client
        gc.callbacks.append(self.gc_callback)

        def restore():
            gc.callbacks.remove(self.gc_callback)
            provider._call_client = original_client
            AsyncSession.execute = original_sql
        return restore


def validate_intervals(events, request_id):
    """Check correlation/order; retain intervals for clipping, never add overlaps."""
    phases = {'sql': ('start', 'stop'), 'sdk': ('queued', 'entered', 'exited', 'returned'),
              'gc': ('start', 'stop')}
    active, intervals, completed, gc_previous = {}, [], set(), {}
    for event in events:
        kind = event['kind']
        if (kind not in phases or event['request_id'] != request_id
                or type(event['at_ns']) is not int or event['at_ns'] < 0
                or type(event['thread']) is not int
                or (kind != 'gc' and event['context_owner'] != request_id)):
            raise ValueError('Uncorrelated diagnostic interval')
        key = kind, event['identity']
        wanted = phases[kind]
        if event['phase'] == wanted[0]:
            if key in active or (kind != 'gc' and key in completed):
                raise ValueError('Duplicated interval start')
            if kind == 'gc' and key in gc_previous:
                start, stop = gc_previous[key]
                if event['at_ns'] < stop or event['at_ns'] <= start:
                    raise ValueError('Duplicated or backwards GC cycle')
            active[key] = []
        if key not in active:
            raise ValueError('Interval end without start')
        group = active[key]
        if len(group) >= len(wanted) or event['phase'] != wanted[len(group)]:
            raise ValueError('Invalid interval order')
        if group and event['at_ns'] < group[-1]['at_ns']:
            raise ValueError('Backwards diagnostic interval')
        group.append(event)
        if len(group) == len(wanted):
            if kind in ('sql', 'gc') and group[0]['thread'] != group[-1]['thread']:
                raise ValueError('Interval changed thread')
            if kind == 'sdk' and (group[0]['thread'] != group[3]['thread']
                    or group[1]['thread'] != group[2]['thread']):
                raise ValueError('SDK handoff identity changed')
            intervals.append(dict(kind=kind, identity=event['identity'], events=group))
            completed.add(key)
            if kind == 'gc':
                gc_previous[key] = group[0]['at_ns'], group[-1]['at_ns']
            del active[key]
    if active:
        raise ValueError('Incomplete diagnostic interval')
    return intervals


def validate_request_intervals(events, request_id):
    intervals = validate_intervals(events, request_id)
    if (sum(i['kind'] == 'sdk' for i in intervals) != 2
            or not any(i['kind'] == 'sql' for i in intervals)):
        raise ValueError('Incomplete SDK/SQL diagnostic coverage')
    return intervals
