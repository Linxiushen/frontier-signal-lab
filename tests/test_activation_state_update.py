"""Protocol integrity, context isolation and incomplete-run controls; no model execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
from unittest.mock import patch

from experiments import activation_state_update_probe as probe


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = probe.ROOT / "fixtures/activation-state-update/protocol.json"
        self.data = probe.ROOT / "fixtures/activation-training/data.json"
        self.manifest = probe.ROOT / "fixtures/activation-training/manifest.json"

    def test_pins_reject_protocol_or_data_changes(self):
        p = probe.validate_protocol(self.protocol, self.data, self.manifest)
        self.assertEqual(p["config"]["native_expected_steps"]["matched_step4"], 5)
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "changed.json"
            changed.write_bytes(self.protocol.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "protocol bytes changed"):
                probe.validate_protocol(changed, self.data, self.manifest)
            changed.write_bytes(self.data.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "data/manifest"):
                probe.validate_protocol(self.protocol, changed, self.manifest)

    def test_freeze_is_content_bound_and_chronological(self):
        p = probe.validate_protocol(self.protocol, self.data, self.manifest)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "freeze.json"
            with patch.object(probe, "utcnow", return_value="2026-10-16T11:00:00+00:00"):
                frozen = probe.freeze_implementation(path, self.protocol, self.data, self.manifest)
            probe.validate_freeze(path, p, self.protocol, started_at="2026-10-16T11:00:01+00:00")
            with self.assertRaisesRegex(ValueError, "chronology"):
                probe.validate_freeze(path, p, self.protocol, started_at="2026-10-16T10:59:59+00:00")
            with self.assertRaisesRegex(ValueError, "already exists"):
                probe.freeze_implementation(path, self.protocol, self.data, self.manifest)
            frozen["new_source_files_sha256"][p["new_source_paths"][0]] = "0" * 64
            frozen["receipt_sha256"] = probe.digest({k:v for k,v in frozen.items() if k != "receipt_sha256"})
            path.write_text(json.dumps(frozen), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "freeze mismatch"):
                probe.validate_freeze(path, p, self.protocol)

    def test_timeout_retains_incomplete_receipt_and_never_becomes_scientific_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe"
            failure = subprocess.TimeoutExpired(["worker"], 420, output=b"partial stdout", stderr=b"partial stderr")
            with patch.object(probe, "validate_freeze", return_value={}), patch.object(
                    probe.subprocess, "run", side_effect=failure) as run:
                with self.assertRaises(subprocess.TimeoutExpired):
                    probe.run_probe(directory, self.data, self.manifest, self.protocol, "unused-freeze", output)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["timeout"], 420)
            receipt = json.loads((output / "incomplete.json").read_text(encoding="utf-8"))
            self.assertFalse(receipt["completed"])
            self.assertIsNone(receipt["scientific_gate_outcome"])
            self.assertFalse((output / "report.json").exists())
            self.assertEqual((output / "workers/seed-11/stderr.txt").read_text(encoding="utf-8"), "partial stderr")


def contexts(primary=.11, secondary=.04):
    result = {}
    for name, treatment in zip(probe.CONTEXTS, (primary, secondary)):
        result[name] = [{"method": method, "update_comparison": {"aggregate": {
            "relative_l2": error, "cosine_similarity": cosine}}}
            for method, error, cosine in zip(probe.attention.METHODS, (0., .5, treatment), (1., .8, .999))]
    return result


class ScientificGateTests(unittest.TestCase):
    def test_fresh_success_cannot_rescue_matched_failure(self):
        gates = probe.context_gates(contexts())
        self.assertFalse(gates["primary_passed"])
        self.assertTrue(gates["contexts"]["fresh_step0"]["passed"])
        for records in ({"fresh_step0": contexts()["fresh_step0"]}, dict(reversed(list(contexts().items())))):
            with self.assertRaises(ValueError):
                probe.context_gates(records)
        changed = contexts()
        changed["matched_step4"].reverse()
        with self.assertRaises(ValueError):
            probe.context_gates(changed)

    def test_every_seed_and_complete_execution_counts_required(self):
        protocol = json.loads((probe.ROOT / "fixtures/activation-state-update/protocol.json").read_text(encoding="utf-8"))
        workers = [{"seed": seed, "completed": True, "initial_parameter_sha256": "same",
                    "contexts": contexts(.04, .04), "counts": {"dense_warmup_backwards": 4,
                        "probe_backwards": 3, "native_warmup_steps": 4, "native_clone_steps": 6}}
                   for seed in (11, 29, 47)]
        self.assertTrue(probe.summarize_workers(workers, protocol)["primary_gate_passed_all_seeds"])
        workers[2]["contexts"] = contexts(.11, .04)
        self.assertFalse(probe.summarize_workers(workers, protocol)["primary_gate_passed_all_seeds"])
        for mutation in (lambda w: w.pop(), lambda w: w[0].update(completed=False),
                         lambda w: w[0]["counts"].update(native_clone_steps=5),
                         lambda w: w[0].update(initial_parameter_sha256="other")):
            changed = copy.deepcopy(workers)
            mutation(changed)
            with self.assertRaises(ValueError):
                probe.summarize_workers(changed, protocol)


if __name__ == "__main__":
    unittest.main()
