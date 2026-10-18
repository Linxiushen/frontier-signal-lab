"""Strict snapshots of caller AdamW state for one common-state CPU diagnostic.

No ML library is imported at module import time. Caller objects are inspected,
never stepped or loaded. This is not a checkpoint loader or a training runner.
"""
from __future__ import annotations

import copy
from collections import defaultdict
import hashlib
import json
import math
import sys


def _error(message):
    from .audit import SaveScopeError
    return SaveScopeError(message)


def _storage(tensor):
    return (str(tensor.device), tensor.untyped_storage().data_ptr())


def _tensor_record(tensor):
    return (tensor, tensor.detach().clone(), tensor._version, _storage(tensor),
            tensor.storage_offset(), tuple(tensor.shape), tuple(tensor.stride()),
            tensor.dtype, tensor.requires_grad)


def _tensor_unchanged(torch, record):
    tensor, value, version, storage, offset, shape, stride, dtype, grad = record
    return (tensor._version == version and _storage(tensor) == storage
            and tensor.storage_offset() == offset and tuple(tensor.shape) == shape
            and tuple(tensor.stride()) == stride and tensor.dtype == dtype
            and tensor.requires_grad == grad and torch.equal(tensor, value))


def _same_options(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(_same_options(actual[k], v) for k, v in expected.items())
    if isinstance(expected, (tuple, list)):
        return len(actual) == len(expected) and all(_same_options(a, b) for a, b in zip(actual, expected))
    return actual == expected


def _hooks(optimizer):
    module = sys.modules.get("torch.optim.optimizer")
    return [(optimizer, "_optimizer_step_pre_hooks"), (optimizer, "_optimizer_step_post_hooks"),
            (module, "_global_optimizer_pre_hooks"), (module, "_global_optimizer_post_hooks")]


def _plain_step(torch, optimizer):
    if type(optimizer) is not torch.optim.AdamW:
        raise _error("optimizer must be an exact torch.optim.AdamW instance")
    if "step" in optimizer.__dict__:
        raise _error("custom AdamW step is unsupported")
    method = getattr(optimizer.step, "__func__", None)
    if (method is not torch.optim.AdamW.step or getattr(method, "__name__", None) != "step"
            or getattr(method, "__module__", None) not in ("torch.optim.adam", "torch.optim.adamw")):
        raise _error("custom AdamW step is unsupported")
    if any(getattr(owner, name, None) for owner, name in _hooks(optimizer)):
        raise _error("AdamW step hooks are unsupported")
    if any(hasattr(optimizer, name) for name in ("grad_scale", "found_inf")):
        raise _error("AdamW AMP step state is unsupported")
    if getattr(optimizer, "_step_supports_amp_scaling", False):
        raise _error("AdamW AMP step policy is unsupported")
    return method


def _options(group):
    from .audit import _optimizer_options
    allowed = {"params", "lr", "betas", "eps", "weight_decay", "amsgrad", "maximize",
               "foreach", "capturable", "differentiable", "fused", "decoupled_weight_decay"}
    if set(group) - allowed:
        raise _error("unsupported AdamW group options: " + ", ".join(sorted(set(group) - allowed)))
    if not {"lr", "betas", "eps", "weight_decay"} <= set(group):
        raise _error("AdamW group is missing required options")
    for key in ("amsgrad", "maximize", "capturable", "differentiable"):
        if group.get(key, False) is not False:
            raise _error("unsupported AdamW flag: " + key)
    for key in ("foreach", "fused"):
        if group.get(key) is not None and group.get(key) is not False:
            raise _error("unsupported AdamW flag: " + key)
    if "decoupled_weight_decay" in group and group["decoupled_weight_decay"] is not True:
        raise _error("AdamW requires decoupled weight decay")
    return _optimizer_options({key: group[key] for key in ("lr", "betas", "eps", "weight_decay")})


def snapshot_adamw(torch, named, optimizer, *, protected_tensors=()):
    """Validate and privately copy one exact single-group AdamW before callbacks.

    The group must contain every supplied trainable Parameter exactly once.
    Its order may differ: mapping is by object identity, never state_dict index.
    Missing state and an explicit empty dict both mean native lazy state.
    Initialized state consists exactly of step/exp_avg/exp_avg_sq. Counters are
    integral CPU float32/float64 scalar tensors below 2**24. Source state may
    not alias supplied parameters/protected registered tensors, existing
    Parameter gradients, or other state tensors. The audit caller supplies all
    registered parameters and buffers, including frozen parameters.
    """
    method = _plain_step(torch, optimizer)
    named = list(named)
    if not named or len({name for name, _ in named}) != len(named):
        raise _error("AdamW requires unique trainable parameter names")
    if len({id(p) for _, p in named}) != len(named) or any(
            type(p) is not torch.nn.Parameter or not p.requires_grad for _, p in named):
        raise _error("AdamW requires unique trainable Parameter identities")
    for _, p in named:
        if p.device.type != "cpu" or p.layout != torch.strided or p.dtype != torch.float32:
            raise _error("AdamW parameters must be CPU strided float32")
        if not bool(torch.isfinite(p).all()):
            raise _error("AdamW parameters must be finite")
    if type(optimizer.param_groups) is not list or len(optimizer.param_groups) != 1:
        raise _error("AdamW requires exactly one parameter group")
    group = optimizer.param_groups[0]
    if type(group) is not dict or type(group.get("params")) is not list:
        raise _error("AdamW group and params must be ordinary dict/list")
    params = group["params"]
    if len(params) != len(named) or {id(p) for p in params} != {id(p) for _, p in named}:
        raise _error("AdamW group must cover the exact trainable model parameters once")
    options = _options(group)
    _options(optimizer.defaults)
    if type(optimizer.state) not in (dict, defaultdict):
        raise _error("AdamW state mapping must be an ordinary dict/defaultdict")
    if any(id(p) not in {id(q) for _, q in named} for p in optimizer.state):
        raise _error("AdamW contains foreign optimizer state")
    protected = [p for _, p in named] + list(protected_tensors)
    occupied = {_storage(t) for t in protected if t.numel()}
    occupied.update(_storage(p.grad) for p in protected if isinstance(p, torch.nn.Parameter)
                    and p.grad is not None and p.grad.numel())
    snapshots, records = {}, []
    for name, p in named:
        state = optimizer.state.get(p)
        if p in optimizer.state and type(state) is not dict:
            raise _error("AdamW parameter state must be an ordinary dict")
        if not state:
            snapshots[name] = {"initialized": False, "step": 0}
            records.append((p, state, {}))
            continue
        if set(state) != {"step", "exp_avg", "exp_avg_sq"}:
            raise _error("AdamW initialized state requires exactly step/exp_avg/exp_avg_sq")
        step = state["step"]
        if (type(step) is not torch.Tensor or step.device.type != "cpu" or step.ndim != 0
                or step.layout != torch.strided or step.dtype not in (torch.float32, torch.float64)
                or step.requires_grad):
            raise _error("AdamW step must be a CPU float32/float64 scalar tensor")
        counter = float(step)
        if not math.isfinite(counter) or counter != int(counter) or not 0 <= counter < 2**24:
            raise _error("AdamW step must be integral and in [0, 2**24)")
        tensor_records = {}
        for key in ("step", "exp_avg", "exp_avg_sq"):
            tensor = state[key]
            if type(tensor) is not torch.Tensor:
                raise _error("AdamW state values must be tensors")
            if key != "step" and (tensor.device.type != "cpu" or tensor.layout != torch.strided
                    or tensor.dtype != torch.float32 or tensor.shape != p.shape or tensor.requires_grad
                    or not bool(torch.isfinite(tensor).all())):
                raise _error("AdamW moments must be finite CPU strided float32 with parameter shape")
            if tensor.numel():
                storage = _storage(tensor)
                if storage in occupied:
                    raise _error("AdamW source state aliases parameters, gradients or other state")
                occupied.add(storage)
            tensor_records[key] = _tensor_record(tensor)
        if bool((state["exp_avg_sq"] < 0).any()):
            raise _error("AdamW second moment must be nonnegative")
        if counter == 0 and (bool((state["exp_avg"] != 0).any()) or bool((state["exp_avg_sq"] != 0).any())):
            raise _error("AdamW step zero requires zero moments")
        snapshots[name] = {"initialized": True, "step": int(counter),
                           **{key: state[key].detach().clone() for key in state}}
        snapshots[name]["counter"] = int(counter)
        records.append((p, state, tensor_records))
    return _Snapshot(torch, named, optimizer, group, options, snapshots, records, method, occupied)


class _Snapshot:
    def __init__(self, torch, named, optimizer, group, options, snapshots, records, method, source_storages):
        from .audit import _hash_tensor
        self._torch, self._named, self._optimizer = torch, named, optimizer
        self._group, self._groups, self._params = group, optimizer.param_groups, group["params"]
        self._param_order = list(group["params"])
        self._group_options = copy.deepcopy({k: v for k, v in group.items() if k != "params"})
        self._defaults, self._default_values = optimizer.defaults, copy.deepcopy(optimizer.defaults)
        self._state, self._state_keys = optimizer.state, list(optimizer.state)
        self._options, self._snapshots, self._records, self._method = options, snapshots, records, method
        self._source_storages = source_storages.copy()
        self._hook_records = [(owner, name, getattr(owner, name, None)) for owner, name in _hooks(optimizer)]
        rows = []
        for name, parameter in named:
            state = snapshots[name]
            rows.append({"name": name, "initialized": state["initialized"],
                         "step": state.get("counter", 0), "parameter_sha256": _hash_tensor(parameter),
                         **({key + "_sha256": _hash_tensor(state[key]) for key in ("step", "exp_avg", "exp_avg_sq")}
                            if state["initialized"] else {})})
        self._receipt = {"kind": "caller_adamw_single_group_snapshot", "mapping": "exact Parameter object identities",
                         "options": copy.deepcopy(options), "parameters": rows,
                         "state_policy": "missing/empty is lazy; initialized step/exp_avg/exp_avg_sq copied separately per arm",
                         "caller_optimizer_stepped": False, "source_state_storages_disjoint": True,
                         "alias_check_scope": "trainable parameters, supplied registered protected tensors, existing Parameter gradients and all state tensors"}
        payload = json.dumps(self._receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        self._receipt["payload_sha256"] = hashlib.sha256(payload).hexdigest()

    @property
    def options(self):
        return copy.deepcopy(self._options)

    @property
    def receipt(self):
        return copy.deepcopy(self._receipt)

    def assert_unchanged(self):
        opt, torch = self._optimizer, self._torch
        changed = (opt.param_groups is not self._groups or len(opt.param_groups) != 1
                   or opt.param_groups[0] is not self._group or self._group.get("params") is not self._params
                   or len(self._params) != len(self._param_order)
                   or any(a is not b for a, b in zip(self._params, self._param_order))
                   or not _same_options({k: v for k, v in self._group.items() if k != "params"}, self._group_options)
                   or opt.defaults is not self._defaults or not _same_options(opt.defaults, self._default_values)
                   or opt.state is not self._state or [id(p) for p in opt.state] != [id(p) for p in self._state_keys])
        if changed:
            raise _error("caller AdamW group/options/state mapping mutated during audit")
        if _plain_step(torch, opt) is not self._method or any(
                getattr(owner, name, None) is not hooks for owner, name, hooks in self._hook_records):
            raise _error("caller AdamW step policy mutated during audit")
        for p, original, tensors in self._records:
            current = opt.state.get(p)
            if current is not original or (current is not None and set(current) != set(tensors)):
                raise _error("caller AdamW state objects mutated during audit")
            for key, record in tensors.items():
                if current[key] is not record[0] or not _tensor_unchanged(torch, record):
                    raise _error("caller AdamW state tensors mutated during audit")

    def step(self, torch, np, named, gradients, present):
        from .audit import _hash_tensor, _metrics, _summary
        self.assert_unchanged()
        named, gradients = list(named), list(gradients)
        if (len(named) != len(self._named) or len(gradients) != len(named)
                or any(n != old or p is not original for (n, p), (old, original) in zip(named, self._named))
                or set(present) != {name for name, _ in named}):
            raise _error("AdamW step input identities differ from snapshot")
        originals = self._source_storages.copy()
        originals.update(_storage(t) for state in self._snapshots.values() for t in state.values()
                         if isinstance(t, torch.Tensor) and t.numel())
        allocated, clones, before = set(), [], []
        for (name, p), (other, gradient) in zip(named, gradients):
            if (name != other or type(present[name]) is not bool or gradient.shape != p.shape
                    or gradient.device.type != "cpu" or gradient.layout != torch.strided
                    or gradient.dtype != torch.float32 or not bool(torch.isfinite(gradient).all())):
                raise _error("AdamW gradient names/shapes/types must match the snapshot")
            clone = torch.nn.Parameter(p.detach().clone())
            clone.grad = gradient.detach().clone() if present[name] else None
            for tensor in (clone, clone.grad):
                if tensor is not None and tensor.numel():
                    storage = _storage(tensor)
                    if storage in allocated or storage in originals:
                        raise _error("AdamW private clone aliases source or another clone")
                    allocated.add(storage)
            clones.append(clone)
            before.append((name, p.detach().clone()))
        private = torch.optim.AdamW(clones, **self._options, foreach=False, fused=False)
        for (name, _), clone in zip(named, clones):
            source = self._snapshots[name]
            if source["initialized"]:
                private.state[clone] = {key: source[key].clone() for key in ("step", "exp_avg", "exp_avg_sq")}
                for tensor in private.state[clone].values():
                    if tensor.numel():
                        storage = _storage(tensor)
                        if storage in originals or storage in allocated:
                            raise _error("AdamW private state clone aliases source or another clone")
                        allocated.add(storage)
        private.step()
        updates = [(name, clone.detach().clone() - value) for (name, value), clone in zip(before, clones)]
        controls, expected_deltas = [], []
        for (name, theta), (_, gradient), clone in zip(before, gradients, clones):
            source, native = self._snapshots[name], private.state.get(clone, {})
            theta64, g = theta.numpy().astype(np.float64), gradient.numpy().astype(np.float64)
            m0 = source["exp_avg"].numpy().astype(np.float64) if source["initialized"] else np.zeros_like(theta64)
            v0 = source["exp_avg_sq"].numpy().astype(np.float64) if source["initialized"] else np.zeros_like(theta64)
            old_step = source.get("counter", 0)
            counter = old_step + int(present[name])
            actual_step = float(native["step"]) if native else 0
            if actual_step != counter:
                raise _error("native accumulated AdamW step counter differs")
            if present[name]:
                b1, b2 = self._options["betas"]
                m, v = b1*m0 + (1-b1)*g, b2*v0 + (1-b2)*g*g
                m_scale, v_scale = np.abs(b1*m0) + np.abs((1-b1)*g), np.abs(b2*v0) + np.abs((1-b2)*g*g)
                dm, dv = _allowance(np, m_scale), _allowance(np, v_scale)
                def parameter(mean, square):
                    return theta64*(1-self._options["lr"]*self._options["weight_decay"]) - self._options["lr"]*(
                        mean/(1-b1**counter))/(np.sqrt(square/(1-b2**counter))+self._options["eps"])
                expected = parameter(m, v)
                corners = [parameter(mm, vv) for mm in (m-dm, m+dm)
                           for vv in (np.maximum(0, v-dv), v+dv)]
                low, high = np.minimum.reduce(corners), np.maximum.reduce(corners)
                padding = _allowance(np, np.abs(theta64) + np.maximum(np.abs(low-theta64), np.abs(high-theta64)))
                low, high = low-padding, high+padding
            else:
                m, v, expected = m0, v0, theta64.copy()
                dm, dv, low, high = np.zeros_like(m), np.zeros_like(v), theta64, theta64
            actual_m = native["exp_avg"].numpy() if native else np.zeros_like(theta64)
            actual_v = native["exp_avg_sq"].numpy() if native else np.zeros_like(theta64)
            controls.append({"name": name, "optimizer_step_before": old_step, "optimizer_step": counter,
                             "initialized_before": source["initialized"], "gradient_present": present[name],
                             "parameter_sha256_after": _hash_tensor(clone),
                             "parameter": _interval_control(np, clone.detach().numpy(), low, high, "four_corner_moment_interval"),
                             "exp_avg": _interval_control(np, actual_m, m-dm, m+dm, "input_scale_rounding"),
                             "exp_avg_sq": _interval_control(np, actual_v, v-dv, v+dv, "input_scale_rounding")})
            expected_deltas.append((name, torch.from_numpy(expected-theta64)))
        self.assert_unchanged()
        update = _summary(torch, updates)
        update.update({"executed": True, "clone_storages_disjoint": True,
                       "independent_reference": {"kind": "numpy_float64_accumulated_adamw_transition",
                         "meaning": "Captured common m/v/counter; native cloned next step checked with independent input-scale moment bounds and four-corner parameter interval. Engineering controls, not scientific fidelity thresholds.",
                         "rounding_bound": {"float32_epsilon_multiplier": 8, "float32_tiny_multiplier": 8,
                                            "moment_scale": "sum(abs(each recurrence input))", "parameter_interval": "four m/v corners plus float32 update rounding padding"},
                         "all_parameter_and_moment_checks_passed": True, "per_parameter": controls,
                         "comparison": _metrics(torch, expected_deltas, updates)}})
        return update, updates


def _allowance(np, scale):
    return 8*np.finfo(np.float32).eps*scale + 8*np.finfo(np.float32).tiny


def _interval_control(np, actual, low, high, kind):
    actual = np.asarray(actual, dtype=np.float64)
    if actual.shape != low.shape or actual.shape != high.shape:
        raise _error("native accumulated AdamW reference shape differs")
    finite = bool(np.isfinite(actual).all() and np.isfinite(low).all() and np.isfinite(high).all())
    if not finite or not bool(np.all((actual >= low) & (actual <= high))):
        raise _error("native accumulated AdamW differs from independent NumPy interval")
    middle = (low+high)/2
    return {"passed": True, "finite": True, "kind": kind,
            "max_absolute_error": float(np.max(np.abs(actual-middle))) if actual.size else 0.0,
            "max_interval_width": float(np.max(high-low)) if actual.size else 0.0}
