"""Physical admission controls. No native runner, model or scientific execution."""
import concurrent.futures
import http.client
import tempfile
import threading
import unittest
from pathlib import Path

from experiments.eval_budget_runner import BudgetLedger, canonical, digest
from experiments.eval_http_budget import HttpBudget
from experiments.verifiers_budget_retry_suite import RetryServer


class HttpBudgetTests(unittest.TestCase):
    def test_reopen_preserves_failed_spend_and_rejects_changed_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "http.sqlite"
            first = HttpBudget(path, "same", 2, 2)
            self.assertTrue(first.receive("turn", "bytes")["admitted"])
            first.response(1, 503, False)
            second = HttpBudget(path, "same", 2, 2)
            self.assertTrue(second.receive("turn", "bytes")["admitted"])
            self.assertEqual(second.receive("other", "bytes")["reason"], "total_exhausted")
            self.assertEqual(second.snapshot()["arrivals"][0]["response_status"], 503)
            self.assertEqual(second.snapshot()["arrivals"][0]["write_completed"], 0)
            before = path.read_bytes()
            for identity, total, per in [("changed", 2, 2), ("same", 3, 2), ("same", 2, 3)]:
                with self.assertRaises(ValueError):
                    HttpBudget(path, identity, total, per)
                self.assertEqual(path.read_bytes(), before)

    def test_changed_wire_content_and_per_attempt_limit_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            budget = HttpBudget(Path(directory) / "http.sqlite", "same", 6, 2)
            self.assertTrue(budget.receive("turn", "original")["admitted"])
            self.assertEqual(budget.receive("turn", "changed")["reason"], "content_conflict")
            self.assertEqual(budget.receive("turn", "original")["reason"], "attempt_exhausted")
            self.assertTrue(budget.receive("different", "different")["admitted"])

    def test_concurrent_callers_cannot_over_admit(self):
        with tempfile.TemporaryDirectory() as directory:
            budget = HttpBudget(Path(directory) / "http.sqlite", "concurrent", 6, 2)
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                rows = list(pool.map(lambda n: budget.receive("turn-" + str(n), "body"), range(12)))
            self.assertEqual(sorted(row["seq"] for row in rows), list(range(1, 13)))
            self.assertEqual(sum(row["admitted"] for row in rows), 6)
            self.assertEqual(len(budget.snapshot()["arrivals"]), 12)

    def test_native_fixture_failure_and_listener_reopen_use_same_physical_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            h = digest((canonical(["cobalt river"]) + "\n").encode())
            logical = BudgetLedger(output / "budget.sqlite", "fixture-control", 3)
            logical.reserve("dev-good", "development", "fixture-good", h)
            protocol = {"datasets": {"development": {"sha256": h}}}
            records = []
            body = canonical({"model": "fixture-good", "messages": [{"role": "user", "content":
                "Answer directly without using tools or running code. Your reply must contain this exact phrase: cobalt river"}]}).encode()
            def send_once():
                server = RetryServer(output, protocol, None, records)
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                try:
                    client.request("POST", "/v1/chat/completions", body,
                        {"X-Frontier-Attempt": "dev-good", "X-Frontier-Data-SHA256": h})
                    response = client.getresponse()
                    status = response.status
                    response.read()
                    return status
                finally:
                    client.close(); server.shutdown(); server.server_close(); thread.join(timeout=5)
            try:
                self.assertEqual(send_once(), 503)
                self.assertEqual(send_once(), 200)
                self.assertEqual(send_once(), 409)
                self.assertEqual([r["slot"]["attempt_ordinal"] for r in records], [1, 2, 3])
                self.assertEqual([r["request_sha256"] for r in records], [digest(body)] * 3)
                self.assertEqual(len(logical.snapshot()["attempts"]), 1)
                self.assertEqual(logical.snapshot()["attempts"][0]["status"], "reserved")
                snapshot = HttpBudget(output / "http-budget.sqlite", digest(canonical(protocol).encode()), 6, 2).snapshot()
                self.assertEqual([r["response_status"] for r in snapshot["arrivals"]], [503, 200, 409])
                self.assertTrue(all(r["write_completed"] for r in snapshot["arrivals"]))
            finally:
                logical.close()


if __name__ == "__main__":
    unittest.main()
