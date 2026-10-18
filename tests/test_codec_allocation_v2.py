"""Pre-freeze v2 controls using stdlib receipts and a mocked Windows Job only."""
import ast
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


FORBIDDEN_ATTEMPTS = []


def forbidden(*args, **kwargs):
    FORBIDDEN_ATTEMPTS.append("ML/process/socket attempt")
    raise AssertionError("pure codec v2 preflight cannot perform ML/process/socket work")


@contextmanager
def pure_only():
    original = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "transformers", "numpy"):
            return forbidden()
        return original(name, *args, **kwargs)
    with ExitStack() as stack:
        stack.enter_context(mock.patch("builtins.__import__", side_effect=guarded_import))
        for module, names in ((subprocess, ("Popen", "run")),
                              (socket, ("socket", "create_connection")),
                              (os, ("system", "startfile", "fork", "forkpty", "posix_spawn", "posix_spawnp",
                                    "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe"))):
            for name in names:
                stack.enter_context(mock.patch.object(module, name, forbidden, create=True))
        yield


with pure_only():
    from experiments import codec_allocation_v2 as probe


ROOT = Path(__file__).resolve().parents[1]
NONCE = "a" * 64


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def provider(phase):
    """Valid immutable-v3 policy fixture; preimport has budget1/count0."""
    value = copy.deepcopy(read(ROOT / "results/codec-allocation/01_off_dense/preimport-ready.json")["provider_guard"])
    value["phase"] = phase
    if phase == "preimport":
        return value
    source = value["provider_source"]
    frames = [{"package_relative_path": source["package_relative_path"], "function": name, "line": line,
               "sha256": source["sha256"], "normalized_path_sha256": source["normalized_path_sha256"]}
              for name, line in (("_has_ipv6", 127), ("<module>", 137))]
    value.update(allowed_local_probe_count=1, observed_event_count=1, diagnostic_events=[{
        "event_index": 0, "event": "socket.bind", "perf_counter": 10.0, "phase": "import",
        "socket_family_code": 23, "socket_type_code": 1, "socket_protocol": 0,
        "endpoint": {"shape": "tuple2", "host_kind": "exact_ipv6_loopback", "port_kind": "ephemeral_zero", "address_logged": False},
        "frames": frames, "frame_scope": probe.prior.PROVIDER_FRAME_SCOPE, "frame_boundary": "outside_selected_package",
        "frames_scanned_count": 3, "saved_frame_count": 2, "frames_truncated": False, "source_hashes_complete": True,
        "diagnostic_errors": [], "decision": "allowed_local_capability_probe"}])
    return value


def model_info():
    return {"model_id": probe.cost.MODEL_ID, "model_revision": probe.cost.MODEL_REVISION,
        "train_sha256": "8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681",
        "batch_indices": [116, 73], "batch_shape": [2, 65], "batch_sha256": "b" * 64,
        "initial_parameter_sha256": "a" * 64, "parameter_tensors": 76, "parameter_elements": 14067712,
        "optimizer_created": False, "holdout_opened": False, "seed": 503,
        "intraop_threads": 1, "interop_threads": 1, "deterministic_algorithms": True}


def operation(spec):
    return {"spec": spec, "forward_calls": 1, "backward_calls": 1, "optimizer_updates": 0,
        "observer_enabled": False, "parameters_unchanged": True, "final_parameter_sha256": "a" * 64,
        "gradient": {"finite": True, "count": 76, "sha256": "c" * 64}, "loss": 2.5,
        "exact_norm_scopes": 13, "exact_attention_scopes": 6, "holdout_opened": False, "checkpoint_written": False,
        "forward_loss_wall_seconds": 0.1, "backward_wall_seconds": 0.2, "forward_plus_backward_wall_seconds": 0.3,
        "trace_sha256": None, "measurement_valid": None, "measurement_gates": None, "profiler_settings": None,
        "callback_pack_wall_seconds": None, "callback_unpack_wall_seconds": None}


class Clock:
    def __init__(self):
        self.value = 10.0
    def now(self):
        self.value += 0.001
        return self.value


