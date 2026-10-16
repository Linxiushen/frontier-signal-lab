"""Stdlib mock controls; no ML import, subprocess, native job or acceptance."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments import process_observer as obs
from experiments import training_observer_probe as p

NONCE = "a" * 64
MIB = 1024 * 1024


class Clock:
    def __init__(self):
        self.value = 10.0

    def now(self):
        self.value += 0.0001
        return self.value

    def sleep(self, duration):
        self.value += duration


def model_info():
    schedule = p.cost.batch_schedule(128, 2, 2, 503)
    return {"model_id": p.cost.MODEL_ID, "model_revision": p.cost.MODEL_REVISION,
        "train_sha256": "8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681",
        "schedule": schedule, "schedule_sha256": p.cost.digest(schedule), "seed": 503,
        "trainable_parameter_count": 14067712, "parameter_tensors": 76,
        "initial_parameter_sha256": "a" * 64, "batch_shapes": [[2, 65], [2, 65]],
        "device": "cpu", "dtype": "torch.float32", "intraop_threads": 1, "interop_threads": 1,
        "deterministic_algorithms": True, "loader_local_files_only": True,
        "trust_remote_code": False, "attention": "eager", "holdout_opened": False,
        "offline_environment": dict(p.OFFLINE_ENV),
        "model_load_timing": {"started_perf_counter": 1.1, "completed_perf_counter": 1.5, "wall_seconds": 0.4},
        "preparation_timing": {"started_perf_counter": 1.0, "completed_perf_counter": 1.6, "wall_seconds": 0.6}}


def operation():
    return {"method": "dense", "arm": "token", "optimizer": p.cost.preset_config()["optimizer"],
        "loop": {"steps_completed": 2, "training_target_positions": 256,
            "preupdate_batch_losses_recorded_after_updates": [4.4, 4.5],
            "loop_perf_counter_start": 2.0, "loop_perf_counter_end": 2.5,
            "training_loop_wall_seconds": 0.5},
        "final_validity": {"final_parameter_gradient_moments_finite": True, "optimizer_counters": [2] * 76},
        "final_parameter_sha256": "b" * 64, "no_checkpoint_written": True, "no_holdout_evaluation": True}


def reading(clock=10.0, amount=300 * MIB):
    return {"pid": 2000, "creation_filetime": 20, "perf_counter": clock,
        "native_cpu_seconds": clock * 2,
        "memory": {"private_bytes": amount, "resident_bytes": amount, "peak_resident_bytes": amount}}


class ContractTests(unittest.TestCase):
    def test_fixed_protocol_matches_cases_steps_and_dependencies(self):
        value = obs.read_small(p.ROOT / "fixtures/training-observer/protocol.json")
        self.assertEqual(value["config"], p.CONFIG)
        self.assertEqual(value["source_paths"], list(p.SOURCE_PATHS))
        self.assertEqual(value["frozen_dependency_paths"], list(p.DEPENDENCY_PATHS))
        self.assertEqual([(c["id"], c["mode"], c["manual_allocation_bytes"]) for c in value["cases_in_order"]], list(p.CASES))
        self.assertEqual(value["model"]["planned_model_loads"], 3)
        self.assertEqual(value["model"]["planned_optimizer_updates"], 6)
        self.assertEqual(value["training"]["schedule"], p.cost.batch_schedule(128, 2, 2, 503))

    def test_model_contract_rejects_remote_loading_device_threads_or_changed_data(self):
        self.assertTrue(p.validate_model(model_info()))
        changes = [("model_revision", "main"), ("loader_local_files_only", False),
            ("trust_remote_code", True), ("holdout_opened", True), ("device", "cuda:0"),
            ("intraop_threads", 2), ("interop_threads", True), ("train_sha256", "b" * 64),
            ("batch_shapes", [[2, 64], [2, 64]]), ("trainable_parameter_count", 14),
            ("initial_parameter_sha256", "G" * 64), ("offline_environment", {}), ("schedule", [[0, 1], [2, 3]])]
        for key, value in changes:
            with self.subTest(key=key):
                info = model_info()
                info[key] = value
                self.assertFalse(p.validate_model(info))

    def test_update_contract_rejects_wrong_optimizer_nonfinite_or_unchanged_parameters(self):
        self.assertTrue(p.validate_operation(operation(), "a" * 64))
        for key, value in (("method", "int8"), ("optimizer", {}), ("final_parameter_sha256", "a" * 64),
                ("no_holdout_evaluation", False), ("no_checkpoint_written", False)):
            record = operation()
            record[key] = value
            with self.subTest(key=key):
                self.assertFalse(p.validate_operation(record, "a" * 64))
        for key, value in (("steps_completed", 3), ("steps_completed", True), ("training_target_positions", 128),
                ("preupdate_batch_losses_recorded_after_updates", [4.0, float("nan")]),
                ("loop_perf_counter_end", 1.0), ("training_loop_wall_seconds", 0.4)):
            record = operation()
            record["loop"][key] = value
            with self.subTest(key=key):
                self.assertFalse(p.validate_operation(record, "a" * 64))
        record = operation()
        record["final_validity"]["optimizer_counters"] = [2.0] * 76
        self.assertFalse(p.validate_operation(record, "a" * 64))

    def test_dense_training_reuses_fixed_historical_helpers_only(self):
        op = operation()
        with mock.patch.object(p.cost, "training_loop", return_value=op["loop"]) as loop, \
                mock.patch.object(p.cost, "final_validity", return_value=op["final_validity"]) as validity, \
                mock.patch.object(p.cost, "parameter_hash", return_value="b" * 64):
            result = p.two_dense_updates("model", "optimizer", ["batch1", "batch2"])
        args, kwargs = loop.call_args
        self.assertEqual(args, ("model", "optimizer", ["batch1", "batch2"], "token", "dense", []))
        self.assertEqual(kwargs["config"]["token_steps"], 2)
        self.assertEqual(kwargs["config"]["optimizer"], p.cost.preset_config()["optimizer"])
        validity.assert_called_once_with("model", "optimizer", 2)
        self.assertTrue(p.validate_operation(result, "a" * 64))

    def test_stage_deadlines_clamp_without_renewing_case_or_suite(self):
        with mock.patch.object(p.time, "perf_counter", return_value=10):
            self.assertEqual(p.stage_deadline(5, 20, 30), 15)
            self.assertEqual(p.stage_deadline(5, 12, 30), 12)
            self.assertEqual(p.stage_deadline(5, 20, 11), 11)

    def test_descendant_snapshot_is_bounded_and_keeps_transitive_children(self):
        self.assertEqual(p.descendants_at_snapshot({2: 1, 3: 2, 4: 90}, 1), {1, 2, 3})
        with self.assertRaisesRegex(obs.ObserverError, "bounded"):
            p.descendants_at_snapshot({i + 1: i for i in range(1, 20)}, 1)


class IdentityAndSamplingTests(unittest.TestCase):
    def test_os_image_uses_retained_handle_and_rejects_wrong_path_hash_pid_or_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "python.exe"
            image.write_bytes(b"fake OS interpreter image; never executed")
            image_value, current_pid, creation = [str(image)], [2000], [20]

            def query(handle, flags, buffer, size):
                self.assertEqual(handle, 222)
                buffer.value = image_value[0]
                size._obj.value = len(buffer.value)
                return True

            backend = SimpleNamespace(k=SimpleNamespace(QueryFullProcessImageNameW=mock.Mock(side_effect=query),
                GetProcessId=lambda handle: current_pid[0]), creation=lambda handle: creation[0],
                checked=lambda result, action: result if result else (_ for _ in ()).throw(obs.ObserverError(action)))
            ref = SimpleNamespace(handle=222, pid=2000, creation_filetime=20)
            receipt = p.os_image(backend, ref, image, obs.sha256_file(image))
            self.assertTrue(receipt["queried_from_retained_handle"])
            self.assertEqual(receipt["sha256"], obs.sha256_file(image))
            self.assertNotIn(str(tmp), json.dumps(receipt))
            image_value[0] = str(Path(tmp) / "launcher.exe")
            with self.assertRaisesRegex(obs.ObserverError, "image differs"):
                p.os_image(backend, ref, image, obs.sha256_file(image))
            image_value[0] = str(image)
            with self.assertRaisesRegex(obs.ObserverError, "bytes differ"):
                p.os_image(backend, ref, image, "a" * 64)
            current_pid[0] = 1000
            with self.assertRaisesRegex(obs.ObserverError, "identity changed"):
                p.os_image(backend, ref, image, obs.sha256_file(image))
            current_pid[0], creation[0] = 2000, 19
            with self.assertRaisesRegex(obs.ObserverError, "identity changed"):
                p.os_image(backend, ref, image, obs.sha256_file(image))

    def test_timed_call_records_parent_cpu_and_wall_without_renaming_as_worker(self):
        costs = []
        with mock.patch.object(p.time, "perf_counter", side_effect=[10.0, 10.2]), \
                mock.patch.object(p.time, "process_time", side_effect=[2.0, 2.03]):
            result = p.timed_call("native_query", lambda: 42, costs)
        self.assertEqual(result, 42)
        self.assertAlmostEqual(costs[0]["parent_process_cpu_seconds"], 0.03)
        self.assertAlmostEqual(costs[0]["wall_seconds"], 0.2)

    def test_inventory_preserves_unknown_observed_process_before_failing(self):
        def ref(pid):
            return SimpleNamespace(pid=pid, creation_filetime=pid)
        job = SimpleNamespace(backend=SimpleNamespace(snapshot=lambda: {1000: 10, 2000: 1000, 3000: 2000, 4000: 2000}),
            retain=ref, member=mock.Mock())
        report = {"parent_query_costs": []}
        with self.assertRaisesRegex(obs.ObserverError, "unexpected"):
            p.inventory(job, ref(1000), ref(2000), ref(3000), report, "postload")
        row = report["stage_process_inventories"][0]
        self.assertEqual(row["unknown_descendants"], [4000])
        self.assertEqual(len(row["processes"]), 4)
        self.assertIn("between-snapshot", row["boundary"])

    def test_read_stage_bracket_goes_through_instrumented_parent_sample(self):
        report = {"samples": [], "parent_query_costs": []}
        actual = SimpleNamespace(pid=2000)
        ready = {"pid": 2000, "stage": "postload", "native_thread_count": 4}
        with mock.patch.object(p, "wait", return_value=ready), \
                mock.patch.object(p.work, "wait_receipt", side_effect=[reading(10), reading(12)]), \
                mock.patch.object(p, "sample", return_value=reading(11)) as sample, \
                mock.patch.object(p.base, "control"), mock.patch.object(p, "inventory"):
            bracket = p.read_stage(None, None, actual, None, Path("unused"), "postload", NONCE, report, 100, 200)
        self.assertTrue(bracket["comparison"]["passed"])
        sample.assert_called_once()
        self.assertEqual(report["stages"]["postload"], ready)

    def test_read_stage_rejects_nonce_sender_thread_or_bracket_failure(self):
        for changed in ({"pid": 1000}, {"native_thread_count": True}, {"stage": "wrong"}):
            ready = {"pid": 2000, "stage": "postload", "native_thread_count": 4, **changed}
            with mock.patch.object(p, "wait", return_value=ready), self.assertRaises(obs.ObserverError):
                p.read_stage(None, None, SimpleNamespace(pid=2000), None, Path("unused"), "postload", NONCE,
                    {"samples": [], "parent_query_costs": []}, 100, 200)
        with mock.patch.object(p, "wait", return_value={"pid": 2000, "stage": "postload", "native_thread_count": 4}), \
                mock.patch.object(p.work, "wait_receipt", side_effect=[reading(10), reading(12)]), \
                mock.patch.object(p, "sample", return_value=reading(11, 400 * MIB)), \
                mock.patch.object(p.base, "control"), self.assertRaisesRegex(obs.ObserverError, "memory bracket"):
            p.read_stage(None, None, SimpleNamespace(pid=2000), None, Path("unused"), "postload", NONCE,
                {"samples": [], "parent_query_costs": []}, 100, 200)

    def test_overhead_windows_preserve_fixed_hold_order_and_raw_cpu_indices(self):
        clock = Clock()
        report = {"samples": [], "parent_query_costs": []}
        job = SimpleNamespace(backend=SimpleNamespace(k=SimpleNamespace(GetCurrentProcess=lambda: -1), snapshot=lambda: {}))

        def sample(*args):
            report["samples"].append(reading(clock.now()))

        with mock.patch.object(p.time, "perf_counter", side_effect=clock.now), \
                mock.patch.object(p.time, "sleep", side_effect=clock.sleep), \
                mock.patch.object(p.obs, "ProcessRef", return_value="borrowed pseudo-handle"), \
                mock.patch.object(p.work, "native_process_cpu", side_effect=[2, 2.01, 2.01, 2.05]), \
                mock.patch.object(p, "sample", side_effect=sample):
            p.overhead_windows(job, None, report, 100, 200)
        windows = report["held_parent_overhead_windows"]
        self.assertEqual([r["sampling_enabled"] for r in windows], [False, True])
        self.assertTrue(all(r["wall_seconds"] >= 0.4 for r in windows))
        self.assertEqual(windows[0]["sample_index_start"], windows[0]["sample_index_end"])
        self.assertGreater(windows[1]["sample_index_end"], windows[1]["sample_index_start"])
        self.assertAlmostEqual(windows[1]["parent_native_cpu_delta_seconds"], 0.04)
        self.assertIn("no causal", report["parent_overhead_boundary"])


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)
        self.launcher = SimpleNamespace(pid=1000, creation_filetime=10)
        self.actual = SimpleNamespace(pid=2000, creation_filetime=20)
        self.native = SimpleNamespace(pid=3000, creation_filetime=30)
        self.job = mock.Mock()
        self.job.start_suspended.return_value = self.launcher
        self.job.authenticate.return_value = (self.actual, [{"pid": 2000}, {"pid": 1000}])
        self.freeze = {"python_executable_sha256": "a" * 64,
            "base_python_executable_sha256": "b" * 64, "native_executable_sha256": "c" * 64}
        self.controls = []
        self.bad_done = False
        self.bad_import = False
        self.bad_model = False
        self.bad_busy = False
        self.cannot_clean = False
        self.patches = [mock.patch.object(p.time, "perf_counter", side_effect=self.clock.now),
            mock.patch.object(p.time, "sleep", side_effect=self.clock.sleep),
            mock.patch.object(p.obs, "WindowsJob", return_value=self.job),
            mock.patch.object(p, "os_image", return_value={"sha256": "b" * 64}),
            mock.patch.object(p.work, "wait_receipt", side_effect=lambda *a, **kw: {"pid": 2000}),
            mock.patch.object(p.work, "verify_native_child", return_value=(self.native, {})),
            mock.patch.object(p, "read_stage", side_effect=self.stage),
            mock.patch.object(p, "wait", side_effect=self.message),
            mock.patch.object(p.base, "control", side_effect=lambda folder, name, nonce, command: self.controls.append((name, command))),
            mock.patch.object(p, "overhead_windows"), mock.patch.object(p, "inventory"),
            mock.patch.object(p.work, "live_member_receipts", return_value=[{"pid": 2000, "alive": True}, {"pid": 3000, "alive": True}]),
            mock.patch.object(p.work, "require_exit", return_value=37),
            mock.patch.object(p.work, "cleanup", side_effect=self.cleanup),
            mock.patch.object(p, "sample", side_effect=self.sample)]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def sample(self, job, actual, report):
        s = reading(self.clock.now(), (364 if report.get("mode") == "private_cap" else 300) * MIB)
        report["samples"].append(s)
        return s

    def stage(self, job, launcher, actual, native, directory, label, nonce, report, *args):
        amount = (364 if label == "allocated" and report["manual_allocation_bytes"] else 300) * MIB
        now = self.clock.now()
        bracket = {"self_before": reading(now, amount), "parent": reading(now + 0.0001, amount),
            "self_after": reading(now + 0.0002, amount), "comparison": {"passed": True}}
        report.setdefault("memory_brackets", {})[label] = bracket
        report["samples"].append(bracket["parent"])
        detail = {"pid": 2000, "stage": label, "native_thread_count": 4}
        if label == "preimport":
            detail.update(torch_imported=False, transformers_imported=False)
        elif label == "postimport":
            detail.update(torch_version="2.9.1+cpu", transformers_version="4.57.3")
        elif label == "postload":
            detail["model"] = model_info()
            if self.bad_model:
                detail["model"]["loader_local_files_only"] = False
        elif label == "postupdate":
            detail["operation"] = operation()
        report.setdefault("stages", {})[label] = detail
        return bracket

    def message(self, directory, name, nonce, *args, **kwargs):
        if name == "worker-completed.json":
            return {"pid": 2000, "native_exit_code": 1 if self.bad_done else 0,
                "native_released_nonempty_line": True, "model_loads": 1, "optimizer_steps": 2}
        if name == "expected-import-failure.json":
            return {"pid": 2000, "stage": "import", "exception_type": "ImportError" if self.bad_import else "ModuleNotFoundError",
                "missing_module": "training_observer_missing_dependency_" + nonce,
                "torch_imported": False, "transformers_imported": False, "model_loads": 0,
                "optimizer_steps": 0, "expected_exit_code": 38}
        if name == "busy-ready.json":
            return {"pid": 2000, "perf_counter": self.clock.now(), "extra_backward_calls": 0,
                "extra_optimizer_steps": 0, "model_forward_no_grad": True}
        if name == "busy-first-operation.json":
            return {"pid": 2000, "completed_perf_counter": self.clock.now(), "model_forward_iterations_completed": 1,
                "extra_backward_calls": 1 if self.bad_busy else 0, "extra_optimizer_steps": 0, "model_forward_no_grad": True}
        raise AssertionError(name)

    def cleanup(self, *args):
        if self.cannot_clean:
            raise obs.ObserverError("injected cleanup failure")
        return {"all_retained_handles_exited": True, "job_active_count": 0,
            "exit_codes": [{"pid": 2000, "exit_code": 0}], "wall_seconds": 0.02}

    def run_case(self, index):
        return p.run_case(p.CASES[index], Path("launcher.exe"), Path("base.exe"), Path("cmd.exe"),
            Path("model"), Path("fixture"), self.freeze, self.output, 190)

    def test_healthy_actual_loader_updates_release_and_job_cleanup(self):
        result = self.run_case(0)
        self.assertTrue(result["passed"], result.get("error"))
        self.assertEqual(result["outcome"], "normal_completion")
        self.assertEqual(set(result["stages"]), {*p.STAGES, "allocated"})
        self.assertEqual(result["allocation_check"]["parent_deltas_bytes"]["private_bytes"], 64 * MIB)
        self.assertIn(("finish.json", "finish"), self.controls)
        self.assertTrue(result["healthy_memory_limit_disabled"])
        self.job.close.assert_called_once()
        self.job.close_refs.assert_called_once()

    def test_healthy_nonzero_exit_never_passes_and_preserves_failure_cleanup(self):
        self.bad_done = True
        result = self.run_case(0)
        self.assertFalse(result["passed"])
        self.assertIn("completion differs", result["error"])
        self.assertTrue(result["failure_cleanup"]["all_retained_handles_exited"])

    def test_failed_loader_contract_stops_before_postupdate_release(self):
        self.bad_model = True
        result = self.run_case(0)
        self.assertFalse(result["passed"])
        self.assertIn("loader", result["error"])
        self.assertNotIn(("postload-continue.json", "continue"), self.controls)

    def test_busy_deadline_requires_forward_and_cpu_progress_then_whole_job_termination(self):
        result = self.run_case(1)
        self.assertTrue(result["passed"], result.get("error"))
        self.assertEqual(result["outcome"], "timeout")
        self.assertGreaterEqual(result["busy_sampling"]["native_cpu_delta_seconds"], 0.25)
        self.assertTrue(result["busy_sampling"]["gap_gate_passed"])
        self.job.terminate.assert_called_once()

    def test_busy_private_cap_uses_postupdate_baseline_and_fixed_latency(self):
        result = self.run_case(2)
        self.assertTrue(result["passed"], result.get("error"))
        self.assertEqual(result["actual_interpreter_private_limit_bytes"], 348 * MIB)
        self.assertEqual(result["outcome"], "memory_private_limit")
        self.assertLessEqual(result["allocation_ready_to_termination_seconds"], 1)

    def test_busy_extra_backward_is_unrelated_failure(self):
        self.bad_busy = True
        result = self.run_case(1)
        self.assertFalse(result["passed"])
        self.assertIn("forward control", result["error"])

    def test_prehandshake_preserves_identity_unavailable_and_no_import(self):
        result = self.run_case(3)
        self.assertTrue(result["passed"], result.get("error"))
        self.assertTrue(result["prehandshake_control"]["actual_interpreter_identity_unavailable"])
        self.assertNotIn("worker_identity", result)
        self.assertFalse(self.controls)

    def test_import_failure_requires_precise_module_and_actual_exit38(self):
        result = self.run_case(4)
        self.assertTrue(result["passed"], result.get("error"))
        self.assertEqual(result["outcome"], "expected_injected_import_failure38")
        self.assertEqual(result["expected_worker_exit_code"], 38)
        self.assertEqual(set(result["stages"]), {"preimport"})
        p.work.require_exit.assert_any_call(self.actual, 38, mock.ANY)
        p.work.require_exit.assert_any_call(self.launcher, 38, mock.ANY)

    def test_unrelated_import_failure_never_satisfies_exact_control(self):
        self.bad_import = True
        result = self.run_case(4)
        self.assertFalse(result["passed"])
        self.assertIn("precise control", result["error"])

    def test_cleanup_failure_retained_and_cannot_pass(self):
        self.cannot_clean = True
        result = self.run_case(0)
        self.assertFalse(result["passed"])
        self.assertIn("cleanup_error", result)
        self.job.close.assert_called_once()
        self.job.close_refs.assert_called_once()


class FreezeTests(unittest.TestCase):
    def freeze_context(self):
        protocol = obs.read_small(p.ROOT / "fixtures/training-observer/protocol.json")
        freeze = {"protocol_sha256": "a" * 64,
            "new_source_files_sha256": {name: "a" * 64 for name in p.SOURCE_PATHS},
            "frozen_dependency_files_sha256": {name: "a" * 64 for name in p.DEPENDENCY_PATHS},
            "python_executable_sha256": "a" * 64, "base_python_executable_sha256": "a" * 64,
            "native_executable_sha256": "a" * 64, "frozen_at": "2026-10-16T21:00:00+00:00"}
        # Never depend on wall-clock being later than this pass's future freeze.
        protocol["predeclared_at"] = "2026-01-01T00:00:00+00:00"
        freeze["frozen_at"] = "2026-01-01T00:00:01+00:00"
        return protocol, freeze

    def test_base_interpreter_hash_is_a_required_freeze_gate(self):
        protocol, freeze = self.freeze_context()
        with mock.patch.object(p.obs, "read_small", side_effect=lambda path: protocol if str(path) == "protocol" else freeze), \
                mock.patch.object(p.obs, "sha256_file", return_value="a" * 64), \
                mock.patch.object(p.cost, "verify_model_assets"), mock.patch.object(p.cost, "validate_fixture"):
            p.validate_freeze("protocol", "freeze", "launcher", "base", "cmd.exe", "model", p.ROOT / "fixtures/activation-cost")
            freeze["base_python_executable_sha256"] = "b" * 64
            with self.assertRaisesRegex(obs.ObserverError, "base_python_executable"):
                p.validate_freeze("protocol", "freeze", "launcher", "base", "cmd.exe", "model", p.ROOT / "fixtures/activation-cost")

    def test_freeze_requires_exact_new_source_dependency_set_and_case_order(self):
        protocol, freeze = self.freeze_context()
        with mock.patch.object(p.obs, "read_small", side_effect=lambda path: protocol if str(path) == "protocol" else freeze), \
                mock.patch.object(p.obs, "sha256_file", return_value="a" * 64):
            freeze["frozen_dependency_files_sha256"].pop(p.DEPENDENCY_PATHS[0])
            with self.assertRaisesRegex(obs.ObserverError, "source/dependency"):
                p.validate_freeze("protocol", "freeze", "launcher", "base", "cmd.exe", "model", p.ROOT / "fixtures/activation-cost")
            protocol["cases_in_order"].reverse()
            with self.assertRaisesRegex(obs.ObserverError, "case order"):
                p.validate_freeze("protocol", "freeze", "launcher", "base", "cmd.exe", "model", p.ROOT / "fixtures/activation-cost")


if __name__ == "__main__":
    unittest.main()
