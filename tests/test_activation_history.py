"""History protocol, isolation and arithmetic controls; never load a model checkpoint."""
import copy
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from experiments import activation_history_probe as probe

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


def policies(error=.04):
    return [{"method": method, "update_comparison": {"aggregate": {
        "relative_l2": rel, "cosine_similarity": cosine}}}
        for method, rel, cosine in zip(probe.attention.METHODS, (0., .5, error), (1., .8, .999))]


def worker_fixture(seed):
    histories = {}
    for h in probe.HISTORIES:
        anchors = []
        for step in probe.AUDIT_STEPS:
            records = policies()
            anchors.append({"history": h, "step": step, "policies": records, "gate": probe.anchor_gate(records),
                "source_state_buffers_rng_unchanged": True, "audit_gradients_cleared": True})
        histories[h] = {"steps": [{"step": i} for i in range(1, 9)], "anchors": anchors}
    return {"seed": seed, "completed": True, "initial_parameter_sha256": "same",
        "histories_storage_disjoint": True, "histories": histories,
        "trajectory_drift": [{"step": s} for s in probe.AUDIT_STEPS],
        "counts": dict(zip(probe.COUNT_KEYS, (16, 12, 16, 12)))}


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.protocol = probe.ROOT / "fixtures/activation-history/protocol.json"
        self.data = probe.ROOT / "fixtures/activation-history/data.json"
        self.manifest = probe.ROOT / "fixtures/activation-history/manifest.json"

    def test_frozen_bytes_schedule_and_new_data(self):
        p = probe.validate_protocol(self.protocol, self.data, self.manifest)
        arrays, _ = probe.load_history_data(self.data, self.manifest)
        self.assertEqual(arrays["train"].shape, (8, 65))
        self.assertEqual(arrays["audit"].shape, (4, 65))
        self.assertEqual(arrays["train"].dtype, np.dtype("int64"))
        self.assertEqual(p["config"]["expected_anchors"], 12)
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "changed.json"
            for original, message, args in ((self.protocol, "protocol bytes changed", (self.data, self.manifest)),
                    (self.data, "data/manifest", None)):
                changed.write_bytes(original.read_bytes() + b"\n")
                with self.assertRaisesRegex(ValueError, message):
                    if args:
                        probe.validate_protocol(changed, *args)
                    else:
                        probe.validate_protocol(self.protocol, changed, self.manifest)

    def test_schema_tokens_and_all_block_disjointness(self):
        data = json.loads(self.data.read_text(encoding="utf-8"))
        previous = json.loads((probe.ROOT / "fixtures/activation-training/data.json").read_text(encoding="utf-8"))
        mutations = [lambda x: x.update(schema_version=2), lambda x: x["train"].pop(),
            lambda x: x["audit"][0].pop(), lambda x: x["train"][0].__setitem__(0, True),
            lambda x: x["train"][0].__setitem__(0, -1), lambda x: x["train"][0].__setitem__(0, 50304),
            lambda x: x["audit"].__setitem__(0, x["train"][0]),
            lambda x: x["train"].__setitem__(1, x["train"][0]),
            lambda x: x["train"].__setitem__(0, previous["holdout"][0])]
        for mutate in mutations:
            candidate = copy.deepcopy(data)
            mutate(candidate)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                probe.validate_blocks(candidate, previous)

    def test_manifest_source_and_preparation_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
            for name in ("train.txt", "audit.txt"):
                (directory / name).write_bytes((self.manifest.parent / name).read_bytes())
            path = directory / "manifest.json"
            for field in ("tokenizer_sha256", "preparation_script_sha256", "data_sha256"):
                changed = copy.deepcopy(manifest)
                changed[field] = "0" * 64
                probe.write_json(path, changed)
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "pin mismatch"):
                    probe.load_history_data(self.data, path)
            probe.write_json(path, manifest)
            (directory / "train.txt").write_bytes(b"modified source")
            with self.assertRaisesRegex(ValueError, "source manifest/hash"):
                probe.load_history_data(self.data, path)

    def test_freeze_integrity_chronology_and_overwrite(self):
        p = probe.validate_protocol(self.protocol, self.data, self.manifest)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "freeze.json"
            with patch.object(probe, "utcnow", return_value="2026-10-16T12:49:00+00:00"):
                with self.assertRaisesRegex(ValueError, "chronology"):
                    probe.freeze_implementation(path, self.protocol, self.data, self.manifest)
            self.assertFalse(path.exists())
            with patch.object(probe, "utcnow", return_value="2026-10-16T13:10:00+00:00"):
                frozen = probe.freeze_implementation(path, self.protocol, self.data, self.manifest)
            probe.validate_freeze(path, p, self.protocol, started_at="2026-10-16T13:10:01+00:00")
            with self.assertRaisesRegex(ValueError, "chronology"):
                probe.validate_freeze(path, p, self.protocol, started_at="2026-10-16T13:09:59+00:00")
            with self.assertRaisesRegex(ValueError, "already exists"):
                probe.freeze_implementation(path, self.protocol, self.data, self.manifest)
            frozen["new_source_files_sha256"][p["new_source_paths"][1]] = "0" * 64
            frozen["receipt_sha256"] = probe.digest({k: v for k, v in frozen.items() if k != "receipt_sha256"})
            probe.write_json(path, frozen)
            with self.assertRaisesRegex(ValueError, "freeze mismatch"):
                probe.validate_freeze(path, p, self.protocol)

    def test_parent_timeout_retains_partial_artifacts_and_null_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "probe"
            failure = subprocess.TimeoutExpired(["worker"], 960, output=b"partial stdout", stderr=b"partial stderr")
            with patch.object(probe, "validate_freeze", return_value={}), patch.object(
                    probe.subprocess, "run", side_effect=failure) as run:
                with self.assertRaises(subprocess.TimeoutExpired):
                    probe.run_probe(directory, self.data, self.manifest, self.protocol, "unused-freeze", output)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.kwargs["timeout"], 960)
            receipt = json.loads((output / "incomplete.json").read_text(encoding="utf-8"))
            self.assertFalse(receipt["completed"])
            self.assertIsNone(receipt["scientific_gate_outcome"])
            self.assertFalse((output / "report.json").exists())
            self.assertEqual((output / "workers/seed-101/stderr.txt").read_text(encoding="utf-8"), "partial stderr")
            with patch.object(probe, "validate_freeze", return_value={}):
                with self.assertRaisesRegex(ValueError, "fresh nonexistent"):
                    probe.run_probe(directory, self.data, self.manifest, self.protocol, "unused-freeze", output)

    def test_worker_refuses_existing_output_before_model_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(probe, "verify_model_assets") as load:
                with self.assertRaises(FileExistsError):
                    probe.worker(directory, self.data, self.manifest, self.protocol, "unused", directory, 101)
                load.assert_not_called()


