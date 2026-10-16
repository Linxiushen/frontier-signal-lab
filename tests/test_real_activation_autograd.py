"""Independent forward/gradient checks and authenticated trace loading contracts."""
import copy
import importlib.util
import json
import io
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest import mock

import numpy as np

from experiments import real_activation_autograd_probe as probe

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


def write_fixture(directory):
    """Test-only small input; never described as a pretrained-model trace."""
    directory = Path(directory)
    bank = np.random.default_rng(6).normal(size=(3, 4, 5)).astype(np.float32)
    trace = directory / "trace.npz"
    np.savez(trace, bank=bank)
    config = {"fixture": "test-only", "shape": list(bank.shape)}
    manifest = {"schema_version": 1, "trace_file_sha256": probe.file_hash(trace),
                "bank_sha256": probe.bank_hash(bank), "bank_shape": list(bank.shape), "bank_dtype": "float32",
                "capture_config": config, "capture_config_sha256": probe.digest(config),
                "activation_boundary": "pre_block_residual", "source_text_sha256": "a" * 64,
                "token_ids_sha256": "b" * 64, "model_id": "test-only", "model_revision": "test-only"}
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return bank, trace, manifest_path, manifest


class TraceIntegrityTests(unittest.TestCase):
    def test_oversized_npy_header_rejected_before_array_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            _, trace, path, manifest = write_fixture(directory)
            header = io.BytesIO()
            np.lib.format.write_array_header_1_0(header, {
                "descr": "<f4", "fortran_order": False, "shape": (6, 2**30, 128)})
            with zipfile.ZipFile(trace, "w") as archive:
                archive.writestr("bank.npy", header.getvalue())
            manifest["trace_file_sha256"] = probe.file_hash(trace)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with mock.patch.object(probe.np, "load", side_effect=AssertionError("must not allocate")):
                with self.assertRaisesRegex(ValueError, "header shape/dtype"):
                    probe.load_trace(trace, path)

    def test_actual_file_bank_and_capture_config_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            bank, trace, path, manifest = write_fixture(directory)
            np.testing.assert_array_equal(probe.load_trace(trace, path)[0], bank)
            changed = bank.copy()
            changed[0, 0, 0] += 1
            np.savez(trace, bank=changed)
            with self.assertRaisesRegex(ValueError, "trace file hash"):
                probe.load_trace(trace, path)
            # Even if the container hash is updated, raw activation tampering fails.
            manifest["trace_file_sha256"] = probe.file_hash(trace)
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "raw bank hash"):
                probe.load_trace(trace, path)
            manifest["bank_sha256"] = probe.bank_hash(changed)
            manifest["capture_config"]["fixture"] = "changed"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "configuration hash"):
                probe.load_trace(trace, path)


