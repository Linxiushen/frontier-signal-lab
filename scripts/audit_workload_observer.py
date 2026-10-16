"""Audit the fixed Torch/Windows engineering receipts with only Python stdlib.

No experiment import, Torch import, OS process query, child launch or remeasurement.
An audit establishes recorded hash/identity/algebra consistency, not authenticity
of coherently rewritten receipts or model quality, containment against attack,
continuous memory peaks, hard ceilings or historical scientific validity.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = "windows-torch-workload-observer-integration-v1"
PROTOCOL_SHA256 = "659146a5f05ed88b23886fefc3a389268883b88c5ad8b3a869712c1d27dbb463"
SOURCE_PATHS = ("experiments/workload_observer_probe.py", "tests/test_workload_observer.py")
DEPENDENCY_HASHES = {
    "experiments/process_observer.py": "3f247512aee1e50940d57e81a0290d658bad56cae098d45b2f92bb69deece175",
    "experiments/process_observer_probe.py": "cfbc7de447cdf7b1dbae98e34c9e642c7d7cc8d93343c961f6aec8f78ea31740",
    "fixtures/process-observer/protocol.json": "e4b77a96ab8aa1a2857b3156f485226791c877b923f847798eaad97e1f4b58a0",
    "fixtures/process-observer/implementation.json": "535c3e78a9abf53fd89452876796c1df8c39a5a8d2b21963f173f148fc03e954"}
CASES = (("healthy32", "healthy", 33554432), ("healthy64", "healthy", 67108864),
         ("busy_timeout", "timeout", 0), ("busy_private_cap64", "private_cap", 67108864),
         ("prehandshake_exit37", "prehandshake_fail", 0), ("injected_import_failure38", "import_fail", 0))
CONFIG = {"torch_version": "2.9.1+cpu", "intraop_threads": 2, "interop_threads": 2,
    "matrix_dimension": 1024, "manual_allocation_maximum_bytes": 67108864,
    "private_cap_increment_bytes": 50331648, "healthy32_minimum_delta_bytes": 25165824,
    "healthy64_minimum_delta_bytes": 58720256, "memory_bracket_tolerance_bytes": 4194304,
    "sampler_interval_seconds": 0.02, "maximum_recorded_sample_gap_seconds": 0.5,
    "handshake_timeout_seconds": 5.0, "import_workload_timeout_seconds": 12.0,
    "barrier_timeout_seconds": 5.0, "busy_timeout_seconds": 1.5,
    "busy_timeout_minimum_cpu_seconds": 0.25, "busy_backstop_seconds": 10.0,
    "cap_ready_to_termination_maximum_seconds": 1.0, "cleanup_timeout_seconds": 4.0,
    "case_timeout_seconds": 20.0, "total_timeout_seconds": 120.0, "maximum_json_bytes": 1048576,
    "prehandshake_expected_exit_code": 37, "import_failure_expected_exit_code": 38}
NATIVE_ARGUMENTS = ["/d", "/q", "/c", "set /p workload_observer_gate="]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def fingerprint(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def stamp(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp lacks timezone")
    return parsed


def audit(report, protocol, freeze, *, protocol_sha256, freeze_sha256,
          actual_source_sha256, actual_dependency_sha256, launch_sha256=None, native_sha256=None):
    """Collect failures and continue across partial/failed cases; never launder failure."""
    checks = []

    def check(ok, label):
        checks.append({"check": label, "passed": bool(ok)})
        return bool(ok)

    def close(a, b, label):
        return check(finite(a) and finite(b) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8), label)

    def identity(value, label):
        pair = value["pid"], value["creation_filetime"]
        check(all(type(x) is int and x > 0 for x in pair), label + ":positive_native_identity")
        return pair

    def message(value, nonce, pid, label):
        check(value.get("nonce") == nonce and value.get("role") == "worker"
              and type(value.get("pid")) is int and value["pid"] == pid, label + ":nonce_role_actual_pid")

    def reading(value, expected, label, cpu=False):
        check(identity(value, label) == expected, label + ":actual_interpreter_identity")
        check(finite(value["perf_counter"]) and value["perf_counter"] >= 0, label + ":monotonic_clock")
        memory = value["memory"]
        check(all(type(memory[k]) is int and memory[k] >= 0 for k in ("resident_bytes", "private_bytes", "peak_resident_bytes")), label + ":memory_bytes")
        check(memory["peak_resident_bytes"] >= memory["resident_bytes"], label + ":resident_peak")
        if cpu:
            check(finite(value["native_cpu_seconds"]) and value["native_cpu_seconds"] >= 0, label + ":native_cpu")

    def cleanup_receipt(case, retained, mode, prefix):
        cleanup = case["cleanup"]
        check(cleanup.get("all_retained_handles_exited") is True, prefix + "all_handles_recorded_exited")
        check(type(cleanup.get("job_active_count")) is int and cleanup["job_active_count"] == 0, prefix + "job_active_zero")
        exits = cleanup["exit_codes"]
        ids = [identity(x, prefix + "exit") for x in exits]
        check(len(ids) == len(set(ids)) and set(ids) == set(retained.items()), prefix + "all_retained_identities_have_exit_receipts")
        check(all(type(x["exit_code"]) is int and 0 <= x["exit_code"] <= 0xFFFFFFFF for x in exits), prefix + "native_exit_codes")
        if mode == "healthy":
            check(all(x["exit_code"] == 0 for x in exits), prefix + "healthy_all_exit_zero")
        elif mode == "prehandshake_fail":
            check(len(exits) == 1 and exits[0]["exit_code"] == 37, prefix + "expected_prehandshake_exit37")
        elif mode == "import_fail":
            worker_pid = case["worker_identity"]["self_receipt"]["pid"]
            launcher_pid = case["launcher"]["pid"]
            by_pid = {x["pid"]: x["exit_code"] for x in exits}
            check(by_pid.get(worker_pid) == by_pid.get(launcher_pid) == 38, prefix + "expected_worker_and_launcher_exit38")
        begin, end, budget = (cleanup[k] for k in ("started_perf_counter", "completed_perf_counter", "timeout_seconds"))
        check(all(finite(x) for x in (begin, end, budget)) and 0 <= end - begin <= budget <= 4.0, prefix + "cleanup_within_4s")
        close(cleanup["wall_seconds"], end - begin, prefix + "cleanup_wall_recomputed")
        # Independent durations must also fit the enclosing recorded case. Merely
        # shifting both cleanup timestamps preserves its local duration algebra.
        anchor = begin if mode == "prehandshake_fail" else case["worker_identity"]["self_receipt"]["perf_counter"]
        check(finite(anchor) and anchor <= begin <= end and end - anchor <= case["wall_seconds"] + 0.25,
              prefix + "known_event_span_fits_case_wall")
        if mode in ("timeout", "private_cap"):
            check(case["termination_request_returned_perf_counter"] <= begin, prefix + "cleanup_after_termination_return")
        return cleanup

    cases, suite_start, suite_end = [], None, None
    try:
        check(report["schema_version"] == protocol["schema_version"] == freeze["schema_version"] == 1, "schema")
        check(report["experiment_id"] == protocol["experiment_id"] == EXPERIMENT, "experiment_identity")
        check(protocol["config"] == CONFIG, "frozen_numeric_protocol")
        check(tuple(protocol["source_paths"]) == SOURCE_PATHS, "declared_sources")
        check(tuple(protocol["frozen_dependency_paths"]) == tuple(DEPENDENCY_HASHES), "declared_dependencies")
        check([(c["id"], c["mode"], c["manual_allocation_bytes"]) for c in protocol["cases_in_order"]] == list(CASES), "declared_fixed_case_order")
        check(protocol_sha256 == PROTOCOL_SHA256 == freeze["protocol_sha256"] == report.get("protocol_sha256"), "fixed_protocol_file_hash")
        check(report.get("implementation_sha256") == freeze_sha256, "implementation_freeze_file_hash")
        source_hashes = freeze["new_source_files_sha256"]
        check(set(source_hashes) == set(SOURCE_PATHS) and all(fingerprint(x) for x in source_hashes.values()), "frozen_source_inventory")
        check(source_hashes == actual_source_sha256 == report.get("source_sha256"), "actual_source_file_hashes")
        check(freeze["frozen_dependency_files_sha256"] == actual_dependency_sha256 == report.get("frozen_dependencies_sha256") == DEPENDENCY_HASHES, "unchanged_historical_dependency_hashes")
        for field, reported, measured, label in (
            ("python_executable_sha256", "launch_executable_sha256", launch_sha256, "launch"),
            ("native_executable_sha256", "native_executable_sha256", native_sha256, "native")):
            check(fingerprint(freeze[field]) and freeze[field] == report.get(reported), "frozen_" + label + "_executable_hash")
            if measured is not None:
                check(measured == freeze[field], "actual_" + label + "_executable_hash")
        check(report.get("launch_executable_basename", "").lower() == "python.exe"
              and report.get("native_executable_basename", "").lower() == "cmd.exe", "fixed_executable_basenames")
        declared, frozen = stamp(protocol["predeclared_at"]), stamp(freeze["frozen_at"])
        suite_start, suite_end = stamp(report["started_at"]), stamp(report["completed_at"])
        check(declared <= frozen <= suite_start <= suite_end, "protocol_freeze_run_chronology")
        check(report.get("protocol_predeclared_at") == protocol["predeclared_at"] and report.get("implementation_frozen_at") == freeze["frozen_at"], "reported_freeze_chronology")
        check(report.get("os_name") == "nt" and report.get("no_fallback") is True, "windows_no_fallback")
        check(report.get("passed") is True and not report.get("error")
              and report.get("final_wall_budget_exceeded") is not True, "declared_acceptance_passed")
        check(finite(report["wall_seconds"]) and 0 <= report["wall_seconds"] <= 120.0, "whole_suite_120s_bound")
        check(abs((suite_end - suite_start).total_seconds() - report["wall_seconds"]) <= 0.25, "suite_utc_and_monotonic_wall_agree")
        cases = report["cases"]
        check([c.get("id") for c in cases] == [c[0] for c in CASES], "all_six_fixed_cases_in_order")
        check(len(cases) == 6 and all(c.get("passed") is True for c in cases), "all_cases_declared_passed")
        nonces = [c.get("nonce") for c in cases]
        check(all(fingerprint(n) for n in nonces) and len(set(nonces)) == len(nonces) == 6, "six_unique_256bit_nonces")
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        check(False, "incomplete_suite_receipt:" + str(error))
        cases = report.get("cases", []) if isinstance(report, dict) and isinstance(report.get("cases"), list) else []

    previous_end = suite_start
    for case, spec in zip(cases, CASES):
        case_id, mode, allocation = spec
        prefix = case_id + ":"
        try:
            check((case["id"], case["mode"], case["expected_manual_allocation_bytes"]) == spec, prefix + "spec_identity")
            check(case.get("passed") is True and not any(case.get(k) for k in ("error", "cleanup_error", "job_close_error", "process_handle_close_error", "failure_cleanup", "final_wall_budget_exceeded")), prefix + "no_hidden_failure")
            begin, end = stamp(case["started_at"]), stamp(case["completed_at"])
            check(begin <= end and (previous_end is None or previous_end <= begin) and (suite_end is None or end <= suite_end), prefix + "case_chronology")
            previous_end = end
            check(finite(case["wall_seconds"]) and 0 <= case["wall_seconds"] <= 20.0, prefix + "case_20s_bound")
            check(abs((end - begin).total_seconds() - case["wall_seconds"]) <= 0.25, prefix + "case_utc_and_monotonic_wall_agree")
            nonce, launcher = case["nonce"], case["launcher"]
            launcher_id = identity(launcher, prefix + "launcher")
            check(launcher.get("assigned_while_suspended") is True and launcher.get("job_handle_inherited") is False, prefix + "suspended_assignment_no_job_handle_inheritance")
            retained = {launcher_id[0]: launcher_id[1]}
            if mode == "prehandshake_fail":
                control = case["prehandshake_control"]
                check(control == {"exit_code": 37, "handshake_absent": True, "actual_interpreter_identity_unavailable": True}, prefix + "exact_prehandshake_failure_control")
                check(not any(case.get(k) for k in ("worker_identity", "native_descendant", "workload_ready", "import_failure_receipt", "memory_brackets", "samples")), prefix + "no_substituted_actual_pid_or_workload")
                check(case.get("outcome") == "expected_prehandshake_exit37", prefix + "outcome")
                cleanup_receipt(case, retained, mode, prefix)
                continue

            worker = case["worker_identity"]
            ready = worker["self_receipt"]
            worker_id = identity(ready, prefix + "worker")
            message(ready, nonce, worker_id[0], prefix + "worker")
            reading(ready, worker_id, prefix + "worker_ready")
            check(worker.get("launcher_differs_from_interpreter") is (worker_id[0] != launcher_id[0]), prefix + "launcher_interpreter_distinction")
            check(ready.get("runtime_executable_basename", "").lower() == "python.exe" and fingerprint(ready.get("runtime_executable_sha256")), prefix + "actual_runtime_image_receipt")
            # Venv launcher bytes and actual base interpreter bytes may differ.
            chain = worker["verified_ancestry"]
            check(1 <= len(chain) <= 16, prefix + "bounded_ancestry")
            pairs = [identity(x, prefix + "ancestor") for x in chain]
            check(pairs[0] == worker_id and pairs[-1] == launcher_id and len({p[0] for p in pairs}) == len(pairs), prefix + "acyclic_ancestry_endpoints")
            check(ready["parent_pid"] == chain[0]["parent_pid"] and all(x.get("job_member") is True for x in chain), prefix + "self_parent_and_job_membership")
            for i, node in enumerate(chain):
                pid, creation = pairs[i]
                check(pid not in retained or retained[pid] == creation, prefix + "consistent_retained_identity")
                retained[pid] = creation
                if i + 1 < len(chain):
                    check(node["parent_pid"] == chain[i + 1]["pid"] and chain[i + 1]["creation_filetime"] <= creation, prefix + "parent_creation_order")
            native = case["native_descendant"]
            native_id = identity(native["os_identity"], prefix + "native")
            launch = native["launch_receipt"]
            message(launch, nonce, worker_id[0], prefix + "native_launch")
            check(native_id[0] not in retained and native["os_identity"]["parent_pid"] == worker_id[0]
                  and native_id[1] >= worker_id[1] and launch["native_pid"] == native_id[0], prefix + "native_direct_child_identity")
            retained[native_id[0]] = native_id[1]
            check(native.get("job_member") is True and native.get("no_native_self_report") is True, prefix + "native_os_identity_not_self_report")
            image = native["os_image"]
            check(image.get("basename", "").lower() == "cmd.exe" and image.get("matches_frozen") is True
                  and image.get("sha256") == freeze["native_executable_sha256"], prefix + "native_image_matches_frozen_hash")
            check(launch.get("command_arguments") == NATIVE_ARGUMENTS and launch.get("close_fds") is True
                  and launch.get("stdin_anonymous_pipe") is True and launch.get("shell") is False
                  and type(launch.get("creationflags")) is int and launch["creationflags"] == 0x08000000
                  and launch.get("stdout_devnull") is True and launch.get("stderr_devnull") is True,
                  prefix + "fixed_native_command_flags_and_pipe")
            if mode == "import_fail":
                failure = case["import_failure_receipt"]
                message(failure, nonce, worker_id[0], prefix + "import_failure")
                check(failure.get("stage") == "import" and failure.get("exception_type") == "ModuleNotFoundError"
                      and failure.get("missing_module") == "workload_observer_missing_dependency_" + nonce
                      and failure.get("torch_imported") is False and type(failure.get("optimizer_steps")) is int
                      and failure["optimizer_steps"] == 0 and failure.get("expected_exit_code") == case.get("expected_worker_exit_code") == 38, prefix + "exact_injected_import_failure")
                check(not any(case.get(k) for k in ("workload_ready", "memory_brackets", "samples")), prefix + "no_torch_workload_after_import_failure")
                check(case.get("outcome") == "expected_injected_import_failure38", prefix + "outcome")
                cleanup_receipt(case, retained, mode, prefix)
                continue

            workload = case["workload_ready"]
            message(workload, nonce, worker_id[0], prefix + "workload")
            op, threads = workload["operation"], workload["native_thread_counts"]
            check(workload.get("torch_version") == "2.9.1+cpu" and workload.get("intraop_threads") == workload.get("interop_threads") == 2, prefix + "actual_torch_cpu_and_thread_configuration")
            check(set(threads) == {"before_import", "before_operation", "after_operation"} and all(type(v) is int and v >= 1 for v in threads.values()), prefix + "raw_native_thread_counts")
            check(all(type(op.get(k)) is int and op[k] == 1 for k in ("forward_calls", "backward_calls", "optimizer_steps")), prefix + "exactly_one_engineering_update")
            check(finite(op["loss"]) and all(op.get(k) is True for k in ("gradient_finite", "parameters_finite", "parameter_changed")), prefix + "finite_update_and_changed_parameter")
            check(op.get("device") == "cpu" and op.get("dtype") == "torch.float32" and op.get("matrix_dimension") == 1024, prefix + "fixed_cpu_workload_shape")
            op_start, op_end, post_import = op["started_perf_counter"], op["completed_perf_counter"], workload["post_import_perf_counter"]
            check(all(finite(x) for x in (op_start, op_end, post_import)) and ready["perf_counter"] <= op_start <= op_end <= post_import, prefix + "operation_chronology")
            close(op["wall_seconds"], op_end - op_start, prefix + "operation_wall_recomputed")
            samples = case["samples"]
            check(bool(samples), prefix + "samples_present")
            for i, sample in enumerate(samples):
                reading(sample, worker_id, prefix + "sample", cpu=True)
                check(sample["perf_counter"] >= ready["perf_counter"], prefix + "sample_after_identity")
                if i:
                    check(samples[i - 1]["perf_counter"] <= sample["perf_counter"] and samples[i - 1]["native_cpu_seconds"] <= sample["native_cpu_seconds"], prefix + "sample_time_cpu_order")
            brackets = case["memory_brackets"]
            check(set(brackets) == {"baseline", "allocated"}, prefix + "two_memory_brackets")
            previous_time = post_import
            for stage in ("baseline", "allocated"):
                bracket = brackets[stage]
                before, parent, after = (bracket[k] for k in ("self_before", "parent", "self_after"))
                for key, value in (("self_before", before), ("parent", parent), ("self_after", after)):
                    reading(value, worker_id, prefix + stage + ":" + key, cpu=key == "parent")
                    if key != "parent": message(value, nonce, worker_id[0], prefix + stage + ":" + key)
                check(parent in samples, prefix + stage + ":parent_sample_recorded")
                order = before["perf_counter"] <= parent["perf_counter"] <= after["perf_counter"]
                same = all((value["pid"], value["creation_filetime"]) == worker_id for value in (before, parent, after))
                expected = {"same_identity": same, "ordered_monotonic_bracket": order}
                for metric in ("resident", "private"):
                    low, middle, high = [value["memory"][metric + "_bytes"] for value in (before, parent, after)]
                    expected[metric + "_within_tolerance"] = min(low, high) - 4194304 <= middle <= max(low, high) + 4194304
                expected["passed"] = all(expected.values())
                check(expected["passed"] and bracket["comparison"] == expected, prefix + stage + ":independent_bracket_recalculation")
                check(previous_time <= before["perf_counter"], prefix + stage + ":post_import_stage_chronology")
                previous_time = after["perf_counter"]
            allocation_record = case["allocation_check"]
            deltas = {key: brackets["allocated"]["parent"]["memory"][key] - brackets["baseline"]["parent"]["memory"][key] for key in ("resident_bytes", "private_bytes")}
            minimum = {0: 0, 33554432: 25165824, 67108864: 58720256}[allocation]
            expected_allocation = {"explicit_allocation_bytes": allocation, "parent_deltas_bytes": deltas,
                "minimum_required_increase_bytes": minimum, "passed": allocation == 0 or all(v >= minimum for v in deltas.values())}
            check(expected_allocation["passed"] and allocation_record == expected_allocation, prefix + "independent_allocation_delta")
            if mode == "healthy":
                done = case["healthy_completion"]
                message(done, nonce, worker_id[0], prefix + "completion")
                check(done.get("native_exit_code") == 0 and done.get("native_released_nonempty_line") is True
                      and type(done.get("optimizer_steps")) is int and done["optimizer_steps"] == 1, prefix + "healthy_native_completion")
                check(case.get("outcome") == "normal_completion" and not any(k.startswith("termination_request_") for k in case), prefix + "healthy_no_false_termination")
            else:
                busy, first, summary = case["busy_ready"], case["busy_first_operation"], case["busy_sampling"]
                message(busy, nonce, worker_id[0], prefix + "busy")
                message(first, nonce, worker_id[0], prefix + "first_busy_operation")
                check(type(busy.get("native_thread_count")) is int and busy["native_thread_count"] >= 1, prefix + "busy_native_threads_recorded")
                check(all(type(r.get(k)) is int and r[k] == 0 for r in (busy, first) for k in ("extra_backward_calls", "extra_optimizer_steps"))
                      and type(first.get("matmul_iterations_completed")) is int and first["matmul_iterations_completed"] == 1, prefix + "busy_no_extra_optimizer_or_backward")
                busy_start, busy_end = summary["started_perf_counter"], summary["completed_perf_counter"]
                check(all(finite(x) for x in (busy_start, busy_end, first["completed_perf_counter"])) and previous_time <= busy_start == busy["perf_counter"] <= first["completed_perf_counter"] <= busy_end, prefix + "busy_chronology")
                close(summary["wall_seconds"], busy_end - busy_start, prefix + "busy_wall_recomputed")
                selected = [sample for sample in samples if busy_start <= sample["perf_counter"] <= busy_end]
                points = [busy_start] + [sample["perf_counter"] for sample in selected] + [busy_end]
                gap = max(b - a for a, b in zip(points, points[1:]))
                cpu_delta = selected[-1]["native_cpu_seconds"] - selected[0]["native_cpu_seconds"] if len(selected) >= 2 else 0
                check(type(summary["samples_count"]) is int and summary["samples_count"] == len(selected) and bool(selected), prefix + "busy_sample_count_recomputed")
                close(summary["maximum_gap_including_boundaries_seconds"], gap, prefix + "busy_maxgap_recomputed")
                close(summary["native_cpu_delta_seconds"], cpu_delta, prefix + "busy_native_cpu_delta_recomputed")
                check(summary.get("gap_gate_passed") is True and gap <= 0.5, prefix + "busy_boundary_inclusive_gap_gate")
                request, returned = case["termination_request_started_perf_counter"], case["termination_request_returned_perf_counter"]
                live = case["pretermination_live_members"]
                check([identity(x, prefix + "pretermination") for x in live] == [worker_id, native_id]
                      and all(x.get("job_member") is True and x.get("alive") is True and finite(x["verified_perf_counter"])
                              and busy_end <= x["verified_perf_counter"] <= request for x in live), prefix + "both_actual_native_live_immediately_before_request")
                check(all(finite(x) for x in (request, returned)) and busy_end <= request <= returned, prefix + "termination_request_chronology")
                if mode == "timeout":
                    close(case["busy_deadline_perf_counter"], busy_start + 1.5, prefix + "timeout_deadline_recomputed")
                    check(busy_end - busy_start >= 1.5 and request >= case["busy_deadline_perf_counter"], prefix + "no_early_1point5s_timeout")
                    check(cpu_delta >= 0.25, prefix + "busy_minimum_native_cpu_progress")
                    check(case.get("outcome") == "timeout", prefix + "outcome")
                else:
                    limit = brackets["baseline"]["parent"]["memory"]["private_bytes"] + 50331648
                    check(case["actual_interpreter_private_limit_bytes"] == limit, prefix + "sampled_private_limit_from_postimport_baseline")
                    crossings = [s for s in samples if s["memory"]["private_bytes"] > limit and s["perf_counter"] >= brackets["allocated"]["self_before"]["perf_counter"]]
                    check(bool(crossings) and case["first_over_limit_sample"] == crossings[0]
                          and samples[-1]["memory"]["private_bytes"] > limit, prefix + "first_and_latest_private_crossing")
                    latency = returned - brackets["allocated"]["self_before"]["perf_counter"]
                    close(case["allocation_ready_to_termination_seconds"], latency, prefix + "cap_latency_recomputed")
                    check(0 <= latency <= 1.0, prefix + "cap_termination_return_within_1s")
                    check(case.get("outcome") == "memory_private_limit", prefix + "outcome")
            clean = cleanup_receipt(case, retained, mode, prefix)
            check(samples[-1]["perf_counter"] <= clean["started_perf_counter"] and (mode != "healthy" or previous_time <= clean["started_perf_counter"]), prefix + "cleanup_after_recorded_work")
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
            check(False, prefix + "incomplete_or_invalid_receipt:" + str(error))
    failures = [c["check"] for c in checks if not c["passed"]]
    omitted = [label for value, label in ((launch_sha256, "actual_launch_executable_hash"), (native_sha256, "actual_native_executable_hash")) if value is None]
    return {"schema_version": 1, "passed": not failures, "receipt_consistency_passed": not failures,
        "check_count": len(checks), "checks_passed": sum(c["passed"] for c in checks), "failures": failures,
        "checks": checks, "unperformed_optional_executable_file_checks": omitted,
        "scope": "Offline stdlib receipt/hash/algebra consistency only; no OS remeasurement, experiment import, Torch import or fresh process execution. Without --python/--native the corresponding executable bytes are not rehashed; those optional checks are explicitly omitted. Cannot authenticate coherently rewritten evidence or prove exact concurrent kernel threads, continuous peaks, hard ceilings, model quality or historical scientific validity."}


def bounded(path):
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= 1048576:
        raise ValueError("JSON receipt exceeds1MiB or is empty")
    def reject(value):
        raise ValueError("nonfinite JSON number: " + value)
    return raw, json.loads(raw, parse_constant=reject)


def audit_files(report_path, protocol_path, freeze_path, python_path=None, native_path=None, root=ROOT):
    raw, report = bounded(report_path)
    protocol_raw, protocol = bounded(protocol_path)
    freeze_raw, freeze = bounded(freeze_path)
    result = audit(report, protocol, freeze, protocol_sha256=sha(protocol_raw), freeze_sha256=sha(freeze_raw),
        actual_source_sha256={p: sha((Path(root) / p).read_bytes()) for p in SOURCE_PATHS},
        actual_dependency_sha256={p: sha((Path(root) / p).read_bytes()) for p in DEPENDENCY_HASHES},
        launch_sha256=sha(Path(python_path).read_bytes()) if python_path else None,
        native_sha256=sha(Path(native_path).read_bytes()) if native_path else None)
    result.update(report_file_sha256=sha(raw), protocol_file_sha256=sha(protocol_raw), implementation_freeze_file_sha256=sha(freeze_raw))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "protocol", "freeze", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--native", type=Path)
    args = parser.parse_args(argv)
    result = audit_files(args.report, args.protocol, args.freeze, args.python, args.native)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("passed", "check_count", "checks_passed", "failures")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
