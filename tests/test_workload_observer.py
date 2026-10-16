"""Mock/unit controls only: never import Torch or launch a real child/job."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments import process_observer as obs
from experiments import workload_observer_probe as probe

MIB = 1024 * 1024
NONCE = "b" * 64


class Clock:
    def __init__(self):
        self.value = 20.0

    def now(self):
        self.value += 0.001
        return self.value

    def sleep(self, duration):
        self.value += duration


def reading(clock=20, resident=300 * MIB, private=400 * MIB):
    return {"pid": 2000, "creation_filetime": 20, "perf_counter": clock,
        "native_cpu_seconds": clock * 2, "memory": {"resident_bytes": resident,
            "private_bytes": private, "peak_resident_bytes": resident}}


def workload_receipt():
    return {"pid": 2000, "torch_version": "2.9.1+cpu", "intraop_threads": 2, "interop_threads": 2,
        "native_thread_counts": {"before_import": 1, "before_operation": 3, "after_operation": 3},
        "operation": {"forward_calls": 1, "backward_calls": 1, "optimizer_steps": 1, "loss": 1.0,
            "gradient_finite": True, "parameters_finite": True, "parameter_changed": True,
            "device": "cpu", "dtype": "torch.float32", "matrix_dimension": 1024,
            "started_perf_counter": 1.0, "completed_perf_counter": 2.0, "wall_seconds": 1.0}}


class ContractTests(unittest.TestCase):
    def test_fixed_protocol_config_sources_cases_and_dependencies_match(self):
        protocol = obs.read_small(probe.ROOT / "fixtures/workload-observer/protocol.json")
        self.assertEqual(protocol["config"], probe.CONFIG)
        self.assertEqual(protocol["source_paths"], list(probe.SOURCE_PATHS))
        self.assertEqual(protocol["frozen_dependency_paths"], list(probe.DEPENDENCY_PATHS))
        self.assertEqual([(c["id"], c["mode"], c["manual_allocation_bytes"]) for c in protocol["cases_in_order"]], list(probe.CASES))

    def test_finite_single_update_cpu_and_thread_configuration_are_required(self):
        self.assertTrue(probe.validate_workload(workload_receipt()))
        patches = [("torch_version", "2.0"), ("intraop_threads", 1), ("interop_threads", 1),
            ("native_thread_counts", {"before_import": 1})]
        for key, value in patches:
            with self.subTest(key=key):
                receipt = workload_receipt()
                receipt[key] = value
                self.assertFalse(probe.validate_workload(receipt))
        for key, value in (("loss", float("nan")), ("loss", float("inf")), ("optimizer_steps", 2),
                ("backward_calls", True), ("gradient_finite", False), ("parameter_changed", False),
                ("device", "cuda:0"), ("completed_perf_counter", 0.5), ("wall_seconds", 0.9)):
            with self.subTest(key=key, value=value):
                receipt = workload_receipt()
                receipt["operation"][key] = value
                self.assertFalse(probe.validate_workload(receipt))

    def test_deadlines_clamp_stage_case_and_suite(self):
        with mock.patch.object(probe.time, "perf_counter", return_value=10.0):
            self.assertEqual(probe.deadline(5, 20, 30), 15)
            self.assertEqual(probe.deadline(5, 12, 30), 12)
            self.assertEqual(probe.deadline(5, 12, 11), 11)

    def test_cleanup_clamps_remaining_budget_and_never_calls_after_expiry(self):
        job = mock.Mock()
        with mock.patch.object(probe.time, "perf_counter", return_value=10.0):
            probe.cleanup(job, 12, 30)
            job.cleanup_receipt.assert_called_with(2, require_zero=True)
            with self.assertRaisesRegex(obs.ObserverError, "remaining budget"):
                probe.cleanup(job, 9, 30)

    def test_sampling_counts_boundaries_and_cpu_progress(self):
        samples = [reading(clock=1), reading(clock=1.25), reading(clock=1.5)]
        summary = probe.sampling_summary(samples, 0.9, 1.7)
        self.assertEqual(summary["samples_count"], 3)
        self.assertEqual(summary["maximum_gap_including_boundaries_seconds"], 0.25)
        self.assertEqual(summary["native_cpu_delta_seconds"], 1)
        self.assertTrue(summary["gap_gate_passed"])
        self.assertFalse(probe.sampling_summary(samples, 0, 2)["gap_gate_passed"])
        self.assertFalse(probe.sampling_summary([], 0, 1)["gap_gate_passed"])

    def test_wait_deadline_does_not_block_and_rejects_wrong_nonce(self):
        clock = Clock()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(probe.time, "perf_counter", side_effect=clock.now), mock.patch.object(probe.time, "sleep", side_effect=clock.sleep):
            with self.assertRaisesRegex(obs.ObserverError, "deadline"):
                probe.wait_receipt(tmp, "absent.json", clock.value + 0.1, NONCE)
            obs.write_new(Path(tmp) / "ready.json", {"nonce": "a" * 64, "role": "worker", "pid": 2000})
            with self.assertRaisesRegex(obs.ObserverError, "nonce"):
                probe.wait_receipt(tmp, "ready.json", clock.value + 1, NONCE)

    def test_expected_exit_requires_exact_code(self):
        ref = SimpleNamespace(alive=lambda: False, exit_code=lambda: 36)
        with self.assertRaisesRegex(obs.ObserverError, "unexpected exit"):
            probe.require_exit(ref, 37, probe.time.perf_counter() + 1)


class NativeMockTests(unittest.TestCase):
    def test_native_identity_requires_os_image_parent_creation_and_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            native_path = Path(tmp) / "cmd.exe"
            native_path.write_bytes(b"mock native binary; never executed")
            native = SimpleNamespace(pid=3000, creation_filetime=30, handle=300)
            actual = SimpleNamespace(pid=2000, creation_filetime=20)
            image_value = [str(native_path)]

            def image_query(handle, flags, buffer, size):
                buffer.value = image_value[0]
                size._obj.value = len(buffer.value)
                return True

            backend = SimpleNamespace(snapshot=lambda: {3000: 2000},
                k=SimpleNamespace(QueryFullProcessImageNameW=mock.Mock(side_effect=image_query)),
                checked=lambda result, action: result if result else (_ for _ in ()).throw(obs.ObserverError(action)))
            job = SimpleNamespace(retain=lambda pid: native, member=mock.Mock(), backend=backend)
            receipt = {"pid": 2000, "native_pid": 3000, "command_arguments": list(probe.NATIVE_ARGUMENTS),
                "close_fds": True, "stdin_anonymous_pipe": True, "shell": False, "creationflags": 0x08000000,
                "stdout_devnull": True, "stderr_devnull": True}
            returned, evidence = probe.verify_native_child(job, actual, receipt, native_path, obs.sha256_file(native_path))
            self.assertIs(returned, native)
            self.assertTrue(evidence["no_native_self_report"])
            self.assertEqual(evidence["os_image"]["basename"], "cmd.exe")
            for key, value in (("pid", 1000), ("close_fds", False), ("stdin_anonymous_pipe", False), ("command_arguments", ["bad"]),
                    ("shell", True), ("creationflags", 0), ("stdout_devnull", False), ("stderr_devnull", False)):
                with self.subTest(key=key), self.assertRaises(obs.ObserverError):
                    probe.verify_native_child(job, actual, {**receipt, **{key: value}}, native_path, obs.sha256_file(native_path))
            backend.snapshot = lambda: {3000: 999}
            with self.assertRaisesRegex(obs.ObserverError, "parent"):
                probe.verify_native_child(job, actual, receipt, native_path, obs.sha256_file(native_path))
            backend.snapshot = lambda: {3000: 2000}
            image_value[0] = str(Path(tmp) / "other.exe")
            with self.assertRaisesRegex(obs.ObserverError, "image"):
                probe.verify_native_child(job, actual, receipt, native_path, obs.sha256_file(native_path))

    def test_native_thread_count_uses_native_snapshot_and_closes_it(self):
        def first(handle, pointer):
            pointer._obj.th32ProcessID = 2000
            pointer._obj.cntThreads = 7
            return True

        backend = SimpleNamespace(k=SimpleNamespace(CreateToolhelp32Snapshot=lambda *a: 99,
            Process32FirstW=first), checked=lambda value, action: value, close=mock.Mock())
        self.assertEqual(probe.native_thread_count(backend, 2000), 7)
        backend.close.assert_called_once_with(99)

    def test_native_process_cpu_is_creation_bound(self):
        def times(handle, created, exited, kernel, user):
            created._obj.low = 20
            kernel._obj.low, user._obj.low = 2_500_000, 7_500_000
            return True

        backend = SimpleNamespace(k=SimpleNamespace(GetProcessTimes=times), checked=lambda value, action: value)
        ref = SimpleNamespace(handle=200, creation_filetime=20)
        self.assertEqual(probe.native_process_cpu(backend, ref), 1.0)
        ref.creation_filetime = 21
        with self.assertRaisesRegex(obs.ObserverError, "creation"):
            probe.native_process_cpu(backend, ref)

    def test_live_receipts_are_recorded_only_after_native_member_checks(self):
        job = SimpleNamespace(member=mock.Mock())
        actual = SimpleNamespace(pid=2000, creation_filetime=20)
        native = SimpleNamespace(pid=3000, creation_filetime=30)
        records = probe.live_member_receipts(job, actual, native)
        self.assertEqual([r["pid"] for r in records], [2000, 3000])
        self.assertEqual(job.member.call_count, 2)
        job.member.side_effect = obs.ObserverError("already exited")
        with self.assertRaisesRegex(obs.ObserverError, "exited"):
            probe.live_member_receipts(job, actual, native)


class WorkerIsolationTests(unittest.TestCase):
    def test_handshake_release_precedes_native_and_torch(self):
        backend = mock.Mock()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(obs, "WindowsBackend", return_value=backend), \
            mock.patch.object(probe.base, "publish_identity") as identity, mock.patch.object(probe, "worker_control", side_effect=obs.ObserverError("deliberate no release")), \
            mock.patch.object(probe.subprocess, "Popen") as popen, mock.patch.object(probe, "prepare_workload") as prepare:
            with self.assertRaisesRegex(obs.ObserverError, "no release"):
                probe.worker(Path(tmp), NONCE, Path(tmp) / "cmd.exe", "healthy", 32 * MIB, 100, 100)
            identity.assert_called_once()
            popen.assert_not_called()
            prepare.assert_not_called()

    def test_prehandshake_control_exits_without_backend_import_or_descendant(self):
        with mock.patch.object(probe.os, "_exit", side_effect=SystemExit(37)) as hard_exit, \
            mock.patch.object(obs, "WindowsBackend") as backend, mock.patch.object(probe, "prepare_workload") as prepare:
            with self.assertRaises(SystemExit):
                probe.worker(Path("unused"), NONCE, Path("cmd.exe"), "prehandshake_fail", 0, 100, 100)
            hard_exit.assert_called_once_with(37)
            backend.assert_not_called()
            prepare.assert_not_called()

    def test_injected_import_failure_does_not_enter_torch_workload(self):
        backend, child = mock.Mock(), mock.Mock()
        child.pid, child.stdin.closed = 3000, False
        missing = "workload_observer_missing_dependency_" + NONCE
        error = ModuleNotFoundError("injected", name=missing)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(obs, "WindowsBackend", return_value=backend), \
            mock.patch.object(probe.base, "publish_identity"), mock.patch.object(probe, "worker_control"), \
            mock.patch.object(probe.subprocess, "Popen", return_value=child), mock.patch.object(probe.importlib, "import_module", side_effect=error), \
            mock.patch.object(probe, "prepare_workload") as prepare, mock.patch.object(probe.os, "_exit", side_effect=SystemExit(38)) as hard_exit:
            with self.assertRaises(SystemExit):
                probe.worker(Path(tmp), NONCE, Path(tmp) / "cmd.exe", "import_fail", 0, 100, 100)
            hard_exit.assert_called_once_with(38)
            prepare.assert_not_called()
            failure = obs.read_small(Path(tmp) / "expected-import-failure.json")
            self.assertEqual(failure["missing_module"], missing)
            self.assertEqual(failure["optimizer_steps"], 0)


class CaseDriverTests(unittest.TestCase):
    def execute(self, spec, *, bad_workload=False, bad_import=False, no_cpu_progress=False,
                bad_allocation=False, native_exited=False, cleanup_failure=False, late_close=False):
        clock, job = Clock(), mock.Mock()
        job.handle = 99
        launcher = SimpleNamespace(pid=1000, creation_filetime=10)
        actual = SimpleNamespace(pid=2000, creation_filetime=20)
        native = SimpleNamespace(pid=3000, creation_filetime=30)
        job.start_suspended.return_value = launcher
        job.authenticate.return_value = (actual, [{"pid": 2000}, {"pid": 1000}])
        if late_close:
            job.close.side_effect = lambda: clock.sleep(21)

        def member(ref):
            if ref is native and native_exited:
                raise obs.ObserverError("native descendant not live")
            return True

        job.member.side_effect = member
        if cleanup_failure:
            job.cleanup_receipt.side_effect = obs.ObserverError("mock cleanup error")
        else:
            job.cleanup_receipt.return_value = {"all_retained_handles_exited": True, "job_active_count": 0,
                "exit_codes": [{"pid": 1000, "creation_filetime": 10, "exit_code": 0},
                    {"pid": 2000, "creation_filetime": 20, "exit_code": 0}, {"pid": 3000, "creation_filetime": 30, "exit_code": 0}]}
        busy_start = [None]

        def wire(directory, name, until, nonce, role="worker", poll=None):
            receipt = {"pid": 2000, "nonce": nonce, "role": role}
            if name == "workload-ready.json":
                return {**receipt, **workload_receipt(), **({"intraop_threads": 1} if bad_workload else {})}
            if name == "expected-import-failure.json":
                return {**receipt, "missing_module": "workload_observer_missing_dependency_" + nonce,
                    "exception_type": "OtherError" if bad_import else "ModuleNotFoundError",
                    "torch_imported": False, "optimizer_steps": 0, "expected_exit_code": 38}
            if name == "worker-completed.json":
                return {**receipt, "native_exit_code": 0, "native_released_nonempty_line": True, "optimizer_steps": 1}
            if name == "busy-ready.json":
                busy_start[0] = clock.now()
                return {**receipt, "perf_counter": busy_start[0], "native_thread_count": 3,
                    "extra_backward_calls": 0, "extra_optimizer_steps": 0}
            if name == "busy-first-operation.json":
                return {**receipt, "completed_perf_counter": clock.now(), "matmul_iterations_completed": 1,
                    "extra_backward_calls": 0, "extra_optimizer_steps": 0}
            return receipt

        def sample(j, ref, samples):
            count = spec[2] if spec[1] == "private_cap" else 0
            value = reading(clock=clock.now(), resident=300 * MIB + count, private=400 * MIB + count)
            if no_cpu_progress:
                value["native_cpu_seconds"] = 0
            samples.append(value)
            return value

        def bracket(j, ref, directory, stage, nonce, report, case_deadline, suite_deadline):
            count = spec[2] if stage == "allocated" and not bad_allocation else 0
            parent = reading(clock=clock.now(), resident=300 * MIB + count, private=400 * MIB + count)
            result = {"parent": parent, "self_before": {**parent, "perf_counter": parent["perf_counter"] - .001},
                "self_after": {**parent, "perf_counter": parent["perf_counter"] + .001}, "comparison": {"passed": True}}
            report["samples"].append(parent)
            report.setdefault("memory_brackets", {})[stage] = result
            return result

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(obs, "WindowsJob", return_value=job), \
            mock.patch.object(probe, "wait_receipt", side_effect=wire), mock.patch.object(probe, "verify_native_child", return_value=(native, {"os_identity": {"pid": 3000}, "no_native_self_report": True})), \
            mock.patch.object(probe, "read_bracket", side_effect=bracket), mock.patch.object(probe, "parent_sample", side_effect=sample), \
            mock.patch.object(probe.base, "control"), mock.patch.object(probe, "require_exit", side_effect=lambda ref, code, until: code), \
            mock.patch.object(probe.time, "perf_counter", side_effect=clock.now), mock.patch.object(probe.time, "sleep", side_effect=clock.sleep):
            report = probe.run_case(spec, Path(tmp) / "python.exe", Path(tmp) / "cmd.exe", "a" * 64, Path(tmp), clock.value + 120)
            self.assertTrue((Path(tmp) / spec[0] / "case-report.json").exists())
        return report, job

    def test_healthy32_and_healthy64_never_invoke_termination(self):
        for spec in probe.CASES[:2]:
            report, job = self.execute(spec)
            self.assertTrue(report["passed"], report)
            self.assertEqual(report["outcome"], "normal_completion")
            job.terminate.assert_not_called()
            command = job.start_suspended.call_args.args[0]
            self.assertIn("--case-deadline", command)
            self.assertIn("--suite-deadline", command)

    def test_timeout_requires_native_cpu_progress_and_samples_correct_pid(self):
        report, job = self.execute(probe.CASES[2])
        self.assertTrue(report["passed"], report)
        self.assertGreaterEqual(report["busy_sampling"]["wall_seconds"], 1.5)
        self.assertGreaterEqual(report["busy_sampling"]["native_cpu_delta_seconds"], .25)
        self.assertEqual({s["pid"] for s in report["samples"]}, {2000})
        self.assertEqual([r["pid"] for r in report["pretermination_live_members"]], [2000, 3000])
        self.assertGreaterEqual(report["termination_request_started_perf_counter"], report["busy_deadline_perf_counter"])
        job.terminate.assert_called_once()

    def test_busy_cap_uses_postimport_baseline_and_after_first_matmul(self):
        report, job = self.execute(probe.CASES[3])
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["actual_interpreter_private_limit_bytes"], 448 * MIB)
        self.assertEqual(report["outcome"], "memory_private_limit")
        self.assertLessEqual(report["allocation_ready_to_termination_seconds"], 1)
        self.assertGreaterEqual(report["termination_request_started_perf_counter"], report["busy_first_operation"]["completed_perf_counter"])
        job.terminate.assert_called_once()

    def test_prehandshake_failure_keeps_actual_identity_unavailable(self):
        report, job = self.execute(probe.CASES[4])
        self.assertTrue(report["passed"], report)
        self.assertTrue(report["prehandshake_control"]["actual_interpreter_identity_unavailable"])
        self.assertNotIn("worker_identity", report)
        self.assertEqual(report["samples"], [])
        job.authenticate.assert_not_called()

    def test_exact_import_failure_is_expected_control_and_cleans_job(self):
        report, job = self.execute(probe.CASES[5])
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["expected_worker_exit_code"], 38)
        self.assertNotIn("workload_ready", report)
        job.terminate.assert_called_once()

    def test_unrelated_import_error_fails_instead_of_expected_success(self):
        report, job = self.execute(probe.CASES[5], bad_import=True)
        self.assertFalse(report["passed"])
        self.assertIn("did not match", report["error"])
        self.assertIn("failure_cleanup", report)

    def test_idle_timeout_control_is_not_accepted_as_busy(self):
        report, job = self.execute(probe.CASES[2], no_cpu_progress=True)
        self.assertFalse(report["passed"])
        self.assertIn("CPU progress", report["error"])

    def test_bad_workload_allocation_or_exited_native_fail_without_fallback(self):
        for options in ({"bad_workload": True}, {"bad_allocation": True}, {"native_exited": True}):
            spec = probe.CASES[2] if "native_exited" in options else probe.CASES[0]
            with self.subTest(options=options):
                report, job = self.execute(spec, **options)
                self.assertFalse(report["passed"])
                self.assertIn("error", report)
                job.terminate.assert_called_once()

    def test_cleanup_failure_does_not_mask_original_workload_failure(self):
        report, job = self.execute(probe.CASES[0], bad_workload=True, cleanup_failure=True)
        self.assertFalse(report["passed"])
        self.assertIn("workload/thread", report["error"])
        self.assertIn("cleanup error", report["cleanup_error"])
        job.close.assert_called_once()
        job.close_refs.assert_called_once()

    def test_slow_final_handle_close_cannot_leave_case_passed(self):
        report, job = self.execute(probe.CASES[0], late_close=True)
        self.assertFalse(report["passed"])
        self.assertTrue(report["final_wall_budget_exceeded"])
        self.assertGreater(report["wall_seconds"], 20)


def freeze_fixture(directory):
    root = Path(directory)
    for name in probe.SOURCE_PATHS + probe.DEPENDENCY_PATHS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock frozen file " + name, encoding="utf-8")
    python, native = root / "python.exe", root / "cmd.exe"
    python.write_bytes(b"mock launcher never executed")
    native.write_bytes(b"mock native never executed")
    protocol_path, freeze_path = root / "protocol.json", root / "implementation.json"
    protocol = {"predeclared_at": "2026-01-01T00:00:00+00:00", "config": probe.CONFIG,
        "source_paths": list(probe.SOURCE_PATHS), "frozen_dependency_paths": list(probe.DEPENDENCY_PATHS),
        "cases_in_order": [{"id": a, "mode": b, "manual_allocation_bytes": c} for a, b, c in probe.CASES]}
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    freeze = {"frozen_at": "2026-01-02T00:00:00+00:00", "protocol_sha256": obs.sha256_file(protocol_path),
        "new_source_files_sha256": {p: obs.sha256_file(root / p) for p in probe.SOURCE_PATHS},
        "frozen_dependency_files_sha256": {p: obs.sha256_file(root / p) for p in probe.DEPENDENCY_PATHS},
        "python_executable_sha256": obs.sha256_file(python), "native_executable_sha256": obs.sha256_file(native)}
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    return root, python, native, protocol_path, freeze_path, freeze


class FreezeTests(unittest.TestCase):
    def test_hashes_cover_new_sources_frozen_dependencies_and_both_executables(self):
        for tamper in (None, "source", "dependency", "python", "native", "protocol", "chronology"):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as tmp:
                root, python, native, protocol, freeze_path, freeze = freeze_fixture(tmp)
                if tamper in ("source", "dependency"):
                    path = (probe.SOURCE_PATHS if tamper == "source" else probe.DEPENDENCY_PATHS)[0]
                    (root / path).write_text("tampered", encoding="utf-8")
                elif tamper in ("python", "native"):
                    (python if tamper == "python" else native).write_bytes(b"tampered")
                elif tamper == "protocol":
                    protocol.write_text(protocol.read_text(encoding="utf-8") + " ", encoding="utf-8")
                elif tamper == "chronology":
                    freeze["frozen_at"] = "2025-01-01T00:00:00+00:00"
                freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
                with mock.patch.object(probe, "ROOT", root):
                    if tamper is None:
                        self.assertTrue(probe.validate_freeze(protocol, freeze_path, python, native))
                    else:
                        with self.assertRaises(obs.ObserverError):
                            probe.validate_freeze(protocol, freeze_path, python, native)

    def test_suite_keeps_all_six_results_with_failure_and_never_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, python, native, protocol, freeze, _ = freeze_fixture(tmp)
            cases = [{"id": spec[0], "passed": i != 3} for i, spec in enumerate(probe.CASES)]
            with mock.patch.object(probe, "ROOT", root), mock.patch.object(probe, "os", SimpleNamespace(name="nt")), \
                mock.patch.object(probe, "run_case", side_effect=cases) as run:
                report = probe.acceptance(python, native, protocol, freeze, root / "output")
                self.assertFalse(report["passed"])
                self.assertEqual(report["cases"], cases)
                self.assertEqual(run.call_count, 6)
            with self.assertRaises(FileExistsError):
                probe.acceptance(python, native, protocol, freeze, root / "output")

    def test_unsupported_platform_is_explicit_failure_with_zero_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, python, native, protocol, freeze, _ = freeze_fixture(tmp)
            with mock.patch.object(probe, "ROOT", root), mock.patch.object(probe, "os", SimpleNamespace(name="posix")), mock.patch.object(probe, "run_case") as run:
                report = probe.acceptance(python, native, protocol, freeze, root / "output")
                self.assertFalse(report["passed"])
                self.assertIn("UnsupportedPlatform", report["error"])
                self.assertEqual(report["cases"], [])
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
