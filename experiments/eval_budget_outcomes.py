"""Optional terminal failure receipts for the existing single-owner budget.

An observed failed native entry spends its allowance and retains its exact
receipt. It supplies no reward and cannot enter winner selection. Uncertain
reserved entries still burn on recovery through the unchanged base ledger.
"""
import re

from experiments.eval_budget_runner import BudgetLedger, canonical


class OutcomeBudgetLedger(BudgetLedger):
    def fail(self, key: str, receipt: dict) -> None:
        if (receipt.get("outcome") != "native_failure"
                or not isinstance(receipt.get("episode_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", receipt["episode_sha256"]) is None):
            raise ValueError("native failure with an immutable episode receipt required")
        encoded = canonical(receipt)
        with self.transaction():
            row = self.db.execute("SELECT status,receipt FROM attempts WHERE key=?", (key,)).fetchone()
            if row is None:
                raise ValueError("failure needs an owned reservation")
            if row["status"] == "failed" and row["receipt"] == encoded:
                return  # Receipt replay is idempotent; this never grants native entry.
            if row["status"] != "reserved":
                raise ValueError("terminal failure receipt cannot change")
            self.db.execute("UPDATE attempts SET status='failed',reward=NULL,receipt=? WHERE key=?", (encoded, key))
