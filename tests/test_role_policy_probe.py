"""Pure stdlib mocked role-policy controls; no native API or child execution."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from experiments import role_policy_probe as p


def fixture():
    paths = {"launcher": Path("launcher/python.exe"), "base_python": Path("base/python.exe"),
        "native": Path("System32/cmd.exe"), "conhost": Path("System32/conhost.exe")}
    hashes = {role: str(index) * 64 for index, role in enumerate(paths, 1)}
    known = {1: (10, "launcher"), 2: (20, "base_python"), 3: (30, "native")}
    def node(pid, created, parent, role, approved=False):
        return {"pid": pid, "creation_filetime": created, "parent_pid": parent,
            "policy_role": role if approved else "unapproved", "approved_known": approved,
            "job_member": True, "alive": True, "image": {"basename": paths[role].name,
            "sha256": hashes[role], "normalized_path_sha256": p.dual.path_hash(paths[role]),
            "exact_path_matches": [role], "path_classification": "exact_executable",
            "queried_from_retained_handle": True, "retained_identity_stable": True}}
    nodes = [node(1, 10, 999, "launcher", True), node(2, 20, 1, "base_python", True),
        node(3, 30, 2, "native", True), node(4, 14, 1, "conhost"), node(5, 35, 3, "conhost")]
    def snapshot(rows, label="after_native"):
        return {"label": label, "processes": copy.deepcopy(rows), "observed_pids": sorted(row["pid"] for row in rows),
            "census_complete": True, "errors": [], "job_count_before": len(rows), "job_count_after": len(rows),
            "started_perf_counter": 10., "completed_perf_counter": 10.001}
    return paths, hashes, known, nodes, node, snapshot


class PolicyTests(unittest.TestCase):
    def setUp(self): self.paths, self.hashes, self.known, self.nodes, self.node, self.snapshot = fixture()

    def evaluate(self, nodes=None, known=None, pins=None):
        return p.evaluate_policy(self.snapshot(self.nodes if nodes is None else nodes),
            self.known if known is None else known, self.paths, self.hashes, {} if pins is None else pins)

    def test_exact_topology_admits_five_only_and_pins_opaque_image_and_parent_identity(self):
        value = self.evaluate()
        self.assertTrue(value["admitted"], value["errors"])
        self.assertEqual(value["admitted_pids"], [1, 2, 3, 4, 5])
        self.assertEqual(value["auxiliary_roles"][0]["parent_ref"], {"pid": 1, "creation_filetime": 10})
        self.assertEqual(value["pinned_auxiliaries"]["launcher"]["auxiliary_ref"], {"pid": 4, "creation_filetime": 14})
        self.assertEqual(value["pinned_auxiliaries"]["launcher"]["frozen_path_sha256"], p.dual.path_hash(self.paths["conhost"]))
        self.assertIs(value["training_permitted"], False)
        self.assertNotIn(str(self.paths["conhost"]), str(value))

    def test_before_native_admits_three_then_preserves_launcher_auxiliary_pin(self):
        before = self.evaluate([self.nodes[i] for i in (0, 1, 3)], {pid: self.known[pid] for pid in (1, 2)})
        after = self.evaluate(pins=before["pinned_auxiliaries"])
        self.assertTrue(before["admitted"]); self.assertTrue(after["admitted"])
        self.assertEqual(before["pinned_auxiliaries"]["launcher"], after["pinned_auxiliaries"]["launcher"])

    def test_missing_or_duplicate_console_owner_auxiliary_rejects(self):
        for rows in (self.nodes[:-1], self.nodes + [self.node(8, 38, 3, "conhost")]):
            value = self.evaluate(rows)
            self.assertFalse(value["admitted"])
            self.assertIn("auxiliary_cardinality_mismatch:native", value["errors"])

    def test_same_image_python_and_its_console_are_never_registered(self):
        rows = self.nodes + [self.node(6, 40, 2, "base_python"), self.node(7, 41, 6, "conhost")]
        value = self.evaluate(rows)
        self.assertFalse(value["admitted"])
        self.assertEqual(value["errors"], ["unregistered_processes_present"])
        self.assertEqual(value["rejected_pids"], [6, 7])
        self.assertEqual([r["reason"] for r in value["rejections"]], ["unregistered_process_identity", "unregistered_parent_identity"])

    def test_same_image_native_and_its_console_are_never_registered(self):
        value = self.evaluate(self.nodes + [self.node(6, 40, 2, "native"), self.node(7, 41, 6, "conhost")])
        self.assertFalse(value["admitted"])
        self.assertEqual(value["admitted_pids"], [1, 2, 3, 4, 5]); self.assertEqual(value["rejected_pids"], [6, 7])

    def test_conhost_beneath_actual_interpreter_is_unapproved(self):
        value = self.evaluate(self.nodes + [self.node(6, 40, 2, "conhost")])
        self.assertEqual(value["rejected_pids"], [6])
        self.assertEqual(value["rejections"][0]["reason"], "unregistered_parent_identity")

    def test_exact_system32_category_or_basename_does_not_replace_path_and_file_hash(self):
        for change in ({"normalized_path_sha256": "f" * 64}, {"sha256": "f" * 64},
                {"exact_path_matches": [], "path_classification": "system32"}, {"basename": "cmd.exe"}):
            rows = copy.deepcopy(self.nodes); rows[3]["image"].update(change)
            with self.subTest(change=change): self.assertFalse(self.evaluate(rows)["admitted"])

    def test_known_parent_pid_creation_and_creation_order_are_required(self):
        for index, field, val in ((1, "parent_pid", 999), (2, "parent_pid", 1),
                (0, "creation_filetime", 11), (3, "creation_filetime", 9)):
            rows = copy.deepcopy(self.nodes); rows[index][field] = val
            with self.subTest(index=index, field=field): self.assertFalse(self.evaluate(rows)["admitted"])

    def test_replaced_auxiliary_pid_or_creation_fails_without_repinning(self):
        before = self.evaluate()
        for field, val in (("pid", 8), ("creation_filetime", 15)):
            rows = copy.deepcopy(self.nodes); rows[3][field] = val
            value = self.evaluate(rows, pins=before["pinned_auxiliaries"])
            self.assertFalse(value["admitted"])
            self.assertIn("auxiliary_identity_replaced:launcher", value["errors"])
            self.assertEqual(value["pinned_auxiliaries"], before["pinned_auxiliaries"])

    def test_dead_nonmember_unstable_or_nonqueried_auxiliary_rejects(self):
        for key in ("job_member", "alive", "retained_identity_stable", "queried_from_retained_handle"):
            rows = copy.deepcopy(self.nodes)
            (rows[3] if key in ("job_member", "alive") else rows[3]["image"])[key] = False
            with self.subTest(key=key): self.assertFalse(self.evaluate(rows)["admitted"])

    def test_incomplete_duplicate_or_count_mismatch_inventory_fails_closed(self):
        for change in ({"census_complete": False}, {"job_count_after": 6}, {"observed_pids": [1, 2]}, {"errors": ["query failed"]}):
            row = self.snapshot(self.nodes); row.update(change)
            self.assertFalse(p.evaluate_policy(row, self.known, self.paths, self.hashes, {})["admitted"])
        self.assertFalse(self.evaluate(self.nodes + [self.nodes[0]])["admitted"])

    def test_negative_verifier_rejects_unrelated_extra_failure_and_preserves_all_original_roles(self):
        previous = self.evaluate()
        rows = self.nodes + [self.node(6, 40, 2, "native")]
        decision = self.evaluate(rows); decision["decision_index"] = 2
        extra = SimpleNamespace(pid=6, creation_filetime=40)
        good = p.verify_rejection(self.snapshot(rows), decision, previous, extra, self.paths, self.hashes, "native")
        self.assertEqual(good["unexpected_pids"], [6])
        for mutate in ("errors", "primary", "target_parent", "aux_extra"):
            bad_rows, bad = copy.deepcopy(rows), copy.deepcopy(decision)
            if mutate == "errors": bad["errors"].append("auxiliary_cardinality_mismatch:launcher")
            if mutate == "primary": bad["primary_roles"][0]["creation_filetime"] = 999
            if mutate == "target_parent": bad_rows[-1]["parent_pid"] = 1
            if mutate == "aux_extra":
                bad_rows += [self.node(7, 41, 6, "conhost"), self.node(8, 42, 6, "conhost")]; bad["rejected_pids"] += [7, 8]
            with self.subTest(mutate=mutate), self.assertRaises(p.obs.ObserverError):
                p.verify_rejection(self.snapshot(bad_rows), bad, previous, extra, self.paths, self.hashes, "native")


class ControlTests(unittest.TestCase):
    def test_false_decision_emits_no_control_and_true_never_permits_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            decision = {"admitted": False, "permitted_control": "reject", "training_permitted": False,
                "decision_index": 2, "label": "after_injection"}
            with self.assertRaises(p.obs.ObserverError): p.control(tmp, "finish.json", "a" * 64, "finish", decision)
            self.assertFalse((Path(tmp) / "finish.json").exists())
            decision.update(admitted=True, permitted_control="create-native", decision_index=0, label="before_native")
            p.control(tmp, "control.json", "a" * 64, "create-native", decision)
            value = p.obs.read_small(Path(tmp) / "control.json")
            self.assertIs(value["training_permitted"], False); self.assertIs(value["role_policy_admitted"], True)
            self.assertEqual(value["role_decision_index"], 0)
            for mutation in ({"training_permitted": True}, {"purpose": "training"}, {"role_policy_admitted": False},
                    {"role_decision_index": 9}, {"role_decision_index": False}, {"role_decision_label": "after_native"}, {"command": "import"}):
                with mock.patch.object(p, "wait", return_value={**value, **mutation}), self.assertRaises(p.obs.ObserverError):
                    p.require_control(tmp, "control.json", "a" * 64, "create-native", 0, 20, 65)

    def test_budget_clamps_stage_case_and_suite_without_renewal(self):
        with mock.patch.object(p.time, "perf_counter", return_value=10.):
            self.assertEqual(p.budget(20, 65), 15.)
            self.assertEqual(p.budget(12, 65), 12.)
            self.assertEqual(p.budget(20, 11), 11.)
            with self.assertRaises(p.obs.ObserverError): p.budget(9, 65)

    def test_fixed_native_launch_receipt_and_pipe_flags_are_preserved(self):
        child = SimpleNamespace(pid=7)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(p.subprocess, "Popen", return_value=child) as popen:
            self.assertIs(p.native_launch(Path(tmp), "native-ready.json", "a" * 64, Path("System32/cmd.exe")), child)
            value = p.obs.read_small(Path(tmp) / "native-ready.json")
            self.assertEqual(value["command_arguments"], list(p.work.NATIVE_ARGUMENTS))
            self.assertEqual(popen.call_args.args[0], [str(Path("System32/cmd.exe")), *p.work.NATIVE_ARGUMENTS])
            self.assertEqual(popen.call_args.kwargs["creationflags"], 0x08000000)
            self.assertIs(popen.call_args.kwargs["shell"], False)
            self.assertIs(popen.call_args.kwargs["close_fds"], True)


class LifecycleTests(unittest.TestCase):
    def exercise(self, injection="none", mutate=None):
        paths, hashes, known, nodes, node, snapshot = fixture()
        rows = copy.deepcopy(nodes)
        if injection != "none": rows += [node(6, 40, 2, "base_python" if injection == "python" else "native"), node(7, 41, 6, "conhost")]
        refs = {row["pid"]: SimpleNamespace(pid=row["pid"], creation_filetime=row["creation_filetime"], handle=row["pid"]) for row in rows}
        current = [nodes[i] for i in (0, 1, 3)]
        job = mock.Mock(); job.start_suspended.return_value = refs[1]
        job.authenticate.side_effect = [(refs[2], []), (refs.get(6), [])]
        job.retain.side_effect = lambda pid, expected=None: refs[pid]
        job.active_count.side_effect = lambda: len(current)
        job.backend.creation.side_effect = lambda handle: refs[handle].creation_filetime + (1 if mutate == "live_identity" and handle == 4 else 0)
        job.backend.k.GetProcessId.side_effect = lambda handle: handle
        controls = []
        def census(j, launcher, primary, px, hs, system32, report, label, *a):
            nonlocal current
            current = [nodes[i] for i in (0, 1, 3)] if label == "before_native" else nodes if label == "after_native" else rows
            current = copy.deepcopy(current)
            if mutate == "baseline_aux" and label == "before_native": current[-1]["parent_pid"] = 2
            value = snapshot(current, label); now = p.time.perf_counter()
            value.update(started_perf_counter=now, completed_perf_counter=now)
            report["censuses"].append(value); return value
        def wait(directory, name, nonce, role, *a):
            if name in ("worker-policy-state.json", "worker-completed.json"):
                return {"pid": 2, "training_permitted": False, "torch_imported": False, "transformers_imported": False,
                    "model_loads": 0, "optimizer_steps": 0, "native_exit_code": 0, "native_released_nonempty_line": True}
            if name == "helper-launch.json": return {"pid": 2, "helper_launcher_pid": 6,
                "base_executable_sha256": hashes["base_python"], "shell": False, "close_fds": True, "creationflags": 0x08000000}
            if "native-ready" in name: return {"pid": 2}
            erole = "launcher" if role == "worker" else "base_python"
            return {"pid": 2 if role == "worker" else 6, "self_executable": {"source": "sys.executable", "basename": paths[erole].name,
                "sha256": "f" * 64 if mutate == "self" else hashes[erole], "normalized_path_sha256": p.dual.path_hash(paths[erole])}}
        def cleanup(*a):
            entries = [{"pid": row["pid"], "creation_filetime": row["creation_filetime"],
                "exit_code": (9 if mutate == "exit" and row["pid"] == 4 else 0 if injection == "none" else 0xE003)} for row in current]
            if mutate == "cleanup_set": entries = entries[:-1]
            return {"all_retained_handles_exited": True, "job_active_count": 0, "exit_codes": entries}
        native_results = [(refs[3], {})] + ([(refs[6], {})] if injection == "native" else [])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(p.obs, "WindowsJob", return_value=job), \
                mock.patch.object(p, "wait", side_effect=wait), mock.patch.object(p.dual, "census", side_effect=census), \
                mock.patch.object(p.work, "verify_native_child", side_effect=native_results), mock.patch.object(p, "cleanup", side_effect=cleanup), \
                mock.patch.object(p.obs, "write_new", side_effect=lambda path, value: controls.append(value)):
            result = p.run_case(next(spec for spec in p.CASES if spec[1] == injection), paths, hashes, Path(tmp), p.time.perf_counter() + 65)
        return result, controls, job

    def test_healthy_policy_stages_hold_exact_three_then_five_and_finish_only_after_admission(self):
        result, controls, job = self.exercise()
        self.assertTrue(result["passed"], result.get("error"))
        self.assertEqual([len(row["held_liveness"]) for row in result["role_decisions"]], [3, 5])
        self.assertEqual([row["command"] for row in controls], ["create-native", "finish"])
        self.assertTrue(all(row["training_permitted"] is False for row in controls))
        job.terminate.assert_not_called(); job.close.assert_called_once(); job.close_refs.assert_called_once()

    def test_python_negative_preserves_admitted_five_rejects_exact_helper_and_console_then_kills_job(self):
        result, controls, job = self.exercise("python")
        self.assertTrue(result["passed"], result.get("error"))
        self.assertEqual(result["rejection"]["unexpected_pids"], [6, 7])
        self.assertEqual([row["command"] for row in controls], ["create-native", "create-injection"])
        self.assertEqual(result["role_decisions"][-1]["permitted_control"], "reject")
        job.terminate.assert_called_once()

    def test_native_negative_uses_independent_retained_os_identity_without_native_self_report(self):
        result, controls, job = self.exercise("native")
        self.assertTrue(result["passed"], result.get("error"))
        self.assertEqual(result["injected_process"], {"kind": "native"})  # native verifier mock receipt, not helper self
        self.assertNotIn("self_receipt", result["injected_process"])
        self.assertEqual(result["rejection"]["injected_ref"], {"pid": 6, "creation_filetime": 40})
        job.terminate.assert_called_once()

    def test_unapproved_baseline_aborts_before_native_control(self):
        result, controls, job = self.exercise(mutate="baseline_aux")
        self.assertFalse(result["passed"]); self.assertEqual(controls, [])
        self.assertTrue(result["failure_cleanup"]["all_retained_handles_exited"]); job.terminate.assert_called_once()

    def test_wrong_self_receipt_aborts_before_any_inventory_or_control(self):
        result, controls, job = self.exercise(mutate="self")
        self.assertFalse(result["passed"]); self.assertEqual(result["censuses"], []); self.assertEqual(controls, [])
        self.assertIn("self executable", result["error"])

    def test_changed_live_creation_aborts_before_control_and_preserves_partial_hold_evidence(self):
        result, controls, job = self.exercise(mutate="live_identity")
        self.assertFalse(result["passed"]); self.assertEqual(controls, [])
        self.assertEqual(len(result["role_decisions"][0]["held_liveness"]), 2)
        self.assertIn("PID/creation changed", result["error"])

    def test_cleanup_missing_identity_or_nonzero_healthy_auxiliary_cannot_pass(self):
        for mutate in ("cleanup_set", "exit"):
            result, controls, job = self.exercise(mutate=mutate)
            self.assertFalse(result["passed"], mutate); self.assertTrue(result["failure_cleanup"]["all_retained_handles_exited"])


class FreezeTests(unittest.TestCase):
    def test_protocol_has_exact_new_sources_dependencies_cases_and_no_training(self):
        value = p.obs.read_small(p.ROOT / "fixtures/role-policy-probe/protocol.json")
        self.assertEqual(value["config"], p.CONFIG)
        self.assertEqual(value["source_paths"], list(p.SOURCE_PATHS)); self.assertEqual(value["frozen_dependency_paths"], list(p.DEPENDENCY_PATHS))
        self.assertEqual(value["review_tool_paths"], list(p.REVIEW_TOOL_PATHS))
        self.assertEqual([(x["id"], x["injection"]) for x in value["cases_in_order"]], list(p.CASES))
        self.assertEqual(value["policy_contract"], p.POLICY_CONTRACT); self.assertIs(value["training_permitted"], False)

    def test_freeze_binds_four_file_path_hashes_sources_auditors_and_exact_System32(self):
        protocol = p.obs.read_small(p.ROOT / "fixtures/role-policy-probe/protocol.json")
        paths = {"launcher": Path("launcher/python.exe"), "base_python": Path("base/python.exe"),
            "native": Path("C:/Windows/System32/cmd.exe"), "conhost": Path("C:/Windows/System32/conhost.exe")}
        freeze = {"protocol_sha256": "a" * 64, "frozen_at": protocol["predeclared_at"],
            "new_source_files_sha256": {n: "a" * 64 for n in p.SOURCE_PATHS},
            "frozen_dependency_files_sha256": {n: "a" * 64 for n in p.DEPENDENCY_PATHS},
            "review_tools_sha256": {n: "a" * 64 for n in p.REVIEW_TOOL_PATHS},
            "executables_sha256": {role: "a" * 64 for role in paths},
            "executable_path_sha256": {role: p.dual.path_hash(path) for role, path in paths.items()}}
        with mock.patch.object(p.obs, "read_small", side_effect=lambda path: protocol if path == "protocol" else freeze), \
                mock.patch.object(p.obs, "sha256_file", return_value="a" * 64), mock.patch.dict(p.os.environ, {"SystemRoot": "C:/Windows"}):
            p.validate_freeze("protocol", "freeze", paths)
            freeze["executable_path_sha256"]["conhost"] = "f" * 64
            with self.assertRaisesRegex(p.obs.ObserverError, "opaque executable path"): p.validate_freeze("protocol", "freeze", paths)
            freeze["executable_path_sha256"]["conhost"] = p.dual.path_hash(paths["conhost"])
            freeze["review_tools_sha256"].pop(p.REVIEW_TOOL_PATHS[0])
            with self.assertRaisesRegex(p.obs.ObserverError, "source/dependency"): p.validate_freeze("protocol", "freeze", paths)
            freeze["review_tools_sha256"][p.REVIEW_TOOL_PATHS[0]] = "a" * 64
            paths["conhost"] = Path("C:/elsewhere/conhost.exe")
            with self.assertRaisesRegex(p.obs.ObserverError, "exact System32"): p.validate_freeze("protocol", "freeze", paths)

    def test_policy_role_or_case_expansion_rejected_before_any_native_construction(self):
        protocol = p.obs.read_small(p.ROOT / "fixtures/role-policy-probe/protocol.json")
        protocol["policy_contract"]["allow_unregistered_same_image"] = True
        with mock.patch.object(p.obs, "read_small", side_effect=[protocol, {}]), self.assertRaisesRegex(p.obs.ObserverError, "protocol/config"):
            p.validate_freeze("protocol", "freeze", {})


if __name__ == "__main__": unittest.main()
