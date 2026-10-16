"""Pure unit/mocked engineering checks. Never start any real child or job."""
import ctypes
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments import process_observer as obs
from experiments import process_observer_probe as probe

NONCE = "a" * 64
MIB = 1024 * 1024


def reading(pid=2000, created=20, resident=32 * MIB, private=16 * MIB, clock=1.0):
    return {"pid": pid, "creation_filetime": created, "perf_counter": clock,
        "memory": {"resident_bytes": resident, "private_bytes": private, "peak_resident_bytes": resident}}


class FakeBackend:
    """ctypes argument-aware kernel mock; no Windows API/DLL invocation."""
    def __init__(self):
        self.events = []
        self.assignment = True
        self.resume_result = 1
        self.living = set()
        self.members = {100, 200, 300, 400}
        self.created = {100: 10, 200: 20, 300: 30, 400: 40}
        self.pids = {100: 1000, 200: 2000, 300: 3000, 400: 4000}
        self.parents = {1000: 900, 2000: 1000, 3000: 2000, 4000: 3000}
        self.close_failures = set()
        self.k = SimpleNamespace(CreateJobObjectW=self.create_job, SetInformationJobObject=self.set_limit,
            CreateProcessW=self.create_process, AssignProcessToJobObject=self.assign,
            GetProcessId=lambda h: self.pids.get(h, 0), ResumeThread=self.resume,
            WaitForSingleObject=lambda h, ms: 0x102 if h in self.living else 0,
            TerminateProcess=self.terminate_process, TerminateJobObject=self.terminate_job,
            OpenProcess=self.open_process, IsProcessInJob=self.is_member,
            QueryInformationJobObject=self.accounting, GetExitCodeProcess=self.exit_code)

    def create_job(self, security, name):
        self.events.append(("create_job", security, name))
        return 99

    def set_limit(self, job, kind, pointer, size):
        self.events.append(("set_limit", pointer._obj.BasicLimitInformation.LimitFlags))
        return True

    def create_process(self, executable, line, process_sa, thread_sa, inherit, flags, environment, cwd, startup, info):
        self.events.append(("create_process", inherit, flags, executable))
        info._obj.hProcess, info._obj.hThread = 100, 101
        info._obj.dwProcessId, info._obj.dwThreadId = 1000, 1001
        self.living.add(100)
        return True

    def assign(self, job, process):
        self.events.append(("assign", job, process))
        return self.assignment

    def resume(self, thread):
        self.events.append(("resume", thread))
        return self.resume_result

    def checked(self, value, action):
        if not value:
            raise obs.ObserverError(action + " mocked failure")
        return value

    def creation(self, handle):
        return self.created[handle]

    def memory(self, handle):
        return {"resident_bytes": handle * 4096, "private_bytes": handle * 8192,
            "peak_resident_bytes": handle * 4096}

    def close(self, handle):
        self.events.append(("close", handle))
        if handle in self.close_failures:
            raise obs.ObserverError("deliberate close failure")

    def terminate_process(self, handle, code):
        self.events.append(("terminate_process", handle))
        self.living.discard(handle)
        return True

    def terminate_job(self, handle, code):
        self.events.append(("terminate_job", handle))
        self.living.clear()
        return True

    def open_process(self, access, inherit, pid):
        self.events.append(("open_process", pid, inherit))
        return next((h for h, p in self.pids.items() if p == pid), 0)

    def is_member(self, handle, job, result):
        result._obj.value = handle in self.members
        return True

    def snapshot(self):
        return dict(self.parents)

    def accounting(self, handle, kind, pointer, size, returned):
        pointer._obj.ActiveProcesses = len(self.living)
        return True

    def exit_code(self, handle, code):
        code._obj.value = 0
        return True


class Clock:
    def __init__(self):
        self.value = 10.0

    def now(self):
        self.value += 0.001
        return self.value

    def sleep(self, duration):
        self.value += duration


