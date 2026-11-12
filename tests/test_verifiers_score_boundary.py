"""Real worker/SQLite boundary with a stubbed runner; no native/model evidence."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments import verifiers_budget_exhaustion as driver
from experiments.eval_budget_outcomes import OutcomeBudgetLedger
from experiments.eval_budget_runner import canonical, digest


class StopAtBarrier(Exception):
    pass


class ScoreVersionBoundaryTests(unittest.TestCase):
    def exercise(self, phase, mutate):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            evaluator = output / "evaluator.py"
            evaluator.write_bytes(b"denominator = 1\n")
            data = output / "data.json"
            data.write_bytes(b'["cobalt river"]\n')
            data_hash = digest(data.read_bytes())
            protocol = {
                "versions": {str(evaluator): digest(evaluator.read_bytes())},
                "evaluator_path": str(evaluator),
                "datasets": {stage: {"path": str(data), "sha256": data_hash}
                             for stage in ("development", "final")},
            }
            protocol_path = output / "protocol.json"
            protocol_path.write_text(canonical(protocol), encoding="utf-8")
            identity = digest(protocol_path.read_bytes())
            if phase == 2:
                prior = OutcomeBudgetLedger(output / "budget.sqlite", identity, 3)
                try:
                    prior.reserve("dev-ok", "development", "fixture-bad", data_hash)
                    prior.complete("dev-ok", 0.0, {"control": "prior unchanged entry"})
                finally:
                    prior.close()

            ok = phase == 1
            trace = types.SimpleNamespace(
                ok=ok, errors=[] if ok else ["stub failure"], is_dropped=False,
                num_turns=1 if ok else 0, reward=0.0,
                rewards={"echoed": types.SimpleNamespace(score=0.0, weight=1.0)} if ok else {},
            )
            episode = types.SimpleNamespace(
                ok=ok, errors=[] if ok else ["stub failure"], traces=[trace],
                to_json=lambda: json.dumps({"stubbed_episode": True, "ok": ok}).encode(),
            )
            calls = []

            async def run_episodes(config):
                calls.append(config)
                if mutate:
                    evaluator.write_bytes(b"denominator = 2\n")
                return [episode]

            modules = {}
            for name in ("verifiers", "verifiers.v1", "verifiers.v1.cli",
                         "verifiers.v1.configs", "verifiers.v1.configs.cli"):
                modules[name] = types.ModuleType(name)
                modules[name].__path__ = []
            modules["verifiers.v1.cli.run"] = types.ModuleType("verifiers.v1.cli.run")
            modules["verifiers.v1.cli.run"].run_episodes = run_episodes
            modules["verifiers.v1.configs.cli.run"] = types.ModuleType("verifiers.v1.configs.cli.run")
            modules["verifiers.v1.configs.cli.run"].RunnerConfig = types.SimpleNamespace(model_validate=lambda cfg: cfg)
            modules["echo"] = types.ModuleType("echo")
            modules["echo"].__file__ = str(evaluator)
            opened = []

            def open_ledger(*args):
                ledger = OutcomeBudgetLedger(*args)
                opened.append(ledger)
                return ledger

            try:
                with patch.dict(sys.modules, modules), \
                     patch.object(driver, "OutcomeBudgetLedger", side_effect=open_ledger), \
                     patch.object(driver.inspect, "getfile", return_value="/source/verifiers/v1/cli/run.py"), \
                     patch.object(driver, "Path", side_effect=lambda path: Path(path).resolve()), \
                     patch.object(driver.time, "sleep", side_effect=StopAtBarrier):
                    error = ValueError if mutate else StopAtBarrier
                    with self.assertRaises(error):
                        driver.worker(protocol_path, output, phase, "http://127.0.0.1:1/v1")
            finally:
                for ledger in opened:
                    ledger.close()

            self.assertEqual(len(calls), 1)
            key = "dev-ok" if ok else "dev-attempt-cap"
            self.assertTrue((output / f"{key}-episode.json").is_file())
            ledger = OutcomeBudgetLedger(output / "budget.sqlite", identity, 3)
            try:
                row = next(row for row in ledger.snapshot()["attempts"] if row["key"] == key)
                if mutate:
                    # Detection must precede both success and failure terminal commits.
                    self.assertEqual((row["status"], row["reward"], row["receipt"]),
                                     ("reserved", None, None))
                    self.assertFalse((output / f"{key}-receipt.json").exists())
                    self.assertEqual(ledger.recover(), 1)
                    self.assertFalse(ledger.reserve(key, "development", row["model"], data_hash))
                    if phase == 1:
                        with self.assertRaises(ValueError):
                            ledger.seal_winner()
                    else:
                        self.assertEqual(ledger.seal_winner(), "fixture-bad")
                else:
                    self.assertEqual(row["status"], "completed" if ok else "failed")
                    self.assertEqual(row["reward"], 0.0 if ok else None)
                    self.assertEqual(ledger.recover(), 0)
                    self.assertTrue((output / f"{key}-receipt.json").is_file())
            finally:
                ledger.close()

    def test_changed_version_never_commits_success_score(self):
        self.exercise(1, True)

    def test_changed_version_never_commits_terminal_failure(self):
        self.exercise(2, True)

    def test_unchanged_version_keeps_success_receipt(self):
        self.exercise(1, False)

    def test_unchanged_version_keeps_failure_receipt(self):
        self.exercise(2, False)


if __name__ == "__main__":
    unittest.main()
