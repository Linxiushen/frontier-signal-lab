"""Post-outcome saved-byte checks only; no model or frozen-module execution."""
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("codec_failure_supplement", ROOT / "scripts/audit_codec_preimport_failure.py")
supplement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supplement)


class SavedPreimportFailureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "raw"
        self.directory.mkdir()
        source = ROOT / "results/codec-allocation"
        paths = ["report.json", "01_off_dense-result.json", "01_off_dense/worker-ready.json",
                 "01_off_dense/preimport-ready.json"]
        for name in paths:
            target = self.directory / name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes((source / name).read_bytes())

    def audit(self, expected=None):
        original = builtins.__import__

        def denied(name, *args, **kwargs):
            if name.split(".")[0] in ("torch", "transformers", "numpy", "experiments"):
                raise AssertionError("ML or frozen producer import during saved-byte audit")
            return original(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=denied):
            return supplement.audit(self.directory, expected_review=expected)

    def rewrite_case(self, mutate):
        report = json.loads((self.directory / "report.json").read_bytes())
        mutate(report["cases"][0])
        case = report["cases"][0]
        (self.directory / "01_off_dense-result.json").write_text(json.dumps(case), encoding="utf-8")
        report["result_sha256"] = hashlib.sha256(supplement.canonical(
            {k: v for k, v in report.items() if k != "result_sha256"})).hexdigest()
        (self.directory / "report.json").write_text(json.dumps(report), encoding="utf-8")

    def test_failed_execution_is_consistent_without_accepting_measurement(self):
        result = self.audit()
        self.assertTrue(result["passed"])
        self.assertTrue(result["receipt_consistency"])
        self.assertIs(result["execution_acceptance"], False)
        self.assertEqual(result["diagnosis"]["failed_provider_predicates"], ["allowed_local_probe_budget"])
        self.assertEqual(result["execution_counts"]["model_loads"], 0)
        self.assertEqual(len(result["unperformed_registered_controls"]), 3)

    def test_raw_whitespace_mutation_rejected_by_prior_receipt_hash(self):
        anchor = Path(self.temporary.name) / "prior-review.json"
        anchor.write_text(json.dumps(self.audit()), encoding="utf-8")
        path = self.directory / "01_off_dense/preimport-ready.json"
        path.write_bytes(path.read_bytes() + b"\n")
        result = self.audit(anchor)
        self.assertFalse(result["checks"]["anchored_raw_byte_hashes"])
        self.assertFalse(result["passed"])
        self.assertIsNone(result["execution_acceptance"])

    def test_changed_raw_budget_cannot_explain_original_failure(self):
        path = self.directory / "01_off_dense/preimport-ready.json"
        pre = json.loads(path.read_bytes())
        pre["provider_guard"]["allowed_local_probe_budget"] = 0
        path.write_text(json.dumps(pre), encoding="utf-8")
        result = self.audit()
        self.assertFalse(result["checks"]["single_observed_provider_contract_mismatch"])
        self.assertIsNone(result["execution_acceptance"])

    def test_cleanup_identity_corruption_rejected_after_outer_hashes_updated(self):
        self.rewrite_case(lambda case: case["failure_cleanup"]["exit_codes"][0].update(
            creation_filetime=case["failure_cleanup"]["exit_codes"][0]["creation_filetime"] + 1))
        result = self.audit()
        self.assertTrue(result["checks"]["suite_payload_hash"])
        self.assertTrue(result["checks"]["separate_case_custody"])
        self.assertFalse(result["checks"]["failure_cleanup_exact_retained_identities"])
        self.assertIsNone(result["execution_acceptance"])

    def test_normal_exit_cannot_replace_saved_forced_termination(self):
        self.rewrite_case(lambda case: case["failure_cleanup"]["exit_codes"][0].update(exit_code=0))
        result = self.audit()
        self.assertFalse(result["checks"]["failure_cleanup_forced_codes"])
        self.assertFalse(result["passed"])

    def test_raw_clock_and_extra_case_are_rejected(self):
        path = self.directory / "01_off_dense/preimport-ready.json"
        pre = json.loads(path.read_bytes())
        pre["stage_ready_perf_counter"] += 1000
        path.write_text(json.dumps(pre), encoding="utf-8")
        (self.directory / "02_off_int8").mkdir()
        result = self.audit()
        self.assertFalse(result["checks"]["preimport_clock_predicates_by_recorded_bounds"])
        self.assertFalse(result["checks"]["only_first_workload_directory"])
        self.assertFalse(result["diagnosis"]["other_visible_outer_gate_predicates_pass"])


if __name__ == "__main__":
    unittest.main()
