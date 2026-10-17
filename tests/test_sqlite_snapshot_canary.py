"""Pure protocol/oracle/path tests: never connect SQLite or launch a worker."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import sqlite_snapshot_canary as probe


class SnapshotCanaryTests(unittest.TestCase):
    def setUp(self):
        self.guards = [patch.object(probe.sqlite3, "connect", side_effect=AssertionError("no SQLite in unit tests")),
                       patch.object(probe.subprocess, "Popen", side_effect=AssertionError("no worker in unit tests")),
                       patch.object(probe.subprocess, "run", side_effect=AssertionError("no worker in unit tests"))]
        for guard in self.guards:
            guard.start()
            self.addCleanup(guard.stop)
        self.protocol = probe.read_protocol(probe.DEFAULT_PROTOCOL)

    def observations(self):
        result = {}
        for arm, generation in (("source", "generation1"), ("main_file_copy", "generation0"),
                                ("sqlite_backup", "generation1")):
            snapshot = self.protocol["expected_snapshots"][generation]
            result[arm] = [dict(integrity_check=["ok"], snapshot=copy.deepcopy(snapshot),
                               logical_sha256=probe.digest(snapshot)) for _ in range(2)]
        return result

    def test_fixed_protocol_and_oracles(self):
        self.assertEqual(self.protocol["seed"], 0)
        self.assertEqual(self.protocol["fresh_readers_per_database"], 2)
        self.assertEqual(len(self.protocol["expected_snapshots"]["generation1"]["messages"]), 2)
        self.assertTrue(all(probe.evaluate_reads(self.observations(), self.protocol["expected_snapshots"]).values()))
        self.assertEqual(probe.uncommitted_oracle(self.protocol)["contexts"][0][1], 2)
        self.assertEqual(len(probe.uncommitted_oracle(self.protocol)["messages"]), 3)

    def test_structurally_valid_backup_can_still_be_stale(self):
        values = self.observations()
        values["sqlite_backup"] = copy.deepcopy(values["main_file_copy"])
        gates = probe.evaluate_reads(values, self.protocol["expected_snapshots"])
        self.assertTrue(gates["sqlite_backup:reader1:integrity_ok"])
        self.assertFalse(gates["sqlite_backup:reader1:literal_snapshot"])
        self.assertFalse(gates["sqlite_backup:reader1:logical_hash"])

    def test_uncommitted_generation_and_partial_rows_rejected(self):
        for table in ("contexts", "messages", "receipts"):
            with self.subTest(table=table):
                values = self.observations()
                values["sqlite_backup"][0]["snapshot"][table].append(["uncommitted", 2])
                gates = probe.evaluate_reads(values, self.protocol["expected_snapshots"])
                self.assertFalse(gates["sqlite_backup:reader1:literal_snapshot"])
                self.assertFalse(gates["sqlite_backup:reopen_stable"])

    def test_missing_second_reader_and_bad_integrity_fail(self):
        values = self.observations()
        values["source"].pop()
        values["main_file_copy"][0]["integrity_check"] = ["corrupt"]
        gates = probe.evaluate_reads(values, self.protocol["expected_snapshots"])
        self.assertFalse(gates["source:two_readers"])
        self.assertFalse(gates["source:reopen_stable"])
        self.assertFalse(gates["main_file_copy:reader1:integrity_ok"])

    def test_logical_hash_is_independent_of_key_order(self):
        a = self.protocol["expected_snapshots"]["generation1"]
        self.assertEqual(probe.digest(a), probe.digest(dict(reversed(list(a.items())))))
        b = copy.deepcopy(a)
        b["messages"].reverse()
        self.assertNotEqual(probe.digest(a), probe.digest(b))

    def test_fixed_settings_cannot_be_tuned(self):
        for key, changed in (("seed", 1), ("synchronous", 1), ("crash_exit_code", 0),
                             ("fresh_readers_per_database", 1), ("worker_timeout_seconds", 11),
                             ("capture_order", ["sqlite_backup", "main_file_copy"]), ("schema_version", True)):
            with self.subTest(key=key):
                protocol = copy.deepcopy(self.protocol)
                protocol[key] = changed
                with self.assertRaises(ValueError):
                    probe.validate_protocol(protocol)

    def test_oracles_cannot_be_resealed_after_a_stale_result(self):
        protocol = copy.deepcopy(self.protocol)
        protocol["expected_snapshots"]["generation1"] = protocol["expected_snapshots"]["generation0"]
        with self.assertRaisesRegex(ValueError, "fixed literal"):
            probe.validate_protocol(protocol)
        protocol = copy.deepcopy(self.protocol)
        protocol["uncommitted_generation2"]["message"][1] = 3
        with self.assertRaisesRegex(ValueError, "uncommitted"):
            probe.validate_protocol(protocol)

    def test_output_paths_are_strict_descendants(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.assertEqual(probe.child_path(root, "raw/reader.jsonl"), root / "raw/reader.jsonl")
            for bad in ("", ".", "../escape", "raw/../../escape", str(root / "absolute")):
                with self.subTest(path=bad), self.assertRaises(ValueError):
                    probe.child_path(root, bad)

    def test_file_hash_covers_actual_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "raw.json"
            path.write_bytes(b'{"generation":1}\n')
            before = probe.file_hash(path)
            path.write_bytes(b'{"generation":0}\n')
            self.assertNotEqual(probe.file_hash(path), before)

    def test_source_and_protocol_freezes_must_match_before_launch(self):
        producer = probe.file_hash(probe.__file__)
        protocol = probe.file_hash(probe.DEFAULT_PROTOCOL)
        probe.verify_freeze(probe.DEFAULT_PROTOCOL, producer, protocol)
        for code_hash, config_hash in ((None, protocol), (producer, None), ("0" * 64, protocol),
                                       (producer, "f" * 64), ("x" * 64, protocol)):
            with self.subTest(code_hash=code_hash), self.assertRaises(ValueError):
                probe.verify_freeze(probe.DEFAULT_PROTOCOL, code_hash, config_hash)

    def freeze(self, directory):
        path = Path(directory) / "implementation.json"
        paths = ("experiments/sqlite_snapshot_canary.py", "tests/test_sqlite_snapshot_canary.py",
                 "fixtures/sqlite-snapshot-canary/protocol.json")
        path.write_text(json.dumps({"schema_version": 1, "experiment": self.protocol["name"],
                                   "files": {name: probe.file_hash(probe.ROOT / name) for name in paths}}),
                        encoding="utf-8")
        return path

    def test_valid_implementation_freeze_then_existing_output_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            freeze = self.freeze(directory)
            probe.verify_implementation_freeze(freeze, probe.DEFAULT_PROTOCOL)
            output = Path(directory) / "already-exists"
            output.mkdir()
            with self.assertRaises(FileExistsError):
                probe.run_probe(output, freeze_path=freeze)

    def test_implementation_freeze_exact_paths_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            freeze = self.freeze(directory)
            value = json.loads(freeze.read_text(encoding="utf-8"))
            value["files"]["tests/test_sqlite_snapshot_canary.py"] = "0" * 64
            freeze.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                probe.verify_implementation_freeze(freeze, probe.DEFAULT_PROTOCOL)
            value["files"]["../escape"] = "0" * 64
            freeze.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly"):
                probe.verify_implementation_freeze(freeze, probe.DEFAULT_PROTOCOL)
            with self.assertRaisesRegex(ValueError, "required"):
                probe.verify_implementation_freeze(None, probe.DEFAULT_PROTOCOL)

    def test_malformed_writer_lines_are_data_and_do_not_hide_original_failure(self):
        parsed = probe.parse_writer_transcript(['{"event":"baseline_ready","pid":1}',
                                                '{"truncated":', '[]', 'null'])
        self.assertEqual([event["event"] for event in parsed["events"]], ["baseline_ready"])
        self.assertEqual([error["line"] for error in parsed["errors"]], [2, 3, 4])
        self.assertEqual(probe.parse_writer_transcript([]), {"events": [], "errors": []})

    def test_protocol_is_json_and_contains_explicit_limits(self):
        encoded = json.loads(probe.DEFAULT_PROTOCOL.read_text(encoding="utf-8"))
        self.assertEqual(encoded, self.protocol)
        self.assertIn("not a novel", " ".join(encoded["limitations"]))
        self.assertIn("production", " ".join(encoded["limitations"]))


if __name__ == "__main__":
    unittest.main()
