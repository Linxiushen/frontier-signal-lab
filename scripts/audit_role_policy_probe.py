"""Portable stdlib replay of saved narrow-role receipts; never starts a process.

An audit checks saved evidence and file-hash consistency. It is not fresh OS
measurement, proof against rewritten evidence, continuous process coverage,
loaded-code integrity, provider attestation, or permission to run training.
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
EXPERIMENT_ID = "windows-role-policy-probe-v1"
SOURCE_PATHS = ("experiments/role_policy_probe.py", "tests/test_role_policy_probe.py")
REVIEW_PATHS = ("scripts/audit_role_policy_probe.py", "tests/test_role_policy_probe_auditor.py")
DEPENDENCY_PATHS = (
    "experiments/dual_identity_census.py", "experiments/process_observer.py",
    "experiments/process_observer_probe.py", "experiments/workload_observer_probe.py",
    "fixtures/process-observer/protocol.json", "fixtures/process-observer/implementation.json",
    "fixtures/workload-observer/protocol.json", "fixtures/workload-observer/implementation.json",
    "fixtures/dual-identity-census/protocol.json", "fixtures/dual-identity-census/implementation.json",
)
CONFIG = {
    "case_timeout_seconds": 20.0, "suite_timeout_seconds": 65.0,
    "stage_timeout_seconds": 5.0, "cleanup_timeout_seconds": 4.0,
    "maximum_descendants": 16, "maximum_depth": 16, "maximum_json_bytes": 1048576,
}
CASES = (("healthy_role_admission", "none"), ("injected_python_rejection", "python"),
         ("injected_native_rejection", "native"))
NATIVE_ARGUMENTS = ["/d", "/q", "/c", "set /p workload_observer_gate="]
SELF_ROLES = {"worker": "launcher", "helper": "base_python"}
OS_ROLES = {"worker": "base_python", "helper": "base_python"}
EXECUTABLE_ROLES = {"launcher", "base_python", "native", "conhost"}
POLICY_CONTRACT = {
    "auxiliary_role": "console_auxiliary", "auxiliary_image_role": "conhost",
    "authorized_console_owner_roles": ["launcher", "native"], "auxiliaries_per_owner": 1,
    "pin_auxiliary_identity_across_stages": True, "allow_unregistered_same_image": False,
    "training_permitted": False,
}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def fingerprint(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def bounded(path):
    content = Path(path).read_bytes()
    if len(content) > CONFIG["maximum_json_bytes"]:
        raise ValueError("JSON exceeds fixed 1MiB bound")

    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("nonfinite JSON")

    return content, json.loads(content, object_pairs_hook=unique, parse_constant=nonfinite)


class Replay:
    """Independent raw-evidence checker; it does not call the producer policy."""

    def __init__(self):
        self.checks = []

    def check(self, condition, name):
        self.checks.append({"check": name, "passed": bool(condition)})
        return bool(condition)

    def identity(self, row, name):
        pair = row["pid"], row["creation_filetime"]
        self.check(all(type(value) is int and value > 0 for value in pair), name + ":PID_creation")
        return pair

    def span(self, row, lower, upper, maximum, name):
        start, end = row["started_perf_counter"], row["completed_perf_counter"]
        self.check(all(finite(value) for value in (start, end)) and
                   lower <= start <= end <= upper and end - start <= maximum,
                   name + ":bounded_clock_span")
        wall = row["wall_seconds"]
        self.check(finite(wall) and finite(start) and finite(end) and
                   math.isclose(wall, end - start, rel_tol=1e-10, abs_tol=1e-8),
                   name + ":wall_recomputed")
        return start, end

    @staticmethod
    def stamp(value):
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone missing")
        return result

    def message(self, row, nonce, role, pid, name):
        self.check(row.get("nonce") == nonce and row.get("role") == role and
                   type(row.get("pid")) is int and row["pid"] == pid,
                   name + ":nonce_role_PID")

    def no_ml(self, row, name, imports=False):
        self.check(row.get("training_permitted") is False and
                   type(row.get("model_loads")) is int and row["model_loads"] == 0 and
                   type(row.get("optimizer_steps")) is int and row["optimizer_steps"] == 0,
                   name + ":training_forbidden_zero_work")
        if imports:
            self.check(row.get("torch_imported") is False and row.get("transformers_imported") is False,
                       name + ":no_ML_imports")

    def image(self, node, role, executables, paths, name):
        value = node["image"]
        basename = value["basename"]
        matches = value["exact_path_matches"]
        self.check(isinstance(basename, str) and bool(basename) and
                   "/" not in basename and "\\" not in basename and
                   fingerprint(value["sha256"]) and fingerprint(value["normalized_path_sha256"]) and
                   value["queried_from_retained_handle"] is True and
                   value["retained_identity_stable"] is True,
                   name + ":retained_OS_image_complete")
        self.check(isinstance(matches, list) and matches == sorted(set(matches)) and
                   set(matches) <= EXECUTABLE_ROLES and
                   value["path_classification"] in ("exact_executable", "system32", "other") and
                   (value["path_classification"] == "exact_executable") == bool(matches),
                   name + ":path_classification")
        for match in matches:
            self.check(value["sha256"] == executables[match] and
                       value["normalized_path_sha256"] == paths[match],
                       name + ":declared_exact_path_matches_freeze")
        if role is not None:
            expected_basename = "cmd.exe" if role == "native" else "conhost.exe" if role == "conhost" else "python.exe"
            self.check(role in matches and value["sha256"] == executables[role] and
                       value["normalized_path_sha256"] == paths[role] and basename.lower() == expected_basename,
                       name + ":independent_exact_image_role")
        return value

    def ancestry(self, owner, nonce, role, ancestor, lower, upper, executables, paths, name):
        ready = owner["self_receipt"]
        pair = self.identity(ready, name)
        self.message(ready, nonce, role, pair[0], name)
        self.check(finite(ready["perf_counter"]) and lower <= ready["perf_counter"] <= upper,
                   name + ":ready_clock")
        chain = owner["verified_ancestry"]
        refs = [self.identity(row, name + ":ancestor") for row in chain]
        self.check(len(chain) == 2 and refs[0] == pair and refs[-1] == ancestor and
                   len({ref[0] for ref in refs}) == 2 and
                   ready["parent_pid"] == ancestor[0] and chain[0]["parent_pid"] == ancestor[0] and
                   all(row.get("job_member") is True for row in chain) and ancestor[1] <= pair[1],
                   name + ":exact_direct_parent_chain")
        expected = SELF_ROLES[role]
        value = ready["self_executable"]
        self.check(owner["self_executable_expected_role"] == expected and
                   owner["retained_os_image_expected_role"] == OS_ROLES[role] and
                   set(value) == {"source", "basename", "sha256", "normalized_path_sha256"} and
                   value["source"] == "sys.executable" and value["basename"].lower() == "python.exe" and
                   value["sha256"] == executables[expected] and
                   value["normalized_path_sha256"] == paths[expected] and
                   not any(key.startswith("runtime_executable_") for key in ready),
                   name + ":self_path_independent_role")
        return pair, chain

    def native(self, owner, nonce, worker, executables, name):
        pair = self.identity(owner["os_identity"], name)
        launch = owner["launch_receipt"]
        self.message(launch, nonce, "worker", worker[0], name + ":launch")
        self.check(launch["native_pid"] == pair[0] and launch["command_arguments"] == NATIVE_ARGUMENTS and
                   launch["close_fds"] is True and launch["stdin_anonymous_pipe"] is True and
                   launch["shell"] is False and launch["creationflags"] == 0x08000000 and
                   launch["stdout_devnull"] is True and launch["stderr_devnull"] is True,
                   name + ":fixed_native_command")
        image = owner["os_image"]
        self.check(owner["os_identity"]["parent_pid"] == worker[0] and pair[1] >= worker[1] and
                   owner["job_member"] is True and owner["no_native_self_report"] is True and
                   image["basename"].lower() == "cmd.exe" and image["sha256"] == executables["native"] and
                   image["matches_frozen"] is True,
                   name + ":retained_native_parent_image")
        return pair


def audit(report, protocol, freeze, *, protocol_sha256, freeze_sha256,
          actual_source_sha256, actual_dependency_sha256, actual_review_tools_sha256,
          executable_sha256=None):
    replay = Replay()
    check = replay.check
    summaries = []
    cases = []
    try:
        check(type(report["schema_version"]) is int and type(protocol["schema_version"]) is int and
              report["schema_version"] == protocol["schema_version"] == 1 and
              report["experiment_id"] == protocol["experiment_id"] == EXPERIMENT_ID,
              "schema_and_experiment")
        check(protocol["config"] == CONFIG and tuple(protocol["source_paths"]) == SOURCE_PATHS and
              tuple(protocol["frozen_dependency_paths"]) == DEPENDENCY_PATHS and
              tuple(protocol["review_tool_paths"]) == REVIEW_PATHS,
              "fixed_config_and_complete_file_sets")
        check([(case["id"], case["injection"]) for case in protocol["cases_in_order"]] == list(CASES) and
              protocol["training_permitted"] is False, "fixed_three_cases_no_training")
        check(protocol["policy_contract"] == report["policy_contract"] == POLICY_CONTRACT,
              "fixed_exact_one_narrow_policy")
        check(protocol["self_executable_roles"] == report["self_executable_roles"] == SELF_ROLES and
              protocol["retained_os_image_roles"] == report["retained_os_image_roles"] == OS_ROLES,
              "independent_self_and_OS_role_maps")
        check(fingerprint(protocol_sha256) and fingerprint(freeze_sha256) and
              freeze["protocol_sha256"] == report["protocol_sha256"] == protocol_sha256 and
              report["implementation_sha256"] == freeze_sha256,
              "protocol_freeze_report_hash_chain")
        for field, names, actual, result_field in (
            ("new_source_files_sha256", SOURCE_PATHS, actual_source_sha256, "source_sha256"),
            ("frozen_dependency_files_sha256", DEPENDENCY_PATHS, actual_dependency_sha256, "dependencies_sha256"),
            ("review_tools_sha256", REVIEW_PATHS, actual_review_tools_sha256, "review_tools_sha256"),
        ):
            values = freeze[field]
            check(set(values) == set(names) and all(fingerprint(value) for value in values.values()) and
                  values == actual == report[result_field], field + ":actual_file_hashes")
        executables = freeze["executables_sha256"]
        paths = freeze["executable_path_sha256"]
        check(set(executables) == set(paths) == EXECUTABLE_ROLES and
              all(fingerprint(value) for value in [*executables.values(), *paths.values()]) and
              executables == report["executables_sha256"] and paths == report["executable_path_sha256"],
              "four_exact_file_and_opaque_path_identities")
        if executable_sha256 is not None:
            check(executable_sha256 == executables, "optional_local_four_file_rehash")
        declared, frozen, started, ended = map(replay.stamp, (
            protocol["predeclared_at"], freeze["frozen_at"], report["started_at"], report["completed_at"]))
        check(declared <= frozen <= started <= ended and
              report["protocol_predeclared_at"] == protocol["predeclared_at"] and
              report["implementation_frozen_at"] == freeze["frozen_at"], "declaration_freeze_run_chronology")
        check(report["passed"] is True and report["os_name"] == "nt" and report["no_fallback"] is True and
              not report.get("error"), "reported_Windows_no_fallback_acceptance")
        replay.no_ml(report, "suite")
        suite_start, suite_end = replay.span(report, 0, float("inf"), 65, "suite")
        cases = report["cases"]
        check([(case["id"], case["injection"]) for case in cases] == list(CASES), "exact_three_case_order")
        nonces = [case[key] for case in cases for key in ("nonce", "helper_nonce")]
        check(len(nonces) == len(set(nonces)) == 6 and all(fingerprint(value) for value in nonces),
              "six_distinct_case_nonces")
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError) as error:
        check(False, "incomplete_suite:" + type(error).__name__)
        cases = []
        suite_start = suite_end = 0
        started = ended = None
        executables = paths = {}

    previous, previous_utc = suite_start, started
    total_snapshots = 0
    for case, (name, injection) in zip(cases, CASES):
        prefix = name + ":"
        try:
            check(case["passed"] is True and not any(case.get(key) for key in (
                "error", "cleanup_error", "job_close_error", "process_handle_close_error", "case_wall_budget_exceeded"))
                and "failure_cleanup" not in case, prefix + "no_hidden_failure")
            replay.no_ml(case, prefix + "case")
            case_start, case_end = replay.span(case, previous, suite_end, 20, prefix + "case")
            previous = case_end
            utc_start, utc_end = replay.stamp(case["started_at"]), replay.stamp(case["completed_at"])
            check(previous_utc <= utc_start <= utc_end <= ended, prefix + "UTC_case_order")
            previous_utc = utc_end
            launcher = replay.identity(case["launcher"], prefix + "launcher")
            check(case["launcher"]["assigned_while_suspended"] is True and
                  case["launcher"]["job_handle_inherited"] is False, prefix + "suspended_assign_no_inherit")
            worker, worker_chain = replay.ancestry(case["worker_identity"], case["nonce"], "worker", launcher,
                case_start, case_end, executables, paths, prefix + "worker")
            state = case["worker_policy_state"]
            replay.message(state, case["nonce"], "worker", worker[0], prefix + "worker_state")
            replay.no_ml(state, prefix + "worker_state", True)
            native = replay.native(case["native_descendant"], case["nonce"], worker, executables, prefix + "native")
            check(len({launcher[0], worker[0], native[0]}) == 3, prefix + "three_distinct_primary_PIDs")
            injected = None
            injected_chain = []
            if injection != "none":
                owner = case["injected_process"]
                check(owner["kind"] == injection, prefix + "precise_injection_kind")
                if injection == "python":
                    # The tighter authenticated-stage clock bound is checked once stage spans are known.
                    injected, injected_chain = replay.ancestry(owner, case["helper_nonce"], "helper", worker,
                        case_start, case_end, executables, paths, prefix + "injected_python")
                    launch = owner["launch_receipt"]
                    replay.message(launch, case["nonce"], "worker", worker[0], prefix + "helper_launch")
                    check(launch["helper_launcher_pid"] == injected[0] and
                          launch["base_executable_sha256"] == executables["base_python"] and
                          launch["shell"] is False and launch["close_fds"] is True and
                          launch["creationflags"] == 0x08000000, prefix + "fixed_helper_launch")
                else:
                    injected = replay.native(owner, case["nonce"], worker, executables, prefix + "injected_native")
                check(injected[0] not in {launcher[0], worker[0], native[0]}, prefix + "injected_identity_is_distinct")

            labels = ["before_native", "after_native"] + (["after_injection"] if injected else [])
            rows, decisions = case["censuses"], case["role_decisions"]
            check([row["label"] for row in rows] == labels and
                  [row["label"] for row in decisions] == labels, prefix + "exact_stage_order")
            check(len(rows) == len(decisions) == len(labels), prefix + "one_decision_per_census")
            total_snapshots += len(rows)
            retained = {}
            parent_links = {}
            image_links = {}
            pins = {}
            auxiliary_refs = {}
            last = case["worker_identity"]["self_receipt"]["perf_counter"]
            original_admitted = set()
            last_live = []
            for index, (row, decision, label) in enumerate(zip(rows, decisions, labels)):
                tag = prefix + label
                start, census_end = replay.span(row, last, case_end, 5, tag + ":census")
                decision_start, decision_end = replay.span(decision, start, case_end, 5, tag + ":decision")
                check(decision_start == start and census_end <= decision_end,
                      tag + ":decision_covers_census_and_hold")
                last = decision_end
                check(row["training_permitted"] is False and row["census_complete"] is True and
                      row["errors"] == [] and row["truncated"] is False and row["query_budget_exceeded"] is False and
                      row["all_known_present"] is True, tag + ":complete_no_error_inventory")
                nodes = row["processes"]
                refs = [replay.identity(node, tag) for node in nodes]
                by_pid = {node["pid"]: node for node in nodes}
                check(3 <= len(nodes) <= 17 and len(by_pid) == len(nodes) and
                      all(type(pid) is int for pid in row["observed_pids"]) and
                      row["observed_pids"] == sorted(by_pid) and
                      type(row["snapshot_observed_count"]) is int and row["snapshot_observed_count"] == len(nodes),
                      tag + ":bounded_unique_full_observed_set")
                check(all(type(row[key]) is int and row[key] == len(nodes)
                          for key in ("job_count_before", "job_count_after")) and
                      row["job_count_matches_before"] is True and row["job_count_matches_after"] is True,
                      tag + ":two_raw_job_counts_recomputed")
                primary = {launcher: "launcher", worker: "base_python"}
                if index:
                    primary[native] = "native"
                check(set(primary) <= set(refs), tag + ":all_exact_primary_refs")
                check((native[0] in by_pid) == bool(index), tag + ":native_creation_stage")
                check((injected[0] in by_pid) == (index == 2) if injected else True,
                      tag + ":injection_creation_stage")
                for node, ref in zip(nodes, refs):
                    check(node.get("job_member") is True and node.get("alive") is True and not node.get("error"),
                          tag + ":live_retained_same_job")
                    check(ref[0] not in retained or retained[ref[0]] == ref[1], tag + ":no_PID_reuse")
                    retained[ref[0]] = ref[1]
                    check(ref not in parent_links or parent_links[ref] == node["parent_pid"], tag + ":stable_parent")
                    parent_links[ref] = node["parent_pid"]
                    image = replay.image(node, primary.get(ref), executables, paths, tag)
                    check(ref not in image_links or image_links[ref] == image, tag + ":image_and_path_stable")
                    image_links[ref] = image
                    check(node["approved_known"] is (ref in primary) and
                          node["policy_role"] == primary.get(ref, "unapproved"), tag + ":raw_known_is_PID_creation")
                    cursor, visited = ref[0], set()
                    for _ in range(17):
                        if cursor == launcher[0]:
                            break
                        if cursor in visited or cursor not in by_pid or by_pid[cursor]["parent_pid"] not in by_pid:
                            raise ValueError("orphan_or_cyclic_tree")
                        visited.add(cursor)
                        child = by_pid[cursor]
                        parent = by_pid[child["parent_pid"]]
                        check(parent["creation_filetime"] <= child["creation_filetime"], tag + ":parent_creation_order")
                        cursor = parent["pid"]
                    check(cursor == launcher[0] and len(visited) <= 16, tag + ":bounded_launcher_tree")
                check(parent_links[worker] == launcher[0] and
                      (not index or parent_links[native] == worker[0]), tag + ":exact_primary_graph")
                raw_unknown = sorted(ref[0] for ref in refs if ref not in primary)
                check(all(type(pid) is int for pid in row["unapproved_pids"]) and
                      row["unapproved_pids"] == raw_unknown, tag + ":raw_unapproved_set")
                expected_primary = []
                for ref, role in primary.items():
                    parent = None if role == "launcher" else launcher if role == "base_python" else worker
                    expected_primary.append({"pid": ref[0], "creation_filetime": ref[1], "role": role,
                        "parent_ref": None if parent is None else {"pid": parent[0], "creation_filetime": parent[1]},
                        "frozen_image_sha256": executables[role], "frozen_path_sha256": paths[role]})
                expected_auxiliary = []
                for owner_role, owner_ref in [("launcher", launcher)] + ([("native", native)] if index else []):
                    candidates = [node for node in nodes if node["parent_pid"] == owner_ref[0] and
                                  node["image"]["sha256"] == executables["conhost"] and
                                  node["image"]["normalized_path_sha256"] == paths["conhost"] and
                                  "conhost" in node["image"]["exact_path_matches"]]
                    check(len(candidates) == 1, tag + ":exact_one_console_for_" + owner_role)
                    auxiliary = candidates[0]
                    replay.image(auxiliary, "conhost", executables, paths, tag + ":console")
                    auxiliary_ref = replay.identity(auxiliary, tag + ":console")
                    check(owner_ref[1] <= auxiliary_ref[1] and auxiliary_ref not in primary,
                          tag + ":exact_console_parent_creation")
                    pin = {"owner_ref": {"pid": owner_ref[0], "creation_filetime": owner_ref[1]},
                           "auxiliary_ref": {"pid": auxiliary_ref[0], "creation_filetime": auxiliary_ref[1]},
                           "frozen_image_sha256": executables["conhost"],
                           "frozen_path_sha256": paths["conhost"]}
                    check(owner_role not in pins or pins[owner_role] == pin, tag + ":pinned_console_identity")
                    pins[owner_role] = pin
                    auxiliary_refs[owner_role] = auxiliary_ref
                    expected_auxiliary.append({"pid": auxiliary_ref[0], "creation_filetime": auxiliary_ref[1],
                        "role": "console_auxiliary", "parent_ref": pin["owner_ref"], "owner_role": owner_role,
                        "frozen_image_sha256": executables["conhost"], "frozen_path_sha256": paths["conhost"]})
                admitted = set(primary) | set(auxiliary_refs.values())
                rejected = set(refs) - admitted
                if index == 0:
                    check(len(nodes) == 3 and not rejected, tag + ":exact_three_initial_roles")
                elif index == 1:
                    check(len(nodes) == 5 and not rejected, tag + ":exact_five_registered_roles")
                    original_admitted = set(admitted)
                else:
                    check(admitted == original_admitted and injected in rejected,
                          tag + ":original_five_stable_precise_target_rejected")
                    target = by_pid[injected[0]]
                    replay.image(target, "base_python" if injection == "python" else "native", executables, paths,
                                 tag + ":same_image_target")
                    check(target["parent_pid"] == worker[0] and target["creation_filetime"] == injected[1],
                          tag + ":injected_direct_worker_parent")
                    extra_aux = rejected - {injected}
                    check(len(extra_aux) <= 1 and len(nodes) == 6 + len(extra_aux), tag + ":bounded_negative_topology")
                    for ref in extra_aux:
                        node = by_pid[ref[0]]
                        replay.image(node, "conhost", executables, paths, tag + ":unregistered_owner_console")
                        check(node["parent_pid"] == injected[0] and injected[1] <= ref[1],
                              tag + ":unregistered_console_stays_rejected")
                expected_rejections = [{"pid": ref[0], "creation_filetime": ref[1],
                    "reason": "unregistered_parent_identity" if ref != injected else "unregistered_process_identity"}
                    for ref in sorted(rejected)]
                expected_admitted = index < 2
                requested = "create-native" if index == 0 else "finish" if injection == "none" or index == 2 else "create-injection"
                check(type(decision["census_index"]) is int and type(decision["decision_index"]) is int and
                      decision["census_index"] == decision["decision_index"] == index and
                      decision["training_permitted"] is False and decision["admitted"] is expected_admitted and
                      decision["requested_control"] == requested and
                      decision["permitted_control"] == (requested if expected_admitted else "reject"),
                      tag + ":decision_control_is_independently_replayed")
                check(all(type(pid) is int for pid in decision["admitted_pids"] + decision["rejected_pids"]) and
                      decision["primary_roles"] == expected_primary and decision["auxiliary_roles"] == expected_auxiliary and
                      decision["pinned_auxiliaries"] == pins and
                      decision["admitted_pids"] == sorted(ref[0] for ref in admitted) and
                      decision["rejected_pids"] == sorted(ref[0] for ref in rejected) and
                      decision["rejections"] == expected_rejections and
                      decision["errors"] == ([] if expected_admitted else ["unregistered_processes_present"]),
                      tag + ":all_policy_labels_and_errors_recomputed")
                for role_entry in decision["primary_roles"] + decision["auxiliary_roles"] + decision["rejections"]:
                    replay.identity(role_entry, tag + ":decision_ref")
                    if role_entry.get("parent_ref") is not None:
                        replay.identity(role_entry["parent_ref"], tag + ":decision_parent_ref")
                for pin_entry in decision["pinned_auxiliaries"].values():
                    replay.identity(pin_entry["owner_ref"], tag + ":pinned_owner_ref")
                    replay.identity(pin_entry["auxiliary_ref"], tag + ":pinned_auxiliary_ref")
                live = decision["held_liveness"]
                live_refs = [replay.identity(value, tag + ":held") for value in live]
                check(len(live) == len(nodes) and len(set(live_refs)) == len(live) and set(live_refs) == set(refs) and
                      all(type(decision[key]) is int and decision[key] == len(nodes)
                          for key in ("job_count_before", "job_count_after")), tag + ":complete_held_set_and_two_job_counts")
                held_previous = census_end
                for value in live:
                    instant = value["verified_perf_counter"]
                    check(value["alive"] is True and value["job_member"] is True and finite(instant) and
                          held_previous <= instant <= decision_end, tag + ":held_live_job_clock")
                    held_previous = instant
                last_live = live
            for ancestor in worker_chain + injected_chain:
                ref = replay.identity(ancestor, prefix + "authenticated_ancestor")
                check(retained.get(ref[0]) == ref[1] and parent_links.get(ref) == ancestor["parent_pid"],
                      prefix + "authenticated_parent_chain_matches_raw")
            if injected:
                if injection == "python":
                    instant = case["injected_process"]["self_receipt"]["perf_counter"]
                    check(decisions[1]["completed_perf_counter"] <= instant <= rows[2]["started_perf_counter"],
                          prefix + "helper_authenticated_only_after_release")
                rejection = case["rejection"]
                replay.identity(rejection["injected_ref"], prefix + "rejection_target_ref")
                check(rejection["injected_ref"] == {"pid": injected[0], "creation_filetime": injected[1]} and
                      rejection["injected_kind"] == injection and type(rejection["decision_index"]) is int and
                      rejection["decision_index"] == 2 and
                      rejection["unexpected_pids"] == decisions[-1]["rejected_pids"] and
                      rejection["original_five_identities_unchanged"] is True and
                      rejection["training_permitted"] is False and rejection["ML_release_absent"] is True,
                      prefix + "exact_negative_reason_no_release")
                terminate_start, terminate_end = case["termination_started_perf_counter"], case["termination_returned_perf_counter"]
                check(finite(terminate_start) and finite(terminate_end) and last <= terminate_start <= terminate_end <= case_end,
                      prefix + "held_before_termination_clock")
                check(case["outcome"] == "unregistered_" + injection + "_rejected_no_training" and
                      "completion" not in case, prefix + "precise_negative_outcome")
                anchor = terminate_end
            else:
                completion = case["completion"]
                replay.message(completion, case["nonce"], "worker", worker[0], prefix + "completion")
                replay.no_ml(completion, prefix + "completion", True)
                check(type(completion["native_exit_code"]) is int and completion["native_exit_code"] == 0 and
                      completion["native_released_nonempty_line"] is True and
                      case["outcome"] == "graceful_role_admission_no_training" and
                      not any(key in case for key in ("rejection", "injected_process", "termination_started_perf_counter")),
                      prefix + "graceful_finish_after_admitted_hold")
                anchor = last
            cleanup = case["cleanup"]
            clean_start, clean_end = replay.span(cleanup, anchor, case_end, 4, prefix + "cleanup")
            check(cleanup["all_retained_handles_exited"] is True and type(cleanup["job_active_count"]) is int and
                  cleanup["job_active_count"] == 0 and finite(cleanup["timeout_seconds"]) and
                  0 < cleanup["timeout_seconds"] <= 4 and
                  clean_end - clean_start <= cleanup["timeout_seconds"] + 1e-8,
                  prefix + "bounded_all_retained_exit_job_zero")
            exits = cleanup["exit_codes"]
            exit_refs = [replay.identity(row, prefix + "exit") for row in exits]
            check(len(set(exit_refs)) == len(exits) and set(exit_refs) == set(retained.items()),
                  prefix + "one_exit_for_every_observed_retained_identity")
            check(all(type(row["exit_code"]) is int and 0 <= row["exit_code"] < 2**32 for row in exits),
                  prefix + "all_exit_codes_preserved")
            codes = {ref: row["exit_code"] for ref, row in zip(exit_refs, exits)}
            if injected:
                controlled = {launcher, worker} | ({injected} if injection == "python" else set())
                check(all(codes.get(ref) == 57347 for ref in controlled), prefix + "held_control_termination_codes")
            else:
                check(all(code == 0 for code in codes.values()), prefix + "all_five_normal_exit_zero")
            summaries.append({"id": name, "snapshots": len(rows), "retained_exit_receipts": len(exits),
                              "final_admitted_pids": decisions[-1]["admitted_pids"],
                              "final_rejected_pids": decisions[-1]["rejected_pids"], "training_permitted": False})
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError, StopIteration) as error:
            check(False, prefix + "incomplete_receipt:" + type(error).__name__)
    check(total_snapshots == 8 and len(summaries) == 3, "three_complete_cases_eight_snapshots")
    failures = [row["check"] for row in replay.checks if not row["passed"]]
    return {"schema_version": 1, "audit_kind": "saved_narrow_role_policy_consistency", "passed": not failures,
            "training_permitted": False, "model_loads": 0, "optimizer_steps": 0,
            "check_count": len(replay.checks), "checks_passed": sum(row["passed"] for row in replay.checks),
            "failures": failures, "checks": replay.checks, "case_summaries": summaries, "scope": __doc__}


def audit_files(report_path, protocol_path=None, freeze_path=None, *, root=ROOT, executables=None):
    root = Path(root)
    protocol_path = Path(protocol_path) if protocol_path else root / "fixtures/role-policy-probe/protocol.json"
    freeze_path = Path(freeze_path) if freeze_path else root / "fixtures/role-policy-probe/implementation.json"
    report_bytes, report = bounded(report_path)
    protocol_bytes, protocol = bounded(protocol_path)
    freeze_bytes, freeze = bounded(freeze_path)
    result = audit(report, protocol, freeze, protocol_sha256=sha(protocol_bytes), freeze_sha256=sha(freeze_bytes),
        actual_source_sha256={name: sha((root / name).read_bytes()) for name in SOURCE_PATHS},
        actual_dependency_sha256={name: sha((root / name).read_bytes()) for name in DEPENDENCY_PATHS},
        actual_review_tools_sha256={name: sha((root / name).read_bytes()) for name in REVIEW_PATHS},
        executable_sha256={role: sha(Path(path).read_bytes()) for role, path in executables.items()} if executables else None)
    result.update(report_sha256=sha(report_bytes), protocol_sha256=sha(protocol_bytes), implementation_sha256=sha(freeze_bytes))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--freeze", type=Path)
    for role in ("launcher", "base-python", "native", "conhost"):
        parser.add_argument("--" + role, type=Path)
    args = parser.parse_args(argv)
    images = {"launcher": args.launcher, "base_python": args.base_python, "native": args.native, "conhost": args.conhost}
    if any(images.values()) and not all(images.values()):
        parser.error("supply all four optional local executable paths")
    result = audit_files(args.report, args.protocol, args.freeze, executables=images if all(images.values()) else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("passed", "training_permitted", "check_count", "checks_passed", "failures")}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
