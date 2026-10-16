"""Fixed-parameter diagnostic preserving actual GPTNeoXAttention saved operands.

No optimizer, holdout evaluation or training update. Uses the already published
backward-only codec; retained dense references make costs descriptive only.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
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
from experiments.activation_gradient_probe import (
    tensor_hash, vector_metrics, analytic_ce_gradient, parameter_comparison,
)
from experiments.activation_norm_gradient_probe import (
    named_layernorm_hooks, norm_inventory, validate_norm_coverage,
)

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[1]
METHODS = ("dense", "model_except_norm_saved_int8", "model_except_norm_attention_saved_int8")
ATTENTION_CLASS_NAME = "transformers.models.gpt_neox.modeling_gpt_neox.GPTNeoXAttention"
SEEDS = (11, 29, 47)
SOURCE_PATHS = (
    "experiments/activation_attention_gradient_probe.py",
    "experiments/activation_norm_gradient_probe.py", "experiments/activation_gradient_probe.py",
    "experiments/activation_training_probe.py",
    "scripts/capture_real_activation.py", "experiments/attnres_memory_probe.py",
    "experiments/attnres_budget_probe.py",
)


def preset_config():
    return {"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "seeds": list(SEEDS),
            "methods_in_order": list(METHODS), "batch_size": 2, "sequence_input_tokens": 64,
            "schedule_steps": 24, "schedule_selection": "first batch only", "dtype": "float32",
            "attention": "eager", "threads": 1, "min_compressed_elements": 256,
            "max_seconds_per_worker": 180, "analytic_logits_gradient_relative_l2_tolerance": 1e-5,
            "norm_preservation_scope": "torch.nn.LayerNorm forward saves",
            "expected_named_layernorm_modules": 13,
            "attention_preservation_scope": ATTENTION_CLASS_NAME + " forward saves",
            "expected_named_attention_modules": 6,
            "attention_save_dominance": {"max_attention_preserved_to_norm_only_relative_l2": 0.5,
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


def attention_type():
    # Keep optional Torch/Transformers imports outside protocol/static tooling.
    from transformers.models.gpt_neox.modeling_gpt_neox import GPTNeoXAttention
    return GPTNeoXAttention


@contextmanager
def named_attention_hooks(model, parameters, policy):
    """Wrap actual GPTNeoXAttention instances; nested hooks select at save time.

    This broad scope includes projections and rotary operations, not only SDPA.
    Original bound calls and pre-existing instance forward attributes survive.
    """
    torch = require_torch()
    cls = attention_type()
    if policy not in ("dense", "int8_saved_tensors"):
        raise ValueError("invalid attention save policy")
    missing = object()
    originals, records = [], {}
    try:
        for name, module in model.named_modules():
            if not isinstance(module, cls):
                continue
            original = module.forward
            prior_attribute = module.__dict__.get("forward", missing)
            codec = SavedActivationCodec(parameters, policy)
            records[name] = {"calls": 0, "codec": codec,
                             "module_class": type(module).__module__ + "." + type(module).__name__}

            def forward(*args, _original=original, _record=records[name], **kwargs):
                _record["calls"] += 1
                active = _record["codec"]
                with torch.autograd.graph.saved_tensors_hooks(active.pack, active.unpack):
                    return _original(*args, **kwargs)

            originals.append((module, prior_attribute))
            module.forward = forward
        yield records
    finally:
        for module, original in reversed(originals):
            if original is missing:
                delattr(module, "forward")
            else:
                module.forward = original


def attention_inventory(records):
    return {name: {"calls": item["calls"], "module_class": item["module_class"],
                   "inventory": item["codec"].inventory()} for name, item in records.items()}


def validate_attention_coverage(record, expected_names, method):
    actual = record["named_attention_saves"]
    if list(actual) != list(expected_names):
        raise ValueError("attention names/order differ from pinned model")
    for name, item in actual.items():
        counts = item["inventory"]["counts"]
        if item["module_class"] != ATTENTION_CLASS_NAME:
            raise ValueError("unexpected actual attention class: " + name)
        if item["calls"] != 1 or counts.get("save_calls", 0) < 1 or counts.get("unpack_calls", 0) < 1:
            raise ValueError("attention needs one forward and nonempty save/unpack coverage: " + name)
        eligible = counts.get("eligible", 0)
        compressed = counts.get("compressed_saves", 0)
        decoded = counts.get("decoded_saves", 0)
        if eligible < 1:
            raise ValueError("attention had no eligible activation save: " + name)
        if method == "model_except_norm_saved_int8":
            if compressed != eligible or decoded != eligible:
                raise ValueError("baseline attention saves did not use original codec policy")
        elif compressed or decoded:
            raise ValueError("preserved/dense attention saved operands were compressed")


def backward_once(model, tokens, method):
    torch = require_torch()
    if method not in METHODS:
        raise ValueError("unknown gradient compression policy")
    model.zero_grad(set_to_none=True)
    parameters = [parameter for _, parameter in model.named_parameters()]
    codec = SavedActivationCodec(parameters, "dense" if method == "dense" else "int8_saved_tensors")
    started = time.perf_counter()
    norm_policy = "dense"
    attention_policy = "int8_saved_tensors" if method == "model_except_norm_saved_int8" else "dense"
    with torch.autograd.graph.saved_tensors_hooks(codec.pack, codec.unpack):
        with named_layernorm_hooks(model, parameters, norm_policy) as norms:
            with named_attention_hooks(model, parameters, attention_policy) as attentions:
                logits = model(input_ids=tokens[:, :-1], use_cache=False).logits
    # Every arm keeps the loss path exact, including dense, outside all hooks.
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
              "named_layernorm_saves": norm_inventory(norms),
              "named_attention_saves": attention_inventory(attentions),
              "attention_save_policy": attention_policy,
              "layernorm_save_policy": norm_policy,
              "timing_seconds_descriptive_only": {"forward_ce_including_pack": forward_end - started,
                                                   "backward_including_unpack": backward_end - forward_end}}
    return record


def attention_save_gate(method_records):
    base = method_records[1]["parameter_gradient_comparison"]["aggregate"]
    exact = method_records[2]["parameter_gradient_comparison"]["aggregate"]
    base_rel, exact_rel = base["relative_l2"], exact["relative_l2"]
    valid_errors = (base_rel is not None and exact_rel is not None
                    and math.isfinite(base_rel) and math.isfinite(exact_rel)
                    and base_rel > 0 and exact_rel >= 0)
    ratio = exact_rel / base_rel if valid_errors else None
    if ratio is not None and not math.isfinite(ratio):
        ratio = None
    cosines = (base["cosine_similarity"], exact["cosine_similarity"])
    valid_cosines = all(value is not None and math.isfinite(value) for value in cosines)
    passed = ratio is not None and ratio <= 0.5 and valid_cosines and cosines[1] >= cosines[0]
    return {"attention_preserved_to_norm_only_relative_l2_ratio": ratio, "passed": passed,
            "meaning": "predeclared broad attention-forward saved-operand sensitivity gate; no training-quality implication"}


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
    norm_names = [name for name, module in model.named_modules() if isinstance(module, torch.nn.LayerNorm)]
    if len(norm_names) != protocol["config"]["expected_named_layernorm_modules"]:
        raise ValueError("unexpected pinned LayerNorm module count")
    cls = attention_type()
    attention_names = [name for name, module in model.named_modules() if isinstance(module, cls)]
    if len(attention_names) != protocol["config"]["expected_named_attention_modules"]:
        raise ValueError("unexpected pinned attention module count")
    if model.config._attn_implementation != "eager" or any(
            module.attention_dropout != 0 for module in model.modules() if isinstance(module, cls)):
        raise ValueError("diagnostic requires eager attention with zero attention dropout")
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
            validate_norm_coverage(record, norm_names, method)
            validate_attention_coverage(record, attention_names, method)
            if references is None:
                references = {name: parameter.grad.detach().clone() for name, parameter in named}
            record["parameter_gradient_comparison"] = parameter_comparison(model, references)
            after = parameter_hash(model)
            if before != initial_hash or after != initial_hash:
                raise ValueError("fixed-point diagnostic changed model parameters")
            record.update(parameter_sha256_before=before, parameter_sha256_after=after)
            if method in METHODS:
                relative = record["observed_vs_analytic_logits_gradient"]["relative_l2"]
                if relative is None or not math.isfinite(relative) or relative > protocol["config"]["analytic_logits_gradient_relative_l2_tolerance"]:
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
              "methods": records, "attention_save_sensitivity_gate": attention_save_gate(records),
              "runtime": {"torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version(),
                          "transformers": importlib.metadata.version("transformers"),
                          "attention_class": ATTENTION_CLASS_NAME,
                          "attention_class_source_sha256": file_hash(sys.modules[cls.__module__].__file__),
                          "system": platform.system(),
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
                                                    "initial_parameter_sha256", "methods", "attention_save_sensitivity_gate")}
                          for w in workers],
              "attention_save_dominance_gate_passed_all_seeds": all(w["attention_save_sensitivity_gate"]["passed"] for w in workers)}
    # Timing and pointer-dependent inventories belong only to observations.
    for item in stable["workers"]:
        item["methods"] = [{k: v for k, v in method.items()
                            if k not in ("timing_seconds_descriptive_only", "saved_tensor_inventory", "named_layernorm_saves", "named_attention_saves")}
                           for method in item["methods"]]
    report = {"schema_version": 1, "config": protocol["config"], "stable_results": stable,
              "stable_result_sha256": digest(stable), "worker_measurements": workers,
              "limitations": ["No optimizer, holdout evaluation or parameter updates; one fixed batch per seed.",
                  "Three seed first batches can overlap; not independent data samples or statistical replicates.",
                  "Dense gradients remain live; timing/memory are descriptive, not efficiency comparisons.",
                  "CE and all named LayerNorm saves are exact in all methods; only actual GPTNeoXAttention forward saves change policy.",
                  "Nested inventories split other-model, LayerNorm and attention saves; unhooked CE is excluded, not total memory.",
                  "Analytic CE uses (softmax(logits)-onehot(target))/128; float32 operation rounding remains.",
                  "Attention-forward scope includes QKV, rotary operations, attention and output projection; no single-operand attribution.",
                  "Independent tiny attention VJP uses identity RoPE; no independent general rotary backward reference.",
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
