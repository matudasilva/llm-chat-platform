"""Campaign-only durable client timing receipts; no runtime/provider integration."""
import hashlib
import os
import time
from pathlib import Path
from uuid import UUID, uuid5

from .ledger import canonical, durable_directory
from .preflight import campaign_tenant

SCHEMA = 'orq41-client-timing-v1'


class RequestTiming:
    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic_ns
        self.points = {'start': self.clock()}

    def mark(self, name):
        if name not in self.points:
            self.points[name] = self.clock()


class MeasurementRecorder:
    def __init__(self, directory, campaign_id, manifest_sha256):
        self.directory = Path(directory).resolve()
        self.campaign_id = str(UUID(campaign_id))
        if (not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64
                or any(c not in '0123456789abcdef' for c in manifest_sha256)):
            raise ValueError('Invalid measurement manifest identity')
        self.manifest_sha256 = manifest_sha256
        durable_directory(self.directory)

    def record(self, entry, request_id, returned_id, success, timing):
        expected = str(uuid5(UUID(self.campaign_id), canonical(entry).decode()))
        if request_id != expected or returned_id != request_id:
            raise ValueError('Measurement request identity mismatch')
        points = dict(timing.points)
        stream = entry['payload']['stream']
        required = ['start', 'headers', 'complete']
        if success and stream:
            required += ['first_event', 'first_content', 'done']
        if any(name not in points for name in required):
            raise ValueError('Missing client measurement')
        order = ['start', 'headers', 'first_event', 'first_content', 'done', 'complete']
        observed = [points[name] for name in order if name in points]
        if any(type(value) is not int or value < 0 for value in observed):
            raise ValueError('Invalid client clock')
        if observed != sorted(observed):
            raise ValueError('Contradictory client timing')
        if not stream and any(name in points for name in ('first_event', 'first_content', 'done')):
            raise ValueError('Non-streaming request has SSE timing')
        def elapsed(name):
            return (points[name] - points['start']) / 1_000_000 if name in points else None
        row = {'schema': SCHEMA, 'campaign_id': self.campaign_id, 'request_id': request_id,
               'manifest_sha256': self.manifest_sha256, 'entry_sha256': hashlib.sha256(canonical(entry)).hexdigest(),
               'seq': entry['seq'], 'block': entry['block'], 'tenant_id': campaign_tenant(entry),
               'stream': stream, 'success': success, 'clock': 'monotonic_ns', 'points_ns': points,
               'headers_ms': elapsed('headers'), 'first_event_ms': elapsed('first_event'),
               'ttft_ms': elapsed('first_content') if stream else None,
               'done_ms': elapsed('done'),
               'full_response_ms': elapsed('complete') if success else None,
               'failure_observed_ms': elapsed('complete') if not success else None}
        path = self.directory / (request_id + '.json')
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as target:
            target.write(canonical(row) + b'\n')
            target.flush()
            os.fsync(target.fileno())
        parent = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
