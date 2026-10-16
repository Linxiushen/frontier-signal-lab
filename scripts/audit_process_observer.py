"""Independently audit recorded Windows observer receipts with stdlib only.

This module never imports or runs the observer, opens OS process handles, or
launches a process. Passing means receipt/hash/algebra consistency, not an OS
remeasurement or authentication of deliberately rewritten evidence.
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
SOURCE_PATHS = ("experiments/process_observer.py", "experiments/process_observer_probe.py", "tests/test_process_observer.py")
CASES = (("healthy32", 33554432, "healthy"), ("healthy64", 67108864, "healthy"),
         ("private_cap64", 67108864, "private_cap"), ("timeout_descendant", 0, "timeout"),
         ("job_close_descendant", 0, "job_close"))
CONFIG = {"maximum_explicit_allocation_bytes_per_process": 67108864,
          "healthy_allocation_bytes": 33554432, "cap_control_allocation_bytes": 67108864,
          "actual_private_cap_increment_bytes": 50331648, "memory_comparison_tolerance_bytes": 4194304,
          "minimum_32mib_resident_and_private_increase_bytes": 25165824,
          "minimum_64mib_resident_and_private_increase_bytes": 58720256,
          "sampler_interval_seconds": 0.02, "maximum_cap_detection_seconds": 1.0,
          "handshake_timeout_seconds": 8.0, "barrier_timeout_seconds": 8.0,
          "healthy_completion_timeout_seconds": 8.0, "timeout_control_seconds": 1.5,
          "cleanup_timeout_seconds": 4.0, "total_timeout_seconds": 90.0, "maximum_json_bytes": 1048576}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def audit(report, protocol, freeze, *, protocol_sha256, freeze_sha256, actual_source_sha256,
          launch_sha256=None):
    """Collect failures, including incomplete/negative runs, without relabeling them passed."""
    checks = []

    def check(ok, label):
        checks.append({"check": label, "passed": bool(ok)})
        return bool(ok)

    def close(a, b, label):
        check(finite(a) and finite(b) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8), label)

    def stamp(value):
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp lacks timezone")
        return parsed

    def fingerprint(value):
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None

    def identity(value, label):
        pair = value["pid"], value["creation_filetime"]
        check(all(type(x) is int and x > 0 for x in pair), label + ":positive_native_identity")
        return pair

    def message(value, nonce, role, label):
        check(value.get("nonce") == nonce and value.get("role") == role, label + ":nonce_role")
        pid = value["pid"]
        check(type(pid) is int and pid > 0, label + ":positive_pid")
        return pid

    def reading(value, expected, label):
        check(identity(value, label) == expected, label + ":actual_interpreter_identity")
        check(finite(value["perf_counter"]) and value["perf_counter"] >= 0, label + ":monotonic_clock")
        memory = value["memory"]
        check(all(type(memory[k]) is int and memory[k] >= 0 for k in ("resident_bytes", "private_bytes", "peak_resident_bytes")), label + ":memory_bytes")
        check(memory["peak_resident_bytes"] >= memory["resident_bytes"], label + ":resident_peak")

    try:
        check(report["schema_version"] == protocol["schema_version"] == 1, "schema")
        check(report["experiment_id"] == protocol["experiment_id"] == "windows-interpreter-observer-engineering-v1", "experiment_identity")
        check(protocol["config"] == CONFIG, "frozen_numeric_protocol")
        check(tuple(protocol["source_paths"]) == SOURCE_PATHS, "declared_sources")
        check([(x["id"], x["allocation_bytes"], x["mode"]) for x in protocol["cases_in_order"]] == list(CASES), "declared_fixed_case_order")
        check(freeze["protocol_sha256"] == protocol_sha256 == report.get("protocol_sha256"), "protocol_file_hash")
        check(report.get("implementation_sha256") == freeze_sha256, "implementation_freeze_file_hash")
        expected_sources = freeze["new_source_files_sha256"]
        check(set(expected_sources) == set(SOURCE_PATHS) and all(fingerprint(x) for x in expected_sources.values()), "frozen_source_inventory")
        check(expected_sources == actual_source_sha256 == report.get("source_sha256"), "actual_source_file_hashes")
        check(fingerprint(freeze["python_executable_sha256"]) and report.get("launch_executable_sha256") == freeze["python_executable_sha256"], "frozen_launch_executable_hash")
        if launch_sha256 is not None:
            check(launch_sha256 == freeze["python_executable_sha256"], "actual_launch_executable_hash")
        declared, frozen = stamp(protocol["predeclared_at"]), stamp(freeze["frozen_at"])
        started, completed = stamp(report["started_at"]), stamp(report["completed_at"])
        check(declared <= frozen <= started <= completed, "protocol_freeze_run_chronology")
        check(report.get("protocol_predeclared_at") == protocol["predeclared_at"] and report.get("implementation_frozen_at") == freeze["frozen_at"], "reported_freeze_chronology")
        check(report.get("os_name") == "nt" and report.get("no_fallback") is True, "windows_no_fallback")
        check(report.get("passed") is True and not report.get("error"), "declared_acceptance_passed")
        check(finite(report["wall_seconds"]) and 0 <= report["wall_seconds"] <= CONFIG["total_timeout_seconds"], "whole_suite_90s_bound")
        cases = report["cases"]
        check([c.get("id") for c in cases] == [c[0] for c in CASES], "all_five_fixed_cases_in_order")
        check(len(cases) == 5 and all(c.get("passed") is True for c in cases), "all_cases_declared_passed")
        nonces = [c.get(k) for c in cases for k in ("nonce", "descendant_nonce")]
        check(all(fingerprint(x) for x in nonces) and len(set(nonces)) == len(nonces) == 10, "ten_unique_256bit_nonces")
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        check(False, "incomplete_suite_receipt:" + str(error))
        cases = report.get("cases", []) if isinstance(report.get("cases"), list) else []
        started = completed = None

    previous_completion = started
    for case, spec in zip(cases, CASES):
        case_id, count, mode = spec
        prefix = case_id + ":"
        try:
            check((case["id"], case["expected_explicit_allocation_bytes"], case["mode"]) == spec, prefix + "spec_identity")
            check(case.get("passed") is True and not any(case.get(k) for k in ("error", "cleanup_error", "job_close_error", "process_handle_close_error")), prefix + "no_hidden_failure")
            case_start, case_end = stamp(case["started_at"]), stamp(case["completed_at"])
            check(case_start <= case_end and (previous_completion is None or previous_completion <= case_start) and (completed is None or case_end <= completed), prefix + "case_chronology")
            previous_completion = case_end
            check(finite(case["wall_seconds"]) and 0 <= case["wall_seconds"] <= CONFIG["total_timeout_seconds"], prefix + "finite_case_wall")
            launcher = case["launcher"]
            launcher_id = identity(launcher, prefix + "launcher")
            check(launcher.get("assigned_while_suspended") is True and launcher.get("job_handle_inherited") is False, prefix + "recorded_suspended_assignment_no_handle_inheritance")
            worker = case["worker_identity"]
            descendant = case["descendant_identity"]
            message(worker["self_receipt"], case["nonce"], "worker", prefix + "worker")
            message(descendant["self_receipt"], case["descendant_nonce"], "descendant", prefix + "descendant")
            worker_id = identity(worker["self_receipt"], prefix + "worker")
            desc_id = identity(descendant["self_receipt"], prefix + "descendant")
            check(worker_id != desc_id and worker_id[0] != desc_id[0], prefix + "distinct_worker_descendant")
            check(worker.get("launcher_differs_from_interpreter") is (launcher_id[0] != worker_id[0]), prefix + "launcher_interpreter_distinction")
            retained = {}
            for owner, actual_id, ancestor_id, label in ((worker, worker_id, launcher_id, "worker"), (descendant, desc_id, worker_id, "descendant")):
                chain = owner["verified_ancestry"]
                check(1 <= len(chain) <= 16, prefix + label + ":bounded_ancestry")
                pairs = [identity(x, prefix + label + ":ancestor") for x in chain]
                check(len({x[0] for x in pairs}) == len(pairs), prefix + label + ":acyclic_ancestry")
                check(pairs[0] == actual_id and pairs[-1] == ancestor_id, prefix + label + ":ancestry_endpoints")
                check(owner["self_receipt"]["parent_pid"] == chain[0]["parent_pid"], prefix + label + ":self_parent_matches_snapshot")
                check(all(x.get("job_member") is True for x in chain), prefix + label + ":recorded_job_membership")
                for i in range(len(chain) - 1):
                    check(chain[i]["parent_pid"] == chain[i + 1]["pid"] and chain[i + 1]["creation_filetime"] <= chain[i]["creation_filetime"], prefix + label + ":parent_creation_order")
                for pid, created in pairs:
                    check(pid not in retained or retained[pid] == created, prefix + "shared_retained_identity")
                    retained[pid] = created
                ready = owner["self_receipt"]
                executable = ready["runtime_executable_basename"]
                check(isinstance(executable, str) and bool(executable) and "/" not in executable and "\\" not in executable and fingerprint(ready["runtime_executable_sha256"]), prefix + label + ":runtime_executable_receipt")
            check(descendant["actual_pid"] == desc_id[0] and descendant["launcher_pid"] in [x["pid"] for x in descendant["verified_ancestry"]], prefix + "descendant_launcher_in_chain")
            check(worker["self_receipt"]["runtime_executable_sha256"] == descendant["self_receipt"]["runtime_executable_sha256"], prefix + "same_worker_descendant_runtime")
            samples = case["samples"]
            check(bool(samples), prefix + "samples_present")
            for i, sample in enumerate(samples):
                reading(sample, worker_id, prefix + "sample")
                if i:
                    check(samples[i - 1]["perf_counter"] <= sample["perf_counter"], prefix + "sample_order")
            brackets = case["memory_brackets"]
            for stage in ("baseline", "allocated"):
                bracket = brackets[stage]
                before, parent, after = (bracket[k] for k in ("self_before", "parent", "self_after"))
                for label, value in (("before", before), ("parent", parent), ("after", after)):
                    reading(value, worker_id, prefix + stage + ":" + label)
                message(before, case["nonce"], "worker", prefix + stage + ":before")
                message(after, case["nonce"], "worker", prefix + stage + ":after")
                check(parent in samples, prefix + stage + ":parent_sample_retained")
                tolerance = CONFIG["memory_comparison_tolerance_bytes"]
                calculated = {"same_identity": all((v["pid"], v["creation_filetime"]) == worker_id for v in (before, parent, after)),
                              "ordered_monotonic_bracket": before["perf_counter"] <= parent["perf_counter"] <= after["perf_counter"]}
                for metric, key in (("resident_bytes", "resident_within_tolerance"), ("private_bytes", "private_within_tolerance")):
                    lo, observed, hi = (v["memory"][metric] for v in (before, parent, after))
                    calculated[key] = min(lo, hi) - tolerance <= observed <= max(lo, hi) + tolerance
                calculated["passed"] = all(calculated.values())
                check(bracket["comparison"] == calculated and calculated["passed"], prefix + stage + ":independent_bracket_recalculation")
            check(brackets["baseline"]["self_after"]["perf_counter"] <= brackets["allocated"]["self_before"]["perf_counter"], prefix + "allocation_stage_order")
            deltas = {k: brackets["allocated"]["parent"]["memory"][k] - brackets["baseline"]["parent"]["memory"][k] for k in ("resident_bytes", "private_bytes")}
            minimum = {0: 0, 33554432: 25165824, 67108864: 58720256}[count]
            calculated = {"explicit_allocation_bytes": count, "parent_deltas_bytes": deltas, "minimum_required_increase_bytes": minimum,
                          "passed": count == 0 or all(d >= minimum for d in deltas.values())}
            check(case["allocation_check"] == calculated and calculated["passed"] and count <= 67108864, prefix + "independent_allocation_delta")
            if mode == "private_cap":
                limit = brackets["baseline"]["parent"]["memory"]["private_bytes"] + 50331648
                check(case["actual_interpreter_private_limit_bytes"] == limit and case.get("cap_is_sampled_not_kernel_hard_ceiling") is True, prefix + "sampled_private_limit")
                crossing = [s for s in samples if s["memory"]["private_bytes"] > limit]
                check(bool(crossing) and case["first_over_limit_sample"] == crossing[0] and brackets["allocated"]["parent"]["memory"]["private_bytes"] > limit, prefix + "actual_interpreter_first_cap_crossing")
                request_start, returned = case["termination_request_started_perf_counter"], case["termination_request_returned_perf_counter"]
                ready = brackets["allocated"]["self_before"]["perf_counter"]
                check(all(finite(x) for x in (request_start, returned)) and brackets["allocated"]["self_after"]["perf_counter"] <= request_start <= returned, prefix + "termination_request_chronology")
                elapsed = returned - ready
                close(case["allocation_ready_to_termination_seconds"], elapsed, prefix + "termination_return_latency_recomputed")
                check(0 <= elapsed <= 1.0, prefix + "cap_termination_return_within_1s")
                check(case.get("enforcement_reason") == "memory_private_limit" and case.get("termination_path") == "TerminateJobObject", prefix + "cap_reason_and_path")
            elif mode == "healthy":
                done = case["healthy_completion"]
                check(message(done, case["nonce"], "worker", prefix + "completion") == worker_id[0] and done["explicit_allocation_bytes"] == count and done["descendant_launcher_returncode"] == 0, prefix + "healthy_completion")
                check(case.get("enforcement_reason") == "normal_completion" and case.get("termination_path") is None, prefix + "no_false_termination")
            else:
                stalled = case["stalled_receipt"]
                check(message(stalled, case["nonce"], "worker", prefix + "stalled") == worker_id[0] and finite(stalled["perf_counter"]) and stalled["perf_counter"] >= brackets["allocated"]["self_after"]["perf_counter"], prefix + "stalled_after_memory_checks")
                if mode == "timeout":
                    begin, end = case["timeout_control_started_perf_counter"], case["timeout_control_completed_perf_counter"]
                    check(all(finite(x) for x in (begin, end)) and stalled["perf_counter"] <= begin <= end, prefix + "timeout_control_chronology")
                    close(case["timeout_wait_seconds"], end - begin, prefix + "timeout_wait_recomputed")
                    close(case["timeout_deadline_perf_counter"], begin + 1.5, prefix + "timeout_deadline_recomputed")
                    check(end - begin >= 1.5, prefix + "no_early_1point5s_timeout")
                    check(end <= case["termination_request_started_perf_counter"] <= case["termination_request_returned_perf_counter"] and case["termination_request_started_perf_counter"] >= case["timeout_deadline_perf_counter"], prefix + "timeout_before_termination")
                    check(case.get("enforcement_reason") == "timeout" and case.get("termination_path") == "TerminateJobObject", prefix + "timeout_reason_path")
                else:
                    check(case.get("enforcement_reason") == "explicit_job_handle_close_control" and case.get("termination_path") == "KILL_ON_JOB_CLOSE; no TerminateJobObject", prefix + "close_control_path")
                    check(stalled["perf_counter"] <= case["job_close_started_perf_counter"] <= case["job_close_returned_perf_counter"], prefix + "close_control_chronology")
                    check(not any(k.startswith("termination_request_") for k in case), prefix + "no_explicit_terminate_receipt_for_close")
            cleanup = case["cleanup"]
            check(cleanup.get("all_retained_handles_exited") is True, prefix + "recorded_all_handles_exited")
            exits = cleanup["exit_codes"]
            exit_ids = [identity(x, prefix + "exit") for x in exits]
            check(len(exit_ids) == len(set(exit_ids)) and set(exit_ids) == set(retained.items()), prefix + "all_retained_identities_have_exit_receipts")
            check(all(type(x["exit_code"]) is int and 0 <= x["exit_code"] <= 0xFFFFFFFF for x in exits), prefix + "native_exit_codes")
            if mode == "healthy":
                check(all(x["exit_code"] == 0 for x in exits), prefix + "healthy_all_exit_zero")
            if mode == "job_close":
                check(cleanup.get("job_active_count") is None and cleanup.get("job_active_count_after_close_not_queryable") is True, prefix + "closed_job_count_unqueryable")
            else:
                check(type(cleanup.get("job_active_count")) is int and cleanup["job_active_count"] == 0, prefix + "job_active_zero")
            begin, end = cleanup["started_perf_counter"], cleanup["completed_perf_counter"]
            check(all(finite(x) for x in (begin, end, cleanup["timeout_seconds"])) and 0 <= end - begin <= cleanup["timeout_seconds"] <= 4.0, prefix + "cleanup_within_4s")
            close(cleanup["wall_seconds"], end - begin, prefix + "cleanup_wall_recomputed")
            if mode in ("private_cap", "timeout"):
                check(case["termination_request_returned_perf_counter"] <= begin, prefix + "cleanup_after_termination_return")
            elif mode == "job_close":
                check(case["job_close_returned_perf_counter"] <= begin, prefix + "cleanup_after_close_return")
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as error:
            check(False, prefix + "incomplete_or_invalid_receipt:" + str(error))

    failures = [x["check"] for x in checks if not x["passed"]]
    return {"schema_version": 1, "passed": not failures, "receipt_consistency_passed": not failures,
            "checks_passed": sum(x["passed"] for x in checks), "check_count": len(checks), "failures": failures,
            "checks": checks, "scope": "Offline receipt/hash/algebra consistency only; no OS remeasurement or fresh process execution. Cannot authenticate coherently rewritten evidence or prove adversarial containment, continuous peaks, hard memory ceilings, model quality or historical observer validity."}


def bounded(path):
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= 1048576:
        raise ValueError("JSON receipt exceeds 1MiB or is empty")
    return raw, json.loads(raw)


def audit_files(report_path, protocol_path, freeze_path, python_path=None, root=ROOT):
    report_raw, report = bounded(report_path)
    protocol_raw, protocol = bounded(protocol_path)
    freeze_raw, freeze = bounded(freeze_path)
    result = audit(report, protocol, freeze, protocol_sha256=sha(protocol_raw), freeze_sha256=sha(freeze_raw),
                   actual_source_sha256={p: sha((Path(root) / p).read_bytes()) for p in SOURCE_PATHS},
                   launch_sha256=sha(Path(python_path).read_bytes()) if python_path else None)
    result.update(report_file_sha256=sha(report_raw), protocol_file_sha256=sha(protocol_raw), implementation_freeze_file_sha256=sha(freeze_raw))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "protocol", "freeze", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--python", type=Path)
    args = parser.parse_args(argv)
    result = audit_files(args.report, args.protocol, args.freeze, args.python)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("passed", "checks_passed", "check_count", "failures")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
