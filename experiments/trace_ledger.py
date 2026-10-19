"""A bounded, serialized JSONL writer for threads sharing one binary sink.

The caller exclusively owns an initially empty sink and its lifecycle. No other
writer may use that sink. A committed row means write returned its exact byte
length and flush returned successfully; this is not fsync/power-loss durability.
On any write/flush failure the ledger is permanently poisoned: the sink may have
an uncommitted partial or complete tail. No rollback, truncation or retry occurs.
This class coordinates threads in one Python process, not separate processes.
Multiple ledger instances must not share a sink. Caps bound admitted output,
not temporary JSON serialization memory. Arbitrary write/flush calls can block;
the class offers no hard I/O deadline or production liveness guarantee.
"""
from contextlib import contextmanager
import hashlib
import json
import threading


class LedgerLimitError(ValueError):
    """Pre-I/O cap refusal. The committed prefix remains usable."""


class LedgerPoisonedError(RuntimeError):
    """No further I/O is permitted after an uncertain I/O attempt."""


class LedgerIOError(RuntimeError):
    """An attempted row is uncertain; inspect snapshot()['failure']."""


class LedgerReentrantError(RuntimeError):
    """A callback attempted to reenter the same ledger on its owning thread."""


class BoundedJSONLLedger:
    def __init__(self, sink, *, max_rows=256, max_row_bytes=32768, max_total_bytes=1048576):
        for name, value in [("max_rows", max_rows), ("max_row_bytes", max_row_bytes), ("max_total_bytes", max_total_bytes)]:
            if type(value) is not int or value <= 0:
                raise ValueError(name + " must be a positive integer")
        self._sink = sink
        self._limits = (max_rows, max_row_bytes, max_total_bytes)
        self._lock, self._local = threading.Lock(), threading.local()
        # One immutable state assignment publishes both records and byte count.
        self._state = ((), 0)
        self._failure = None

    @contextmanager
    def _serialized(self):
        if getattr(self._local, "active", False):
            raise LedgerReentrantError("Recursive ledger calls are forbidden")
        self._local.active = True
        try:
            with self._lock:
                yield
        finally:
            self._local.active = False

    def append(self, kind, **fields):
        with self._serialized():
            if self._failure is not None:
                raise LedgerPoisonedError("A prior row has uncertain sink state; further writes are forbidden")
            if not isinstance(kind, str) or not kind:
                raise ValueError("kind must be a nonempty string")
            if "seq" in fields or "kind" in fields:
                raise ValueError("seq and kind belong to the ledger")
            records, committed_bytes = self._state
            seq = len(records)
            max_rows, max_row_bytes, max_total_bytes = self._limits
            if seq >= max_rows:
                raise LedgerLimitError("Row count cap exceeded")
            row = {"kind": kind, "seq": seq, **fields}
            encoded = (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            if len(encoded) > max_row_bytes or committed_bytes + len(encoded) > max_total_bytes:
                raise LedgerLimitError("Row/total byte cap exceeded")
            # Prepare all retained data before touching the sink. Encoded bytes
            # detach the committed record from mutable caller/return objects.
            returned = json.loads(encoded)
            prepared = (records + (encoded,), committed_bytes + len(encoded))
            attempt = {"seq": seq, "row_bytes": len(encoded), "row_sha256": hashlib.sha256(encoded).hexdigest(),
                "stage": "write", "write_return": None, "flush_completed": False,
                "sink_may_have_uncommitted_bytes": True}
            try:
                written = self._sink.write(encoded)
                attempt["write_return"] = written if type(written) is int else None
                if type(written) is not int or written != len(encoded):
                    raise OSError("Sink write did not acknowledge the exact row byte count")
                attempt["stage"] = "flush"
                self._sink.flush()
                attempt["flush_completed"] = True
            except BaseException as exc:
                attempt["error_type"] = type(exc).__name__
                self._failure = attempt
                raise LedgerIOError("Row I/O failed; sink tail is uncertain and ledger is poisoned") from exc
            self._state = prepared
            return returned

    def snapshot(self):
        """Return detached committed records and the explicit uncertain attempt."""
        with self._serialized():
            records, size = self._state
            return {"committed_rows": len(records), "committed_bytes": size,
                "records": [json.loads(row) for row in records],
                "failure": None if self._failure is None else dict(self._failure),
                "poisoned": self._failure is not None,
                "commit_scope": "exact binary write plus successful flush; no fsync/power-loss claim"}
