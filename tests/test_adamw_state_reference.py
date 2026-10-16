"""Tiny CPU stateful-AdamW engineering tests; never load a model checkpoint."""
import importlib.util
import json
import unittest
from unittest.mock import patch

import numpy as np

from experiments import adamw_state_reference as ref

TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None


@unittest.skipUnless(TORCH_AVAILABLE, "optional CPU Torch is unavailable")
class StatefulAdamWTests(unittest.TestCase):
    def setUp(self):
        self.torch = ref.require_torch()
        self.torch.set_num_threads(1)

    def parameter(self):
        torch = self.torch
        p = torch.nn.Parameter(torch.tensor([1., -2., 0., .125, -.5], dtype=torch.float32))
        p.grad = torch.tensor([0., 1e-12, -1e-8, 1e-4, -2.], dtype=torch.float32)
        return p

    def warmed(self):
        p = self.parameter()
        named = [("weight", p)]
        optimizer = ref.make_optimizer(named)
        optimizer.state[p] = {
            "exp_avg": self.torch.tensor([.05, -.1, .2, -.04, .5], dtype=self.torch.float32),
            "exp_avg_sq": self.torch.tensor([.03, .01, .5, .005, 2.], dtype=self.torch.float32),
            "step": self.torch.tensor(4., dtype=self.torch.float32)}
        return named, optimizer

    def snapshot_sources(self, named, states):
        tensors = [v for _, p in named for v in (p, p.grad)]
        tensors += [row[key] for row in states.values() for key in ("exp_avg", "exp_avg_sq")]
        return [(value, value.clone(), value.untyped_storage().data_ptr(), value._version) for value in tensors]

    def assert_sources(self, saved):
        for value, expected, pointer, version in saved:
            self.assertTrue(self.torch.equal(value, expected))
            self.assertEqual(value.untyped_storage().data_ptr(), pointer)
            self.assertEqual(value._version, version)

    def test_nonzero_step4_to5_matches_independent_reference(self):
        named, optimizer = self.warmed()
        inputs = ref.capture_step_inputs(named, optimizer)
        p = named[0][1]
        expected = ref.numpy_adamw_step(inputs["weight"]["parameter"].numpy(), p.grad.numpy(),
            exp_avg=inputs["weight"]["exp_avg"].numpy(), exp_avg_sq=inputs["weight"]["exp_avg_sq"].numpy(), step=4)
        optimizer.step()
        checked = ref.check_native_step(inputs, named, optimizer)
        self.assertTrue(checked["all_checks_passed"])
        receipt = checked["per_parameter"][0]
        self.assertEqual((receipt["input_step"], receipt["optimizer_step"]), (4, 5))
        self.assertEqual(receipt["input_sha256"]["exp_avg"], ref.tensor_hash(inputs["weight"]["exp_avg"]))
        np.testing.assert_allclose(p.detach().numpy(), expected["parameter"], rtol=2e-7, atol=1e-8)
        np.testing.assert_allclose(optimizer.state[p]["exp_avg"].numpy(), expected["exp_avg"], rtol=2e-7, atol=1e-8)
        json.dumps(checked, allow_nan=False)

    def test_fresh_absent_state_is_zero_without_mutation_then_step1(self):
        p = self.parameter()
        named = [("weight", p)]
        optimizer = ref.make_optimizer(named)
        inputs = ref.capture_step_inputs(named, optimizer)
        frozen = ref.freeze_optimizer_state(named, optimizer)
        self.assertFalse(optimizer.state)
        self.assertEqual(inputs["weight"]["step"], 0)
        self.assertFalse(bool(inputs["weight"]["exp_avg"].any()))
        self.assertFalse(bool(frozen["weight"]["exp_avg_sq"].any()))
        optimizer.step()
        checked = ref.check_native_step(inputs, named, optimizer)
        self.assertEqual(checked["per_parameter"][0]["optimizer_step"], 1)
        clone, _ = ref.clone_step(named, None)
        self.assertEqual(clone["input_steps"], {"weight": 0})
        self.assertEqual(clone["optimizer_steps"], {"weight": 1})

    def test_disjoint_clones_include_every_step_tensor_and_preserve_sources(self):
        named, optimizer = self.warmed()
        second = self.parameter()
        named.append(("second", second))
        optimizer = ref.make_optimizer(named)
        for _, p in named:
            optimizer.state[p] = {"exp_avg": self.torch.full_like(p, .05),
                                  "exp_avg_sq": self.torch.full_like(p, .01),
                                  "step": self.torch.tensor(4., dtype=self.torch.float32)}
        states = ref.freeze_optimizer_state(named, optimizer)
        saved = self.snapshot_sources(named, states)
        original_state_hash = ref.state_hash(named, optimizer)
        original_frozen_hash = ref.frozen_state_hash(states)
        original = ref.make_optimizer
        captured = []

        def capture(clones):
            clones = list(clones)
            result = original(clones)
            captured.append((clones, result))
            return result

        with patch.object(ref, "make_optimizer", capture):
            record, dense = ref.clone_step(named, states)
        clones, cloned_optimizer = captured[0]
        source_ptrs = {value.untyped_storage().data_ptr() for value, _, _, _ in saved}
        pointers = []
        for (_, p), (_, q) in zip(named, clones):
            values = [q, q.grad, *cloned_optimizer.state[q].values()]
            for value in values:
                pointer = value.untyped_storage().data_ptr()
                self.assertNotIn(pointer, source_ptrs)
                self.assertNotIn(pointer, pointers)
                pointers.append(pointer)
            self.assertTrue(self.torch.equal(dense[next(n for n,v in named if v is p)], q.detach() - p.detach()))
        self.assertEqual(len(pointers), 10)
        self.assertTrue(record["clone_storages_disjoint"])
        self.assertTrue(record["sources_unchanged"])
        self.assertEqual(record["update_comparison"]["aggregate"]["relative_l2"], 0.)
        self.assertEqual(ref.state_hash(named, optimizer), original_state_hash)
        self.assertEqual(ref.frozen_state_hash(states), original_frozen_hash)
        self.assert_sources(saved)
        repeated, _ = ref.clone_step(named, states, dense)
        self.assertEqual(record, repeated)

    def test_state_hash_excludes_gradient_and_frozen_hash_excludes_theta(self):
        named, optimizer = self.warmed()
        p = named[0][1]
        before = ref.state_hash(named, optimizer)
        frozen = ref.freeze_optimizer_state(named, optimizer)
        frozen_before = ref.frozen_state_hash(frozen)
        p.grad.fill_(3)
        self.assertEqual(ref.state_hash(named, optimizer), before)
        with self.torch.no_grad():
            p.add_(.2)
        self.assertNotEqual(ref.state_hash(named, optimizer), before)
        self.assertEqual(ref.frozen_state_hash(frozen), frozen_before)
        frozen["weight"]["exp_avg"].add_(.1)
        self.assertNotEqual(ref.frozen_state_hash(frozen), frozen_before)

    def test_input_scale_bound_handles_near_zero_moment_cancellation(self):
        torch = self.torch
        p = torch.nn.Parameter(torch.tensor([0., .25], dtype=torch.float32))
        p.grad = torch.tensor([-9., 1e-20], dtype=torch.float32)
        named = [("weight", p)]
        optimizer = ref.make_optimizer(named)
        optimizer.state[p] = {"exp_avg": torch.tensor([1., 0.], dtype=torch.float32),
                              "exp_avg_sq": torch.tensor([1., 1e-30], dtype=torch.float32),
                              "step": torch.tensor(4., dtype=torch.float32)}
        inputs = ref.capture_step_inputs(named, optimizer)
        optimizer.step()
        result = ref.check_native_step(inputs, named, optimizer)
        self.assertTrue(result["all_checks_passed"])
        # The result nearly cancels. Relative-to-result tolerance would reject
        # ordinary float32 lerp rounding; the declared input-scale bound passes.
        expected = .9 * inputs["weight"]["exp_avg"].double().numpy() + (1 - .9) * p.grad.double().numpy()
        actual = optimizer.state[p]["exp_avg"].double().numpy()
        naive = 8 * np.finfo(np.float32).eps * np.abs(expected) + 8 * np.finfo(np.float32).tiny
        self.assertTrue(np.any(np.abs(actual - expected) > naive))

    def test_parameter_interval_encloses_interior_moment_points(self):
        theta = np.array([0., .1, -1.])
        mean, square = np.array([0., -.2, .3]), np.array([1e-40, .01, .2])
        mtol, vtol = np.array([1e-20, 1e-6, 2e-6]), np.array([1e-38, 1e-7, 2e-7])
        lower, upper, enlargement = ref._parameter_interval(theta, mean, square, mtol, vtol, 5)
        for m_fraction in (-.9, 0., .7):
            for v_fraction in (-.8, .2, .95):
                m = mean + m_fraction * mtol
                v = np.maximum(0., square + v_fraction * vtol)
                actual = theta * (1 - 1e-6) - 1e-4 * (m / (1 - .9 ** 5)) / (np.sqrt(v / (1 - .999 ** 5)) + 1e-8)
                self.assertTrue(np.all(lower <= actual) and np.all(actual <= upper))
        self.assertTrue(np.all(enlargement > 0))

    def test_counter_bias_correction_and_tampered_native_outputs_rejected(self):
        for error in ("step", "bias_correction", "parameter", "exp_avg", "exp_avg_sq"):
            with self.subTest(error=error):
                named, optimizer = self.warmed()
                inputs = ref.capture_step_inputs(named, optimizer)
                p = named[0][1]
                optimizer.step()
                state = optimizer.state[p]
                if error == "step":
                    state["step"].add_(1)
                elif error == "bias_correction":
                    wrong = inputs["weight"]["parameter"].double().numpy() * (1 - 1e-6) - 1e-4 * (
                        state["exp_avg"].double().numpy() / (1 - .9)) / (np.sqrt(state["exp_avg_sq"].double().numpy() / (1 - .999)) + 1e-8)
                    p.data.copy_(self.torch.from_numpy(wrong).float())
                elif error == "parameter":
                    p.data.add_(.01)
                else:
                    state[error].add_(.01)
                with self.assertRaises(ValueError):
                    ref.check_native_step(inputs, named, optimizer)

    def test_wrong_coupled_decay_and_epsilon_placement_rejected(self):
        for error in ("coupled_decay", "epsilon"):
            with self.subTest(error=error):
                p = self.parameter()
                named = [("weight", p)]
                optimizer = ref.make_optimizer(named)
                inputs = ref.capture_step_inputs(named, optimizer)
                theta, gradient = inputs["weight"]["parameter"].double().numpy(), p.grad.double().numpy()
                optimizer.step()
                if error == "coupled_decay":
                    coupled = gradient + .01 * theta
                    wrong = theta - 1e-4 * coupled / (np.abs(coupled) + 1e-8)
                else:
                    wrong = theta * (1 - 1e-6) - 1e-4 * gradient / np.sqrt(gradient * gradient + 1e-8)
                p.data.copy_(self.torch.from_numpy(wrong).float())
                with self.assertRaisesRegex(ValueError, "parameter"):
                    ref.check_native_step(inputs, named, optimizer)

    def test_missing_nonfinite_and_wrong_dtype_gradients_rejected(self):
        torch = self.torch
        for dtype, gradient in ((torch.float32, None), (torch.float32, float("nan")), (torch.float64, 1.)):
            p = torch.nn.Parameter(torch.tensor([1.], dtype=dtype))
            if gradient is not None:
                p.grad = torch.tensor([gradient], dtype=dtype)
            with self.subTest(dtype=dtype, gradient=gradient):
                if dtype == torch.float64:
                    with self.assertRaises(ValueError):
                        ref.make_optimizer([("weight", p)])
                else:
                    optimizer = ref.make_optimizer([("weight", p)])
                    with self.assertRaises(ValueError):
                        ref.capture_step_inputs([("weight", p)], optimizer)
                with self.assertRaises(ValueError):
                    ref.clone_step([("weight", p)], None)

    def test_incomplete_wrong_dtype_shape_negative_or_nonfinite_state_rejected(self):
        for error in ("missing", "dtype", "shape", "negative", "nonfinite", "fractional_step", "step_dtype", "step_zero_nonzero_moment", "alias"):
            with self.subTest(error=error):
                named, optimizer = self.warmed()
                p = named[0][1]
                state = optimizer.state[p]
                if error == "missing":
                    del state["exp_avg"]
                elif error == "dtype":
                    state["exp_avg"] = state["exp_avg"].double()
                elif error == "shape":
                    state["exp_avg"] = state["exp_avg"][:2].clone()
                elif error == "negative":
                    state["exp_avg_sq"][0] = -1
                elif error == "nonfinite":
                    state["exp_avg"][0] = float("inf")
                elif error == "fractional_step":
                    state["step"].fill_(4.5)
                elif error == "step_dtype":
                    state["step"] = state["step"].double()
                elif error == "step_zero_nonzero_moment":
                    state["step"].zero_()
                else:
                    state["exp_avg"] = p.grad
                with self.assertRaises(ValueError):
                    ref.capture_step_inputs(named, optimizer)

    def test_frozen_state_and_dense_delta_references_are_strict(self):
        named, optimizer = self.warmed()
        states = ref.freeze_optimizer_state(named, optimizer)
        for invalid in ({}, {"other": states["weight"]}, {"weight": {"step": 4}},
                        {"weight": {**states["weight"], "step": 4.0}}):
            with self.subTest(invalid=str(invalid)[:80]), self.assertRaises(ValueError):
                ref.clone_step(named, invalid)
        aliased = {"weight": {**states["weight"], "exp_avg": named[0][1].grad}}
        with self.assertRaisesRegex(ValueError, "alias"):
            ref.clone_step(named, aliased)
        with self.assertRaisesRegex(ValueError, "reference names"):
            ref.clone_step(named, states, {})
        record, dense = ref.clone_step(named, states)
        named[0][1].grad.mul_(-1)
        changed, returned = ref.clone_step(named, states, dense)
        self.assertIs(returned, dense)
        self.assertGreater(changed["update_comparison"]["aggregate"]["difference_l2"], 0)
        self.assertNotEqual(changed["update_comparison"]["per_parameter"][0]["candidate_update_sha256"],
                            ref.tensor_hash(named[0][1]))

    def test_optimizer_configuration_and_input_snapshot_aliases_rejected(self):
        named, optimizer = self.warmed()
        optimizer.param_groups[0]["weight_decay"] = .2
        with self.assertRaisesRegex(ValueError, "configuration"):
            ref.capture_step_inputs(named, optimizer)
        named, optimizer = self.warmed()
        inputs = ref.capture_step_inputs(named, optimizer)
        optimizer.step()
        inputs["weight"]["exp_avg"] = optimizer.state[named[0][1]]["exp_avg"]
        with self.assertRaises(ValueError):
            ref.check_native_step(inputs, named, optimizer)


if __name__ == "__main__":
    unittest.main()