@unittest.skipUnless(TORCH_AVAILABLE, "optional CPU PyTorch is not installed")
class AutogradContracts(unittest.TestCase):
    def test_dense_forward_matches_independent_numpy_and_passes_double_gradcheck(self):
        import torch
        bank = np.random.default_rng(4).normal(size=(3, 2, 4))
        query = np.array([0.2, -0.3, 0.1, 0.4])
        values = torch.tensor(bank, dtype=torch.float64, requires_grad=True)
        pseudoquery = torch.tensor(query, dtype=torch.float64, requires_grad=True)
        actual = probe.dense_mix(values, pseudoquery)
        np.testing.assert_allclose(actual.detach().numpy(), probe.numpy_mix(bank, query), rtol=1e-12, atol=1e-12)
        self.assertTrue(torch.autograd.gradcheck(probe.dense_mix, (values, pseudoquery),
                                                eps=1e-6, atol=1e-5, rtol=1e-4))

    def test_int8_repacks_each_step_included_in_total_and_uses_identity_surrogate(self):
        import torch
        bank = torch.tensor([[[0.0, 1.0, -0.3]], [[1.0, 0.1, -0.7]]], requires_grad=True)
        query = torch.tensor([0.2, -0.3, 0.1], requires_grad=True)
        original_pack = probe.pack_bank
        with mock.patch.object(probe, "pack_bank", wraps=original_pack) as pack:
            first, _, costs = probe.autograd_step(bank, query, "int8_identity_ste")
            self.assertEqual(pack.call_count, 1)
            first = first.detach().clone()
            self.assertGreater(costs["pack_wall_seconds"], 0)
            self.assertGreaterEqual(costs["forward_including_pack_and_loss_wall_seconds"], costs["pack_wall_seconds"])
            with torch.no_grad():
                bank[0, 0, 1] += 2
            second, _, _ = probe.autograd_step(bank, query, "int8_identity_ste")
            self.assertEqual(pack.call_count, 2)
            self.assertFalse(torch.allclose(first, second))
        codes, scales = original_pack(bank)
        self.assertFalse(scales.requires_grad)
        self.assertEqual(codes.dtype, torch.int8)
        # Identity STE's bank derivative equals the dense operator evaluated at
        # decoded values. This is explicitly a surrogate, not quantizer gradcheck.
        decoded = (bank + (codes.float() * scales - bank).detach()).detach().requires_grad_(True)
        other_query = query.detach().clone().requires_grad_(True)
        reference = probe.dense_mix(decoded, other_query)
        reference.square().mean().backward()
        np.testing.assert_allclose(bank.grad.numpy(), decoded.grad.numpy(), rtol=1e-6, atol=1e-7)
        np.testing.assert_allclose(query.grad.numpy(), other_query.grad.numpy(), rtol=1e-6, atol=1e-7)

    def test_saved_tensor_inventory_deduplicates_aliases_of_backing_storage(self):
        import torch
        values = torch.arange(12, dtype=torch.float32).reshape(3, 4)
        inventory = probe.SavedTensorInventory()
        inventory.pack(values)
        inventory.pack(values[:, :2])
        result = inventory.result()
        self.assertEqual(result["logical_saved_bytes_including_duplicate_saves"], (12 + 6) * 4)
        self.assertEqual(result["unique_backing_storage_bytes_including_saved_input_aliases"], 12 * 4)
        self.assertEqual(result["unique_backing_storage_count"], 1)

    def test_fresh_workers_report_real_peaks_finite_gradients_and_numpy_parity(self):
        with tempfile.TemporaryDirectory(prefix="activation-autograd-test-") as directory:
            _, trace, manifest, _ = write_fixture(directory)
            output = Path(directory) / "output"
            report = probe.run_probe(trace, manifest, output, seeds=(11,), warmup=0, repeats=1)
            workers = report["worker_measurements"]
            self.assertEqual(len(workers), 2)
            self.assertEqual(len({item["pid"] for item in workers}), 2)
            self.assertTrue(report["stable_results"]["all_dense_numpy_parity_passed"])
            for worker in workers:
                self.assertTrue(worker["all_outputs_and_gradients_finite"])
                self.assertEqual(worker["platform"]["torch_threads"], 1)
                self.assertGreater(worker["process_lifetime_peak_bytes"], 0)
                self.assertGreater(worker["saved_tensors"]["unique_backing_storage_bytes_including_saved_input_aliases"], 0)
                self.assertGreater(worker["timed_steps"][0]["backward_wall_seconds"], 0)
            changed = copy.deepcopy(report)
            observation_hash = changed.pop("observation_sha256")
            self.assertEqual(probe.digest(changed), observation_hash)
            self.assertEqual(probe.digest(changed["stable_results"]), changed["stable_result_sha256"])
            changed["worker_measurements"][0]["timed_steps"][0]["pack_wall_seconds"] += 1
            self.assertEqual(probe.digest(changed["stable_results"]), changed["stable_result_sha256"])
            self.assertNotEqual(probe.digest(changed), observation_hash)


if __name__ == "__main__":
    unittest.main()
