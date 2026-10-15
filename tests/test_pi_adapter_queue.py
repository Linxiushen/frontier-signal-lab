"""Execute the actual pinned adapter once; inspect SQL truth and guard controls."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "pi_adapter_queue_probe.mjs"
SOURCE = ROOT / "third_party" / "pi" / "cloudflare.ts"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PiAdapterQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise RuntimeError("Node.js 24.19+ is required for the pinned TypeScript adapter probe")
        cls.temp = tempfile.TemporaryDirectory(prefix="pi-adapter-queue-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(cls.temp.name) / "output"
        before = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
        completed = subprocess.run([cls.node, str(SCRIPT), "--output", str(cls.output)],
                                   cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=25)
        if completed.returncode:
            raise AssertionError(f"Adapter subprocess failed: {completed.stdout}\n{completed.stderr}")
        cls.report = json.loads((cls.output / "probe.json").read_text(encoding="utf-8"))
        cls.runs = {row["scenario"]: row for row in cls.report["runs"]}
        cls.source_before = before
        cls.source_after = hashlib.sha256(SOURCE.read_bytes()).hexdigest()

    def test_exact_rows_are_business_progress_not_only_safety_flags(self):
        expected = {
            "queued_write_commit": [{"id": "inside", "value": 1}, {"id": "queued", "value": 2}],
            "queued_write_abort": [{"id": "queued", "value": 2}],
            "direct_write_abort_control": [],
            "transaction_after_abort": [{"id": "after_abort", "value": 4}],
            "retained_handle_after_commit": [{"id": "kept", "value": 5}],
            "retained_handle_after_abort": [],
        }
        self.assertEqual(set(self.runs), set(expected))
        for name, rows in expected.items():
            with self.subTest(scenario=name):
                self.assertEqual(self.runs[name]["actual_rows"], rows)
                self.assertEqual(self.runs[name]["expected_rows"], rows)

    def test_other_adapter_write_waits_then_completes_after_commit(self):
        row = self.runs["queued_write_commit"]
        self.assertFalse(row["queued_settled_before_release"])
        self.assertEqual(row["rows_before_release"], [{"id": "inside", "value": 1}])
        self.assertEqual(row["queued_outcome"]["status"], "fulfilled")
        events = row["events"]
        self.assertLess(events.index("queued.submitted"), events.index("release.requested"))
        self.assertLess(events.index("release.requested"), events.index("storage.commit"))
        self.assertLess(events.index("storage.commit"), events.index("queued.fulfilled"))

    def test_queued_write_survives_transaction_abort(self):
        row = self.runs["queued_write_abort"]
        self.assertFalse(row["queued_settled_before_release"])
        self.assertEqual(row["rows_before_release"], [{"id": "inside", "value": 1}])
        self.assertEqual(row["transaction_outcome"]["status"], "rejected")
        self.assertEqual(row["queued_outcome"]["status"], "fulfilled")
        self.assertLess(row["events"].index("storage.rollback"), row["events"].index("queued.fulfilled"))

    def test_direct_write_negative_control_is_not_hidden_as_success(self):
        row = self.runs["direct_write_abort_control"]
        self.assertTrue(row["direct_write_completed_before_abort"])
        self.assertTrue(row["completed_direct_write_missing_after_abort"])
        self.assertEqual(row["rows_before_release"],
                         [{"id": "direct", "value": 3}, {"id": "inside", "value": 1}])
        self.assertIn("Negative control", row["control_role"])

    def test_abort_does_not_poison_shared_queue(self):
        row = self.runs["transaction_after_abort"]
        self.assertEqual(row["first_outcome"]["status"], "rejected")
        self.assertEqual(row["next_outcome"]["status"], "fulfilled")
        self.assertLess(row["events"].index("first_transaction.rejected"),
                        row["events"].index("next_transaction.fulfilled"))

    def test_retained_handles_reject_after_both_settlements(self):
        for name in ("retained_handle_after_commit", "retained_handle_after_abort"):
            with self.subTest(scenario=name):
                result = self.runs[name]["retained_handle_outcome"]
                self.assertEqual(result["status"], "rejected")
                self.assertEqual(result["error"], "SQLite transaction handle is no longer active")

    def test_source_license_and_result_hashes_are_verifiable(self):
        provenance = json.loads((SOURCE.parent / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(self.source_before, self.source_after)
        self.assertEqual(self.source_after, provenance["source_sha256"])
        self.assertEqual(self.report["config"]["source_sha256"], self.source_after)
        self.assertEqual(self.report["config"]["license_sha256"],
                         hashlib.sha256((SOURCE.parent / "LICENSE").read_bytes()).hexdigest())
        report = dict(self.report)
        expected = report.pop("result_sha256")
        self.assertEqual(hashlib.sha256(canonical(report).encode("utf-8")).hexdigest(), expected)

    def test_normal_run_does_not_touch_substituted_factory(self):
        substitution = self.report["dependency_substitution"]
        self.assertEqual(substitution["factory_open_attempts"], 0)
        self.assertTrue(substitution["unused_factory_confirmed"])
        self.assertIn("registerHooks", substitution["implementation"])

    def test_sentinel_is_fail_closed_when_factory_is_actually_accessed(self):
        completed = subprocess.run([self.node, str(SCRIPT), "--self-test-sentinel"],
                                   cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"sentinel_rejected": True, "attempts": 1})

    def test_real_deadline_rejects_unresolved_promise(self):
        completed = subprocess.run([self.node, str(SCRIPT), "--self-test-timeout"],
                                   cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"timeout_detected": True, "error": "DeadlineError"})
        self.assertTrue(all(row["deadline_ms"] == 2000 for row in self.report["runs"]))
        self.assertEqual(self.report["config"]["overall_deadline_ms"], 20000)

    def test_report_and_output_files_state_scope_and_negative_result(self):
        self.assertEqual(sorted(path.name for path in self.output.iterdir()), ["probe.json", "report.md"])
        report = (self.output / "report.md").read_text(encoding="utf-8")
        self.assertIn("negative control", report)
        self.assertIn("not the full pi/Pico", report)
        self.assertIn("not an operating-system network sandbox", report)
        self.assertTrue(self.report["all_passed"])


if __name__ == "__main__":
    unittest.main()
