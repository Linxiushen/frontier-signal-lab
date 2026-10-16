"""CPU operator/autograd replay on authenticated, frozen pretrained activations.

The random shared query is a pseudoquery, not a learned model parameter. Int8
packing happens on every step and its backward uses an explicit identity STE.
This is neither backbone training nor evidence about language-model quality,
GPU memory, faithful quantization gradients, or upstream AttnRes reproduction.
PyTorch is an optional dependency; the real probe requires it explicitly.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
import zipfile

import numpy as np

if __package__:
    from .attnres_memory_probe import process_memory
else:
    from attnres_memory_probe import process_memory


SCRIPT = Path(__file__).resolve()
METHODS = ("dense_float32", "int8_identity_ste")
EPS = 1e-6
MAX_BANK_BYTES = 64 * 1024 * 1024
RTOL, ATOL = 2e-5, 2e-6


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            result.update(block)
    return result.hexdigest()


def bank_hash(bank):
    """SHA256 of little-endian float32 C-order bank bytes, excluding metadata."""
    return hashlib.sha256(np.ascontiguousarray(bank, dtype="<f4").tobytes()).hexdigest()


def array_hash(array):
    array = np.ascontiguousarray(array)
    result = hashlib.sha256(canonical({"shape": list(array.shape), "dtype": str(array.dtype)}).encode())
    result.update(array.tobytes())
    return result.hexdigest()


def load_trace(trace_path, manifest_path):
    """Verify the persisted trace, raw bank, and canonical capture configuration."""
    if Path(manifest_path).stat().st_size > 1024 * 1024:
        raise ValueError("trace manifest exceeds 1 MiB")
    if Path(trace_path).stat().st_size > MAX_BANK_BYTES + 1024 * 1024:
        raise ValueError("trace container exceeds bounded size")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported trace manifest schema")
    if file_hash(trace_path) != manifest.get("trace_file_sha256"):
        raise ValueError("trace file hash mismatch")
    capture = manifest.get("capture_config")
    if not isinstance(capture, dict) or digest(capture) != manifest.get("capture_config_sha256"):
        raise ValueError("capture configuration hash mismatch")
    # Inspect the archive and .npy header before NumPy can allocate/decompress
    # the full array. A matching manifest hash alone is not a resource bound.
    with zipfile.ZipFile(trace_path) as container:
        entries = container.infolist()
        if len(entries) != 1 or entries[0].filename != "bank.npy":
            raise ValueError("trace must contain only bank.npy")
        entry = entries[0]
        if (entry.file_size > MAX_BANK_BYTES + 8192 or entry.flag_bits & 1
                or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise ValueError("trace archive entry exceeds bounded size or encoding")
        with container.open(entry) as stream:
            version = np.lib.format.read_magic(stream)
            reader = { (1, 0): np.lib.format.read_array_header_1_0,
                       (2, 0): np.lib.format.read_array_header_2_0 }.get(version)
            if reader is None:
                raise ValueError("unsupported NumPy trace header")
            shape, _, dtype = reader(stream, max_header_size=4096)
            if (len(shape) != 3 or any(type(size) is not int or size < 1 for size in shape)
                    or dtype != np.dtype("float32") or math.prod(shape) * dtype.itemsize > MAX_BANK_BYTES):
                raise ValueError("trace header shape/dtype exceeds bounded bank contract")
            if entry.file_size != stream.tell() + math.prod(shape) * dtype.itemsize:
                raise ValueError("trace entry length does not match its array header")
    with np.load(trace_path, allow_pickle=False) as archive:
        if set(archive.files) != {"bank"}:
            raise ValueError("trace must contain only the bank array")
        bank = archive["bank"]
    if (bank.dtype != np.dtype("float32") or bank.ndim != 3 or min(bank.shape) < 1
            or bank.nbytes > MAX_BANK_BYTES or not np.isfinite(bank).all()):
        raise ValueError("expected finite float32 [depth,tokens,dim] bank of at most 64 MiB")
    if manifest.get("bank_shape") != list(bank.shape) or manifest.get("bank_dtype") != "float32":
        raise ValueError("trace bank shape/dtype mismatch")
    if bank_hash(bank) != manifest.get("bank_sha256"):
        raise ValueError("raw bank hash mismatch")
    if manifest.get("activation_boundary") != "pre_block_residual":
        raise ValueError("probe requires consistently captured pre-block residuals")
    for name in ("source_text_sha256", "token_ids_sha256"):
        value = manifest.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("missing or malformed " + name)
    if not manifest.get("model_id") or not manifest.get("model_revision"):
        raise ValueError("model provenance must be present")
    return np.ascontiguousarray(bank), manifest


def require_torch():
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("This real activation probe requires optional CPU PyTorch; no synthetic fallback is used") from error
    return torch


def make_query(dim, seed):
    """A deterministic Gaussian shared pseudoquery, never trained or optimized."""
    return (np.random.default_rng(seed).standard_normal(dim) / math.sqrt(dim)).astype(np.float32)


def numpy_mix(bank, query, eps=EPS):
    """Independent float64 NumPy forward reference, with no torch operations."""
    values = np.asarray(bank, dtype=np.float64)
    query = np.asarray(query, dtype=np.float64)
    normalized = values / np.sqrt(np.mean(values * values, axis=-1, keepdims=True) + eps)
    logits = np.sum(normalized * query, axis=-1)
    weights = np.exp(logits - logits.max(axis=0, keepdims=True))
    weights /= weights.sum(axis=0, keepdims=True)
    return np.sum(values * weights[..., None], axis=0)


def dense_mix(bank, query, eps=EPS):
    """Depth softmax of RMS-normalized bank dot shared query; mix original bank."""
    torch = require_torch()
    normalized = bank * torch.rsqrt(bank.square().mean(dim=-1, keepdim=True) + eps)
    weights = torch.softmax((normalized * query).sum(dim=-1), dim=0)
    return (weights.unsqueeze(-1) * bank).sum(dim=0)


def pack_bank(bank):
    """Per-vector symmetric int8 packing; neither scales nor codes get gradients."""
    torch = require_torch()
    with torch.no_grad():
        maximum = bank.detach().abs().amax(dim=-1, keepdim=True)
        scales = torch.where(maximum == 0, torch.ones_like(maximum), maximum / 127.0)
        codes = torch.round(bank.detach() / scales).clamp(-127, 127).to(torch.int8)
    return codes, scales


def forward_operator(bank, query, method):
    """Return output and component times; packing is inside every invocation."""
    if method not in METHODS:
        raise ValueError("unknown method")
    pack_seconds, decode_seconds = 0.0, 0.0
    if method == "int8_identity_ste":
        started = time.perf_counter()
        codes, scales = pack_bank(bank)
        pack_seconds = time.perf_counter() - started
        started = time.perf_counter()
        dequantized = codes.to(bank.dtype) * scales
        # Identity surrogate d(decoded)/d(bank)=I, not round/clamp's derivative.
        values = bank + (dequantized - bank).detach()
        decode_seconds = time.perf_counter() - started
    else:
        values = bank
    started = time.perf_counter()
    output = dense_mix(values, query)
    readout_seconds = time.perf_counter() - started
    return output, {"pack_wall_seconds": pack_seconds,
                    "decode_and_ste_wall_seconds": decode_seconds,
                    "readout_wall_seconds": readout_seconds}


def autograd_step(bank, query, method):
    """One forward/loss/backward without an optimizer update or cached packing."""
    bank.grad = None
    query.grad = None
    started = time.perf_counter()
    output, components = forward_operator(bank, query, method)
    loss = output.square().mean()
    forward_end = time.perf_counter()
    loss.backward()
    backward_end = time.perf_counter()
    components.update(forward_including_pack_and_loss_wall_seconds=forward_end - started,
                      backward_wall_seconds=backward_end - forward_end,
                      forward_backward_wall_seconds=backward_end - started)
    return output, loss, components


class SavedTensorInventory:
    """Saved logical bytes and storage union; this is not measured process RAM.

    Unique storage includes saved aliases of live inputs and counts their entire
    backing storage. Duplicate logical saves are reported separately. The hook
    inventory is collected in an extra untimed step, so it does not instrument
    the reported operator timings.
    """

    def __init__(self):
        self.logical_bytes = 0
        self.entries = []
        self.storages = {}

    def pack(self, tensor):
        storage = tensor.untyped_storage()
        key = (str(tensor.device), storage.data_ptr())
        self.storages[key] = storage.nbytes()
        logical = tensor.numel() * tensor.element_size()
        self.logical_bytes += logical
        self.entries.append({"shape": list(tensor.shape), "dtype": str(tensor.dtype), "logical_bytes": logical})
        return tensor

    @staticmethod
    def unpack(tensor):
        return tensor

    def result(self):
        return {"logical_saved_bytes_including_duplicate_saves": self.logical_bytes,
                "unique_backing_storage_bytes_including_saved_input_aliases": sum(self.storages.values()),
                "unique_backing_storage_count": len(self.storages), "save_count": len(self.entries),
                "entries": self.entries, "collection": "one extra untimed forward/backward; no optimizer"}


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8", newline="\n")


def worker(trace_path, manifest_path, output_dir, method, seed, warmup, repeats):
    torch = require_torch()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    memory = {"after_import_before_input": process_memory()}
    bank_array, manifest = load_trace(trace_path, manifest_path)
    query_array = make_query(bank_array.shape[-1], seed)
    # The original frozen trace is detached. Gradients below belong to operator
    # leaf copies, not to the model that produced those residual activations.
    bank = torch.from_numpy(bank_array).clone().requires_grad_(True)
    query = torch.from_numpy(query_array).clone().requires_grad_(True)
    memory["after_input_and_leaf_copies"] = process_memory()
    for _ in range(warmup):
        autograd_step(bank, query, method)
    memory["after_warmup"] = process_memory()
    steps = []
    for _ in range(repeats):
        output, loss, costs = autograd_step(bank, query, method)
        steps.append(costs)
    memory["after_timed_steps"] = process_memory()
    inventory = SavedTensorInventory()
    with torch.autograd.graph.saved_tensors_hooks(inventory.pack, inventory.unpack):
        output, loss, _ = autograd_step(bank, query, method)
    memory["after_untimed_saved_tensor_step"] = process_memory()
    arrays = {"output": output.detach().numpy().copy(), "bank_gradient": bank.grad.detach().numpy().copy(),
              "query_gradient": query.grad.detach().numpy().copy()}
    if not all(np.isfinite(array).all() for array in arrays.values()) or not math.isfinite(float(loss.detach())):
        raise ValueError("nonfinite output/loss/operator gradient")
    np.savez(output_dir / "arrays.npz", **arrays)
    memory["after_output_persist"] = process_memory()
    result = {"method": method, "seed": seed, "pid": os.getpid(), "started_utc": started_utc,
              "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "warmup_steps": warmup,
              "timed_steps": steps, "memory": memory,
              "process_lifetime_peak_bytes": memory["after_output_persist"]["peak_bytes"],
              "saved_tensors": inventory.result(), "loss": float(loss.detach()),
              "all_outputs_and_gradients_finite": True,
              "array_sha256": {name: array_hash(array) for name, array in arrays.items()},
              "arrays_file_sha256": file_hash(output_dir / "arrays.npz"),
              "bank_sha256": manifest["bank_sha256"], "query_sha256": array_hash(query_array),
              "platform": {"python": platform.python_version(), "system": platform.system(),
                           "machine": platform.machine(), "numpy": np.__version__, "torch": torch.__version__,
                           "torch_threads": torch.get_num_threads(), "torch_interop_threads": torch.get_num_interop_threads()}}
    _write_json(output_dir / "worker.json", result)
    return result


def error_metrics(actual, reference):
    actual, reference = np.asarray(actual, dtype=np.float64), np.asarray(reference, dtype=np.float64)
    difference = actual - reference
    actual_norm, reference_norm = np.linalg.norm(actual.ravel()), np.linalg.norm(reference.ravel())
    return {"max_absolute": float(np.max(np.abs(difference))),
            "relative_l2": float(np.linalg.norm(difference.ravel()) / max(reference_norm, 1e-30)),
            "cosine_similarity": float(np.dot(actual.ravel(), reference.ravel()) / (actual_norm * reference_norm))
            if actual_norm > 0 and reference_norm > 0 else None}


def validate_config(seeds, warmup, repeats):
    if (not seeds or len(seeds) > 3 or len(set(seeds)) != len(seeds)
            or any(type(seed) is not int or seed < 0 or seed >= 2**32 for seed in seeds)):
        raise ValueError("provide 1..3 distinct integer seeds in [0,2**32)")
    if type(warmup) is not int or not 0 <= warmup <= 2:
        raise ValueError("warmup must be 0..2")
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("repeats must be 1..5")


def run_probe(trace_path, manifest_path, output_dir, seeds=(11, 29, 47), warmup=1, repeats=3):
    torch = require_torch()  # A real run fails clearly when the optional dependency is absent.
    seeds = list(seeds)
    validate_config(seeds, warmup, repeats)
    bank, manifest = load_trace(trace_path, manifest_path)
    trace_path, manifest_path = Path(trace_path).resolve(), Path(manifest_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / "report.json").exists():
        raise ValueError("output directory already has a report; use a fresh run directory")
    config = {"methods": list(METHODS), "seeds": seeds, "warmup": warmup, "repeats": repeats,
              "eps": EPS, "threads": 1, "loss": "mean(output**2)",
              "query": "shared deterministic Gaussian pseudoquery / sqrt(dim); no optimizer updates",
              "quantization": "per depth/token maxabs/127; round clamp [-127,127]; zero scale replaced with 1",
              "backward": "explicit identity STE through decoded bank; codes/scales detached",
              "worker_order_seed": 1729, "worker_timeout_seconds": 120, "rtol": RTOL, "atol": ATOL}
    source_files = {name: file_hash(SCRIPT.with_name(name)) for name in (
        SCRIPT.name, "attnres_memory_probe.py", "attnres_budget_probe.py")}
    workers, numerics = [], []
    jobs = [(seed, method) for seed in seeds for method in METHODS]
    random.Random(config["worker_order_seed"]).shuffle(jobs)
    environment = os.environ.copy()
    environment.update({name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    for seed, method in jobs:
        directory = output_dir / "workers" / f"seed-{seed}--{method}"
        command = [sys.executable, str(SCRIPT), "--trace", str(trace_path), "--manifest", str(manifest_path),
                   "--output", str(directory), "--worker", method, "--seed", str(seed),
                   "--warmup", str(warmup), "--repeats", str(repeats)]
        completed = subprocess.run(command, env=environment, capture_output=True, text=True,
                                   timeout=config["worker_timeout_seconds"], check=False)
        if completed.returncode:
            raise RuntimeError(f"worker failed ({seed}, {method}): {completed.stderr[-4000:]}")
        result = json.loads((directory / "worker.json").read_text(encoding="utf-8"))
        result["worker_record_file"] = (directory / "worker.json").relative_to(output_dir).as_posix()
        result["arrays_file"] = (directory / "arrays.npz").relative_to(output_dir).as_posix()
        if file_hash(directory / "arrays.npz") != result["arrays_file_sha256"]:
            raise ValueError("worker output file hash mismatch")
        workers.append(result)
    workers.sort(key=lambda item: (item["seed"], item["method"]))
    for seed in seeds:
        selected = {item["method"]: item for item in workers if item["seed"] == seed}
        arrays = {}
        for method, item in selected.items():
            with np.load(output_dir / item["arrays_file"], allow_pickle=False) as archive:
                arrays[method] = {key: archive[key] for key in archive.files}
            for key, value in arrays[method].items():
                if array_hash(value) != item["array_sha256"][key] or not np.isfinite(value).all():
                    raise ValueError("worker array hash/finite check failed")
        dense = arrays["dense_float32"]
        reference = numpy_mix(bank, make_query(bank.shape[-1], seed))
        parity = bool(np.allclose(dense["output"], reference, rtol=RTOL, atol=ATOL))
        if not parity:
            raise ValueError("dense output failed independent NumPy parity")
        numerics.append({"seed": seed, "dense_numpy_parity_passed": parity,
                         "dense_numpy_error": error_metrics(dense["output"], reference),
                         "int8_vs_dense": {name: error_metrics(arrays["int8_identity_ste"][name], dense[name])
                                           for name in ("output", "bank_gradient", "query_gradient")}})
    stable = {"config_sha256": digest(config), "source_files_sha256": source_files,
              "trace_file_sha256": manifest["trace_file_sha256"], "bank_sha256": manifest["bank_sha256"],
              "capture_config_sha256": manifest["capture_config_sha256"],
              "trace_manifest_sha256": file_hash(manifest_path), "bank_shape": list(bank.shape),
              "source_text_sha256": manifest["source_text_sha256"], "token_ids_sha256": manifest["token_ids_sha256"],
              "model_id": manifest["model_id"], "model_revision": manifest["model_revision"],
              "activation_boundary": manifest["activation_boundary"], "numerical_results": numerics,
              "workers": [{key: item[key] for key in ("method", "seed", "loss", "array_sha256", "query_sha256", "saved_tensors")}
                          for item in workers], "all_outputs_and_gradients_finite": True,
              "all_dense_numpy_parity_passed": True}
    report = {"schema_version": 1, "config": config, "stable_results": stable,
              "stable_result_sha256": digest(stable), "worker_measurements": workers,
              "runtime": {"torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version()},
              "limitations": ["Frozen pretrained residual replay with random shared pseudoqueries; no learned query or optimizer updates.",
                              "Cumulative pre-block Pythia residual states are an independent operator fixture, not AttnRes branch outputs.",
                              "Timed repetitions reuse the same bank/query without updates inside each fresh method/seed worker; they are not independent process replicates.",
                              "Gradients belong to detached operator leaf copies, not the pretrained backbone.",
                              "Identity STE is a surrogate gradient; quantizer scales/codes are detached.",
                              "Every timed int8 step packs the original float32 bank and materializes its float32 decoded copy.",
                              "CPU lifetime peaks include imports, input copies, warmup, timed steps, untimed hooks, and output persistence; not isolated operator peaks.",
                              "Saved tensor logical/storage counts are inventories, not measured process memory or training-memory savings.",
                              "Exact numerical hashes document this runtime; parity uses tolerance and cross-platform exact hashes are not required.",
                              "No model quality, held-out token performance, full training, GPU benefit, or upstream architecture reproduction claim."]}
    report["observation_sha256"] = digest(report)
    _write_json(output_dir / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=[11, 29, 47])
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--worker", choices=METHODS, help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        validate_config([args.seed], args.warmup, args.repeats)
        worker(args.trace, args.manifest, args.output, args.worker, args.seed, args.warmup, args.repeats)
    else:
        result = run_probe(args.trace, args.manifest, args.output, args.seeds, args.warmup, args.repeats)
        print(canonical({"report": str(args.output / "report.json"),
                         "stable_result_sha256": result["stable_result_sha256"],
                         "observation_sha256": result["observation_sha256"]}))


if __name__ == "__main__":
    main()
