"""Fixed-parameter gradient diagnostic separating model and CE saved tensors.

No optimizer, holdout evaluation or training update. Uses the already published
backward-only codec; retained dense references make costs descriptive only.
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
from experiments.activation_training_probe import (
    SavedActivationCodec, batch_schedule, canonical, digest, file_hash, load_data,
    parameter_hash, require_torch, verify_model_assets, write_json,
)
from scripts.capture_real_activation import MODEL_ID, MODEL_REVISION

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]
METHODS = ("dense", "all_saved_int8", "model_saved_int8")
SEEDS = (11, 29, 47)
SOURCE_PATHS = (
    "experiments/activation_gradient_probe.py", "experiments/activation_training_probe.py",
    "scripts/capture_real_activation.py", "experiments/attnres_memory_probe.py",
    "experiments/attnres_budget_probe.py",
)


def preset_config():
    return {"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "seeds": list(SEEDS),
            "methods_in_order": list(METHODS), "batch_size": 2, "sequence_input_tokens": 64,
            "schedule_steps": 24, "schedule_selection": "first batch only", "dtype": "float32",
            "attention": "eager", "threads": 1, "min_compressed_elements": 256,
            "max_seconds_per_worker": 180, "analytic_logits_gradient_relative_l2_tolerance": 1e-5,
            "loss_save_dominance": {"max_model_only_to_all_saved_relative_l2": 0.5,
                                    "cosine_no_worse": True, "require_all_seeds": True}}


def validate_protocol(protocol_path, data_path, manifest_path):
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    if protocol.get("schema_version") != 1 or protocol.get("config") != preset_config():
        raise ValueError("protocol does not match fixed gradient diagnostic preset")
    if protocol.get("config_sha256") != digest(protocol["config"]):
        raise ValueError("protocol configuration hash mismatch")
    if protocol.get("data_sha256") != file_hash(data_path) or protocol.get("training_manifest_sha256") != file_hash(manifest_path):
        raise ValueError("protocol data/manifest hash mismatch")
    sources = protocol.get("source_files_sha256", {})
    if not isinstance(sources, dict) or not set(SOURCE_PATHS).issubset(sources):
        raise ValueError("protocol missing execution dependency source hashes")
    for name in SOURCE_PATHS:
        if sources[name] != file_hash(ROOT / name):
            raise ValueError("protocol execution source hash mismatch: " + name)
    return protocol


def tensor_hash(tensor):
    array = tensor.detach().cpu().contiguous().numpy()
    return digest({"dtype": str(array.dtype), "shape": list(array.shape),
                   "data_sha256": hashlib.sha256(array.tobytes()).hexdigest()})


def vector_metrics(reference, candidate):
    """Float64 accumulation; no one giant concatenated parameter vector."""
    torch = require_torch()
    if reference.shape != candidate.shape:
        raise ValueError("gradient shape mismatch")
    left, right = reference.detach().to(torch.float64), candidate.detach().to(torch.float64)
    delta = right - left
    values = {"reference_sum_squares": float(torch.sum(left * left)),
              "candidate_sum_squares": float(torch.sum(right * right)),
              "difference_sum_squares": float(torch.sum(delta * delta)),
              "dot_product": float(torch.sum(left * right)),
              "max_absolute_difference": float(torch.max(torch.abs(delta))) if delta.numel() else 0.0}
    return finish_metrics(values)


def finish_metrics(values):
    values = dict(values)
    rn = math.sqrt(values["reference_sum_squares"])
    cn = math.sqrt(values["candidate_sum_squares"])
    dn = math.sqrt(values["difference_sum_squares"])
    values.update(reference_l2=rn, candidate_l2=cn, difference_l2=dn,
                  relative_l2=dn / rn if rn else (0.0 if dn == 0 else None),
                  cosine_similarity=(max(-1.0, min(1.0, values["dot_product"] / (rn * cn)))
                                     if rn and cn else (1.0 if rn == cn else 0.0)))
    return values


def aggregate_metrics(items):
    keys = ("reference_sum_squares", "candidate_sum_squares", "difference_sum_squares", "dot_product")
    totals = {key: math.fsum(item[key] for item in items) for key in keys}
    totals["max_absolute_difference"] = max((item["max_absolute_difference"] for item in items), default=0.0)
    return finish_metrics(totals)


def analytic_ce_gradient(logits, targets):
    # d mean CE / d logits = (softmax(logits) - onehot(target)) / number of targets.
    torch = require_torch()
    rows = logits.detach().reshape(-1, logits.shape[-1])
    labels = targets.reshape(-1)
    gradient = torch.softmax(rows, dim=-1)
    gradient[torch.arange(len(labels), device=rows.device), labels] -= 1.0
    return (gradient / len(labels)).reshape_as(logits)


def backward_once(model, tokens, method):
    torch = require_torch()
    if method not in METHODS:
        raise ValueError("unknown gradient compression policy")
    model.zero_grad(set_to_none=True)
    parameters = [parameter for _, parameter in model.named_parameters()]
    codec = SavedActivationCodec(parameters, "dense" if method == "dense" else "int8_saved_tensors")
    started = time.perf_counter()
    with torch.autograd.graph.saved_tensors_hooks(codec.pack, codec.unpack):
        logits = model(input_ids=tokens[:, :-1], use_cache=False).logits
        if method != "model_saved_int8":
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), tokens[:, 1:].reshape(-1))
    if method == "model_saved_int8":
        loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), tokens[:, 1:].reshape(-1))
    forward_end = time.perf_counter()
    logits.retain_grad()
    loss.backward()
    backward_end = time.perf_counter()
    if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in parameters):
        raise ValueError("missing or nonfinite full-model gradient")
    if logits.grad is None or not bool(torch.isfinite(logits.grad).all()) or not math.isfinite(float(loss.detach())):
        raise ValueError("nonfinite logits gradient/loss")
    analytic = analytic_ce_gradient(logits, tokens[:, 1:])
    analytic_error = vector_metrics(analytic, logits.grad)
    rows = logits.grad.detach().reshape(-1, logits.shape[-1]).to(torch.float64).sum(dim=-1)
    analytic_rows = analytic.reshape(-1, logits.shape[-1]).to(torch.float64).sum(dim=-1)
    record = {"method": method, "logits_sha256": tensor_hash(logits), "forward_loss": float(loss.detach()),
              "logits_gradient_sha256": tensor_hash(logits.grad), "analytic_logits_gradient_sha256": tensor_hash(analytic),
              "observed_vs_analytic_logits_gradient": analytic_error,
              "observed_logits_gradient_row_sum": {"max_absolute": float(rows.abs().max()), "l2": float(torch.linalg.vector_norm(rows))},
              "analytic_logits_gradient_row_sum": {"max_absolute": float(analytic_rows.abs().max()), "l2": float(torch.linalg.vector_norm(analytic_rows))},
              "parameter_tensors_with_finite_gradients": len(parameters),
              "parameter_elements_with_finite_gradients": sum(p.numel() for p in parameters),
              "saved_tensor_inventory": codec.inventory(),
              "timing_seconds_descriptive_only": {"forward_ce_including_pack": forward_end - started,
                                                   "backward_including_unpack": backward_end - forward_end}}
    return record


def parameter_comparison(model, references):
    per_parameter = []
    for name, parameter in model.named_parameters():
        gradient = parameter.grad
        comparison = vector_metrics(references[name], gradient)
        per_parameter.append({"name": name, "shape": list(parameter.shape), "elements": parameter.numel(),
                              "reference_gradient_sha256": tensor_hash(references[name]),
                              "candidate_gradient_sha256": tensor_hash(gradient), **comparison})
    return {"aggregate": aggregate_metrics(per_parameter), "per_parameter": per_parameter}


def loss_save_gate(method_records):
    all_error = method_records[1]["parameter_gradient_comparison"]["aggregate"]
    model_error = method_records[2]["parameter_gradient_comparison"]["aggregate"]
    all_rel, model_rel = all_error["relative_l2"], model_error["relative_l2"]
    ratio = model_rel / all_rel if all_rel is not None and all_rel > 0 and model_rel is not None else None
    passed = ratio is not None and ratio <= 0.5 and model_error["cosine_similarity"] >= all_error["cosine_similarity"]
    return {"model_only_to_all_saved_relative_l2_ratio": ratio, "passed": passed,
            "meaning": "predeclared fixed-point loss-save sensitivity gate; no training-quality implication"}


def _budget_exit():
    os._exit(124)


def worker(model_dir, data_path, manifest_path, protocol_path, output, seed):
    protocol = validate_protocol(protocol_path, data_path, manifest_path)
    if seed not in SEEDS:
        raise ValueError("seed absent from predeclared protocol")
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
    for parameter in model.parameters():
        parameter.requires_grad_(True)
    named = list(model.named_parameters())
    if len(named) != 76 or sum(p.numel() for _, p in named) != 14067712:
        raise ValueError("unexpected pinned model parameter coverage")
    if any(module.p != 0 for module in model.modules() if isinstance(module, torch.nn.Dropout)):
        raise ValueError("diagnostic requires zero dropout")
    schedule = batch_schedule(8, 24, 2, seed)
    selected = schedule[0]
    tokens = torch.from_numpy(arrays["train"][selected])
    initial_hash = parameter_hash(model)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    started = time.perf_counter()
    watchdog = threading.Timer(protocol["config"]["max_seconds_per_worker"], _budget_exit)
    watchdog.daemon = True
    references = None
    records = []
    watchdog.start()
    try:
        for method in METHODS:
            before = parameter_hash(model)
            record = backward_once(model, tokens, method)
            if references is None:
                references = {name: parameter.grad.detach().clone() for name, parameter in named}
            record["parameter_gradient_comparison"] = parameter_comparison(model, references)
            after = parameter_hash(model)
            if before != initial_hash or after != initial_hash:
                raise ValueError("fixed-point diagnostic changed model parameters")
            record.update(parameter_sha256_before=before, parameter_sha256_after=after)
            if method in ("dense", "model_saved_int8"):
                relative = record["observed_vs_analytic_logits_gradient"]["relative_l2"]
                if relative is None or relative > protocol["config"]["analytic_logits_gradient_relative_l2_tolerance"]:
                    raise ValueError("exact loss-path analytic logits-gradient control failed")
            if records and (record["logits_sha256"] != records[0]["logits_sha256"]
                            or record["forward_loss"] != records[0]["forward_loss"]):
                raise ValueError("compression changed dense forward logits/loss")
            records.append(record)
    finally:
        watchdog.cancel()
    elapsed = time.perf_counter() - started
    if elapsed > protocol["config"]["max_seconds_per_worker"]:
        raise ValueError("fixed-point worker exceeded predeclared budget")
    result = {"seed": seed, "completed": True, "pid": os.getpid(), "started_at": started_at,
              "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "wall_seconds_descriptive_only": elapsed,
              "batch_indices": selected, "batch_tokens_sha256": tensor_hash(tokens), "schedule_sha256": digest(schedule),
              "target_positions_per_method": 128, "initial_parameter_sha256": initial_hash,
              "data_sha256": file_hash(data_path), "training_manifest_sha256": file_hash(manifest_path),
              "protocol_sha256": file_hash(protocol_path), "config_sha256": protocol["config_sha256"],
              "source_files_sha256": {path: file_hash(ROOT / path) for path in SOURCE_PATHS},
              "methods": records, "loss_save_sensitivity_gate": loss_save_gate(records),
              "runtime": {"torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version(),
                          "transformers": importlib.metadata.version("transformers"), "system": platform.system(),
                          "machine": platform.machine(), "device": "cpu", "threads": 1,
                          "deterministic_algorithms": torch.are_deterministic_algorithms_enabled()}}
    write_json(output / "worker.json", result)
    return result


def run_probe(model_dir, data_path, manifest_path, protocol_path, output):
    protocol = validate_protocol(protocol_path, data_path, manifest_path)
    load_data(data_path, manifest_path)
    verify_model_assets(model_dir)
    output = Path(output).resolve()
    if (output / "report.json").exists() or (output / "workers").exists():
        raise ValueError("use a fresh output directory")
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({key: "1" for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    workers = []
    for seed in SEEDS:
        directory = output / "workers" / f"seed-{seed}"
        command = [sys.executable, str(SCRIPT), "--model-dir", str(Path(model_dir).resolve()),
                   "--data", str(Path(data_path).resolve()), "--manifest", str(Path(manifest_path).resolve()),
                   "--protocol", str(Path(protocol_path).resolve()), "--output", str(directory), "--seed", str(seed)]
        child = subprocess.run(command, env=environment, capture_output=True, text=True,
                               timeout=protocol["config"]["max_seconds_per_worker"] + 120, check=False)
        if child.returncode:
            raise RuntimeError(f"gradient worker {seed} failed (exit={child.returncode}): {child.stderr[-4000:]}")
        result = json.loads((directory / "worker.json").read_text(encoding="utf-8"))
        if not result["completed"] or [r["method"] for r in result["methods"]] != list(METHODS):
            raise ValueError("incomplete fixed-point worker; no completed report")
        result["worker_record_file"] = (directory / "worker.json").relative_to(output).as_posix()
        workers.append(result)
    if len({w["initial_parameter_sha256"] for w in workers}) != 1:
        raise ValueError("workers did not share the same pretrained parameter state")
    stable = {"config_sha256": protocol["config_sha256"], "protocol_sha256": file_hash(protocol_path),
              "data_sha256": file_hash(data_path), "training_manifest_sha256": file_hash(manifest_path),
              "source_files_sha256": {path: file_hash(ROOT / path) for path in SOURCE_PATHS},
              "workers": [{key: w[key] for key in ("seed", "batch_indices", "batch_tokens_sha256", "schedule_sha256",
                                                    "initial_parameter_sha256", "methods", "loss_save_sensitivity_gate")}
                          for w in workers],
              "loss_save_dominance_gate_passed_all_seeds": all(w["loss_save_sensitivity_gate"]["passed"] for w in workers)}
    # Timing and pointer-dependent inventories belong only to observations.
    for item in stable["workers"]:
        item["methods"] = [{k: v for k, v in method.items()
                            if k not in ("timing_seconds_descriptive_only", "saved_tensor_inventory")}
                           for method in item["methods"]]
    report = {"schema_version": 1, "config": protocol["config"], "stable_results": stable,
              "stable_result_sha256": digest(stable), "worker_measurements": workers,
              "limitations": ["No optimizer, holdout evaluation or parameter updates; one fixed batch per seed.",
                  "Three seed first batches can overlap; not independent data samples or statistical replicates.",
                  "Dense gradients remain live; timing/memory are descriptive, not efficiency comparisons.",
                  "Only the CE hook boundary changes; normalization and other model saves remain compressed.",
                  "Analytic CE uses (softmax(logits)-onehot(target))/128; float32 operation rounding remains.",
                  "A successful sensitivity gate is confined to these fixed points, not training quality or universal dominance.",
                  "No AttnRes, learned depth routing, GPU, ActNN reproduction or novel algorithm claim."]}
    report["observation_sha256"] = digest(report)
    write_json(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model-dir", "data", "manifest", "protocol", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.seed is not None:
        worker(args.model_dir, args.data, args.manifest, args.protocol, args.output, args.seed)
    else:
        report = run_probe(args.model_dir, args.data, args.manifest, args.protocol, args.output)
        print(canonical({"report": str(args.output / "report.json"), "stable_result_sha256": report["stable_result_sha256"]}))


if __name__ == "__main__":
    main()
