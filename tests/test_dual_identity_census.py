"""Pure stdlib mocked census controls; no native calls or child launch."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from experiments import dual_identity_census as p


class Clock:
    def __init__(self): self.value = 10.0
    def now(self): self.value += 0.0001; return self.value


class ContractTests(unittest.TestCase):
    def test_protocol_exact_cases_config_and_no_training(self):
        value = p.obs.read_small(p.ROOT / "fixtures/dual-identity-census/protocol.json")
        self.assertEqual(value["config"], p.CONFIG)
        self.assertEqual(value["source_paths"], list(p.SOURCE_PATHS))
        self.assertEqual(value["frozen_dependency_paths"], list(p.DEPENDENCY_PATHS))
        self.assertEqual(value["review_tool_paths"], list(p.REVIEW_TOOL_PATHS))
        self.assertEqual([(x["id"], x["injected"]) for x in value["cases_in_order"]], list(p.CASES))
        self.assertIs(value["training_permitted"], False)
        self.assertEqual(value["self_executable_roles"], {"worker": "launcher", "helper": "base_python"})
        self.assertEqual(value["retained_os_image_roles"], {"worker": "base_python", "helper": "base_python"})

    def test_nonrenewable_deadline_clamp_and_exhaustion(self):
        with mock.patch.object(p.time, "perf_counter", return_value=10):
            self.assertEqual(p.budget(20, 30), 15)
            self.assertEqual(p.budget(12, 30), 12)
            self.assertEqual(p.budget(20, 11), 11)
            with self.assertRaisesRegex(p.obs.ObserverError, "exhausted"): p.budget(9, 30)

    def test_bounded_tree_retains_all_cached_PIDs_instead_of_slicing(self):
        parents = {i: 1 for i in range(2, 30)}
        ids, truncated = p.bounded_tree(parents, 1)
        self.assertEqual(ids, list(range(1, 30)))
        self.assertFalse(truncated)  # separate row count/query budget fails census
        ids, truncated = p.bounded_tree({i + 1: i for i in range(1, 20)}, 1)
        self.assertTrue(truncated)
        self.assertEqual(ids, list(range(1, 18)))

    def test_controller_never_grants_training_and_rejects_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            p.control(tmp, "control.json", "a" * 64, "finish")
            value = p.obs.read_small(Path(tmp) / "control.json")
            self.assertIs(value["training_permitted"], False)
            value["training_permitted"] = True
            with mock.patch.object(p, "wait", return_value=value), self.assertRaises(p.obs.ObserverError):
                p.require_control(tmp, "control.json", "a" * 64, "finish", 20, 30)


class DualIdentityTests(unittest.TestCase):
    def paths_and_hashes(self, folder, equal_content=False):
        paths = {role: Path(folder) / role / "python.exe" for role in ("launcher", "base_python")}
        for role, path in paths.items():
            path.parent.mkdir()
            path.write_bytes(b"same file bytes" if equal_content else role.encode())
        return paths, {role: p.obs.sha256_file(path) for role, path in paths.items()}

    def os_image(self, path):
        def query(handle, flags, buffer, size): buffer.value = str(path); return True
        backend = SimpleNamespace(k=SimpleNamespace(QueryFullProcessImageNameW=mock.Mock(side_effect=query), GetProcessId=lambda h: 7),
            creation=lambda h: 70, checked=lambda result, action: result or (_ for _ in ()).throw(p.obs.ObserverError(action)))
        return backend, SimpleNamespace(pid=7, creation_filetime=70, handle=777)

    def test_split_venv_self_launcher_and_retained_base_image_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, hashes = self.paths_and_hashes(tmp)
            ready = {"self_executable": p.self_executable_identity(paths["launcher"])}
            roles = p.verify_self_executable(ready, "worker", paths, hashes)
            backend, ref = self.os_image(paths["base_python"])
            image = p.image_identity(backend, ref, paths, Path(tmp) / "System32")
            self.assertEqual(roles, {"self_executable_expected_role": "launcher", "retained_os_image_expected_role": "base_python"})
            self.assertEqual(image["exact_path_matches"], ["base_python"])
            self.assertNotEqual(ready["self_executable"]["sha256"], image["sha256"])
            self.assertNotEqual(ready["self_executable"]["normalized_path_sha256"], image["normalized_path_sha256"])

    def test_equal_binary_bytes_do_not_replace_each_roles_exact_path_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, hashes = self.paths_and_hashes(tmp, equal_content=True)
            self.assertEqual(hashes["launcher"], hashes["base_python"])
            p.verify_self_executable({"self_executable": p.self_executable_identity(paths["launcher"])}, "worker", paths, hashes)
            p.verify_self_executable({"self_executable": p.self_executable_identity(paths["base_python"])}, "helper", paths, hashes)
            with self.assertRaisesRegex(p.obs.ObserverError, "declared launcher"):
                p.verify_self_executable({"self_executable": p.self_executable_identity(paths["base_python"])}, "worker", paths, hashes)

    def test_helper_self_and_OS_image_may_match_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, hashes = self.paths_and_hashes(tmp)
            ready = {"self_executable": p.self_executable_identity(paths["base_python"])}
            roles = p.verify_self_executable(ready, "helper", paths, hashes)
            backend, ref = self.os_image(paths["base_python"])
            image = p.image_identity(backend, ref, paths, Path(tmp) / "System32")
            self.assertEqual(roles["self_executable_expected_role"], "base_python")
            self.assertEqual(ready["self_executable"]["sha256"], image["sha256"])
            self.assertNotIn("approved_known", roles)

    def test_self_content_path_source_and_field_set_each_gate_the_declared_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths, hashes = self.paths_and_hashes(tmp)
            original = p.self_executable_identity(paths["launcher"])
            for mutation in ({"source": "OS-image"}, {"sha256": "f" * 64}, {"normalized_path_sha256": "e" * 64},
                    {"basename": "other.exe"}, {"runtime_executable_sha256": hashes["launcher"]}):
                value = {**original, **mutation}
                with self.subTest(mutation=mutation), self.assertRaises(p.obs.ObserverError):
                    p.verify_self_executable({"self_executable": value}, "worker", paths, hashes)

    def test_published_self_receipt_has_opaque_path_and_no_runtime_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "private" / "python.exe"
            executable.parent.mkdir(); executable.write_bytes(b"never run")
            backend = SimpleNamespace(self_reading=lambda: {"pid": 7, "creation_filetime": 70, "perf_counter": 10.})
            with mock.patch.object(p.sys, "executable", str(executable)), mock.patch.object(p.os, "getppid", return_value=6):
                p.publish_identity(backend, tmp, "ready.json", "a" * 64, "worker")
            value = p.obs.read_small(Path(tmp) / "ready.json")
            self.assertEqual(set(value["self_executable"]), {"source", "basename", "sha256", "normalized_path_sha256"})
            self.assertEqual(value["self_executable"]["normalized_path_sha256"], p.path_hash(executable))
            self.assertFalse(any(key.startswith("runtime_executable") for key in value))
            self.assertNotIn(str(tmp), str(value))


class ImageTests(unittest.TestCase):
    def test_OS_image_retained_query_path_hash_and_classification(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "System32" / "support.exe"; image.parent.mkdir(); image.write_bytes(b"never executed")
            def query(handle, flags, buffer, size): buffer.value = str(image); return True
            backend = SimpleNamespace(k=SimpleNamespace(QueryFullProcessImageNameW=mock.Mock(side_effect=query), GetProcessId=lambda h: 2),
                creation=lambda h: 20, checked=lambda result, action: result or (_ for _ in ()).throw(p.obs.ObserverError(action)))
            ref = SimpleNamespace(pid=2, creation_filetime=20, handle=222)
            value = p.image_identity(backend, ref, {"base_python": image}, image.parent)
            self.assertEqual(value["exact_path_matches"], ["base_python"])
            self.assertEqual(value["normalized_path_sha256"], p.path_hash(image))
            self.assertNotIn(str(tmp), str(value))
            self.assertTrue(value["retained_identity_stable"])
            value = p.image_identity(backend, ref, {}, image.parent)
            self.assertEqual(value["path_classification"], "system32")
            partial = {}
            with mock.patch.object(p.obs, "sha256_file", side_effect=OSError("hash denied")), self.assertRaises(OSError):
                p.image_identity(backend, ref, {}, image.parent, partial)
            self.assertEqual(partial["basename"], "support.exe")
            self.assertIsNone(partial["sha256"])
            self.assertEqual(partial["normalized_path_sha256"], p.path_hash(image))
            backend.creation = lambda h: 21
            with self.assertRaisesRegex(p.obs.ObserverError, "identity changed"):
                p.image_identity(backend, ref, {}, image.parent)


class CensusTests(unittest.TestCase):
    def setUp(self):
        self.parents = {1: 999, 2: 1, 3: 2, 4: 2}
        self.known = {1: (10, "launcher"), 2: (20, "base_python"), 3: (30, "native")}
        self.report = {}
        self.job = SimpleNamespace(backend=SimpleNamespace(snapshot=lambda: self.parents), active_count=lambda: len(self.parents),
            retain=lambda pid, expected=None: SimpleNamespace(pid=pid, creation_filetime=pid * 10), member=mock.Mock())
        self.paths = {role: Path(role) for role in ("launcher", "base_python", "native")}
        self.hashes = {role: str(i) * 64 for i, role in enumerate(self.paths, 1)}
        self.fail_pid = None
        self.wrong_known_hash = False
        self.calls = []

    def image(self, backend, ref, paths, system32, value):
        self.calls.append(ref.pid)
        role = self.known.get(ref.pid, (None, "base_python"))[1]
        value.update(basename="python.exe", normalized_path_sha256="a" * 64, sha256=None,
            exact_path_matches=[role], path_classification="exact_executable", queried_from_retained_handle=True)
        if ref.pid == self.fail_pid: raise PermissionError(13, "image hash unavailable", "Z:/private/unrelated-helper.exe")
        value["sha256"] = "0" * 64 if self.wrong_known_hash else self.hashes[role]
        value["retained_identity_stable"] = True

    def run_census(self):
        return p.census(self.job, SimpleNamespace(pid=1), self.known, self.paths, self.hashes, Path("System32"),
            self.report, "after_helper", p.time.perf_counter() + 20, p.time.perf_counter() + 45)

    def test_identified_image_identical_helper_remains_unapproved(self):
        with mock.patch.object(p, "image_identity", side_effect=self.image): row = self.run_census()
        self.assertTrue(row["census_complete"])
        self.assertEqual(row["unapproved_pids"], [4])
        self.assertIs(row["training_permitted"], False)
        helper = next(x for x in row["processes"] if x["pid"] == 4)
        self.assertEqual(helper["image"]["sha256"], self.hashes["base_python"])
        self.assertIs(helper["approved_known"], False)

    def test_hash_failure_keeps_partial_image_and_continues_other_rows(self):
        self.fail_pid = 2
        with mock.patch.object(p, "image_identity", side_effect=self.image), self.assertRaisesRegex(p.obs.ObserverError, "incomplete"):
            self.run_census()
        row = self.report["censuses"][0]
        self.assertEqual(self.calls, [1, 2, 3, 4])
        self.assertEqual(row["processes"][1]["image"]["basename"], "python.exe")
        self.assertIsNone(row["processes"][1]["image"]["sha256"])
        self.assertTrue(row["processes"][1]["error"])
        self.assertNotIn("Z:/private", str(self.report))

    def test_known_image_wrong_hash_fails_without_promoting_known_role(self):
        self.wrong_known_hash = True
        with mock.patch.object(p, "image_identity", side_effect=self.image), self.assertRaises(p.obs.ObserverError): self.run_census()
        row = self.report["censuses"][0]
        self.assertFalse(any(n["approved_known"] for n in row["processes"]))
        self.assertEqual(len(row["errors"]), 3)

    def test_job_count_mismatch_fails_and_preserves_snapshot(self):
        self.job.active_count = lambda: 5
        with mock.patch.object(p, "image_identity", side_effect=self.image), self.assertRaises(p.obs.ObserverError): self.run_census()
        row = self.report["censuses"][0]
        self.assertEqual(row["snapshot_observed_count"], 4)
        self.assertFalse(row["job_count_matches_before"])

    def test_query_budget_retains_unqueried_cached_nodes_with_errors(self):
        self.parents = {1: 999, **{i: 1 for i in range(2, 21)}}
        with mock.patch.object(p, "image_identity", side_effect=self.image), self.assertRaises(p.obs.ObserverError): self.run_census()
        row = self.report["censuses"][0]
        self.assertEqual(len(row["processes"]), 20)
        self.assertEqual(len(self.calls), 17)
        self.assertTrue(row["query_budget_exceeded"])
        self.assertTrue(all("error" in n for n in row["processes"] if n["pid"] >= 18))


class LifecycleTests(unittest.TestCase):
    def exercise(self, injected, approve_helper=False, late_close=False, wrong_self=False):
        with tempfile.TemporaryDirectory() as tmp:
            refs = [SimpleNamespace(pid=i, creation_filetime=i * 10) for i in range(1, 5)]
            launcher, actual, native, helper = refs
            job = mock.Mock(); job.start_suspended.return_value = launcher
            clock = Clock()
            if late_close: job.close.side_effect = lambda: setattr(clock, "value", clock.value + 21)
            job.authenticate.side_effect = [(actual, []), (helper, [])]
            paths = {k: Path(k) for k in ("launcher", "base_python", "native")}; hashes = {k: "a" * 64 for k in paths}
            controls, snapshots = [], []
            def wait(directory, name, nonce, role, *a):
                if name == "worker-census-state.json": return {"pid": 2, "training_permitted": False, "torch_imported": False, "transformers_imported": False, "model_loads": 0, "optimizer_steps": 0}
                if name == "helper-launch.json": return {"pid": 2, "helper_launcher_pid": 4, "base_executable_sha256": "a" * 64, "shell": False, "close_fds": True, "creationflags": 0x08000000}
                if name == "worker-completed.json": return {"pid": 2, "native_exit_code": 0, "native_released_nonempty_line": True, "training_permitted": False, "torch_imported": False, "transformers_imported": False, "model_loads": 0, "optimizer_steps": 0}
                return {"pid": 2 if role == "worker" else 4, "self_executable": {"source": "sys.executable",
                    "basename": paths[p.SELF_EXECUTABLE_ROLES[role]].name,
                    "sha256": "f" * 64 if wrong_self and role == "worker" else hashes[p.SELF_EXECUTABLE_ROLES[role]],
                    "normalized_path_sha256": p.path_hash(paths[p.SELF_EXECUTABLE_ROLES[role]])}}
            def census(job, launcher, known, paths, hashes, system32, report, label, *a):
                snapshots.append((label, copy.deepcopy(known)))
                row = {"label": label, "unapproved_pids": [5] if label != "after_helper" else [4, 5],
                    "processes": [{"pid": 4, "approved_known": approve_helper, "image": {"sha256": "a" * 64, "exact_path_matches": ["base_python"]}}]}
                report["censuses"].append(row); return row
            cleanup = {"all_retained_handles_exited": True, "job_active_count": 0,
                "exit_codes": [{"pid": x.pid, "creation_filetime": x.creation_filetime, "exit_code": 0} for x in refs]}
            with mock.patch.object(p.obs, "WindowsJob", return_value=job), mock.patch.object(p, "wait", side_effect=wait), \
                    mock.patch.object(p.time, "perf_counter", side_effect=clock.now), \
                    mock.patch.object(p, "census", side_effect=census), mock.patch.object(p.work, "verify_native_child", return_value=(native, {})), \
                    mock.patch.object(p.work, "live_member_receipts", return_value=[]), mock.patch.object(p, "cleanup", return_value=cleanup), \
                    mock.patch.object(p, "control", side_effect=lambda folder, name, nonce, command: controls.append((name, command))), \
                    mock.patch.dict(p.os.environ, {"SystemRoot": "C:/Windows"}):
                result = p.run_case(p.CASES[int(injected)], paths, hashes, Path(tmp), p.time.perf_counter() + 45)
            return result, controls, snapshots, job

    def test_graceful_census_with_extras_passes_observation_but_never_grants_training(self):
        result, controls, snapshots, job = self.exercise(False)
        self.assertTrue(result["passed"], result.get("error"))
        self.assertIs(result["training_permitted"], False)
        self.assertEqual(result["before_native_unapproved_pids"], [5])
        self.assertEqual([x[0] for x in snapshots], ["before_native", "after_native"])
        self.assertEqual(controls[-1], ("after-native-continue.json", "finish"))
        job.terminate.assert_not_called(); job.close.assert_called_once(); job.close_refs.assert_called_once()

    def test_injected_identified_helper_never_added_to_known_policy_and_is_terminated(self):
        result, controls, snapshots, job = self.exercise(True)
        self.assertTrue(result["passed"], result.get("error"))
        self.assertEqual(result["rejection"]["helper_pid"], 4)
        self.assertIs(result["rejection"]["training_permitted"], False)
        self.assertNotIn(4, snapshots[-1][1]); job.terminate.assert_called_once()
        self.assertFalse(any("import" in name or "helper-finish" in name for name, _ in controls))

    def test_helper_promoted_to_known_is_failure_and_cleanup_is_retained(self):
        result, controls, snapshots, job = self.exercise(True, True)
        self.assertFalse(result["passed"])
        self.assertIn("unapproved", result["error"])
        self.assertTrue(result["failure_cleanup"]["all_retained_handles_exited"])

    def test_final_handle_close_over_case_deadline_fails_and_still_closes_all_refs(self):
        result, controls, snapshots, job = self.exercise(False, late_close=True)
        self.assertFalse(result["passed"])
        self.assertTrue(result["case_wall_budget_exceeded"])
        self.assertTrue(result["cleanup"]["all_retained_handles_exited"])
        job.close.assert_called_once(); job.close_refs.assert_called_once()

    def test_wrong_self_identity_preserves_receipt_and_rejects_before_native_release(self):
        result, controls, snapshots, job = self.exercise(False, wrong_self=True)
        self.assertFalse(result["passed"])
        self.assertIn("self executable", result["error"])
        self.assertEqual(result["worker_identity"]["self_receipt"]["self_executable"]["sha256"], "f" * 64)
        self.assertEqual(controls, []); self.assertEqual(snapshots, [])
        self.assertTrue(result["failure_cleanup"]["all_retained_handles_exited"])
        job.terminate.assert_called_once(); job.close.assert_called_once(); job.close_refs.assert_called_once()


class FreezeTests(unittest.TestCase):
    def test_freeze_binds_all_three_executables_and_exact_source_dependency_sets(self):
        protocol = p.obs.read_small(p.ROOT / "fixtures/dual-identity-census/protocol.json")
        protocol["predeclared_at"] = "2026-01-01T00:00:00+00:00"
        freeze = {"protocol_sha256": "a" * 64, "frozen_at": "2026-01-01T00:00:01+00:00",
            "new_source_files_sha256": {n: "a" * 64 for n in p.SOURCE_PATHS},
            "frozen_dependency_files_sha256": {n: "a" * 64 for n in p.DEPENDENCY_PATHS},
            "review_tools_sha256": {n: "a" * 64 for n in p.REVIEW_TOOL_PATHS},
            "executables_sha256": {n: "a" * 64 for n in ("launcher", "base_python", "native")}}
        paths = {"launcher": Path("launcher.exe"), "base_python": Path("base.exe"), "native": Path("cmd.exe")}
        freeze["executable_path_sha256"] = {role: p.path_hash(path) for role, path in paths.items()}
        with mock.patch.object(p.obs, "read_small", side_effect=[protocol, freeze, protocol, freeze, protocol, freeze]), \
                mock.patch.object(p.obs, "sha256_file", return_value="a" * 64):
            p.validate_freeze("protocol", "freeze", paths)
            freeze["executables_sha256"]["base_python"] = "b" * 64
            with self.assertRaisesRegex(p.obs.ObserverError, "executable freeze"):
                p.validate_freeze("protocol", "freeze", paths)
            freeze["frozen_dependency_files_sha256"].pop(p.DEPENDENCY_PATHS[0])
            with self.assertRaisesRegex(p.obs.ObserverError, "source/dependency"):
                p.validate_freeze("protocol", "freeze", paths)

    def test_preexecution_freeze_rejects_correct_content_at_wrong_canonical_path(self):
        protocol = p.obs.read_small(p.ROOT / "fixtures/dual-identity-census/protocol.json")
        protocol["predeclared_at"] = "2026-01-01T00:00:00+00:00"
        paths = {"launcher": Path("launcher.exe"), "base_python": Path("base.exe"), "native": Path("cmd.exe")}
        freeze = {"protocol_sha256": "a" * 64, "frozen_at": "2026-01-01T00:00:01+00:00",
            "new_source_files_sha256": {n: "a" * 64 for n in p.SOURCE_PATHS},
            "frozen_dependency_files_sha256": {n: "a" * 64 for n in p.DEPENDENCY_PATHS},
            "review_tools_sha256": {n: "a" * 64 for n in p.REVIEW_TOOL_PATHS},
            "executables_sha256": {n: "a" * 64 for n in paths},
            "executable_path_sha256": {role: p.path_hash(path) for role, path in paths.items()}}
        freeze["executable_path_sha256"]["launcher"] = "f" * 64
        with mock.patch.object(p.obs, "read_small", side_effect=[protocol, freeze]), mock.patch.object(p.obs, "sha256_file", return_value="a" * 64):
            with self.assertRaisesRegex(p.obs.ObserverError, "opaque executable path freeze"):
                p.validate_freeze("protocol", "freeze", paths)

    def test_protocol_role_maps_cannot_be_replaced_by_self_equals_OS_assumption(self):
        protocol = p.obs.read_small(p.ROOT / "fixtures/dual-identity-census/protocol.json")
        protocol["self_executable_roles"]["worker"] = "base_python"
        with mock.patch.object(p.obs, "read_small", side_effect=[protocol, {}]), self.assertRaisesRegex(p.obs.ObserverError, "protocol/config"):
            p.validate_freeze("protocol", "freeze", {})


if __name__ == "__main__": unittest.main()
