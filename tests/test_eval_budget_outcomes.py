"""Failure-denominator and recovery controls; no upstream/native execution."""
import http.client
import tempfile
import threading
import unittest
from pathlib import Path

from experiments.eval_budget_outcomes import OutcomeBudgetLedger
from experiments.eval_budget_runner import canonical, digest
from experiments.eval_http_budget import HttpBudget
from experiments.verifiers_budget_exhaustion import ExhaustionServer


class OutcomeBudgetTests(unittest.TestCase):
    def test_invalid_or_unowned_failure_does_not_mutate_reservation(self):
        with tempfile.TemporaryDirectory() as folder:
            db = OutcomeBudgetLedger(Path(folder) / "logical.sqlite", "id", 1)
            try:
                db.reserve("owned", "development", "m", "d")
                before = db.snapshot()
                for sha in [None, 1, "", "a" * 63, "g" * 64]:
                    with self.assertRaises(ValueError):
                        db.fail("owned", {"outcome": "native_failure", "episode_sha256": sha})
                    self.assertEqual(db.snapshot(), before)
                with self.assertRaises(ValueError):
                    db.fail("unknown", {"outcome": "native_failure", "episode_sha256": "a" * 64})
                self.assertEqual(db.snapshot(), before)
            finally:
                db.close()

    def test_failed_higher_candidate_cannot_replace_completed_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            db = OutcomeBudgetLedger(Path(folder) / "logical.sqlite", "id", 2)
            try:
                db.reserve("ok", "development", "low", "data")
                db.complete("ok", 0, {"denominator": 1})
                db.reserve("failure", "development", "high", "data")
                receipt = {"outcome": "native_failure", "episode_sha256": "a" * 64, "observed_rewards": {"echoed": 1}}
                db.fail("failure", receipt)
                self.assertEqual(db.seal_winner(), "low")
                row = db.snapshot()["attempts"][1]
                self.assertEqual((row["status"], row["reward"], row["receipt"]), ("failed", None, canonical(receipt)))
                self.assertFalse(db.reserve("failure", "development", "high", "data"))
                with self.assertRaises(ValueError):
                    db.reserve("replacement", "development", "high", "data")
            finally:
                db.close()

    def test_reopen_keeps_exact_failure_and_burns_only_uncertain(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "logical.sqlite"
            receipt = {"outcome": "native_failure", "episode_sha256": "b" * 64}
            db = OutcomeBudgetLedger(path, "id", 3)
            db.reserve("failed", "development", "m", "d")
            db.fail("failed", receipt)
            db.reserve("uncertain", "development", "m", "d")
            db.close()
            db = OutcomeBudgetLedger(path, "id", 3)
            try:
                self.assertEqual(db.recover(), 1)
                before = db.snapshot()
                db.fail("failed", receipt)
                self.assertEqual(db.snapshot(), before)
                with self.assertRaises(ValueError):
                    db.fail("failed", {**receipt, "episode_sha256": "c" * 64})
                with self.assertRaises(ValueError):
                    db.complete("failed", 1, {})
                with self.assertRaises(ValueError):
                    db.seal_winner()
                self.assertEqual(db.snapshot(), before)
            finally:
                db.close()

    def test_failed_final_still_spends_the_only_final_allowance(self):
        with tempfile.TemporaryDirectory() as folder:
            db = OutcomeBudgetLedger(Path(folder) / "logical.sqlite", "id", 1)
            try:
                db.reserve("dev", "development", "m", "d")
                db.complete("dev", 0, {})
                db.seal_winner()
                db.reserve("final", "final", "m", "f")
                db.fail("final", {"outcome": "native_failure", "episode_sha256": "d" * 64})
                self.assertFalse(db.reserve("final", "final", "m", "f"))
                with self.assertRaises(ValueError):
                    db.reserve("second", "final", "m", "f")
                self.assertIsNone(db.snapshot()["attempts"][-1]["reward"])
            finally:
                db.close()

    def test_denied_retry_spends_ordinal_and_cannot_renew_on_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "http.sqlite"
            first = HttpBudget(path, "id", 3, 1)
            self.assertTrue(first.receive("ok", "x")["admitted"])
            self.assertTrue(first.receive("retry", "y")["admitted"])
            self.assertEqual(first.receive("retry", "y")["reason"], "attempt_exhausted")
            second = HttpBudget(path, "id", 3, 1)
            self.assertEqual(second.receive("new", "z")["reason"], "total_exhausted")
            self.assertEqual(sum(r["admitted"] for r in second.snapshot()["arrivals"]), 2)

    def test_actual_http_boundary_binds_retry_and_both_exhaustion_reasons(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            h = digest((canonical(["cobalt river"]) + "\n").encode())
            logical = OutcomeBudgetLedger(output / "budget.sqlite", "control", 3)
            records = []
            protocol = {"datasets": {"development": {"sha256": h}, "final": {"sha256": h}}}
            for key in ["dev-ok", "dev-attempt-cap", "dev-total-cap"]:
                logical.reserve(key, "development", "fixture-bad", h)
            def send(key):
                server = ExhaustionServer(output, protocol, None, records)
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                body = canonical({"model": "fixture-bad", "messages": [{"role": "user", "content":
                    "Answer directly without using tools or running code. Your reply must contain this exact phrase: cobalt river"}]}).encode()
                try:
                    client.request("POST", "/v1/chat/completions", body,
                        {"X-Frontier-Attempt": key, "X-Frontier-Data-SHA256": h})
                    response = client.getresponse()
                    status = response.status
                    response.read()
                    return status
                finally:
                    client.close(); server.shutdown(); server.server_close(); thread.join(timeout=5)
            try:
                self.assertEqual([send(k) for k in ["dev-ok", "dev-attempt-cap", "dev-attempt-cap", "dev-total-cap"]],
                                 [200, 503, 403, 403])
                self.assertEqual([r["slot"]["reason"] for r in records],
                                 ["admitted", "admitted", "attempt_exhausted", "total_exhausted"])
                self.assertEqual(records[1]["request_sha256"], records[2]["request_sha256"])
                self.assertTrue(all(r["status"] == "delivered" and r["write_completed"] for r in records))
                self.assertEqual([r["status"] for r in logical.snapshot()["attempts"]], ["reserved"] * 3)
            finally:
                logical.close()


if __name__ == "__main__":
    unittest.main()