class GateTests(unittest.TestCase):
    def setUp(self):
        self.protocol = json.loads((probe.ROOT / "fixtures/activation-history/protocol.json").read_text(encoding="utf-8"))
        self.workers = [worker_fixture(seed) for seed in (101, 211, 307)]

    def test_all_twelve_anchors_and_no_seed_history_checkpoint_rescue(self):
        summary = probe.summarize_workers(self.workers, self.protocol)
        self.assertEqual(len(summary["anchor_gates"]), 12)
        self.assertTrue(summary["primary_gate_passed_all_anchors"])
        anchor = self.workers[2]["histories"][probe.HISTORIES[1]]["anchors"][1]
        anchor["policies"] = policies(.11)
        anchor["gate"] = probe.anchor_gate(anchor["policies"])
        self.assertFalse(probe.summarize_workers(self.workers, self.protocol)["primary_gate_passed_all_anchors"])
        self.assertTrue(summary["trajectory_drift_has_no_pass_threshold"])

    def test_missing_duplicate_order_count_or_control_failures_reject(self):
        mutations = [lambda w: w.pop(), lambda w: w.reverse(), lambda w: w[0].update(completed=False),
            lambda w: w[0]["counts"].update(native_clone_steps=11),
            lambda w: w[0].update(initial_parameter_sha256="other"),
            lambda w: w[0]["histories"].pop(probe.HISTORIES[1]),
            lambda w: w[0]["histories"]["dense"]["steps"].pop(),
            lambda w: w[0]["histories"]["dense"]["anchors"].reverse(),
            lambda w: w[0]["histories"]["dense"]["anchors"].__setitem__(1, w[0]["histories"]["dense"]["anchors"][0]),
            lambda w: w[0]["histories"]["dense"]["anchors"][0].update(audit_gradients_cleared=False),
            lambda w: w[0]["histories"]["dense"]["anchors"][0]["policies"].reverse(),
            lambda w: w[0]["trajectory_drift"].pop()]
        for mutate in mutations:
            changed = copy.deepcopy(self.workers)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                probe.summarize_workers(changed, self.protocol)


