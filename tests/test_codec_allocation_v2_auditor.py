"""Pure saved-receipt controls for v2; no ML, native process, or network."""
import builtins
from contextlib import ExitStack, contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest import mock


FORBIDDEN_ATTEMPTS = []


def forbidden(*args, **kwargs):
    FORBIDDEN_ATTEMPTS.append("ML/process/network")
    raise AssertionError("saved-receipt auditor controls must remain pure")


@contextmanager
def pure_only():
    original = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "transformers", "numpy"):
            return forbidden()
        return original(name, *args, **kwargs)
    with ExitStack() as stack:
        stack.enter_context(mock.patch("builtins.__import__", side_effect=guarded_import))
        for module, names in ((subprocess, ("Popen", "run")), (socket, ("socket", "create_connection")),
                              (os, ("system", "startfile", "fork", "posix_spawn", "spawnv", "spawnve"))):
            for name in names:
                stack.enter_context(mock.patch.object(module, name, forbidden, create=True))
        yield


with pure_only():
    from experiments import codec_allocation_v2 as producer
    from scripts import audit_codec_allocation_v2 as auditor


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                          encoding="utf-8", newline="\n")


def valid_provider(phase):
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
        "frames": frames, "frame_scope": producer.prior.PROVIDER_FRAME_SCOPE, "frame_boundary": "outside_selected_package",
        "frames_scanned_count": 3, "saved_frame_count": 2, "frames_truncated": False, "source_hashes_complete": True,
        "diagnostic_errors": [], "decision": "allowed_local_capability_probe"}])
    return value


