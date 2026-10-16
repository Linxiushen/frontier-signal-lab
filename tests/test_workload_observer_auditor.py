"""Independent synthetic receipts and negative mutations; no experiment imports."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from scripts import audit_workload_observer as auditor

MIB = 1024 * 1024


def fixture():
    """Build report-shaped evidence without running or importing the producer."""
    sources = {p: "a" * 64 for p in auditor.SOURCE_PATHS}
    dependencies = dict(auditor.DEPENDENCY_HASHES)
    protocol = {"schema_version": 1, "experiment_id": auditor.EXPERIMENT,
        "predeclared_at": "2026-10-16T00:00:00+00:00", "config": dict(auditor.CONFIG),
        "source_paths": list(auditor.SOURCE_PATHS), "frozen_dependency_paths": list(dependencies),
        "cases_in_order": [{"id": i, "mode": m, "manual_allocation_bytes": n} for i, m, n in auditor.CASES]}
    freeze = {"schema_version": 1, "frozen_at": "2026-10-16T00:00:01+00:00",
        "protocol_sha256": auditor.PROTOCOL_SHA256, "new_source_files_sha256": sources,
        "frozen_dependency_files_sha256": dict(dependencies), "python_executable_sha256": "c" * 64,
        "native_executable_sha256": "e" * 64}
    report = {"schema_version": 1, "experiment_id": auditor.EXPERIMENT, "passed": True,
        "protocol_sha256": auditor.PROTOCOL_SHA256, "implementation_sha256": "d" * 64,
        "source_sha256": dict(sources), "frozen_dependencies_sha256": dict(dependencies),
        "launch_executable_basename": "python.exe", "launch_executable_sha256": "c" * 64,
        "native_executable_basename": "cmd.exe", "native_executable_sha256": "e" * 64,
        "protocol_predeclared_at": protocol["predeclared_at"], "implementation_frozen_at": freeze["frozen_at"],
        "started_at": "2026-10-16T00:00:02+00:00", "completed_at": "2026-10-16T00:01:00+00:00",
        "wall_seconds": 58.0, "os_name": "nt", "no_fallback": True, "cases": []}
    for index, (case_id, mode, allocation) in enumerate(auditor.CASES):
        tick, offset = 100.0 + index * 10, index * 1000
        nonce = f"{index + 1:064x}"

        def reading(clock, allocated=False):
            increase = allocation if allocated else 0
            return {"pid": offset + 2, "creation_filetime": 20, "perf_counter": clock,
                "memory": {"resident_bytes": 100 * MIB + increase, "private_bytes": 80 * MIB + increase,
                           "peak_resident_bytes": 100 * MIB + increase}}

        def message(**values):
            return {"nonce": nonce, "role": "worker", "pid": offset + 2, **values}

        def sample(clock, allocated=False):
            return {**reading(clock, allocated), "native_cpu_seconds": 1 + (clock - tick) * 0.5}

        utc_start = dt.datetime(2026, 10, 16, 0, 0, 3 + index * 10, tzinfo=dt.timezone.utc)
        case = {"id": case_id, "mode": mode, "expected_manual_allocation_bytes": allocation,
            "nonce": nonce, "passed": True, "started_at": utc_start.isoformat(),
            "completed_at": (utc_start + dt.timedelta(seconds=5)).isoformat(), "wall_seconds": 5.0,
            "launcher": {"pid": offset + 1, "creation_filetime": 10,
                "assigned_while_suspended": True, "job_handle_inherited": False}, "samples": []}
        retained = [(offset + 1, 10)]
        if mode == "prehandshake_fail":
            case.update(prehandshake_control={"exit_code": 37, "handshake_absent": True,
                "actual_interpreter_identity_unavailable": True}, outcome="expected_prehandshake_exit37")
        else:
            ready = message(**reading(tick), parent_pid=offset + 1,
                runtime_executable_basename="python.exe", runtime_executable_sha256="f" * 64)
            case["worker_identity"] = {"self_receipt": ready, "launcher_differs_from_interpreter": True,
                "verified_ancestry": [
                    {"pid": offset + 2, "creation_filetime": 20, "parent_pid": offset + 1, "job_member": True},
                    {"pid": offset + 1, "creation_filetime": 10, "parent_pid": 90000, "job_member": True}]}
            case["native_descendant"] = {"launch_receipt": message(native_pid=offset + 3,
                command_arguments=list(auditor.NATIVE_ARGUMENTS), close_fds=True, stdin_anonymous_pipe=True,
                shell=False, creationflags=0x08000000, stdout_devnull=True, stderr_devnull=True),
                "os_identity": {"pid": offset + 3, "creation_filetime": 30, "parent_pid": offset + 2},
                "os_image": {"basename": "cmd.exe", "sha256": "e" * 64, "matches_frozen": True},
                "job_member": True, "no_native_self_report": True}
            retained += [(offset + 2, 20), (offset + 3, 30)]
            if mode == "import_fail":
                case.update(import_failure_receipt=message(stage="import", exception_type="ModuleNotFoundError",
                    missing_module="workload_observer_missing_dependency_" + nonce, torch_imported=False,
                    optimizer_steps=0, expected_exit_code=38), expected_worker_exit_code=38,
                    outcome="expected_injected_import_failure38")
            else:
                case["workload_ready"] = message(torch_version="2.9.1+cpu", intraop_threads=2, interop_threads=2,
                    native_thread_counts={"before_import": 1, "before_operation": 6, "after_operation": 6},
                    operation={"forward_calls": 1, "backward_calls": 1, "optimizer_steps": 1, "loss": 1.0,
                        "gradient_finite": True, "parameters_finite": True, "parameter_changed": True,
                        "device": "cpu", "dtype": "torch.float32", "matrix_dimension": 1024,
                        "started_perf_counter": tick + 0.2, "completed_perf_counter": tick + 0.3, "wall_seconds": 0.1},
                    post_import_perf_counter=tick + 0.4)
                case["memory_brackets"] = {}
                for stage, clock in (("baseline", tick + 1), ("allocated", tick + 2)):
                    allocated = stage == "allocated"
                    parent = sample(clock + 0.05, allocated)
                    case["samples"].append(parent)
                    case["memory_brackets"][stage] = {"self_before": message(**reading(clock, allocated)),
                        "parent": parent, "self_after": message(**reading(clock + 0.1, allocated)),
                        "comparison": {"same_identity": True, "ordered_monotonic_bracket": True,
                            "resident_within_tolerance": True, "private_within_tolerance": True, "passed": True}}
                case["allocation_check"] = {"explicit_allocation_bytes": allocation,
                    "parent_deltas_bytes": {"resident_bytes": allocation, "private_bytes": allocation},
                    "minimum_required_increase_bytes": {0: 0, 33554432: 25165824, 67108864: 58720256}[allocation], "passed": True}
                if mode == "healthy":
                    case.update(outcome="normal_completion", healthy_completion=message(native_exit_code=0,
                        native_released_nonempty_line=True, optimizer_steps=1))
                else:
                    busy_start, busy_end = tick + 2.3, tick + (3.9 if mode == "timeout" else 2.5)
                    case["busy_ready"] = message(perf_counter=busy_start, native_thread_count=6,
                        extra_backward_calls=0, extra_optimizer_steps=0)
                    case["busy_first_operation"] = message(completed_perf_counter=busy_start + 0.01,
                        matmul_iterations_completed=1, extra_backward_calls=0, extra_optimizer_steps=0)
                    steps = 16 if mode == "timeout" else 2
                    selected = [sample(busy_start + i * 0.1, allocated=True) for i in range(steps + 1)]
                    # Stable exact boundary avoids an accidental float-rounding omission.
                    selected[-1]["perf_counter"] = busy_end
                    case["samples"] += selected
                    case["busy_sampling"] = {"started_perf_counter": busy_start, "completed_perf_counter": busy_end,
                        "wall_seconds": busy_end - busy_start, "samples_count": len(selected),
                        "maximum_gap_including_boundaries_seconds": 0.1,
                        "native_cpu_delta_seconds": selected[-1]["native_cpu_seconds"] - selected[0]["native_cpu_seconds"],
                        "gap_gate_passed": True}
                    case["pretermination_live_members"] = [{"pid": pid, "creation_filetime": created,
                        "job_member": True, "alive": True, "verified_perf_counter": busy_end + 0.01 + j * 0.01}
                        for j, (pid, created) in enumerate(retained[1:])]
                    case.update(termination_request_started_perf_counter=busy_end + 0.03,
                        termination_request_returned_perf_counter=busy_end + 0.04)
                    if mode == "timeout":
                        case.update(outcome="timeout", busy_deadline_perf_counter=busy_start + 1.5)
                    else:
                        case.update(outcome="memory_private_limit", actual_interpreter_private_limit_bytes=128 * MIB,
                            first_over_limit_sample=case["memory_brackets"]["allocated"]["parent"],
                            allocation_ready_to_termination_seconds=busy_end + 0.04 - (tick + 2))
        case["cleanup"] = {"all_retained_handles_exited": True, "job_active_count": 0,
            "exit_codes": [{"pid": pid, "creation_filetime": created,
                "exit_code": 0 if mode == "healthy" else 37 if mode == "prehandshake_fail"
                    else 38 if mode == "import_fail" and pid != offset + 3 else 0xE003} for pid, created in retained],
            "started_perf_counter": tick + 4.3, "completed_perf_counter": tick + 4.4,
            "wall_seconds": 0.1, "timeout_seconds": 4.0}
        report["cases"].append(case)
    return report, protocol, freeze, sources, dependencies


class WorkloadAuditorTests(unittest.TestCase):
    def run_audit(self, data, local_executables=True):
        report, protocol, freeze, sources, dependencies = data
        return auditor.audit(report, protocol, freeze, protocol_sha256=auditor.PROTOCOL_SHA256,
            freeze_sha256="d" * 64, actual_source_sha256=sources, actual_dependency_sha256=dependencies,
            launch_sha256="c" * 64 if local_executables else None,
            native_sha256="e" * 64 if local_executables else None)

    def rejects(self, mutation, label):
        data = fixture()
        mutation(data)
        result = self.run_audit(data)
        self.assertFalse(result["passed"], label)
        self.assertTrue(any(label in x for x in result["failures"]), result["failures"])

    def test_complete_independent_synthetic_receipts(self):
        result = self.run_audit(fixture())
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(result["unperformed_optional_executable_file_checks"], [])
        self.assertIn("no OS remeasurement", result["scope"])

    def test_optional_executable_file_checks_are_explicit(self):
        result = self.run_audit(fixture(), local_executables=False)
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(result["unperformed_optional_executable_file_checks"], ["actual_launch_executable_hash", "actual_native_executable_hash"])

    def test_fixed_protocol_source_and_historical_dependency_tamper(self):
        for mutation, label in [
            (lambda d: d[1]["config"].update(busy_timeout_seconds=0.1), "frozen_numeric_protocol"),
            (lambda d: d[1]["cases_in_order"].reverse(), "declared_fixed_case_order"),
            (lambda d: d[2].update(protocol_sha256="f" * 64), "fixed_protocol_file_hash"),
            (lambda d: d[3].update({auditor.SOURCE_PATHS[0]: "f" * 64}), "actual_source_file_hashes"),
            (lambda d: d[4].update({next(iter(d[4])): "f" * 64}), "unchanged_historical_dependency_hashes"),
            (lambda d: d[2].update(native_executable_sha256="f" * 64), "native_executable_hash"),
        ]:
            with self.subTest(label=label): self.rejects(mutation, label)

    def test_actual_identity_nonce_native_ancestry_and_command_tamper(self):
        for mutation, label in [
            (lambda d: d[0]["cases"][0]["worker_identity"]["self_receipt"].update(nonce="f" * 64), "nonce_role_actual_pid"),
            (lambda d: d[0]["cases"][0]["worker_identity"]["verified_ancestry"][0].update(parent_pid=9999), "parent_creation_order"),
            (lambda d: d[0]["cases"][0]["native_descendant"]["os_identity"].update(parent_pid=9999), "native_direct_child_identity"),
            (lambda d: d[0]["cases"][0]["native_descendant"]["os_image"].update(sha256="f" * 64), "native_image_matches_frozen_hash"),
            (lambda d: d[0]["cases"][0]["native_descendant"]["launch_receipt"].update(shell=True), "fixed_native_command_flags"),
            (lambda d: d[0]["cases"][0]["native_descendant"]["launch_receipt"].update(creationflags=0), "fixed_native_command_flags"),
            (lambda d: d[0]["cases"][0]["native_descendant"]["launch_receipt"].update(stdout_devnull=False), "fixed_native_command_flags"),
            (lambda d: d[0]["cases"][0]["native_descendant"]["launch_receipt"].update(stderr_devnull=False), "fixed_native_command_flags"),
            (lambda d: d[0]["cases"][0]["samples"][0].update(pid=1), "actual_interpreter_identity"),
        ]:
            with self.subTest(label=label): self.rejects(mutation, label)

    def test_operation_and_native_thread_tamper(self):
        for mutation, label in [
            (lambda d: d[0]["cases"][0]["workload_ready"]["operation"].update(loss=float("nan")), "finite_update"),
            (lambda d: d[0]["cases"][0]["workload_ready"]["operation"].update(optimizer_steps=2), "exactly_one_engineering_update"),
            (lambda d: d[0]["cases"][0]["workload_ready"].update(intraop_threads=64), "actual_torch_cpu_and_thread_configuration"),
            (lambda d: d[0]["cases"][0]["workload_ready"]["native_thread_counts"].update(after_operation=0), "raw_native_thread_counts"),
            (lambda d: d[0]["cases"][0]["workload_ready"]["operation"].update(completed_perf_counter=0), "operation_chronology"),
        ]:
            with self.subTest(label=label): self.rejects(mutation, label)

    def test_bracket_and_allocation_are_recomputed(self):
        self.rejects(lambda d: d[0]["cases"][0]["memory_brackets"]["allocated"]["self_after"].update(perf_counter=0), "independent_bracket_recalculation")
        self.rejects(lambda d: d[0]["cases"][0]["allocation_check"]["parent_deltas_bytes"].update(private_bytes=0), "independent_allocation_delta")

    def test_busy_boundary_gap_cpu_and_extra_work_tamper(self):
        for mutation, label in [
            (lambda d: d[0]["cases"][2]["busy_sampling"].update(maximum_gap_including_boundaries_seconds=0), "busy_maxgap_recomputed"),
            (lambda d: d[0]["cases"][2]["busy_sampling"].update(native_cpu_delta_seconds=99), "busy_native_cpu_delta_recomputed"),
            (lambda d: d[0]["cases"][2]["busy_first_operation"].update(extra_optimizer_steps=1), "busy_no_extra_optimizer_or_backward"),
            (lambda d: d[0]["cases"][2]["busy_sampling"].update(started_perf_counter=121.3), "busy_boundary_inclusive_gap_gate"),
        ]:
            with self.subTest(label=label): self.rejects(mutation, label)
        def no_progress(data):
            c = data[0]["cases"][2]
            for s in c["samples"]: s["native_cpu_seconds"] = 1.0
            c["busy_sampling"]["native_cpu_delta_seconds"] = 0.0
        self.rejects(no_progress, "busy_minimum_native_cpu_progress")

    def test_cap_crossing_time_and_live_members_tamper(self):
        for mutation, label in [
            (lambda d: d[0]["cases"][3].update(actual_interpreter_private_limit_bytes=500 * MIB), "sampled_private_limit"),
            (lambda d: d[0]["cases"][3].update(first_over_limit_sample=copy.deepcopy(d[0]["cases"][3]["samples"][0])), "first_and_latest_private_crossing"),
            (lambda d: d[0]["cases"][3].update(termination_request_returned_perf_counter=134, allocation_ready_to_termination_seconds=2), "cap_termination_return_within_1s"),
            (lambda d: d[0]["cases"][3]["pretermination_live_members"][1].update(alive=False), "both_actual_native_live"),
        ]:
            with self.subTest(label=label): self.rejects(mutation, label)

    def test_early_timeout_cleanup_missing_handle_and_false_healthy_tamper(self):
        for mutation, label in [
            (lambda d: d[0]["cases"][2]["busy_sampling"].update(completed_perf_counter=123), "no_early_1point5s_timeout"),
            (lambda d: d[0]["cases"][2]["cleanup"].update(job_active_count=1), "job_active_zero"),
            (lambda d: d[0]["cases"][2]["cleanup"]["exit_codes"].pop(), "all_retained_identities_have_exit_receipts"),
            (lambda d: d[0]["cases"][2]["cleanup"].update(completed_perf_counter=130), "cleanup_within_4s"),
            (lambda d: d[0]["cases"][1]["cleanup"]["exit_codes"][0].update(exit_code=1), "healthy_all_exit_zero"),
            (lambda d: d[0]["cases"][1].update(termination_request_started_perf_counter=114), "healthy_no_false_termination"),
        ]:
            with self.subTest(label=label): self.rejects(mutation, label)

    def test_exact_negative_controls_cannot_be_other_failures(self):
        for mutation, label in [
            (lambda d: d[0]["cases"][4]["prehandshake_control"].update(exit_code=1), "exact_prehandshake_failure_control"),
            (lambda d: d[0]["cases"][4].update(worker_identity={"pid": 4001}), "no_substituted_actual_pid"),
            (lambda d: d[0]["cases"][5]["import_failure_receipt"].update(missing_module="unrelated_dependency"), "exact_injected_import_failure"),
            (lambda d: d[0]["cases"][5]["import_failure_receipt"].update(torch_imported=True), "exact_injected_import_failure"),
            (lambda d: d[0]["cases"][5]["cleanup"]["exit_codes"][1].update(exit_code=1), "expected_worker_and_launcher_exit38"),
        ]:
            with self.subTest(label=label): self.rejects(mutation, label)

    def test_failed_partial_run_is_rejected_and_later_controls_still_audited(self):
        data = fixture()
        data[0].update(passed=False, error="retained failed suite")
        data[0]["cases"][0] = {"id": "healthy32", "passed": False, "error": "retained failed case"}
        data[0]["cases"][5]["import_failure_receipt"]["missing_module"] = "unrelated"
        result = self.run_audit(data)
        self.assertFalse(result["passed"])
        self.assertIn("declared_acceptance_passed", result["failures"])
        self.assertTrue(any("healthy32:incomplete_or_invalid_receipt" in x for x in result["failures"]))
        self.assertTrue(any("injected_import_failure38:exact_injected_import_failure" in x for x in result["failures"]))

    def test_explicit_wall_failure_flags_are_never_ignored(self):
        self.rejects(lambda d: d[0].update(final_wall_budget_exceeded=True), "declared_acceptance_passed")
        self.rejects(lambda d: d[0]["cases"][0].update(final_wall_budget_exceeded=True), "no_hidden_failure")

    def test_shifted_cleanup_cannot_escape_enclosing_case_wall(self):
        for index in (0, 2, 3, 5):
            def shift(data):
                clean = data[0]["cases"][index]["cleanup"]
                clean["started_perf_counter"] += 1000
                clean["completed_perf_counter"] += 1000
            with self.subTest(index=index): self.rejects(shift, "known_event_span_fits_case_wall")
        # With no handshake there is no worker clock anchor; even the recorded
        # cleanup interval must still fit its short enclosing case duration.
        def short_case(data):
            c = data[0]["cases"][4]
            c["wall_seconds"] = 0.01
            c["cleanup"].update(completed_perf_counter=c["cleanup"]["started_perf_counter"] + 0.5, wall_seconds=0.5)
        self.rejects(short_case, "known_event_span_fits_case_wall")

    def test_nonobject_root_produces_structured_failure(self):
        data = fixture()
        for root in ([], None, "invalid"):
            with self.subTest(root=root):
                result = self.run_audit((root, *data[1:]))
                self.assertFalse(result["passed"])
                self.assertTrue(any("incomplete_suite_receipt" in x for x in result["failures"]))

    def test_json_size_and_nonfinite_values_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "receipt.json"
            for payload in (b"{}" * 524289, b'{"loss":NaN}', b'{"loss":Infinity}', b""):
                path.write_bytes(payload)
                with self.subTest(size=len(payload)), self.assertRaises(ValueError): auditor.bounded(path)
            path.write_text(json.dumps({"passed": False, "error": "retained"}), encoding="utf-8")
            self.assertFalse(auditor.bounded(path)[1]["passed"])


if __name__ == "__main__":
    unittest.main()
