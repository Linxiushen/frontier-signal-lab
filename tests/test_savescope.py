"""Small CPU engineering checks for the reusable API; no model downloads."""
import json
import math
from pathlib import Path
import random
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from savescope import SaveScopeError, SavedTensorPolicy, audit

try:
    import numpy as np
    import torch
except ImportError:
    np = torch = None


class DependencyBoundaryTests(unittest.TestCase):
    def test_base_import_does_not_load_ml_libraries(self):
        result = subprocess.run([sys.executable, "-c",
            "import sys, savescope; assert 'torch' not in sys.modules; assert 'numpy' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipIf(torch is None, "optional Torch/NumPy dependencies unavailable")
class AuditEngineeringTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(19)
        np.random.seed(19)
        random.seed(19)

    def mlp(self):
        return torch.nn.Sequential(torch.nn.Linear(16, 32), torch.nn.GELU(),
                                   torch.nn.Dropout(.25), torch.nn.Linear(32, 16))

    def data(self):
        return torch.randn(2, 8, 16)

    def run_model(self, model, x=None, **kwargs):
        x = self.data() if x is None else x
        return audit(model, lambda m: m(x), lambda output: output.square().mean(), **kwargs)

    def transformer(self):
        class TinyTransformer(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.normalization = torch.nn.LayerNorm(16)
                self.attn = torch.nn.MultiheadAttention(16, 4, batch_first=True)
                self.attention_norm_fake = torch.nn.Identity()
                self.proj = torch.nn.Linear(16, 16)

            def forward(self, x):
                x = self.normalization(x)
                y, _ = self.attn(x, x, x, need_weights=False)
                return self.proj(self.normalization(x + y))
        return TinyTransformer()

    def snapshot(self, model):
        return {
            "tensors": [(t, t.detach().clone(), t.untyped_storage().data_ptr(), t._version)
                        for t in list(model.parameters()) + list(model.buffers())],
            "grads": [(p, p.requires_grad, p.grad, p.grad.clone() if p.grad is not None else None)
                      for p in model.parameters()],
            "modules": [(m, m.training, dict(m._parameters), dict(m._buffers), dict(m._modules),
                         m.__dict__.get("forward")) for m in model.modules()],
            "python": random.getstate(), "numpy": np.random.get_state(),
            "torch": torch.get_rng_state().clone(),
        }

    def assert_restored(self, model, state, *, versions=True):
        for t, value, ptr, version in state["tensors"]:
            self.assertTrue(torch.equal(t, value))
            self.assertEqual(t.untyped_storage().data_ptr(), ptr)
            if versions:
                self.assertEqual(t._version, version)
        for p, required, grad, value in state["grads"]:
            self.assertEqual(p.requires_grad, required)
            self.assertIs(p.grad, grad)
            if grad is not None:
                self.assertTrue(torch.equal(grad, value))
        for m, training, parameters, buffers, children, forward in state["modules"]:
            self.assertEqual(m.training, training)
            for actual, expected in ((m._parameters, parameters), (m._buffers, buffers), (m._modules, children)):
                self.assertEqual(list(actual), list(expected))
                for name in expected:
                    self.assertIs(actual[name], expected[name])
            self.assertIs(m.__dict__.get("forward"), forward)
        self.assertEqual(random.getstate(), state["python"])
        current = np.random.get_state()
        self.assertEqual(current[0], state["numpy"][0])
        self.assertTrue(np.array_equal(current[1], state["numpy"][1]))
        self.assertEqual(current[2:], state["numpy"][2:])
        self.assertTrue(torch.equal(torch.get_rng_state(), state["torch"]))

    def test_tiny_transformer_classes_repeated_calls_and_json(self):
        result = self.run_model(self.transformer())
        self.assertEqual(result["mode"], "executed")
        self.assertEqual([a["policy"] for a in result["arms"]], [p.value for p in SavedTensorPolicy])
        self.assertEqual(len(result["comparisons"]), 2)
        self.assertTrue(all(a["numerically_valid"] for a in result["arms"]))
        self.assertTrue(all(c["loss_matches_dense"] for c in result["comparisons"]))
        for arm in result["arms"]:
            modules = arm["inventory"]["sensitive_modules"]
            self.assertEqual(set(modules), {"normalization", "attn"})
            self.assertEqual(modules["normalization"]["calls"], 2)
            self.assertEqual(modules["attn"]["calls"], 1)
            self.assertGreater(arm["update"]["l2"], 0)
            self.assertTrue(arm["update"]["clone_storages_disjoint"])
            self.assertTrue(arm["update"]["independent_reference"]["all_parameter_and_moment_checks_passed"])
        baseline, compressed, kept = result["arms"]
        self.assertGreater(compressed["inventory"]["sensitive_modules"]["attn"]["counts"]["compressed_saves"], 0)
        self.assertNotIn("compressed_saves", kept["inventory"]["sensitive_modules"]["attn"]["counts"])
        self.assertEqual(baseline["inventory"]["logical_bytes"]["original_logical_saved_bytes"],
                         kept["inventory"]["logical_bytes"]["original_logical_saved_bytes"])
        json.dumps(result, allow_nan=False)

    def test_dense_gradients_match_direct_autograd_and_steps_use_clones(self):
        model, x = self.mlp().eval(), self.data()
        model(x).square().mean().backward()
        expected_norm = sum(float(p.grad.double().square().sum()) for p in model.parameters()) ** .5
        state = self.snapshot(model)
        original = torch.optim.AdamW
        seen = []

        def optimizer(parameters, **options):
            parameters = list(parameters)
            for q, p, direct in zip(parameters, model.parameters(), state["grads"]):
                self.assertIsNot(q, p)
                self.assertNotEqual(q.untyped_storage().data_ptr(), p.untyped_storage().data_ptr())
                self.assertIsNot(q.grad, p.grad)
                self.assertTrue(torch.equal(q.grad, p.grad))
                self.assertTrue(torch.equal(q.grad, direct[3]))
            seen.append(parameters)
            return original(parameters, **options)

        with patch.object(torch.optim, "AdamW", optimizer):
            result = self.run_model(model, x, policies=("dense",), optimizer_kwargs={"weight_decay": .03})
        self.assertEqual(len(seen), 1)
        # Equivalent FP64 norm reductions can differ by an ULP across platforms;
        # the gradients above must match the direct-autograd snapshot exactly.
        self.assertLessEqual(abs(result["arms"][0]["gradient"]["l2"] - expected_norm),
                             4 * math.ulp(expected_norm))
        controls = result["arms"][0]["update"]["independent_reference"]["per_parameter"]
        self.assertTrue(all(row["optimizer_step"] == 1 for row in controls))
        self.assert_restored(model, state)

    def test_callback_postprocessing_and_loss_stay_outside_hooks(self):
        model, x = self.mlp().eval(), self.data()
        basic = self.run_model(model, x)
        # Both callbacks save large operands for backward. Neither changes the
        # model-forward inventory now that hooks live inside actual forward.
        result = audit(model, lambda m: m(x).log_softmax(-1),
                       lambda output: output.softmax(-1).square().mean())
        for left, right in zip(basic["arms"], result["arms"]):
            self.assertEqual(left["inventory"], right["inventory"])

    def test_sensitive_child_used_after_root_forward_stays_outside_hooks(self):
        model, x = self.transformer(), self.data()
        basic = self.run_model(model, x)
        result = audit(model, lambda m: m.normalization(m(x)), lambda output: output.square().mean())
        for left, right in zip(basic["arms"], result["arms"]):
            self.assertEqual(left["inventory"], right["inventory"])

    def test_exact_custom_ancestor_and_root_are_selected_by_type(self):
        model = self.mlp().eval()
        result = self.run_model(model, exact_module_types=(torch.nn.Sequential,))
        kept = result["arms"][2]
        self.assertEqual(set(kept["inventory"]["sensitive_modules"]), {""})
        self.assertEqual(kept["inventory"]["sensitive_modules"][""]["calls"], 1)
        self.assertEqual(kept["inventory"]["other_forward"]["original_logical_saved_bytes"], 0)
        self.assertEqual(result["comparisons"][1]["gradient"]["relative_l2"], 0)
        self.assertEqual(result["comparisons"][1]["update"]["relative_l2"], 0)

    def test_parameter_and_buffer_storage_aliases_are_exact(self):
        class Aliases(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.weight = torch.nn.Parameter(torch.randn(16, 16))
                self.register_buffer("operand", torch.randn(16, 16))

            def forward(self, x):
                return (x @ self.weight.view(16, 16) + self.weight.view(16, 16).square()
                        + self.weight * self.operand.view(16, 16))
        result = self.run_model(Aliases(), torch.randn(16, 16))
        for arm in result["arms"]:
            self.assertGreaterEqual(arm["inventory"]["other_forward"]["counts"]["parameter_or_buffer_storage_excluded"], 2)

    def test_registered_state_grad_identity_modes_and_all_rng_restored(self):
        class Stateful(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.layer = torch.nn.Linear(16, 16)
                self.dropout = torch.nn.Dropout(.5)
                self.register_buffer("calls", torch.tensor(7, dtype=torch.int64))
                self.register_buffer("mean", torch.zeros(16))

            def forward(self, x):
                self.calls.add_(1)
                self.mean.copy_(x.mean((0, 1)))
                random.random()
                np.random.rand()
                return self.dropout(self.layer(x))
        model, x = Stateful(), self.data()
        model.layer.eval()
        model.layer.bias.requires_grad_(False)
        for parameter in model.parameters():
            parameter.grad = torch.randn_like(parameter)
        state = self.snapshot(model)
        result = self.run_model(model, x)
        self.assertTrue(all(c["loss_matches_dense"] for c in result["comparisons"]))
        self.assert_restored(model, state, versions=False)  # buffer updates advance their counters
        for parameter, _, _, version in state["tensors"][:2]:
            self.assertEqual(parameter._version, version)

    def test_original_instance_forward_and_exceptions_are_restored(self):
        for failure in ("forward", "loss"):
            with self.subTest(failure=failure):
                model, x = self.mlp(), self.data()
                inherited = model.forward

                def custom(value):
                    random.random()
                    np.random.rand()
                    torch.rand(1)
                    if failure == "forward":
                        raise RuntimeError("intentional callback failure")
                    return inherited(value)
                model.forward = custom
                state = self.snapshot(model)

                def loss(output):
                    raise RuntimeError("intentional callback failure")
                with self.assertRaisesRegex(RuntimeError, "intentional"):
                    audit(model, lambda m: m(x), loss)
                self.assert_restored(model, state)
        model = self.mlp()
        inherited = model.forward
        model.forward = lambda value: inherited(value)
        state = self.snapshot(model)
        self.run_model(model)
        # data() draws are external to audit; compare state after generating x.
        self.assertIs(model.forward, state["modules"][0][-1])

    def test_mutation_contract_errors_restore_original_model(self):
        for mutation in ("parameter", "registration", "mode", "requires_grad", "storage", "stride", "forward"):
            with self.subTest(mutation=mutation):
                model, x = self.mlp(), self.data()
                if mutation == "stride":
                    with torch.no_grad():
                        model[0].weight.zero_()
                state = self.snapshot(model)

                def forward(m):
                    output = m(x)
                    if mutation == "parameter":
                        with torch.no_grad():
                            m[0].weight.add_(1)
                    elif mutation == "registration":
                        m.register_buffer("unexpected", torch.ones(1))
                    elif mutation == "mode":
                        m.eval()
                    elif mutation == "requires_grad":
                        m[0].weight.requires_grad_(False)
                    elif mutation == "storage":
                        m[0].weight.data = m[0].weight.detach().clone()
                    elif mutation == "stride":
                        m[0].weight.data = m[0].weight.detach().as_strided(m[0].weight.shape, (1, 32))
                    else:
                        m.forward = lambda value: value
                    return output
                with self.assertRaises(SaveScopeError):
                    audit(model, forward, lambda output: output.square().mean())
                self.assert_restored(model, state, versions=False)

    def test_loss_cannot_reenter_audited_root_or_children(self):
        for use_child in (False, True):
            model, x = self.mlp(), self.data()
            state = self.snapshot(model)
            with self.assertRaisesRegex(SaveScopeError, "loss_fn must not call"):
                audit(model, lambda m: m(x), lambda output: (model[0](x) if use_child else model(x)).mean())
            self.assert_restored(model, state)

    def test_nested_audit_and_cross_thread_forward_rejected(self):
        model, x = self.mlp(), self.data()
        state = self.snapshot(model)
        with self.assertRaisesRegex(SaveScopeError, "nested or concurrent"):
            audit(model, lambda m: (m(x), self.run_model(m, x))[0], lambda output: output.square().mean())
        self.assert_restored(model, state)
        errors = []

        def callback(m):
            def worker():
                try:
                    m(x)
                except Exception as error:
                    errors.append(error)
            thread = threading.Thread(target=worker)
            thread.start()
            thread.join()
            if errors:
                raise errors[0]
        with self.assertRaisesRegex(SaveScopeError, "crossed the audit thread"):
            audit(model, callback, lambda output: output.mean())
        self.assert_restored(model, state)

    def test_unused_parameters_stay_unchanged_and_optimizer_skips_them(self):
        class Unused(torch.nn.Linear):
            def __init__(self):
                super().__init__(16, 16)
                self.unused = torch.nn.Parameter(torch.ones(16))
        result = self.run_model(Unused(), optimizer_kwargs={"weight_decay": .5})
        for arm in result["arms"]:
            self.assertEqual(arm["gradient"]["unused_parameters"], ["unused"])
            unused = next(row for row in arm["update"]["per_parameter"] if row["name"] == "unused")
            self.assertEqual(unused["l2"], 0)
            control = next(row for row in arm["update"]["independent_reference"]["per_parameter"] if row["name"] == "unused")
            self.assertEqual(control["optimizer_step"], 0)

    def test_nonfinite_loss_returns_invalid_json_and_restores_state(self):
        model, x = self.mlp(), self.data()
        state = self.snapshot(model)
        result = audit(model, lambda m: m(x), lambda output: output.mean() * float("nan"))
        self.assertTrue(all(not a["numerically_valid"] and not a["update"]["executed"] for a in result["arms"]))
        json.dumps(result, allow_nan=False)
        self.assert_restored(model, state)

    def test_independent_optimizer_controls_detect_tampered_native_output(self):
        original = torch.optim.AdamW
        for field in ("parameter", "exp_avg", "step"):
            with self.subTest(field=field):
                model, x = self.mlp(), self.data()
                state = self.snapshot(model)

                def optimizer(parameters, **options):
                    parameters = list(parameters)
                    result = original(parameters, **options)
                    step = result.step

                    def corrupted_step():
                        step()
                        if field == "parameter":
                            parameters[0].data.add_(1)
                        elif field == "step":
                            result.state[parameters[0]]["step"].add_(1)
                        else:
                            result.state[parameters[0]][field].add_(1)
                    result.step = corrupted_step
                    return result
                with patch.object(torch.optim, "AdamW", optimizer), self.assertRaisesRegex(SaveScopeError, "native AdamW"):
                    self.run_model(model, x, policies=("dense",))
                self.assert_restored(model, state)

    def test_nonfinite_native_update_marks_arm_invalid(self):
        model, x = self.mlp(), self.data()
        state = self.snapshot(model)
        original = torch.optim.AdamW

        def optimizer(parameters, **options):
            parameters = list(parameters)
            result = original(parameters, **options)
            step = result.step

            def overflowed_step():
                step()
                parameters[0].data.fill_(float("inf"))
            result.step = overflowed_step
            return result
        with patch.object(torch.optim, "AdamW", optimizer):
            result = self.run_model(model, x, policies=("dense",))
        self.assertFalse(result["arms"][0]["numerically_valid"])
        self.assertFalse(result["arms"][0]["update"]["finite"])
        json.dumps(result, allow_nan=False)
        self.assert_restored(model, state)

    def test_custom_betas_and_epsilon_pass_independent_moment_bounds(self):
        result = self.run_model(self.mlp(), optimizer_kwargs={"lr": .001, "betas": (.2, .7),
                                                            "eps": 1e-4, "weight_decay": .2})
        for arm in result["arms"]:
            self.assertTrue(arm["update"]["independent_reference"]["all_parameter_and_moment_checks_passed"])
        # With no selected sensitive class, both compressed policies are equal.
        self.assertEqual(result["arms"][1]["gradient"], result["arms"][2]["gradient"])
        self.assertEqual(result["arms"][1]["update"], result["arms"][2]["update"])

    def test_subnormal_saved_operand_uses_exact_fallback(self):
        value = torch.nextafter(torch.tensor(0., dtype=torch.float32), torch.tensor(1., dtype=torch.float32))
        x = torch.full((2, 8, 16), value)
        result = self.run_model(self.mlp(), x)
        for arm in result["arms"][1:]:
            self.assertGreater(arm["inventory"]["other_forward"]["counts"]["scale_underflow_exact_fallback"], 0)
            self.assertTrue(arm["numerically_valid"])

    def test_invalid_execution_contracts(self):
        model, x = self.mlp(), self.data()
        bad_options = ({"lr": -1}, {"eps": 0}, {"weight_decay": float("inf")},
                       {"betas": (1, .99)}, {"foreach": True})
        for options in bad_options:
            with self.subTest(options=options), self.assertRaises(SaveScopeError):
                self.run_model(model, x, optimizer_kwargs=options)
        for policies in ((), ("int8",), ("dense", "dense"), ("dense", "unknown")):
            with self.subTest(policies=policies), self.assertRaises(SaveScopeError):
                self.run_model(model, x, policies=policies)
        with self.assertRaises(SaveScopeError):
            self.run_model(model, x, exact_module_types=(str,))
        with self.assertRaisesRegex(SaveScopeError, "float32"):
            self.run_model(self.mlp().double(), x.double())
        with self.assertRaisesRegex(SaveScopeError, "trainable"):
            self.run_model(torch.nn.Identity(), x)
        with self.assertRaisesRegex(SaveScopeError, "supplied model"):
            audit(model, lambda m: m[0](x), lambda output: output.mean())
        for loss in (lambda output: output, lambda output: 1.0, lambda output: output.detach().mean()):
            with self.assertRaisesRegex(SaveScopeError, "differentiable scalar"):
                audit(model, lambda m: m(x), loss)
        with self.assertRaisesRegex(SaveScopeError, "CPU scalar"):
            audit(model, lambda m: m(x), lambda output: output.sum().to("meta"))
        with self.assertRaisesRegex(SaveScopeError, "finite"):
            with torch.no_grad():
                model[0].weight[0, 0] = float("nan")
            self.run_model(model, x)

    def test_preexisting_sparse_gradient_is_rejected_before_changes(self):
        model, x = self.mlp(), self.data()
        model[0].weight.grad = torch.sparse_coo_tensor(torch.tensor([[0], [0]]), torch.ones(1), model[0].weight.shape)
        grad = model[0].weight.grad
        with self.assertRaisesRegex(SaveScopeError, "pre-existing sparse"):
            self.run_model(model, x)
        self.assertIs(model[0].weight.grad, grad)
        self.assertNotIn("forward", model.__dict__)

    def test_distinct_parameters_with_shared_storage_are_rejected(self):
        model, x = self.mlp(), self.data()
        model.register_parameter("aliased_weight", torch.nn.Parameter(model[0].weight.detach()))
        with self.assertRaisesRegex(SaveScopeError, "sharing backing storage"):
            self.run_model(model, x)
        self.assertNotIn("forward", model.__dict__)


if __name__ == "__main__":
    unittest.main()
