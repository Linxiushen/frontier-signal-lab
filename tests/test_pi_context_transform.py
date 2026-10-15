"""Run complete pinned pi modules and verify their replay boundary and authentic parent control."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments" / "pi_context_transform_probe.mjs"
VENDOR = ROOT / "third_party" / "pi-context"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class PiContextTransformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")
        if cls.node is None:
            raise RuntimeError("Node.js with native TypeScript support is required")
        cls.temp = tempfile.TemporaryDirectory(prefix="pi-context-transform-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.output = Path(cls.temp.name) / "output"
        cls.before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in VENDOR.glob("*.ts")}
        completed = subprocess.run([cls.node, str(SCRIPT), "--output", str(cls.output)],
                                   cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
        if completed.returncode:
            raise AssertionError(f"Context-transform subprocess failed: {completed.stdout}\n{completed.stderr}")
        cls.report = json.loads((cls.output / "probe.json").read_text(encoding="utf-8"))
        cls.runs = {row["scenario"]: row for row in cls.report["runs"]}

    def test_all_eight_traces_run_both_actual_modules(self):
        self.assertEqual(set(self.runs), {
            "same_identity_opaque_reasoning", "model_identity_change_tools",
            "provider_identity_change", "api_identity_change", "alternating_models_a_b_a",
            "error_and_aborted_turns", "complete_tools_with_system_message", "unsigned_blank_thinking",
        })
        self.assertEqual(self.report["summary"], {
            "traces": 8, "module_executions": 16, "parent_negative_control_traces": 4,
            "parent_desired_boundary_failures": 4, "merged_desired_boundary_failures": 0,
        })
        self.assertTrue(self.report["all_passed"])
        for row in self.runs.values():
            for version in ("parent", "merged"):
                with self.subTest(scenario=row["scenario"], version=version):
                    observation = row[version]
                    self.assertEqual(observation["output"], observation["expected_output"])
                    self.assertTrue(observation["exact_output_matches"])

    def test_same_identity_keeps_empty_opaque_reasoning(self):
        row = self.runs["same_identity_opaque_reasoning"]
        expected = [
            {"type": "thinking", "thinking": "SAME_READABLE"},
            {"type": "thinking", "thinking": "", "thinkingSignature": "opaque-fixture-signed-empty"},
            {"type": "thinking", "thinking": "", "redacted": True},
            {"type": "text", "text": "visible answer", "textSignature": "opaque-fixture-text"},
        ]
        for version in ("parent", "merged"):
            self.assertEqual(row[version]["output"][1]["content"], expected)

    def test_each_identity_field_has_authentic_parent_negative_control(self):
        for name, marker in (("model_identity_change_tools", "FOREIGN_MODEL_REASONING"),
                             ("provider_identity_change", "FOREIGN_PROVIDER_REASONING"),
                             ("api_identity_change", "FOREIGN_API_REASONING"),
                             ("alternating_models_a_b_a", "FOREIGN_B_MIDDLE")):
            row = self.runs[name]
            with self.subTest(scenario=name):
                self.assertTrue(row["parent_expected_negative_control"])
                self.assertEqual(row["parent"]["visible_foreign_reasoning"], [marker])
                self.assertFalse(row["parent"]["desired_foreign_reasoning_boundary"])
                self.assertEqual(row["merged"]["visible_foreign_reasoning"], [])
                self.assertTrue(row["merged"]["desired_foreign_reasoning_boundary"])
                self.assertTrue(row["parent_control_matches_expectation"])
                self.assertTrue(row["passed"])

    def test_model_change_preserves_text_arguments_ids_and_results(self):
        row = self.runs["model_identity_change_tools"]
        source_call = row["input"][1]["content"][-1]
        for version in ("parent", "merged"):
            output = row[version]["output"]
            call = next(block for block in output[1]["content"] if block["type"] == "toolCall")
            self.assertEqual(call["id"], "call|foreign:1")
            self.assertEqual(call["arguments"], source_call["arguments"])
            self.assertNotIn("thoughtSignature", call)
            self.assertEqual(output[2], row["input"][2])
            self.assertEqual(output[2]["toolCallId"], call["id"])
            visible = next(block for block in output[1]["content"] if block.get("text") == "performing lookup")
            self.assertEqual(visible, {"type": "text", "text": "performing lookup"})
            self.assertFalse(any(block["type"] == "thinking" for block in output[1]["content"]))

    def test_alternating_identity_retains_only_target_reasoning(self):
        output = self.runs["alternating_models_a_b_a"]["merged"]["output"]
        self.assertEqual(output[1]["content"][0], {"type": "thinking", "thinking": "SAME_A_FIRST"})
        self.assertEqual(output[3]["content"], [{"type": "text", "text": "B middle"}])
        self.assertEqual(output[5]["content"][0]["thinkingSignature"], "opaque-A-return")

    def test_incomplete_turns_are_omitted_without_fabricated_tool_results(self):
        for version in ("parent", "merged"):
            output = self.runs["error_and_aborted_turns"][version]["output"]
            self.assertEqual([row["role"] for row in output], ["user", "user", "user", "assistant"])
            self.assertEqual([row["content"] for row in output[:3]],
                             ["retryable request", "retry after error", "retry after abort"])
            self.assertEqual(output[-1]["content"], [{"type": "text", "text": "completed answer"}])
            self.assertFalse(any(row["role"] == "toolResult" for row in output))

    def test_complete_tools_hold_system_message_and_do_not_duplicate_results(self):
        row = self.runs["complete_tools_with_system_message"]
        for version in ("parent", "merged"):
            output = row[version]["output"]
            self.assertEqual([message["role"] for message in output],
                             ["user", "assistant", "toolResult", "toolResult", "system", "user"])
            self.assertEqual(output[1], row["input"][1])
            self.assertEqual(output[2:4], row["input"][3:5])
            self.assertEqual(output[4], row["input"][2])
            self.assertEqual([message["toolCallId"] for message in output if message["role"] == "toolResult"],
                             ["literal|call:2", "literal|call:1"])
            self.assertNotIn("No result provided", canonical(output))

    def test_blank_unsigned_thinking_is_dropped(self):
        for version in ("parent", "merged"):
            content = self.runs["unsigned_blank_thinking"][version]["output"][1]["content"]
            self.assertEqual(content, [{"type": "text", "text": "ordinary answer"}])

    def test_input_model_sources_and_hashes_are_unchanged(self):
        provenance = json.loads((VENDOR / "provenance.json").read_text(encoding="utf-8"))
        for version in ("parent", "merged"):
            spec = provenance["sources"][version]
            actual = hashlib.sha256((VENDOR / spec["file"]).read_bytes()).hexdigest()
            self.assertEqual(self.before[spec["file"]], actual)
            self.assertEqual(spec["source_sha256"], actual)
            self.assertEqual(self.report["config"]["sources"][version]["source_sha256"], actual)
            self.assertTrue(self.report["source_files_unchanged"][version])
            for row in self.runs.values():
                self.assertTrue(row[version]["input_and_model_unchanged"])
                self.assertEqual(row[version]["input_and_model_sha256_before"],
                                 row[version]["input_and_model_sha256_after"])
                self.assertEqual(row[version]["output_sha256"],
                                 hashlib.sha256(canonical(row[version]["output"]).encode()).hexdigest())
        self.assertEqual(self.report["config"]["probe_sha256"], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
        self.assertEqual(self.report["config"]["provenance_sha256"],
                         hashlib.sha256((VENDOR / "provenance.json").read_bytes()).hexdigest())
        self.assertEqual(self.report["config"]["license_sha256"],
                         hashlib.sha256((VENDOR / "LICENSE").read_bytes()).hexdigest())
        copy = dict(self.report)
        result_hash = copy.pop("result_sha256")
        self.assertEqual(hashlib.sha256(canonical(copy).encode()).hexdigest(), result_hash)

    def test_repeated_subprocess_is_deterministic(self):
        output = Path(self.temp.name) / "repeat"
        repeated = subprocess.run([self.node, str(SCRIPT), "--output", str(output)],
                                  cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        for name in ("probe.json", "report.md"):
            self.assertEqual((self.output / name).read_bytes(), (output / name).read_bytes())

    def isolated_probe(self, directory):
        copy_root = Path(directory)
        (copy_root / "experiments").mkdir()
        shutil.copy2(SCRIPT, copy_root / "experiments" / SCRIPT.name)
        shutil.copytree(VENDOR, copy_root / "third_party" / "pi-context")
        return copy_root, copy_root / "experiments" / SCRIPT.name

    def test_changed_source_fails_hash_guard_in_real_subprocess(self):
        with tempfile.TemporaryDirectory(prefix="pi-context-tamper-") as directory:
            copy_root, script = self.isolated_probe(directory)
            source = copy_root / "third_party" / "pi-context" / "merged-transform-messages.ts"
            source.write_bytes(source.read_bytes() + b"\n// intentional isolated tamper\n")
            output = copy_root / "output"
            result = subprocess.run([self.node, str(script), "--output", str(output)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Pinned merged source SHA256 mismatch", result.stderr)
            self.assertFalse(output.exists())

    def test_actual_parent_regression_causes_real_subprocess_failure(self):
        with tempfile.TemporaryDirectory(prefix="pi-context-regression-") as directory:
            copy_root, script = self.isolated_probe(directory)
            vendor = copy_root / "third_party" / "pi-context"
            old = (vendor / "parent-transform-messages.ts").read_bytes()
            (vendor / "merged-transform-messages.ts").write_bytes(old)
            provenance_path = vendor / "provenance.json"
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["sources"]["merged"]["source_sha256"] = hashlib.sha256(old).hexdigest()
            provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8", newline="\n")
            output = copy_root / "output"
            result = subprocess.run([self.node, str(script), "--output", str(output)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads((output / "probe.json").read_text(encoding="utf-8"))
            self.assertFalse(report["all_passed"])
            self.assertEqual(report["summary"]["merged_desired_boundary_failures"], 4)
            self.assertEqual(sum(not row["merged"]["exact_output_matches"] for row in report["runs"]), 4)

    def test_scope_is_explicit_and_no_dependency_substitution_is_used(self):
        config = self.report["config"]
        self.assertFalse(config["runtime_dependency_substitution"])
        self.assertFalse(config["module_hooks"])
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), ["probe.json", "report.md"])
        report = (self.output / "report.md").read_text(encoding="utf-8")
        self.assertIn("expected negative control", report)
        self.assertIn("synthetic sentinels", report)
        self.assertIn("No provider requests", report)


if __name__ == "__main__":
    unittest.main()
