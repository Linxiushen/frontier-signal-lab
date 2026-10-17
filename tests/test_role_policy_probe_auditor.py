"""Independent synthetic receipts and tampering only; no observer, OS or ML calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import audit_role_policy_probe as a


def fixture(optional_console=True):
    """Build a small declared topology directly, never through producer helpers."""
    source = {name: "1" * 64 for name in a.SOURCE_PATHS}
    dependencies = {name: "2" * 64 for name in a.DEPENDENCY_PATHS}
    reviews = {name: "3" * 64 for name in a.REVIEW_PATHS}
    executables = dict(zip(("launcher", "base_python", "native", "conhost"), ("a" * 64, "b" * 64, "c" * 64, "f" * 64)))
    paths = {name: str(index) * 64 for index, name in enumerate(executables, 4)}
    protocol = {"schema_version": 1, "experiment_id": "windows-role-policy-probe-v1",
        "predeclared_at": "2026-01-01T00:00:00Z", "config": dict(a.CONFIG),
        "source_paths": list(a.SOURCE_PATHS), "frozen_dependency_paths": list(a.DEPENDENCY_PATHS),
        "review_tool_paths": list(a.REVIEW_PATHS), "training_permitted": False,
        "self_executable_roles": dict(a.SELF_ROLES), "retained_os_image_roles": dict(a.OS_ROLES),
        "policy_contract": copy.deepcopy(a.POLICY_CONTRACT),
        "cases_in_order": [{"id": name, "injection": kind} for name, kind in a.CASES]}
    freeze = {"protocol_sha256": "d" * 64, "frozen_at": "2026-01-01T00:01:00Z",
        "new_source_files_sha256": dict(source), "frozen_dependency_files_sha256": dict(dependencies),
        "review_tools_sha256": dict(reviews), "executables_sha256": dict(executables),
        "executable_path_sha256": dict(paths)}
    flags = {"training_permitted": False, "model_loads": 0, "optimizer_steps": 0,
             "torch_imported": False, "transformers_imported": False}
    report = {"schema_version": 1, "experiment_id": protocol["experiment_id"], "passed": True,
        "os_name": "nt", "no_fallback": True, "training_permitted": False, "model_loads": 0, "optimizer_steps": 0,
        "policy_contract": copy.deepcopy(a.POLICY_CONTRACT), "self_executable_roles": dict(a.SELF_ROLES),
        "retained_os_image_roles": dict(a.OS_ROLES), "protocol_sha256": "d" * 64, "implementation_sha256": "e" * 64,
        "source_sha256": dict(source), "dependencies_sha256": dict(dependencies), "review_tools_sha256": dict(reviews),
        "executables_sha256": dict(executables), "executable_path_sha256": dict(paths),
        "protocol_predeclared_at": protocol["predeclared_at"], "implementation_frozen_at": freeze["frozen_at"],
        "started_at": "2026-01-01T00:02:00Z", "completed_at": "2026-01-01T00:02:30Z",
        "started_perf_counter": 100., "completed_perf_counter": 130., "wall_seconds": 30., "cases": []}
    for index, (name, injection) in enumerate(a.CASES):
        root = 100 + index * 100
        worker, native, launch_aux, native_aux, target, target_aux = (root + n for n in range(1, 7))
        start = 100. + index * 10
        nonce, helper_nonce = str(index * 2 + 1) * 64, str(index * 2 + 2) * 64
        created = {root: 1000 + index * 100, worker: 1002 + index * 100,
                   native: 1003 + index * 100, launch_aux: 1001 + index * 100,
                   native_aux: 1004 + index * 100, target: 1005 + index * 100, target_aux: 1006 + index * 100}
        parents = {root: 999, worker: root, native: worker, launch_aux: root, native_aux: native,
                   target: worker, target_aux: target}

        def ref(pid):
            return {"pid": pid, "creation_filetime": created[pid]}

        def ancestor(pid):
            return {**ref(pid), "parent_pid": parents[pid], "job_member": True}

        def message(pid, current_nonce=nonce, role="worker"):
            return {"pid": pid, "nonce": current_nonce, "role": role}

        def owner(pid, role, instant, current_nonce):
            path_role = "launcher" if role == "worker" else "base_python"
            return {"self_receipt": {**ancestor(pid), **message(pid, current_nonce, role), "perf_counter": instant,
                    "self_executable": {"source": "sys.executable", "basename": "python.exe",
                        "sha256": executables[path_role], "normalized_path_sha256": paths[path_role]}},
                    "verified_ancestry": [ancestor(pid), ancestor(parents[pid])],
                    "self_executable_expected_role": path_role, "retained_os_image_expected_role": "base_python"}

        def native_owner(pid):
            return {"launch_receipt": {**message(worker), "native_pid": pid,
                    "command_arguments": list(a.NATIVE_ARGUMENTS), "close_fds": True, "stdin_anonymous_pipe": True,
                    "shell": False, "creationflags": 0x08000000, "stdout_devnull": True, "stderr_devnull": True},
                    "os_identity": {**ref(pid), "parent_pid": worker},
                    "os_image": {"basename": "cmd.exe", "sha256": executables["native"], "matches_frozen": True},
                    "job_member": True, "no_native_self_report": True}

        def node(pid):
            image_role = "launcher" if pid == root else "native" if pid == native or (pid == target and injection == "native") else "conhost" if pid in (launch_aux, native_aux, target_aux) else "base_python"
            known_role = "launcher" if pid == root else "base_python" if pid == worker else "native" if pid == native else None
            return {**ancestor(pid), "alive": True, "policy_role": known_role or "unapproved", "approved_known": bool(known_role),
                "image": {"basename": "conhost.exe" if image_role == "conhost" else "cmd.exe" if image_role == "native" else "python.exe",
                    "sha256": executables[image_role], "normalized_path_sha256": paths[image_role],
                    "exact_path_matches": [image_role], "path_classification": "exact_executable",
                    "queried_from_retained_handle": True, "retained_identity_stable": True}}

        case = {"id": name, "injection": injection, "nonce": nonce, "helper_nonce": helper_nonce, "passed": True,
            "started_at": f"2026-01-01T00:02:{index * 10:02d}Z", "completed_at": f"2026-01-01T00:02:{index * 10 + 2:02d}Z",
            "started_perf_counter": start, "completed_perf_counter": start + 2., "wall_seconds": 2.,
            "training_permitted": False, "model_loads": 0, "optimizer_steps": 0,
            "launcher": {**ref(root), "assigned_while_suspended": True, "job_handle_inherited": False},
            "worker_identity": owner(worker, "worker", start + .1, nonce),
            "worker_policy_state": {**message(worker), **flags}, "native_descendant": native_owner(native),
            "censuses": [], "role_decisions": []}
        if injection == "python":
            case["injected_process"] = {"kind": injection, **owner(target, "helper", start + 1.1, helper_nonce),
                "launch_receipt": {**message(worker), "helper_launcher_pid": target,
                    "base_executable_sha256": executables["base_python"], "shell": False,
                    "close_fds": True, "creationflags": 0x08000000}}
        elif injection == "native":
            case["injected_process"] = {"kind": injection, **native_owner(target)}
        pins = {}
        for stage_index, label in enumerate(["before_native", "after_native"] + (["after_injection"] if injection != "none" else [])):
            pids = [root, worker, launch_aux] + ([native, native_aux] if stage_index else [])
            if stage_index == 2:
                pids += [target] + ([target_aux] if optional_console else [])
            nodes = [node(pid) for pid in sorted(pids)]
            begin = start + .2 + stage_index * .5
            end = begin + .05
            row = {"label": label, "training_permitted": False, "started_perf_counter": begin,
                "completed_perf_counter": end, "wall_seconds": end - begin, "processes": nodes,
                "observed_pids": sorted(pids), "snapshot_observed_count": len(pids),
                "job_count_before": len(pids), "job_count_after": len(pids), "job_count_matches_before": True,
                "job_count_matches_after": True, "all_known_present": True, "census_complete": True,
                "truncated": False, "query_budget_exceeded": False, "errors": [],
                "unapproved_pids": sorted(pid for pid in pids if pid not in (root, worker, native))}
            primary = []
            for pid, role, parent in [(root, "launcher", None), (worker, "base_python", root)] + ([(native, "native", worker)] if stage_index else []):
                primary.append({**ref(pid), "role": role, "parent_ref": ref(parent) if parent else None,
                    "frozen_image_sha256": executables[role], "frozen_path_sha256": paths[role]})
            aux = []
            for owner_role, owner_pid, aux_pid in [("launcher", root, launch_aux)] + ([("native", native, native_aux)] if stage_index else []):
                pins[owner_role] = {"owner_ref": ref(owner_pid), "auxiliary_ref": ref(aux_pid),
                    "frozen_image_sha256": executables["conhost"], "frozen_path_sha256": paths["conhost"]}
                aux.append({**ref(aux_pid), "role": "console_auxiliary", "parent_ref": ref(owner_pid), "owner_role": owner_role,
                    "frozen_image_sha256": executables["conhost"], "frozen_path_sha256": paths["conhost"]})
            rejected = sorted(pid for pid in pids if pid in (target, target_aux))
            requested = "create-native" if stage_index == 0 else "finish" if injection == "none" or stage_index == 2 else "create-injection"
            decision = {"label": label, "admitted": stage_index < 2, "training_permitted": False,
                "primary_roles": primary, "auxiliary_roles": aux, "admitted_pids": sorted(set(pids) - set(rejected)),
                "rejected_pids": rejected, "rejections": [{**ref(pid), "reason": "unregistered_process_identity" if pid == target else "unregistered_parent_identity"} for pid in rejected],
                "errors": ["unregistered_processes_present"] if rejected else [], "pinned_auxiliaries": copy.deepcopy(pins),
                "census_index": stage_index, "decision_index": stage_index, "requested_control": requested,
                "permitted_control": "reject" if rejected else requested, "started_perf_counter": begin,
                "completed_perf_counter": begin + .1, "wall_seconds": .1, "job_count_before": len(pids), "job_count_after": len(pids),
                "held_liveness": [{**ref(pid), "job_member": True, "alive": True, "verified_perf_counter": end + .001 * (n + 1)} for n, pid in enumerate(sorted(pids))]}
            case["censuses"].append(row)
            case["role_decisions"].append(decision)
        if injection == "none":
            case["completion"] = {**message(worker), **flags, "native_exit_code": 0, "native_released_nonempty_line": True}
            case["outcome"] = "graceful_role_admission_no_training"
        else:
            case["rejection"] = {"injected_ref": ref(target), "injected_kind": injection, "decision_index": 2,
                "unexpected_pids": list(case["role_decisions"][-1]["rejected_pids"]), "original_five_identities_unchanged": True,
                "training_permitted": False, "ML_release_absent": True, "reason": "controlled unexpected identity"}
            case["termination_started_perf_counter"] = start + 1.4
            case["termination_returned_perf_counter"] = start + 1.41
            case["outcome"] = "unregistered_" + injection + "_rejected_no_training"
        final_pids = case["censuses"][-1]["observed_pids"]
        case["cleanup"] = {"all_retained_handles_exited": True, "job_active_count": 0,
            "started_perf_counter": start + 1.5, "completed_perf_counter": start + 1.6, "wall_seconds": .1,
            "timeout_seconds": 3.5, "exit_codes": [{**ref(pid), "exit_code": 57347 if injection != "none" and (pid in (root, worker) or (injection == "python" and pid == target)) else 0} for pid in final_pids]}
        report["cases"].append(case)
    return report, protocol, freeze, {"protocol_sha256": "d" * 64, "freeze_sha256": "e" * 64,
        "actual_source_sha256": dict(source), "actual_dependency_sha256": dict(dependencies), "actual_review_tools_sha256": dict(reviews)}


class RolePolicyAuditorTests(unittest.TestCase):
    def setUp(self):
        self.report, self.protocol, self.freeze, self.kw = fixture()

    def audit(self):
        return a.audit(self.report, self.protocol, self.freeze, **self.kw)

    def reject(self, mutation):
        original = copy.deepcopy((self.report, self.protocol, self.freeze, self.kw))
        mutation()
        result = self.audit()
        self.assertFalse(result["passed"], result)
        self.assertTrue(result["failures"])
        self.report, self.protocol, self.freeze, self.kw = original

    def test_complete_synthetic_eight_stages_and_both_same_image_negatives(self):
        result = self.audit()
        self.assertTrue(result["passed"], result["failures"])
        self.assertEqual(sum(case["snapshots"] for case in result["case_summaries"]), 8)
        self.assertFalse(result["training_permitted"])
        self.assertEqual(result["model_loads"], 0)

    def test_optional_unapproved_console_need_not_exist(self):
        self.report, self.protocol, self.freeze, self.kw = fixture(False)
        self.assertTrue(self.audit()["passed"], self.audit()["failures"])

    def test_equal_launcher_base_bytes_keep_distinct_path_roles(self):
        old, new = self.freeze["executables_sha256"]["launcher"], self.freeze["executables_sha256"]["base_python"]
        def replace(value):
            if isinstance(value, dict):
                return {key: replace(child) for key, child in value.items()}
            if isinstance(value, list):
                return [replace(child) for child in value]
            return new if value == old else value
        self.report, self.freeze = replace(self.report), replace(self.freeze)
        self.assertTrue(self.audit()["passed"], self.audit()["failures"])

    def test_actual_hash_chain_and_reviewer_bytes(self):
        mutations = [lambda: self.kw.update(protocol_sha256="0" * 64),
            lambda: self.kw.update(freeze_sha256="0" * 64),
            lambda: self.kw["actual_source_sha256"].update({a.SOURCE_PATHS[0]: "0" * 64}),
            lambda: self.kw["actual_dependency_sha256"].update({a.DEPENDENCY_PATHS[0]: "0" * 64}),
            lambda: self.kw["actual_review_tools_sha256"].update({a.REVIEW_PATHS[0]: "0" * 64}),
            lambda: self.report["executable_path_sha256"].update(conhost="0" * 64),
            lambda: self.report["executables_sha256"].update(conhost="0" * 64)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_local_four_file_hash_inventory(self):
        self.kw["executable_sha256"] = dict(self.freeze["executables_sha256"])
        self.assertTrue(self.audit()["passed"])
        self.reject(lambda: self.kw["executable_sha256"].update(conhost="0" * 64))

    def test_protocol_roles_counts_and_case_order_cannot_drift(self):
        for mutation in [lambda: self.protocol["config"].update(maximum_descendants=32),
                lambda: self.protocol["policy_contract"].update(auxiliaries_per_owner=2),
                lambda: self.protocol["policy_contract"].update(allow_unregistered_same_image=True),
                lambda: self.report["cases"].reverse(), lambda: self.report["cases"].pop(),
                lambda: self.protocol["self_executable_roles"].update(worker="base_python")]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_no_ML_import_release_and_hidden_failure(self):
        for mutation in [lambda: self.report.update(training_permitted=True),
                lambda: self.report["cases"][0]["worker_policy_state"].update(torch_imported=True),
                lambda: self.report["cases"][0]["completion"].update(model_loads=1),
                lambda: self.report["cases"][1]["rejection"].update(ML_release_absent=False),
                lambda: self.report["cases"][0].update(error="failed"),
                lambda: self.report["cases"][0].update(case_wall_budget_exceeded=True)]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_self_path_and_OS_image_contracts_are_independent(self):
        for mutation in [lambda: self.report["cases"][0]["worker_identity"]["self_receipt"]["self_executable"].update(sha256="b" * 64),
                lambda: self.report["cases"][0]["worker_identity"].update(retained_os_image_expected_role="launcher"),
                lambda: self.report["cases"][1]["injected_process"]["self_receipt"]["self_executable"].update(normalized_path_sha256="4" * 64),
                lambda: self.report["cases"][0]["worker_identity"]["self_receipt"].update(runtime_executable_sha256="a" * 64)]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_console_exact_file_path_and_retained_identity(self):
        for field, value in [("sha256", "0" * 64), ("normalized_path_sha256", "0" * 64),
                             ("basename", "cmd.exe"), ("queried_from_retained_handle", False),
                             ("retained_identity_stable", False), ("exact_path_matches", [])]:
            with self.subTest(field=field):
                self.reject(lambda: self.report["cases"][0]["censuses"][0]["processes"][-1]["image"].update({field: value}))

    def test_parent_ref_PID_creation_and_topology_are_replayed(self):
        for mutation in [lambda: self.report["cases"][0]["role_decisions"][0]["auxiliary_roles"][0]["parent_ref"].update(creation_filetime=999),
                lambda: self.report["cases"][0]["censuses"][0]["processes"][-1].update(parent_pid=101),
                lambda: self.report["cases"][0]["censuses"][1]["processes"][2].update(parent_pid=100),
                lambda: self.report["cases"][0]["censuses"][1]["processes"][1].update(creation_filetime=999),
                lambda: self.report["cases"][0]["role_decisions"][1]["pinned_auxiliaries"]["launcher"]["owner_ref"].update(creation_filetime=999)]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_console_identity_cannot_be_replaced_or_disappear(self):
        def replace():
            case = self.report["cases"][0]
            for value in [case["censuses"][1]["processes"][3], case["role_decisions"][1]["auxiliary_roles"][0],
                          case["role_decisions"][1]["pinned_auxiliaries"]["launcher"]["auxiliary_ref"],
                          case["role_decisions"][1]["held_liveness"][3]]:
                value["creation_filetime"] += 1
        self.reject(replace)
        self.reject(lambda: self.report["cases"][0]["censuses"][1]["processes"].pop(3))

    def test_same_image_helper_and_extra_native_cannot_be_promoted(self):
        for case_index in (1, 2):
            def promote():
                decision = self.report["cases"][case_index]["role_decisions"][-1]
                decision.update(admitted=True, permitted_control="finish", errors=[], rejections=[], rejected_pids=[])
                decision["admitted_pids"] += [205 if case_index == 1 else 305]
            with self.subTest(case_index=case_index):
                self.reject(promote)

    def test_unregistered_owner_console_cannot_be_admitted(self):
        self.reject(lambda: self.report["cases"][1]["role_decisions"][-1]["auxiliary_roles"].append({"pid": 206, "role": "console_auxiliary"}))
        self.reject(lambda: self.report["cases"][2]["censuses"][-1]["processes"][-1].update(parent_pid=302))

    def test_negative_requires_exact_target_and_no_unrelated_error(self):
        for mutation in [lambda: self.report["cases"][1]["role_decisions"][-1]["errors"].append("missing_console"),
                lambda: self.report["cases"][1]["injected_process"]["self_receipt"].update(nonce="0" * 64),
                lambda: self.report["cases"][2]["injected_process"]["os_identity"].update(pid=302),
                lambda: self.report["cases"][2]["rejection"]["injected_ref"].update(creation_filetime=999),
                lambda: self.report["cases"][1]["censuses"][-1]["processes"][-1]["image"].update(sha256="0" * 64)]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_incomplete_inventory_or_count_cannot_pass_as_rejection(self):
        for mutation in [lambda: self.report["cases"][1]["censuses"][-1].update(census_complete=False),
                lambda: self.report["cases"][0]["censuses"][0].update(job_count_before=99),
                lambda: self.report["cases"][1]["censuses"][-1].update(truncated=True),
                lambda: self.report["cases"][0]["censuses"][0]["processes"][0].update(job_member=False),
                lambda: self.report["cases"][0]["censuses"][0]["processes"].append(copy.deepcopy(self.report["cases"][0]["censuses"][0]["processes"][0]))]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_control_permission_is_bound_to_correct_decision(self):
        for mutation in [lambda: self.report["cases"][0]["role_decisions"][0].update(permitted_control="finish"),
                lambda: self.report["cases"][0]["role_decisions"][1].update(decision_index=0),
                lambda: self.report["cases"][1]["role_decisions"][-1].update(permitted_control="finish"),
                lambda: self.report["cases"][0]["native_descendant"]["launch_receipt"].update(shell=True)]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_held_liveness_set_clock_and_identity(self):
        for mutation in [lambda: self.report["cases"][0]["role_decisions"][0]["held_liveness"].pop(),
                lambda: self.report["cases"][0]["role_decisions"][0]["held_liveness"][0].update(alive=False),
                lambda: self.report["cases"][0]["role_decisions"][0]["held_liveness"][0].update(verified_perf_counter=100.1),
                lambda: self.report["cases"][0]["role_decisions"][1].update(job_count_after=99),
                lambda: self.report["cases"][1].update(termination_started_perf_counter=110.5)]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_chronology_deadlines_and_nonfinite_clocks(self):
        for mutation in [lambda: self.freeze.update(frozen_at="2027-01-01T00:00:00Z"),
                lambda: self.report["cases"][0]["censuses"][0].update(completed_perf_counter=float("nan")),
                lambda: self.report.update(wall_seconds=99),
                lambda: self.report["cases"][1]["injected_process"]["self_receipt"].update(perf_counter=110.5),
                lambda: self.report["cases"][0]["role_decisions"][1].update(completed_perf_counter=106.),
                lambda: self.report["cases"][0].update(started_at="2026-01-01T00:02:00")]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_cleanup_exit_set_codes_and_zero_job(self):
        for mutation in [lambda: self.report["cases"][0]["cleanup"].update(job_active_count=1),
                lambda: self.report["cases"][1]["cleanup"]["exit_codes"].pop(),
                lambda: self.report["cases"][1]["cleanup"]["exit_codes"][0].update(exit_code=0),
                lambda: self.report["cases"][0]["cleanup"]["exit_codes"][-1].update(exit_code=1),
                lambda: self.report["cases"][0]["cleanup"].update(timeout_seconds=.01),
                lambda: self.report["cases"][2]["cleanup"]["exit_codes"].append({"pid": 9999, "creation_filetime": 99, "exit_code": 0})]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_native_and_console_termination_codes_are_preserved_without_invented_rule(self):
        for case in self.report["cases"][1:]:
            for exit_row in case["cleanup"]["exit_codes"]:
                if exit_row["pid"] not in (200, 201, 205, 300, 301):
                    exit_row["exit_code"] = 123
        self.assertTrue(self.audit()["passed"], self.audit()["failures"])

    def test_bool_or_float_aliases_do_not_replace_exact_integer_fields(self):
        for mutation in [lambda: self.report.update(schema_version=True),
                lambda: self.report["cases"][0]["role_decisions"][1].update(decision_index=True),
                lambda: self.report["cases"][0]["censuses"][0].update(observed_pids=[100., 101., 103.]),
                lambda: self.report["cases"][0]["role_decisions"][0].update(admitted_pids=[100., 101., 103.]),
                lambda: self.report["cases"][0]["completion"].update(native_exit_code=False),
                lambda: self.report["cases"][0]["cleanup"].update(job_active_count=False)]:
            with self.subTest(mutation=mutation):
                self.reject(mutation)

    def test_file_entrypoint_hashes_strict_JSON_and_missing_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in (*a.SOURCE_PATHS, *a.DEPENDENCY_PATHS, *a.REVIEW_PATHS):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
            for field, names, report_field in [("new_source_files_sha256", a.SOURCE_PATHS, "source_sha256"),
                    ("frozen_dependency_files_sha256", a.DEPENDENCY_PATHS, "dependencies_sha256"),
                    ("review_tools_sha256", a.REVIEW_PATHS, "review_tools_sha256")]:
                self.freeze[field] = {name: a.sha((root / name).read_bytes()) for name in names}
                self.report[report_field] = dict(self.freeze[field])
            pp, fp, rp = (root / name for name in ("protocol.json", "freeze.json", "report.json"))
            pp.write_text(json.dumps(self.protocol), encoding="utf-8")
            self.freeze["protocol_sha256"] = self.report["protocol_sha256"] = a.sha(pp.read_bytes())
            fp.write_text(json.dumps(self.freeze), encoding="utf-8")
            self.report["implementation_sha256"] = a.sha(fp.read_bytes())
            rp.write_text(json.dumps(self.report), encoding="utf-8")
            self.assertTrue(a.audit_files(rp, pp, fp, root=root)["passed"])
            (root / a.REVIEW_PATHS[0]).write_bytes(b"changed")
            self.assertFalse(a.audit_files(rp, pp, fp, root=root)["passed"])
            for content in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
                rp.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    a.bounded(rp)
        self.assertFalse(a.audit({}, {}, {}, **self.kw)["passed"])


if __name__ == "__main__":
    unittest.main()
