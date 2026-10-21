"""Serialized trace integration for the existing Windows JobObject observer.

One caller owns the job, ledger and initially empty binary sink. Start/sample
calls serialize native handle use and trace publication. After a trace error,
further start/sample calls refuse; shutdown still attempts native termination,
empty-job verification and every handle close. Existing frozen observers and
their historical receipts are unchanged. Blocking arbitrary sinks are outside
this adapter's liveness contract; ledger flush is not power-loss durability.
"""
import copy
import threading
import time

from experiments import process_observer as native


class ObservedWindowsJob:
    def __init__(self, ledger, *, job=None):
        self.ledger = ledger
        self.job = native.WindowsJob() if job is None else job
        self._lock = threading.RLock()
        self._ref = None
        self._launch_attempted = False
        self._retired = False
        self._trace_error = None
        self._shutdown = None

    def _record(self, kind, **fields):
        if self._trace_error is not None:
            raise native.ObserverError("Trace failed; only shutdown is permitted")
        try:
            return self.ledger.append(kind, native_thread_id=threading.get_native_id(),
                emitted_perf_counter=time.perf_counter(), **fields)
        except BaseException as error:
            self._trace_error = {"kind": kind, "error_type": type(error).__name__}
            raise

    def _check_active(self):
        if self._retired or self._trace_error is not None:
            raise native.ObserverError("Session retired or trace failed; only shutdown is permitted")

    def start(self, command, *, cwd=None):
        with self._lock:
            self._check_active()
            if self._launch_attempted:
                raise native.ObserverError("This observer owns one launch only")
            # Retain ownership before logging: a failed write must not hide the
            # live process from the cleanup path.
            self._launch_attempted = True
            self._ref = self.job.start_suspended(command, cwd=cwd)
            self._record("started", pid=self._ref.pid,
                creation_filetime=self._ref.creation_filetime)
            return self._ref

    def sample(self, request_id):
        with self._lock:
            self._check_active()
            if self._ref is None:
                raise native.ObserverError("No process has been started")
            if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                raise ValueError("request_id must contain 1..128 characters")
            self.job.member(self._ref)
            reading = self._ref.reading()
            return self._record("sample", request_id=request_id, reading=reading)

    def shutdown(self, timeout=4.0):
        """Native cleanup remains mandatory when trace recording has failed.

        Timeout bounds the existing cooperative cleanup poll, not arbitrary
        sink/OS calls. A repeated successful shutdown returns a detached receipt.
        Native cleanup/close errors are raised after all closes are attempted.
        """
        with self._lock:
            if self._shutdown is not None:
                return copy.deepcopy(self._shutdown)
            self._retired = True
            cleanup, errors = None, []
            try:
                if self.job.active_count():
                    self.job.terminate()
                cleanup = self.job.cleanup_receipt(timeout, require_zero=True)
            except BaseException as error:
                errors.append(error)
            for close in (self.job.close, self.job.close_refs):
                try:
                    close()
                except BaseException as error:
                    errors.append(error)
            if not errors:
                try:
                    self._record("closed", cleanup=cleanup)
                except BaseException:
                    pass  # Explicitly retained below; no retry or fabricated row.
            report = {"native_cleanup": cleanup, "native_errors": [type(e).__name__ for e in errors],
                "handles_closed": not errors, "trace_complete": self._trace_error is None,
                "trace_error": copy.deepcopy(self._trace_error), "ledger": self.ledger.snapshot()}
            if errors:
                raise native.ObserverError("Native shutdown failed after all closes were attempted: "
                    + ", ".join(report["native_errors"])) from errors[0]
            self._shutdown = report
            return copy.deepcopy(report)
