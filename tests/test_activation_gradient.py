"""Independent fixed-point controls for the CE/model hook-boundary diagnostic."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from experiments import activation_gradient_probe as probe

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


class ProtocolAndMetricTests(unittest.TestCase):
    def test_protocol_rejects_changed_config_data_and_execution_source(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            data, manifest, protocol = [directory / name for name in ("data.json", "manifest.json", "protocol.json")]
            data.write_bytes(b"data")
            manifest.write_bytes(b"manifest")
            payload = {"schema_version": 1, "config": probe.preset_config(),
                       "data_sha256": probe.file_hash(data), "training_manifest_sha256": probe.file_hash(manifest),
                       "source_files_sha256": {path: probe.file_hash(probe.ROOT / path) for path in probe.SOURCE_PATHS}}
            payload["config_sha256"] = probe.digest(payload["config"])

            def save(value):
                protocol.write_text(json.dumps(value), encoding="utf-8")

            save(payload)
            self.assertEqual(probe.validate_protocol(protocol, data, manifest), payload)
            modified = copy.deepcopy(payload)
            modified["config"]["methods_in_order"].reverse()
            modified["config_sha256"] = probe.digest(modified["config"])
            save(modified)
            with self.assertRaisesRegex(ValueError, "preset"):
                probe.validate_protocol(protocol, data, manifest)
            modified = copy.deepcopy(payload)
            modified["data_sha256"] = "0" * 64
            save(modified)
            with self.assertRaisesRegex(ValueError, "data/manifest"):
                probe.validate_protocol(protocol, data, manifest)
            modified = copy.deepcopy(payload)
            modified["source_files_sha256"][probe.SOURCE_PATHS[0]] = "0" * 64
            save(modified)
            with self.assertRaisesRegex(ValueError, "execution source"):
                probe.validate_protocol(protocol, data, manifest)

    def test_aggregate_vector_metrics_and_degenerate_norms(self):
        # Two independent vector pieces: reference [3,0,4], candidate [0,0,4].
        actual = probe.aggregate_metrics([
            {"reference_sum_squares": 9, "candidate_sum_squares": 0, "difference_sum_squares": 9,
             "dot_product": 0, "max_absolute_difference": 3},
            {"reference_sum_squares": 16, "candidate_sum_squares": 16, "difference_sum_squares": 0,
             "dot_product": 16, "max_absolute_difference": 0},
        ])
        self.assertEqual(actual["reference_l2"], 5)
        self.assertEqual(actual["candidate_l2"], 4)
        self.assertEqual(actual["relative_l2"], 0.6)
        self.assertEqual(actual["cosine_similarity"], 0.8)
        zero = {"reference_sum_squares": 0, "candidate_sum_squares": 0, "difference_sum_squares": 0,
                "dot_product": 0, "max_absolute_difference": 0}
        self.assertEqual(probe.finish_metrics(zero)["cosine_similarity"], 1)
        zero.update(candidate_sum_squares=1, difference_sum_squares=1, max_absolute_difference=1)
        self.assertIsNone(probe.finish_metrics(zero)["relative_l2"])
        self.assertEqual(probe.finish_metrics(zero)["cosine_similarity"], 0)

    def test_dominance_gate_requires_both_error_and_cosine_and_nonzero_reference_error(self):
        def records(all_rel, model_rel, all_cos=0.7, model_cos=0.8):
            return [{}, {"parameter_gradient_comparison": {"aggregate": {"relative_l2": all_rel, "cosine_similarity": all_cos}}},
                    {"parameter_gradient_comparison": {"aggregate": {"relative_l2": model_rel, "cosine_similarity": model_cos}}}]
        self.assertTrue(probe.loss_save_gate(records(0.2, 0.1))["passed"])
        self.assertFalse(probe.loss_save_gate(records(0.2, 0.10001))["passed"])
        self.assertFalse(probe.loss_save_gate(records(0.2, 0.1, 0.9, 0.8))["passed"])
        self.assertFalse(probe.loss_save_gate(records(0, 0))["passed"])
        self.assertFalse(probe.loss_save_gate(records(None, 0))["passed"])


@unittest.skipUnless(TORCH_AVAILABLE, "optional CPU PyTorch is not installed")
class HookBoundaryTests(unittest.TestCase):
    def model_and_tokens(self):
        import torch
        class TinyLM(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding = torch.nn.Embedding(300, 32)
                self.head = torch.nn.Linear(32, 300)
            def forward(self, input_ids, use_cache=False):
                return SimpleNamespace(logits=self.head(self.embedding(input_ids)))
        torch.manual_seed(7)
        model = TinyLM()
        tokens = (torch.arange(34).reshape(2, 17) * 7) % 300
        return model, tokens

    def test_analytic_ce_gradient_matches_independent_numpy_stable_softmax(self):
        import torch
        values = np.array([[[1000, 1001, 999], [-1002, -1000, -1001]],
                           [[2, -2, 0], [0, 0, 0]]], dtype=np.float32)
        labels = np.array([[1, 2], [0, 2]], dtype=np.int64)
        shifted = values.astype(np.float64) - values.max(axis=-1, keepdims=True)
        probabilities = np.exp(shifted) / np.exp(shifted).sum(axis=-1, keepdims=True)
        expected = probabilities.copy().reshape(-1, 3)
        expected[np.arange(4), labels.reshape(-1)] -= 1
        expected = expected.reshape(values.shape) / 4
        actual = probe.analytic_ce_gradient(torch.tensor(values), torch.tensor(labels)).numpy()
        np.testing.assert_allclose(actual, expected, rtol=2e-6, atol=2e-8)
        # Float32 softmax/subtraction need not retain an exactly zero row sum.
        # Half an ulp at one bounds this tiny four-row analytic control.
        np.testing.assert_allclose(actual.sum(axis=-1), 0, rtol=0, atol=np.finfo(np.float32).eps / 2)

    def test_model_only_hook_preserves_ce_gradient_while_all_saved_perturbs_it(self):
        import torch
        model, tokens = self.model_and_tokens()
        initial = probe.parameter_hash(model)
        records = [probe.backward_once(model, tokens, method) for method in probe.METHODS]
        self.assertEqual(len({r["logits_sha256"] for r in records}), 1)
        self.assertEqual(len({r["forward_loss"] for r in records}), 1)
        self.assertLess(records[0]["observed_vs_analytic_logits_gradient"]["relative_l2"], 1e-5)
        self.assertLess(records[2]["observed_vs_analytic_logits_gradient"]["relative_l2"], 1e-5)
        self.assertGreater(records[1]["observed_vs_analytic_logits_gradient"]["relative_l2"], 1e-4)
        # CE saves [32,300] tensors; the model-only context excludes them.
        def loss_shapes(record):
            return sum(item["saves"] for item in record["saved_tensor_inventory"]["shape_audit"]
                       if item["shape"] == [32, 300] and item["policy"] == "eligible")
        self.assertEqual(loss_shapes(records[1]), 2)
        self.assertEqual(loss_shapes(records[2]), 0)
        self.assertEqual(probe.parameter_hash(model), initial)
        self.assertTrue(all(torch.isfinite(p.grad).all() for p in model.parameters()))

    def test_repeated_backward_clears_accumulation_and_parameter_comparison_matches_numpy(self):
        model, tokens = self.model_and_tokens()
        probe.backward_once(model, tokens, "dense")
        refs = {name: parameter.grad.detach().clone() for name, parameter in model.named_parameters()}
        probe.backward_once(model, tokens, "dense")
        for name, parameter in model.named_parameters():
            self.assertEqual(probe.tensor_hash(refs[name]), probe.tensor_hash(parameter.grad))
        probe.backward_once(model, tokens, "model_saved_int8")
        actual = probe.parameter_comparison(model, refs)
        left = np.concatenate([refs[n].numpy().ravel().astype(np.float64) for n, _ in model.named_parameters()])
        right = np.concatenate([p.grad.numpy().ravel().astype(np.float64) for _, p in model.named_parameters()])
        self.assertAlmostEqual(actual["aggregate"]["relative_l2"], np.linalg.norm(right-left)/np.linalg.norm(left), places=12)
        self.assertAlmostEqual(actual["aggregate"]["cosine_similarity"], np.dot(left,right)/(np.linalg.norm(left)*np.linalg.norm(right)), places=12)
        self.assertEqual([r["name"] for r in actual["per_parameter"]], list(refs))


if __name__ == "__main__":
    unittest.main()
