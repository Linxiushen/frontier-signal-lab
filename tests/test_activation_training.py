"""Independent contracts for backward-only saved-activation compression."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from experiments import activation_training_probe as probe

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


class DatasetAndScheduleTests(unittest.TestCase):
    def test_valid_pinned_assets_reject_unpinned_loader_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(b"{}")
            pins = {"config.json": (2, probe.file_hash(path))}
            with mock.patch.object(probe, "PINNED_ASSETS", pins):
                probe.verify_model_assets(directory)
                (Path(directory) / "adapter_config.json").write_bytes(b"{}")
                with self.assertRaisesRegex(ValueError, "unpinned loader override"):
                    probe.verify_model_assets(directory)

    def test_hash_tampering_and_identical_holdout_blocks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "data.json"
            manifest = Path(directory) / "manifest.json"
            payload = {"schema_version": 1, "train": [list(range(65)) for _ in range(8)],
                       "holdout": [list(range(65, 130)) for _ in range(8)]}
            data.write_text(json.dumps(payload), encoding="utf-8")
            record = {"data_sha256": probe.file_hash(data), "model_id": probe.MODEL_ID,
                      "model_revision": probe.MODEL_REVISION, "train_source_sha256": "a" * 64,
                      "holdout_source_sha256": "b" * 64, "tokenizer_sha256": probe.PINNED_ASSETS["tokenizer.json"][1]}
            manifest.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(probe.load_data(data, manifest)[0]["train"].shape, (8, 65))
            payload["holdout"][0] = payload["train"][0]
            data.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "file hash"):
                probe.load_data(data, manifest)
            record["data_sha256"] = probe.file_hash(data)
            manifest.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identical train/holdout"):
                probe.load_data(data, manifest)

    def test_schedule_preserves_each_epoch_budget_and_pairing(self):
        schedule = probe.batch_schedule(8, 24, 2, 11)
        self.assertEqual(schedule, probe.batch_schedule(8, 24, 2, 11))
        self.assertNotEqual(schedule, probe.batch_schedule(8, 24, 2, 29))
        flat = [index for batch in schedule for index in batch]
        self.assertEqual(len(flat), 48)
        for start in range(0, 48, 8):
            self.assertEqual(sorted(flat[start:start + 8]), list(range(8)))


@unittest.skipUnless(TORCH_AVAILABLE, "optional CPU PyTorch is not installed")
class SavedCompressionTests(unittest.TestCase):
    def test_parameter_aliases_excluded_and_quantized_payload_does_not_retain_original(self):
        import torch
        parameter = torch.nn.Parameter(torch.arange(512, dtype=torch.float32).reshape(16, 32))
        codec = probe.SavedActivationCodec([parameter], "int8_saved_tensors")
        alias = parameter.t()
        exact = codec.pack(alias)
        self.assertIsInstance(exact, torch.Tensor)
        self.assertEqual(probe.storage_key(exact), probe.storage_key(parameter))
        activation = torch.linspace(-1.1, 2.3, 512).reshape(16, 32)
        codes, scales = codec.pack(activation)
        self.assertEqual(codes.dtype, torch.int8)
        self.assertFalse(scales.requires_grad)
        self.assertNotEqual(probe.storage_key(codes), probe.storage_key(activation))
        decoded = codec.unpack((codes, scales))
        self.assertGreater(float((decoded - activation).abs().max()), 0)
        self.assertLessEqual(float((decoded - activation).abs().max()), float(scales.max()) / 2 + 1e-6)
        inventory = codec.inventory()
        self.assertEqual(inventory["counts"]["parameter_storage_excluded"], 1)
        self.assertEqual(inventory["counts"]["compressed_saves"], 1)
        self.assertEqual(inventory["retained_activation_storage_union_bytes"], 512 + 16 * 4)

    def test_backward_matches_independent_quantized_saved_inputs_and_forward_stays_dense(self):
        import torch
        torch.manual_seed(2)
        inputs = torch.randn(8, 32, requires_grad=True)
        weight = torch.nn.Parameter(torch.randn(16, 32))
        codec = probe.SavedActivationCodec([weight], "int8_saved_tensors")
        with torch.autograd.graph.saved_tensors_hooks(codec.pack, codec.unpack):
            output = inputs @ weight.t()
        expected_output = inputs.detach() @ weight.detach().t()
        self.assertTrue(torch.equal(output.detach(), expected_output))
        upstream = torch.randn_like(output)
        output.backward(upstream)
        # Independent NumPy quantization of the input saved by matmul.
        array = inputs.detach().numpy()
        scale = np.max(np.abs(array), axis=-1, keepdims=True) / 127
        scale = np.where(scale == 0, 1, scale)
        decoded = np.clip(np.rint(array / scale), -127, 127).astype(np.int8).astype(np.float32) * scale
        np.testing.assert_allclose(weight.grad.numpy(), upstream.numpy().T @ decoded, rtol=1e-5, atol=1e-5)
        # Weight-backed save is exact, so the input gradient remains exact here.
        np.testing.assert_allclose(inputs.grad.numpy(), upstream.numpy() @ weight.detach().numpy(), rtol=1e-5, atol=1e-5)

    def test_true_next_token_targets_and_full_parameter_optimizer_updates(self):
        import torch
        class TinyLM(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embedding = torch.nn.Embedding(9, 16)
                self.head = torch.nn.Linear(16, 9)
            def forward(self, input_ids, use_cache=False):
                self.last_inputs = input_ids.detach().clone()
                return SimpleNamespace(logits=self.head(self.embedding(input_ids)))
        model = TinyLM()
        tokens = torch.tensor([[1, 2, 3, 4], [5, 6, 7, 8]])
        actual = probe.next_token_loss(model, tokens)
        logits = model(tokens[:, :-1]).logits
        expected = torch.nn.functional.cross_entropy(logits.reshape(-1, 9), tokens[:, 1:].reshape(-1))
        self.assertTrue(torch.equal(actual, expected))
        self.assertTrue(torch.equal(model.last_inputs, tokens[:, :-1]))
        before = probe.parameter_hash(model)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0, foreach=False)
        record = probe.train_step(model, optimizer, tokens, "int8_saved_tensors")
        self.assertNotEqual(before, probe.parameter_hash(model))
        self.assertEqual(record["parameter_elements_with_finite_gradients"], sum(value.numel() for value in model.parameters()))
        self.assertGreater(record["parameter_gradient_l2"], 0)
        self.assertTrue(all(value.grad is not None and torch.isfinite(value.grad).all() for value in model.parameters()))


if __name__ == "__main__":
    unittest.main()
