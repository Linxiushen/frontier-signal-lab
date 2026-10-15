"""Numerical and budget contract checks for the independent depth-bank probe."""

import unittest

import numpy as np

from experiments.attnres_budget_probe import (
    METHODS, budget_record, depth_logits, error_metrics, evaluate_method, full_mix,
    make_bank, make_query, nonuniform_blocks, quantize_vectors, run_probe,
)


class DepthMixTests(unittest.TestCase):
    def setUp(self):
        self.bank = make_bank(8, 5, 12, 42, "random")
        self.query = make_query(self.bank, 42, "fixed_random")

    def test_matches_independent_scalar_reference(self):
        actual = full_mix(self.bank, self.query)
        expected = np.zeros((5, 12), dtype=np.float64)
        for token in range(5):
            logits = []
            for depth in range(8):
                vector = self.bank[depth, token].astype(np.float64)
                key = vector / np.sqrt(np.mean(vector ** 2) + 1e-6)
                logits.append(sum(key[j] * self.query[token, j] for j in range(12)))
            weights = np.exp(np.array(logits) - max(logits))
            weights /= sum(weights)
            for depth in range(8):
                expected[token] += weights[depth] * self.bank[depth, token]
        np.testing.assert_allclose(actual, expected, rtol=2e-6, atol=2e-6)

    def test_temperature_divides_raw_logits(self):
        raw = depth_logits(self.bank, self.query)
        np.testing.assert_allclose(depth_logits(self.bank, self.query, 3.5), raw / 3.5)
        result = run_probe([3], 2, 4, [1], 2, temperature=2.0)
        self.assertEqual(result["config"]["temperature"], 2.0)
        self.assertIn("/ temperature", result["formula"])
        for temperature in (0, -1, float("nan"), float("inf")):
            with self.subTest(temperature=temperature), self.assertRaises(ValueError):
                run_probe([3], 2, 4, [1], 2, temperature=temperature)

    def test_fixed_random_query_is_shared_and_bank_independent(self):
        expected = np.broadcast_to(self.query[0], self.query.shape)
        np.testing.assert_array_equal(self.query, expected)
        np.testing.assert_array_equal(
            make_query(self.bank * 100, 42, "fixed_random"), self.query)

    def test_token_isolation_for_every_method(self):
        changed = self.bank.copy()
        changed[:, 3] += 100
        for method in METHODS:
            with self.subTest(method=method):
                original, _ = evaluate_method(self.bank, self.query, method, 3)
                modified, _ = evaluate_method(changed, self.query, method, 3)
                np.testing.assert_array_equal(original[[0, 1, 2, 4]], modified[[0, 1, 2, 4]])

    def test_single_depth_identity(self):
        bank = self.bank[:1]
        np.testing.assert_array_equal(full_mix(bank, self.query), bank[0])

    def test_full_budget_subsets_and_oracle_equal_full(self):
        reference = full_mix(self.bank, self.query)
        for method in ("full", "recent_subset", "stride_subset", "oracle_topk"):
            with self.subTest(method=method):
                actual, _ = evaluate_method(self.bank, self.query, method, 99)
                np.testing.assert_allclose(actual, reference, rtol=2e-6, atol=2e-6)

    def test_quantization_bound_and_mixing_error(self):
        packed, scales = quantize_vectors(self.bank)
        restored = packed.astype(np.float32) * scales
        self.assertEqual(packed.dtype, np.int8)
        self.assertEqual(scales.dtype, np.float32)
        self.assertTrue(np.all(np.abs(restored - self.bank) <= scales * 0.501 + 1e-7))
        candidate, _ = evaluate_method(self.bank, self.query, "int8", 3)
        metrics = error_metrics(full_mix(self.bank, self.query), candidate)
        self.assertLess(metrics["relative_l2"], 0.03)
        self.assertGreater(metrics["mean_token_cosine"], 0.999)

    def test_zero_bank_is_finite(self):
        zeros = np.zeros_like(self.bank)
        for method in METHODS:
            output, _ = evaluate_method(zeros, self.query, method, 3)
            np.testing.assert_array_equal(output, zeros[0])
            self.assertEqual(error_metrics(zeros[0], output)["mean_token_cosine"], 1.0)

    def test_costs_distinguish_selection_from_storage(self):
        for method in METHODS:
            _, costs = evaluate_method(self.bank, self.query, method, 3)
            scored = 8 if method in ("full", "int8", "oracle_topk") else 3
            self.assertEqual(costs["logit_evaluations"], scored * 5)
            if method == "int8":
                self.assertEqual(costs["logical_persistent_bank_bytes"], 8 * 5 * (12 + 4))
                self.assertEqual(costs["dequantization_temporary_bytes"], self.bank.nbytes)
            else:
                stored = 8 if method in ("full", "oracle_topk") else 3
                self.assertEqual(costs["logical_persistent_bank_bytes"], stored * 5 * 12 * 4)
                self.assertEqual(costs["dequantization_temporary_bytes"], 0)
        self.assertEqual(budget_record(8, 5, 12, 8)["logical_persistent_bank_bytes"], self.bank.nbytes)

    def test_logical_storage_matches_actual_retained_array_bytes(self):
        indices = np.linspace(0, 7, 3, dtype=np.int64)
        packed, scales = quantize_vectors(self.bank)
        retained = {
            "full": (self.bank,),
            "recent_subset": (self.bank[-3:].copy(),),
            "stride_subset": (self.bank[indices],),
            "block_sum": (np.stack([part.sum(axis=0) for part in np.array_split(self.bank, 3)]),),
            "nonuniform_block_sum": (np.stack([part.sum(axis=0) for part in nonuniform_blocks(self.bank, 3)]),),
            "int8": (packed, scales),
            "oracle_topk": (self.bank,),
        }
        for method, arrays in retained.items():
            with self.subTest(method=method):
                _, costs = evaluate_method(self.bank, self.query, method, 3)
                self.assertEqual(costs["logical_persistent_bank_bytes"], sum(a.nbytes for a in arrays))
        _, int8_costs = evaluate_method(self.bank, self.query, "int8", 3)
        self.assertEqual(int8_costs["dequantization_temporary_bytes"],
                         (packed.astype(np.float32) * scales).nbytes)

    def test_nonuniform_groups_preserve_every_vector(self):
        for count in (1, 3, 8):
            groups = nonuniform_blocks(self.bank, count)
            self.assertEqual(len(groups), count)
            self.assertTrue(all(len(group) > 0 for group in groups))
            self.assertGreaterEqual(len(groups[0]), len(groups[-1]))
            np.testing.assert_array_equal(np.concatenate(groups), self.bank)

    def test_seed_determinism_and_invalid_config(self):
        first = run_probe([3], 2, 4, [1], 2)
        self.assertEqual(first, run_probe([3], 2, 4, [1], 2))
        for args in [([], 2, 4, [1], 2), ([0], 2, 4, [1], 2),
                     ([3], 0, 4, [1], 2), ([3], 2, 4, [-1], 2),
                     ([3], 2, 4, [], 2), ([3], 2, 4, [1], 0)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                run_probe(*args)


if __name__ == "__main__":
    unittest.main()
