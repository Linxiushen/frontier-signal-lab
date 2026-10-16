"""Actual attention save isolation: independent VJP and unchanged baselines."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from experiments import activation_attention_gradient_probe as probe
from experiments import activation_norm_gradient_probe as previous

ATTENTION_AVAILABLE = (importlib.util.find_spec("torch") is not None
                       and importlib.util.find_spec("transformers") is not None)


class ProtocolAndGateTests(unittest.TestCase):
    def test_protocol_requires_source_data_and_exact_attention_scope(self):
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
                    altered["config"]["expected_named_attention_modules"] = 5
                    altered["config_sha256"] = probe.digest(altered["config"])
                elif mutation == "source":
                    altered["source_files_sha256"][probe.SOURCE_PATHS[0]] = "0" * 64
                else:
                    altered["data_sha256"] = "0" * 64
                protocol.write_text(json.dumps(altered), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    probe.validate_protocol(protocol, data, manifest)

    def test_gate_keeps_failure_and_nonfinite_degenerate_controls(self):
        def records(base, exact, before=0.7, after=0.8):
            return [{}, {"parameter_gradient_comparison": {"aggregate": {"relative_l2": base, "cosine_similarity": before}}},
                    {"parameter_gradient_comparison": {"aggregate": {"relative_l2": exact, "cosine_similarity": after}}}]
        self.assertTrue(probe.attention_save_gate(records(4, 2))["passed"])
        self.assertTrue(probe.attention_save_gate(records(4, 0))["passed"])
        self.assertFalse(probe.attention_save_gate(records(4, 2.0001))["passed"])
        self.assertFalse(probe.attention_save_gate(records(4, 1, 0.9, 0.8))["passed"])
        for base, exact in ((0, 0), (None, 0), (4, None), (float("inf"), 1),
                            (float("nan"), 1), (4, float("inf")), (4, float("nan")),
                            (-1, 0), (4, -1), (1e-308, 1e308)):
            gate = probe.attention_save_gate(records(base, exact))
            self.assertFalse(gate["passed"])
            self.assertIsNone(gate["attention_preserved_to_norm_only_relative_l2_ratio"])
        for before, after in ((None, 1), (0.5, None), (float("nan"), 1), (0.5, float("inf"))):
            self.assertFalse(probe.attention_save_gate(records(4, 1, before, after))["passed"])


@unittest.skipUnless(ATTENTION_AVAILABLE, "optional CPU PyTorch/Transformers are not installed")
class AttentionSaveTests(unittest.TestCase):
    def config(self):
        from transformers.models.gpt_neox.configuration_gpt_neox import GPTNeoXConfig
        config = GPTNeoXConfig(hidden_size=64, num_attention_heads=2, num_hidden_layers=1,
                               intermediate_size=128, max_position_embeddings=32,
                               attention_dropout=0.0, hidden_dropout=0.0, attention_bias=True,
                               rotary_pct=0.25)
        config._attn_implementation = "eager"
        return config

    def mask_and_positions(self, length, rotary_dims):
        import torch
        mask = torch.triu(torch.full((length, length), torch.finfo(torch.float32).min), diagonal=1)
        cos = torch.ones(1, length, rotary_dims)
        return mask[None, None], (cos, torch.zeros_like(cos))

    def tiny_model(self):
        import torch
        config = self.config()
        cls = probe.attention_type()
        masks = self.mask_and_positions
        class TinyLM(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding = torch.nn.Embedding(300, 64)
                self.norm = torch.nn.LayerNorm(64)
                self.block = cls(config, layer_idx=0)  # Deliberately not named "attention".
                self.attention = torch.nn.Identity()  # A name alone must not select this.
                self.head = torch.nn.Linear(64, 300)
            def forward(self, input_ids, use_cache=False):
                hidden = self.norm(self.embedding(input_ids))
                mask, positions = masks(input_ids.shape[-1], self.block.rotary_ndims)
                output, _ = self.block(hidden, attention_mask=mask, position_embeddings=positions)
                return SimpleNamespace(logits=self.head(output))
        torch.manual_seed(19)
        return TinyLM().eval(), (torch.arange(18).reshape(2, 9) * 7) % 300

    def test_actual_attention_matches_independent_numpy_causal_forward_and_vjp(self):
        import torch
        generator = np.random.default_rng(23)
        module = probe.attention_type()(self.config(), layer_idx=0).eval()
        with torch.no_grad():
            for parameter in module.parameters():
                values = generator.normal(0, 0.08, size=tuple(parameter.shape)).astype(np.float32)
                parameter.copy_(torch.from_numpy(values))
        x = generator.normal(0, 0.7, size=(2, 8, 64)).astype(np.float32)
        upstream = generator.normal(0, 0.4, size=x.shape).astype(np.float32)
        inputs = torch.tensor(x, requires_grad=True)
        mask, positions = self.mask_and_positions(8, module.rotary_ndims)
        parameters = list(module.parameters())
        outer = probe.SavedActivationCodec(parameters, "int8_saved_tensors")
        with torch.autograd.graph.saved_tensors_hooks(outer.pack, outer.unpack):
            with probe.named_attention_hooks(module, parameters, "dense") as records:
                actual, actual_probabilities = module(inputs, attention_mask=mask, position_embeddings=positions)
        actual.backward(torch.tensor(upstream))

        # Independent float64 algebra. Identity RoPE is explicit: cos=1, sin=0.
        arrays = {name: value.detach().numpy().astype(np.float64) for name, value in module.named_parameters()}
        values, dy = x.astype(np.float64), upstream.astype(np.float64)
        wqkv, bqkv = arrays["query_key_value.weight"], arrays["query_key_value.bias"]
        wo, bo = arrays["dense.weight"], arrays["dense.bias"]
        batch, length, hidden = values.shape
        heads, width = 2, hidden // 2
        # GPTNeoX packs QKV within each head, not three complete head banks.
        packed = (values @ wqkv.T + bqkv).reshape(batch, length, heads, 3 * width).transpose(0, 2, 1, 3)
        q, k, v = np.split(packed, 3, axis=-1)
        scores = (q @ k.swapaxes(-1, -2)) / np.sqrt(width)
        causal = np.arange(length)[:, None] >= np.arange(length)[None, :]
        scores = np.where(causal, scores, -np.inf)
        exponentials = np.exp(scores - scores.max(axis=-1, keepdims=True))
        probabilities = exponentials / exponentials.sum(axis=-1, keepdims=True)
        attended = probabilities @ v
        joined = attended.transpose(0, 2, 1, 3).reshape(batch, length, hidden)
        expected = joined @ wo.T + bo

        djoined = dy @ wo
        dattended = djoined.reshape(batch, length, heads, width).transpose(0, 2, 1, 3)
        dv = probabilities.swapaxes(-1, -2) @ dattended
        dp = dattended @ v.swapaxes(-1, -2)
        ds = probabilities * (dp - (dp * probabilities).sum(axis=-1, keepdims=True))
        dq = (ds @ k) / np.sqrt(width)
        dk = (ds.swapaxes(-1, -2) @ q) / np.sqrt(width)
        dpacked = np.concatenate((dq, dk, dv), axis=-1).transpose(0, 2, 1, 3).reshape(batch, length, 3 * hidden)
        expected_gradients = {
            "query_key_value.weight": dpacked.reshape(-1, 3 * hidden).T @ values.reshape(-1, hidden),
            "query_key_value.bias": dpacked.sum(axis=(0, 1)),
            "dense.weight": dy.reshape(-1, hidden).T @ joined.reshape(-1, hidden),
            "dense.bias": dy.sum(axis=(0, 1)),
        }
        np.testing.assert_allclose(actual.detach().numpy(), expected, rtol=2e-5, atol=2e-6)
        np.testing.assert_allclose(actual_probabilities.detach().numpy(), probabilities, rtol=2e-5, atol=2e-6)
        np.testing.assert_allclose(inputs.grad.numpy(), dpacked @ wqkv, rtol=3e-5, atol=3e-6)
        for name, parameter in module.named_parameters():
            np.testing.assert_allclose(parameter.grad.numpy(), expected_gradients[name], rtol=3e-5, atol=3e-6)
        self.assertEqual(outer.inventory()["counts"].get("save_calls", 0), 0)
        probe.validate_attention_coverage({"named_attention_saves": probe.attention_inventory(records)},
                                          [""], "model_except_norm_attention_saved_int8")

    def test_wrapped_actual_class_baselines_match_prior_norm_policy_exactly(self):
        model, tokens = self.tiny_model()
        initial = probe.parameter_hash(model)
        for method in ("dense", "model_except_norm_saved_int8"):
            prior = previous.backward_once(model, tokens, method)
            gradients = {name: probe.tensor_hash(p.grad) for name, p in model.named_parameters()}
            actual = probe.backward_once(model, tokens, method)
            self.assertEqual(prior["logits_sha256"], actual["logits_sha256"])
            self.assertEqual(prior["forward_loss"], actual["forward_loss"])
            self.assertEqual(prior["logits_gradient_sha256"], actual["logits_gradient_sha256"])
            self.assertEqual(gradients, {name: probe.tensor_hash(p.grad) for name, p in model.named_parameters()})
            probe.validate_norm_coverage(actual, ["norm"], method)
            probe.validate_attention_coverage(actual, ["block"], method)
        treatment = probe.backward_once(model, tokens, "model_except_norm_attention_saved_int8")
        probe.validate_norm_coverage(treatment, ["norm"], "model_except_norm_attention_saved_int8")
        probe.validate_attention_coverage(treatment, ["block"], "model_except_norm_attention_saved_int8")
        self.assertEqual(treatment["logits_sha256"], actual["logits_sha256"])
        self.assertLess(treatment["observed_vs_analytic_logits_gradient"]["relative_l2"], 1e-5)
        self.assertEqual(probe.parameter_hash(model), initial)

    def test_instance_forward_restored_after_success_and_inside_outside_failure(self):
        model, tokens = self.tiny_model()
        parameters = list(model.parameters())
        self.assertNotIn("forward", model.block.__dict__)
        original = model.block.forward
        with probe.named_attention_hooks(model, parameters, "dense") as records:
            model(input_ids=tokens[:, :-1])
        self.assertEqual(list(records), ["block"])
        self.assertNotIn("forward", model.block.__dict__)
        self.assertEqual(model.block.forward, original)
        custom = lambda *args, **kwargs: original(*args, **kwargs)
        model.block.forward = custom
        with self.assertRaisesRegex(RuntimeError, "after forward"):
            with probe.named_attention_hooks(model, parameters, "dense"):
                model(input_ids=tokens[:, :-1])
                raise RuntimeError("after forward")
        self.assertIs(model.block.__dict__["forward"], custom)
        failing = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("inside attention"))
        model.block.forward = failing
        with self.assertRaisesRegex(RuntimeError, "inside attention"):
            with probe.named_attention_hooks(model, parameters, "dense"):
                model(input_ids=tokens[:, :-1])
        self.assertIs(model.block.__dict__["forward"], failing)

    def test_repeated_backward_clears_accumulation_and_rejects_bad_coverage(self):
        model, tokens = self.tiny_model()
        method = "model_except_norm_attention_saved_int8"
        first = probe.backward_once(model, tokens, method)
        reference = {name: p.grad.detach().clone() for name, p in model.named_parameters()}
        second = probe.backward_once(model, tokens, method)
        self.assertEqual(first["logits_gradient_sha256"], second["logits_gradient_sha256"])
        self.assertEqual(probe.parameter_comparison(model, reference)["aggregate"]["difference_sum_squares"], 0)
        for field, value, message in (("calls", 0, "one forward"), ("module_class", "torch.nn.Linear", "actual attention class")):
            corrupted = copy.deepcopy(second)
            corrupted["named_attention_saves"]["block"][field] = value
            with self.assertRaisesRegex(ValueError, message):
                probe.validate_attention_coverage(corrupted, ["block"], method)
        with self.assertRaisesRegex(ValueError, "names/order"):
            probe.validate_attention_coverage(second, ["attention"], method)


if __name__ == "__main__":
    unittest.main()
