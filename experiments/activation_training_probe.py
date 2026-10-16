"""Bounded full-Pythia causal-LM training with backward-only saved-tensor int8.

Original diagnostic, inspired by activation-compression work such as ActNN; not
an ActNN implementation, AttnRes reproduction, or matched-wall-time experiment.
Forward values stay float32. Quantized saved tensors approximate backward; no
STE is used. Runtime imports are optional until an actual training run starts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import threading
import time

import numpy as np

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.attnres_memory_probe import process_memory
from scripts.capture_real_activation import MODEL_ID, MODEL_REVISION, PINNED_ASSETS


SCRIPT = Path(__file__).resolve()
METHODS = ("dense", "int8_saved_tensors")
MAX_DATA_BYTES = 1024 * 1024
MIN_ELEMENTS = 256


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    Path(path).write_bytes((json.dumps(value, indent=2, ensure_ascii=False,
                                     allow_nan=False) + "\n").encode("utf-8"))


def require_torch():
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("optional CPU PyTorch is required; no synthetic training fallback") from error
    return torch


def load_data(data_path, manifest_path):
    if Path(data_path).stat().st_size > MAX_DATA_BYTES or Path(manifest_path).stat().st_size > MAX_DATA_BYTES:
        raise ValueError("data/manifest exceeds 1 MiB bound")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if file_hash(data_path) != manifest.get("data_sha256"):
        raise ValueError("training data file hash mismatch")
    if manifest.get("model_id") != MODEL_ID or manifest.get("model_revision") != MODEL_REVISION:
        raise ValueError("training data model pin mismatch")
    for key in ("train_source_sha256", "holdout_source_sha256", "tokenizer_sha256"):
        value = manifest.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("missing or invalid " + key)
    if manifest["train_source_sha256"] == manifest["holdout_source_sha256"]:
        raise ValueError("train and holdout source hashes must differ")
    if manifest["tokenizer_sha256"] != PINNED_ASSETS["tokenizer.json"][1]:
        raise ValueError("training data tokenizer pin mismatch")
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported training data schema")
    arrays = {}
    for split in ("train", "holdout"):
        blocks = data.get(split)
        if (not isinstance(blocks, list) or len(blocks) != 8
                or any(not isinstance(row, list) or len(row) != 65 for row in blocks)
                or any(type(token) is not int or not 0 <= token < 50304 for row in blocks for token in row)):
            raise ValueError("each split must contain eight 65-token blocks in the pinned vocabulary")
        arrays[split] = np.asarray(blocks, dtype=np.int64)
    if {tuple(row) for row in data["train"]} & {tuple(row) for row in data["holdout"]}:
        raise ValueError("identical train/holdout token blocks are prohibited")
    return arrays, manifest


def verify_model_assets(model_dir):
    model_dir = Path(model_dir)
    for name, (size, expected) in PINNED_ASSETS.items():
        path = model_dir / name
        if not path.is_file() or path.stat().st_size != size or file_hash(path) != expected:
            raise ValueError("pinned model asset mismatch: " + name)
    overrides = ("added_tokens.json", "vocab.json", "merges.txt", "vocab.txt",
                 "tokenizer.model", "chat_template.jinja", "adapter_config.json")
    if any((model_dir / name).exists() for name in overrides):
        raise ValueError("local model directory contains an unpinned loader override")


def batch_schedule(count, steps, batch_size, seed):
    generator = np.random.default_rng(seed)
    order = []
    while len(order) < steps * batch_size:
        order.extend(int(index) for index in generator.permutation(count))
    return [order[start:start + batch_size] for start in range(0, steps * batch_size, batch_size)]


def storage_key(tensor):
    return (str(tensor.device), tensor.untyped_storage().data_ptr())


class SavedActivationCodec:
    """Saved-tensor hooks without retaining compressed originals.

    Exclusion compares backing storage, so transposed/reshaped parameter aliases
    remain exact. All eligible float32 activations are in scope, including
    attention intermediates and cross-entropy/log-softmax saves. Inventories
    count logical saves and unique backing storage, not OS allocation peaks.
    """

    def __init__(self, parameters, method, min_elements=MIN_ELEMENTS):
        if method not in METHODS:
            raise ValueError("unknown saved-activation method")
        self.method, self.min_elements = method, min_elements
        self.parameter_storages = {storage_key(parameter) for parameter in parameters}
        self.counts = Counter()
        self.shapes = Counter()
        self.source_storages = {}
        self.retained_parameter_storages = {}
        self.retained_activation_storages = {}
        self.original_logical_bytes = 0
        self.retained_logical_bytes = 0
        self.pack_seconds = self.unpack_seconds = 0.0

    def _retained(self, tensor, parameter=False):
        collection = self.retained_parameter_storages if parameter else self.retained_activation_storages
        collection[storage_key(tensor)] = tensor.untyped_storage().nbytes()
        self.retained_logical_bytes += tensor.numel() * tensor.element_size()

    def pack(self, tensor):
        torch = require_torch()
        started = time.perf_counter()
        parameter = storage_key(tensor) in self.parameter_storages
        self.source_storages[storage_key(tensor)] = tensor.untyped_storage().nbytes()
        logical = tensor.numel() * tensor.element_size()
        self.original_logical_bytes += logical
        self.counts["save_calls"] += 1
        if parameter:
            reason = "parameter_storage_excluded"
        elif tensor.device.type != "cpu" or tensor.dtype != torch.float32:
            reason = "dtype_or_device_excluded"
        elif tensor.ndim < 1 or tensor.numel() < self.min_elements or tensor.shape[-1] == 0:
            reason = "size_or_shape_excluded"
        else:
            reason = "eligible"
        self.counts[reason] += 1
        self.shapes[(reason, str(tensor.dtype), tuple(tensor.shape))] += 1
        if self.method == "int8_saved_tensors" and reason == "eligible":
            with torch.no_grad():
                if not bool(torch.isfinite(tensor).all()):
                    raise ValueError("nonfinite saved activation")
                maximum = tensor.detach().abs().amax(dim=-1, keepdim=True)
                scales = torch.where(maximum == 0, torch.ones_like(maximum), maximum / 127.0)
                codes = torch.round(tensor.detach() / scales).clamp(-127, 127).to(torch.int8)
            self._retained(codes)
            self._retained(scales)
            self.counts["compressed_saves"] += 1
            packed = (codes, scales)
        else:
            packed = tensor.detach()
            self._retained(packed, parameter)
        self.pack_seconds += time.perf_counter() - started
        return packed

    def unpack(self, payload):
        started = time.perf_counter()
        self.counts["unpack_calls"] += 1
        if isinstance(payload, tuple):
            codes, scales = payload
            tensor = codes.to(scales.dtype) * scales
            self.counts["decoded_saves"] += 1
        else:
            tensor = payload
        self.unpack_seconds += time.perf_counter() - started
        return tensor

    def inventory(self):
        return {"counts": dict(self.counts), "original_logical_saved_bytes_including_duplicates": self.original_logical_bytes,
                "retained_logical_payload_bytes_including_duplicates": self.retained_logical_bytes,
                "source_storage_union_bytes_diagnostic": sum(self.source_storages.values()),
                "retained_activation_storage_union_bytes": sum(self.retained_activation_storages.values()),
                "retained_parameter_storage_union_bytes_excluded_from_compression": sum(self.retained_parameter_storages.values()),
                "shape_audit": [{"policy": reason, "dtype": dtype, "shape": list(shape), "saves": count}
                                for (reason, dtype, shape), count in sorted(self.shapes.items())]}


def parameter_hash(model):
    result = hashlib.sha256()
    for name, value in model.named_parameters():
        result.update(canonical({"name": name, "shape": list(value.shape), "dtype": str(value.dtype)}).encode())
        result.update(value.detach().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def next_token_loss(model, token_blocks):
    torch = require_torch()
    # Each 65-token block supplies 64 causal input/target pairs. No cross-block
    # transition is scored and every block resets its sequence positions.
    logits = model(input_ids=token_blocks[:, :-1].contiguous(), use_cache=False).logits
    targets = token_blocks[:, 1:].contiguous()
    return torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), targets.reshape(-1))


def evaluate(model, token_blocks, batch_size):
    torch = require_torch()
    model.eval()
    total, pairs = 0.0, 0
    with torch.no_grad():
        for start in range(0, len(token_blocks), batch_size):
            batch = token_blocks[start:start + batch_size]
            loss = next_token_loss(model, batch)
            count = len(batch) * (batch.shape[1] - 1)
            total += float(loss) * count
            pairs += count
    if not math.isfinite(total):
        raise ValueError("nonfinite holdout NLL")
    model.train()
    return {"mean_nll": total / pairs, "scored_token_pairs": pairs}


def train_step(model, optimizer, tokens, method):
    torch = require_torch()
    parameters = list(model.parameters())
    optimizer.zero_grad(set_to_none=True)
    codec = SavedActivationCodec(parameters, method)
    started = time.perf_counter()
    with torch.autograd.graph.saved_tensors_hooks(codec.pack, codec.unpack):
        loss = next_token_loss(model, tokens)
    forward_end = time.perf_counter()
    loss.backward()
    backward_end = time.perf_counter()
    gradient_squared = 0.0
    for parameter in parameters:
        if parameter.grad is None or not bool(torch.isfinite(parameter.grad).all()):
            raise ValueError("missing or nonfinite full-model parameter gradient")
        gradient_squared += float(torch.linalg.vector_norm(parameter.grad)) ** 2
    gradient_norm_end = time.perf_counter()
    optimizer.step()
    optimizer_end = time.perf_counter()
    for parameter in parameters:
        if not bool(torch.isfinite(parameter).all()):
            raise ValueError("nonfinite updated model parameter")
    end = time.perf_counter()
    if not math.isfinite(float(loss.detach())):
        raise ValueError("nonfinite next-token training loss")
    return {"next_token_nll": float(loss.detach()), "parameter_gradient_l2": math.sqrt(gradient_squared),
            "parameter_tensors_with_finite_gradients": len(parameters),
            "parameter_elements_with_finite_gradients": sum(parameter.numel() for parameter in parameters),
            "saved_tensor_inventory": codec.inventory(),
            "timing_seconds": {"forward_crossentropy_including_pack": forward_end - started,
                               "backward_including_unpack": backward_end - forward_end,
                               "gradient_norm_and_finite_checks": gradient_norm_end - backward_end,
                               "optimizer": optimizer_end - gradient_norm_end,
                               "updated_parameter_finite_checks": end - optimizer_end, "instrumented_step_total": end - started,
                               "saved_tensor_pack_callbacks": codec.pack_seconds,
                               "saved_tensor_unpack_callbacks": codec.unpack_seconds}}


def validate_config(seeds, steps, batch_size, lr, max_seconds):
    if (not seeds or len(seeds) > 3 or len(set(seeds)) != len(seeds)
            or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in seeds)):
        raise ValueError("provide 1..3 distinct nonnegative uint32 seeds")
    if type(steps) is not int or not 1 <= steps <= 24 or batch_size not in (1, 2):
        raise ValueError("steps must be 1..24 and batch size 1 or 2")
    if not math.isfinite(lr) or lr <= 0 or lr > 1e-3:
        raise ValueError("learning rate must be in (0,1e-3]")
    if not math.isfinite(max_seconds) or not 1 <= max_seconds <= 180:
        raise ValueError("training budget must be 1..180 seconds per worker")


def _budget_exit():
    sys.stderr.write("hard training-loop wall-time budget exceeded; worker aborted without completed report\n")
    sys.stderr.flush()
    os._exit(124)


def validate_predeclared(manifest, seeds, steps, batch_size, lr, max_seconds, worker_method=None):
    config = manifest.get("predeclared_config")
    if not isinstance(config, dict) or digest(config) != manifest.get("predeclared_config_sha256"):
        raise ValueError("predeclared configuration hash mismatch")
    expected = {"steps": steps, "batch_size": batch_size, "learning_rate": lr,
                "sequence_length": 64, "train_blocks": 8, "holdout_blocks": 8,
                "optimizer": "AdamW", "weight_decay": 0, "betas": [0.9, 0.999],
                "optimizer_eps": 1e-8, "max_training_seconds_per_worker": max_seconds,
                "methods": list(METHODS)}
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError("arguments do not match predeclared training configuration")
    if worker_method is None:
        if config.get("seeds") != list(seeds):
            raise ValueError("seeds differ from predeclared configuration")
    elif worker_method not in config["methods"] or any(seed not in config.get("seeds", []) for seed in seeds):
        raise ValueError("worker seed/method absent from predeclared configuration")


def worker(model_dir, data_path, manifest_path, output, method, seed, steps, batch_size, lr, max_seconds):
    torch = require_torch()
    from transformers import AutoModelForCausalLM
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    arrays, manifest = load_data(data_path, manifest_path)
    validate_predeclared(manifest, [seed], steps, batch_size, lr, max_seconds, method)
    verify_model_assets(model_dir)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    memory = {"after_import_before_model": process_memory()}
    model = AutoModelForCausalLM.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False,
                                               use_safetensors=True, dtype=torch.float32,
                                               attn_implementation="eager").to(device="cpu", dtype=torch.float32)
    for parameter in model.parameters():
        parameter.requires_grad_(True)
    if any(module.p != 0 for module in model.modules() if isinstance(module, torch.nn.Dropout)):
        raise ValueError("pinned deterministic diagnostic requires zero dropout")
    count = sum(parameter.numel() for parameter in model.parameters())
    if count != 14_067_712 or not all(parameter.dtype == torch.float32 and parameter.device.type == "cpu"
                                    for parameter in model.parameters()):
        raise ValueError("unexpected pinned full-model parameter count/dtype")
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, betas=(0.9, 0.999), eps=1e-8,
                                 weight_decay=0, foreach=False, fused=False)
    train = torch.from_numpy(arrays["train"])
    holdout = torch.from_numpy(arrays["holdout"])
    schedule = batch_schedule(len(train), steps, batch_size, seed)
    initial_hash = parameter_hash(model)
    initial = evaluate(model, holdout, batch_size)
    memory["after_model_and_initial_holdout"] = process_memory()
    records = []
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    started = time.perf_counter()
    watchdog = threading.Timer(max_seconds, _budget_exit)
    watchdog.daemon = True
    watchdog.start()
    try:
        for index, indices in enumerate(schedule):
            record = train_step(model, optimizer, train[indices], method)
            record.update(step=index, batch_indices=indices, scored_token_pairs=batch_size * 64,
                          process_memory=process_memory())
            records.append(record)
            if time.perf_counter() - started > max_seconds:
                raise RuntimeError("training-loop wall-time budget exceeded; matched run aborted")
        training_seconds = time.perf_counter() - started
    finally:
        watchdog.cancel()
    training_completed_at = dt.datetime.now(dt.timezone.utc).isoformat()
    memory["after_training"] = process_memory()
    final = evaluate(model, holdout, batch_size)
    final_hash = parameter_hash(model)
    if final_hash == initial_hash:
        raise ValueError("training failed to update full-model parameters")
    memory["after_final_holdout_and_hash"] = process_memory()
    result = {"method": method, "seed": seed, "pid": os.getpid(), "completed": True,
              "training_started_at": started_at, "training_completed_at": training_completed_at,
              "training_loop_wall_seconds": training_seconds, "steps_completed": len(records),
              "scored_train_token_pairs": steps * batch_size * 64, "parameter_count": count,
              "all_parameters_trainable": all(parameter.requires_grad for parameter in model.parameters()),
              "initial_parameter_sha256": initial_hash, "final_parameter_sha256": final_hash,
              "schedule": schedule, "schedule_sha256": digest(schedule), "initial_holdout": initial,
              "final_holdout": final, "step_records": records, "memory": memory,
              "process_lifetime_peak_bytes": memory["after_final_holdout_and_hash"]["peak_bytes"],
              "data_sha256": manifest["data_sha256"], "runtime": {
                  "torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version(),
                  "transformers": importlib.metadata.version("transformers"), "system": platform.system(),
                  "release": platform.release(), "machine": platform.machine(), "device": "cpu",
                  "torch_num_threads": torch.get_num_threads(), "torch_num_interop_threads": torch.get_num_interop_threads(),
                  "deterministic_algorithms": torch.are_deterministic_algorithms_enabled()}}
    write_json(output / "worker.json", result)
    return result


def run_probe(model_dir, data_path, manifest_path, output, seeds=(11, 29, 47), steps=24,
              batch_size=2, lr=1e-4, max_seconds=180):
    require_torch()
    seeds = list(seeds)
    validate_config(seeds, steps, batch_size, lr, max_seconds)
    _, manifest = load_data(data_path, manifest_path)
    validate_predeclared(manifest, seeds, steps, batch_size, lr, max_seconds)
    verify_model_assets(model_dir)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "report.json").exists() or (output / "workers").exists():
        raise ValueError("use a fresh output directory")
    config = {"model_id": MODEL_ID, "model_revision": MODEL_REVISION, "methods": list(METHODS),
              "seeds": seeds, "steps": steps, "batch_size": batch_size, "sequence_input_tokens": 64,
              "lr": lr, "adamw_betas": [0.9, 0.999], "adamw_eps": 1e-8, "weight_decay": 0,
              "max_training_loop_seconds_per_worker": max_seconds, "min_compressed_elements": MIN_ELEMENTS,
              "threads": 1, "dtype": "float32", "attention": "eager", "worker_order_seed": 1729,
              "quantization": "backward-only saved-tensor per-last-dim symmetric int8; parameter-backed aliases excluded"}
    jobs = [(seed, method) for seed in seeds for method in METHODS]
    random.Random(config["worker_order_seed"]).shuffle(jobs)
    environment = os.environ.copy()
    environment.update({name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    workers = []
    for seed, method in jobs:
        directory = output / "workers" / f"seed-{seed}--{method}"
        command = [sys.executable, str(SCRIPT), "--model-dir", str(Path(model_dir).resolve()),
                   "--data", str(Path(data_path).resolve()), "--manifest", str(Path(manifest_path).resolve()),
                   "--output", str(directory), "--worker", method, "--seed", str(seed),
                   "--steps", str(steps), "--batch-size", str(batch_size), "--lr", str(lr),
                   "--max-seconds", str(max_seconds)]
        child = subprocess.run(command, env=environment, capture_output=True, text=True,
                               timeout=max_seconds + 120, check=False)
        if child.returncode:
            raise RuntimeError(f"training worker failed ({seed},{method},exit={child.returncode}): {child.stderr[-4000:]}")
        result = json.loads((directory / "worker.json").read_text(encoding="utf-8"))
        if not result["completed"] or result["steps_completed"] != steps:
            raise ValueError("incomplete matched-token worker; no completed report")
        result["worker_record_file"] = (directory / "worker.json").relative_to(output).as_posix()
        workers.append(result)
    workers.sort(key=lambda item: (item["seed"], item["method"]))
    comparisons = []
    for seed in seeds:
        dense, packed = [next(item for item in workers if item["seed"] == seed and item["method"] == method)
                         for method in METHODS]
        for key in ("initial_parameter_sha256", "schedule_sha256", "data_sha256", "scored_train_token_pairs", "initial_holdout"):
            if dense[key] != packed[key]:
                raise ValueError("paired worker initial/input mismatch: " + key)
        comparisons.append({"seed": seed, "initial_holdout_nll": dense["initial_holdout"]["mean_nll"],
                            "dense_final_holdout_nll": dense["final_holdout"]["mean_nll"],
                            "int8_final_holdout_nll": packed["final_holdout"]["mean_nll"],
                            "int8_minus_dense_final_holdout_nll": packed["final_holdout"]["mean_nll"] - dense["final_holdout"]["mean_nll"]})
    sources = {path.as_posix(): file_hash(path) for path in (
        Path("experiments/activation_training_probe.py"), Path("scripts/capture_real_activation.py"),
        Path("experiments/attnres_memory_probe.py"), Path("experiments/attnres_budget_probe.py"))}
    stable = {"config_sha256": digest(config), "data_sha256": manifest["data_sha256"],
              "manifest_sha256": file_hash(manifest_path), "source_files_sha256": sources,
              "comparisons": comparisons,
              "workers": [{key: item[key] for key in ("method", "seed", "initial_parameter_sha256", "final_parameter_sha256",
                                                       "schedule_sha256", "steps_completed", "scored_train_token_pairs")}
                          for item in workers]}
    report = {"schema_version": 1, "config": config, "stable_results": stable, "stable_result_sha256": digest(stable),
              "worker_measurements": workers, "limitations": [
                  "Full conventional Pythia causal-LM parameter updates on tiny original text; no AttnRes or learned depth routing.",
                  "Saved activation quantization approximates backward only; forward is dense float32; no identity STE.",
                  "Compresses all eligible saved float32 activations including CE/logsoftmax saves, not residual-bank-only compression.",
                  "Matched token/update schedule only; matched-wall-clock quality, general LM quality, and GPU benefits remain untested.",
                  "Initial/final holdout are tiny fixed diagnostics; no intermediate holdout selection or hyperparameter tuning.",
                  "OS lifetime peaks include imports, model/grads/AdamW, holdout, hashes and finite/norm instrumentation; not isolated training peaks.",
                  "Training-loop time includes zero_grad, codec construction and batch selection; per-step timers start after zero_grad and codec construction.",
                  "Hook storage unions are inventories; original-source unions may reuse pointers and are diagnostics, not live retained bytes.",
                  "Related work includes ActNN activation-compressed training; this simple symmetric int8 hook is not an ActNN reproduction."]}
    report["observation_sha256"] = digest(report)
    write_json(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=[11, 29, 47])
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--max-seconds", type=float, default=180)
    parser.add_argument("--worker", choices=METHODS, help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        validate_config([args.seed], args.steps, args.batch_size, args.lr, args.max_seconds)
        worker(args.model_dir, args.data, args.manifest, args.output, args.worker, args.seed,
               args.steps, args.batch_size, args.lr, args.max_seconds)
    else:
        report = run_probe(args.model_dir, args.data, args.manifest, args.output, args.seeds,
                           args.steps, args.batch_size, args.lr, args.max_seconds)
        print(canonical({"report": str(args.output / "report.json"), "stable_result_sha256": report["stable_result_sha256"]}))


if __name__ == "__main__":
    main()
