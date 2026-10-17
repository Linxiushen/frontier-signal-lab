"""Stdlib mock controls; no ML import, subprocess, native job or acceptance."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments import process_observer as obs
from experiments import training_observer_v3 as p

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
        value = obs.read_small(p.ROOT / "fixtures/training-observer-v3/protocol.json")
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


PROVIDER_PATH = Path("mock-site/urllib3/util/connection.py").resolve()
SOURCE_PATH_HASH = "f" * 64


def frame_chain(extra=0, boundary=True):
    tail = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(p.ROOT / "outside.py"), co_name="outside"),
        f_lineno=1, f_back=None) if boundary else None
    for _ in range(extra):
        tail = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(PROVIDER_PATH), co_name="helper"), f_lineno=9, f_back=tail)
    tail = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(PROVIDER_PATH), co_name="<module>"), f_lineno=137, f_back=tail)
    return SimpleNamespace(f_code=SimpleNamespace(co_filename=str(PROVIDER_PATH), co_name="_has_ipv6"), f_lineno=127, f_back=tail)


def provider(phase="postimport", budget=1):
    frames = [{"package_relative_path": p.PROVIDER_SOURCE_RELATIVE_PATH,
        "function": name, "line": line, "sha256": p.PROVIDER_SOURCE_SHA256,
        "normalized_path_sha256": SOURCE_PATH_HASH} for name,line in (("_has_ipv6",127),("<module>",137))]
    count = 0 if phase in ("preimport","injected_import") else 1
    return {"installed": True, "python_audit_only": True, "native_network_sandbox": False,
        "external_providers_permitted": False, "synthetic_probe_denials": 1,
        "unexpected_denied_events": [], "denied_audit_events": list(p.PROVIDER_DENIED_EVENTS),
        "policy_id": p.PROVIDER_POLICY_ID, "phase": phase,
        "provider_source": {"package_relative_path": p.PROVIDER_SOURCE_RELATIVE_PATH,
            "sha256": p.PROVIDER_SOURCE_SHA256, "normalized_path_sha256": SOURCE_PATH_HASH},
        "allowed_local_probe_budget": budget, "allowed_local_probe_count": count,
        "diagnostic_event_limit": 4, "diagnostic_overflow_count": 0, "observed_event_count": count,
        "diagnostic_events": [{"event_index":0,"event":"socket.bind","perf_counter":10.0,"phase":"import",
            "socket_family_code":23,"socket_type_code":1,"socket_protocol":0,
            "endpoint":{"shape":"tuple2","host_kind":"exact_ipv6_loopback","port_kind":"ephemeral_zero","address_logged":False},
            "frames":frames,"frame_scope":p.PROVIDER_FRAME_SCOPE,"frame_boundary":"outside_selected_package",
            "frames_scanned_count":3,"saved_frame_count":2,"frames_truncated":False,"source_hashes_complete":True,
            "diagnostic_errors":[],"decision":"allowed_local_capability_probe"}] if count else []}


class MockGuard:
    def __init__(self,budget=1):
        self.phase="preimport"; self.budget=budget; self.install=mock.Mock()
    def set_phase(self,phase): self.phase=phase
    def receipt(self): return provider(self.phase,self.budget)


class ProviderTests(unittest.TestCase):
    def guard(self, budget=True):
        with mock.patch.object(p,"source_digest",return_value=p.PROVIDER_SOURCE_SHA256), \
                mock.patch.object(p.dual,"path_hash",return_value=SOURCE_PATH_HASH):
            return p.LocalProviderGuard(PROVIDER_PATH,budget)

    def diagnose(self,guard,event="socket.bind",address=("::1",0),family=23,kind=1,protocol=0,frames=None):
        sock=SimpleNamespace(family=family,type=kind,proto=protocol)
        with mock.patch.object(p,"source_digest",return_value=p.PROVIDER_SOURCE_SHA256), \
                mock.patch.object(p.dual,"path_hash",return_value=SOURCE_PATH_HASH), \
                mock.patch.object(p.sys,"_getframe",return_value=frame_chain() if frames is None else frames):
            return guard.audit(event,(sock,address))

    def installed(self,budget=True):
        guard=self.guard(budget)
        with mock.patch.object(p.sys,"addaudithook") as register, mock.patch.object(p.sys,"audit",
                side_effect=lambda event,*args:guard.audit(event,args)):
            guard.install()
        register.assert_called_once_with(guard.audit)
        return guard

    def test_exact_import_probe_allowed_once_and_synthetic_probe_is_separate(self):
        guard=self.installed()
        self.assertTrue(p.validate_provider(guard.receipt(),"preimport"))
        guard.set_phase("import");self.diagnose(guard);guard.set_phase("postimport")
        self.assertTrue(p.validate_provider(guard.receipt(),"postimport"))
        self.assertEqual(guard.receipt()["observed_event_count"],1)
        self.assertEqual(guard.receipt()["synthetic_probe_denials"],1)
        guard.set_phase("import")
        with self.assertRaises(PermissionError):self.diagnose(guard)
        self.assertFalse(p.validate_provider(guard.receipt()))

    def test_wrong_endpoint_family_type_protocol_or_phase_denied(self):
        changes=[{"address":("127.0.0.1",0)},{"address":("::1",True)},{"address":("::1",1)},
            {"address":("::1",0,0,0)},{"address":["::1",0]},{"address":"secret-host.example"},
            {"family":2},{"family":True},{"kind":2},{"protocol":6}]
        for change in changes:
            guard=self.installed();guard.set_phase("import")
            with self.subTest(change=change),self.assertRaises(PermissionError):self.diagnose(guard,**change)
            self.assertEqual(guard.receipt()["allowed_local_probe_count"],0)
        for phase in ("preimport","postimport","load","train","busy","complete","injected_import"):
            guard=self.installed();guard.set_phase(phase)
            with self.subTest(phase=phase),self.assertRaises(PermissionError):self.diagnose(guard)
        guard=self.installed(False);guard.set_phase("import")
        with self.assertRaises(PermissionError):self.diagnose(guard)

    def test_wrong_source_path_hash_function_line_or_module_frame_denied(self):
        for change in ("path","hash","pathhash","function","line","modulefunction","moduleline","extra","nostackboundary"):
            guard=self.installed();guard.set_phase("import");frames=frame_chain()
            if change=="path":frames.f_code.co_filename=str(PROVIDER_PATH.parent / "other.py")
            elif change=="function":frames.f_code.co_name="other"
            elif change=="line":frames.f_lineno=128
            elif change=="modulefunction":frames.f_back.f_code.co_name="other"
            elif change=="moduleline":frames.f_back.f_lineno=138
            elif change=="extra":frames=frame_chain(extra=1)
            elif change=="nostackboundary":frames=frame_chain(boundary=False)
            with mock.patch.object(p,"source_digest",return_value="b"*64 if change=="hash" else p.PROVIDER_SOURCE_SHA256), \
                    mock.patch.object(p.dual,"path_hash",return_value="b"*64 if change=="pathhash" else SOURCE_PATH_HASH), \
                    mock.patch.object(p.sys,"_getframe",return_value=frames),self.subTest(change=change),self.assertRaises(PermissionError):
                guard.audit("socket.bind",(SimpleNamespace(family=23,type=1,proto=0),("::1",0)))

    def test_diagnostics_bound_frames_and_source_bytes_and_never_save_secrets(self):
        guard=self.installed();guard.set_phase("import")
        frames=frame_chain(extra=8)
        with self.assertRaises(PermissionError):self.diagnose(guard,frames=frames,address=("private-secret.example",443))
        event=guard.receipt()["diagnostic_events"][0]
        self.assertTrue(event["frames_truncated"]);self.assertEqual(len(event["frames"]),8)
        self.assertEqual(event["frames_scanned_count"],9)
        raw=json.dumps(guard.receipt())
        for secret in ("private-secret.example",str(PROVIDER_PATH),"outside.py","443"):
            self.assertNotIn(secret,raw)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bounded.py";path.write_bytes(b"x"*(p.PROVIDER_CONFIG["maximum_source_file_bytes"]+1))
            with self.assertRaises(obs.ObserverError):p.source_digest(path)
            path.write_bytes(b"x");self.assertEqual(p.source_digest(path),p.hashlib.sha256(b"x").hexdigest())

    def test_unsafe_or_unreadable_frame_fails_closed_without_outside_hashing(self):
        for bad in ("line","function","hash"):
            guard=self.installed();guard.set_phase("import");frames=frame_chain()
            if bad=="line":frames.f_lineno=True
            if bad=="function":frames.f_code.co_name="unsafe/path"
            with mock.patch.object(p,"source_digest",side_effect=OSError("secret-path") if bad=="hash" else None,
                    return_value=p.PROVIDER_SOURCE_SHA256),mock.patch.object(p.sys,"_getframe",return_value=frames), \
                    self.subTest(bad=bad),self.assertRaises(PermissionError):
                guard.audit("socket.bind",(SimpleNamespace(family=23,type=1,proto=0),("::1",0)))
            receipt=guard.receipt();self.assertFalse(receipt["diagnostic_events"][0]["source_hashes_complete"])
            self.assertNotIn("secret-path",json.dumps(receipt))
        guard=self.installed()
        with mock.patch.object(p,"source_digest",return_value=p.PROVIDER_SOURCE_SHA256) as digest, \
                mock.patch.object(p.dual,"path_hash",return_value=SOURCE_PATH_HASH):
            data=guard.capture_frames(frame_chain())
        self.assertEqual(digest.call_count,2);self.assertEqual(data["frames_scanned_count"],3)

    def test_all_other_events_denied_and_overflow_count_never_hides_attempts(self):
        guard=self.installed();guard.set_phase("import")
        for event in p.PROVIDER_DENIED_EVENTS:
            with self.subTest(event=event),self.assertRaises(PermissionError):guard.audit(event,())
        receipt=guard.receipt();self.assertEqual(len(receipt["diagnostic_events"]),4)
        self.assertEqual(receipt["observed_event_count"],7);self.assertEqual(receipt["diagnostic_overflow_count"],3)
        self.assertEqual(len(receipt["unexpected_denied_events"]),4)
        self.assertFalse(p.validate_provider(receipt));guard.audit("open",("local",))

    def test_receipt_is_detached_and_malformed_records_cannot_pass(self):
        guard=self.installed();guard.set_phase("import");self.diagnose(guard);guard.set_phase("postimport")
        row=guard.receipt();row["diagnostic_events"][0]["frames"][0]["line"]=0
        self.assertTrue(p.validate_provider(guard.receipt()))
        changes=[("installed",False),("synthetic_probe_denials",True),("unexpected_denied_events",["socket.connect"]),
            ("native_network_sandbox",True),("external_providers_permitted",True),("denied_audit_events",[]),
            ("provider_source",None),("diagnostic_events",[None]),("diagnostic_event_limit",True),
            ("observed_event_count",2),("diagnostic_overflow_count",1),("policy_id","other")]
        for key,value in changes:
            row=provider();row[key]=value
            with self.subTest(key=key):self.assertFalse(p.validate_provider(row))
        for key,value in (("frames",[None,None]),("frames",{}),("frames_truncated",True),
                ("frame_boundary","stack_end"),("frames_scanned_count",2),("saved_frame_count",True),
                ("perf_counter",float("nan")),("event_index",True),("decision","denied")):
            row=provider();row["diagnostic_events"][0][key]=value
            with self.subTest(key=key):self.assertFalse(p.validate_provider(row))

    def test_explicit_source_path_and_hash_required_before_install(self):
        with mock.patch.object(p,"source_digest",return_value="a"*64),self.assertRaises(obs.ObserverError):
            p.LocalProviderGuard(PROVIDER_PATH,True)
        with self.assertRaises(obs.ObserverError):p.LocalProviderGuard("wrong.py",True)
        guard=self.guard()
        with mock.patch.object(p.sys,"addaudithook"),mock.patch.object(p.sys,"audit"),self.assertRaises(obs.ObserverError):guard.install()


class NewCustodyTests(unittest.TestCase):
    def custody_report(self):
        return {"provider_source_path_sha256":SOURCE_PATH_HASH,
            "stages":{label:{"provider_guard":provider(label)} for label in (*p.STAGES,"allocated")},
            "healthy_completion":{"provider_guard":provider("complete")}}

    def test_exact_frozen_source_cumulative_event_and_import_clock_custody(self):
        report=self.custody_report()
        report["stages"]["postimport"].update(import_started_perf_counter=9.0,import_completed_perf_counter=11.0)
        p.verify_provider_custody(report,"healthy")
        self.assertTrue(report["provider_custody_verified"])
        for changed in ("source","eventtime","eventidentity","missingevent"):
            bad=copy.deepcopy(report)
            if changed=="source":bad["stages"]["postload"]["provider_guard"]["provider_source"]["normalized_path_sha256"]="e"*64
            elif changed=="eventtime":bad["stages"]["postimport"]["import_completed_perf_counter"]=9.9
            elif changed=="eventidentity":bad["healthy_completion"]["provider_guard"]["diagnostic_events"][0]["perf_counter"]=10.1
            else:bad["healthy_completion"]["provider_guard"]["diagnostic_events"]=[]
            with self.subTest(changed=changed),self.assertRaises(obs.ObserverError):p.verify_provider_custody(bad,"healthy")

    def test_stage_provider_failure_reports_its_own_condition(self):
        ready={"pid":2000,"stage":"preimport","native_thread_count":7,"provider_guard":provider("preimport")}
        ready["provider_guard"]["installed"]=False
        with mock.patch.object(p,"wait",return_value=ready),self.assertRaisesRegex(obs.ObserverError,"provider guard"):
            p.read_stage(None,None,SimpleNamespace(pid=2000),None,Path("unused"),"preimport",NONCE,
                {"mode":"healthy"},100,200)

    def report(self):
        return {"controller_controls": [], "case_deadline_perf_counter": 100,
            "suite_deadline_perf_counter": 200, "role_decisions": [{"decision_index": 0,
                "label": "before_native", "admitted": True, "completed_perf_counter": 9.0}]}

    def test_control_requires_exact_plan_current_admission_and_completed_census(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(p.time, "perf_counter", return_value=10):
            folder = Path(tmp); report = self.report()
            p.control(folder, "create-native.json", NONCE, "create-native", report)
            row = report["controller_controls"][0]
            self.assertEqual(row["emitted_perf_counter"], 10)
            self.assertEqual(row["role_decision_label"], "before_native")
            self.assertTrue(row["training_v3_authorized"])
            for changes, name, command in (({"admitted": False}, "preimport-parent-done.json", "parent-sampled"),
                    ({"completed_perf_counter": 11}, "preimport-parent-done.json", "parent-sampled"),
                    ({}, "finish.json", "finish")):
                bad = self.report(); bad["role_decisions"][0].update(changes)
                with self.subTest(changes=changes), self.assertRaises(obs.ObserverError):
                    p.control(folder, name, NONCE, command, bad)

    def test_worker_control_acceptance_has_exact_nonce_sequence_decision_and_monotonic_time(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(p.time, "perf_counter", return_value=10):
            folder = Path(tmp); report = self.report()
            p.control(folder, "create-native.json", NONCE, "create-native", report)
            row = {k: v for k, v in report["controller_controls"][0].items() if k != "filename"}
            state = {"next_index": 0, "last_emitted": 0}
            with mock.patch.object(p.base, "wait_json", return_value=row):
                p.require_control(folder, "create-native.json", NONCE, "create-native", "before_native", 0, state, 100, 200)
            self.assertEqual(state["next_index"], 1)
            receipt = obs.read_small(folder / "create-native-accepted.json")
            self.assertEqual(receipt["control_envelope"], row)
            for field, changed in (("emitted_perf_counter", 11), ("emitted_perf_counter", float("nan")),
                    ("control_index", 1), ("role_decision_index", True), ("role_decision_label", "postload"),
                    ("purpose", "inventory-only"), ("training_v3_authorized", False)):
                altered = {**row, field: changed}
                with self.subTest(field=field), mock.patch.object(p.base, "wait_json", return_value=altered), self.assertRaises(obs.ObserverError):
                    p.require_control(folder, "unused.json", NONCE, "create-native", "before_native", 0,
                        {"next_index": 0, "last_emitted": 0}, 100, 200)

    def test_inventory_preserves_rejection_and_private_paths_never_become_public_field(self):
        job = SimpleNamespace()
        launcher, actual, native = [SimpleNamespace(pid=i, creation_filetime=i * 10) for i in (1, 2, 3)]
        paths = {r: Path(r + ".exe") for r in ("launcher", "base_python", "native", "conhost")}
        report = {"_paths": paths, "executables_sha256": {}, "case_deadline_perf_counter": 100,
            "suite_deadline_perf_counter": 200, "parent_query_costs": []}
        decision = {"admitted": True, "pinned_auxiliaries": {"launcher": {"pid": 4}}}
        with mock.patch.object(p.role, "policy_stage", return_value=({"label": "postload"}, decision)) as policy:
            self.assertEqual(p.inventory(job, launcher, actual, native, report, "postload"), {"label": "postload"})
        self.assertEqual(policy.call_args.args[2], {1: (10, "launcher"), 2: (20, "base_python"), 3: (30, "native")})
        self.assertEqual(report["pinned_auxiliaries"], {"launcher": {"pid": 4}})
        self.assertEqual(report["parent_query_costs"][0]["kind"], "held_role_census_and_liveness")
        with mock.patch.object(p.role, "policy_stage", return_value=({}, {"admitted": False})), self.assertRaises(obs.ObserverError):
            p.inventory(job, launcher, actual, native, report, "postupdate")
        self.assertIs(report["_paths"], paths)

    def test_cleanup_exact_creation_pin_rejects_missing_duplicate_and_reused_pid(self):
        report = {"launcher": {"pid": 1, "creation_filetime": 10}, "censuses": [],
            "cleanup": {"all_retained_handles_exited": True, "job_active_count": 0,
                "exit_codes": [{"pid": 1, "creation_filetime": 10, "exit_code": 37}]}}
        p.verify_cleanup(report, "prehandshake_fail")
        for rows in ([], [{"pid": 1, "creation_filetime": 11, "exit_code": 37}],
                [report["cleanup"]["exit_codes"][0]] * 2):
            bad = copy.deepcopy(report); bad["cleanup"]["exit_codes"] = rows
            with self.subTest(rows=rows), self.assertRaises(obs.ObserverError):
                p.verify_cleanup(bad, "prehandshake_fail")


class FreezeAndWorkerTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(p.os.environ, {"SystemRoot": p.os.environ.get("SystemRoot", "mock-system")})
        patch.start(); self.addCleanup(patch.stop)

    def context(self):
        protocol = obs.read_small(p.ROOT / "fixtures/training-observer-v3/protocol.json")
        protocol["predeclared_at"] = "2026-01-01T00:00:00+00:00"
        paths = {"launcher": Path("launcher/python.exe"), "base_python": Path("base/python.exe"),
            "native": Path(p.os.environ["SystemRoot"]) / "System32/cmd.exe",
            "conhost": Path(p.os.environ["SystemRoot"]) / "System32/conhost.exe"}
        freeze = {"protocol_sha256": "a" * 64, "frozen_at": "2026-01-01T00:00:01+00:00",
            "new_source_files_sha256": {n: "a" * 64 for n in p.SOURCE_PATHS},
            "frozen_dependency_files_sha256": {n: "a" * 64 for n in p.DEPENDENCY_PATHS},
            "review_tools_sha256": {n: "a" * 64 for n in p.REVIEW_TOOL_PATHS},
            "python_executable_sha256": "a" * 64, "base_python_executable_sha256": "a" * 64,
            "native_executable_sha256": "a" * 64, "executables_sha256": {r: "a" * 64 for r in paths},
            "executable_path_sha256": {r: p.dual.path_hash(v) for r, v in paths.items()},
            "provider_source_sha256": p.PROVIDER_SOURCE_SHA256, "provider_source_path_sha256": p.dual.path_hash(PROVIDER_PATH)}
        return protocol, paths, freeze

    def test_freeze_requires_four_exact_paths_files_reviewers_case_order_and_control_plan(self):
        protocol, paths, freeze = self.context()
        def check():
            return p.validate_freeze("protocol", "freeze", *paths.values(), PROVIDER_PATH, "model", p.ROOT / "fixtures/activation-cost")
        with mock.patch.object(p.obs, "read_small", side_effect=lambda x: protocol if str(x) == "protocol" else freeze), \
                mock.patch.object(p.obs, "sha256_file", return_value="a" * 64), \
                mock.patch.object(p, "source_digest", return_value=p.PROVIDER_SOURCE_SHA256), \
                mock.patch.object(p.cost, "verify_model_assets") as assets, mock.patch.object(p.cost, "validate_fixture"):
            check()
            assets.assert_called_once_with("model")
            for field in ("new_source_files_sha256", "frozen_dependency_files_sha256", "review_tools_sha256",
                    "executables_sha256", "executable_path_sha256"):
                saved = freeze[field]; freeze[field] = {}
                with self.subTest(field=field), self.assertRaises(obs.ObserverError): check()
                freeze[field] = saved
            for field in ("provider_source_sha256","provider_source_path_sha256"):
                saved=freeze[field];freeze[field]="b"*64
                with self.subTest(field=field),self.assertRaises(obs.ObserverError):check()
                freeze[field]=saved
            protocol["provider_custody"]["provider_config"]["maximum_allowed_probes_per_ML_worker"]=2
            with self.assertRaises(obs.ObserverError):check()
            protocol["provider_custody"]["provider_config"]["maximum_allowed_probes_per_ML_worker"]=1
            protocol["control_plan"].reverse()
            with self.assertRaises(obs.ObserverError): check()

    def test_stage_records_guard_threads_and_consumes_timestamped_measurement_then_release(self):
        backend = SimpleNamespace(self_reading=lambda: reading())
        rows = []
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            messages = []
            for index, command in ((1, "parent-sampled"), (2, "continue")):
                messages.append({"nonce": NONCE, "role": "controller", "pid": 1000,
                    "command": command, "purpose": p.CONTROL_PURPOSE, "training_v3_authorized": True,
                    "role_policy_admitted": True, "role_decision_index": 1,
                    "role_decision_label": "preimport", "control_index": index, "emitted_perf_counter": 9})
            with mock.patch.object(p.work, "native_thread_count", return_value=4), \
                    mock.patch.object(p.time, "perf_counter", return_value=10), \
                    mock.patch.object(p.base, "wait_json", side_effect=messages), \
                    mock.patch.object(p.obs, "write_new", side_effect=lambda path, value: rows.append((path.name, value))):
                p.memory_stage(backend, folder, "preimport", NONCE, 100, 200,
                    {"next_index": 1, "last_emitted": 0}, MockGuard(), torch_imported=False)
            self.assertEqual([name for name, _ in rows], ["preimport-ready.json", "preimport-before.json",
                "preimport-parent-done-accepted.json", "preimport-after.json", "preimport-continue-accepted.json"])
            self.assertEqual(rows[0][1]["provider_guard"], provider("preimport"))
            self.assertEqual(rows[0][1]["native_thread_count"], 4)

    def controls_fixture(self, folder):
        report = {"nonce": NONCE, "controller_controls": [], "case_deadline_perf_counter": 100,
            "native_descendant": {"launch_receipt": {"launch_started_perf_counter": 1.2}},
            "import_failure_receipt": {"import_started_perf_counter": 3.2}}
        for index, (filename, command, label, decision) in enumerate(p.CONTROL_PLAN[:3]):
            row = {"filename": filename, "nonce": NONCE, "role": "controller", "pid": 1000,
                "command": command, "purpose": p.CONTROL_PURPOSE, "training_v3_authorized": True,
                "role_policy_admitted": True, "role_decision_index": decision,
                "role_decision_label": label, "control_index": index, "emitted_perf_counter": index + 1}
            report["controller_controls"].append(row)
            obs.write_new(folder / filename.replace(".json", "-accepted.json"),
                {"nonce": NONCE, "role": "worker", "pid": 2000, "filename": filename,
                    "control_envelope": {k: v for k, v in row.items() if k != "filename"},
                    "accepted_perf_counter": index + 1.1, "next_control_index": index + 1})
        return report

    def test_saved_controls_verify_exact_received_copy_and_action_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); report = self.controls_fixture(folder)
            p.verify_controls(folder, report, "import_fail", 2000)
            self.assertTrue(report["control_custody_verified"])
            report["native_descendant"]["launch_receipt"]["launch_started_perf_counter"] = 1.0
            with self.assertRaisesRegex(obs.ObserverError, "action precedes"):
                p.verify_controls(folder, report, "import_fail", 2000)
            report["controller_controls"][0]["emitted_perf_counter"] = 2
            with self.assertRaisesRegex(obs.ObserverError, "acceptance differs"):
                p.verify_controls(folder, report, "import_fail", 2000)

    def test_actual_worker_path_uses_new_identity_guard_controls_and_exact_two_update_helper(self):
        backend = mock.Mock(); child = mock.Mock(); child.wait.return_value = 0; child.stdin.closed = False
        guard = MockGuard()
        torch, transformers = SimpleNamespace(__version__="2.9.1+cpu"), SimpleNamespace(__version__="4.57.3")
        emitted = []
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(p.obs, "WindowsBackend", return_value=backend), \
                mock.patch.object(p, "LocalProviderGuard", return_value=guard), \
                mock.patch.object(p.dual, "publish_identity") as identity, \
                mock.patch.object(p, "require_control") as control, \
                mock.patch.object(p.subprocess, "Popen", return_value=child) as popen, \
                mock.patch.object(p, "memory_stage") as stages, \
                mock.patch.object(p, "import_packages", return_value=(torch, transformers)) as imports, \
                mock.patch.object(p, "prepare_model", return_value=("model", "optimizer", ["batch"], model_info())) as prepare, \
                mock.patch.object(p, "two_dense_updates", return_value=operation()) as updates, \
                mock.patch.object(p.obs, "write_new", side_effect=lambda path, value: emitted.append((path.name, value))), \
                mock.patch.object(p.time, "perf_counter", return_value=10):
            p.worker(Path(tmp), NONCE, Path("cmd.exe"), PROVIDER_PATH, Path("model"), Path("fixture"), "healthy", 64 * MIB, 100, 200)
        identity.assert_called_once()
        self.assertEqual(identity.call_args.args[2], "worker-ready.json")
        self.assertEqual([call.args[2] for call in stages.call_args_list], [*p.STAGES, "allocated"])
        self.assertEqual([call.args[3] for call in control.call_args_list], ["create-native", "finish"])
        guard.install.assert_called_once(); imports.assert_called_once(); prepare.assert_called_once()
        updates.assert_called_once_with("model", "optimizer", ["batch"])
        self.assertIs(popen.call_args.kwargs["shell"], False)
        self.assertTrue(emitted[-1][1]["native_released_nonempty_line"])
        self.assertEqual(emitted[-1][1]["provider_guard"], provider("complete"))
        child.stdin.write.assert_called_once_with(b"done\r\n")

    def test_actual_worker_precise_import_failure_never_calls_ml_loader_or_updates(self):
        class ExitRequested(BaseException): pass
        backend = mock.Mock(); child = mock.Mock(); child.stdin.closed = False
        guard = MockGuard()
        emitted = []
        guard = MockGuard(0)
        missing = "training_observer_v3_missing_dependency_" + NONCE
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(p.obs, "WindowsBackend", return_value=backend), \
                mock.patch.object(p, "LocalProviderGuard", return_value=guard), \
                mock.patch.object(p.dual, "publish_identity"), mock.patch.object(p, "require_control"), \
                mock.patch.object(p.subprocess, "Popen", return_value=child), mock.patch.object(p, "memory_stage"), \
                mock.patch.object(p.importlib, "import_module", side_effect=ModuleNotFoundError(name=missing)) as injected, \
                mock.patch.object(p, "import_packages") as imports, mock.patch.object(p, "prepare_model") as prepare, \
                mock.patch.object(p, "two_dense_updates") as updates, \
                mock.patch.object(p.os, "_exit", side_effect=ExitRequested) as exit_call, \
                mock.patch.object(p.obs, "write_new", side_effect=lambda path, value: emitted.append((path.name, value))), \
                self.assertRaises(ExitRequested):
            p.worker(Path(tmp), NONCE, Path("cmd.exe"), PROVIDER_PATH, Path("model"), Path("fixture"), "import_fail", 0, 100, 200)
        injected.assert_called_once_with(missing); exit_call.assert_called_once_with(38)
        imports.assert_not_called(); prepare.assert_not_called(); updates.assert_not_called()
        receipt = next(value for name, value in emitted if name == "expected-import-failure.json")
        self.assertEqual(receipt["missing_module"], missing)
        self.assertEqual(receipt["exception_type"], "ModuleNotFoundError")
        self.assertEqual(receipt["model_loads"], 0)

    def test_propagated_worker_denial_retains_bounded_guard_phase_and_timestamp(self):
        backend=mock.Mock();child=mock.Mock();child.stdin.closed=False
        guard=MockGuard();emitted=[]
        denied=provider("import");denied["unexpected_denied_events"]=["socket.connect"]
        denied["allowed_local_probe_count"]=0
        denied["diagnostic_events"][0].update(event="socket.connect",decision="denied")
        guard.receipt=lambda:copy.deepcopy(denied)
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(p.obs,"WindowsBackend",return_value=backend), \
                mock.patch.object(p,"LocalProviderGuard",return_value=guard),mock.patch.object(p.dual,"publish_identity"), \
                mock.patch.object(p,"require_control"),mock.patch.object(p.subprocess,"Popen",return_value=child), \
                mock.patch.object(p,"memory_stage"),mock.patch.object(p,"import_packages",side_effect=PermissionError("denied event")), \
                mock.patch.object(p,"prepare_model") as prepare,mock.patch.object(p,"two_dense_updates") as updates, \
                mock.patch.object(p.time,"perf_counter",return_value=10), \
                mock.patch.object(p.obs,"write_new",side_effect=lambda path,value:emitted.append((path.name,value))), \
                self.assertRaises(PermissionError):
            p.worker(Path(tmp),NONCE,Path("cmd.exe"),PROVIDER_PATH,Path("model"),Path("fixture"),"healthy",64*MIB,100,200)
        failure=next(value for name,value in emitted if name=="worker-failure.json")
        self.assertEqual(failure["phase"],"import");self.assertEqual(failure["failure_perf_counter"],10)
        self.assertEqual(failure["provider_guard"],denied)
        prepare.assert_not_called();updates.assert_not_called()
        self.assertFalse(p.validate_provider(failure["provider_guard"]))


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
            "base_python_executable_sha256": "b" * 64, "native_executable_sha256": "c" * 64,
            "executables_sha256": {"launcher": "a" * 64, "base_python": "b" * 64, "native": "c" * 64, "conhost": "d" * 64},
            "executable_path_sha256": {role: "e" * 64 for role in ("launcher", "base_python", "native", "conhost")},
            "provider_source_sha256": p.PROVIDER_SOURCE_SHA256, "provider_source_path_sha256": SOURCE_PATH_HASH}
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
            mock.patch.object(p, "control", side_effect=lambda folder, name, nonce, command, report: self.controls.append((name, command))),
            mock.patch.object(p, "overhead_windows"), mock.patch.object(p, "inventory", side_effect=self.inventory),
            mock.patch.object(p.dual, "verify_self_executable", return_value={"self_executable_matches_frozen": True}),
            mock.patch.object(p, "verify_controls"),
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
        self.inventory(job, launcher, actual, native, report, label)
        detail = {"pid": 2000, "stage": label, "native_thread_count": 4, "provider_guard": provider(label,0 if self.current_mode=="import_fail" else 1)}
        if label == "preimport":
            detail.update(torch_imported=False, transformers_imported=False)
        elif label == "postimport":
            detail.update(torch_version="2.9.1+cpu", transformers_version="4.57.3",import_started_perf_counter=9.9,import_completed_perf_counter=10.1)
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
                "native_released_nonempty_line": True, "model_loads": 1, "optimizer_steps": 2, "provider_guard": provider("complete")}
        if name == "expected-import-failure.json":
            return {"pid": 2000, "stage": "import", "exception_type": "ImportError" if self.bad_import else "ModuleNotFoundError",
                "missing_module": "training_observer_v3_missing_dependency_" + nonce,
                "torch_imported": False, "transformers_imported": False, "model_loads": 0,
                "optimizer_steps": 0, "expected_exit_code": 38, "provider_guard": provider("injected_import",0)}
        if name == "busy-ready.json":
            return {"pid": 2000, "perf_counter": self.clock.now(), "extra_backward_calls": 0,
                "extra_optimizer_steps": 0, "model_forward_no_grad": True, "provider_guard": provider("busy")}
        if name == "busy-first-operation.json":
            return {"pid": 2000, "completed_perf_counter": self.clock.now(), "model_forward_iterations_completed": 1,
                "extra_backward_calls": 1 if self.bad_busy else 0, "extra_optimizer_steps": 0, "model_forward_no_grad": True, "provider_guard": provider("busy")}
        raise AssertionError(name)

    def cleanup(self, *args):
        if self.cannot_clean:
            raise obs.ObserverError("injected cleanup failure")
        return {"all_retained_handles_exited": True, "job_active_count": 0,
            "exit_codes": [{"pid": pid, "creation_filetime": created, "exit_code": (38 if self.current_mode == "import_fail" and pid in (1000,2000) else (0xE003 if self.current_mode in ("timeout","private_cap") and pid in (1000,2000) else 0))}
                for pid,created in ([(1000,10)] if self.current_mode == "prehandshake_fail" else [(1000,10),(2000,20),(3000,30),(4000,40),(5000,50)])], "wall_seconds": 0.02}

    def inventory(self, job, launcher, actual, native, report, label):
        nodes = [{"pid": pid, "creation_filetime": created} for pid,created in ([(1000,10),(2000,20),(4000,40)] if native is None else [(1000,10),(2000,20),(3000,30),(4000,40),(5000,50)])]
        report["censuses"].append({"label": label, "processes": nodes})
        report["role_decisions"].append({"label":label,"decision_index":len(report["role_decisions"]),"admitted":True,"primary_roles":[{"pid":1000,"role":"launcher"},{"pid":2000,"role":"base_python"}]})
        return report["censuses"][-1]

    def run_case(self, index):
        self.current_mode = p.CASES[index][1]
        return p.run_case(p.CASES[index], Path("launcher.exe"), Path("base.exe"), Path("cmd.exe"), Path("conhost.exe"), PROVIDER_PATH,
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

    def test_hidden_worker_failure_rejects_success_and_copies_exact_raw_diagnostic(self):
        failure={"nonce":NONCE,"role":"worker","pid":2000,"phase":"complete",
            "failure_perf_counter":10.1,"provider_guard":provider("complete"),"error":"injected late failure"}
        def cleanup(*args):
            path=self.output / p.CASES[0][0] / "worker-failure.json"
            if not path.exists():obs.write_new(path,failure)
            return self.cleanup(*args)
        with mock.patch.object(p.secrets,"token_hex",return_value=NONCE),mock.patch.object(p.work,"cleanup",side_effect=cleanup):
            result=self.run_case(0)
        self.assertFalse(result["passed"]);self.assertEqual(result["worker_failure_receipt"],failure)
        self.assertIn("worker failure receipt",result["error"])

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


