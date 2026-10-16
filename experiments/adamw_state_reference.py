"""Independent stateful AdamW controls for the predeclared CPU diagnostic.

This module is separate from the fresh-state SaveScope API. Rounding bounds
check native arithmetic, never scientific update fidelity. All comparisons use
actual float32 parameter differences, not parameters themselves.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from experiments.activation_update_probe import (
    OPTIMIZER, aggregate_metrics, numpy_adamw_step, update_metrics,
)
from experiments.activation_gradient_probe import tensor_hash
from experiments.activation_training_probe import digest, require_torch


def _tensor(value, *, shape=None, label="tensor", nonnegative=False):
    torch = require_torch()
    if (not isinstance(value, torch.Tensor) or value.device.type != "cpu"
            or value.dtype != torch.float32 or value.layout != torch.strided
            or value.numel() == 0 or not bool(torch.isfinite(value).all())
            or (shape is not None and value.shape != shape)):
        raise ValueError(label + " must be a finite nonempty matching CPU float32 strided tensor")
    if nonnegative and bool((value < 0).any()):
        raise ValueError(label + " must be nonnegative")
    return value


def _step(value, *, native=False):
    torch = require_torch()
    if native:
        if (not isinstance(value, torch.Tensor) or value.device.type != "cpu"
                or value.dtype != torch.float32 or value.ndim != 0
                or not bool(torch.isfinite(value))):
            raise ValueError("native AdamW step must be a finite CPU float32 scalar tensor")
        number = float(value)
        if not number.is_integer():
            raise ValueError("native AdamW step must be integral")
        value = int(number)
    if type(value) is not int or not 0 <= value < 2 ** 24:
        raise ValueError("step must be a nonnegative integer with exact float32 next-step representation")
    return value


def _disjoint(tensors, *, forbidden=()):
    occupied = {v.untyped_storage().data_ptr() for v in forbidden}
    for label, value in tensors:
        ptr = value.untyped_storage().data_ptr()
        if ptr in occupied:
            raise ValueError("tensor backing storage aliases another input: " + label)
        occupied.add(ptr)
    return occupied


def _named(named, *, gradients=False):
    torch = require_torch()
    named = list(named)
    if (not named or any(not isinstance(row, (tuple, list)) or len(row) != 2 for row in named)
            or any(not isinstance(name, str) or not name for name, _ in named)
            or len({name for name, _ in named}) != len(named)):
        raise ValueError("a nonempty unique named parameter sequence is required")
    tensors = []
    for name, parameter in named:
        if not isinstance(parameter, torch.nn.Parameter) or not parameter.requires_grad:
            raise ValueError("trainable torch Parameters are required")
        _tensor(parameter, label=name)
        tensors.append((name, parameter))
        if gradients:
            _tensor(parameter.grad, shape=parameter.shape, label=name + " gradient")
            tensors.append((name + " gradient", parameter.grad))
    _disjoint(tensors)
    return named


def _check_optimizer(named, optimizer):
    torch = require_torch()
    if not isinstance(optimizer, torch.optim.AdamW) or len(optimizer.param_groups) != 1:
        raise ValueError("one actual AdamW parameter group is required")
    group = optimizer.param_groups[0]
    if len(group["params"]) != len(named) or any(a is not b for (_, a), b in zip(named, group["params"])):
        raise ValueError("optimizer parameters/order differ from the named inputs")
    expected = {"lr": OPTIMIZER["learning_rate"], "betas": tuple(OPTIMIZER["betas"]),
                "eps": OPTIMIZER["epsilon"], "weight_decay": OPTIMIZER["weight_decay"],
                **{k: OPTIMIZER[k] for k in ("foreach", "fused", "amsgrad", "maximize", "capturable", "differentiable")}}
    if any(group.get(key) != value for key, value in expected.items()):
        raise ValueError("optimizer hyperparameters differ from the frozen AdamW configuration")
    if set(optimizer.state) - {p for _, p in named}:
        raise ValueError("optimizer contains state for an unknown parameter")


def make_optimizer(named):
    """Use exactly the frozen AdamW options and one group; state starts absent."""
    torch = require_torch()
    named = _named(named)
    return torch.optim.AdamW([p for _, p in named], lr=OPTIMIZER["learning_rate"],
        betas=tuple(OPTIMIZER["betas"]), eps=OPTIMIZER["epsilon"],
        weight_decay=OPTIMIZER["weight_decay"], foreach=False, fused=False,
        amsgrad=False, maximize=False, capturable=False, differentiable=False)


def _native_state(named, optimizer):
    """Validate native state without initializing or otherwise mutating it."""
    torch = require_torch()
    _check_optimizer(named, optimizer)
    states, tensors = {}, [(name, p) for name, p in named]
    tensors.extend((name + " gradient", p.grad) for name, p in named if p.grad is not None)
    for name, parameter in named:
        row = optimizer.state.get(parameter)
        if not row:
            states[name] = {"exp_avg": torch.zeros_like(parameter),
                            "exp_avg_sq": torch.zeros_like(parameter), "step": 0}
            continue
        if set(row) != {"exp_avg", "exp_avg_sq", "step"}:
            raise ValueError("native AdamW state is incomplete or has unsupported fields")
        mean = _tensor(row["exp_avg"], shape=parameter.shape, label=name + " exp_avg")
        square = _tensor(row["exp_avg_sq"], shape=parameter.shape, label=name + " exp_avg_sq", nonnegative=True)
        step = _step(row["step"], native=True)
        if step == 0 and (bool(mean.any()) or bool(square.any())):
            raise ValueError("step-zero AdamW moments must be zero")
        states[name] = {"exp_avg": mean, "exp_avg_sq": square, "step": step}
        tensors.extend((name + " " + key, row[key]) for key in ("exp_avg", "exp_avg_sq", "step"))
    _disjoint(tensors)
    return states


def capture_step_inputs(named, optimizer):
    """Snapshot actual theta, required gradient, moments and integer pre-step t."""
    named = _named(named, gradients=True)
    states = _native_state(named, optimizer)
    inputs = {name: {"parameter": p.detach().clone(), "gradient": p.grad.detach().clone(),
                     "exp_avg": states[name]["exp_avg"].detach().clone(),
                     "exp_avg_sq": states[name]["exp_avg_sq"].detach().clone(),
                     "step": states[name]["step"]} for name, p in named}
    _disjoint([(name + " " + key, row[key]) for name, row in inputs.items()
               for key in ("parameter", "gradient", "exp_avg", "exp_avg_sq")])
    return inputs


def freeze_optimizer_state(named, optimizer):
    """Return disjoint frozen m/v snapshots; absent native state means zero."""
    named = _named(named)
    states = _native_state(named, optimizer)
    return {name: {"exp_avg": row["exp_avg"].detach().clone(),
                   "exp_avg_sq": row["exp_avg_sq"].detach().clone(), "step": row["step"]}
            for name, row in states.items()}


def _frozen_states(states, named=None):
    if not isinstance(states, dict) or not states:
        raise ValueError("complete nonempty named optimizer state is required")
    if any(not isinstance(name, str) or not name for name in states):
        raise ValueError("state names must be nonempty strings")
    shapes = {name: p.shape for name, p in named} if named is not None else None
    if shapes is not None and set(states) != set(shapes):
        raise ValueError("optimizer state names differ from parameters")
    tensors = []
    for name, row in states.items():
        if not isinstance(row, dict) or set(row) != {"exp_avg", "exp_avg_sq", "step"}:
            raise ValueError("frozen AdamW state is incomplete or has unsupported fields")
        mean = _tensor(row["exp_avg"], shape=shapes[name] if shapes is not None else None, label=name + " exp_avg")
        square = _tensor(row["exp_avg_sq"], shape=mean.shape, label=name + " exp_avg_sq", nonnegative=True)
        step = _step(row["step"])
        if step == 0 and (bool(mean.any()) or bool(square.any())):
            raise ValueError("step-zero AdamW moments must be zero")
        tensors.extend(((name + " exp_avg", mean), (name + " exp_avg_sq", square)))
    _disjoint(tensors)
    return states


def frozen_state_hash(states):
    """Stable content hash of m/v/integer step, excluding parameters/gradients."""
    states = _frozen_states(states)
    return digest({name: {"exp_avg": tensor_hash(row["exp_avg"]),
                          "exp_avg_sq": tensor_hash(row["exp_avg_sq"]), "step": row["step"]}
                   for name, row in states.items()})


def state_hash(named, optimizer):
    """Stable theta+m/v/t hash; independent of gradient presence or values."""
    named = _named(named)
    states = _native_state(named, optimizer)
    return digest({name: {"parameter": tensor_hash(p), "exp_avg": tensor_hash(states[name]["exp_avg"]),
                          "exp_avg_sq": tensor_hash(states[name]["exp_avg_sq"]), "step": states[name]["step"]}
                   for name, p in named})


def _array_hash(value):
    array = np.ascontiguousarray(value)
    return digest({"dtype": str(array.dtype), "shape": list(array.shape),
                   "data_sha256": hashlib.sha256(array.tobytes()).hexdigest()})


def _moment_control(actual, expected, tolerance):
    error = np.abs(actual - expected)
    if not np.isfinite(actual).all() or not np.isfinite(expected).all() or np.any(error > tolerance):
        raise ValueError("native AdamW moment differs from input-scale NumPy rounding bound")
    return {"passed": True, "max_absolute_error": float(error.max()),
            "max_fraction_of_allowed_error": float((error / tolerance).max()),
            "max_allowed_error": float(tolerance.max()), "tolerance_sha256": _array_hash(tolerance)}


def _parameter_interval(theta, mean, square, mean_tolerance, square_tolerance, step):
    """Propagate the m/v rectangle through corrected AdamW and round outward.

    With v>=0 and positive epsilon, m/sqrt(v) extrema on a rectangle occur
    among its four corners, including when the m interval crosses zero.
    The recorded corner update includes decoupled decay and the adaptive term.
    """
    b1, b2 = OPTIMIZER["betas"]
    rate, epsilon, decay = (OPTIMIZER[k] for k in ("learning_rate", "epsilon", "weight_decay"))
    lower = np.full_like(theta, np.inf)
    upper = np.full_like(theta, -np.inf)
    largest_delta = np.zeros_like(theta)
    for mean_sign in (-1, 1):
        corrected_mean = (mean + mean_sign * mean_tolerance) / (1 - b1 ** step)
        for square_sign in (-1, 1):
            corrected_square = np.maximum(0, square + square_sign * square_tolerance) / (1 - b2 ** step)
            delta = -rate * decay * theta - rate * corrected_mean / (np.sqrt(corrected_square) + epsilon)
            corner = theta + delta
            lower = np.minimum(lower, corner)
            upper = np.maximum(upper, corner)
            largest_delta = np.maximum(largest_delta, np.abs(delta))
    enlargement = 8 * np.finfo(np.float32).eps * (np.abs(theta) + largest_delta) + 8 * np.finfo(np.float32).tiny
    return lower - enlargement, upper + enlargement, enlargement


def check_native_step(inputs, named, optimizer):
    """Check every native t->t+1 against independent float64 stateful equations."""
    named = _named(named, gradients=True)
    states = _native_state(named, optimizer)
    if not isinstance(inputs, dict) or set(inputs) != {name for name, _ in named}:
        raise ValueError("step inputs are incomplete")
    snapshots = []
    receipts = []
    for name, parameter in named:
        row = inputs[name]
        if not isinstance(row, dict) or set(row) != {"parameter", "gradient", "exp_avg", "exp_avg_sq", "step"}:
            raise ValueError("step input fields are incomplete")
        for key in ("parameter", "gradient", "exp_avg", "exp_avg_sq"):
            _tensor(row[key], shape=parameter.shape, label="input " + name + " " + key, nonnegative=key == "exp_avg_sq")
            snapshots.append((name + " " + key, row[key]))
        step = _step(row["step"])
        if step == 0 and (bool(row["exp_avg"].any()) or bool(row["exp_avg_sq"].any())):
            raise ValueError("step-zero input moments must be zero")
        if states[name]["step"] != step + 1:
            raise ValueError("native AdamW counter differs from pre-step t+1")
        if not require_torch().equal(row["gradient"], parameter.grad):
            raise ValueError("gradient changed between step capture and native check")
        theta, gradient, mean0, square0 = [row[key].detach().numpy().astype(np.float64)
            for key in ("parameter", "gradient", "exp_avg", "exp_avg_sq")]
        reference = numpy_adamw_step(theta, gradient, exp_avg=mean0, exp_avg_sq=square0, step=step,
            learning_rate=OPTIMIZER["learning_rate"], betas=OPTIMIZER["betas"],
            epsilon=OPTIMIZER["epsilon"], weight_decay=OPTIMIZER["weight_decay"])
        b1, b2 = OPTIMIZER["betas"]
        eps32, tiny32 = np.finfo(np.float32).eps, np.finfo(np.float32).tiny
        mean_tolerance = 8 * eps32 * (np.abs(b1 * mean0) + np.abs((1 - b1) * gradient)) + 8 * tiny32
        square_tolerance = 8 * eps32 * (np.abs(b2 * square0) + np.abs((1 - b2) * gradient * gradient)) + 8 * tiny32
        parity = {
            "exp_avg": _moment_control(states[name]["exp_avg"].numpy().astype(np.float64), reference["exp_avg"], mean_tolerance),
            "exp_avg_sq": _moment_control(states[name]["exp_avg_sq"].numpy().astype(np.float64), reference["exp_avg_sq"], square_tolerance)
        }
        lower, upper, enlargement = _parameter_interval(theta, reference["exp_avg"], reference["exp_avg_sq"],
                                                       mean_tolerance, square_tolerance, step + 1)
        actual = parameter.detach().numpy().astype(np.float64)
        expected = reference["parameter"]
        if not np.isfinite(lower).all() or not np.isfinite(upper).all() or np.any(actual < lower) or np.any(actual > upper):
            raise ValueError("native AdamW parameter lies outside propagated NumPy rounding interval")
        if np.any(expected < lower) or np.any(expected > upper):
            raise ValueError("invalid propagated parameter interval")
        error = np.abs(actual - expected)
        allowed = np.where(actual >= expected, upper - expected, expected - lower)
        parity["parameter"] = {
            "passed": True, "max_absolute_error": float(error.max()),
            "max_fraction_of_allowed_error": float((error / allowed).max()),
            "max_interval_width": float((upper - lower).max()),
            "max_rounding_enlargement": float(enlargement.max()),
            "lower_sha256": _array_hash(lower), "upper_sha256": _array_hash(upper)
        }
        receipts.append({"name": name, "shape": list(parameter.shape), "elements": parameter.numel(),
            "input_step": step, "optimizer_step": step + 1,
            "input_sha256": {**{key: tensor_hash(row[key]) for key in ("parameter", "gradient", "exp_avg", "exp_avg_sq")}, "step": digest(step)},
            "output_sha256": {"parameter": tensor_hash(parameter), "gradient": tensor_hash(parameter.grad),
                "exp_avg": tensor_hash(states[name]["exp_avg"]), "exp_avg_sq": tensor_hash(states[name]["exp_avg_sq"]),
                "step": digest(step + 1), "native_step_tensor": tensor_hash(optimizer.state[parameter]["step"])},
            "numpy_reference_sha256": {key: _array_hash(value) for key, value in reference.items() if key != "step"},
            "numpy_reference_parity": parity})
    _disjoint(snapshots, forbidden=[v for _, p in named for v in (p, p.grad)] +
              [optimizer.state[p][key] for _, p in named for key in ("exp_avg", "exp_avg_sq", "step")])
    result = {"all_checks_passed": True, "per_parameter": receipts,
              "reference": "independent NumPy float64 stateful AdamW; input-scale moment bounds and four-corner corrected parameter interval",
              "rounding_control_is_not_scientific_fidelity_gate": True}
    json.dumps(result, allow_nan=False)
    return result


def clone_step(named, states, dense_updates=None):
    """One real step on fully disjoint theta/g/m/v/t clones; preserve sources."""
    torch = require_torch()
    named = _named(named, gradients=True)
    if states is None:
        states = {name: {"exp_avg": torch.zeros_like(p), "exp_avg_sq": torch.zeros_like(p), "step": 0} for name, p in named}
    _frozen_states(states, named)
    sources = [(name + " parameter", p) for name, p in named]
    sources += [(name + " gradient", p.grad) for name, p in named]
    sources += [(name + " " + key, states[name][key]) for name, _ in named for key in ("exp_avg", "exp_avg_sq")]
    _disjoint(sources)
    before_state = frozen_state_hash(states)
    before_parameters = digest({name: tensor_hash(p) for name, p in named})
    before_gradients = digest({name: tensor_hash(p.grad) for name, p in named})
    clones = []
    for name, parameter in named:
        q = torch.nn.Parameter(parameter.detach().clone())
        q.grad = parameter.grad.detach().clone()
        clones.append((name, q))
    optimizer = make_optimizer(clones)
    for name, q in clones:
        optimizer.state[q] = {"exp_avg": states[name]["exp_avg"].clone(),
                              "exp_avg_sq": states[name]["exp_avg_sq"].clone(),
                              "step": torch.tensor(float(states[name]["step"]), dtype=torch.float32)}
    clone_tensors = [(name + " " + key, value) for name, q in clones for key, value in
                     (("parameter", q), ("gradient", q.grad), *optimizer.state[q].items())]
    _disjoint(clone_tensors, forbidden=[value for _, value in sources])
    cloned_parameters = digest({name: tensor_hash(q) for name, q in clones})
    cloned_gradients = digest({name: tensor_hash(q.grad) for name, q in clones})
    cloned_moments = frozen_state_hash(_native_state(clones, optimizer))
    if (cloned_parameters != before_parameters or cloned_gradients != before_gradients
            or cloned_moments != before_state):
        raise ValueError("optimizer clones differ from source theta/gradient/moments/step")
    initial_hash = state_hash(clones, optimizer)
    expected_initial_hash = digest({name: {"parameter": tensor_hash(p),
        "exp_avg": tensor_hash(states[name]["exp_avg"]),
        "exp_avg_sq": tensor_hash(states[name]["exp_avg_sq"]), "step": states[name]["step"]}
        for name, p in named})
    if initial_hash != expected_initial_hash:
        raise ValueError("cloned full initial state differs from source")
    inputs = capture_step_inputs(clones, optimizer)
    if dense_updates is not None:
        if not isinstance(dense_updates, dict) or set(dense_updates) != {name for name, _ in named}:
            raise ValueError("dense update reference names are incomplete")
        for name, p in named:
            _tensor(dense_updates[name], shape=p.shape, label="dense update reference")
    optimizer.step()
    checker = check_native_step(inputs, clones, optimizer)
    rows, retained = [], {} if dense_updates is None else dense_updates
    for (name, parameter), (_, q), receipt in zip(named, clones, checker["per_parameter"]):
        delta = (q.detach() - parameter.detach()).contiguous()
        if dense_updates is None:
            retained[name] = delta.clone()
        comparison = update_metrics(retained[name].numpy(), delta.numpy())
        rows.append({"name": name, "shape": list(q.shape), "elements": q.numel(), **comparison,
            "parameter_sha256_before": tensor_hash(parameter), "parameter_sha256_after": tensor_hash(q),
            "gradient_sha256": tensor_hash(parameter.grad), "reference_update_sha256": tensor_hash(retained[name]),
            "candidate_update_sha256": tensor_hash(delta), "optimizer_step": receipt["optimizer_step"],
            "exp_avg_sha256": receipt["output_sha256"]["exp_avg"], "exp_avg_sq_sha256": receipt["output_sha256"]["exp_avg_sq"],
            "numpy_reference_sha256": receipt["numpy_reference_sha256"], "numpy_reference_parity": receipt["numpy_reference_parity"]})
    if (before_state != frozen_state_hash(states) or before_parameters != digest({n: tensor_hash(p) for n, p in named})
            or before_gradients != digest({n: tensor_hash(p.grad) for n, p in named})):
        raise ValueError("clone step mutated source parameters, gradients or frozen state")
    record = {"update_comparison": {"per_parameter": rows, "aggregate": aggregate_metrics(rows)},
              "initial_state_sha256": before_state, "initial_parameter_sha256": before_parameters,
              "initial_parameter_clone_sha256": cloned_parameters,
              "initial_gradient_clone_sha256": cloned_gradients,
              "initial_optimizer_clone_sha256": cloned_moments,
              "initial_full_state_sha256": initial_hash, "clone_storages_disjoint": True,
              "input_steps": {name: inputs[name]["step"] for name, _ in named},
              "optimizer_steps": {row["name"]: row["optimizer_step"] for row in checker["per_parameter"]},
              "native_optimizer_steps": 1, "numpy_all_parameter_and_moment_checks_passed": True,
              "checker_receipts": checker, "sources_unchanged": True}
    json.dumps(record, allow_nan=False)
    return record, retained
