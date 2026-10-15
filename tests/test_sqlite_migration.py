"""Real disk, hard process exits and independent obligation accounting."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from experiments import sqlite_migration_probe as probe


class SQLiteMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # One complete matrix: 10 traces, exactly 20 bounded child processes.
        cls.report = probe.run_probe()

    def test_decoder_distinguishes_errors_from_unknown_evidence(self):
        expected = {"02-missing": "missing_assignment_id", "03-truncated": "invalid_json",
                    "04-version": "unsupported_version"}
        for binding, task, raw in probe.fixtures():
            value, error = probe.decode(raw, task)
            self.assertEqual(error, expected.get(binding))
            self.assertEqual(value is None, binding in expected)
        self.assertEqual(probe.decode("[]", "t")[1], "not_an_object")
        self.assertEqual(probe.decode('{"version":true}', "t")[1], "unsupported_version")

    def test_false_clean_is_detected_without_claiming_row_deletion(self):
        for row in self.report["runs"]:
            m = row["metrics"]
            self.assertTrue(m["original_rows_preserved"])
            self.assertEqual(m["visible_obligations"], 6)
            self.assertEqual(m["missing_obligations"], 0)
            self.assertEqual(m["invalid_binding_rows"], 3)
            self.assertEqual(m["invalid_rows_accepted_into_bindings"], 0)
            self.assertEqual(m["unknown_evidence_newly_retired"], 0)
            if row["policy"] == "silent_skip":
                self.assertTrue(m["false_clean"])
                self.assertEqual(m["invalid_rows_without_warning"], 3)
            else:
                self.assertFalse(m["false_clean"])
                self.assertEqual(m["invalid_rows_without_warning"], 0)

    def test_progress_counts_do_not_treat_preservation_or_blocking_as_done(self):
        for row in self.report["runs"]:
            m = row["metrics"]
            self.assertEqual(m["accepted_obligations_total"], 6)
            self.assertEqual(m["accepted_obligations_current"] + m["runnable_obligations"]
                             + m["blocked_obligations"] + m["done_obligations"], 6)
            self.assertEqual(m["done_obligations"], 0)
            self.assertEqual(m["unresolved_obligations"], 6)
            self.assertEqual(m["runnable_obligations"], 1)
            self.assertEqual(m["blocked_obligations"], 5 if row["policy"] == "warn_preserve" else 2)

    def test_hard_exit_really_rolls_back_transaction_before_commit(self):
        for row in self.report["runs"]:
            if row["crashpoint"] not in ("after_row_write", "after_diagnostic_step", "before_commit"):
                continue
            self.assertEqual(row["worker_exit_code"], probe.CRASH_EXIT)
            self.assertEqual(row["snapshots"]["after_fault"], row["snapshots"]["before"])
            self.assertEqual(row["snapshots"]["after_fault"]["migration_state"][0]["version"], 0)
            self.assertTrue(row["transaction_atomic"])

    def test_post_commit_exit_retains_complete_migration(self):
        for row in self.report["runs"]:
            if row["crashpoint"] != "after_commit":
                continue
            self.assertEqual(row["worker_exit_code"], probe.CRASH_EXIT)
            self.assertEqual(row["snapshots"]["after_fault"], row["snapshots"]["after_recovery"])
            self.assertEqual(row["snapshots"]["after_fault"]["migration_state"][0]["version"], 1)

    def test_restart_and_replay_are_idempotent(self):
        for row in self.report["runs"]:
            self.assertTrue(row["replay_idempotent"])
            self.assertEqual(row["snapshots"]["after_recovery"], row["snapshots"]["after_replay"])
            self.assertTrue(row["transaction_atomic"])
        for policy in probe.POLICIES:
            outcomes = [row["snapshot_sha256"]["after_recovery"] for row in self.report["runs"]
                        if row["policy"] == policy]
            self.assertEqual(len(set(outcomes)), 1)

    def test_remigration_preserves_independently_completed_obligation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite3"
            probe.initialize(path)
            probe.migrate(path, "warn_preserve")
            connection = probe.connect(path)
            connection.execute("UPDATE obligations SET state='done',reason=NULL WHERE task_id='task-valid'")
            connection.close()
            before = probe.snapshot(path)
            probe.migrate(path, "warn_preserve")
            self.assertEqual(probe.snapshot(path), before)

    def test_warnings_preserve_exact_original_text_hash(self):
        for row in self.report["runs"]:
            disk = row["snapshots"]["after_recovery"]
            raw = {r["binding_id"]: r["value_json"] for r in disk["legacy_bindings"]}
            for warning in disk["warnings"]:
                self.assertEqual(warning["original_sha256"],
                                 hashlib.sha256(raw[warning["binding_id"]].encode("utf-8")).hexdigest())

    def test_unknown_evidence_cannot_retire_even_with_terminal_hint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite3"
            probe.initialize(path)
            connection = probe.connect(path)
            value = json.loads(connection.execute("SELECT value_json FROM legacy_bindings WHERE binding_id='05-unknown'").fetchone()[0])
            value["delivery_evidence"] = "terminal"
            connection.execute("UPDATE legacy_bindings SET value_json=? WHERE binding_id='05-unknown'",
                               (probe.canonical(value),))
            connection.close()
            probe.migrate(path, "warn_preserve")
            disk = probe.snapshot(path)
            bindings = {r["binding_id"]: r for r in disk["bindings"]}
            tasks = {r["task_id"]: r for r in disk["obligations"]}
            self.assertEqual(bindings["05-unknown"]["state"], "active")
            self.assertEqual(tasks["task-unknown"]["reason"], "unknown_requester_evidence")
            self.assertEqual(bindings["06-terminal"]["state"], "retired")
            self.assertEqual(tasks["task-terminal"]["state"], "blocked")

    def test_result_and_snapshot_hashes_are_verifiable(self):
        report = copy.deepcopy(self.report)
        result_hash = report.pop("result_sha256")
        self.assertEqual(probe.digest(report), result_hash)
        for row in report["runs"]:
            for phase, disk in row["snapshots"].items():
                self.assertEqual(probe.digest(disk), row["snapshot_sha256"][phase])

    def test_exports_are_replayable_sql_and_explicit_negative_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            probe.write_report(self.report, root)
            self.assertEqual(json.loads((root / "probe.json").read_text()), self.report)
            report = (root / "report.md").read_text()
            self.assertIn("Blocking is not success", report)
            self.assertEqual(len(list((root / "counterexamples").glob("*.json"))), 5)
            self.assertEqual(len(list((root / "sql").glob("*.sql"))), 20)
            row = self.report["runs"][-1]
            restored = root / "restored.sqlite3"
            connection = sqlite3.connect(restored)
            connection.executescript(row["sql_snapshots"]["after_recovery"])
            connection.close()
            self.assertEqual(probe.snapshot(restored), row["snapshots"]["after_recovery"])

    def test_measure_uses_database_rows_and_invalid_config_is_rejected(self):
        disk = copy.deepcopy(self.report["runs"][0]["snapshots"]["after_recovery"])
        with patch.object(probe, "decode", side_effect=AssertionError("metric must not reuse decoder")):
            self.assertEqual(probe.measure(disk)["invalid_binding_rows"], 3)
        disk["obligations"] = disk["obligations"][1:]
        self.assertEqual(probe.measure(disk)["missing_obligations"], 1)
        for policies, crashes in [((), probe.CRASHPOINTS), (("unknown",), ("none",)),
                                  (probe.POLICIES, ("unknown",))]:
            with self.assertRaises(ValueError):
                probe.run_probe(policies, crashes)


if __name__ == "__main__":
    unittest.main()
