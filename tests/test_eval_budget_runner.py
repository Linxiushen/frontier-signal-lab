import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from experiments.eval_budget_runner import BudgetLedger, digest, verify_files
from experiments.prepare_verifiers_budget import prepare


class EvaluationBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "budget.sqlite"
        self.ledger = BudgetLedger(self.path, "frozen-v1", 3)

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def test_restart_burns_uncertain_attempt_without_refund(self):
        self.assertTrue(self.ledger.reserve("a", "development", "bad", "dev"))
        self.ledger.close()
        self.ledger = BudgetLedger(self.path, "frozen-v1", 3)
        self.assertEqual(self.ledger.recover(), 1)
        self.assertFalse(self.ledger.reserve("a", "development", "bad", "dev"))
        self.assertEqual(self.ledger.snapshot()["attempts"][0]["status"], "burned")

    def test_completion_persists_and_cannot_be_overwritten(self):
        self.ledger.reserve("a", "development", "good", "dev")
        self.ledger.complete("a", 1.0, {"trace_sha256": "x", "denominator": 1})
        self.ledger.close()
        self.ledger = BudgetLedger(self.path, "frozen-v1", 3)
        self.assertEqual(self.ledger.recover(), 0)
        with self.assertRaises(ValueError):
            self.ledger.complete("a", 0.0, {})
        self.assertEqual(self.ledger.snapshot()["attempts"][0]["reward"], 1)

    def test_sealed_selection_and_single_final_budget(self):
        with self.assertRaises(ValueError):
            self.ledger.reserve("final", "final", "good", "sealed")
        for key, model, score in [("a", "bad", 0), ("b", "good", 1)]:
            self.ledger.reserve(key, "development", model, "dev")
            self.ledger.complete(key, score, {})
        self.assertEqual(self.ledger.seal_winner(), "good")
        with self.assertRaises(ValueError):
            self.ledger.reserve("c", "development", "extra", "dev")
        with self.assertRaises(ValueError):
            self.ledger.reserve("wrong", "final", "bad", "sealed")
        self.assertTrue(self.ledger.reserve("final", "final", "good", "sealed"))
        self.ledger.complete("final", 1.0, {})
        self.assertFalse(self.ledger.reserve("final", "final", "good", "sealed"))
        with self.assertRaises(ValueError):
            self.ledger.reserve("again", "final", "good", "sealed")

    def test_identity_and_nonfinite_result_refused(self):
        self.ledger.reserve("a", "development", "good", "dev")
        with self.assertRaises(ValueError):
            self.ledger.reserve("a", "development", "other", "dev")
        with self.assertRaises(ValueError):
            self.ledger.complete("a", float("nan"), {})
        for identity, limit in [("changed", 3), ("frozen-v1", 4)]:
            with self.assertRaises(ValueError):
                BudgetLedger(self.path, identity, limit)

    def test_evaluator_bytes_tamper_refused(self):
        evaluator = Path(self.temp.name) / "evaluator.py"
        evaluator.write_bytes(b"denominator = 1\n")
        versions = {str(evaluator): digest(evaluator.read_bytes())}
        verify_files(versions)
        evaluator.write_bytes(b"denominator = 2\n")
        with self.assertRaises(ValueError):
            verify_files(versions)
        self.assertEqual(self.ledger.snapshot()["attempts"], [])

    def test_concurrent_reservations_share_fixed_budget(self):
        def reserve(i):
            ledger = BudgetLedger(self.path, "frozen-v1", 3)
            try:
                return ledger.reserve(str(i), "development", "good", "dev")
            except ValueError:
                return False
            finally:
                ledger.close()
        with ThreadPoolExecutor(max_workers=8) as pool:
            admitted = list(pool.map(reserve, range(8)))
        self.assertEqual(sum(admitted), 3)
        self.assertEqual(len(self.ledger.snapshot()["attempts"]), 3)

    def test_missing_harness_lock_cannot_create_freeze(self):
        root = Path(self.temp.name)
        with self.assertRaises(FileNotFoundError):
            prepare(root, root / "missing-harness.lock", root / "missing-package.lock", root / "freeze")
        self.assertFalse((root / "freeze").exists())


if __name__ == "__main__":
    unittest.main()
