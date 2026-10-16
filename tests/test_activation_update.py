"""Independent AdamW equations, native step controls, and falsifiable update gates."""
import importlib.util
import unittest

import numpy as np

from experiments import activation_update_probe as probe

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


class ReferenceAndGateTests(unittest.TestCase):
    def test_first_step_reference_includes_decoupled_decay_and_epsilon(self):
        theta = np.array([1., -2., 0., .125, -.5])
        gradient = np.array([0., 1e-12, -1e-8, 1e-4, -2.])
        result = probe.numpy_adamw_step(theta, gradient)
        expected = theta * (1 - 1e-4 * .01) - 1e-4 * gradient / (np.abs(gradient) + 1e-8)
        np.testing.assert_allclose(result["parameter"], expected, rtol=1e-14, atol=1e-16)
        np.testing.assert_allclose(result["exp_avg"], .1 * gradient, rtol=1e-14)
        np.testing.assert_allclose(result["exp_avg_sq"], .001 * gradient ** 2, rtol=1e-14)
        self.assertEqual(result["step"], 1)
        with self.assertRaises(ValueError):
            probe.numpy_adamw_step(theta, np.array([np.nan] * 5))
        with self.assertRaises(ValueError):
            probe.numpy_adamw_step(theta, gradient, exp_avg_sq=-np.ones(5))

    def test_gate_requires_all_three_conditions_and_valid_denominator(self):
        def records(a=.5, b=.05, ca=.7, cb=.999):
            return [{}, {"update_comparison": {"aggregate": {"relative_l2": a, "cosine_similarity": ca}}},
                    {"update_comparison": {"aggregate": {"relative_l2": b, "cosine_similarity": cb}}}]
        self.assertTrue(probe.update_fidelity_gate(records())["passed"])
        for kwargs in ({"b": .11}, {"cb": .98}, {"a": .06}, {"a": 0.}, {"a": None},
                       {"a": float("inf")}, {"a": 1e-320, "b": 1e300}, {"ca": .9999}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(probe.update_fidelity_gate(records(**kwargs))["passed"])
        # Low raw weight error cannot substitute for actual update direction.
        bad = probe.update_metrics(np.array([1e-4, -1e-4]), np.array([-1e-4, 1e-4]))
        self.assertEqual(bad["cosine_similarity"], -1.)
        self.assertEqual(bad["relative_l2"], 2.)


@unittest.skipUnless(TORCH_AVAILABLE, "optional CPU Torch is unavailable")
class NativeAdamWTests(unittest.TestCase):
    def test_actual_clone_step_matches_reference_and_preserves_originals(self):
        torch = probe.require_torch()
        p = torch.nn.Parameter(torch.tensor([1., -2., 0., .125, -.5], dtype=torch.float32))
        p.grad = torch.tensor([0., 1e-12, -1e-8, 1e-4, -2.], dtype=torch.float32)
        before, gradient = p.detach().clone(), p.grad.clone()
        record, dense = probe.adamw_step_clones([("weight", p)])
        self.assertTrue(torch.equal(p, before))
        self.assertTrue(torch.equal(p.grad, gradient))
        self.assertTrue(record["clone_storages_disjoint"])
        self.assertTrue(record["numpy_all_parameter_and_moment_checks_passed"])
        self.assertEqual(record["update_comparison"]["aggregate"]["relative_l2"], 0.)
        second, _ = probe.adamw_step_clones([("weight", p)], dense)
        self.assertEqual(record, second)

    def test_none_gradient_skips_while_zero_gradient_decays_and_advances(self):
        torch = probe.require_torch()
        absent = torch.nn.Parameter(torch.tensor([1., -2.], dtype=torch.float32))
        zero = torch.nn.Parameter(absent.detach().clone())
        zero.grad = torch.zeros_like(zero)
        optimizer = torch.optim.AdamW([absent, zero], lr=1e-4, betas=(.9, .999), eps=1e-8,
                                     weight_decay=.01, foreach=False, fused=False)
        original = absent.detach().numpy().copy()
        optimizer.step()
        self.assertTrue(torch.equal(absent, torch.tensor(original)))
        self.assertNotIn(absent, optimizer.state)
        self.assertEqual(float(optimizer.state[zero]["step"]), 1.)
        expected = probe.numpy_adamw_step(original, np.zeros(2))
        probe.reference_bound(zero.detach().numpy(), expected["parameter"], original)
        skipped = probe.numpy_adamw_step(original, None)
        np.testing.assert_array_equal(skipped["parameter"], original)
        self.assertEqual(skipped["step"], 0)

    def test_reference_detects_coupled_decay_and_wrong_epsilon_placement(self):
        torch = probe.require_torch()
        theta = np.array([1., -2., 0., .125, -.5], dtype=np.float32)
        gradient = np.array([0., 1e-12, -1e-8, 1e-4, -2.], dtype=np.float32)
        reference = probe.numpy_adamw_step(theta, gradient)
        p = torch.nn.Parameter(torch.from_numpy(theta.copy()))
        p.grad = torch.from_numpy(gradient.copy())
        record, _ = probe.adamw_step_clones([("weight", p)])
        self.assertTrue(record["numpy_all_parameter_and_moment_checks_passed"])
        coupled_g = gradient.astype(np.float64) + .01 * theta
        coupled = theta - 1e-4 * coupled_g / (np.abs(coupled_g) + 1e-8)
        with self.assertRaises(ValueError):
            probe.reference_bound(coupled, reference["parameter"], theta)
        wrong_epsilon = theta * (1 - 1e-6) - 1e-4 * gradient / np.sqrt(gradient ** 2 + 1e-8)
        with self.assertRaises(ValueError):
            probe.reference_bound(wrong_epsilon, reference["parameter"], theta)

    def test_clone_api_rejects_incomplete_nonfinite_or_wrong_dtype_gradients(self):
        torch = probe.require_torch()
        for dtype, gradient in [(torch.float32, None), (torch.float32, float("nan")), (torch.float64, 1.)]:
            p = torch.nn.Parameter(torch.tensor([1.], dtype=dtype))
            if gradient is not None:
                p.grad = torch.tensor([gradient], dtype=dtype)
            with self.subTest(dtype=dtype, gradient=gradient), self.assertRaises(ValueError):
                probe.adamw_step_clones([("weight", p)])


if __name__ == "__main__":
    unittest.main()