class WireTests(unittest.TestCase):
    def test_nonce_role_and_pid_are_required(self):
        valid = {"nonce": NONCE, "role": "worker", "pid": 123}
        self.assertIs(obs.validate_message(valid, NONCE, "worker"), valid)
        for patch in ({"nonce": "b" * 64}, {"role": "descendant"}, {"pid": True}, {"pid": 0}):
            with self.subTest(patch=patch), self.assertRaises(obs.ObserverError):
                obs.validate_message({**valid, **patch}, NONCE, "worker")
        for invalid in (None, [], 12):
            with self.assertRaisesRegex(obs.ObserverError, "object"):
                obs.validate_message(invalid, NONCE, "worker")
        for invalid in ("A" * 64, "abc", "a" * 63, 3):
            with self.assertRaises(obs.ObserverError):
                obs.validate_nonce(invalid)

    def test_json_publication_is_one_use_and_read_bound_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "message.json"
            obs.write_new(path, {"a": 1})
            original = path.read_bytes()
            with self.assertRaises(FileExistsError):
                obs.write_new(path, {"a": 2})
            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(path.with_name("message.json.pending").exists())
            with self.assertRaisesRegex(obs.ObserverError, "size"):
                obs.read_small(path, maximum=1)
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(obs.ObserverError, "object"):
                obs.read_small(path)

    def test_wait_has_deadline_and_calls_poll_without_real_sleep(self):
        clock, polls = Clock(), []
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(obs.ObserverError, "deadline"):
            probe.wait_json(Path(tmp) / "absent.json", clock.value + 0.1, NONCE, "worker",
                poll=lambda: polls.append(1), clock=clock.now, sleep=clock.sleep)
        self.assertGreater(len(polls), 0)
        self.assertLess(len(polls), 10)

    def test_wait_rejects_wrong_nonce_and_child_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ready.json"
            obs.write_new(path, {"nonce": "b" * 64, "role": "worker", "pid": 1})
            with self.assertRaisesRegex(obs.ObserverError, "nonce"):
                probe.wait_json(path, probe.time.perf_counter() + 10, NONCE, "worker")
            obs.write_new(Path(tmp) / "worker-failure.json", {"error": "deliberate"})
            with self.assertRaisesRegex(obs.ObserverError, "deliberate"):
                probe.wait_json(Path(tmp) / "other.json", probe.time.perf_counter() + 10, NONCE, "worker")

    def test_public_error_removes_local_paths(self):
        self.assertNotIn(str(probe.ROOT), probe.public_error(ValueError(str(probe.ROOT / "private"))))


class BracketTests(unittest.TestCase):
    def test_correct_process_bracket_matches_resident_and_private(self):
        before, parent, after = reading(clock=1), reading(clock=2), reading(clock=3)
        self.assertTrue(obs.compare_memory_bracket(before, parent, after, 0)["passed"])
        parent["memory"]["resident_bytes"] += 4 * MIB
        self.assertTrue(obs.compare_memory_bracket(before, parent, after, 4 * MIB)["passed"])
        parent["memory"]["resident_bytes"] += 1
        self.assertFalse(obs.compare_memory_bracket(before, parent, after, 4 * MIB)["passed"])

    def test_launcher_wrong_creation_and_out_of_order_are_not_salvaged(self):
        for patch in ({"pid": 1000}, {"creation_filetime": 21}, {"perf_counter": 4.0}):
            with self.subTest(patch=patch):
                self.assertFalse(obs.compare_memory_bracket(reading(clock=1), {**reading(clock=2), **patch}, reading(clock=3), 4 * MIB)["passed"])

    def test_private_mismatch_is_a_failed_gate(self):
        parent = reading(clock=2)
        parent["memory"]["private_bytes"] += 4 * MIB + 1
        result = obs.compare_memory_bracket(reading(clock=1), parent, reading(clock=3), 4 * MIB)
        self.assertFalse(result["private_within_tolerance"])
        self.assertFalse(result["passed"])

    def test_invalid_memory_values_and_tolerance_are_rejected(self):
        for value in (True, -1, 3.5):
            bad = reading(clock=2)
            bad["memory"]["private_bytes"] = value
            with self.assertRaises(obs.ObserverError):
                obs.compare_memory_bracket(reading(clock=1), bad, reading(clock=3), 0)
        with self.assertRaises(obs.ObserverError):
            obs.compare_memory_bracket(reading(), reading(), reading(), -1)

    def test_cap_is_strictly_above_threshold(self):
        self.assertFalse(obs.memory_limit_crossed(reading(private=100), 100))
        self.assertTrue(obs.memory_limit_crossed(reading(private=101), 100))

    def test_allocation_requires_both_resident_and_private_increase(self):
        base = {"parent": reading()}
        allocated = {"parent": reading(resident=64 * MIB, private=48 * MIB)}
        self.assertTrue(probe.check_allocation(base, allocated, 32 * MIB)["passed"])
        allocated["parent"]["memory"]["private_bytes"] = 16 * MIB
        self.assertFalse(probe.check_allocation(base, allocated, 32 * MIB)["passed"])


