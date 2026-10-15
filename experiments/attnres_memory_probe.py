"""Synthetic CPU inference: fresh-process memory/time for residual-bank mixing.

Measures NumPy process working sets, not GPU memory, training or upstream AttnRes.
The parent prepares prepacked fixtures; each worker loads only its method's bank.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import tempfile
import time

import numpy as np

if __package__:
    from .attnres_budget_probe import depth_logits, error_metrics, full_mix, make_bank, make_query, quantize_vectors
else:
    from attnres_budget_probe import depth_logits, error_metrics, full_mix, make_bank, make_query, quantize_vectors


METHODS = ("dense_float32", "int8_full_dequantize", "int8_tiled")
RTOL, ATOL = 1e-4, 1e-5
SCRIPT = Path(__file__).resolve()
MAX_BANK_BYTES = 128 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            result.update(block)
    return result.hexdigest()


def array_hash(array):
    result = hashlib.sha256(canonical({"shape": list(array.shape), "dtype": str(array.dtype)}).encode())
    result.update(np.ascontiguousarray(array).tobytes())
    return result.hexdigest()


def int8_tiled_mix(packed, scales, query, tile_depth=16, temperature=1.0):
    """Two passes over prepacked int8 depth tiles, without a full float bank.

    The first pass finds each token's maximum logit. The second accumulates the
    same softmax numerator/denominator in float64, returning float32 output.
    RMSNorm/logit/dequantization arithmetic reuses our float32 budget diagnostic.
    Products and logits must remain representable in float32; finite inputs alone
    do not guarantee that range. Generated fixtures satisfy it; workers reject
    any nonfinite final output.
    """
    if (packed.ndim != 3 or packed.dtype != np.int8 or min(packed.shape) < 1
            or scales.shape != packed.shape[:2] + (1,) or scales.dtype != np.float32
            or query.shape != packed.shape[1:] or query.dtype != np.float32):
        raise ValueError("expected int8 [depth,token,feature], float32 scales [depth,token,1] and query [token,feature]")
    if not isinstance(tile_depth, int) or isinstance(tile_depth, bool) or tile_depth < 1:
        raise ValueError("tile_depth must be a positive integer")
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("temperature must be finite and positive")
    if not np.all(np.isfinite(scales)) or np.any(scales <= 0) or not np.all(np.isfinite(query)):
        raise ValueError("scales must be finite positive and query must be finite")
    depth, tokens, dim = packed.shape
    maxima = np.full(tokens, -np.inf, dtype=np.float32)
    for start in range(0, depth, tile_depth):
        tile = packed[start:start + tile_depth].astype(np.float32) * scales[start:start + tile_depth]
        logits = depth_logits(tile, query, temperature)
        np.maximum(maxima, logits.max(axis=0), out=maxima)
        del tile, logits
    numerator = np.zeros((tokens, dim), dtype=np.float64)
    denominator = np.zeros(tokens, dtype=np.float64)
    for start in range(0, depth, tile_depth):
        tile = packed[start:start + tile_depth].astype(np.float32) * scales[start:start + tile_depth]
        logits = depth_logits(tile, query, temperature)
        weights = np.exp(logits - maxima[None, :])
        numerator += np.einsum("dt,dtf->tf", weights, tile, dtype=np.float64)
        denominator += weights.sum(axis=0, dtype=np.float64)
        del tile, logits, weights
    return (numerator / denominator[:, None]).astype(np.float32)


def process_memory():
    """OS process high-water peak and current resident bytes, never array sums."""
    system = platform.system()
    if system == "Windows":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"peak_bytes": int(counters.PeakWorkingSetSize), "resident_bytes": int(counters.WorkingSetSize),
                "backend": "GetProcessMemoryInfo PeakWorkingSetSize/WorkingSetSize", "native_peak_units": "bytes"}
    if system in ("Linux", "Darwin"):
        import resource
        multiplier = 1 if system == "Darwin" else 1024
        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * multiplier
        if system == "Linux":
            try:
                # VmHWM belongs to the current exec's memory map. ru_maxrss can
                # retain a larger pre-exec high-water from a forked parent.
                status = {}
                for line in Path("/proc/self/status").read_text().splitlines():
                    fields = line.split()
                    if fields and fields[0] in ("VmHWM:", "VmRSS:"):
                        if len(fields) != 3 or fields[2] != "kB":
                            raise ValueError("unexpected procfs resident-memory units")
                        status[fields[0]] = int(fields[1]) * 1024
                return {"peak_bytes": status["VmHWM:"], "resident_bytes": status["VmRSS:"],
                        "backend": "/proc/self/status VmHWM/VmRSS", "native_peak_units": "KiB (converted to bytes)",
                        "resource_ru_maxrss_bytes_diagnostic": peak}
            except (OSError, ValueError, KeyError, IndexError):
                pass
        return {"peak_bytes": peak, "resident_bytes": None,
                "backend": "resource.getrusage(RUSAGE_SELF).ru_maxrss" + (" fallback; may include inherited pre-exec high-water" if system == "Linux" else ""),
                "native_peak_units": "bytes" if system == "Darwin" else "KiB (converted to bytes)"}
    raise RuntimeError("Memory measurement supports Windows, Linux and Darwin only")


def platform_record():
    return {"system": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "python": platform.python_version(), "numpy": np.__version__, "byteorder": sys.byteorder}


def prepare_fixture(directory, depth, tokens, dim, seed):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    bank = make_bank(depth, tokens, dim, seed, "random")
    query = np.array(make_query(bank, seed, "fixed_random"), dtype=np.float32, copy=True)
    generation_seconds = time.perf_counter() - started
    started = time.perf_counter()
    packed, scales = quantize_vectors(bank)
    quantization_seconds = time.perf_counter() - started
    started = time.perf_counter()
    arrays = {"bank": bank, "query": query, "packed": packed, "scales": scales}
    files = {}
    for name, array in arrays.items():
        path = directory / (name + ".npy")
        np.save(path, array, allow_pickle=False)
        files[name] = {"filename": path.name, "sha256": file_hash(path), "array_nbytes": array.nbytes,
                       "shape": list(array.shape), "dtype": str(array.dtype)}
    write_seconds = time.perf_counter() - started
    started = time.perf_counter()
    dense_reference = full_mix(bank, query)
    quantized_reference = full_mix(packed.astype(np.float32) * scales, query)
    reference_seconds = time.perf_counter() - started
    specification = {"depth": depth, "tokens": tokens, "dim": dim, "seed": seed,
                     "distribution": "random", "query": "fixed_random_shared_not_learned", "files": files,
                     "reference_dense_array_sha256": array_hash(dense_reference),
                     "reference_quantized_array_sha256": array_hash(quantized_reference)}
    (directory / "fixture.json").write_text(json.dumps(specification, indent=2) + "\n", encoding="utf-8")
    costs = {"generation_wall_seconds": generation_seconds, "quantization_wall_seconds": quantization_seconds,
             "fixture_write_and_hash_wall_seconds": write_seconds, "parent_reference_wall_seconds": reference_seconds}
    return specification, costs, dense_reference, quantized_reference


def worker(method, fixture_dir, output_path, result_path, tile_depth):
    if method not in METHODS:
        raise ValueError("unknown method")
    started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    baseline = process_memory()  # NumPy and this module have already been imported.
    started = time.perf_counter()
    fixture_dir = Path(fixture_dir)
    fixture = json.loads((fixture_dir / "fixture.json").read_text(encoding="utf-8"))
    names = ("query", "bank") if method == "dense_float32" else ("query", "packed", "scales")
    arrays = {}
    for name in names:
        path = fixture_dir / fixture["files"][name]["filename"]
        if file_hash(path) != fixture["files"][name]["sha256"]:
            raise ValueError("fixture file hash mismatch: " + name)
        arrays[name] = np.load(path, allow_pickle=False)  # No mmap; owned NumPy input buffers.
    load_seconds = time.perf_counter() - started
    loaded = process_memory()
    started = time.perf_counter()
    if method == "dense_float32":
        output = full_mix(arrays["bank"], arrays["query"])
    elif method == "int8_full_dequantize":
        dequantized = arrays["packed"].astype(np.float32) * arrays["scales"]
        output = full_mix(dequantized, arrays["query"])
    else:
        output = int8_tiled_mix(arrays["packed"], arrays["scales"], arrays["query"], tile_depth)
    operator_seconds = time.perf_counter() - started
    operator_end = process_memory()
    if not np.all(np.isfinite(output)):
        raise ValueError("non-finite operator output")
    started = time.perf_counter()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(output_path, output, allow_pickle=False)
    output_file_hash = file_hash(output_path)
    output_array_hash = array_hash(output)
    persist_seconds = time.perf_counter() - started
    final = process_memory()
    result = {"method": method, "pid": os.getpid(), "platform": platform_record(), "loaded_arrays": list(names),
              "started_utc": started_utc, "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "loaded_input_array_bytes": sum(a.nbytes for a in arrays.values()),
              "load_and_input_hash_wall_seconds": load_seconds, "operator_wall_seconds": operator_seconds,
              "output_persist_and_hash_wall_seconds": persist_seconds,
              "memory": {"post_import_before_input": baseline, "after_input_load": loaded,
                         "after_operator": operator_end, "after_output_persist": final},
              "process_peak_bytes": final["peak_bytes"], "resident_after_operator_bytes": operator_end["resident_bytes"],
              "high_water_increment_from_post_import_bytes": max(0, final["peak_bytes"] - baseline["peak_bytes"]),
              "high_water_increment_from_post_load_bytes": max(0, final["peak_bytes"] - loaded["peak_bytes"]),
              "output_file_sha256": output_file_hash, "output_array_sha256": output_array_hash}
    Path(result_path).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    return result


def validate_config(depths, tokens, dim, seeds, repeats, tile_depth):
    values = list(depths) + [tokens, dim, repeats, tile_depth]
    if not depths or any(type(v) is not int or v < 1 for v in values):
        raise ValueError("depths, tokens, dim, repeats and tile_depth must be positive integers")
    if not seeds or any(type(v) is not int or v < 0 for v in seeds):
        raise ValueError("provide nonnegative integer seeds")
    if len(set(depths)) != len(depths) or len(set(seeds)) != len(seeds):
        raise ValueError("duplicate depths or seeds are not supported")
    if repeats > 3:
        raise ValueError("repeats is bounded to 1..3 fresh processes per method/case")
    if max(depths) * tokens * dim * 4 > MAX_BANK_BYTES:
        raise ValueError("dense bank exceeds the conservative 128 MiB per-case limit")
    if len(depths) * len(seeds) * repeats * len(METHODS) > 180:
        raise ValueError("configuration exceeds 180 worker processes")


def run_probe(depths=(128, 256), tokens=256, dim=256, seeds=(7,), repeats=3, tile_depth=16,
              output_dir=Path("results/attnres-memory")):
    depths, seeds = list(depths), list(seeds)
    validate_config(depths, tokens, dim, seeds, repeats, tile_depth)
    started_utc = dt.datetime.now(dt.timezone.utc).isoformat()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config = {"depths": depths, "tokens": tokens, "dim": dim, "seeds": seeds, "repeats": repeats,
              "tile_depth": tile_depth, "methods": list(METHODS), "temperature": 1.0,
              "worker_order_seed": 1729, "worker_timeout_seconds": 60, "rtol": RTOL, "atol": ATOL,
              "threads": {name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")}}
    sources = {SCRIPT.name: file_hash(SCRIPT), "attnres_budget_probe.py": file_hash(SCRIPT.with_name("attnres_budget_probe.py"))}
    measurements, preparation, fixtures, numerical = [], [], [], []
    with tempfile.TemporaryDirectory(prefix="attnres-memory-fixtures-") as temporary:
        for depth in depths:
            for seed in seeds:
                case_id = f"d{depth}-t{tokens}-f{dim}-s{seed}"
                fixture_dir = Path(temporary) / case_id
                specification, costs, dense_ref, quant_ref = prepare_fixture(fixture_dir, depth, tokens, dim, seed)
                fixtures.append(dict(case_id=case_id, **specification))
                preparation.append(dict(case_id=case_id, **costs))
                gc.collect()  # Preparation arrays belong to the parent, never to a worker.
                jobs = [(repeat, method) for repeat in range(repeats) for method in METHODS]
                random.Random(config["worker_order_seed"] + depth + seed).shuffle(jobs)
                for order, (repeat, method) in enumerate(jobs):
                    stem = f"{case_id}--{method}--r{repeat}"
                    output = output_dir / "outputs" / (stem + ".npy")
                    raw_record = output_dir / "workers" / (stem + ".json")
                    raw_record.parent.mkdir(exist_ok=True)
                    command = [sys.executable, str(SCRIPT), "--worker", "--method", method, "--fixture-dir", str(fixture_dir),
                               "--worker-output", str(output.resolve()), "--worker-result", str(raw_record.resolve()),
                               "--tile-depth", str(tile_depth)]
                    environment = dict(os.environ, **config["threads"])
                    started = time.perf_counter()
                    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=60, env=environment)
                    subprocess_seconds = time.perf_counter() - started
                    if completed.returncode:
                        raise RuntimeError(f"worker {method} failed ({completed.returncode}): {completed.stderr[:800]}")
                    measured = json.loads(raw_record.read_text(encoding="utf-8"))
                    actual = np.load(output, allow_pickle=False)
                    if file_hash(output) != measured["output_file_sha256"] or array_hash(actual) != measured["output_array_sha256"]:
                        raise ValueError("worker output hash mismatch")
                    measured.update(case_id=case_id, depth=depth, seed=seed, repeat=repeat, case_job_order=order,
                                    subprocess_wall_seconds=subprocess_seconds, output_file=str(output.relative_to(output_dir)),
                                    worker_record_file=str(raw_record.relative_to(output_dir)))
                    measurements.append(measured)
                    numerical.append({"case_id": case_id, "method": method, "repeat": repeat,
                                      "output_array_sha256": measured["output_array_sha256"],
                                      "output_file_sha256": measured["output_file_sha256"],
                                      "versus_dense": error_metrics(dense_ref, actual),
                                      "versus_quantized_full": error_metrics(quant_ref, actual),
                                      "quantized_full_equivalent": bool(np.allclose(actual, quant_ref, rtol=RTOL, atol=ATOL)) if method != "dense_float32" else None,
                                      "dense_reference_equivalent": bool(np.allclose(actual, dense_ref, rtol=RTOL, atol=ATOL)) if method == "dense_float32" else None})
    stable = {"config_sha256": digest(config), "code_sha256": sources, "fixtures": fixtures, "numerical_results": numerical}
    result = {"schema_version": 1, "experiment": "synthetic prepacked residual-bank CPU inference memory and wall time",
              "started_utc": started_utc, "completed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "config": config, "platform": platform_record(), "stable_results": stable,
              "stable_result_sha256": digest(stable), "parent_preparation_measurements": preparation,
              "worker_measurements": measurements,
              "all_numerical_checks_passed": all(n["quantized_full_equivalent"] if n["method"] != "dense_float32" else n["dense_reference_equivalent"] for n in numerical),
              "limitations": [
                  "Synthetic random inference-only banks and one seeded shared query. No real activations, learned pseudo-query, training/backward, model quality, GPU or upstream AttnRes implementation is measured.",
                  "Inputs are prepacked once in the parent. Worker timing excludes fixture generation, quantization, input loading and output persistence; these costs are recorded separately. This is not per-step quantization or a deployable activation/retention system.",
                  "Every method/case/repeat uses a fresh Python process. Int8 workers load only packed values, scales and query, never the dense float bank. No memory mapping is used.",
                  "Process peak is an OS lifetime high-water resident/working-set measurement sampled after output persistence, before final metadata serialization/exit. It includes Python/NumPy imports, input buffers, allocator behavior, temporaries and output storage; it is not precise operator-only allocation or GPU peak memory.",
                  "Post-import and post-load high-water increments are differences between lifetime maxima, not isolated operator peaks. Freed or cached allocations, page residency, OS scheduling and system load affect observations.",
                  "Linux uses procfs VmHWM/VmRSS in KiB converted to bytes; ru_maxrss is retained only as a diagnostic. If procfs is unavailable, the fallback ru_maxrss can contain an inherited pre-exec high-water and current RSS is unavailable. Darwin ru_maxrss uses bytes. Windows uses GetProcessMemoryInfo PeakWorkingSetSize and WorkingSetSize in bytes.",
                  "The full-int8 path retains packed inputs and creates a complete float32 dequantized bank before the existing full_mix; construction/quantization was excluded. The tiled path makes two passes, recomputes RMSNorm/logits, and accumulates weighted sums in float64. No latency or memory improvement threshold is assumed.",
                  "Worker order is deterministically shuffled within each shape/seed to interleave methods and repeats. This reduces simple fixed-order bias but does not control temperature, background work or OS allocator differences. At most three repeats are descriptive, not statistical performance guarantees.",
                  "Fixture/output and code/config hashes identify numerical evidence. The stable result hash excludes timing, memory, process IDs and platform scheduling; the full observation hash includes variable measurements. Exact numerical hashes can differ across NumPy/platform versions even when tolerance checks pass.",
              ]}
    result["observation_sha256"] = digest(result)
    return result


def render_markdown(result):
    lines = ["# Synthetic residual-bank CPU memory probe", "", "Fresh processes execute our NumPy inference diagnostic over prepacked synthetic banks. These are observed CPU process peaks and wall times.", "", f"Observed UTC: {result['started_utc']} to {result['completed_utc']}.", "", "| Dense bank | Method | Repeats | Median operator ms | Median process peak MiB | Median post-import peak MiB | Median post-load peak MiB | Median post-load RSS MiB |", "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for fixture in result["stable_results"]["fixtures"]:
        for method in METHODS:
            rows = [r for r in result["worker_measurements"] if r["case_id"] == fixture["case_id"] and r["method"] == method]
            median = lambda fn: float(np.median([fn(r) for r in rows]))
            rss = [r["memory"]["after_input_load"]["resident_bytes"] for r in rows]
            rss_text = "unavailable" if any(v is None for v in rss) else f"{np.median(rss) / 2**20:.2f}"
            lines.append(f"| {fixture['files']['bank']['array_nbytes'] / 2**20:.0f} MiB | {method} | {len(rows)} | {median(lambda r: r['operator_wall_seconds']) * 1000:.2f} | {median(lambda r: r['process_peak_bytes']) / 2**20:.2f} | {median(lambda r: r['memory']['post_import_before_input']['peak_bytes']) / 2**20:.2f} | {median(lambda r: r['memory']['after_input_load']['peak_bytes']) / 2**20:.2f} | {rss_text} |")
    lines += ["", f"Numerical checks: **{result['all_numerical_checks_passed']}**; int8 tiled/full tolerance rtol={RTOL}, atol={ATOL}. Quantization error against dense mixing is recorded separately; this does not measure model quality.", "", "Raw per-process phase peaks/RSS, load/persist/subprocess time, parent preparation/quantization cost, numerical errors and hashes are in probe.json and workers/. Outputs are retained in outputs/; temporary input fixtures can be regenerated from the recorded configuration and hashes.", "", f"Stable numerical/config/code SHA256: `{result['stable_result_sha256']}`", f"Full variable observation SHA256: `{result['observation_sha256']}`", "", "## Limits", ""]
    lines.extend("- " + item for item in result["limitations"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depths", nargs="+", type=int, default=[128, 256])
    parser.add_argument("--tokens", type=int, default=256)
    parser.add_argument("--dim", type=int, default=256)
    parser.add_argument("--seeds", nargs="+", type=int, default=[7])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--tile-depth", type=int, default=16)
    parser.add_argument("--output", type=Path, default=Path("results/attnres-memory"))
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--method", choices=METHODS, help=argparse.SUPPRESS)
    parser.add_argument("--fixture-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-result", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.worker:
            if not all((args.method, args.fixture_dir, args.worker_output, args.worker_result)):
                parser.error("worker requires method, fixture-dir, worker-output and worker-result")
            worker(args.method, args.fixture_dir, args.worker_output, args.worker_result, args.tile_depth)
            return 0
        result = run_probe(args.depths, args.tokens, args.dim, args.seeds, args.repeats, args.tile_depth, args.output)
        (args.output / "probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        (args.output / "report.md").write_text(render_markdown(result), encoding="utf-8", newline="\n")
        print(json.dumps({"worker_processes": len(result["worker_measurements"]), "all_numerical_checks_passed": result["all_numerical_checks_passed"], "stable_result_sha256": result["stable_result_sha256"]}))
        return 0 if result["all_numerical_checks_passed"] else 1
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
