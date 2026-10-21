"""Post-outcome archived-directory regressions, not v2 prefreeze controls."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import check_training_ledger_v2_preservation as p

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/training-ledger-v2/raw"
PROTOCOL = ROOT / "fixtures/training-ledger-v2/protocol.json"
FREEZE = ROOT / "fixtures/training-ledger-v2/implementation.json"


class SavedCallerDirectory(unittest.TestCase):
    def test_original_rejection_and_separate_full_preservation(self):
        result = p.review(OUT, PROTOCOL, FREEZE)
        self.assertFalse(result["frozen_saved_byte_acceptance"])
        self.assertTrue(result["post_outcome_preservation"])
        self.assertEqual(result["frozen_rejections"], [{"check": p.REJECTION, "passed": False}])
        self.assertEqual((result["model_loads"], result["optimizer_updates"]), (2, 16))

    def test_missing_and_unknown_files_reject_both_actual_case_directories(self):
        cases = json.loads((OUT / "report.json").read_bytes())["cases"]
        for case in cases:
            for fault in ("missing-progress", "missing-original", "unknown", "pending"):
                with self.subTest(case=case["id"], fault=fault), tempfile.TemporaryDirectory() as tmp:
                    target = Path(tmp) / case["id"]
                    shutil.copytree(OUT / case["id"], target)
                    if fault == "missing-progress":
                        (target / "import-progress-06.json").unlink()
                    elif fault == "missing-original":
                        (target / "worker-ready.json").unlink()
                    else:
                        (target / ("unexpected.json" if fault == "unknown" else "orphan.pending")).write_text("{}")
                    with self.assertRaises((AssertionError, FileNotFoundError)):
                        p.payload_sets(case, target)

    def test_progress_provider_nonce_and_identity_are_still_replayed(self):
        case = json.loads((OUT / "report.json").read_bytes())["cases"][0]
        freeze = json.loads(FREEZE.read_bytes())
        for field in ("nonce", "pid", "creation_filetime"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "healthy"
                shutil.copytree(OUT / "healthy", target)
                path = target / "import-progress-00.json"
                row = json.loads(path.read_bytes())
                row[field] = "wrong" if field == "nonce" else row[field] + 1
                path.write_text(json.dumps(row), encoding="utf8")
                # Inventory passes; independent progress custody must still fail.
                p.payload_sets(case, target)
                with self.assertRaises(AssertionError):
                    p.frozen.audit_progress(case, target, freeze)


if __name__ == "__main__":
    unittest.main()
