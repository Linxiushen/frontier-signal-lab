"""Native CPU correctness controls for caller-state SaveScope diagnostics.

These tiny unit/integration checks are not a training-quality experiment.
"""
import copy
import json
import unittest

from savescope import SaveScopeError, audit
from savescope.optimizer_state import snapshot_adamw

try:
    import numpy as np
    import torch
except ImportError:
    np = torch = None


@unittest.skipIf(torch is None, "optional Torch/NumPy dependencies unavailable")
class AdamWStateTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(71)

    def fixture(self, *, reordered=False):
        class Tiny(torch.nn.Module):
            def __init__(self):
                super().__init__()
                for name, offset in (("a", .1), ("b", .3), ("c", -.2), ("lazy", .6)):
                    self.register_parameter(name, torch.nn.Parameter(torch.arange(4, dtype=torch.float32)/9+offset))

            def forward(self, x):
                return self.a*x + self.c*x.square() + self.lazy

        model = Tiny()
        params = list(model.parameters())
        optimizer = torch.optim.AdamW(params[::-1] if reordered else params,
            lr=.013, betas=(.6, .8), eps=1e-5, weight_decay=.07,
            foreach=False, fused=False)
        # Actual native warm-up yields unequal counters and one lazy state.
        for step in range(3):
            for i, (name, p) in enumerate(model.named_parameters()):
                p.grad = torch.full_like(p, (i+1)*.11 + step*.04) if (
                    name == "a" or (name == "b" and step == 0) or (name == "c" and step < 2)) else None
            optimizer.step()
        return model, optimizer

    def gradients(self, model):
        present = {name: name != "b" for name, _ in model.named_parameters()}
        gradients = [(name, torch.full_like(p, (i+1)*-.09))
                     for i, (name, p) in enumerate(model.named_parameters())]
        return gradients, present

    def capture_state(self, model, optimizer):
        # Parameter deepcopy omits .grad; retain its caller object and value
        # separately so this oracle actually checks existing-grad restoration.
        gradients = {name: (p.grad, None if p.grad is None else p.grad.detach().clone())
                     for name, p in model.named_parameters()}
        return copy.deepcopy((model, optimizer)), gradients

    def assert_state_same(self, model, optimizer, snapshot):
        (old_model, old_optimizer), gradients = snapshot
        for (name, p), (other, q) in zip(model.named_parameters(), old_model.named_parameters()):
            self.assertEqual(name, other)
            self.assertTrue(torch.equal(p, q))
            old_grad, old_value = gradients[name]
            self.assertIs(p.grad, old_grad)
            if p.grad is not None:
                self.assertTrue(torch.equal(p.grad, old_value))
            a, b = optimizer.state.get(p, {}), old_optimizer.state.get(q, {})
            self.assertEqual(set(a), set(b))
            for key in a:
                self.assertTrue(torch.equal(a[key], b[key]), (name, key))

    def test_accumulated_transition_matches_separate_native_clone_and_keeps_caller(self):
        model, optimizer = self.fixture(reordered=True)
        original = self.capture_state(model, optimizer)
        reference, native = copy.deepcopy((model, optimizer))
        gradients, present = self.gradients(model)
        before = {name: p.detach().clone() for name, p in reference.named_parameters()}
        for (name, p), (_, g) in zip(reference.named_parameters(), gradients):
            p.grad = g.clone() if present[name] else None
        native.step()
        captured = snapshot_adamw(torch, list(model.named_parameters()), optimizer)
        result, updates = captured.step(torch, np, list(model.named_parameters()), gradients, present)
        for (name, update), (_, p) in zip(updates, reference.named_parameters()):
            self.assertTrue(torch.equal(update, p.detach()-before[name]))
        rows = result["independent_reference"]["per_parameter"]
        self.assertEqual([r["optimizer_step_before"] for r in rows], [3, 1, 2, 0])
        self.assertEqual([r["optimizer_step"] for r in rows], [4, 1, 3, 1])
        self.assertTrue(all(r[k]["passed"] for r in rows for k in ("parameter", "exp_avg", "exp_avg_sq")))
        self.assertTrue(result["clone_storages_disjoint"])
        captured.assert_unchanged()
        self.assert_state_same(model, optimizer, original)
        json.dumps(result, allow_nan=False)
        json.dumps(captured.receipt, allow_nan=False)

    def test_fresh_reset_is_a_negative_control(self):
        model, optimizer = self.fixture()
        gradients, present = self.gradients(model)
        captured = snapshot_adamw(torch, list(model.named_parameters()), optimizer)
        _, updates = captured.step(torch, np, list(model.named_parameters()), gradients, present)
        fresh = [torch.nn.Parameter(p.detach().clone()) for p in model.parameters()]
        fresh_optimizer = torch.optim.AdamW(fresh, **captured.options, foreach=False, fused=False)
        before = [p.detach().clone() for p in fresh]
        for (name, g), p in zip(gradients, fresh):
            p.grad = g.clone() if present[name] else None
        fresh_optimizer.step()
        self.assertFalse(torch.equal(updates[0][1], fresh[0].detach()-before[0]))

    def test_audit_dense_arm_matches_native_current_state(self):
        model, optimizer = self.fixture()
        reference, native = copy.deepcopy((model, optimizer))
        initial = self.capture_state(model, optimizer)
        x = torch.tensor([.2, -.4, .7, 1.1])
        before = {name: p.detach().clone() for name, p in reference.named_parameters()}
        native.zero_grad(set_to_none=True)
        reference(x).square().mean().backward()
        native.step()
        result = audit(model, lambda m: m(x), lambda out: out.square().mean(),
                       policies=("dense", "int8"), optimizer=optimizer)
        from savescope.audit import _hash_tensor
        actual = result["arms"][0]["update"]["per_parameter"]
        for row, (name, p) in zip(actual, reference.named_parameters()):
            self.assertEqual(row["name"], name)
            self.assertEqual(row["sha256"], _hash_tensor(p.detach()-before[name]))
        self.assertIn("captured caller", result["optimizer"]["initial_state"])
        self.assert_state_same(model, optimizer, initial)

    def test_explicit_empty_lazy_and_unused_state_remain_unchanged(self):
        model, optimizer = self.fixture()
        optimizer.state[model.lazy] = {}
        captured = snapshot_adamw(torch, list(model.named_parameters()), optimizer)
        gradients, present = self.gradients(model)
        present["lazy"] = False
        result, updates = captured.step(torch, np, list(model.named_parameters()), gradients, present)
        captured.assert_unchanged()
        self.assertEqual(optimizer.state[model.lazy], {})
        self.assertEqual(result["independent_reference"]["per_parameter"][-1]["optimizer_step"], 0)
        self.assertEqual(torch.count_nonzero(updates[-1][1]), 0)

    def test_native_default_foreach_and_fused_none_are_supported(self):
        model = torch.nn.Linear(2, 1)
        optimizer = torch.optim.AdamW(model.parameters())
        snapshot_adamw(torch, list(model.named_parameters()), optimizer).assert_unchanged()

    def test_invalid_state_refuses_before_forward(self):
        mutations = [
            lambda m, o: o.state[m.a].update(exp_avg=torch.zeros(3)),
            lambda m, o: o.state[m.a].update(exp_avg=torch.zeros(4, dtype=torch.float64)),
            lambda m, o: o.state[m.a]["exp_avg"].fill_(float("nan")),
            lambda m, o: o.state[m.a]["exp_avg_sq"].fill_(-1),
            lambda m, o: o.state[m.a].update(extra=torch.zeros(4)),
            lambda m, o: o.state[m.a].pop("exp_avg"),
            lambda m, o: o.state[m.a].update(step=torch.tensor([3.])),
            lambda m, o: o.state[m.a].update(step=torch.tensor(3, dtype=torch.int64)),
            lambda m, o: o.state[m.a].update(step=torch.tensor(1.5)),
            lambda m, o: o.state[m.a].update(step=torch.tensor(-1.)),
            lambda m, o: o.state[m.a].update(step=torch.tensor(float("inf"))),
            lambda m, o: o.state[m.a].update(step=torch.tensor(float(2**24))),
            lambda m, o: o.state[m.a].update(step=torch.tensor(0.)),
            lambda m, o: o.state.update({m.lazy: None}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                model, optimizer = self.fixture()
                mutate(model, optimizer)
                called = []
                with self.assertRaises(SaveScopeError):
                    audit(model, lambda m: called.append(True) or m(torch.ones(4)),
                          lambda out: out.sum(), optimizer=optimizer)
                self.assertEqual(called, [])

    def test_group_identity_flags_extra_state_and_subclass_refuse(self):
        changes = [
            lambda m, o: o.param_groups[0]["params"].append(m.a),
            lambda m, o: o.param_groups[0]["params"].pop(),
            lambda m, o: o.param_groups[0]["params"].__setitem__(0, torch.nn.Parameter(torch.zeros(4))),
            lambda m, o: o.state.update({torch.nn.Parameter(torch.zeros(4)): {}}),
            lambda m, o: o.param_groups.append(dict(o.param_groups[0])),
            lambda m, o: o.param_groups[0].update(foreach=True),
            lambda m, o: o.param_groups[0].update(fused=True),
            lambda m, o: o.param_groups[0].update(maximize=True),
            lambda m, o: o.param_groups[0].update(amsgrad=True),
            lambda m, o: o.param_groups[0].update(capturable=True),
            lambda m, o: o.param_groups[0].update(differentiable=True),
            lambda m, o: o.param_groups[0].update(decoupled_weight_decay=False),
            lambda m, o: o.param_groups[0].update(unknown_option=1),
            lambda m, o: setattr(o, "step", lambda: None),
        ]
        for mutate in changes:
            with self.subTest(mutation=mutate):
                model, optimizer = self.fixture()
                mutate(model, optimizer)
                with self.assertRaises(SaveScopeError):
                    snapshot_adamw(torch, list(model.named_parameters()), optimizer)
        class Derived(torch.optim.AdamW):
            pass
        model = torch.nn.Linear(2, 1)
        with self.assertRaises(SaveScopeError):
            snapshot_adamw(torch, list(model.named_parameters()), Derived(model.parameters()))

    def test_parameter_and_cross_state_aliases_refuse(self):
        for field in ("parameter", "gradient", "state"):
            with self.subTest(field=field):
                model, optimizer = self.fixture()
                optimizer.state[model.a]["exp_avg"] = {
                    "parameter": model.a.detach(), "gradient": model.a.grad,
                    "state": optimizer.state[model.c]["exp_avg"],
                }[field]
                with self.assertRaisesRegex(SaveScopeError, "aliases"):
                    snapshot_adamw(torch, list(model.named_parameters()), optimizer)

    def test_step_hooks_refuse_including_global_hooks(self):
        from torch.optim.optimizer import register_optimizer_step_pre_hook
        model, optimizer = self.fixture()
        for handle in (optimizer.register_step_pre_hook(lambda *args: None),):
            try:
                with self.assertRaisesRegex(SaveScopeError, "hooks"):
                    snapshot_adamw(torch, list(model.named_parameters()), optimizer)
            finally:
                handle.remove()
        handle = register_optimizer_step_pre_hook(lambda *args: None)
        try:
            with self.assertRaisesRegex(SaveScopeError, "hooks"):
                snapshot_adamw(torch, list(model.named_parameters()), optimizer)
        finally:
            handle.remove()

    def test_buffer_and_frozen_parameter_aliases_refuse_before_forward(self):
        for kind in ("buffer", "frozen"):
            with self.subTest(kind=kind):
                model, optimizer = self.fixture()
                if kind == "buffer":
                    model.register_buffer("protected", torch.ones_like(model.a))
                else:
                    model.register_parameter("protected", torch.nn.Parameter(torch.ones_like(model.a), requires_grad=False))
                optimizer.state[model.a]["exp_avg"] = model.protected.detach()
                called = []
                with self.assertRaisesRegex(SaveScopeError, "aliases"):
                    audit(model, lambda m: called.append(True) or m(torch.ones(4)),
                          lambda out: out.sum(), optimizer=optimizer)
                self.assertEqual(called, [])

    def test_callback_optimizer_mutation_is_detected_not_silently_restored(self):
        model, optimizer = self.fixture()
        def forward(m):
            optimizer.state[m.a]["exp_avg"].add_(1)
            return m(torch.ones(4))
        before = optimizer.state[model.a]["exp_avg"].clone()
        with self.assertRaisesRegex(SaveScopeError, "mutated"):
            audit(model, forward, lambda out: out.square().mean(), optimizer=optimizer)
        self.assertTrue(torch.equal(optimizer.state[model.a]["exp_avg"], before+1))

    def test_callback_exception_preserves_untouched_optimizer(self):
        model, optimizer = self.fixture()
        captured = snapshot_adamw(torch, list(model.named_parameters()), optimizer)
        def forward(m):
            m(torch.ones(4))
            raise RuntimeError("deliberate callback failure")
        with self.assertRaisesRegex(RuntimeError, "deliberate"):
            audit(model, forward, lambda out: out.sum(), optimizer=optimizer)
        captured.assert_unchanged()

    def test_in_place_restored_values_are_still_mutation(self):
        model, optimizer = self.fixture()
        captured = snapshot_adamw(torch, list(model.named_parameters()), optimizer)
        tensor = optimizer.state[model.a]["exp_avg"]
        tensor.add_(1)
        tensor.sub_(1)
        with self.assertRaisesRegex(SaveScopeError, "mutated"):
            captured.assert_unchanged()

    def test_optimizer_kwargs_conflict_refuses_before_forward(self):
        model, optimizer = self.fixture()
        called = []
        with self.assertRaises(SaveScopeError):
            audit(model, lambda m: called.append(True) or m(torch.ones(4)),
                  lambda out: out.sum(), optimizer=optimizer, optimizer_kwargs={"lr": .01})
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
