"""Post-outcome, evidence-specific audit of the codec v1 preimport failure.

Uses only the standard library and saved bytes. It imports neither the frozen
producer, reducer nor auditor and never starts a workload. This supplement was
written after the failure; it cannot change frozen execution acceptance.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CASE = "01_off_dense"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    raw = Path(path).read_bytes()
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("saved JSON exceeds 64 MiB supplement budget")
    return json.loads(raw)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def function(tree, name):
    matches = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == name]
    if len(matches) != 1:
        raise ValueError("static function identity differs: " + name)
    return matches[0]


def audit(result_dir, protocol_path=None, freeze_path=None, expected_review=None, root=ROOT):
    root, result_dir = Path(root), Path(result_dir)
    protocol_path = Path(protocol_path or root / "fixtures/codec-allocation/protocol.json")
    freeze_path = Path(freeze_path or root / "fixtures/codec-allocation/implementation.json")
    checks = {}

    def check(name, condition):
        checks[name] = bool(condition)

    protocol, freeze = read(protocol_path), read(freeze_path)
    report = read(result_dir / "report.json")
    case = report["cases"][0]
    separate = read(result_dir / (CASE + "-result.json"))
    ready = read(result_dir / CASE / "worker-ready.json")
    pre = read(result_dir / CASE / "preimport-ready.json")
    cleanup = case["failure_cleanup"]
    evidence_paths = ["report.json", CASE + "-result.json",
                      CASE + "/worker-ready.json", CASE + "/preimport-ready.json"]
    evidence_hashes = {p: digest((result_dir / p).read_bytes()) for p in evidence_paths}
    manifest_path = result_dir / "original-manifest.json"
    if manifest_path.exists():
        manifest = read(manifest_path)
        check("original_copy_manifest", manifest["all_original_files_sha256"] == evidence_hashes
              and manifest["original_files"] == 4 and manifest["copied_without_execution"] is True)
    if expected_review is not None:
        anchor = read(expected_review)
        check("anchored_raw_byte_hashes", evidence_hashes == anchor["evidence_files_sha256"])
        check("anchored_protocol_hash", digest(protocol_path.read_bytes()) == anchor["protocol_sha256"])
        check("anchored_freeze_hash", digest(freeze_path.read_bytes()) == anchor["freeze_sha256"])
    check("protocol_hash", digest(protocol_path.read_bytes()) == freeze["protocol_sha256"] == report["protocol_sha256"])
    check("freeze_hash", digest(freeze_path.read_bytes()) == report["implementation_sha256"])
    check("suite_payload_hash", digest(canonical({k: v for k, v in report.items() if k != "result_sha256"})) == report["result_sha256"])
    check("one_failed_prefix_case", len(report["cases"]) == 1 and case["id"] == CASE
          and case["spec"] == protocol["cases_in_order"][0]
          and case["spec"] == {"id": CASE, "observer_enabled": False, "method": "dense"}
          and case["passed"] is False and report["passed"] is False)
    check("one_suite_no_retry", report["suite_launches"] == 1 and report["retries"] == 0)
    check("separate_case_custody", case == separate)
    check("experiment_identity", protocol["schema_version"] == report["schema_version"] == 1
          and protocol["experiment_id"] == report["experiment_id"] == "pythia14m-matched-codec-allocation-cost-v1")
    check("chronology", dt.datetime.fromisoformat(protocol["predeclared_at"])
          <= dt.datetime.fromisoformat(freeze["frozen_at"])
          <= dt.datetime.fromisoformat(report["started_at"])
          <= dt.datetime.fromisoformat(case["started_at"])
          <= dt.datetime.fromisoformat(case["completed_at"])
          <= dt.datetime.fromisoformat(report["completed_at"]))
    frozen_files = {}
    for field in ("new_source_files_sha256", "frozen_dependency_files_sha256", "review_tool_files_sha256"):
        for path, expected in freeze[field].items():
            actual = digest((root / path).read_bytes())
            frozen_files[path] = actual
            check("frozen_file:" + path, actual == expected)
    check("frozen_source_inventory", set(freeze["new_source_files_sha256"]) == set(protocol["source_paths"]))
    check("frozen_dependency_inventory", set(freeze["frozen_dependency_files_sha256"]) == set(protocol["frozen_dependency_paths"]))
    check("frozen_review_tool_inventory", set(freeze["review_tool_files_sha256"]) == set(protocol["review_tool_paths"]))
    pre_review_path = root / "fixtures/codec-allocation/pre-execution-review.json"
    pre_review = read(pre_review_path)
    check("pre_execution_aggregate_custody", digest(pre_review_path.read_bytes()) == freeze["pre_execution_review_sha256"])
    check("prefreeze_reviews_and_guard_pass_recorded", all(pre_review[k]["passed"] is True
          for k in ("root", "guarded_tests", "producer_static_review", "auditor_static_review"))
          and pre_review["guarded_tests"]["tests_run"] == 27
          and pre_review["guarded_tests"]["forbidden_attempts"] == [])
    check("prefreeze_root_source_hashes", all(digest((root / p).read_bytes()) == h
          for p, h in pre_review["root"]["files_sha256"].items()))
    check("prefreeze_guarded_bytes_stable", pre_review["guarded_tests"]["before_sha256"]
          == pre_review["guarded_tests"]["after_sha256"] == pre_review["root"]["files_sha256"])

    # Parse frozen code as data; never import, compile, eval or execute its AST.
    producer = ast.parse((root / "experiments/codec_allocation_probe.py").read_bytes())
    prior = ast.parse((root / "experiments/training_observer_v3.py").read_bytes())
    process = ast.parse((root / "experiments/process_observer.py").read_bytes())
    run_case, worker = function(producer, "run_case"), function(producer, "worker")
    validator = function(prior, "validate_provider")
    calls = [n for n in ast.walk(run_case) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "validate_provider"
             and len(n.args) == 3 and isinstance(n.args[2], ast.IfExp)]
    check("static_stage_validator_call_unique", len(calls) == 1)
    budget_rule = ast.unparse(calls[0].args[2])
    check("static_preimport_expected_budget_zero", budget_rule == "0 if stage == 'preimport' else 1")
    guard_calls = [n for n in ast.walk(worker) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr == "LocalProviderGuard"]
    check("static_worker_guard_budget_enabled", len(guard_calls) == 1
          and isinstance(guard_calls[0].args[1], ast.Constant) and guard_calls[0].args[1].value is True)
    prior_text = ast.unparse(prior)
    validator_text = ast.unparse(validator)
    check("static_guard_enabled_budget_one", "self.allowed_budget = 1 if allow_local_probe is True else 0" in prior_text)
    check("static_guard_receipt_exports_budget", "'allowed_local_probe_budget': self.allowed_budget" in prior_text)
    check("static_validator_budget_is_distinct_from_count", "('allowed_local_probe_budget', expected_budget)" in validator_text
          and "expected_count = 0 if phase in ('preimport', 'injected_import') else 1" in validator_text)
    normal_read_stage = ast.unparse(function(prior, "read_stage"))
    check("normal_prior_preimport_budget_one", "0 if report['mode'] == 'import_fail' else 1" in normal_read_stage)
    worker_text = ast.unparse(worker)
    held_text = ast.unparse(function(producer, "held_stage"))
    check("static_preimport_release_before_ML_import", worker_text.index("'preimport'")
          < worker_text.index("prior.import_packages()")
          and "require_control(directory, stage + '-continue.json'" in held_text)
    gate_line = next(n.lineno for n in ast.walk(run_case) if isinstance(n, ast.Raise)
                     and "codec held identity/provider/thread gate failed" in ast.unparse(n))
    retained_stage_lines = [n.lineno for n in ast.walk(run_case) if isinstance(n, ast.Assign)
                            and any(ast.unparse(t) == "report['stages'][stage]" for t in n.targets)]
    check("static_raw_failure_omission_explained", len(retained_stage_lines) == 1 and retained_stage_lines[0] > gate_line)

    check("raw_worker_custody", ready == case["worker_identity"]["self_receipt"])
    check("raw_preimport_omitted_from_stage_report", case["stages"] == {} and pre not in case.values())
    check("raw_nonce_role_identity", ready["nonce"] == pre["nonce"] == case["nonce"]
          and ready["role"] == pre["role"] == "worker"
          and ready["pid"] == pre["pid"] == case["worker_identity"]["os_image"]["pid"])
    check("parent_and_child_distinct", ready["pid"] != case["launcher"]["pid"]
          and ready["parent_pid"] == case["launcher"]["pid"])
    check("raw_preimport_stage", pre["stage"] == "preimport")
    check("raw_thread_gate", type(pre["native_thread_count"]) is int
          and 1 <= pre["native_thread_count"] <= protocol["config"]["maximum_native_threads"])
    check("raw_ML_not_imported", pre["torch_imported"] is False and pre["transformers_imported"] is False)
    guard = pre["provider_guard"]
    source = guard["provider_source"]
    denied = ["socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex",
              "socket.gethostbyaddr", "socket.sendto", "socket.bind"]
    provider_predicates = {
        "phase": guard.get("phase") == "preimport",
        "installed": guard.get("installed") is True,
        "python_audit_only": guard.get("python_audit_only") is True,
        "native_network_sandbox": guard.get("native_network_sandbox") is False,
        "external_providers_permitted": guard.get("external_providers_permitted") is False,
        "synthetic_probe_denials": type(guard.get("synthetic_probe_denials")) is int and guard["synthetic_probe_denials"] == 1,
        "unexpected_denied_events": guard.get("unexpected_denied_events") == [],
        "denied_audit_events": guard.get("denied_audit_events") == denied,
        "policy_id": guard.get("policy_id") == "urllib3-ipv6-loopback-capability-probe-v1",
        "source_relative_path": source.get("package_relative_path") == "urllib3/util/connection.py",
        "source_hash": source.get("sha256") == protocol["provider_custody"]["provider_source_sha256"] == freeze["provider_source_sha256"],
        "source_path_hash_format": isinstance(source.get("normalized_path_sha256"), str)
            and re.fullmatch("[0-9a-f]{64}", source["normalized_path_sha256"]) is not None,
        "allowed_local_probe_budget": type(guard.get("allowed_local_probe_budget")) is int and guard["allowed_local_probe_budget"] == 0,
        "allowed_local_probe_count": type(guard.get("allowed_local_probe_count")) is int and guard["allowed_local_probe_count"] == 0,
        "diagnostic_event_limit": type(guard.get("diagnostic_event_limit")) is int and guard["diagnostic_event_limit"] == 4,
        "diagnostic_overflow_count": type(guard.get("diagnostic_overflow_count")) is int and guard["diagnostic_overflow_count"] == 0,
        "observed_event_count": type(guard.get("observed_event_count")) is int and guard["observed_event_count"] == 0,
        "diagnostic_events": guard.get("diagnostic_events") == [],
    }
    failed_provider_predicates = [k for k, v in provider_predicates.items() if not v]
    check("single_observed_provider_contract_mismatch", failed_provider_predicates == ["allowed_local_probe_budget"]
          and guard["allowed_local_probe_budget"] == 1)
    check("provider_path_identity_matches_freeze", source["normalized_path_sha256"] == freeze["provider_source_path_sha256"])
    check("reported_failure_is_exact_gate", case["error"] == "ObserverError: codec held identity/provider/thread gate failed: preimport")
    check("no_admitted_release_or_operation", case["controller_controls"] == case["worker_controls"] == []
          and "operation" not in case and "completion" not in case
          and case["censuses"] == case["role_decisions"] == [] and report["math_controls"] == {})
    case_dirs = [p.name for p in result_dir.iterdir() if p.is_dir()
                 and re.fullmatch(r"\d{2}_(on|off)_(dense|int8)", p.name)]
    check("only_first_workload_directory", sorted(case_dirs) == [CASE])
    check("complete_first_case_file_inventory", sorted(p.name for p in (result_dir / CASE).iterdir())
          == ["preimport-ready.json", "worker-ready.json"])
    check("only_first_case_result", sorted(p.name for p in result_dir.glob("*-result.json")) == [CASE + "-result.json"])

    ancestry = case["worker_identity"]["verified_ancestry"]
    identities = {(r["pid"], r["creation_filetime"]) for r in ancestry}
    expected_identities = {(ready["pid"], ready["creation_filetime"]),
                           (case["launcher"]["pid"], case["launcher"]["creation_filetime"])}
    check("two_retained_ancestry_identities", len(ancestry) == 2 and identities == expected_identities
          and all(r["job_member"] is True for r in ancestry))
    check("stored_executable_custody", case["executables_sha256"] == freeze["executables_sha256"]
          and case["executable_path_sha256"] == freeze["executable_path_sha256"]
          and ready["self_executable"]["sha256"] == freeze["executables_sha256"]["launcher"]
          and ready["self_executable"]["normalized_path_sha256"] == freeze["executable_path_sha256"]["launcher"])
    for name, role in (("launcher", "launcher"), ("worker_identity", "base_python")):
        image = case[name]["os_image"]
        check("retained_image:" + name, image["sha256"] == freeze["executables_sha256"][role]
              and image["queried_from_retained_handle"] is True and image["matches_frozen_path_and_hash"] is True
              and (image["pid"], image["creation_filetime"]) in expected_identities)
    exits = cleanup["exit_codes"]
    check("failure_cleanup_exact_retained_identities", len(exits) == 2
          and {(r["pid"], r["creation_filetime"]) for r in exits} == expected_identities)
    check("failure_cleanup_empty_job_and_exited", cleanup["all_retained_handles_exited"] is True
          and cleanup["job_active_count"] == 0)
    check("failure_cleanup_forced_codes", all(type(r["exit_code"]) is int and r["exit_code"] == 0xE003 for r in exits))
    terminate_text = ast.unparse(function(process, "terminate"))
    check("static_forced_termination_code", "TerminateJobObject(self.handle, 57347)" in terminate_text)
    decision_lower = max(case["launcher"]["os_image"]["verified_perf_counter"],
                         case["worker_identity"]["os_image"]["verified_perf_counter"], pre["stage_ready_perf_counter"])
    decision_upper = cleanup["started_perf_counter"]
    check("preimport_clock_predicates_by_recorded_bounds", all(finite(v) for v in [case["started_perf_counter"], ready["perf_counter"], pre["stage_ready_perf_counter"], decision_lower, decision_upper])
          and case["started_perf_counter"] <= ready["perf_counter"] <= pre["stage_ready_perf_counter"]
          <= decision_lower <= decision_upper < min(case["case_deadline_perf_counter"], case["suite_deadline_perf_counter"]))
    check("cleanup_and_case_timing", decision_upper <= cleanup["completed_perf_counter"] <= case["completed_perf_counter"]
          and abs(cleanup["wall_seconds"] - (cleanup["completed_perf_counter"] - cleanup["started_perf_counter"])) < 1e-9
          and 0 <= cleanup["wall_seconds"] <= cleanup["timeout_seconds"] == protocol["config"]["cleanup_timeout_seconds"]
          and abs(case["wall_seconds"] - (case["completed_perf_counter"] - case["started_perf_counter"])) < 1e-9)
    check("suite_timing", abs(report["wall_seconds"] - (dt.datetime.fromisoformat(report["completed_at"]) - dt.datetime.fromisoformat(report["started_at"])).total_seconds()) < .01)
    passed = all(checks.values())
    return {
        "schema_version": 1, "audited_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "review_kind": "post-outcome evidence-specific independent stdlib supplement",
        "passed": passed, "receipt_consistency": passed,
        "execution_acceptance": False if passed else None, "reported_execution_acceptance": report["passed"],
        "checks": checks, "check_count": len(checks), "evidence_files_sha256": evidence_hashes,
        "protocol_sha256": digest(protocol_path.read_bytes()), "freeze_sha256": digest(freeze_path.read_bytes()),
        "pre_execution_aggregate_sha256": digest(pre_review_path.read_bytes()),
        "frozen_files_sha256": frozen_files, "review_tool_sha256": digest(Path(__file__).read_bytes()),
        "suite_payload_sha256": report["result_sha256"],
        "diagnosis": {"classification": "preimport provider-budget caller/worker contract mismatch",
                      "actual_allowed_probe_budget": guard["allowed_local_probe_budget"],
                      "parent_expected_probe_budget": 0, "expected_and_observed_probe_count": 0,
                      "failed_provider_predicates": failed_provider_predicates,
                      "provider_predicates": provider_predicates,
                      "other_visible_outer_gate_predicates_pass": all(checks[k] for k in
                          ("raw_nonce_role_identity", "raw_preimport_stage", "raw_thread_gate",
                           "preimport_clock_predicates_by_recorded_bounds")),
                      "decision_time_recorded_interval": [decision_lower, decision_upper],
                      "raw_failure_omission": "preimport-ready.json exists, but report.stages is empty because the parent saves a stage only after validating it; frozen report is preserved."},
        "execution_counts": {"validated_against_this_evidence": passed,
                             "actual_suites": 1, "case_launches": 1, "successful_cases": 0,
                             "retained_process_exits": 2, "ML_imports": 0, "model_loads": 0,
                             "forwards": 0, "backwards": 0, "optimizer_updates": 0,
                             "raw_allocation_traces": 0, "operation_receipts": 0,
                             "basis": "Raw preimport flags, no release controls, exact gated source order and complete case file inventory; no live re-execution."},
        "cleanup": {"exact_retained_identity_set": sorted([list(v) for v in expected_identities]),
                    "exit_code": 57347, "exit_code_meaning": "0xE003 parent TerminateJobObject, not normal success",
                    "job_active_count": 0, "wall_seconds": cleanup["wall_seconds"]},
        "unperformed_registered_controls": list(protocol["saved_receipt_rejection_controls"]),
        "unperformed_control_reason": "No allocation trace, poststudy receipt or gradient operation was produced; none of the three registered actual-receipt mutation controls can be exercised on this outcome.",
        "limitations": [
            "The experiment failed. A consistent failure receipt does not accept the allocation/cost measurement or repair frozen code.",
            "The supplement was written after observing the outcome; it is not part of the pre-execution freeze or a retry.",
            "Raw byte anchoring requires --expected-review with the previously saved independent receipt; unanchored field checks alone are not a signature.",
            "Frozen source/JSON and retained-handle receipt identities are checked; no current executable, live process, OS isolation or native provider behavior is independently reproduced.",
            "The exact parent decision timestamp was not recorded. Source order and retained monotonic timestamps bound it before cleanup and below both deadlines.",
            "No forbidden provider event is observed in the raw preimport receipt; the guard is Python-audit-only and no OS network sandbox is claimed.",
            "No allocator events, callback workspace, timing comparison, training benefit, OS/GPU peak or quality result exists in this failed attempt."
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, default=ROOT / "results/codec-allocation")
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--expected-review", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit(args.result, args.protocol, args.freeze, args.expected_review)
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration) as error:
        result = {"passed": False, "execution_acceptance": None, "error": str(error)}
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