class CodecV2AuditorTests(unittest.TestCase):
    def setUp(self):
        self.guard = pure_only()
        self.guard.__enter__()
        self.addCleanup(self.guard.__exit__, None, None, None)
        self.addCleanup(self.assertEqual, FORBIDDEN_ATTEMPTS, [])
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.result = self.root / "saved-results"
        self.result.mkdir()
        self.case = copy.deepcopy(read(ROOT / "results/codec-allocation/01_off_dense-result.json"))
        self.case["schema_version"] = 2
        self.case_dir = self.result / self.case["id"]
        self.case_dir.mkdir()
        self.raw = copy.deepcopy(read(ROOT / "results/codec-allocation/01_off_dense/preimport-ready.json"))
        # A synthetic honest v2 policy rejection, derived from the original
        # no-import receipt. This is a receipt fixture, never a runtime retry.
        self.raw["provider_guard"]["allowed_local_probe_budget"] = 0
        self.case["received_stage_receipts"] = {"preimport": self.raw}
        checked = self.raw["stage_ready_perf_counter"] + 0.01
        self.case["gate_diagnostics"] = {"preimport": producer.stage_diagnostics(self.raw,
            "preimport", self.raw["pid"], self.case["started_perf_counter"],
            self.case["case_deadline_perf_counter"], self.case["suite_deadline_perf_counter"], None, checked)}
        self.protocol = copy.deepcopy(producer.protocol_template("2026-10-18T00:59:00+00:00"))
        self.protocol_path = self.root / "protocol.json"
        write(self.protocol_path, self.protocol)
        self.freeze = {"protocol_sha256": auditor.sha(self.protocol_path),
            "frozen_at": "2026-10-18T00:59:30+00:00", "new_source_files_sha256": {},
            "frozen_dependency_files_sha256": {}, "review_tool_files_sha256": {},
            "executables_sha256": copy.deepcopy(self.case["executables_sha256"]),
            "executable_path_sha256": copy.deepcopy(self.case["executable_path_sha256"])}
        self.freeze_path = self.root / "implementation.json"
        write(self.freeze_path, self.freeze)
        self.report = {"schema_version": 2, "experiment_id": producer.EXPERIMENT_ID,
            "started_at": "2026-10-18T01:00:00+00:00", "completed_at": "2026-10-18T01:00:01+00:00",
            "cases": [self.case], "suite_launches": 1, "retries": 0, "passed": False,
            "protocol_sha256": auditor.sha(self.protocol_path), "implementation_sha256": auditor.sha(self.freeze_path),
            "math_controls": {}}
        write(self.case_dir / "worker-ready.json", self.case["worker_identity"]["self_receipt"])
        self.publish()

    def publish(self, save_raw=True):
        """Rebind case/report bytes so mutations test semantics, not stale hashes."""
        if save_raw:
            for stage, value in self.case["received_stage_receipts"].items():
                write(self.case_dir / (stage + "-ready.json"), value)
        write(self.result / (self.case["id"] + "-result.json"), self.case)
        self.report["cases"] = [self.case]
        self.report["result_sha256"] = hashlib.sha256(auditor.canonical({
            k: v for k, v in self.report.items() if k != "result_sha256"})).hexdigest()
        write(self.result / "report.json", self.report)

    def audit(self):
        return auditor.audit(self.result, self.protocol_path, self.freeze_path)

    def collect_evidence(self):
        checks = {}
        auditor.audit_v2_evidence(self.result, self.case, self.protocol, self.freeze,
                                  lambda name, value: checks.update({name: bool(value)}))
        return checks

    def valid_completion(self):
        return {"nonce": self.case["nonce"], "role": "worker", "pid": self.raw["pid"],
                "spec": copy.deepcopy(self.case["spec"]), "model_loads": 1, "forward_calls": 1,
                "backward_calls": 1, "optimizer_updates": 0, "provider_guard": valid_provider("complete")}

    def assert_rejected(self, result, check=None):
        self.assertFalse(result["passed"])
        self.assertIsNone(result["execution_acceptance"])
        self.assertIs(result["reported_execution_acceptance"], False)
        if check is not None:
            self.assertFalse(result["checks"][self.case["id"] + ":v2:" + check])
            self.assertTrue(result["checks"]["suite_payload_hash"])
            self.assertTrue(result["checks"][self.case["id"] + ":separate_result"])

    def test_honest_gate_failure_has_valid_custody_and_no_execution_acceptance(self):
        result = self.audit()
        self.assertTrue(result["passed"], result)
        self.assertIs(result["execution_acceptance"], False)
        self.assertIs(result["reported_execution_acceptance"], False)
        self.assertEqual(result["completed_case_receipts"], 1)
        self.assertEqual(result["traces"], [])

    def test_raw_saved_file_mismatch_rejected(self):
        file_value = copy.deepcopy(self.raw)
        file_value["native_thread_count"] += 1
        write(self.case_dir / "preimport-ready.json", file_value)
        self.assert_rejected(self.audit(), "raw_file:preimport")

    def test_wrong_nonce_rejected_after_consistent_rehash(self):
        self.raw["nonce"] = "f" * 64
        self.publish()
        self.assert_rejected(self.audit(), "raw_nonce_role:preimport")

    def test_faked_diagnostics_rejected_after_consistent_rehash(self):
        self.case["gate_diagnostics"]["preimport"]["predicates"]["provider_policy_budget_one"] = True
        self.publish()
        self.assert_rejected(self.audit(), "diagnostics_recomputed:preimport")

    def test_rejected_stage_cannot_be_saved_as_accepted(self):
        self.case["stages"]["preimport"] = copy.deepcopy(self.raw)
        self.publish()
        self.assert_rejected(self.audit(), "admission_consistent:preimport")

    def test_missing_cleanup_identity_rejected(self):
        self.case["failure_cleanup"]["exit_codes"].pop()
        self.publish()
        self.assert_rejected(self.audit(), "cleanup_exact_retained")

    def test_live_cleanup_exit_code_rejected(self):
        self.case["failure_cleanup"]["exit_codes"][0]["exit_code"] = 259
        self.publish()
        self.assert_rejected(self.audit(), "cleanup_empty_and_exited")

    def test_cleanup_after_case_completion_rejected(self):
        cleanup = self.case["failure_cleanup"]
        cleanup["completed_perf_counter"] = self.case["completed_perf_counter"] + 0.1
        cleanup["wall_seconds"] = cleanup["completed_perf_counter"] - cleanup["started_perf_counter"]
        self.publish()
        self.assert_rejected(self.audit(), "cleanup_timing")

    def test_missing_raw_file_returns_failure_with_original_reported_rejection(self):
        (self.case_dir / "worker-ready.json").unlink()
        self.assert_rejected(self.audit())

    def test_all_five_stage_diagnostics_recompute_with_exact_provider_phases(self):
        raw, accepted, diagnostics = {}, {}, {}
        self.case["worker_controls"] = []
        self.case["controller_controls"] = []
        start = self.raw["stage_ready_perf_counter"]
        for index, stage in enumerate(producer.STAGES):
            value = copy.deepcopy(self.raw)
            value.update(stage=stage, stage_ready_perf_counter=start + index * 0.005,
                         provider_guard=valid_provider(producer.PHASES[stage]))
            if stage == "poststudy":
                write(self.case_dir / "operation.json", {"synthetic_receipt_fixture": True})
                value["operation_sha256"] = auditor.sha(self.case_dir / "operation.json")
            if stage == "complete":
                value["provider_guard"]["allowed_local_probe_budget"] = 0
            raw[stage] = value
            previous = None if index == 0 else self.case["worker_controls"][-1]["accepted_perf_counter"]
            diagnostics[stage] = producer.stage_diagnostics(value, stage, value["pid"], self.case["started_perf_counter"],
                self.case["case_deadline_perf_counter"], self.case["suite_deadline_perf_counter"], previous,
                value["stage_ready_perf_counter"] + 0.0005)
            write(self.case_dir / (stage + "-ready.json"), value)
            if stage != "complete":
                accepted[stage] = value
                name = stage + "-continue.json"
                self.case["controller_controls"].append({"filename": name})
                self.case["worker_controls"].append({"accepted_perf_counter": value["stage_ready_perf_counter"] + 0.001,
                    "pid": value["pid"], "role": "worker", "filename": name})
        self.case.update(received_stage_receipts=raw, stages=accepted, gate_diagnostics=diagnostics,
                         error="ObserverError: codec held identity/provider/thread gate failed: complete")
        checks = self.collect_evidence()
        self.assertTrue(all(checks.values()), {k: v for k, v in checks.items() if not v})
        self.assertEqual([diagnostics[stage]["expected_provider_phase"] for stage in producer.STAGES],
                         ["preimport", "postimport", "postload", "postupdate", "complete"])

    def test_completion_semantics_cannot_be_rescued_by_refreshing_file(self):
        # Isolate the evidence helper's completion contract, not a full suite
        # acceptance claim. The full-suite auditor separately requires 8 cases.
        self.case.update(passed=True, received_stage_receipts={}, stages={}, gate_diagnostics={},
                         completion=self.valid_completion())
        write(self.case_dir / "worker-completed.json", self.case["completion"])
        self.assertTrue(all(self.collect_evidence().values()))
        baseline = copy.deepcopy(self.case["completion"])
        mutations = [lambda d: d.update(nonce="f" * 64), lambda d: d.update(role="controller"),
            lambda d: d.update(pid=d["pid"] + 1), lambda d: d.update(spec={}),
            lambda d: d.update(model_loads=0), lambda d: d.update(forward_calls=2),
            lambda d: d.update(backward_calls=0), lambda d: d.update(optimizer_updates=1),
            lambda d: d["provider_guard"].update(allowed_local_probe_budget=0),
            lambda d: d["provider_guard"].update(allowed_local_probe_count=0)]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                value = copy.deepcopy(baseline)
                mutate(value)
                self.case["completion"] = value
                write(self.case_dir / "worker-completed.json", value)
                self.assertEqual(read(self.case_dir / "worker-completed.json"), value)
                self.assertFalse(self.collect_evidence()[self.case["id"] + ":v2:completion_contract"])

    def test_pinned_model_contract_rejects_semantic_mutations_in_refreshed_raw(self):
        self.case.update(passed=True, received_stage_receipts={}, stages={}, gate_diagnostics={},
                         worker_controls=[], controller_controls=[], completion=self.valid_completion())
        model = {"model_id": producer.cost.MODEL_ID, "model_revision": producer.cost.MODEL_REVISION,
            "train_sha256": self.protocol["training"]["train_sha256"], "batch_indices": [116, 73],
            "batch_shape": [2, 65], "batch_sha256": "a" * 64, "initial_parameter_sha256": "b" * 64,
            "parameter_tensors": 76, "parameter_elements": 14067712, "optimizer_created": False,
            "holdout_opened": False, "seed": 503, "intraop_threads": 1, "interop_threads": 1,
            "deterministic_algorithms": True}
        for index, stage in enumerate(producer.STAGES[:3]):
            value = copy.deepcopy(self.raw)
            value.update(stage=stage, stage_ready_perf_counter=self.raw["stage_ready_perf_counter"] + index * 0.005,
                         provider_guard=valid_provider(producer.PHASES[stage]))
            if stage == "postload":
                value["model"] = copy.deepcopy(model)
            previous = None if index == 0 else self.case["worker_controls"][-1]["accepted_perf_counter"]
            self.case["received_stage_receipts"][stage] = value
            self.case["stages"][stage] = value
            self.case["gate_diagnostics"][stage] = producer.stage_diagnostics(value, stage, value["pid"],
                self.case["started_perf_counter"], self.case["case_deadline_perf_counter"],
                self.case["suite_deadline_perf_counter"], previous, value["stage_ready_perf_counter"] + 0.0005)
            write(self.case_dir / (stage + "-ready.json"), value)
            name = stage + "-continue.json"
            self.case["controller_controls"].append({"filename": name})
            self.case["worker_controls"].append({"pid": value["pid"], "role": "worker", "filename": name,
                "accepted_perf_counter": value["stage_ready_perf_counter"] + 0.001})
        self.assertTrue(all(self.collect_evidence().values()))
        mutations = {"model_revision": "main", "train_sha256": "c" * 64, "seed": 701,
            "batch_indices": [73, 116], "batch_shape": [2, 64], "batch_sha256": "invalid",
            "optimizer_created": True, "holdout_opened": True, "intraop_threads": 2}
        for key, changed in mutations.items():
            with self.subTest(field=key):
                mutated = dict(model, **{key: changed})
                self.case["received_stage_receipts"]["postload"]["model"] = mutated
                write(self.case_dir / "postload-ready.json", self.case["received_stage_receipts"]["postload"])
                self.assertFalse(self.collect_evidence()[self.case["id"] + ":v2:pinned_model_preparation"])

    def test_ack_identity_and_original_deadline_reject_semantic_mutations(self):
        # Accepted preimport, then an honest postimport budget rejection, so a
        # real saved control/ack pair is checked by the full saved-file auditor.
        self.raw["provider_guard"]["allowed_local_probe_budget"] = 1
        self.case["stages"] = {"preimport": self.raw}
        self.case["gate_diagnostics"]["preimport"] = producer.stage_diagnostics(self.raw, "preimport", self.raw["pid"],
            self.case["started_perf_counter"], self.case["case_deadline_perf_counter"], self.case["suite_deadline_perf_counter"],
            None, self.raw["stage_ready_perf_counter"] + 0.0005)
        name, stamp = "preimport-continue.json", self.raw["stage_ready_perf_counter"]
        control = {"nonce": self.case["nonce"], "role": "controller", "pid": 99, "stage": "preimport",
            "purpose": producer.EXPERIMENT_ID, "command": "continue", "control_index": 0,
            "admitted": True, "emitted_perf_counter": stamp + 0.0006}
        ack = {"nonce": self.case["nonce"], "role": "worker", "pid": self.raw["pid"], "filename": name,
            "control_envelope": control, "accepted_perf_counter": stamp + 0.001, "next_control_index": 1,
            "parent_wait": {"started_perf_counter": stamp + 0.0007, "completed_perf_counter": stamp + 0.002}}
        self.case["controller_controls"] = [dict(control, filename=name)]
        self.case["worker_controls"] = [ack]
        rejected = copy.deepcopy(self.raw)
        rejected.update(stage="postimport", stage_ready_perf_counter=stamp + 0.005,
                        provider_guard=valid_provider("postimport"))
        rejected["provider_guard"]["allowed_local_probe_budget"] = 0
        self.case["received_stage_receipts"]["postimport"] = rejected
        self.case["gate_diagnostics"]["postimport"] = producer.stage_diagnostics(rejected, "postimport", rejected["pid"],
            self.case["started_perf_counter"], self.case["case_deadline_perf_counter"], self.case["suite_deadline_perf_counter"],
            ack["accepted_perf_counter"], stamp + 0.006)
        self.case["error"] = "ObserverError: codec held identity/provider/thread gate failed: postimport"
        write(self.case_dir / name, control)
        def publish_ack(value):
            self.case["worker_controls"] = [value]
            write(self.case_dir / value["filename"].replace(".json", "-accepted.json"),
                  {k: v for k, v in value.items() if k != "parent_wait"})
            self.publish()
        publish_ack(ack)
        self.assertTrue(self.audit()["passed"])
        for fields in ({"pid": self.raw["pid"] + 1}, {"role": "controller"}, {"filename": "other-continue.json"},
                       {"accepted_perf_counter": -1}, {"accepted_perf_counter": self.case["case_deadline_perf_counter"]}):
            with self.subTest(mutation=fields):
                publish_ack(dict(ack, **fields))
                self.assert_rejected(self.audit(), "ack_identity_deadline:0")


if __name__ == "__main__":
    unittest.main()
