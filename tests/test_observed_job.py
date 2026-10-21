"""Adapter controls use native collaborators as mocks; no process is launched."""
import io
import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from experiments.observed_job import ObservedWindowsJob
from experiments.trace_ledger import BoundedJSONLLedger, LedgerIOError, LedgerLimitError
from experiments import process_observer as native


def fixture(sink=None, **limits):
    job = mock.Mock()
    job.active_count.return_value = 1
    ref = SimpleNamespace(pid=123, creation_filetime=456,
        reading=lambda: {"pid": 123, "creation_filetime": 456,
            "memory": {"private_bytes": 100}, "perf_counter": 1.0})
    job.start_suspended.return_value = ref
    job.cleanup_receipt.return_value = {"all_retained_handles_exited": True, "job_active_count": 0}
    sink = io.BytesIO() if sink is None else sink
    ledger = BoundedJSONLLedger(sink, **limits)
    return ObservedWindowsJob(ledger, job=job), job, sink


class ObservedJobTests(unittest.TestCase):
    def test_concurrent_native_samples_commit_exactly_once_with_caller_identity(self):
        session, job, sink = fixture()
        session.start(["mock.exe"])
        barrier = threading.Barrier(4)
        failures = []
        def sample(worker):
            try:
                barrier.wait(2)
                for step in range(8):
                    session.sample(f"{worker}:{step}")
            except BaseException as error:
                failures.append(error)
        threads = [threading.Thread(target=sample, args=(i,), daemon=True) for i in range(4)]
        for t in threads: t.start()
        for t in threads:
            t.join(3)
            self.assertFalse(t.is_alive())
        self.assertEqual(failures, [])
        result = session.shutdown()
        rows = [json.loads(x) for x in sink.getvalue().splitlines()]
        self.assertEqual([x["seq"] for x in rows], list(range(34)))
        self.assertEqual({x["request_id"] for x in rows[1:-1]},
            {f"{worker}:{step}" for worker in range(4) for step in range(8)})
        self.assertEqual(job.member.call_count, 32)
        self.assertTrue(result["trace_complete"])

    def test_capacity_failure_still_terminates_verifies_and_closes(self):
        session, job, sink = fixture(max_rows=1)
        session.start(["mock.exe"])
        with self.assertRaises(LedgerLimitError): session.sample("over-cap")
        before = sink.getvalue()
        with self.assertRaises(native.ObserverError): session.sample("no-retry")
        result = session.shutdown()
        self.assertEqual(sink.getvalue(), before)
        self.assertFalse(result["trace_complete"])
        self.assertFalse(result["ledger"]["poisoned"])
        job.terminate.assert_called_once()
        job.cleanup_receipt.assert_called_once_with(4.0, require_zero=True)
        job.close.assert_called_once(); job.close_refs.assert_called_once()

    def test_uncertain_start_write_does_not_orphan_retained_process(self):
        class Failed(io.BytesIO):
            def write(self, data):
                super().write(data[:5])
                raise OSError("injected partial write")
        session, job, sink = fixture(Failed())
        with self.assertRaises(LedgerIOError): session.start(["mock.exe"])
        result = session.shutdown()
        self.assertTrue(result["ledger"]["poisoned"])
        self.assertEqual(result["ledger"]["committed_rows"], 0)
        self.assertEqual(len(sink.getvalue()), 5)
        self.assertTrue(result["handles_closed"])
        job.terminate.assert_called_once()

    def test_native_cleanup_error_still_attempts_both_close_paths(self):
        for failing in ["terminate", "cleanup_receipt", "close"]:
            with self.subTest(failing=failing):
                session, job, _ = fixture()
                session.start(["mock.exe"])
                getattr(job, failing).side_effect = OSError("injected native failure")
                with self.assertRaises(native.ObserverError): session.shutdown()
                job.close.assert_called_once(); job.close_refs.assert_called_once()

    def test_shutdown_is_idempotent_detached_and_retires_sampling(self):
        session, job, _ = fixture()
        session.start(["mock.exe"])
        first = session.shutdown(); first["native_cleanup"]["job_active_count"] = 999
        self.assertEqual(session.shutdown()["native_cleanup"]["job_active_count"], 0)
        job.close.assert_called_once()
        with self.assertRaises(native.ObserverError): session.sample("late")
        with self.assertRaises(native.ObserverError): session.start(["mock.exe"])

    def test_prelaunch_and_input_refusals_do_not_mutate_native_resources(self):
        session, job, _ = fixture()
        with self.assertRaises(native.ObserverError): session.sample("before")
        job.member.assert_not_called()
        session.start(["mock.exe"])
        with self.assertRaises(native.ObserverError): session.start(["second.exe"])
        for value in ["", None, "x" * 129]:
            with self.assertRaises(ValueError): session.sample(value)
        job.start_suspended.assert_called_once()
        job.member.assert_not_called()
        session.shutdown()

    def test_failed_native_launch_is_cleaned_without_a_fabricated_start_row(self):
        session, job, sink = fixture()
        job.start_suspended.side_effect = native.ObserverError("launch refused")
        with self.assertRaises(native.ObserverError): session.start(["mock.exe"])
        self.assertEqual(sink.getvalue(), b"")
        with self.assertRaises(native.ObserverError): session.start(["forbidden-retry.exe"])
        job.start_suspended.assert_called_once()
        session.shutdown()
        job.close.assert_called_once(); job.close_refs.assert_called_once()


if __name__ == "__main__":
    unittest.main()
