"""SaveScope: one predeclared zero-state AdamW update fidelity diagnostic.

Actual optimizer steps operate on disjoint clones. The pretrained model stays fixed.
NumPy equations are independent of the native optimizer implementation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

import numpy as np

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import activation_attention_gradient_probe as attention
from experiments.activation_training_probe import (
    batch_schedule, canonical, digest, file_hash, load_data, parameter_hash,
    require_torch, verify_model_assets, write_json,
)
from experiments.activation_gradient_probe import parameter_comparison, tensor_hash
from experiments.activation_norm_gradient_probe import validate_norm_coverage

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
METHODS = attention.METHODS
SEEDS = attention.SEEDS
SOURCE_PATHS = ("experiments/activation_update_probe.py", "tests/test_activation_update.py", *attention.SOURCE_PATHS)
OPTIMIZER = {"name": "AdamW", "learning_rate": 1e-4, "betas": [0.9, 0.999],
             "epsilon": 1e-8, "weight_decay": 0.01, "foreach": False, "fused": False,
             "amsgrad": False, "maximize": False, "capturable": False, "differentiable": False}
GATE = {"max_relative_l2_to_dense": 0.1, "min_cosine_to_dense": 0.99,
        "max_treatment_to_norm_only_relative_l2": 0.5,
        "cosine_no_worse_than_norm_only": True, "require_all_seeds": True}


def numpy_adamw_step(theta, gradient, *, exp_avg=None, exp_avg_sq=None, step=0,
                     learning_rate=1e-4, betas=(0.9, 0.999), epsilon=1e-8, weight_decay=0.01):
    """Independent float64 decoupled AdamW equations, including absent-gradient semantics."""
    theta = np.asarray(theta, dtype=np.float64)
    if not np.isfinite(theta).all() or type(step) is not int or step < 0:
        raise ValueError("finite parameters and a nonnegative integer step required")
    b1, b2 = betas
    if not (0 <= b1 < 1 and 0 <= b2 < 1 and learning_rate >= 0 and epsilon > 0 and weight_decay >= 0):
        raise ValueError("invalid AdamW hyperparameters")
    if not all(math.isfinite(x) for x in (b1, b2, learning_rate, epsilon, weight_decay)):
        raise ValueError("nonfinite AdamW hyperparameters")
    m = np.zeros_like(theta) if exp_avg is None else np.asarray(exp_avg, dtype=np.float64)
    v = np.zeros_like(theta) if exp_avg_sq is None else np.asarray(exp_avg_sq, dtype=np.float64)
    if m.shape != theta.shape or v.shape != theta.shape or not np.isfinite(m).all() or not np.isfinite(v).all() or (v < 0).any():
        raise ValueError("invalid AdamW moments")
    if gradient is None:
        return {"parameter": theta.copy(), "exp_avg": m.copy(), "exp_avg_sq": v.copy(), "step": step}
    g = np.asarray(gradient, dtype=np.float64)
    if g.shape != theta.shape or not np.isfinite(g).all():
        raise ValueError("finite matching gradient required")
    m1 = b1 * m + (1 - b1) * g
    v1 = b2 * v + (1 - b2) * g * g
    t = step + 1
    update = learning_rate * (m1 / (1 - b1 ** t)) / (np.sqrt(v1 / (1 - b2 ** t)) + epsilon)
    parameter = theta * (1 - learning_rate * weight_decay) - update
    if not all(np.isfinite(x).all() for x in (m1, v1, parameter)):
        raise ValueError("nonfinite AdamW reference result")
    return {"parameter": parameter, "exp_avg": m1, "exp_avg_sq": v1, "step": t}


def _derived(stats):
    rn, cn, dn = (math.sqrt(stats[k]) for k in ("reference_sum_squares", "candidate_sum_squares", "difference_sum_squares"))
    return {**stats, "reference_l2": rn, "candidate_l2": cn, "difference_l2": dn,
            "relative_l2": dn / rn if rn else (0.0 if dn == 0 else None),
            "cosine_similarity": max(-1.0, min(1.0, stats["dot_product"] / (rn * cn))) if rn and cn else (1.0 if rn == cn else 0.0)}


def update_metrics(reference, candidate):
    a, b = np.asarray(reference, dtype=np.float64), np.asarray(candidate, dtype=np.float64)
    if a.shape != b.shape or a.size == 0 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("finite nonempty matching updates required")
    d = b - a
    return _derived({"reference_sum_squares": float(np.sum(a * a, dtype=np.float64)),
                     "candidate_sum_squares": float(np.sum(b * b, dtype=np.float64)),
                     "difference_sum_squares": float(np.sum(d * d, dtype=np.float64)),
                     "dot_product": float(np.sum(a * b, dtype=np.float64)),
                     "max_absolute_difference": float(np.max(np.abs(d)))})


def aggregate_metrics(records):
    keys = ("reference_sum_squares", "candidate_sum_squares", "difference_sum_squares", "dot_product")
    return _derived({**{k: math.fsum(r[k] for r in records) for k in keys},
                     "max_absolute_difference": max(r["max_absolute_difference"] for r in records)})


def update_fidelity_gate(records):
    baseline, treatment = [r["update_comparison"]["aggregate"] for r in records[1:]]
    a, b = baseline["relative_l2"], treatment["relative_l2"]
    ca, cb = baseline["cosine_similarity"], treatment["cosine_similarity"]
    finite = lambda x: x is not None and math.isfinite(x)
    ratio = b / a if finite(a) and finite(b) and a > 0 and b >= 0 else None
    if ratio is not None and not math.isfinite(ratio):
        ratio = None
    errors = finite(b) and b <= GATE["max_relative_l2_to_dense"]
    direction = finite(cb) and cb >= GATE["min_cosine_to_dense"]
    dominance = ratio is not None and ratio <= GATE["max_treatment_to_norm_only_relative_l2"] and finite(ca) and finite(cb) and cb >= ca
    return {"absolute_error_passed": errors, "absolute_direction_passed": direction,
            "relative_dominance_passed": dominance, "treatment_to_norm_only_relative_l2_ratio": ratio,
            "passed": bool(errors and direction and dominance)}


def reference_bound(actual, expected, original=None):
    actual, expected = np.asarray(actual, dtype=np.float64), np.asarray(expected, dtype=np.float64)
    scale = np.abs(expected) if original is None else np.abs(original) + np.abs(expected - original)
    tolerance = 8 * np.finfo(np.float32).eps * scale + 8 * np.finfo(np.float32).tiny
    error = np.abs(actual - expected)
    if actual.shape != expected.shape or not np.isfinite(actual).all() or not np.isfinite(expected).all() or (error > tolerance).any():
        raise ValueError("native AdamW differs from independent NumPy rounding bound")
    return {"passed": True, "max_absolute_error": float(error.max()),
            "max_fraction_of_allowed_error": float(np.max(error / tolerance))}


def _array_hash(array):
    a = np.ascontiguousarray(array)
    return digest({"dtype": str(a.dtype), "shape": list(a.shape), "data_sha256": hashlib.sha256(a.tobytes()).hexdigest()})


def adamw_step_clones(named_parameters, dense_updates=None):
    """Execute one real native step on disjoint clones and return every parameter's receipts.

    Returns (record, dense_update_reference). The input model and its gradients remain unchanged.
    This function is also usable with a caller's own named CPU float32 parameters.
    """
    torch = require_torch()
    named = list(named_parameters)
    if not named or len({n for n, _ in named}) != len(named):
        raise ValueError("unique nonempty named parameter sequence required")
    clones = []
    original_storages = {p.untyped_storage().data_ptr() for _, p in named}
    original_storages.update(p.grad.untyped_storage().data_ptr() for _, p in named if p.grad is not None)
    allocated = set()
    before = {}
    for name, p in named:
        if p.device.type != "cpu" or p.dtype != torch.float32 or p.grad is None or not bool(torch.isfinite(p.grad).all()):
            raise ValueError("finite CPU float32 gradients required for every parameter")
        q = torch.nn.Parameter(p.detach().clone())
        q.grad = p.grad.detach().clone()
        for value in (q, q.grad):
            ptr = value.untyped_storage().data_ptr()
            if ptr in original_storages or ptr in allocated:
                raise ValueError("optimizer clone storage aliases another input")
            allocated.add(ptr)
        before[name] = tensor_hash(q)
        if not torch.equal(q, p) or not torch.equal(q.grad, p.grad):
            raise ValueError("optimizer input clone differs")
        clones.append(q)
    optimizer = torch.optim.AdamW(clones, lr=OPTIMIZER["learning_rate"], betas=tuple(OPTIMIZER["betas"]),
        eps=OPTIMIZER["epsilon"], weight_decay=OPTIMIZER["weight_decay"], foreach=False, fused=False,
        amsgrad=False, maximize=False, capturable=False, differentiable=False)
    for q in clones:
        state = optimizer.state[q]
        state.update(step=torch.tensor(0.0), exp_avg=torch.zeros_like(q), exp_avg_sq=torch.zeros_like(q))
        for value in (state["exp_avg"], state["exp_avg_sq"]):
            ptr = value.untyped_storage().data_ptr()
            if ptr in original_storages or ptr in allocated or bool(value.any()):
                raise ValueError("optimizer initial moments alias or are nonzero")
            allocated.add(ptr)
    optimizer.step()
    per_parameter, retained = [], {} if dense_updates is None else dense_updates
    for (name, p), q in zip(named, clones):
        state = optimizer.state[q]
        if float(state["step"]) != 1 or not bool(torch.isfinite(q).all()):
            raise ValueError("invalid native first AdamW step")
        theta = p.detach().numpy().astype(np.float64)
        reference = numpy_adamw_step(theta, p.grad.detach().numpy(), learning_rate=OPTIMIZER["learning_rate"],
            betas=OPTIMIZER["betas"], epsilon=OPTIMIZER["epsilon"], weight_decay=OPTIMIZER["weight_decay"])
        parity = {"parameter": reference_bound(q.detach().numpy(), reference["parameter"], theta),
                  "exp_avg": reference_bound(state["exp_avg"].numpy(), reference["exp_avg"]),
                  "exp_avg_sq": reference_bound(state["exp_avg_sq"].numpy(), reference["exp_avg_sq"])}
        delta = (q.detach() - p.detach()).contiguous()
        if dense_updates is None:
            retained[name] = delta.clone()
        ref = retained[name]
        metrics = update_metrics(ref.numpy(), delta.numpy())
        per_parameter.append({"name": name, "shape": list(p.shape), "elements": p.numel(), **metrics,
            "reference_update_sha256": tensor_hash(ref), "candidate_update_sha256": tensor_hash(delta),
            "parameter_sha256_before": before[name], "parameter_sha256_after": tensor_hash(q),
            "gradient_sha256": tensor_hash(p.grad), "exp_avg_sha256": tensor_hash(state["exp_avg"]),
            "exp_avg_sq_sha256": tensor_hash(state["exp_avg_sq"]), "optimizer_step": 1,
            "numpy_reference_sha256": {k: _array_hash(v) for k, v in reference.items() if k != "step"},
            "numpy_reference_parity": parity})
    return {"update_comparison": {"per_parameter": per_parameter, "aggregate": aggregate_metrics(per_parameter)},
            "initial_parameter_clone_sha256": digest(before), "initial_optimizer_state": "all_zero_moments_step0",
            "clone_storages_disjoint": True, "native_optimizer_steps": 1,
            "numpy_all_parameter_and_moment_checks_passed": True}, retained


def validate_protocol(protocol_path, data_path, manifest_path, reference_path):
    p = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    c = p["config"]
    expected = dict(attention.preset_config())
    expected.pop("attention_save_dominance")
    expected.update(optimizer=OPTIMIZER, optimizer_context="zero-state first step only; all parameters including bias/norm share one group",
        optimizer_initial_step=0, optimizer_steps_per_arm=1, gradient_clipping=False, learning_rate_schedule=False,
        numpy_reference_dtype="float64", numpy_reference_elementwise_tolerance={"float32_epsilon_multiplier": 8, "float32_tiny_multiplier": 8}, update_gate=GATE)
    if p.get("schema_version") != 1 or c != expected or p["config_sha256"] != digest(c):
        raise ValueError("update protocol/config mismatch")
    if p["data_sha256"] != file_hash(data_path) or p["training_manifest_sha256"] != file_hash(manifest_path):
        raise ValueError("update data/manifest pin mismatch")
    for name in attention.SOURCE_PATHS:
        if p["source_files_sha256"].get(name) != file_hash(ROOT / name):
            raise ValueError("frozen dependency source changed: " + name)
    reference = json.loads(Path(reference_path).read_text(encoding="utf-8"))
    if reference["config"] != attention.preset_config() or reference["stable_result_sha256"] != digest(reference["stable_results"]):
        raise ValueError("invalid attention reference")
    if reference["observation_sha256"] != digest({k: v for k, v in reference.items() if k != "observation_sha256"}):
        raise ValueError("attention reference observation hash mismatch")
    if reference["stable_results"]["source_files_sha256"] != p["source_files_sha256"]:
        raise ValueError("attention reference source chain mismatch")
    return p, reference


def _stable_gradient(record):
    return {k: v for k, v in record.items() if k not in ("timing_seconds_descriptive_only", "saved_tensor_inventory", "named_layernorm_saves", "named_attention_saves")}


def worker(model_dir, data_path, manifest_path, protocol_path, reference_path, output, seed):
    protocol, prior = validate_protocol(protocol_path, data_path, manifest_path, reference_path)
    if seed not in SEEDS:
        raise ValueError("undeclared seed")
    paired = next(w for w in prior["worker_measurements"] if w["seed"] == seed)
    arrays, _ = load_data(data_path, manifest_path)
    verify_model_assets(model_dir)
    torch = require_torch()
    from transformers import AutoModelForCausalLM
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    model = AutoModelForCausalLM.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, dtype=torch.float32, attn_implementation="eager").to(device="cpu", dtype=torch.float32)
    model.eval()
    named = list(model.named_parameters())
    for _, p in named:
        p.requires_grad_(True)
    if len(named) != 76 or sum(p.numel() for _, p in named) != 14067712:
        raise ValueError("unexpected model parameter coverage")
    cls = attention.attention_type()
    norms = [n for n, m in model.named_modules() if isinstance(m, torch.nn.LayerNorm)]
    attentions = [n for n, m in model.named_modules() if isinstance(m, cls)]
    if len(norms) != 13 or len(attentions) != 6 or model.config._attn_implementation != "eager" or any(
        (isinstance(m, torch.nn.Dropout) and m.p != 0) or (isinstance(m, cls) and m.attention_dropout != 0) for m in model.modules()):
        raise ValueError("unexpected model save scope/dropout/attention")
    runtime = {"torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version(),
        "transformers": importlib.metadata.version("transformers"), "attention_class": attention.ATTENTION_CLASS_NAME,
        "attention_class_source_sha256": file_hash(sys.modules[cls.__module__].__file__), "system": platform.system(),
        "machine": platform.machine(), "device": "cpu", "threads": 1, "deterministic_algorithms": torch.are_deterministic_algorithms_enabled()}
    if runtime != paired["runtime"]:
        raise ValueError("supply an attention reference replayed in this same runtime")
    schedule = batch_schedule(8, 24, 2, seed)
    tokens = torch.from_numpy(arrays["train"][schedule[0]])
    initial = parameter_hash(model)
    if initial != paired["initial_parameter_sha256"] or schedule[0] != paired["batch_indices"] or tensor_hash(tokens) != paired["batch_tokens_sha256"]:
        raise ValueError("attention comparison initial/input mismatch")
    Path(output).mkdir(parents=True, exist_ok=True)
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    started = time.perf_counter()
    timer = threading.Timer(180, attention._budget_exit)
    timer.daemon = True
    references = updates = None
    records = []
    timer.start()
    try:
        for method in METHODS:
            before = parameter_hash(model)
            gradient = attention.backward_once(model, tokens, method)
            validate_norm_coverage(gradient, norms, method)
            attention.validate_attention_coverage(gradient, attentions, method)
            if references is None:
                references = {n: p.grad.detach().clone() for n, p in named}
            gradient["parameter_gradient_comparison"] = parameter_comparison(model, references)
            after = parameter_hash(model)
            gradient.update(parameter_sha256_before=before, parameter_sha256_after=after)
            previous = next(r for r in paired["methods"] if r["method"] == method)
            if before != initial or after != initial or _stable_gradient(gradient) != _stable_gradient(previous):
                raise ValueError("fixed model/gradient does not match prior attention diagnostic")
            relative = gradient["observed_vs_analytic_logits_gradient"]["relative_l2"]
            if relative is None or not math.isfinite(relative) or relative > 1e-5:
                raise ValueError("exact CE analytical control failed")
            measurement, retained = adamw_step_clones(named, updates)
            if updates is None:
                updates = retained
            if parameter_hash(model) != initial:
                raise ValueError("optimizer modified original model")
            records.append({"method": method, "gradient_diagnostic": gradient, **measurement})
    finally:
        timer.cancel()
    elapsed = time.perf_counter() - started
    if elapsed > 180 or len({r["initial_parameter_clone_sha256"] for r in records}) != 1:
        raise ValueError("worker budget or common optimizer starting parameters failed")
    result = {"seed": seed, "completed": True, "pid": os.getpid(), "started_at": started_at,
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "wall_seconds_descriptive_only": elapsed,
        "batch_indices": schedule[0], "batch_tokens_sha256": tensor_hash(tokens), "schedule_sha256": digest(schedule),
        "target_positions_per_method": 128, "initial_parameter_sha256": initial,
        "data_sha256": file_hash(data_path), "training_manifest_sha256": file_hash(manifest_path),
        "protocol_sha256": file_hash(protocol_path), "config_sha256": protocol["config_sha256"],
        "attention_reference_file_sha256": file_hash(reference_path), "attention_reference_stable_sha256": prior["stable_result_sha256"],
        "source_files_sha256": {p: file_hash(ROOT / p) for p in SOURCE_PATHS},
        "all_gradient_records_match_attention_reference": True, "original_model_unchanged": True,
        "methods": records, "update_fidelity_gate": update_fidelity_gate(records), "runtime": runtime}
    write_json(Path(output) / "worker.json", result)
    return result


def run_probe(model_dir, data_path, manifest_path, protocol_path, reference_path, output):
    protocol, prior = validate_protocol(protocol_path, data_path, manifest_path, reference_path)
    verify_model_assets(model_dir)
    output = Path(output).resolve()
    if (output / "report.json").exists() or (output / "workers").exists():
        raise ValueError("fresh output directory required")
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({k: "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    workers = []
    for seed in SEEDS:
        directory = output / "workers" / f"seed-{seed}"
        command = [sys.executable, str(SCRIPT), "--model-dir", str(Path(model_dir).resolve()),
            "--data", str(Path(data_path).resolve()), "--manifest", str(Path(manifest_path).resolve()),
            "--protocol", str(Path(protocol_path).resolve()), "--attention-reference", str(Path(reference_path).resolve()),
            "--output", str(directory), "--seed", str(seed)]
        child = subprocess.run(command, env=env, capture_output=True, text=True, timeout=300, check=False)
        if child.returncode:
            raise RuntimeError(f"update worker {seed} failed (exit={child.returncode}): {child.stderr[-4000:]}")
        w = json.loads((directory / "worker.json").read_text(encoding="utf-8"))
        if not w["completed"] or [m["method"] for m in w["methods"]] != list(METHODS):
            raise ValueError("incomplete update worker")
        w["worker_record_file"] = (directory / "worker.json").relative_to(output).as_posix()
        workers.append(w)
    stable_workers = []
    for w in workers:
        item = {k: w[k] for k in ("seed", "batch_indices", "batch_tokens_sha256", "schedule_sha256", "initial_parameter_sha256", "update_fidelity_gate")}
        item["methods"] = [{**{k: v for k, v in m.items() if k != "gradient_diagnostic"},
                             "gradient_diagnostic": _stable_gradient(m["gradient_diagnostic"])} for m in w["methods"]]
        stable_workers.append(item)
    stable = {"config_sha256": protocol["config_sha256"], "protocol_sha256": file_hash(protocol_path),
        "data_sha256": file_hash(data_path), "training_manifest_sha256": file_hash(manifest_path),
        "source_files_sha256": {p: file_hash(ROOT / p) for p in SOURCE_PATHS},
        "attention_reference_stable_sha256": prior["stable_result_sha256"], "workers": stable_workers,
        "update_fidelity_gate_passed_all_seeds": all(w["update_fidelity_gate"]["passed"] for w in workers)}
    report = {"schema_version": 1, "config": protocol["config"], "stable_results": stable,
        "stable_result_sha256": digest(stable), "worker_measurements": workers,
        "scientific_gate_failure_is_valid_completed_result": True, "limitations": protocol["limitations"]}
    report["observation_sha256"] = digest(report)
    write_json(output / "report.json", report)
    lines = ["# AdamW first-step update fidelity", "", "One fixed-point diagnostic; zero optimizer state and weight decay 0.01. The model remains unchanged.", "", "| Seed | Norm-only update relative L2 | Attention-preserved update relative L2 | Treatment cosine | Error ratio | Joint gate |", "| --- | --- | --- | --- | --- | --- |"]
    for w in workers:
        a, b = [m["update_comparison"]["aggregate"] for m in w["methods"][1:]]
        g = w["update_fidelity_gate"]
        fmt = lambda v: "undefined" if v is None else format(v, ".9g")
        lines.append(f"| {w['seed']} | {fmt(a['relative_l2'])} | {fmt(b['relative_l2'])} | {fmt(b['cosine_similarity'])} | {fmt(g['treatment_to_norm_only_relative_l2_ratio'])} | {g['passed']} |")
    lines += ["", f"All three batches pass: **{stable['update_fidelity_gate_passed_all_seeds']}**.", "", "All native parameter/moment updates passed independent NumPy rounding bounds. All 76 gradient records matched the same-runtime attention diagnostic in every arm. The 3 batches overlap (320 unique target positions).", "", "The joint gate requires treatment update relative L2 <= 0.10, cosine >= 0.99, and at most half the norm-only error with cosine no worse in every batch. A failed scientific gate is retained without retuning.", "", "No accumulated optimizer state, holdout evaluation, convergence, training quality, lower cost, GPU or AttnRes conclusion. Full parameter/moment clones and retained dense references add diagnostic cost.", "", f"Stable SHA-256: `{report['stable_result_sha256']}`", f"Observation SHA-256: `{report['observation_sha256']}`", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model-dir", "data", "manifest", "protocol", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--attention-reference", type=Path, default=ROOT / "results/activation-attention-gradient/report.json")
    parser.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.seed is not None:
        worker(args.model_dir, args.data, args.manifest, args.protocol, args.attention_reference, args.output, args.seed)
    else:
        report = run_probe(args.model_dir, args.data, args.manifest, args.protocol, args.attention_reference, args.output)
        print(canonical({"report": str(args.output / "report.json"), "stable_result_sha256": report["stable_result_sha256"], "gate_passed": report["stable_results"]["update_fidelity_gate_passed_all_seeds"]}))


if __name__ == "__main__":
    main()