@unittest.skipUnless(TORCH_AVAILABLE, "optional CPU Torch is unavailable")
class TinyTensorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.torch = probe.require_torch()

    def tiny(self):
        model = self.torch.nn.Linear(2, 1, bias=False)
        with self.torch.no_grad():
            model.weight.copy_(self.torch.tensor([[.25, -.5]]))
        named = list(model.named_parameters())
        return model, named, probe.native.make_optimizer(named)

    def backward(self, model, tokens, method):
        model.zero_grad(set_to_none=True)
        values = {probe.attention.METHODS[0]: [.2, -.3], probe.attention.METHODS[1]: [-.1, -.2],
                  probe.attention.METHODS[2]: [.23, -.27]}
        model.weight.grad = self.torch.tensor([values[method]], dtype=self.torch.float32)
        return {"forward_loss": 1.25, "logits_sha256": "constant", "timing_seconds_descriptive_only": {"backward": 99}}

    def test_actual_history_continues_and_discarded_audits_preserve_state_clear_grads(self):
        model, named, optimizer = self.tiny()
        tokens = self.torch.tensor([[1, 2]])
        with patch.object(probe.attention, "backward_once", side_effect=self.backward), patch.object(probe.stateprobe, "validate_gradient"):
            first = probe.history_step(model, named, optimizer, tokens, "dense", 1, [], [])
            self.assertGreater(first["actual_native_delta_l2"], 0)
            state = probe.native.state_hash(named, optimizer)
            audit = probe.audit_anchor(model, named, optimizer, tokens, "dense", 1, [], [])
            self.assertEqual(probe.native.state_hash(named, optimizer), state)
            self.assertTrue(audit["audit_gradients_cleared"])
            self.assertTrue(all(p.grad is None for _, p in named))
            self.assertEqual([set(p["input_steps"].values()) for p in audit["policies"]], [{1}, {1}, {1}])
            second = probe.history_step(model, named, optimizer, tokens, "dense", 2, [], [])
            self.assertEqual(second["state_sha256_before"], state)
            self.assertEqual(optimizer.state[named[0][1]]["step"].item(), 2)
            self.assertTrue(all(p.grad is None for _, p in named))

    def test_policy_histories_accumulate_their_own_real_moments(self):
        histories = {}
        with patch.object(probe.attention, "backward_once", side_effect=self.backward), patch.object(probe.stateprobe, "validate_gradient"):
            for h in probe.HISTORIES:
                model, named, optimizer = self.tiny()
                histories[h] = {"model": model, "named": named, "optimizer": optimizer}
                for step in range(1, 3):
                    probe.history_step(model, named, optimizer, self.torch.tensor([[1, 2]]), h, step, [], [])
            self.assertTrue(probe.assert_history_storage_disjoint(histories))
            d, t = [histories[h] for h in probe.HISTORIES]
            ds = probe.native.freeze_optimizer_state(d["named"], d["optimizer"])
            ts = probe.native.freeze_optimizer_state(t["named"], t["optimizer"])
            self.assertFalse(self.torch.equal(ds["weight"]["exp_avg"], ts["weight"]["exp_avg"]))
            self.assertEqual(ds["weight"]["step"], ts["weight"]["step"])
            histories[probe.HISTORIES[1]]["named"] = d["named"]
            with self.assertRaisesRegex(ValueError, "share"):
                probe.assert_history_storage_disjoint(histories)

    def test_audit_source_mutation_and_forward_mismatch_stop_and_clear(self):
        for fault in ("source", "forward", "rng"):
            model, named, optimizer = self.tiny()
            calls = []
            def bad_backward(m, tokens, method):
                r = self.backward(m, tokens, method)
                calls.append(method)
                if fault == "source" and len(calls) == 1:
                    with self.torch.no_grad():
                        m.weight.add_(.01)
                elif fault == "forward" and len(calls) == 2:
                    r["forward_loss"] = 2.0
                elif fault == "rng":
                    self.torch.rand(1)
                return r
            with self.subTest(fault=fault), patch.object(probe.attention, "backward_once", side_effect=bad_backward), patch.object(probe.stateprobe, "validate_gradient"):
                with self.assertRaises(ValueError):
                    probe.audit_anchor(model, named, optimizer, self.torch.tensor([[1, 2]]), "dense", 0, [], [])
                self.assertTrue(all(p.grad is None for _, p in named))

    def test_audit_clone_initial_state_counter_and_control_mismatch_reject(self):
        real_clone = probe.native.clone_step
        for field in ("initial_full_state_sha256", "input_steps", "sources_unchanged"):
            model, named, optimizer = self.tiny()
            def bad_clone(*args, **kwargs):
                record, retained = real_clone(*args, **kwargs)
                record[field] = {"weight": 99} if field == "input_steps" else False
                return record, retained
            with self.subTest(field=field), patch.object(probe.attention, "backward_once", side_effect=self.backward), patch.object(probe.stateprobe, "validate_gradient"), patch.object(probe.native, "clone_step", side_effect=bad_clone):
                with self.assertRaisesRegex(ValueError, "anchor/counter/native control"):
                    probe.audit_anchor(model, named, optimizer, self.torch.tensor([[1, 2]]), "dense", 0, [], [])
                self.assertTrue(all(p.grad is None for _, p in named))

    def test_drift_matches_independent_arithmetic_and_has_no_threshold(self):
        t = self.torch.tensor
        dense, treatment, initial = {"x": t([3., 4.])}, {"x": t([3., 6.])}, {"x": t([0., 0.])}
        ds = {"x": {"exp_avg": t([1., 2.]), "exp_avg_sq": t([2., 3.]), "step": 4}}
        ts = {"x": {"exp_avg": t([2., 2.]), "exp_avg_sq": t([2., 6.]), "step": 4}}
        r = probe.trajectory_drift(list(dense.items()), ds, list(treatment.items()), ts, initial, 8., 4)
        self.assertEqual(r["parameter"]["aggregate"]["difference_l2"], 2.)
        self.assertAlmostEqual(r["parameter"]["aggregate"]["relative_l2"], .4)
        self.assertAlmostEqual(r["parameter"]["aggregate"]["cosine_similarity"], 33 / (5 * math.sqrt(45)))
        self.assertEqual(r["exp_avg"]["aggregate"]["difference_l2"], 1.)
        self.assertEqual(r["exp_avg_sq"]["aggregate"]["difference_l2"], 3.)
        self.assertEqual(r["normalizations"]["dense_cumulative_displacement"]["parameter_drift_ratio"], .4)
        self.assertEqual(r["normalizations"]["dense_update_path_length"]["parameter_drift_ratio"], .25)
        self.assertNotIn("gate", r)
        self.assertNotIn("passed", r)
        ts["x"]["step"] = 3
        with self.assertRaisesRegex(ValueError, "counters"):
            probe.trajectory_drift(list(dense.items()), ds, list(treatment.items()), ts, initial, 8., 4)

    def test_zero_denominators_explicit_and_json_safe(self):
        zero = {"x": self.torch.zeros(2)}
        one = {"x": self.torch.ones(2)}
        states = {"x": {"exp_avg": self.torch.zeros(2), "exp_avg_sq": self.torch.zeros(2), "step": 4}}
        r = probe.trajectory_drift(list(zero.items()), states, list(one.items()), copy.deepcopy(states), zero, 0., 4)
        self.assertIsNone(r["parameter"]["aggregate"]["relative_l2"])
        self.assertIsNone(r["exp_avg"]["aggregate"]["cosine_similarity"])
        self.assertTrue(all(v["parameter_drift_ratio"] is None and v["undefined_reason"] for v in r["normalizations"].values()))
        json.dumps(r, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
