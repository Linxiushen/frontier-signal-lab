"""Integrity and portable-viewer boundaries; no ML dependencies required."""
from pathlib import Path
import tempfile
import unittest

from savescope.report import SCHEMA, load_report, recorded_case, render, seal, validate, write_report


class PortableReportTests(unittest.TestCase):
    def fixture(self):
        return seal({"schema": SCHEMA, "mode": "executed_audit", "limitations": [],
            "runs": [{"label": "sample", "arms": [{"id": "dense", "label": "Exact",
                "gradient": {"relative_l2": 0.0, "cosine_similarity": 1.0,
                    "per_parameter": [{"name": "</script><script>alert(1)</script>", "elements": 4}]}}]}]})

    def test_modified_observation_rejected(self):
        report = self.fixture()
        report["runs"][0]["arms"][0]["gradient"]["relative_l2"] = 9
        with self.assertRaisesRegex(ValueError, "SHA256"):
            validate(report)

    def test_nonfinite_rejected_even_when_resealed(self):
        report = self.fixture()
        report["runs"][0]["arms"][0]["gradient"]["relative_l2"] = float("nan")
        with self.assertRaises(ValueError):
            seal(report)

    def test_script_termination_is_escaped(self):
        html = render(self.fixture())
        self.assertNotIn("</script><script>alert(1)</script>", html)
        self.assertIn("\\u003c/script", html)
        # No report-supplied strings are inserted using innerHTML.
        self.assertNotIn("innerHTML", html)

    def test_round_trip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "one-run"
            html = write_report(self.fixture(), output)
            self.assertTrue(html.is_file())
            original = (output / "report.json").read_bytes()
            self.assertEqual(load_report(output / "report.json"), self.fixture())
            with self.assertRaises(FileExistsError):
                write_report(self.fixture(), output)
            self.assertEqual((output / "report.json").read_bytes(), original)

    def test_bundled_evidence_is_explicit_replay(self):
        report = recorded_case()
        self.assertEqual(report["mode"], "recorded_replay")
        self.assertEqual(len(report["runs"]), 3)
        self.assertEqual([len(r["arms"]) for r in report["runs"]], [3, 3, 3])
        self.assertTrue(report["source_files"])

    def test_json_schema_type_errors_fail_cleanly(self):
        report = self.fixture()
        report["runs"][0]["arms"][0]["gradient"]["relative_l2"] = "0.01"
        with self.assertRaises(ValueError):
            validate(seal(report))

    def test_malformed_nested_values_rejected_at_import(self):
        for bad in (None, [], "run"):
            report = self.fixture()
            report["runs"] = [bad]
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate(seal(report))
        for field, bad in (("arms", [None]), ("arms", [])):
            report = self.fixture()
            report["runs"][0][field] = bad
            with self.assertRaises(ValueError):
                validate(seal(report))
        for bad in ([], {"relative_l2": True}, {"per_parameter": [{"name": "p", "elements": "ten"}]}):
            report = self.fixture()
            report["runs"][0]["arms"][0]["gradient"] = bad
            with self.assertRaises(ValueError):
                validate(seal(report))
        report = self.fixture()
        report["sources"] = None
        with self.assertRaises(ValueError):
            validate(seal(report))
        report = self.fixture()
        report["runs"][0]["exact_scopes"] = "not an array"
        with self.assertRaises(ValueError):
            validate(seal(report))

    def test_invalid_audit_is_not_presented_as_perfect_agreement(self):
        from savescope.demo import as_report
        data = as_report({"arms": [{"policy": "dense", "loss": None,
            "numerically_valid": False, "gradient": {"finite": True},
            "update": {"executed": False}}], "comparisons": [], "limitations": []})
        arm = data["runs"][0]["arms"][0]
        self.assertIsNone(arm["gradient"]["relative_l2"])
        self.assertIsNone(arm["gradient"]["cosine_similarity"])
        self.assertIsNone(arm["update"])
        self.assertIn("INVALID", data["runs"][0]["gradient_gate"])


if __name__ == "__main__":
    unittest.main()