class CodecV2PreflightTests(unittest.TestCase):
    def setUp(self):
        self.guard = pure_only()
        self.guard.__enter__()
        self.addCleanup(self.guard.__exit__, None, None, None)
        self.addCleanup(self.assertEqual, FORBIDDEN_ATTEMPTS, [])

    def run_mock_case(self, corrupt_stage=None, mutate=None):
        """Run all real controller logic, except OS queries and worker transport."""
        clock, observed = Clock(), {}
        spec = probe.case_spec("01_off_dense")
        launcher, actual = SimpleNamespace(pid=100, creation_filetime=1000), SimpleNamespace(pid=200, creation_filetime=2000)
        identities = [{"pid": ref.pid, "creation_filetime": ref.creation_filetime} for ref in (launcher, actual)]
        job = mock.Mock(name="mock_only_job")
        job.start_suspended.return_value = launcher
        job.authenticate.return_value = (actual, [])
        freeze = {"executables_sha256": {name: "d" * 64 for name in ("launcher", "base_python", "native", "conhost")},
                  "executable_path_sha256": {name: "e" * 64 for name in ("launcher", "base_python", "native", "conhost")}}
        paths = {name: Path("never-opened") / name for name in freeze["executables_sha256"]}
        def wait_receipt(directory, filename, *args):
            if filename == "worker-ready.json":
                return {"nonce": NONCE, "role": "worker", "pid": actual.pid}
            if filename.endswith("-ready.json"):
                stage = filename.removesuffix("-ready.json")
                value = {"nonce": NONCE, "role": "worker", "pid": actual.pid, "stage": stage,
                    "stage_ready_perf_counter": clock.now(), "native_thread_count": 4,
                    "provider_guard": provider(probe.PHASES[stage])}
                if stage == "preimport":
                    value.update(torch_imported=False, transformers_imported=False)
                if stage == "postload":
                    value["model"] = model_info()
                if stage == "poststudy":
                    probe.write_bounded(Path(directory) / "operation.json", operation(spec))
                    value["operation_sha256"] = sha256(Path(directory) / "operation.json")
                if stage == corrupt_stage:
                    mutate(value)
                observed[stage] = copy.deepcopy(value)
                return value
            if filename.endswith("-accepted.json"):
                control_name = filename.removesuffix("-accepted.json") + ".json"
                control = read(Path(directory) / control_name)
                return {"nonce": NONCE, "role": "worker", "pid": actual.pid, "filename": control_name,
                    "control_envelope": control, "accepted_perf_counter": clock.now(),
                    "next_control_index": control["control_index"] + 1}
            if filename == "worker-completed.json":
                return {"nonce": NONCE, "role": "worker", "pid": actual.pid, "spec": spec,
                    "model_loads": 1, "forward_calls": 1, "backward_calls": 1, "optimizer_updates": 0,
                    "provider_guard": provider("complete")}
            raise AssertionError("unexpected transport filename: " + filename)
        def inventory(unused_job, unused_launcher, unused_actual, native, report, stage):
            self.assertIsNone(native)
            report["censuses"].append({"processes": copy.deepcopy(identities)})
            report["role_decisions"].append({"admitted": True, "label": stage, "completed_perf_counter": clock.now()})
        cleanup = {"all_retained_handles_exited": True, "job_active_count": 0,
                   "exit_codes": [dict(row, exit_code=0) for row in identities]}
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(mock.patch.object(probe.obs, "WindowsJob", return_value=job))
            stack.enter_context(mock.patch.object(probe.obs, "WindowsBackend", side_effect=forbidden))
            stack.enter_context(mock.patch.object(probe.time, "perf_counter", side_effect=clock.now))
            stack.enter_context(mock.patch.object(probe.secrets, "token_hex", return_value=NONCE))
            stack.enter_context(mock.patch.object(probe.work, "wait_receipt", side_effect=wait_receipt))
            stack.enter_context(mock.patch.object(probe.prior, "os_image", return_value={}))
            stack.enter_context(mock.patch.object(probe.dual, "verify_self_executable", return_value={}))
            validation = stack.enter_context(mock.patch.object(probe.prior, "validate_provider", wraps=probe.prior.validate_provider))
            stack.enter_context(mock.patch.object(probe.prior, "inventory", side_effect=inventory))
            stack.enter_context(mock.patch.object(probe.prior, "import_packages", side_effect=forbidden))
            stack.enter_context(mock.patch.object(probe.work, "cleanup", return_value=cleanup))
            result = probe.run_case(paths, Path("unopened-provider"), Path("unopened-model"), Path("unopened-fixture"),
                                    freeze, Path(directory), spec, 500.0)
            validation_calls = validation.call_args_list
        return result, observed, validation_calls, job

    def test_real_validator_full_parent_handshake_all_five_stages_and_finish(self):
        result, observed, calls, job = self.run_mock_case()
        self.assertTrue(result["passed"], result.get("error"))
        self.assertEqual(list(result["stages"]), list(probe.STAGES))
        self.assertEqual(result["received_stage_receipts"], observed)
        self.assertEqual(len(result["controller_controls"]), 6)
        self.assertEqual(len(result["worker_controls"]), 6)
        self.assertEqual([call.args[1] for call in calls], ["preimport", "postimport", "postload", "postupdate", "complete", "complete"])
        self.assertTrue(all(call.kwargs == {"expected_budget": 1} for call in calls))
        for stage, diagnostic in result["gate_diagnostics"].items():
            self.assertEqual(set(diagnostic["predicates"]), set(probe.STAGE_PREDICATES))
            self.assertTrue(all(diagnostic["predicates"].values()), stage)
        self.assertTrue(result["cleanup_exact_retained_identity_set"])
        job.terminate.assert_not_called()

    def test_bad_budget_rejected_with_raw_and_each_diagnostic_preserved(self):
        result, observed, calls, job = self.run_mock_case("preimport",
            lambda value: value["provider_guard"].update(allowed_local_probe_budget=0))
        self.assertFalse(result["passed"])
        self.assertEqual(result["stages"], {})
        self.assertEqual(result["received_stage_receipts"], observed)
        gates = result["gate_diagnostics"]["preimport"]["predicates"]
        self.assertFalse(gates["provider_policy_budget_one"])
        self.assertTrue(all(value for key, value in gates.items() if key != "provider_policy_budget_one"))
        self.assertEqual(result["controller_controls"], [])
        self.assertEqual(calls[0].kwargs, {"expected_budget": 1})
        job.terminate.assert_called_once_with()

    def test_preimport_count_mismatch_is_not_fixed_by_budget(self):
        result, observed, _, _ = self.run_mock_case("preimport",
            lambda value: value["provider_guard"].update(allowed_local_probe_count=1))
        self.assertFalse(result["passed"])
        self.assertEqual(result["received_stage_receipts"], observed)
        self.assertFalse(result["gate_diagnostics"]["preimport"]["predicates"]["provider_policy_budget_one"])

    def test_unexpected_bind_after_import_stops_before_next_control(self):
        def mutate(value):
            value["provider_guard"]["unexpected_denied_events"] = [{"event": "socket.bind"}]
        result, observed, _, _ = self.run_mock_case("postimport", mutate)
        self.assertFalse(result["passed"])
        self.assertEqual(list(result["stages"]), ["preimport"])
        self.assertEqual(len(result["controller_controls"]), 1)
        self.assertEqual(result["received_stage_receipts"], observed)
        self.assertFalse(result["gate_diagnostics"]["postimport"]["predicates"]["provider_policy_budget_one"])

    def test_independent_gates_retain_multiple_failure_causes(self):
        def mutate(value):
            value["stage_ready_perf_counter"] = float("nan")
            value["native_thread_count"] = True
            value["provider_guard"]["allowed_local_probe_budget"] = 0
        result, _, calls, _ = self.run_mock_case("preimport", mutate)
        gates = result["gate_diagnostics"]["preimport"]["predicates"]
        self.assertFalse(gates["stage_clock_finite"])
        self.assertFalse(gates["native_threads_bounded"])
        self.assertFalse(gates["provider_policy_budget_one"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(gates["pid_matches"])

    def test_known_v1_preimport_passes_v2_without_altering_v1(self):
        raw = read(ROOT / "results/codec-allocation/01_off_dense/preimport-ready.json")
        checked = raw["stage_ready_perf_counter"] + 1.0
        diagnostic = probe.stage_diagnostics(raw, "preimport", raw["pid"], checked - 2.0,
                                             checked + 90.0, checked + 480.0, None, checked)
        self.assertTrue(all(diagnostic["predicates"].values()))
        freeze = read(ROOT / "fixtures/codec-allocation/implementation.json")
        self.assertEqual(sha256(ROOT / "fixtures/codec-allocation/protocol.json"), freeze["protocol_sha256"])
        for field in ("new_source_files_sha256", "frozen_dependency_files_sha256", "review_tool_files_sha256"):
            for relative, expected in freeze[field].items():
                self.assertEqual(sha256(ROOT / relative), expected, relative)

    def test_v2_changes_no_measurement_math_or_numeric_controls(self):
        previous = read(ROOT / "fixtures/codec-allocation/protocol.json")
        current = probe.protocol_template("2026-10-18T01:06:33+00:00")
        saved = read(ROOT / "fixtures/codec-allocation-v2/protocol.json")
        self.assertIs(probe.validate_protocol(saved), saved)
        self.assertEqual(saved["source_paths"], list(probe.SOURCE_PATHS))
        self.assertEqual(saved["review_tool_paths"], list(probe.REVIEW_PATHS))
        self.assertEqual(saved["frozen_dependency_paths"], list(probe.DEPENDENCY_PATHS))
        for key in ("config", "cases_in_order", "training", "model", "boundaries", "allocator_identity_policy", "measurement_gate"):
            self.assertEqual(current[key], previous[key], key)
        old_ast = ast.parse((ROOT / "experiments/codec_allocation_probe.py").read_text(encoding="utf-8"))
        new_ast = ast.parse((ROOT / "experiments/codec_allocation_v2.py").read_text(encoding="utf-8"))
        names = ("LifetimeRegistry", "InstrumentedCodec", "extract_trace", "perform_study", "prepare", "finalize_trace",
                 "worker", "validate_operation", "math_controls")
        for name in names:
            old = next(node for node in old_ast.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name)
            new = next(node for node in new_ast.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name)
            self.assertEqual(ast.dump(old, include_attributes=False), ast.dump(new, include_attributes=False), name)

    def test_suite_stops_first_failed_case_and_never_retries(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(probe, "validate_freeze", return_value=({}, {})), \
                mock.patch.object(probe.obs, "sha256_file", return_value="f" * 64), \
                mock.patch.object(probe, "run_case", return_value={"passed": False}) as case:
            output = Path(directory) / "fresh"
            result = probe.acceptance({}, None, None, None, Path("protocol"), Path("freeze"), output)
        case.assert_called_once()
        self.assertFalse(result["passed"])
        self.assertEqual(result["suite_launches"], 1)
        self.assertEqual(result["retries"], 0)
        self.assertEqual(len(result["cases"]), 1)


if __name__ == "__main__":
    unittest.main()