class JobMockTests(unittest.TestCase):
    def test_suspended_assign_resume_order_and_noninherited_handle(self):
        backend = FakeBackend()
        job = obs.WindowsJob(backend)
        ref = job.start_suspended(["python.exe", "-S", "probe.py"])
        names = [e[0] for e in backend.events]
        self.assertLess(names.index("create_process"), names.index("assign"))
        self.assertLess(names.index("assign"), names.index("resume"))
        self.assertIn(("set_limit", 0x2000), backend.events)
        launch = next(e for e in backend.events if e[0] == "create_process")
        self.assertFalse(launch[1])
        self.assertEqual(launch[2], 0x08000004)
        self.assertEqual(ref.pid, 1000)
        self.assertIn(("close", 101), backend.events)
        self.assertNotIn(("close", 100), backend.events)

    def test_assignment_failure_never_resumes_and_kills_suspended_launcher(self):
        backend = FakeBackend()
        backend.assignment = False
        job = obs.WindowsJob(backend)
        with self.assertRaisesRegex(obs.ObserverError, "AssignProcess"):
            job.start_suspended(["python.exe"])
        self.assertFalse(any(e[0] == "resume" for e in backend.events))
        self.assertIn(("terminate_process", 100), backend.events)
        self.assertIn(("close", 100), backend.events)
        self.assertIn(("close", 101), backend.events)

    def test_resume_unexpected_count_uses_whole_job_cleanup(self):
        for count in (0, 2, 0xFFFFFFFF):
            backend = FakeBackend()
            backend.resume_result = count
            job = obs.WindowsJob(backend)
            with self.assertRaisesRegex(obs.ObserverError, "ResumeThread"):
                job.start_suspended(["python.exe"])
            self.assertIn(("terminate_job", 99), backend.events)
            self.assertIn(("close", 101), backend.events)

    def test_launch_cleanup_failures_attempt_wait_and_both_handles_preserve_original(self):
        backend = FakeBackend()
        backend.assignment = False
        backend.k.TerminateProcess = mock.Mock(side_effect=obs.ObserverError("mock terminate failed"))
        backend.close_failures.update((100, 101))
        job = obs.WindowsJob(backend)
        with self.assertRaises(obs.ObserverError) as caught:
            job.start_suspended(["python.exe"])
        text = str(caught.exception)
        self.assertIn("AssignProcessToJobObject", text)
        self.assertIn("mock terminate failed", text)
        self.assertIn("cleanup wait", text)
        self.assertIn("process handle close", text)
        self.assertIn("thread handle close", text)
        self.assertIn(("close", 100), backend.events)
        self.assertIn(("close", 101), backend.events)
        self.assertIsNotNone(caught.exception.__cause__)

    def test_nonce_identity_ancestry_and_live_membership_are_all_required(self):
        backend = FakeBackend()
        job = obs.WindowsJob(backend)
        launcher = job.start_suspended(["python.exe"])
        backend.living.add(200)
        message = {"nonce": NONCE, "role": "worker", "pid": 2000, "creation_filetime": 20, "parent_pid": 1000}
        actual, chain = job.authenticate(message, NONCE, "worker", launcher)
        self.assertEqual([p["pid"] for p in chain], [2000, 1000])
        self.assertEqual(actual.reading()["memory"]["resident_bytes"], 200 * 4096)
        self.assertNotEqual(actual.pid, launcher.pid)
        for patch in ({"nonce": "b" * 64}, {"creation_filetime": 21}, {"parent_pid": 123}):
            with self.subTest(patch=patch), self.assertRaises(obs.ObserverError):
                job.authenticate({**message, **patch}, NONCE, "worker", launcher)
        backend.members.remove(200)
        with self.assertRaisesRegex(obs.ObserverError, "live member"):
            job.authenticate(message, NONCE, "worker", launcher)

    def test_process_creation_mismatch_closes_rejected_handle(self):
        backend = FakeBackend()
        job = obs.WindowsJob(backend)
        with self.assertRaisesRegex(obs.ObserverError, "creation"):
            job.retain(2000, expected_creation=21)
        self.assertIn(("close", 200), backend.events)
        self.assertNotIn(2000, job.refs)

    def test_ancestry_creation_order_and_cycles_are_rejected(self):
        backend = FakeBackend()
        job = obs.WindowsJob(backend)
        launcher = job.start_suspended(["python.exe"])
        backend.living.add(200)
        backend.created[100] = 30
        # Retained launcher has earlier recorded creation; live native mismatch
        # is separately rejected by reading(), while this tests parent order.
        launcher.creation_filetime = 30
        message = {"nonce": NONCE, "role": "worker", "pid": 2000, "creation_filetime": 20, "parent_pid": 1000}
        with self.assertRaisesRegex(obs.ObserverError, "creation order"):
            job.authenticate(message, NONCE, "worker", launcher)

    def test_exited_handle_cannot_produce_live_memory(self):
        backend = FakeBackend()
        ref = obs.ProcessRef(backend, 200)
        with self.assertRaisesRegex(obs.ObserverError, "exited"):
            ref.reading()

    def test_job_close_is_distinct_from_terminate_and_accounting_after_close_rejected(self):
        backend = FakeBackend()
        job = obs.WindowsJob(backend)
        job.close()
        job.close()
        self.assertEqual(backend.events.count(("close", 99)), 1)
        self.assertFalse(any(e[0] == "terminate_job" for e in backend.events))
        with self.assertRaisesRegex(obs.ObserverError, "after close"):
            job.active_count()

    def test_cleanup_checks_job_empty_as_well_as_retained_exits(self):
        backend = FakeBackend()
        job = obs.WindowsJob(backend)
        job.retain(2000)
        backend.living.add(400)  # Unretained, but still counted in job accounting.
        clock = Clock()
        with self.assertRaisesRegex(obs.ObserverError, "cleanup deadline"):
            job.cleanup_receipt(0.1, require_zero=True, sleep=clock.sleep, clock=clock.now)
        backend.living.clear()
        result = job.cleanup_receipt(0.1, require_zero=True, sleep=clock.sleep, clock=clock.now)
        self.assertEqual(result["job_active_count"], 0)
        self.assertTrue(result["all_retained_handles_exited"])

    def test_one_close_failure_does_not_skip_other_retained_handles(self):
        backend = FakeBackend()
        job = obs.WindowsJob(backend)
        job.retain(2000)
        job.retain(3000)
        backend.close_failures.add(200)
        with self.assertRaisesRegex(obs.ObserverError, "all handles attempted"):
            job.close_refs()
        self.assertIn(("close", 200), backend.events)
        self.assertIn(("close", 300), backend.events)
        self.assertEqual(job.refs[2000].handle, 200)
        self.assertIsNone(job.refs[3000].handle)
        backend.close_failures.remove(200)
        job.refs[2000].close()
        self.assertIsNone(job.refs[2000].handle)

    def test_job_close_failure_retains_handle_for_termination_and_retry(self):
        backend = FakeBackend()
        job = obs.WindowsJob(backend)
        backend.close_failures.add(99)
        with self.assertRaises(obs.ObserverError):
            job.close()
        self.assertEqual(job.handle, 99)
        job.terminate()
        backend.close_failures.remove(99)
        job.close()
        self.assertIsNone(job.handle)

    def test_cleanup_slow_successful_query_still_fails_time_bound(self):
        backend = FakeBackend()
        job = obs.WindowsJob(backend)
        clock = Clock()
        original = backend.accounting

        def slow_accounting(*args):
            clock.value += 0.2
            return original(*args)

        backend.k.QueryInformationJobObject = slow_accounting
        with self.assertRaisesRegex(obs.ObserverError, "final queries"):
            job.cleanup_receipt(0.1, require_zero=True, clock=clock.now, sleep=clock.sleep)

    def test_unsupported_platform_is_not_a_linux_fallback(self):
        with mock.patch.object(obs, "os", SimpleNamespace(name="posix")), self.assertRaises(obs.UnsupportedPlatform):
            obs.WindowsBackend()

    def test_native_layouts_have_fixed_width_windows_fields(self):
        self.assertEqual(ctypes.sizeof(obs.DWORD), 4)
        self.assertEqual(ctypes.sizeof(obs.FILETIME), 8)
        self.assertEqual(ctypes.sizeof(obs.MEMORY_COUNTERS), 80 if ctypes.sizeof(ctypes.c_void_p) == 8 else 44)
        self.assertEqual(ctypes.sizeof(obs.BASIC_ACCOUNTING), 48)
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(obs.STARTUPINFO), 104)
            self.assertEqual(ctypes.sizeof(obs.PROCESS_INFORMATION), 24)
            self.assertEqual(ctypes.sizeof(obs.EXTENDED_LIMIT), 144)


