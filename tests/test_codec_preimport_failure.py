"""POST-OUTCOME regressions for the preserved failed codec suite.

These tests were designed after the frozen suite failed. They do not change
its acceptance or authorize another execution. The process branch below runs
only against a mocked Job and saved receipts; no ML, process, or socket is used.
"""
import builtins
from contextlib import ExitStack, contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


ATTEMPTS = []


def forbidden(*args, **kwargs):
    ATTEMPTS.append("forbidden_runtime_action")
    raise AssertionError("post-outcome regression cannot start a process or socket")


@contextmanager
def pure_only():
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "transformers", "numpy"):
            ATTEMPTS.append("forbidden_ML_import:" + name)
            raise AssertionError("post-outcome regression cannot import ML packages")
        return original_import(name, *args, **kwargs)
    with ExitStack() as stack:
        stack.enter_context(mock.patch("builtins.__import__", side_effect=guarded_import))
        for module, name in ((subprocess, "Popen"), (subprocess, "run"),
                             (os, "system"), (os, "startfile"),
                             (socket, "socket"), (socket, "create_connection")):
            stack.enter_context(mock.patch.object(module, name, forbidden, create=True))
        yield


with pure_only():
    from experiments import codec_allocation_probe as probe


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results/codec-allocation"
IMPLEMENTATION_SHA256 = "76034998b53d90fbaf62e0498606ea45f22435b1bbae8925b0e58bd933327ce0"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CodecPreimportPostOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.guard = pure_only()
        self.guard.__enter__()
        self.addCleanup(self.guard.__exit__, None, None, None)
        self.addCleanup(self.assertEqual, ATTEMPTS, [])
        self.preimport = read(RESULTS / "01_off_dense/preimport-ready.json")
        self.original_case = read(RESULTS / "01_off_dense-result.json")
        self.freeze = read(ROOT / "fixtures/codec-allocation/implementation.json")

    def test_saved_preimport_budget_and_count_are_distinct(self):
        guard = self.preimport["provider_guard"]
        self.assertEqual(guard["allowed_local_probe_budget"], 1)
        self.assertEqual(guard["allowed_local_probe_count"], 0)
        self.assertTrue(probe.prior.validate_provider(guard, "preimport", 1))
        self.assertFalse(probe.prior.validate_provider(guard, "preimport", 0))
        changed = copy.deepcopy(guard)
        changed["allowed_local_probe_count"] = 1
        self.assertFalse(probe.prior.validate_provider(changed, "preimport", 1))

    def test_frozen_run_case_calls_zero_budget_and_rejects_before_release(self):
        """Exercise the real frozen branch; replace every OS-facing dependency."""
        original = self.original_case
        launcher = SimpleNamespace(pid=original["launcher"]["pid"],
                                   creation_filetime=original["launcher"]["creation_filetime"])
        actual = SimpleNamespace(pid=self.preimport["pid"],
                                 creation_filetime=original["worker_identity"]["self_receipt"]["creation_filetime"])
        job = mock.Mock(name="in_memory_job_only")
        job.start_suspended.return_value = launcher
        job.authenticate.return_value = (actual, [])
        paths = {key: Path("never-opened") / key for key in ("launcher", "base_python", "native", "conhost")}
        # First clock establishes the original case start. Later clocks put the
        # saved stage safely inside that case without any sleeping or worker.
        clocks = iter([original["started_perf_counter"]])
        def clock():
            return next(clocks, self.preimport["stage_ready_perf_counter"] + 1.0)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(mock.patch.object(probe.obs, "WindowsJob", return_value=job))
            stack.enter_context(mock.patch.object(probe.obs, "WindowsBackend", side_effect=forbidden))
            stack.enter_context(mock.patch.object(probe.time, "perf_counter", side_effect=clock))
            stack.enter_context(mock.patch.object(probe.secrets, "token_hex", return_value=self.preimport["nonce"]))
            stack.enter_context(mock.patch.object(probe.work, "wait_receipt", side_effect=[
                original["worker_identity"]["self_receipt"], self.preimport]))
            stack.enter_context(mock.patch.object(probe.prior, "os_image", return_value={}))
            stack.enter_context(mock.patch.object(probe.dual, "verify_self_executable", return_value={}))
            validation = stack.enter_context(mock.patch.object(probe.prior, "validate_provider",
                wraps=probe.prior.validate_provider))
            inventory = stack.enter_context(mock.patch.object(probe.prior, "inventory", side_effect=forbidden))
            controls = stack.enter_context(mock.patch.object(probe, "parent_control", side_effect=forbidden))
            stack.enter_context(mock.patch.object(probe.prior, "import_packages", side_effect=forbidden))
            stack.enter_context(mock.patch.object(probe.work, "cleanup", return_value={"mock_only": True}))
            result = probe.run_case(paths, Path("not-opened-provider"), Path("not-opened-model"),
                Path("not-opened-fixture"), self.freeze, Path(directory), dict(original["spec"]),
                original["suite_deadline_perf_counter"])
        validation.assert_called_once_with(self.preimport["provider_guard"], "preimport", 0)
        self.assertFalse(result["passed"])
        self.assertEqual(result["error"], "ObserverError: codec held identity/provider/thread gate failed: preimport")
        self.assertEqual(result["stages"], {})
        self.assertEqual(result["controller_controls"], [])
        self.assertEqual(result["worker_controls"], [])
        inventory.assert_not_called()
        controls.assert_not_called()
        job.terminate.assert_called_once_with()
        job.close.assert_called_once_with()
        job.close_refs.assert_called_once_with()

    def test_all_frozen_files_and_implementation_preserved(self):
        self.assertEqual(sha256(ROOT / "fixtures/codec-allocation/implementation.json"), IMPLEMENTATION_SHA256)
        self.assertEqual(sha256(ROOT / "fixtures/codec-allocation/protocol.json"), self.freeze["protocol_sha256"])
        for field in ("new_source_files_sha256", "frozen_dependency_files_sha256", "review_tool_files_sha256"):
            for relative, expected in self.freeze[field].items():
                with self.subTest(path=relative):
                    self.assertEqual(sha256(ROOT / relative), expected)

    def test_original_outcome_remains_no_import_no_release_no_measurement(self):
        self.assertFalse(self.preimport["torch_imported"])
        self.assertFalse(self.preimport["transformers_imported"])
        self.assertFalse(self.original_case["passed"])
        self.assertEqual(self.original_case["controller_controls"], [])
        self.assertNotIn("operation", self.original_case)
        self.assertEqual(self.original_case["error"],
                         "ObserverError: codec held identity/provider/thread gate failed: preimport")
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("transformers", sys.modules)


if __name__ == "__main__":
    unittest.main()
