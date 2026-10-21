"""Saved negative evidence controls; no native observer/producer imports."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.check_observed_job_failure import check

ROOT = Path(__file__).resolve().parents[1]


class ObservedJobFailureTests(unittest.TestCase):
    def verify(self, output):
        return check(output, ROOT / "fixtures/observed-job/protocol.json",
                     ROOT / "fixtures/observed-job/implementation.json", ROOT)

    def test_saved_negative_is_preserved_without_becoming_acceptance(self):
        result = self.verify(ROOT / "results/observed-job/raw")
        self.assertTrue(result["preservation_passed"])
        self.assertFalse(result["native_acceptance"])
        self.assertEqual(result["recorded_samples"], 0)

    def test_rejects_acceptance_topology_cleanup_and_progress_mutations(self):
        mutations = [
            lambda r: r.update(passed=True),
            lambda r: r["cases"][0]["native_identity"].update(job_active_count=1),
            lambda r: r["cases"][0]["shutdown"]["native_cleanup"].update(job_active_count=1),
            lambda r: r["cases"][0].update(sampler_native_thread_ids=[1, 2, 3, 4]),
            lambda r: r["cases"][0]["native_identity"].update(creation_filetime=1),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "raw"
                shutil.copytree(ROOT / "results/observed-job/raw", output)
                report = json.loads((output / "report.json").read_bytes())
                mutate(report)
                (output / "report.json").write_text(json.dumps(report), encoding="utf8")
                # Mirror mutation too, so report/case equality cannot hide a
                # missing semantic check for the failed result.
                (output / "threaded_samples/result.json").write_text(json.dumps(report["cases"][0]), encoding="utf8")
                with self.assertRaises(ValueError):
                    self.verify(output)

    def test_rejects_trace_tampering_and_fabricated_unrun_case(self):
        for target in ["trace", "unrun"]:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "raw"
                shutil.copytree(ROOT / "results/observed-job/raw", output)
                if target == "trace":
                    with (output / "threaded_samples/trace.jsonl").open("ab") as stream:
                        stream.write(b"{}\n")
                else:
                    (output / "row_cap").mkdir()
                with self.assertRaises(ValueError):
                    self.verify(output)


if __name__ == "__main__":
    unittest.main()
