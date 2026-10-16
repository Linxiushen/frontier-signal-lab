"""Prospective CPU training cost, process peak and sealed final-text diagnostic.

The timed workers never open the heldout data. Profiling and final evaluation
run in separate fresh processes after the twelve training endpoints are sealed.
No model execution occurs at import time; ML dependencies are optional.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager, nullcontext
import ctypes
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.capture_real_activation import MODEL_ID, MODEL_REVISION, PINNED_ASSETS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
SEEDS = (503, 701, 907)
METHODS = ("dense", "model_except_norm_attention_saved_int8")
ATTENTION_CLASS = "transformers.models.gpt_neox.modeling_gpt_neox.GPTNeoXAttention"
SOURCE_PATHS = ("experiments/activation_cost_probe.py", "tests/test_activation_cost.py", "scripts/prepare_activation_cost.py")
MAX_JSON_BYTES = 1024 * 1024


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def read_small(path):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON exceeds 1 MiB: " + path.name)
    return json.loads(path.read_text(encoding="utf-8"))


def preset_config():
    return {"model_id": MODEL_ID, "model_revision": MODEL_REVISION,
            "seeds": list(SEEDS), "methods": list(METHODS), "train_blocks": 128,
            "holdout_blocks": 64, "batch_size": 2, "sequence_input_tokens": 64,
            "token_steps": 64, "time_budget_seconds": 60.0,
            "max_time_overshoot_seconds": 1.0, "max_time_steps": 4096,
            "profile_steps": 2, "threads": 1, "dtype": "float32", "attention": "eager",
            "optimizer": {"learning_rate": 0.0001, "betas": [0.9, 0.999],
                          "epsilon": 1e-8, "weight_decay": 0.01, "foreach": False, "fused": False},
            "max_token_loop_seconds": 120.0, "max_time_loop_seconds": 65.0,
            "token_worker_timeout_seconds": 180, "time_worker_timeout_seconds": 120,
            "profile_worker_timeout_seconds": 120, "evaluation_timeout_seconds": 300,
            "total_timeout_seconds": 1200, "max_resident_bytes": 2147483648,
            "max_private_bytes": 3221225472, "min_free_memory_bytes": 8589934592,
            "min_free_disk_bytes": 5368709120, "max_output_bytes": 1610612736,
            "sampler_interval_seconds": 0.02, "min_compressed_elements": 256,
            "expected_layernorm_modules": 13, "expected_attention_modules": 6,
            "schedule": "stdlib Random(seed).shuffle complete128-block epochs; batch2; full4096-step schedule fixed before all loops"}


def batch_schedule(count, steps, batch_size, seed):
    if count < 1 or steps < 1 or batch_size < 1 or count % batch_size:
        raise ValueError("invalid complete-epoch schedule dimensions")
    rng, order = random.Random(seed), []
    while len(order) < steps * batch_size:
        epoch = list(range(count))
        rng.shuffle(epoch)
        order.extend(epoch)
    return [order[i:i + batch_size] for i in range(0, steps * batch_size, batch_size)]


def job_order():
    jobs = []
    for arm, offset in (("token", 0), ("time", 1)):
        for i, seed in enumerate(SEEDS):
            methods = METHODS if (i + offset) % 2 == 0 else tuple(reversed(METHODS))
            jobs.extend({"arm": arm, "seed": seed, "method": m} for m in methods)
    return jobs


def load_blocks(path, key, expected_count):
    data = read_small(path)
    blocks = data.get(key)
    if data.get("schema_version") != 1 or not isinstance(blocks, list) or len(blocks) != expected_count:
        raise ValueError("invalid " + key + " block count/schema")
    if any(not isinstance(b, list) or len(b) != 65 or
           any(type(t) is not int or not 0 <= t < 50304 for t in b) for b in blocks):
        raise ValueError("invalid " + key + " token block")
    if len({tuple(b) for b in blocks}) != len(blocks):
        raise ValueError("duplicate " + key + " blocks")
    return blocks


def validate_fixture(fixture, verify_holdout=False):
    """Training path validates only the train bytes and heldout hash metadata."""
    fixture = Path(fixture)
    manifest = read_small(fixture / "manifest.json")
    protocol = read_small(fixture / "protocol.json")
    freeze = read_small(fixture / "implementation.json")
    if manifest.get("schema_version") != 1 or manifest.get("model_id") != MODEL_ID or manifest.get("model_revision") != MODEL_REVISION:
        raise ValueError("manifest model/schema mismatch")
    if manifest.get("tokenizer_sha256") != PINNED_ASSETS["tokenizer.json"][1]:
        raise ValueError("tokenizer pin mismatch")
    for key in ("train_sha256", "holdout_sha256", "train_source_sha256", "holdout_source_sha256"):
        value = manifest.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("missing/invalid " + key)
    if manifest["train_source_sha256"] == manifest["holdout_source_sha256"]:
        raise ValueError("source files must differ")
    if file_hash(fixture / "train.json") != manifest["train_sha256"]:
        raise ValueError("train file hash mismatch")
    if verify_holdout and file_hash(fixture / "holdout.json") != manifest["holdout_sha256"]:
        raise ValueError("holdout file hash mismatch")
    if protocol.get("schema_version") != 1 or protocol.get("config") != preset_config() or protocol.get("config_sha256") != digest(preset_config()):
        raise ValueError("protocol fixed config mismatch")
    for key, expected in (("train_sha256", manifest["train_sha256"]), ("holdout_sha256", manifest["holdout_sha256"]),
                          ("manifest_sha256", file_hash(fixture / "manifest.json"))):
        if protocol.get(key) != expected:
            raise ValueError("protocol " + key + " mismatch")
    if freeze.get("schema_version") != 1 or freeze.get("protocol_sha256") != file_hash(fixture / "protocol.json"):
        raise ValueError("implementation protocol mismatch")
    dependencies = protocol.get("frozen_dependencies_sha256", {})
    if not isinstance(dependencies, dict) or "scripts/capture_real_activation.py" not in dependencies:
        raise ValueError("protocol missing pinned dependency set")
    for name, expected in dependencies.items():
        if file_hash(ROOT / name) != expected:
            raise ValueError("protocol dependency changed: " + name)
    if protocol.get("preparation_script_sha256") != file_hash(ROOT / "scripts/prepare_activation_cost.py"):
        raise ValueError("preparation script changed")
    for seed in SEEDS:
        full = batch_schedule(128, 4096, 2, seed)
        declared_schedule = protocol.get("schedules", {}).get(str(seed), {})
        if (declared_schedule.get("time_schedule_sha256") != digest(full)
                or declared_schedule.get("token_schedule_sha256") != digest(full[:64])
                or declared_schedule.get("token_batches") != full[:64]):
            raise ValueError("protocol schedule mismatch")
    for key, names in (("new_source_files_sha256", SOURCE_PATHS), ("frozen_dependencies_sha256", tuple(dependencies))):
        table = freeze.get(key, {})
        if not isinstance(table, dict) or any(table.get(name) != file_hash(ROOT / name) for name in names):
            raise ValueError("implementation source mismatch: " + key)
        if any(file_hash(ROOT / name) != expected for name, expected in table.items()):
            raise ValueError("implementation extra source mismatch: " + key)
    declared = dt.datetime.fromisoformat(protocol["predeclared_at"].replace("Z", "+00:00"))
    frozen = dt.datetime.fromisoformat(freeze["frozen_at"].replace("Z", "+00:00"))
    if declared.tzinfo is None or frozen.tzinfo is None or not declared < frozen <= dt.datetime.now(dt.timezone.utc):
        raise ValueError("invalid protocol/freeze chronology")
    return manifest, protocol, freeze


def require_torch():
    try:
        import torch
    except ImportError as error:
        raise RuntimeError("optional CPU Torch required; no synthetic fallback") from error
    return torch


def verify_model_assets(model_dir):
    folder = Path(model_dir)
    for name, (size, expected) in PINNED_ASSETS.items():
        path = folder / name
        if not path.is_file() or path.stat().st_size != size or file_hash(path) != expected:
            raise ValueError("pinned asset mismatch: " + name)
    overrides = ("added_tokens.json", "vocab.json", "merges.txt", "vocab.txt", "tokenizer.model", "chat_template.jinja", "adapter_config.json")
    if any((folder / name).exists() for name in overrides):
        raise ValueError("unpinned loader override")


def load_model(model_dir, seed):
    torch = require_torch()
    from transformers import AutoModelForCausalLM
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    model = AutoModelForCausalLM.from_pretrained(str(model_dir), local_files_only=True,
        trust_remote_code=False, torch_dtype=torch.float32, attn_implementation="eager").cpu().eval()
    if len(list(model.parameters())) != 76 or sum(p.numel() for p in model.parameters()) != 14067712:
        raise ValueError("pinned trainable parameter layout changed")
    if any(p.dtype != torch.float32 or not p.requires_grad for p in model.parameters()):
        raise ValueError("parameters must all be trainable CPU float32")
    if any(isinstance(m, torch.nn.Dropout) and m.p != 0 for m in model.modules()):
        raise ValueError("unexpected nonzero dropout")
    return model


def parameter_hash(model):
    """Bounded streaming digest; no retained clone/reference or bytes copy."""
    h = hashlib.sha256()
    for name, value in model.named_parameters():
        if not value.is_contiguous():
            raise ValueError("streaming parameter digest requires contiguous tensors")
        h.update(canonical({"name": name, "shape": list(value.shape), "dtype": str(value.dtype)}).encode())
        h.update(memoryview(value.detach().numpy()).cast("B"))
    return h.hexdigest()


def storage_key(tensor):
    return (str(tensor.device), tensor.untyped_storage().data_ptr())


class CostCodec:
    """Required quantizer work only: no callbacks clocks, shape tables or counters."""
    def __init__(self, parameters, compress=True):
        self.parameter_storages = {storage_key(p) for p in parameters}
        self.compress = compress

    def eligible(self, tensor):
        torch = require_torch()
        return (storage_key(tensor) not in self.parameter_storages and tensor.device.type == "cpu"
                and tensor.dtype == torch.float32 and tensor.ndim > 0 and tensor.numel() >= 256 and tensor.shape[-1] > 0)

    def pack(self, tensor):
        torch = require_torch()
        if self.compress and self.eligible(tensor):
            with torch.no_grad():
                # Same finite-value policy and quantizer as the existing codec.
                if not bool(torch.isfinite(tensor).all()):
                    raise ValueError("nonfinite saved activation")
                maximum = tensor.detach().abs().amax(dim=-1, keepdim=True)
                scales = torch.where(maximum == 0, torch.ones_like(maximum), maximum / 127.0)
                codes = torch.round(tensor.detach() / scales).clamp(-127, 127).to(torch.int8)
            return codes, scales
        return tensor.detach()

    def unpack(self, payload):
        if isinstance(payload, tuple):
            codes, scales = payload
            return codes.to(scales.dtype) * scales
        return payload


class ProfileCodec(CostCodec):
    """Auxiliary instrumentation; never instantiated in timed training workers."""
    def __init__(self, parameters, compress=True):
        super().__init__(parameters, compress)
        self.counts, self.shapes, self.retained, self.parameters = Counter(), Counter(), {}, {}
        self.original_bytes = self.payload_bytes = 0
        self.pack_seconds = self.unpack_seconds = 0.0

    def pack(self, tensor):
        start = time.perf_counter()
        parameter = storage_key(tensor) in self.parameter_storages
        eligible = self.eligible(tensor)
        policy = "parameter_storage_excluded" if parameter else ("eligible" if eligible else "dtype_size_shape_excluded")
        self.counts["save_calls"] += 1
        self.counts[policy] += 1
        self.shapes[(policy, str(tensor.dtype), tuple(tensor.shape))] += 1
        self.original_bytes += tensor.numel() * tensor.element_size()
        payload = super().pack(tensor)
        if isinstance(payload, tuple):
            self.counts["compressed_saves"] += 1
        for item in payload if isinstance(payload, tuple) else (payload,):
            (self.parameters if parameter else self.retained)[storage_key(item)] = item.untyped_storage().nbytes()
            self.payload_bytes += item.numel() * item.element_size()
        self.pack_seconds += time.perf_counter() - start
        return payload

    def unpack(self, payload):
        start = time.perf_counter()
        self.counts["unpack_calls"] += 1
        if isinstance(payload, tuple):
            self.counts["decoded_saves"] += 1
        result = super().unpack(payload)
        self.unpack_seconds += time.perf_counter() - start
        return result

    def inventory(self):
        return {"counts": dict(self.counts), "original_logical_bytes_including_duplicates": self.original_bytes,
                "retained_logical_payload_bytes_including_duplicates": self.payload_bytes,
                "retained_nonparameter_backing_union_bytes": sum(self.retained.values()),
                "retained_parameter_backing_union_bytes": sum(self.parameters.values()),
                "callback_pack_seconds_instrumented": self.pack_seconds,
                "callback_unpack_seconds_instrumented": self.unpack_seconds,
                "shape_audit": [{"policy": p, "dtype": t, "shape": list(s), "saves": n}
                                for (p, t, s), n in sorted(self.shapes.items())]}


def exact_pack(tensor):
    return tensor.detach()


def exact_unpack(payload):
    return payload


def preservation_modules(model):
    torch = require_torch()
    from transformers.models.gpt_neox.modeling_gpt_neox import GPTNeoXAttention
    norms, attentions = [], []
    for name, module in model.named_modules():
        if isinstance(module, torch.nn.LayerNorm):
            norms.append((name, module))
        if isinstance(module, GPTNeoXAttention):
            if type(module).__module__ + "." + type(module).__name__ != ATTENTION_CLASS:
                raise ValueError("unexpected attention subclass")
            attentions.append((name, module))
    if len(norms) != 13 or len(attentions) != 6:
        raise ValueError("exact norm/attention preservation layout mismatch")
    return norms, attentions


@contextmanager
def preserve_scopes(modules, profile_codecs=None):
    """Identical nested save-mask semantics; restore even on forward failure."""
    torch = require_torch()
    missing, originals = object(), []
    try:
        for name, module in modules:
            previous = module.__dict__.get("forward", missing)
            original = module.forward
            codec = profile_codecs[name] if profile_codecs is not None else None

            def forward(*args, _original=original, _codec=codec, **kwargs):
                pack, unpack = (_codec.pack, _codec.unpack) if _codec is not None else (exact_pack, exact_unpack)
                with torch.autograd.graph.saved_tensors_hooks(pack, unpack):
                    return _original(*args, **kwargs)

            originals.append((module, previous))
            module.forward = forward
        yield
    finally:
        for module, previous in reversed(originals):
            if previous is missing:
                delattr(module, "forward")
            else:
                module.forward = previous


def forward_loss(model, tokens, codec=None):
    torch = require_torch()
    hooks = torch.autograd.graph.saved_tensors_hooks(codec.pack, codec.unpack) if codec is not None else nullcontext()
    with hooks:
        logits = model(input_ids=tokens[:, :-1].contiguous(), use_cache=False).logits
    # Exact CE sits OUTSIDE all compression hooks in every arm.
    return torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), tokens[:, 1:].contiguous().reshape(-1))


def classify_time(elapsed, steps, config=None):
    c = preset_config() if config is None else config
    valid = (c["time_budget_seconds"] <= elapsed <= c["time_budget_seconds"] + c["max_time_overshoot_seconds"]
             and 0 < steps < c["max_time_steps"])
    return {"valid": valid, "actual_loop_seconds": elapsed,
            "overshoot_seconds": elapsed - c["time_budget_seconds"],
            "reached_budget": elapsed >= c["time_budget_seconds"],
            "step_cap_reached": steps >= c["max_time_steps"],
            "interpretation": "atomic-step approximately matched time; explicit [60,61]s window, no retry"}


def memory_info(pid=None):
    """OS lifetime high-water is exact; external current RSS samples are not."""
    if platform.system() == "Windows":
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        api = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        api.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        api.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel.GetCurrentProcess() if pid is None else kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            result = Counters(); result.cb = ctypes.sizeof(result)
            if not api.GetProcessMemoryInfo(handle, ctypes.byref(result), result.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            return {"peak_bytes": int(result.PeakWorkingSetSize), "resident_bytes": int(result.WorkingSetSize),
                    "private_bytes": int(result.PrivateUsage), "backend": "Windows GetProcessMemoryInfo"}
        finally:
            if pid is not None:
                kernel.CloseHandle(handle)
    if platform.system() == "Linux":
        status = {}
        for line in Path("/proc/" + ("self" if pid is None else str(pid)) + "/status").read_text().splitlines():
            fields = line.split()
            if fields and fields[0] in ("VmHWM:", "VmRSS:"):
                status[fields[0]] = int(fields[1]) * 1024
        return {"peak_bytes": status["VmHWM:"], "resident_bytes": status["VmRSS:"],
                "private_bytes": None, "backend": "Linux procfs VmHWM/VmRSS; private bytes unavailable"}
    raise RuntimeError("process memory supported on Windows/Linux only")


def free_memory_bytes():
    if platform.system() == "Windows":
        from ctypes import wintypes
        class Status(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in ("total_phys", "avail_phys", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_extended")]
        value = Status(); value.length = ctypes.sizeof(value)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
            raise ctypes.WinError()
        return int(value.avail_phys)
    if platform.system() == "Linux":
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("free physical memory unavailable")


def optimizer_for(model):
    torch = require_torch(); o = preset_config()["optimizer"]
    return torch.optim.AdamW(model.parameters(), lr=o["learning_rate"], betas=tuple(o["betas"]),
        eps=o["epsilon"], weight_decay=o["weight_decay"], foreach=False, fused=False)


def training_loop(model, optimizer, batches, arm, method, modules, profile=False, config=None):
    """No heldout, references, state clones, hashes, or per-pack clocks here."""
    torch = require_torch(); c = preset_config() if config is None else config
    if arm not in ("token", "time", "profile") or method not in METHODS:
        raise ValueError("unknown arm/method")
    if profile:
        return profile_loop(model, optimizer, batches, method, modules, c)
    parameters = list(model.parameters())
    active = method != "dense"
    outer = CostCodec(parameters) if active else None
    limit = c["profile_steps"] if arm == "profile" else (c["token_steps"] if arm == "token" else c["max_time_steps"])
    losses = [None] * limit
    wall0, cpu0 = time.perf_counter(), time.process_time()
    with preserve_scopes(modules) if active else nullcontext():
        for i in range(limit):
            optimizer.zero_grad(set_to_none=True)
            loss = forward_loss(model, batches[i], outer)
            loss.backward()
            optimizer.step()
            # Scalar synchronization/logging occurs after the update but inside
            # the total wall/CPU clock and the real time-budget deadline.
            losses[i] = float(loss.detach())
            if not math.isfinite(losses[i]):
                raise ValueError("nonfinite observed training loss")
            elapsed = time.perf_counter() - wall0
            hard = c["max_time_loop_seconds"] if arm == "time" else c["max_token_loop_seconds"]
            if elapsed > hard:
                raise TimeoutError("training loop hard deadline exceeded")
            if arm == "time" and elapsed >= c["time_budget_seconds"]:
                break
    cpu, wall_end = time.process_time() - cpu0, time.perf_counter()
    wall = wall_end - wall0
    steps = i + 1
    out = {"steps_completed": steps, "training_target_positions": steps * 128,
           "training_loop_wall_seconds": wall, "training_loop_cpu_seconds": cpu,
           "loop_perf_counter_start": wall0, "loop_perf_counter_end": wall_end,
           "training_targets_per_second": steps * 128 / wall, "preupdate_batch_losses_recorded_after_updates": losses[:steps],
           "time_control": classify_time(wall, steps, c) if arm == "time" else None,
           "cost_boundary": "loop includes necessary hooks, all training work, scalar loss record/check, scope setup/restoration; excludes postvalidation/checkpoint/evaluation"}
    return out


def profile_loop(model, optimizer, batches, method, modules, config):
    """Fresh inventories per step: never union allocation pointers across steps."""
    parameters, profiles, losses = list(model.parameters()), [], []
    wall0, cpu0 = time.perf_counter(), time.process_time()
    for i in range(config["profile_steps"]):
        outer = ProfileCodec(parameters, method != "dense")
        scopes = {name: ProfileCodec(parameters, False) for name, _ in modules}
        optimizer.zero_grad(set_to_none=True)
        with preserve_scopes(modules, scopes):
            loss = forward_loss(model, batches[i], outer)
            loss.backward()
        optimizer.step()
        losses.append(float(loss.detach()))
        if not math.isfinite(losses[-1]):
            raise ValueError("nonfinite profiled training loss")
        for codec in scopes.values():
            if (codec.counts["save_calls"] < 1 or codec.counts["unpack_calls"] < 1
                    or codec.counts["compressed_saves"] or codec.counts["decoded_saves"]):
                raise ValueError("profile exact-scope save/unpack coverage failed")
        compressed = outer.counts["compressed_saves"]
        if method != "dense":
            if compressed < 1 or compressed != outer.counts["eligible"] or compressed != outer.counts["decoded_saves"]:
                raise ValueError("profile outer compression coverage failed")
        elif compressed or outer.counts["decoded_saves"]:
            raise ValueError("profile dense scope unexpectedly compressed")
        # Global union across all simultaneously retained forward-save scopes.
        union = {}
        for codec in (outer, *scopes.values()):
            union.update(codec.retained)
        profiles.append({"step": i + 1, "outer": outer.inventory(),
                         "preserved_scopes": {name: codec.inventory() for name, codec in scopes.items()},
                         "all_scope_nonparameter_backing_union_bytes": sum(union.values())})
    wall_end, cpu = time.perf_counter(), time.process_time() - cpu0
    wall = wall_end - wall0
    return {"steps_completed": config["profile_steps"], "training_target_positions": config["profile_steps"] * 128,
            "training_loop_wall_seconds": wall, "training_loop_cpu_seconds": cpu,
            "loop_perf_counter_start": wall0, "loop_perf_counter_end": wall_end,
            "training_targets_per_second": config["profile_steps"] * 128 / wall,
            "preupdate_batch_losses_recorded_after_updates": losses, "time_control": None,
            "profile": {"steps": profiles, "boundary": "two instrumented actual steps from initial weights; individual step inventories; not primary cost/peak or mean training callback cost"}}


def final_validity(model, optimizer, steps):
    torch = require_torch()
    counts = []
    for p in model.parameters():
        if p.grad is None or not bool(torch.isfinite(p).all()) or not bool(torch.isfinite(p.grad).all()):
            raise ValueError("nonfinite final parameter/gradient")
        state = optimizer.state[p]
        if not all(bool(torch.isfinite(state[k]).all()) for k in ("exp_avg", "exp_avg_sq")):
            raise ValueError("nonfinite final moments")
        counts.append(int(state["step"].item()))
    if counts != [steps] * len(counts):
        raise ValueError("native optimizer counters mismatch")
    return {"final_parameter_gradient_moments_finite": True, "optimizer_counters": counts,
            "boundary": "post-loop final checks; not proof of every intermediate gradient or numerical update fidelity"}


def training_worker(model_dir, fixture, output, arm, method, seed):
    """NO holdout file opens, even to compute its hash."""
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    try:
        manifest, protocol, freeze = validate_fixture(fixture, verify_holdout=False)
        c = preset_config()
        if seed not in SEEDS or method not in METHODS or arm not in ("token", "time", "profile"):
            raise ValueError("job absent from predeclared design")
        blocks = load_blocks(Path(fixture) / "train.json", "train", 128)
        schedule = batch_schedule(128, c["max_time_steps"], 2, seed)
        verify_model_assets(model_dir)
        torch = require_torch()
        model = load_model(model_dir, seed)
        model_ready_memory = memory_info()
        norms, attentions = preservation_modules(model)
        optimizer = optimizer_for(model)
        steps = c["max_time_steps"] if arm == "time" else (c["profile_steps"] if arm == "profile" else c["token_steps"])
        all_tokens = torch.tensor(blocks, dtype=torch.long)
        # Allocate all indexed input batches BEFORE the cost boundary. This
        # fixed, declared cache is small (max~4.1MiB) and included in process peak.
        batches = [all_tokens[indices] for indices in schedule[:steps]]
        initial = parameter_hash(model)
        start_memory = memory_info()
        started_at = utc_now()
        result = training_loop(model, optimizer, batches, arm, method, norms + attentions, profile=arm == "profile")
        finish_memory = memory_info()
        # Persist the immutable boundary BEFORE postvalidation/hashes/checkpoint.
        boundary = {"schema_version": 1, "seed": seed, "arm": arm, "method": method,
                    "started_at": started_at, "completed_at": utc_now(), **result,
                    "memory_model_ready_before_optimizer_batches": model_ready_memory,
                    "memory_before_training": start_memory, "memory_through_training_completion": finish_memory,
                    "lifetime_peak_boundary": "imports/load/setup/streaming initial digest/training only; not isolated training peak; later postprocessing excluded"}
        write_new(output / "cost-boundary.json", boundary)
        valid = final_validity(model, optimizer, result["steps_completed"])
        final = parameter_hash(model)
        if initial == final:
            raise ValueError("no change to overall parameter digest")
        checkpoint = None
        if arm != "profile":
            checkpoint = output / "checkpoint.pt"
            with checkpoint.open("xb") as stream:
                torch.save(model.state_dict(), stream)
        record = {**boundary, "completed": True, "initial_parameter_sha256": initial,
                  "final_parameter_sha256": final, "schedule_sha256": digest(schedule),
                  "used_schedule_sha256": digest(schedule[:result["steps_completed"]]),
                  "train_sha256": manifest["train_sha256"], "protocol_sha256": file_hash(Path(fixture) / "protocol.json"),
                  "implementation_sha256": file_hash(Path(fixture) / "implementation.json"),
                  "final_validity": valid, "checkpoint": checkpoint.name if checkpoint else None,
                  "checkpoint_sha256": file_hash(checkpoint) if checkpoint else None,
                  "runtime": {"python": platform.python_version(), "torch": torch.__version__, "system": platform.system(),
                              "device": "cpu", "threads": torch.get_num_threads(), "deterministic": torch.are_deterministic_algorithms_enabled()}}
        write_new(output / "worker.json", record)
        return record
    except BaseException as error:
        write_new(output / "failure.json", {"completed": False, "at": utc_now(), "type": type(error).__name__, "error": str(error),
                  "seed": seed, "arm": arm, "method": method, "no_retry": True})
        raise


def evaluate_model(model, blocks):
    torch = require_torch()
    values = []
    with torch.no_grad():
        for block in blocks:
            tokens = torch.tensor([block], dtype=torch.long)
            value = float(forward_loss(model, tokens))
            if not math.isfinite(value):
                raise ValueError("nonfinite sealed final evaluation")
            values.append(value)
    return {"mean_nll": math.fsum(values) / len(values), "scored_target_positions": len(values) * 64,
            "block_mean_nll": values}


def validate_release(release):
    endpoints = release.get("endpoints", [])
    expected = {(j["arm"], j["seed"], j["method"]) for j in job_order()}
    actual = [(j.get("arm"), j.get("seed"), j.get("method")) for j in endpoints]
    if release.get("all_training_completed") is not True or len(actual) != 12 or set(actual) != expected:
        raise ValueError("heldout release requires every declared training endpoint")
    for e in endpoints:
        if file_hash(e["checkpoint_path"]) != e["checkpoint_sha256"]:
            raise ValueError("endpoint checkpoint hash mismatch before release")
    return endpoints


def evaluation_worker(model_dir, fixture, output, release_path):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    try:
        release = read_small(release_path)
        endpoints = validate_release(release)
        started_at = utc_now()
        manifest, _, _ = validate_fixture(fixture, verify_holdout=True)
        if release.get("protocol_sha256") != file_hash(Path(fixture) / "protocol.json"):
            raise ValueError("release protocol mismatch")
        # First semantic read of heldout data in any experiment worker.
        blocks = load_blocks(Path(fixture) / "holdout.json", "holdout", 64)
        train = load_blocks(Path(fixture) / "train.json", "train", 128)
        if set(map(tuple, blocks)) & set(map(tuple, train)):
            raise ValueError("identical train/heldout blocks")
        torch = require_torch()
        verify_model_assets(model_dir)
        model = load_model(model_dir, SEEDS[0])
        baseline_hash = parameter_hash(model)
        initial = evaluate_model(model, blocks)
        results = []
        for e in endpoints:
            state = torch.load(e["checkpoint_path"], map_location="cpu", weights_only=True)
            model.load_state_dict(state, strict=True)
            del state
            if parameter_hash(model) != e["final_parameter_sha256"] or baseline_hash != e["initial_parameter_sha256"]:
                raise ValueError("initial/final model digest mismatch in evaluation")
            results.append({"arm": e["arm"], "seed": e["seed"], "method": e["method"],
                            "checkpoint_sha256": e["checkpoint_sha256"], "evaluation": evaluate_model(model, blocks)})
        result = {"completed": True, "started_only_after_all_training": True, "started_at": started_at, "completed_at": utc_now(), "release_sha256": file_hash(release_path),
                  "holdout_sha256": manifest["holdout_sha256"], "initial_parameter_sha256": baseline_hash,
                  "initial": initial, "endpoints": results,
                  "limitation": "separate-book fixed fiction prefix; possible pretraining overlap; no general quality or causal claim"}
        write_new(output / "evaluation.json", result)
        return result
    except BaseException as error:
        write_new(output / "failure.json", {"completed": False, "at": utc_now(), "type": type(error).__name__, "error": str(error), "no_retry": True})
        raise


def directional_screens(workers, evaluation):
    comparisons = []
    baseline = evaluation["initial"]["mean_nll"]
    for arm in ("token", "time"):
        for seed in SEEDS:
            pair = [next(w for w in workers if w["arm"] == arm and w["seed"] == seed and w["method"] == method) for method in METHODS]
            scores = [next(e for e in evaluation["endpoints"] if e["arm"] == arm and e["seed"] == seed and e["method"] == method)["evaluation"]["mean_nll"] for method in METHODS]
            dense, compressed = pair
            valid_time = arm != "time" or all(w["time_control"]["valid"] for w in pair)
            conditions = {"compressed_nll_no_worse_than_dense": scores[1] <= scores[0], "compressed_nll_below_initial": scores[1] < baseline}
            if arm == "token":
                conditions.update(compressed_loop_strictly_faster=compressed["training_loop_wall_seconds"] < dense["training_loop_wall_seconds"],
                    compressed_lifetime_peak_strictly_lower=compressed["memory_through_training_completion"]["peak_bytes"] < dense["memory_through_training_completion"]["peak_bytes"])
            comparisons.append({"arm": arm, "seed": seed, "initial_nll": baseline, "dense_final_nll": scores[0], "compressed_final_nll": scores[1],
                "compressed_minus_dense_nll": scores[1] - scores[0], "dense_final_minus_initial_nll": scores[0] - baseline,
                "compressed_final_minus_initial_nll": scores[1] - baseline,
                "compressed_to_dense_wall_ratio": compressed["training_loop_wall_seconds"] / dense["training_loop_wall_seconds"],
                "compressed_minus_dense_lifetime_peak_bytes": compressed["memory_through_training_completion"]["peak_bytes"] - dense["memory_through_training_completion"]["peak_bytes"],
                "time_control_valid": valid_time, "conditions": conditions, "directional_screen_passed": valid_time and all(conditions.values())})
    return {"comparisons": comparisons,
            "all_token_directional_screens_passed": all(x["directional_screen_passed"] for x in comparisons if x["arm"] == "token"),
            "all_time_controls_and_directional_screens_passed": all(x["directional_screen_passed"] for x in comparisons if x["arm"] == "time"),
            "interpretation": "strict prospective sign screen only, no tolerance/equivalence/significance/general efficiency or quality claim"}


def output_bytes(folder):
    return sum(p.stat().st_size for p in Path(folder).rglob("*") if p.is_file())


def training_sample_summary(samples, start, end):
    selected = [s for s in samples if start <= s["sample_perf_counter"] <= end]
    points = [start] + [s["sample_perf_counter"] for s in selected] + [end]
    return {"samples_count": len(selected), "sampled_max_resident_bytes": max((s["resident_bytes"] for s in selected), default=None),
            "sampled_max_private_bytes": max((s["private_bytes"] for s in selected if s["private_bytes"] is not None), default=None),
            "largest_gap_including_boundaries_seconds": max((b - a for a, b in zip(points, points[1:])), default=None),
            "loop_perf_counter_start": start, "loop_perf_counter_end": end,
            "scope": "samples with cross-process monotonic timestamps in actual training interval; lower bound, not exact peak; query timing is approximate"}


def run_child(command, output, timeout, global_deadline, config):
    """Parent-only sampling; native child high-water receipt remains separate."""
    output = Path(output)
    environment = os.environ.copy()
    environment.update({name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    environment.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    samples, failure, started = [], None, time.perf_counter()
    stdout_path, stderr_path = output.parent / (output.name + "-stdout.txt"), output.parent / (output.name + "-stderr.txt")
    output.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
        child = subprocess.Popen(command, env=environment, stdout=stdout, stderr=stderr)
        try:
            while child.poll() is None:
                now = time.perf_counter()
                if now - started > timeout or now > global_deadline:
                    failure = "child/global wall deadline exceeded"
                    break
                try:
                    measured = memory_info(child.pid)
                    sample = {"elapsed_seconds": now - started, "sample_perf_counter": time.perf_counter(), **measured}
                    samples.append(sample)
                    if sample["resident_bytes"] > config["max_resident_bytes"] or (sample["private_bytes"] is not None and sample["private_bytes"] > config["max_private_bytes"]):
                        failure = "sampled process memory cap exceeded"
                        break
                except (OSError, KeyError):
                    if child.poll() is None:
                        raise
                time.sleep(config["sampler_interval_seconds"])
        finally:
            if child.poll() is None:
                child.kill()
            child.wait()
    summary = {"samples_count": len(samples), "samples": samples,
               "max_gap_seconds": max((b["elapsed_seconds"] - a["elapsed_seconds"] for a, b in zip(samples, samples[1:])), default=None),
               "sampled_max_resident_bytes": max((s["resident_bytes"] for s in samples), default=None),
               "scope": "child lifetime including setup/postprocessing; sampled max is lower bound, NOT exact training peak",
               "parent_wall_seconds": time.perf_counter() - started, "returncode": child.returncode, "failure": failure}
    if (output / "cost-boundary.json").exists():
        boundary = read_small(output / "cost-boundary.json")
        summary["training_interval_samples"] = training_sample_summary(samples, boundary["loop_perf_counter_start"], boundary["loop_perf_counter_end"])
    write_new(output.parent / (output.name + "-memory-samples.json"), summary)
    if failure or child.returncode:
        raise RuntimeError(failure or "child failed with exit " + str(child.returncode))
    return {k: v for k, v in summary.items() if k != "samples"}


def run_probe(model_dir, fixture, output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter(); c = preset_config(); deadline = start + c["total_timeout_seconds"]
    try:
        manifest, protocol, freeze = validate_fixture(fixture, verify_holdout=True)
        verify_model_assets(model_dir)
        write_new(output / "execution-start.json", {"at": utc_now(), "config": c,
            "protocol_sha256": file_hash(Path(fixture) / "protocol.json"), "implementation_sha256": file_hash(Path(fixture) / "implementation.json"),
            "jobs": job_order(), "heldout_semantic_reads_before_training": 0})
        workers, profiles, endpoints = [], [], []
        jobs = job_order() + [{"arm": "profile", "seed": seed, "method": method} for seed in SEEDS for method in METHODS]
        for job in jobs:
            if free_memory_bytes() < c["min_free_memory_bytes"] or shutil.disk_usage(output).free < c["min_free_disk_bytes"]:
                raise RuntimeError("free memory/disk prerequisite failed before child")
            if output_bytes(output) > c["max_output_bytes"] or time.perf_counter() >= deadline:
                raise RuntimeError("run output/global budget exhausted")
            directory = output / "workers" / (str(job["seed"]) + "--" + job["arm"] + "--" + job["method"])
            command = [sys.executable, str(SCRIPT), "--model-dir", str(Path(model_dir).resolve()), "--fixture", str(Path(fixture).resolve()),
                       "--output", str(directory), "--worker", job["arm"], "--method", job["method"], "--seed", str(job["seed"])]
            sample = run_child(command, directory, c[job["arm"] + "_worker_timeout_seconds"], deadline, c)
            w = read_small(directory / "worker.json")
            w["parent_sampling"] = sample
            if not w.get("completed"):
                raise ValueError("incomplete worker")
            if job["arm"] == "profile":
                profiles.append(w)
            else:
                workers.append(w)
                endpoints.append({**job, "checkpoint_path": str(directory / "checkpoint.pt"), "checkpoint_sha256": w["checkpoint_sha256"],
                                  "initial_parameter_sha256": w["initial_parameter_sha256"], "final_parameter_sha256": w["final_parameter_sha256"]})
        # All pairing checks precede the sole evaluator and heldout release.
        if len(workers) != 12 or len(profiles) != 6 or len({w["initial_parameter_sha256"] for w in workers + profiles}) != 1:
            raise ValueError("incomplete jobs or mismatched initial weights")
        for seed in SEEDS:
            if len({w["schedule_sha256"] for w in workers + profiles if w["seed"] == seed}) != 1:
                raise ValueError("paired schedule mismatch")
        release = {"all_training_completed": True, "completed_at": utc_now(), "endpoints": endpoints,
                   "protocol_sha256": file_hash(Path(fixture) / "protocol.json")}
        write_new(output / "heldout-release.json", release)
        evaldir = output / "evaluation"
        command = [sys.executable, str(SCRIPT), "--model-dir", str(Path(model_dir).resolve()), "--fixture", str(Path(fixture).resolve()),
                   "--output", str(evaldir), "--evaluate-release", str(output / "heldout-release.json")]
        run_child(command, evaldir, c["evaluation_timeout_seconds"], deadline, c)
        evaluation = read_small(evaldir / "evaluation.json")
        screens = directional_screens(workers, evaluation)
        stable = {"config": c, "train_sha256": manifest["train_sha256"], "holdout_sha256": manifest["holdout_sha256"],
                  "endpoints": [{k: e[k] for k in ("arm", "seed", "method", "checkpoint_sha256", "initial_parameter_sha256", "final_parameter_sha256")} for e in endpoints],
                  "evaluation": evaluation, "screens": screens}
        result = {"schema_version": 1, "completed": True, "scientific_screen_failure_is_completed_result": True,
                  "stable_results": stable, "stable_result_sha256": digest(stable), "workers": workers, "profiles": profiles,
                  "protocol_sha256": file_hash(Path(fixture) / "protocol.json"), "implementation_sha256": file_hash(Path(fixture) / "implementation.json"),
                  "total_wall_seconds": time.perf_counter() - start, "limitations": [
                  "One local run; three shared-corpus schedule scenarios are not independent statistical/performance replications.",
                  "Exact OS lifetime peak through training includes imports/load/setup; sampled lifetime RSS is a lower bound, not an isolated training peak.",
                  "Separate profile invocations have counter/timer overhead; callback times are not mean training cost and inventories are not OS peaks.",
                  "Atomic-step time control has declared [60,61]s window; every invalid/capped endpoint remains without retry or rescue.",
                  "Separate-book fixed-prefix fiction may have appeared in pretraining; no general quality, convergence, significance, GPU/AttnRes or causal moment inference.",
                  "Strict directional screens provide neither numerical equivalence nor a general practical-benefit claim; all prior negatives remain."]}
        result["observation_sha256"] = digest(result)
        if output_bytes(output) > c["max_output_bytes"]:
            raise RuntimeError("run output quota exceeded before final report")
        write_new(output / "report.json", result)
        return result
    except BaseException as error:
        write_new(output / "failure.json", {"completed": False, "at": utc_now(), "type": type(error).__name__, "error": str(error),
                  "no_retry": True, "wall_seconds": time.perf_counter() - start, "heldout_release_exists": (output / "heldout-release.json").exists()})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", choices=("token", "time", "profile"), help=argparse.SUPPRESS)
    parser.add_argument("--method", choices=METHODS, help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--evaluate-release", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        if args.evaluate_release is not None or args.method is None or args.seed is None:
            parser.error("worker needs method/seed and cannot evaluate")
        training_worker(args.model_dir, args.fixture, args.output, args.worker, args.method, args.seed)
    elif args.evaluate_release is not None:
        evaluation_worker(args.model_dir, args.fixture, args.output, args.evaluate_release)
    else:
        result = run_probe(args.model_dir, args.fixture, args.output)
        print(canonical({"report": str(args.output / "report.json"), "stable_result_sha256": result["stable_result_sha256"]}))


if __name__ == "__main__":
    main()
