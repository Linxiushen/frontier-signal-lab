"""Eager CPU saved-tensor diagnostics, independent of the frozen experiments.

This module imports no ML library at import time. Its deterministic last-axis
int8 codec derives from this repository's MIT activation-training diagnostic.
It changes backward saved operands, while forward values and the separate loss
call remain exact. This is a diagnostic, not a production compression policy.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import random
import threading


class SaveScopeError(ValueError):
    """The requested audit violates the supported execution contract."""


class SavedTensorPolicy(str, Enum):
    DENSE = "dense"
    INT8 = "int8"
    INT8_KEEP_SENSITIVE = "int8_keep_sensitive"


_ACTIVE_MODELS = set()
_ACTIVE_LOCK = threading.Lock()
_MISSING = object()


def _dependencies():
    try:
        import torch
        import numpy as np
    except ImportError as exc:
        raise SaveScopeError("audit requires the optional PyTorch and NumPy dependencies") from exc
    return torch, np


def _storage(tensor):
    return (str(tensor.device), tensor.untyped_storage().data_ptr())


def _type_name(value):
    return type(value).__module__ + "." + type(value).__qualname__


@contextmanager
def _exclusive(modules):
    identities = {id(module) for module in modules}
    with _ACTIVE_LOCK:
        if identities & _ACTIVE_MODELS:
            raise SaveScopeError("nested or concurrent audits of shared modules are unsupported")
        _ACTIVE_MODELS.update(identities)
    try:
        yield
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_MODELS.difference_update(identities)


class _State:
    """Keep original objects/storage as well as values, including existing grads."""

    def __init__(self, model, torch, np):
        self.model, self.torch, self.np = model, torch, np
        self.modules = list(model.modules())
        self.registrations = [(m, dict(m._parameters), dict(m._buffers), dict(m._modules),
                               set(m._non_persistent_buffers_set), m.training) for m in self.modules]
        self.parameters = list(model.named_parameters())
        self.buffers = list(model.named_buffers())
        self.values = []
        for _, tensor in self.parameters + self.buffers:
            self.values.append((tensor, tensor.detach(), tensor.detach().clone()))
        self.parameter_values = {id(tensor): value for tensor, _, value in self.values}
        self.gradients = []
        for _, p in self.parameters:
            grad = p.grad
            self.gradients.append((p, p.requires_grad, grad,
                                   grad.detach() if grad is not None else None,
                                   grad.detach().clone() if grad is not None else None))
        self.rng = (random.getstate(), np.random.get_state(), torch.get_rng_state().clone())

    def restore(self):
        # Restoring registration dictionaries also undoes an erroneous added or
        # replaced parameter/buffer/module. Unregistered application state is not
        # part of this contract.
        for module, parameters, buffers, children, nonpersistent, training in self.registrations:
            for target, original in ((module._parameters, parameters), (module._buffers, buffers),
                                     (module._modules, children)):
                target.clear()
                target.update(original)
            module._non_persistent_buffers_set = set(nonpersistent)
            module.training = training
        with self.torch.no_grad():
            for tensor, original_storage, value in self.values:
                tensor.data = original_storage
                tensor.data.copy_(value)
            for parameter, requires_grad, grad, original_storage, value in self.gradients:
                parameter.requires_grad_(requires_grad)
                if grad is not None:
                    grad.data = original_storage
                    grad.data.copy_(value)
                parameter.grad = grad
        random.setstate(self.rng[0])
        self.np.random.set_state(self.rng[1])
        self.torch.set_rng_state(self.rng[2])

    def assert_contract(self):
        for module, parameters, buffers, children, nonpersistent, training in self.registrations:
            for actual, expected in ((module._parameters, parameters), (module._buffers, buffers),
                                     (module._modules, children)):
                if list(actual) != list(expected) or any(actual[k] is not expected[k] for k in expected):
                    raise SaveScopeError("forward/loss changed registered model structure")
            if module.training != training or module._non_persistent_buffers_set != nonpersistent:
                raise SaveScopeError("forward/loss changed model mode or buffer registration")
        for parameter, required, _, _, _ in self.gradients:
            if parameter.requires_grad != required:
                raise SaveScopeError("forward/loss changed requires_grad")
        for tensor, original_storage, value in self.values:
            if (tensor.shape != value.shape or tensor.dtype != value.dtype or tensor.device != value.device
                    or tensor.stride() != original_storage.stride()
                    or tensor.storage_offset() != original_storage.storage_offset()):
                raise SaveScopeError("forward/loss changed tensor metadata")
            if _storage(tensor) != _storage(original_storage):
                raise SaveScopeError("forward/loss replaced registered tensor storage")
        for _, parameter in self.parameters:
            value = self.parameter_values[id(parameter)]
            if not self.torch.equal(parameter.detach(), value):
                raise SaveScopeError("forward/loss mutated parameters before the optimizer step")


class _Codec:
    def __init__(self, torch, protected, compress, min_elements=256):
        self.torch, self.protected, self.compress = torch, protected, compress
        self.min_elements = min_elements
        self.counts = Counter()
        self.shapes = Counter()
        self.original_bytes = self.payload_bytes = 0

    def pack(self, tensor):
        torch = self.torch
        if tensor.device.type != "cpu" or tensor.layout != torch.strided:
            raise SaveScopeError("saved operands must be CPU strided tensors")
        self.counts["save_calls"] += 1
        self.original_bytes += tensor.numel() * tensor.element_size()
        if _storage(tensor) in self.protected:
            reason = "parameter_or_buffer_storage_excluded"
        elif tensor.dtype != torch.float32:
            reason = "dtype_excluded"
        elif tensor.ndim == 0 or tensor.numel() < self.min_elements or tensor.shape[-1] == 0:
            reason = "size_or_shape_excluded"
        elif not bool(torch.isfinite(tensor).all()):
            reason = "nonfinite_excluded"
        else:
            reason = "eligible"
        self.counts[reason] += 1
        self.shapes[(reason, str(tensor.dtype), tuple(tensor.shape))] += 1
        if self.compress and reason == "eligible":
            with torch.no_grad():
                maximum = tensor.detach().abs().amax(dim=-1, keepdim=True)
                scales = torch.where(maximum == 0, torch.ones_like(maximum), maximum / 127.0)
                # Avoid division by an underflowed scale for subnormal operands.
                if bool((scales == 0).any()):
                    self.counts["scale_underflow_exact_fallback"] += 1
                else:
                    codes = torch.round(tensor.detach() / scales).clamp(-127, 127).to(torch.int8)
                    self.counts["compressed_saves"] += 1
                    self.payload_bytes += codes.numel() * codes.element_size() + scales.numel() * scales.element_size()
                    return (codes, scales)
        self.payload_bytes += tensor.numel() * tensor.element_size()
        return tensor.detach()

    def unpack(self, payload):
        self.counts["unpack_calls"] += 1
        if isinstance(payload, tuple):
            codes, scales = payload
            self.counts["decoded_unpacks"] += 1
            return codes.to(scales.dtype) * scales
        return payload

    def inventory(self):
        return {"counts": dict(self.counts),
                "original_logical_saved_bytes": self.original_bytes,
                "retained_logical_payload_bytes": self.payload_bytes,
                "shape_audit": [{"reason": reason, "dtype": dtype, "shape": list(shape), "saves": count}
                                for (reason, dtype, shape), count in sorted(self.shapes.items())]}


@contextmanager
def _scopes(model, torch, protected, policy, sensitive_types, outer):
    """Same instrumentation in every arm; innermost actual forward scope wins."""
    originals, records, installed = [], {}, []
    owner = threading.get_ident()
    root_calls = [0]
    root_depth = [0]
    try:
        for name, module in model.named_modules():
            sensitive = isinstance(module, sensitive_types)
            if not sensitive and module is not model:
                continue
            original = module.forward
            previous = module.__dict__.get("forward", _MISSING)
            codec = _Codec(torch, protected, policy == "int8") if sensitive else None
            if sensitive:
                records[name] = {"module_class": _type_name(module), "calls": 0, "codec": codec}
            record = records.get(name) if sensitive else None

            def wrapped(*args, _original=original, _codec=codec, _record=record,
                        _root=module is model, **kwargs):
                if threading.get_ident() != owner:
                    raise SaveScopeError("model forward crossed the audit thread")
                if not _root and root_depth[0] == 0:
                    # Sensitive children may be used for callback postprocessing;
                    # their operations are outside the actual root-forward scope.
                    return _original(*args, **kwargs)
                if _root:
                    root_calls[0] += 1
                if _record is not None:
                    _record["calls"] += 1
                def invoke():
                    if _codec is None:
                        return _original(*args, **kwargs)
                    with torch.autograd.graph.saved_tensors_hooks(_codec.pack, _codec.unpack):
                        return _original(*args, **kwargs)

                if _root:
                    nested = root_depth[0] > 0
                    root_depth[0] += 1
                    try:
                        if nested:
                            # A recursive root call inherits an active exact
                            # ancestor instead of overwriting that ancestor hook.
                            return invoke()
                        with torch.autograd.graph.saved_tensors_hooks(outer.pack, outer.unpack):
                            return invoke()
                    finally:
                        root_depth[0] -= 1
                return invoke()

            originals.append((module, previous))
            module.forward = wrapped
            installed.append((module, wrapped))
        yield records, root_calls
        if any(module.__dict__.get("forward") is not wrapper for module, wrapper in installed):
            raise SaveScopeError("forward/loss replaced an instrumented forward")
    finally:
        for module, previous in reversed(originals):
            if previous is _MISSING:
                module.__dict__.pop("forward", None)
            else:
                module.forward = previous


@contextmanager
def _loss_boundary(model):
    """Loss code may use its own modules but cannot re-enter the audited model."""
    originals = []

    def blocked(*args, **kwargs):
        raise SaveScopeError("loss_fn must not call the audited model or its modules")

    try:
        for module in model.modules():
            originals.append((module, module.__dict__.get("forward", _MISSING)))
            module.forward = blocked
        yield
        if any(module.__dict__.get("forward") is not blocked for module, _ in originals):
            raise SaveScopeError("loss_fn replaced a model forward")
    finally:
        for module, previous in reversed(originals):
            if previous is _MISSING:
                module.__dict__.pop("forward", None)
            else:
                module.forward = previous


def _hash_tensor(tensor):
    array = tensor.detach().contiguous().numpy()
    header = json.dumps({"dtype": str(array.dtype), "shape": list(array.shape)}, sort_keys=True).encode()
    return hashlib.sha256(header + b"\0" + array.tobytes()).hexdigest()


def _metrics(torch, reference, candidate):
    if len(reference) != len(candidate):
        raise SaveScopeError("comparison tensor counts differ")
    rows, totals = [], Counter()
    all_finite = True
    maximum = 0.0
    for (name, left), (other, right) in zip(reference, candidate):
        if name != other or left.shape != right.shape:
            raise SaveScopeError("comparison tensor names/shapes differ")
        a, b = left.detach().to(torch.float64), right.detach().to(torch.float64)
        finite = bool(torch.isfinite(a).all()) and bool(torch.isfinite(b).all())
        all_finite &= finite
        if finite:
            values = {"reference_sum_squares": float((a*a).sum()), "candidate_sum_squares": float((b*b).sum()),
                      "difference_sum_squares": float(((b-a)**2).sum()), "dot_product": float((a*b).sum())}
            error = float((b-a).abs().max()) if a.numel() else 0.0
            rows.append({"name": name, "elements": a.numel(), **_finish(values), "max_absolute_difference": error})
            totals.update(values)
            maximum = max(maximum, error)
        else:
            rows.append({"name": name, "elements": a.numel(), "finite": False})
    if not all_finite:
        return {"finite": False, "relative_l2": None, "cosine_similarity": None, "per_parameter": rows}
    return {"finite": True, **_finish(totals), "max_absolute_difference": maximum, "per_parameter": rows}


def _finish(values):
    r, c, d = (math.sqrt(values.get(k, 0.0)) for k in
               ("reference_sum_squares", "candidate_sum_squares", "difference_sum_squares"))
    return {**values, "reference_l2": r, "candidate_l2": c, "difference_l2": d,
            "relative_l2": d/r if r else (0.0 if d == 0 else None),
            "cosine_similarity": max(-1.0, min(1.0, values.get("dot_product", 0.0)/(r*c)))
                                  if r and c else (1.0 if r == c else 0.0),
            "zero_reference_norm": r == 0}


def _summary(torch, tensors, present=None):
    rows, squares = [], []
    for name, value in tensors:
        finite = bool(torch.isfinite(value).all())
        norm = float(torch.linalg.vector_norm(value.to(torch.float64))) if finite else None
        rows.append({"name": name, "shape": list(value.shape), "elements": value.numel(),
                     "present": True if present is None else present[name],
                     "finite": finite, "l2": norm, "sha256": _hash_tensor(value)})
        if norm is not None:
            squares.append(norm*norm)
    finite = all(row["finite"] for row in rows)
    return {"tensors": len(rows), "elements": sum(row["elements"] for row in rows),
            "present_tensors": sum(row["present"] for row in rows), "finite": finite,
            "l2": math.sqrt(math.fsum(squares)) if finite else None, "per_parameter": rows}


def _optimizer_options(options):
    values = {"lr": 1e-4, "betas": (0.9, 0.999), "eps": 1e-8, "weight_decay": 0.0}
    options = {} if options is None else dict(options)
    unknown = set(options) - set(values)
    if unknown:
        raise SaveScopeError("unsupported AdamW options: " + ", ".join(sorted(unknown)))
    values.update(options)
    for key in ("lr", "eps", "weight_decay"):
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise SaveScopeError("AdamW options must be finite numbers")
        if value < 0 or (key == "eps" and value == 0):
            raise SaveScopeError("AdamW requires lr/weight_decay>=0 and eps>0")
    betas = values["betas"]
    if not isinstance(betas, (tuple, list)) or len(betas) != 2 or any(
            isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x < 1 for x in betas):
        raise SaveScopeError("AdamW betas must contain two finite values in [0,1)")
    values["betas"] = tuple(betas)
    return values


def _rounding_control(np, actual, expected, original=None):
    """Independent elementwise float32 rounding control, not a fidelity gate."""
    actual = np.asarray(actual, dtype=np.float64)
    expected = np.asarray(expected, dtype=np.float64)
    if actual.shape != expected.shape:
        raise SaveScopeError("native AdamW reference shape differs")
    if not np.isfinite(actual).all() or not np.isfinite(expected).all():
        return {"passed": False, "finite": False, "max_absolute_error": None,
                "max_fraction_of_allowed_error": None}
    scale = np.abs(expected) if original is None else np.abs(original) + np.abs(expected - original)
    allowed = 8 * np.finfo(np.float32).eps * scale + 8 * np.finfo(np.float32).tiny
    error = np.abs(actual - expected)
    passed = bool(np.all(error <= allowed))
    if not passed:
        raise SaveScopeError("native AdamW differs from independent NumPy rounding bounds")
    return {"passed": True, "finite": True,
            "max_absolute_error": float(error.max()) if error.size else 0.0,
            "max_fraction_of_allowed_error": float((error / allowed).max()) if error.size else 0.0}


def _first_step(torch, np, named, gradients, present, options):
    """Run native AdamW only on independent parameter/gradient clones."""
    clones, before = [], []
    original_storages = {_storage(p) for _, p in named if p.numel()}
    original_storages.update(_storage(p.grad) for _, p in named if p.grad is not None and p.grad.numel())
    allocated = set()
    for (name, parameter), (other, gradient) in zip(named, gradients):
        if name != other:
            raise SaveScopeError("optimizer input names differ")
        value = parameter.detach().clone()
        clone = torch.nn.Parameter(value.clone())
        clone.grad = gradient.clone() if present[name] else None
        for tensor in (clone, clone.grad):
            if tensor is not None and tensor.numel():
                storage = _storage(tensor)
                if storage in original_storages or storage in allocated:
                    raise SaveScopeError("optimizer clone aliases model or another clone")
                allocated.add(storage)
        clones.append(clone)
        before.append((name, value))
    optimizer = torch.optim.AdamW(clones, **options, foreach=False, fused=False)
    optimizer.step()
    updates = [(name, clone.detach().clone() - value)
               for (name, value), clone in zip(before, clones)]
    update = _summary(torch, updates)
    expected_deltas, controls = [], []
    for (name, theta), (_, gradient), clone in zip(before, gradients, clones):
        theta64 = theta.numpy().astype(np.float64)
        g64 = gradient.numpy().astype(np.float64)
        b1, b2 = options["betas"]
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            if present[name]:
                mean = (1 - b1) * g64
                square = (1 - b2) * g64 * g64
                expected = theta64 * (1 - options["lr"] * options["weight_decay"]) - options["lr"] * (
                    mean / (1 - b1)) / (np.sqrt(square / (1 - b2)) + options["eps"])
            else:
                mean = square = np.zeros_like(theta64)
                expected = theta64.copy()
            expected_deltas.append((name, torch.from_numpy(expected - theta64)))
        native = optimizer.state.get(clone, {})
        actual_step = float(native["step"]) if native else 0
        expected_step = 1 if present[name] else 0
        if actual_step != expected_step:
            raise SaveScopeError("native AdamW first-step counter differs")
        controls.append({"name": name, "optimizer_step": expected_step,
                         "parameter_sha256_after": _hash_tensor(clone),
                         "parameter": _rounding_control(np, clone.detach().numpy(), expected, theta64),
                         "exp_avg": _rounding_control(np, native["exp_avg"].numpy() if native else np.zeros_like(theta64), mean),
                         "exp_avg_sq": _rounding_control(np, native["exp_avg_sq"].numpy() if native else np.zeros_like(theta64), square)})
    all_controls = all(row[key]["passed"] for row in controls for key in ("parameter", "exp_avg", "exp_avg_sq"))
    update["independent_reference"] = {
        "kind": "numpy_float64_closed_form_adamw_first_step",
        "meaning": "Fresh zero moments; independent parameter, moment and step checks. Float32 rounding bounds are engineering controls, not scientific fidelity thresholds.",
        "rounding_bound": {"float32_epsilon_multiplier": 8, "float32_tiny_multiplier": 8,
                           "parameter_scale": "abs(initial_parameter) + abs(expected_parameter - initial_parameter)",
                           "moment_scale": "abs(expected_moment)"},
        "all_parameter_and_moment_checks_passed": all_controls,
        "per_parameter": controls, "comparison": _metrics(torch, expected_deltas, updates)}
    update["executed"] = True
    update["clone_storages_disjoint"] = True
    update["finite"] = update["finite"] and all_controls
    return update, updates


def audit(model, forward_fn, loss_fn, *,
          policies=("dense", "int8", "int8_keep_sensitive"), optimizer_kwargs=None,
          exact_module_types=(), optimizer=None):
    """Compare saved-operand policies at one initial model state.

    Actual ``model.forward`` calls made by ``forward_fn(model)`` run under
    saved-tensor hooks; callback operations outside those calls stay exact.
    ``loss_fn(outputs)`` runs outside SaveScope hooks and cannot re-enter the model. It must
    return one differentiable scalar. All arms start with identical registered
    model state and global CPU/Python/NumPy RNG state; each makes one backward
    and one AdamW step on independent parameter clones. By default moments are
    fresh; ``optimizer=`` captures a supported caller AdamW's state once and
    starts every arm from that same state. The caller optimizer is never stepped.
    Registered state, modes and grad
    objects/values are restored even when a callback raises.

    Supported: CPU float32 strided parameters, eager first-order autograd,
    one thread, no compile/checkpoint/distributed execution, no pre-existing
    live autograd graph or caller-installed saved_tensors_hooks. Ordinary buffer value updates are reset between arms.
    Callbacks must not mutate parameters, registration, mode, external inputs
    or other application state. This API restores values/storage, not an
    external live autograd graph or arbitrary application attributes.
    """
    torch, np = _dependencies()
    if not isinstance(model, torch.nn.Module) or not callable(forward_fn) or not callable(loss_fn):
        raise SaveScopeError("provide an nn.Module, forward_fn(model), and loss_fn(outputs)")
    if hasattr(model, "_orig_mod") or isinstance(model, (torch.nn.DataParallel, torch.nn.parallel.DistributedDataParallel)):
        raise SaveScopeError("compiled and distributed wrappers are unsupported")
    try:
        policies = tuple(SavedTensorPolicy(p).value for p in policies)
    except (TypeError, ValueError) as exc:
        raise SaveScopeError("unknown saved-tensor policy") from exc
    if not policies or policies[0] != "dense" or len(set(policies)) != len(policies):
        raise SaveScopeError("policies must start with a unique dense baseline")
    if not isinstance(exact_module_types, (tuple, list)) or any(
            not isinstance(cls, type) or not issubclass(cls, torch.nn.Module) for cls in exact_module_types):
        raise SaveScopeError("exact_module_types must contain nn.Module classes")
    sensitive_types = (torch.nn.LayerNorm, torch.nn.MultiheadAttention) + tuple(exact_module_types)
    if optimizer is not None and optimizer_kwargs is not None:
        raise SaveScopeError("optimizer and optimizer_kwargs are mutually exclusive")
    options = _optimizer_options(optimizer_kwargs)
    for _, tensor in list(model.named_parameters()) + list(model.named_buffers()):
        if tensor.device.type != "cpu" or tensor.layout != torch.strided:
            raise SaveScopeError("registered model state must be CPU strided tensors")
        if tensor.is_floating_point() and tensor.dtype != torch.float32:
            raise SaveScopeError("floating model state must be float32")
        if tensor.is_complex():
            raise SaveScopeError("complex model state is unsupported")
    for _, parameter in model.named_parameters():
        if not bool(torch.isfinite(parameter).all()):
            raise SaveScopeError("registered parameters must be finite")
        if parameter.grad is not None and parameter.grad.layout != torch.strided:
            raise SaveScopeError("pre-existing sparse gradients are unsupported")
    parameter_storages = {}
    for name, parameter in model.named_parameters():
        if not parameter.numel():
            continue
        key = _storage(parameter)
        if key in parameter_storages:
            raise SaveScopeError("distinct registered parameters sharing backing storage are unsupported: "
                                 + parameter_storages[key] + ", " + name)
        parameter_storages[key] = name
    named = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    if not named:
        raise SaveScopeError("model needs at least one trainable parameter")
    optimizer_snapshot = None
    if optimizer is not None:
        from .optimizer_state import snapshot_adamw
        optimizer_snapshot = snapshot_adamw(
            torch, named, optimizer,
            protected_tensors=[tensor for _, tensor in
                               list(model.named_parameters()) + list(model.named_buffers())])
        options = optimizer_snapshot.options
    state = _State(model, torch, np)
    arms, comparisons = [], []
    dense_gradients = dense_updates = None
    with _exclusive(state.modules):
        try:
            for policy in policies:
                if optimizer_snapshot is not None:
                    optimizer_snapshot.assert_unchanged()
                state.restore()
                for _, p in state.parameters:
                    p.grad = None
                protected = {_storage(t) for _, t in state.parameters + state.buffers}
                outer = _Codec(torch, protected, policy != "dense")
                with torch.enable_grad():
                    with _scopes(model, torch, protected, policy, sensitive_types, outer) as (scopes, calls):
                        outputs = forward_fn(model)
                    if calls[0] == 0:
                        raise SaveScopeError("forward_fn must call the supplied model's forward")
                    state.assert_contract()
                    with _loss_boundary(model):
                        loss = loss_fn(outputs)
                    if (not isinstance(loss, torch.Tensor) or loss.ndim != 0 or not loss.requires_grad
                            or not loss.is_floating_point()):
                        raise SaveScopeError("loss_fn must return one differentiable scalar tensor")
                    if loss.device.type != "cpu":
                        raise SaveScopeError("loss_fn must return a CPU scalar tensor")
                    state.assert_contract()
                    loss_value = float(loss.detach())
                    if math.isfinite(loss_value):
                        loss.backward()
                state.assert_contract()
                if optimizer_snapshot is not None:
                    optimizer_snapshot.assert_unchanged()
                present = {name: p.grad is not None for name, p in named}
                if any(p.grad is not None and p.grad.layout != torch.strided for _, p in named):
                    raise SaveScopeError("sparse gradients are unsupported")
                gradients = [(name, p.grad.detach().clone() if p.grad is not None else torch.zeros_like(p)) for name, p in named]
                gradient = _summary(torch, gradients, present)
                gradient["unused_parameters"] = [name for name, used in present.items() if not used]
                valid = math.isfinite(loss_value) and gradient["finite"] and any(present.values())
                updates = None
                if valid:
                    if optimizer_snapshot is None:
                        update, updates = _first_step(torch, np, named, gradients, present, options)
                    else:
                        update, updates = optimizer_snapshot.step(torch, np, named, gradients, present)
                    valid = update["finite"]
                else:
                    update = {"executed": False, "reason": "nonfinite loss/gradient or no parameter gradient",
                              "finite": None, "l2": None}
                inventories = {name: {"module_class": item["module_class"], "calls": item["calls"],
                                      **item["codec"].inventory()} for name, item in scopes.items()}
                outer_inventory = outer.inventory()
                logical = {k: outer_inventory[k] + sum(item[k] for item in inventories.values())
                           for k in ("original_logical_saved_bytes", "retained_logical_payload_bytes")}
                inventory = {"other_forward": outer_inventory, "sensitive_modules": inventories,
                             "model_forward_calls": calls[0], "logical_bytes": logical,
                             "loss_saved_tensors_included": False,
                             "meaning": "Logical saves count duplicates; excludes loss and unrelated live tensors. Not peak allocation or training memory."}
                arms.append({"policy": policy, "loss": loss_value if math.isfinite(loss_value) else None,
                             "numerically_valid": valid, "gradient": gradient, "update": update, "inventory": inventory})
                if policy == "dense":
                    dense_gradients, dense_updates = gradients, updates
                else:
                    comparisons.append({"policy": policy, "loss_matches_dense": arms[-1]["loss"] == arms[0]["loss"],
                                        "gradient": _metrics(torch, dense_gradients, gradients),
                                        "update": _metrics(torch, dense_updates, updates) if dense_updates is not None and updates is not None else
                                                  {"available": False, "relative_l2": None, "cosine_similarity": None}})
        finally:
            state.restore()
            if optimizer_snapshot is not None:
                optimizer_snapshot.assert_unchanged()
    report = {"schema_version": 1, "kind": "savescope_audit", "mode": "executed",
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "model": {"class": _type_name(model), "parameter_tensors": len(state.parameters),
                        "trainable_parameter_tensors": len(named), "trainable_elements": sum(p.numel() for _, p in named),
                        "device": "cpu", "parameter_dtype": "float32"},
              "scope": {"forward": "actual model.forward calls made by forward_fn(model); callback operations outside model stay exact",
                        "loss": "loss_fn(outputs), outside SaveScope hooks; re-entry into audited modules rejected",
                        "sensitive_module_types": [cls.__module__ + "." + cls.__qualname__ for cls in sensitive_types],
                        "selection": "actual module classes; innermost forward scope wins", "min_compressed_elements": 256,
                        "protected": "registered parameter and buffer backing-storage aliases"},
              "optimizer": {"type": "AdamW", "initial_state": "fresh zero moments for every arm" if optimizer_snapshot is None
                            else "captured caller AdamW state for every arm",
                            "execution": "independent parameter and gradient clones; model is never stepped", **options},
              "arms": arms, "comparisons": comparisons,
              "runtime": {"torch": torch.__version__, "numpy": np.__version__},
              "limitations": ["Eager CPU float32, first-order, single-threaded diagnostic only; compile, checkpoint and distributed execution unsupported.",
                              "Caller-installed saved_tensors_hooks are unsupported; loss and callback postprocessing are outside SaveScope hooks only.",
                              "Registered values/storage, modes, existing grad objects and global CPU/Python/NumPy RNG restored; arbitrary callback state and external inputs are not restored.",
                              "Call between steps without an external live autograd graph. Arbitrary callback mutations and external input state are unsupported.",
                              "One common-state AdamW step is not a training-quality or trajectory-equivalence result; scientific error is reported without a success threshold.",
                              "Int8 changes backward operands; repeated module calls and repeated unpacks are counted, not assumed to occur once.",
                              "Logical payload counts are not peak memory, speed, end-to-end savings, scale or architecture claims."]}
    if optimizer_snapshot is not None:
        report["optimizer"]["snapshot"] = optimizer_snapshot.receipt
        report["limitations"].append("Caller AdamW must have one supported group covering exactly the trainable model parameters. Callback/concurrent optimizer mutations are rejected, not restored.")
    # Refuse accidental NaN/Infinity output at this public serialization boundary.
    json.dumps(report, allow_nan=False)
    return report