def freeze_fixture(directory):
    root = Path(directory)
    for name in probe.SOURCE_PATHS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock source " + name, encoding="utf-8")
    python = root / "python.exe"
    python.write_bytes(b"mock executable, never launched")
    protocol_path, freeze_path = root / "protocol.json", root / "implementation.json"
    protocol = {"predeclared_at": "2026-01-01T00:00:00+00:00", "config": probe.CONFIG,
        "source_paths": list(probe.SOURCE_PATHS), "cases_in_order": [
            {"id": a, "allocation_bytes": b, "mode": c} for a, b, c in probe.CASES]}
    protocol_path.write_text(json.dumps(protocol), encoding="utf-8")
    freeze = {"frozen_at": "2026-01-02T00:00:00+00:00", "protocol_sha256": obs.sha256_file(protocol_path),
        "new_source_files_sha256": {p: obs.sha256_file(root / p) for p in probe.SOURCE_PATHS},
        "python_executable_sha256": obs.sha256_file(python)}
    freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
    return root, python, protocol_path, freeze_path, freeze


class FreezeTests(unittest.TestCase):
    def test_protocol_config_and_case_order_match_frozen_design(self):
        protocol = obs.read_small(probe.ROOT / "fixtures/process-observer/protocol.json")
        self.assertEqual(protocol["config"], probe.CONFIG)
        self.assertEqual([(c["id"], c["allocation_bytes"], c["mode"]) for c in protocol["cases_in_order"]], list(probe.CASES))

    def test_frozen_sources_protocol_launch_executable_and_chronology_are_required(self):
        for tamper in (None, "protocol", "source", "python", "chronology", "extra_source"):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as tmp:
                root, python, protocol, freeze_path, freeze = freeze_fixture(tmp)
                if tamper == "protocol":
                    protocol.write_text(protocol.read_text(encoding="utf-8") + " ", encoding="utf-8")
                elif tamper == "source":
                    (root / probe.SOURCE_PATHS[0]).write_text("modified", encoding="utf-8")
                elif tamper == "python":
                    python.write_bytes(b"modified executable")
                elif tamper == "chronology":
                    freeze["frozen_at"] = "2025-01-01T00:00:00+00:00"
                elif tamper == "extra_source":
                    freeze["new_source_files_sha256"]["extra.py"] = "0" * 64
                freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
                with mock.patch.object(probe, "ROOT", root):
                    if tamper is None:
                        self.assertTrue(probe.validate_freeze(protocol, freeze_path, python))
                    else:
                        with self.assertRaises(obs.ObserverError):
                            probe.validate_freeze(protocol, freeze_path, python)

    def test_unsupported_acceptance_writes_failure_and_spawns_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, python, protocol, freeze, _ = freeze_fixture(tmp)
            output = root / "output"
            with mock.patch.object(probe, "ROOT", root), mock.patch.object(probe, "os", SimpleNamespace(name="posix")), mock.patch.object(probe, "run_case") as run:
                report = probe.acceptance(python, protocol, freeze, output)
                self.assertFalse(report["passed"])
                self.assertIn("UnsupportedPlatform", report["error"])
                self.assertEqual(report["cases"], [])
                run.assert_not_called()
            self.assertTrue((output / "report.json").exists())

    def test_suite_retains_failed_case_and_does_not_select_or_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, python, protocol, freeze, _ = freeze_fixture(tmp)
            responses = [{"id": case[0], "passed": i != 2} for i, case in enumerate(probe.CASES)]
            with mock.patch.object(probe, "ROOT", root), mock.patch.object(probe, "os", SimpleNamespace(name="nt")), mock.patch.object(probe, "run_case", side_effect=responses) as run:
                report = probe.acceptance(python, protocol, freeze, root / "output")
                self.assertFalse(report["passed"])
                self.assertEqual(run.call_count, 5)
                self.assertEqual(report["cases"], responses)
            with self.assertRaises(FileExistsError):
                probe.acceptance(python, protocol, freeze, root / "output")


