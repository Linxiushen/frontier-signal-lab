"""Fixture engineering controls; no Verifiers/native/model/scientific execution."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from experiments.eval_budget_runner import BudgetLedger, canonical, digest
from experiments.verifiers_budget_suite_v2 import FixtureServer, resolve_request


PROMPT = "Answer directly without using tools or running code. Your reply must contain this exact phrase: "


class RequestIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.db = self.output / "budget.sqlite"
        self.ledger = BudgetLedger(self.db, "v2-unit-only", 3)
        self.data = {phase: digest((canonical([phrase]) + "\n").encode())
                     for phase, phrase in [("development", "cobalt river"), ("final", "silent cedar")]}
        self.protocol = {"datasets": {phase: {"sha256": h} for phase, h in self.data.items()},
                         "specification": {"workload": {"http_arrival_ceiling": 3}}}

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def body(self, model="fixture-good", phrase="cobalt river"):
        return {"model": model, "messages": [{"role": "user", "content": PROMPT + phrase}]}

    def test_duplicate_bad_request_does_not_change_good_reservation_identity(self):
        self.ledger.reserve("dev-bad", "development", "fixture-bad", self.data["development"])
        self.ledger.reserve("dev-good", "development", "fixture-good", self.data["development"])
        for _ in range(2):
            self.assertEqual(resolve_request(self.db, self.protocol, "dev-bad", self.data["development"],
                                            self.body("fixture-bad")), ("dev-bad", "deliberate mismatch"))
        self.assertEqual(resolve_request(self.db, self.protocol, "dev-good", self.data["development"], self.body()),
                         ("dev-good", "cobalt river"))
        with self.assertRaises(ValueError):
            resolve_request(self.db, self.protocol, "final-once", self.data["final"], self.body(phrase="silent cedar"))

    def test_missing_changed_completed_and_burned_requests_refused_without_mutation(self):
        self.ledger.reserve("dev-good", "development", "fixture-good", self.data["development"])
        before = self.ledger.snapshot()
        for key, h, body in [("absent", self.data["development"], self.body()),
                             ("dev-good", "changed", self.body()),
                             ("dev-good", self.data["development"], self.body("fixture-bad")),
                             ("dev-good", self.data["development"], self.body(phrase="changed phrase")),
                             ("dev-good", self.data["development"], {"model": "fixture-good", "messages": [{"content": "extra " + PROMPT + "cobalt river"}]})]:
            with self.assertRaises(ValueError):
                resolve_request(self.db, self.protocol, key, h, body)
            self.assertEqual(before, self.ledger.snapshot())
        self.ledger.complete("dev-good", 1, {})
        with self.assertRaises(ValueError):
            resolve_request(self.db, self.protocol, "dev-good", self.data["development"], self.body())
        self.ledger.reserve("uncertain", "development", "fixture-good", self.data["development"])
        self.ledger.recover()
        with self.assertRaises(ValueError):
            resolve_request(self.db, self.protocol, "uncertain", self.data["development"], self.body())

    def test_final_uses_distinct_reserved_content_after_winner(self):
        self.ledger.reserve("dev-good", "development", "fixture-good", self.data["development"])
        self.ledger.complete("dev-good", 1, {})
        self.ledger.seal_winner()
        self.ledger.reserve("final-once", "final", "fixture-good", self.data["final"])
        self.assertEqual(resolve_request(self.db, self.protocol, "final-once", self.data["final"],
                                        self.body(phrase="silent cedar")), ("final-once", "silent cedar"))
        with self.assertRaises(ValueError):
            resolve_request(self.db, self.protocol, "final-once", self.data["development"], self.body())

    def test_failed_arrival_body_retained_and_physical_budget_not_refunded(self):
        self.ledger.reserve("dev-good", "development", "fixture-good", self.data["development"])
        server = FixtureServer(self.output, self.protocol, None)  # JSON path has no dialect dependency.
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        def send(key):
            client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                raw = canonical(self.body()).encode()
                client.request("POST", "/v1/chat/completions", raw,
                               {"X-Frontier-Attempt": key, "X-Frontier-Data-SHA256": self.data["development"]})
                reply = client.getresponse()
                return reply.status, reply.read()
            finally:
                client.close()
        try:
            self.assertEqual(send("absent")[0], 409)
            self.assertEqual(send("dev-good")[0], 200)
            self.assertEqual(send("dev-good")[0], 200)
            self.assertEqual(send("dev-good")[0], 409)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=5)
        self.assertEqual([r["status"] for r in server.records], ["refused_or_failed", "delivered", "delivered", "refused_or_failed"])
        self.assertIn("budget exhausted", server.records[3]["error"])
        for i, record in enumerate(server.records, 1):
            self.assertEqual(json.loads((self.output / f"http-{i}-arrival.json").read_bytes()), record)
            self.assertEqual(digest((self.output / f"http-{i}-request.bin").read_bytes()), record["request_sha256"])
            self.assertEqual(digest((self.output / f"http-{i}-response.bin").read_bytes()), record["response_sha256"])
            self.assertTrue(record["request_body_complete"])
        self.assertEqual(len(self.ledger.snapshot()["attempts"]), 1)


if __name__ == "__main__":
    unittest.main()
