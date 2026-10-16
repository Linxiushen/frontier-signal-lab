"""LayerNorm save isolation: independent VJP, identical baseline, safe restoration."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from experiments import activation_norm_gradient_probe as probe
from experiments import activation_gradient_probe as previous

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


class ProtocolAndGateTests(unittest.TestCase):
    def test_protocol_requires_source_data_and_exact_module_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            data, manifest, protocol = [directory / name for name in ("data", "manifest", "protocol")]
            data.write_bytes(b"data")
            manifest.write_bytes(b"manifest")
            value = {"schema_version": 1, "config": probe.preset_config(),
                     "config_sha256": probe.digest(probe.preset_config()), "data_sha256": probe.file_hash(data),
                     "training_manifest_sha256": probe.file_hash(manifest),
                     "source_files_sha256": {name: probe.file_hash(probe.ROOT / name) for name in probe.SOURCE_PATHS}}
            protocol.write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(probe.validate_protocol(protocol, data, manifest), value)
            for mutation, message in (("scope", "preset"), ("source", "execution source"), ("data", "data/manifest")):
                altered = copy.deepcopy(value)
                if mutation == "scope":
                    altered["config"]["expected_named_layernorm_modules"] = 12
                    altered["config_sha256"] = probe.digest(altered["config"])
                elif mutation == "source":
                    altered["source_files_sha256"][probe.SOURCE_PATHS[0]] = "0" * 64
                else:
                    altered["data_sha256"] = "0" * 64
                protocol.write_text(json.dumps(altered), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    probe.validate_protocol(protocol, data, manifest)

    def test_gate_keeps_failed_and_degenerate_outcomes(self):
        def records(base, exact, before=0.7, after=0.8):
            return [{}, {"parameter_gradient_comparison": {"aggregate": {"relative_l2": base, "cosine_similarity": before}}},
                    {"parameter_gradient_comparison": {"aggregate": {"relative_l2": exact, "cosine_similarity": after}}}]
        self.assertTrue(probe.norm_save_gate(records(4, 2))["passed"])
        self.assertFalse(probe.norm_save_gate(records(4, 2.0001))["passed"])
        self.assertFalse(probe.norm_save_gate(records(4, 1, 0.9, 0.8))["passed"])
        self.assertFalse(probe.norm_save_gate(records(0, 0))["passed"])
        self.assertIsNone(probe.norm_save_gate(records(None, 0))["norm_preserved_to_model_saved_relative_l2_ratio"])


@unittest.skipUnless(TORCH_AVAILABLE, "optional CPU PyTorch is not installed")
class LayerNormSaveTests(unittest.TestCase):
    def tiny_model(self):
        import torch
        class TinyLM(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding = torch.nn.Embedding(300, 64)
                self.norm = torch.nn.LayerNorm(64)
                self.head = torch.nn.Linear(64, 300)
            def forward(self, input_ids, use_cache=False):
                return SimpleNamespace(logits=self.head(self.norm(self.embedding(input_ids))))
        torch.manual_seed(19)
        return TinyLM(), (torch.arange(34).reshape(2, 17) * 7) % 300

    def test_exact_layernorm_identity_saves_match_independent_numpy_vjp(self):
        import torch
        generator = np.random.default_rng(23)
        x = generator.normal(size=(8, 64)).astype(np.float32)
        gamma = generator.uniform(0.3, 1.2, size=64).astype(np.float32)
        beta = generator.normal(size=64).astype(np.float32)
        upstream = generator.normal(size=x.shape).astype(np.float32)
        module = torch.nn.LayerNorm(64, eps=1e-5)
        with torch.no_grad():
            module.weight.copy_(torch.tensor(gamma))
            module.bias.copy_(torch.tensor(beta))
        inputs = torch.tensor(x, requires_grad=True)
        outer = probe.SavedActivationCodec(list(module.parameters()), "int8_saved_tensors")
        with torch.autograd.graph.saved_tensors_hooks(outer.pack, outer.unpack):
            with probe.named_layernorm_hooks(module, list(module.parameters()), "dense") as records:
                output = module(inputs)
        output.backward(torch.tensor(upstream))
        values = x.astype(np.float64)
        centered = values - values.mean(axis=-1, keepdims=True)
        invstd = 1 / np.sqrt(np.mean(centered**2, axis=-1, keepdims=True) + 1e-5)
        xhat = centered * invstd
        scaled = upstream.astype(np.float64) * gamma
        dx = invstd * (scaled - scaled.mean(axis=-1, keepdims=True)
                      - xhat * (scaled*xhat).mean(axis=-1, keepdims=True))
        np.testing.assert_allclose(output.detach().numpy(), xhat*gamma+beta, rtol=2e-5, atol=2e-6)
        np.testing.assert_allclose(inputs.grad.numpy(), dx, rtol=3e-5, atol=3e-6)
        np.testing.assert_allclose(module.weight.grad.numpy(), (upstream*xhat).sum(axis=0), rtol=3e-5, atol=3e-6)
        np.testing.assert_allclose(module.bias.grad.numpy(), upstream.sum(axis=0), rtol=3e-5, atol=3e-6)
        self.assertEqual(outer.inventory()["counts"].get("save_calls", 0), 0)
        self.assertGreater(records[""]["codec"].inventory()["counts"]["eligible"], 0)
        self.assertEqual(records[""]["codec"].inventory()["counts"].get("compressed_saves", 0), 0)

    def test_wrapped_baselines_match_prior_unsplit_saved_policy_exactly(self):
        model, tokens = self.tiny_model()
        initial = probe.parameter_hash(model)
        for method in ("dense", "model_saved_int8"):
            prior = previous.backward_once(model, tokens, method)
            gradients = {n: probe.tensor_hash(p.grad) for n,p in model.named_parameters()}
            actual = probe.backward_once(model, tokens, method)
            self.assertEqual(prior["logits_sha256"], actual["logits_sha256"])
            self.assertEqual(prior["forward_loss"], actual["forward_loss"])
            self.assertEqual(gradients, {n: probe.tensor_hash(p.grad) for n,p in model.named_parameters()})
            probe.validate_norm_coverage(actual, ["norm"], method)
        preserved = probe.backward_once(model, tokens, "model_except_norm_saved_int8")
        probe.validate_norm_coverage(preserved, ["norm"], "model_except_norm_saved_int8")
        self.assertEqual(preserved["logits_sha256"], actual["logits_sha256"])
        self.assertLess(preserved["observed_vs_analytic_logits_gradient"]["relative_l2"], 1e-5)
        self.assertEqual(probe.parameter_hash(model), initial)

    def test_instance_forward_restored_for_success_and_exception(self):
        import torch
        model, tokens = self.tiny_model()
        self.assertNotIn("forward", model.norm.__dict__)
        original = model.norm.forward
        with probe.named_layernorm_hooks(model, list(model.parameters()), "dense"):
            model(input_ids=tokens[:, :-1])
        self.assertNotIn("forward", model.norm.__dict__)
        self.assertEqual(model.norm.forward, original)
        # Preserve an actual pre-existing instance-level callable by identity.
        custom = lambda inputs: original(inputs)
        model.norm.forward = custom
        with self.assertRaisesRegex(RuntimeError, "after forward"):
            with probe.named_layernorm_hooks(model, list(model.parameters()), "dense"):
                model(input_ids=tokens[:, :-1])
                raise RuntimeError("after forward")
        self.assertIs(model.norm.__dict__["forward"], custom)
        failing = lambda inputs: (_ for _ in ()).throw(RuntimeError("inside norm"))
        model.norm.forward = failing
        with self.assertRaisesRegex(RuntimeError, "inside norm"):
            with probe.named_layernorm_hooks(model, list(model.parameters()), "dense"):
                model(input_ids=tokens[:, :-1])
        self.assertIs(model.norm.__dict__["forward"], failing)

    def test_preserved_layernorm_repeated_backward_clears_accumulation(self):
        model, tokens = self.tiny_model()
        first = probe.backward_once(model, tokens, "model_except_norm_saved_int8")
        reference = {name: parameter.grad.detach().clone() for name,parameter in model.named_parameters()}
        second = probe.backward_once(model, tokens, "model_except_norm_saved_int8")
        self.assertEqual(first["logits_gradient_sha256"], second["logits_gradient_sha256"])
        comparison = probe.parameter_comparison(model, reference)
        self.assertEqual(comparison["aggregate"]["difference_sum_squares"], 0)
        corrupted = copy.deepcopy(second)
        corrupted["named_layernorm_saves"]["norm"]["calls"] = 0
        with self.assertRaisesRegex(ValueError, "called/saved"):
            probe.validate_norm_coverage(corrupted, ["norm"], "model_except_norm_saved_int8")


if __name__ == "__main__":
    unittest.main()