class CaseDriverMockTests(unittest.TestCase):
    def execute(self, spec, invalid_allocation=False, early_descendant_exit=False, first_job_close_failure=False):
        clock = Clock()
        job = mock.Mock()
        job.handle = 99
        launcher = SimpleNamespace(pid=1000, creation_filetime=10)
        actual = SimpleNamespace(pid=2000, creation_filetime=20, alive=lambda: True,
            reading=lambda: reading(clock=clock.now()))
        descendant = SimpleNamespace(pid=4000, creation_filetime=40, alive=lambda: not early_descendant_exit)
        job.start_suspended.return_value = launcher
        job.retain.return_value = SimpleNamespace(pid=3000, creation_filetime=30)
        job.authenticate.side_effect = [(actual, [{"pid": 2000}, {"pid": 1000}]),
            (descendant, [{"pid": 4000}, {"pid": 3000}, {"pid": 2000}])]
        close_attempts = []

        def close():
            close_attempts.append(1)
            if first_job_close_failure and len(close_attempts) == 1:
                raise obs.ObserverError("mock first job close failure")
            job.handle = None

        def member(ref):
            if ref is descendant and not descendant.alive():
                raise obs.ObserverError("descendant is not a live member")
            return True

        job.close.side_effect = close
        job.member.side_effect = member
        job.cleanup_receipt.side_effect = lambda *a, **kw: {"all_retained_handles_exited": True,
            "job_active_count": 0 if job.handle is not None else None,
            "exit_codes": [{"pid": 2000, "creation_filetime": 20, "exit_code": 0}]}

        def wire(path, *args, **kwargs):
            if path.name == "descendant-launcher.json":
                return {"pid": 2000, "launcher_pid": 3000}
            return {"pid": 2000, "perf_counter": clock.now()}

        def fake_bracket(j, ref, directory, stage, nonce, samples, report, deadline):
            count = spec[1] if stage == "allocated" and not invalid_allocation else 0
            parent = reading(resident=32 * MIB + count, private=16 * MIB + count, clock=clock.now())
            samples.append(parent)
            receipt = {"parent": parent, "self_before": {**parent, "perf_counter": parent["perf_counter"] - 0.001},
                "self_after": {**parent, "perf_counter": parent["perf_counter"] + 0.001}, "comparison": {"passed": True}}
            report.setdefault("memory_brackets", {})[stage] = receipt
            return receipt

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(obs, "WindowsJob", return_value=job), \
                mock.patch.object(probe, "wait_json", side_effect=wire), mock.patch.object(probe, "bracket", side_effect=fake_bracket), \
                mock.patch.object(probe, "control"), mock.patch.object(probe.time, "perf_counter", side_effect=clock.now), \
                mock.patch.object(probe.time, "sleep", side_effect=clock.sleep):
            report = probe.run_case(spec, Path(tmp) / "python.exe", Path(tmp), clock.value + 90)
            self.assertTrue((Path(tmp) / spec[0] / "case-report.json").exists())
        return report, job

    def test_both_healthy_controls_never_invoke_termination(self):
        for spec in probe.CASES[:2]:
            report, job = self.execute(spec)
            self.assertTrue(report["passed"], report)
            self.assertEqual(report["enforcement_reason"], "normal_completion")
            job.terminate.assert_not_called()

    def test_cap_uses_actual_private_threshold_and_job_termination(self):
        report, job = self.execute(probe.CASES[2])
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["enforcement_reason"], "memory_private_limit")
        self.assertEqual(report["first_over_limit_sample"]["pid"], 2000)
        self.assertEqual(report["actual_interpreter_private_limit_bytes"], 64 * MIB)
        self.assertLessEqual(report["allocation_ready_to_termination_seconds"], 1)
        self.assertLessEqual(report["termination_request_started_perf_counter"], report["termination_request_returned_perf_counter"])
        job.terminate.assert_called_once()

    def test_timeout_waits_declared_interval_and_terminates_job(self):
        report, job = self.execute(probe.CASES[3])
        self.assertTrue(report["passed"], report)
        self.assertGreaterEqual(report["timeout_wait_seconds"], 1.5)
        self.assertEqual(report["timeout_wait_seconds"], report["timeout_control_completed_perf_counter"] - report["timeout_control_started_perf_counter"])
        self.assertGreaterEqual(report["termination_request_started_perf_counter"], report["timeout_deadline_perf_counter"])
        self.assertEqual(report["enforcement_reason"], "timeout")
        job.terminate.assert_called_once()

    def test_job_close_control_does_not_call_terminate_or_claim_empty_count(self):
        report, job = self.execute(probe.CASES[4])
        self.assertTrue(report["passed"], report)
        self.assertIsNone(report["cleanup"]["job_active_count"])
        self.assertTrue(report["cleanup"]["job_active_count_after_close_not_queryable"])
        job.terminate.assert_not_called()

    def test_failed_allocation_is_retained_and_triggers_exception_cleanup(self):
        report, job = self.execute(probe.CASES[0], invalid_allocation=True)
        self.assertFalse(report["passed"])
        self.assertIn("allocation", report["error"])
        self.assertIn("failure_cleanup", report)
        job.terminate.assert_called_once()

    def test_job_close_rejects_descendant_that_exited_before_control(self):
        report, job = self.execute(probe.CASES[4], early_descendant_exit=True)
        self.assertFalse(report["passed"])
        self.assertIn("not a live member", report["error"])
        self.assertIn("failure_cleanup", report)
        job.terminate.assert_called_once()

    def test_job_close_first_failure_terminates_cleans_then_finally_retries(self):
        report, job = self.execute(probe.CASES[4], first_job_close_failure=True)
        self.assertFalse(report["passed"])
        self.assertIn("first job close failure", report["error"])
        self.assertTrue(report["failure_cleanup"]["all_retained_handles_exited"])
        self.assertEqual(job.close.call_count, 2)
        self.assertIsNone(job.handle)
        job.terminate.assert_called_once()

    def test_failed_suspended_launch_preserves_receipt_and_cleans_whole_job(self):
        job = mock.Mock()
        job.handle = 99
        job.start_suspended.side_effect = obs.ObserverError("mock launch failure")
        job.cleanup_receipt.return_value = {"all_retained_handles_exited": True, "job_active_count": 0}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(obs, "WindowsJob", return_value=job):
            report = probe.run_case(probe.CASES[0], Path(tmp) / "python.exe", Path(tmp), probe.time.perf_counter() + 90)
        self.assertFalse(report["passed"])
        self.assertIn("mock launch failure", report["error"])
        self.assertTrue(report["failure_cleanup"]["all_retained_handles_exited"])
        job.terminate.assert_called_once()
        job.close.assert_called_once()
        job.close_refs.assert_called_once()


if __name__ == "__main__":
    unittest.main()
