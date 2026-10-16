"""Frozen short-history diagnostic; experimental and separate from SaveScope v0.1."""
from __future__ import annotations

import argparse
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
from experiments import activation_attention_gradient_probe as attention
from experiments import activation_state_update_probe as stateprobe
from experiments import adamw_state_reference as native
from experiments.activation_gradient_probe import parameter_comparison, tensor_hash
from experiments.activation_training_probe import (
    batch_schedule, canonical, digest, file_hash, load_data, parameter_hash, require_torch,
    verify_model_assets, write_json,
)
from experiments.activation_update_probe import (
    OPTIMIZER, GATE, _stable_gradient, update_fidelity_gate, update_metrics, aggregate_metrics,
)
from scripts.capture_real_activation import MODEL_ID, MODEL_REVISION, PINNED_ASSETS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
PROTOCOL_SHA256 = "612b12f3c013822ac0074b4920544ac5c2e3c0bbeef545bae7056ecbd5076fa4"
HISTORIES = ("dense", "model_except_norm_attention_saved_int8")
AUDIT_STEPS = (4, 8)
COUNT_KEYS = ("history_backwards", "probe_backwards", "native_history_steps", "native_clone_steps")


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def validate_blocks(data, previous):
    if not isinstance(data, dict) or set(data) != {"schema_version", "train", "audit"} or data["schema_version"] != 1:
        raise ValueError("unsupported history data schema")
    arrays, all_blocks = {}, []
    for split, count in (("train", 8), ("audit", 4)):
        blocks = data[split]
        if (not isinstance(blocks, list) or len(blocks) != count
                or any(not isinstance(row, list) or len(row) != 65 for row in blocks)
                or any(type(token) is not int or not 0 <= token < 50304 for row in blocks for token in row)):
            raise ValueError("history splits require eight train/four audit 65-token integer blocks")
        all_blocks.extend(map(tuple, blocks))
        arrays[split] = np.asarray(blocks, dtype=np.int64)
    old = {tuple(row) for split in ("train", "holdout") for row in previous[split]}
    if len(set(all_blocks)) != 12 or set(all_blocks) & old:
        raise ValueError("history blocks overlap each other or previous train/holdout")
    return arrays


def load_history_data(data_path, manifest_path):
    if any(Path(p).stat().st_size > 1024 * 1024 for p in (data_path, manifest_path)):
        raise ValueError("data/manifest exceeds 1 MiB bound")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1 or manifest.get("model_id") != MODEL_ID
            or manifest.get("model_revision") != MODEL_REVISION
            or manifest.get("data_sha256") != file_hash(data_path)
            or manifest.get("tokenizer_sha256") != PINNED_ASSETS["tokenizer.json"][1]
            or manifest.get("preparation_script_sha256") != file_hash(ROOT / "scripts/prepare_activation_history.py")):
        raise ValueError("history manifest/model/tokenizer/preparation/data pin mismatch")
    if set(manifest.get("sources", {})) != {"train", "audit"}:
        raise ValueError("history manifest source coverage mismatch")
    for split, count in (("train", 8), ("audit", 4)):
        source = manifest["sources"][split]
        if (source.get("file") != split + ".txt" or source.get("blocks") != count
                or source.get("tokens_per_block") != 65 or source.get("selected_tokens") != count * 65
                or type(source.get("source_tokens")) is not int or source["source_tokens"] < count * 65
                or source.get("license") != "MIT"
                or source.get("origin") != "original model-written synthetic prose; numerical diagnostic only"
                or file_hash(Path(manifest_path).parent / source["file"]) != source.get("sha256")):
            raise ValueError("history source manifest/hash mismatch")
    data = json.loads(Path(data_path).read_text(encoding="utf-8"))
    previous, _ = load_data(ROOT / "fixtures/activation-training/data.json", ROOT / "fixtures/activation-training/manifest.json")
    prior = json.loads((ROOT / "results/activation-training/report.json").read_text(encoding="utf-8"))
    if file_hash(ROOT / "fixtures/activation-training/data.json") != prior["stable_results"]["data_sha256"]:
        raise ValueError("previous block exclusion data changed")
    return validate_blocks(data, previous), manifest


def validate_protocol(path, data, manifest):
    if file_hash(path) != PROTOCOL_SHA256:
        raise ValueError("predeclared protocol bytes changed")
    protocol = json.loads(Path(path).read_text(encoding="utf-8"))
    config = protocol["config"]
    if (digest(config) != protocol["config_sha256"] or config["optimizer"] != OPTIMIZER
            or config["primary_gate"] != GATE or tuple(config["methods_in_order"]) != attention.METHODS
            or tuple(config["histories_in_order"]) != HISTORIES or tuple(config["audit_steps"]) != AUDIT_STEPS):
        raise ValueError("predeclared config mismatch")
    if file_hash(data) != protocol["data_sha256"] or file_hash(manifest) != protocol["manifest_sha256"]:
        raise ValueError("data/manifest pin mismatch")
    for name, expected in {**protocol["frozen_dependencies_sha256"], **protocol["prior_results_sha256"]}.items():
        if file_hash(ROOT / name) != expected:
            raise ValueError("frozen dependency or prior result changed: " + name)
    for seed in config["seeds"]:
        schedule = batch_schedule(8, 8, 2, seed)
        expected = protocol["schedules"][str(seed)]
        if schedule != expected["history_batches"] or digest(schedule) != expected["history_batches_sha256"]:
            raise ValueError("predeclared schedule mismatch")
    load_history_data(data, manifest)
    return protocol


def freeze_implementation(path, protocol_path, data, manifest):
    protocol = validate_protocol(protocol_path, data, manifest)
    if Path(path).exists():
        raise ValueError("implementation freeze already exists")
    record = {"schema_version": 1, "frozen_at": utcnow(), "protocol_sha256": file_hash(protocol_path),
        "new_source_files_sha256": {p: file_hash(ROOT / p) for p in protocol["new_source_paths"]},
        "frozen_dependencies_sha256": protocol["frozen_dependencies_sha256"],
        "note": "Implementation and engineering tests fixed before scientific model execution; not an external timestamp attestation."}
    if dt.datetime.fromisoformat(record["frozen_at"]) < dt.datetime.fromisoformat(protocol["predeclared_at"]):
        raise ValueError("protocol/freeze chronology mismatch")
    record["receipt_sha256"] = digest(record)
    write_json(path, record)
    return record


def validate_freeze(path, protocol, protocol_path, *, started_at=None):
    freeze = json.loads(Path(path).read_text(encoding="utf-8"))
    if (freeze["receipt_sha256"] != digest({k: v for k, v in freeze.items() if k != "receipt_sha256"})
            or freeze["protocol_sha256"] != file_hash(protocol_path)
            or freeze["frozen_dependencies_sha256"] != protocol["frozen_dependencies_sha256"]
            or freeze["new_source_files_sha256"] != {p: file_hash(ROOT / p) for p in protocol["new_source_paths"]}):
        raise ValueError("implementation freeze mismatch")
    predeclared, frozen = [dt.datetime.fromisoformat(t) for t in (protocol["predeclared_at"], freeze["frozen_at"])]
    if frozen < predeclared or (started_at is not None and dt.datetime.fromisoformat(started_at) < frozen):
        raise ValueError("protocol/freeze/execution chronology mismatch")
    return freeze


def buffer_hash(model):
    return digest({n: tensor_hash(value) for n, value in model.named_buffers()})


def assert_history_storage_disjoint(histories):
    seen = set()
    for history in HISTORIES:
        item = histories[history]
        tensors = [p for _, p in item["named"]] + [p.grad for _, p in item["named"] if p.grad is not None]
        tensors += [b for _, b in item["model"].named_buffers()]
        tensors += [v for state in item["optimizer"].state.values() for v in state.values() if hasattr(v, "untyped_storage")]
        pointers = {(str(t.device), t.untyped_storage().data_ptr()) for t in tensors if t.numel()}
        if pointers & seen:
            raise ValueError("independent histories share parameter/gradient/buffer/optimizer storage")
        seen.update(pointers)
    return True


def anchor_gate(records):
    if [r["method"] for r in records] != list(attention.METHODS):
        raise ValueError("all three audit policies in declared order required")
    return update_fidelity_gate(records)


def audit_anchor(model, named, optimizer, tokens, history, step, norms, attentions):
    torch = require_torch()
    state = native.state_hash(named, optimizer)
    buffers, rng = buffer_hash(model), torch.random.get_rng_state().clone()
    frozen = native.freeze_optimizer_state(named, optimizer)
    frozen_hash = native.frozen_state_hash(frozen)
    if any(row["step"] != step for row in frozen.values()):
        raise ValueError("audit anchor native optimizer counters differ from checkpoint")
    records, gradients = [], []
    references = updates = None
    try:
        for method in attention.METHODS:
            if native.state_hash(named, optimizer) != state or native.frozen_state_hash(frozen) != frozen_hash:
                raise ValueError("audit source state changed")
            gradient = attention.backward_once(model, tokens, method)
            stateprobe.validate_gradient(gradient, norms, attentions, method)
            if references is None:
                references = {n: p.grad.detach().clone() for n, p in named}
            gradient["parameter_gradient_comparison"] = parameter_comparison(model, references)
            if gradients and any(gradient[k] != gradients[0][k] for k in ("logits_sha256", "forward_loss")):
                raise ValueError("same-anchor compression altered forward loss/logits")
            gradients.append(gradient)
            record, retained = native.clone_step(named, frozen, updates)
            if updates is None:
                updates = retained
            if (record["initial_full_state_sha256"] != state or record["initial_state_sha256"] != frozen_hash
                    or any(t != step for t in record["input_steps"].values())
                    or any(t != step + 1 for t in record["optimizer_steps"].values())
                    or record["native_optimizer_steps"] != 1 or not record["sources_unchanged"]
                    or not record["clone_storages_disjoint"] or not record["numpy_all_parameter_and_moment_checks_passed"]):
                raise ValueError("audit clone anchor/counter/native control mismatch")
            if native.state_hash(named, optimizer) != state or native.frozen_state_hash(frozen) != frozen_hash:
                raise ValueError("audit clone modified original state")
            records.append({"method": method, **record})
        if buffer_hash(model) != buffers or not torch.equal(torch.random.get_rng_state(), rng):
            raise ValueError("audit changed registered buffers or RNG state")
    finally:
        model.zero_grad(set_to_none=True)
    if any(p.grad is not None for _, p in named):
        raise ValueError("audit gradients were not cleared")
    return {"history": history, "step": step, "batch_tokens_sha256": tensor_hash(tokens),
        "source_full_state_sha256": state, "frozen_optimizer_state_sha256": frozen_hash,
        "source_state_buffers_rng_unchanged": True, "audit_gradients_cleared": True,
        "gradients": gradients, "policies": records, "gate": anchor_gate(records)}


def history_step(model, named, optimizer, tokens, method, step, norms, attentions):
    before = native.state_hash(named, optimizer)
    try:
        gradient = attention.backward_once(model, tokens, method)
        stateprobe.validate_gradient(gradient, norms, attentions, method)
        inputs = native.capture_step_inputs(named, optimizer)
        if any(row["step"] != step - 1 for row in inputs.values()):
            raise ValueError("history input optimizer counter mismatch")
        optimizer.step()
        check = native.check_native_step(inputs, named, optimizer)
        if any(row["optimizer_step"] != step for row in check["per_parameter"]):
            raise ValueError("history output optimizer counter mismatch")
        delta_squared = math.fsum(float(np.square(p.detach().numpy().astype(np.float64)
            - inputs[name]["parameter"].numpy().astype(np.float64)).sum(dtype=np.float64)) for name, p in named)
    finally:
        model.zero_grad(set_to_none=True)
    return {"step": step, "method": method, "batch_tokens_sha256": tensor_hash(tokens),
        "state_sha256_before": before, "state_sha256_after": native.state_hash(named, optimizer),
        "actual_native_delta_l2": math.sqrt(delta_squared), "history_gradients_cleared": True,
        "gradient_diagnostic": gradient, "checker_receipts": check}


def _descriptive_metrics(reference, candidate):
    rows = [{"name": n, **update_metrics(reference[n].detach().numpy(), candidate[n].detach().numpy())}
            for n in reference]
    result = {"per_parameter": rows, "aggregate": aggregate_metrics(rows)}
    for metric in [*rows, result["aggregate"]]:
        if metric["reference_l2"] == 0:
            metric["relative_l2"] = None
            metric["relative_l2_undefined_reason"] = "zero dense reference norm"
        if metric["reference_l2"] == 0 or metric["candidate_l2"] == 0:
            metric["cosine_similarity"] = None
            metric["cosine_undefined_reason"] = "zero vector norm"
    return result


def trajectory_drift(dense_named, dense_states, treatment_named, treatment_states, initial, dense_path_length, step):
    dense, treatment = dict(dense_named), dict(treatment_named)
    if list(dense) != list(treatment) or set(initial) != set(dense) or set(dense_states) != set(dense) or set(treatment_states) != set(dense):
        raise ValueError("trajectory drift needs matching complete parameter/state names")
    if any(row["step"] != step for states in (dense_states, treatment_states) for row in states.values()):
        raise ValueError("paired trajectory counters differ from checkpoint")
    if not math.isfinite(dense_path_length) or dense_path_length < 0:
        raise ValueError("finite nonnegative actual dense path length required")
    parameters = _descriptive_metrics(dense, treatment)
    displacement = math.sqrt(math.fsum(float(np.square(dense[n].detach().numpy().astype(np.float64)
        - initial[n].detach().numpy().astype(np.float64)).sum(dtype=np.float64)) for n in dense))
    difference = parameters["aggregate"]["difference_l2"]
    normalizations = {}
    for label, denominator in (("dense_cumulative_displacement", displacement), ("dense_update_path_length", dense_path_length)):
        normalizations[label] = {"denominator_l2": denominator,
            "parameter_drift_ratio": difference / denominator if denominator else None,
            "undefined_reason": None if denominator else "zero " + label}
    return {"step": step, "descriptive_only": True, "parameter": parameters,
        "exp_avg": _descriptive_metrics({n: dense_states[n]["exp_avg"] for n in dense}, {n: treatment_states[n]["exp_avg"] for n in dense}),
        "exp_avg_sq": _descriptive_metrics({n: dense_states[n]["exp_avg_sq"] for n in dense}, {n: treatment_states[n]["exp_avg_sq"] for n in dense}),
        "normalizations": normalizations, "native_counters_equal_checkpoint": True,
        "interpretation": "Own-trajectory differences mix parameters, gradients, moments and history; no drift threshold or causal moment attribution."}


def _model_item(model, torch, cls):
    model.eval()
    named = list(model.named_parameters())
    for _, p in named:
        p.requires_grad_(True)
    norms = [n for n, m in model.named_modules() if isinstance(m, torch.nn.LayerNorm)]
    attentions = [n for n, m in model.named_modules() if isinstance(m, cls)]
    if (len(named) != 76 or sum(p.numel() for _, p in named) != 14067712 or len(norms) != 13 or len(attentions) != 6
            or model.config._attn_implementation != "eager" or any((isinstance(m, torch.nn.Dropout) and m.p != 0)
            or (isinstance(m, cls) and m.attention_dropout != 0) for m in model.modules())):
        raise ValueError("model/scope/dropout coverage mismatch")
    return {"model": model, "named": named, "optimizer": native.make_optimizer(named), "norms": norms,
            "attentions": attentions, "steps": [], "anchors": [], "path_length": 0.0}


def worker(model_dir, data, manifest, protocol_path, freeze_path, output, seed):
    started_at, started = utcnow(), time.perf_counter()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    timer = threading.Timer(900, attention._budget_exit)
    timer.daemon = True
    timer.start()
    try:
        protocol = validate_protocol(protocol_path, data, manifest)
        validate_freeze(freeze_path, protocol, protocol_path, started_at=started_at)
        config = protocol["config"]
        if seed not in config["seeds"]:
            raise ValueError("undeclared seed")
        arrays, _ = load_history_data(data, manifest)
        verify_model_assets(model_dir)
        torch = require_torch()
        from transformers import AutoModelForCausalLM
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.manual_seed(seed)
        cls = attention.attention_type()
        histories = {}
        for method in HISTORIES:
            model = AutoModelForCausalLM.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False,
                use_safetensors=True, dtype=torch.float32, attn_implementation="eager").to(device="cpu", dtype=torch.float32)
            histories[method] = _model_item(model, torch, cls)
        initial_hashes = {h: parameter_hash(v["model"]) for h, v in histories.items()}
        if len(set(initial_hashes.values())) != 1 or len({buffer_hash(v["model"]) for v in histories.values()}) != 1:
            raise ValueError("histories did not begin at identical pinned pretrained parameters/buffers")
        assert_history_storage_disjoint(histories)
        initial = {n: p.detach().clone() for n, p in histories["dense"]["named"]}
        schedule = batch_schedule(8, 8, 2, seed)
        drifts = []
        for step, selected in enumerate(schedule, 1):
            for method in HISTORIES:
                item = histories[method]
                tokens = torch.from_numpy(arrays["train"][selected])
                record = history_step(item["model"], item["named"], item["optimizer"], tokens,
                    method, step, item["norms"], item["attentions"])
                record["batch_indices"] = selected
                item["steps"].append(record)
                item["path_length"] += record["actual_native_delta_l2"]
                if step in AUDIT_STEPS:
                    indices = config["audit_batches"][str(step)]
                    audit = audit_anchor(item["model"], item["named"], item["optimizer"],
                        torch.from_numpy(arrays["audit"][indices]), method, step, item["norms"], item["attentions"])
                    audit["batch_indices"] = indices
                    item["anchors"].append(audit)
                assert_history_storage_disjoint(histories)
            if step in AUDIT_STEPS:
                d, t = [histories[h] for h in HISTORIES]
                drifts.append(trajectory_drift(d["named"], native.freeze_optimizer_state(d["named"], d["optimizer"]),
                    t["named"], native.freeze_optimizer_state(t["named"], t["optimizer"]), initial, d["path_length"], step))
        if any(parameter_hash(v["model"]) == initial_hashes[h] for h, v in histories.items()):
            raise ValueError("actual training history did not change pretrained parameters")
    finally:
        timer.cancel()
    elapsed = time.perf_counter() - started
    if elapsed > config["max_seconds_per_worker"]:
        raise ValueError("worker exceeded declared budget")
    result = {"seed": seed, "completed": True, "pid": os.getpid(), "started_at": started_at, "completed_at": utcnow(),
        "wall_seconds_descriptive_only": elapsed, "initial_parameter_sha256": initial_hashes["dense"],
        "schedule_sha256": digest(schedule), "histories_storage_disjoint": True,
        "histories": {h: {"steps": v["steps"], "anchors": v["anchors"], "actual_update_path_length": v["path_length"],
            "final_parameter_sha256": parameter_hash(v["model"]), "final_full_state_sha256": native.state_hash(v["named"], v["optimizer"])}
            for h, v in histories.items()}, "trajectory_drift": drifts,
        "counts": {"history_backwards": 16, "probe_backwards": 12, "native_history_steps": 16, "native_clone_steps": 12},
        "protocol_sha256": file_hash(protocol_path), "implementation_freeze_sha256": file_hash(freeze_path),
        "config_sha256": protocol["config_sha256"],
        "runtime": {"torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version(),
            "transformers": importlib.metadata.version("transformers"), "attention_class": attention.ATTENTION_CLASS_NAME,
            "attention_class_source_sha256": file_hash(sys.modules[cls.__module__].__file__), "system": platform.system(),
            "machine": platform.machine(), "threads": 1, "device": "cpu", "deterministic_algorithms": torch.are_deterministic_algorithms_enabled()}}
    write_json(output / "worker.json", result)
    return result


def summarize_workers(workers, protocol):
    config = protocol["config"]
    if [w["seed"] for w in workers] != config["seeds"] or any(not w["completed"] for w in workers):
        raise ValueError("all declared workers in seed order must complete")
    totals = {k: sum(w["counts"][k] for w in workers) for k in COUNT_KEYS}
    expected = {k: v for k, v in config["expected_counts"].items() if k != "workers"}
    if totals != expected or len(workers) != config["expected_counts"]["workers"]:
        raise ValueError("declared execution counts differ")
    if len({w["initial_parameter_sha256"] for w in workers}) != 1:
        raise ValueError("workers did not share pinned pretrained weights")
    gates = []
    for worker_record in workers:
        if not worker_record["histories_storage_disjoint"] or list(worker_record["histories"]) != list(HISTORIES):
            raise ValueError("both independent histories in declared order required")
        if [r["step"] for r in worker_record["trajectory_drift"]] != list(AUDIT_STEPS):
            raise ValueError("both descriptive paired checkpoints required")
        for history, item in worker_record["histories"].items():
            if [r["step"] for r in item["steps"]] != list(range(1, 9)) or [r["step"] for r in item["anchors"]] != list(AUDIT_STEPS):
                raise ValueError("complete actual history and both audit points required")
            for anchor in item["anchors"]:
                if (anchor["history"] != history or not anchor["source_state_buffers_rng_unchanged"]
                        or not anchor["audit_gradients_cleared"] or anchor["gate"] != anchor_gate(anchor["policies"])):
                    raise ValueError("audit anchor identity/control/gate mismatch")
                gates.append({"seed": worker_record["seed"], "history": history, "step": anchor["step"], **anchor["gate"]})
    if len(gates) != config["expected_anchors"]:
        raise ValueError("all twelve anchors required")
    return {"counts": {"workers": len(workers), **totals}, "anchor_gates": gates,
        "primary_gate_passed_all_anchors": all(g["passed"] for g in gates), "trajectory_drift_has_no_pass_threshold": True}


def stable_worker(worker_record):
    result = {k: v for k, v in worker_record.items() if k not in ("pid", "started_at", "completed_at", "wall_seconds_descriptive_only",
        "runtime", "parent_wall_seconds_descriptive_only", "worker_file_sha256")}
    result["histories"] = {}
    for history, item in worker_record["histories"].items():
        clean = {k: v for k, v in item.items() if k not in ("steps", "anchors")}
        clean["steps"] = [{**r, "gradient_diagnostic": _stable_gradient(r["gradient_diagnostic"])} for r in item["steps"]]
        clean["anchors"] = [{**a, "gradients": [_stable_gradient(g) for g in a["gradients"]]} for a in item["anchors"]]
        result["histories"][history] = clean
    return result


def run_probe(model_dir, data, manifest, protocol_path, freeze_path, output):
    protocol = validate_protocol(protocol_path, data, manifest)
    validate_freeze(freeze_path, protocol, protocol_path, started_at=utcnow())
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("fresh nonexistent output directory required; no scientific retry in place")
    (output / "workers").mkdir(parents=True)
    env = os.environ.copy()
    env.update({k: "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    workers = []
    for seed in protocol["config"]["seeds"]:
        directory = output / "workers" / f"seed-{seed}"
        command = [sys.executable, str(SCRIPT), "--seed", str(seed)]
        for name, value in (("model-dir", model_dir), ("data", data), ("manifest", manifest),
                ("protocol", protocol_path), ("freeze", freeze_path), ("output", directory)):
            command.extend(["--" + name, str(Path(value).resolve())])
        start = time.perf_counter()
        try:
            child = subprocess.run(command, env=env, capture_output=True, text=True,
                timeout=protocol["config"]["parent_worker_timeout_seconds"], check=False)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "stdout.txt").write_text(child.stdout, encoding="utf-8")
            (directory / "stderr.txt").write_text(child.stderr, encoding="utf-8")
            if child.returncode:
                raise RuntimeError(f"history worker {seed} failed exit={child.returncode}: {child.stderr[-2000:]}")
            record = json.loads((directory / "worker.json").read_text(encoding="utf-8"))
            record["parent_wall_seconds_descriptive_only"] = time.perf_counter() - start
            record["worker_file_sha256"] = file_hash(directory / "worker.json")
            workers.append(record)
        except Exception as error:
            directory.mkdir(parents=True, exist_ok=True)
            if isinstance(error, subprocess.TimeoutExpired):
                for name, content in (("stdout.txt", error.stdout), ("stderr.txt", error.stderr)):
                    if content is not None:
                        (directory / name).write_text(content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content, encoding="utf-8")
            write_json(output / "incomplete.json", {"completed": False, "seed": seed, "failed_at": utcnow(),
                "reason": str(error), "parent_wall_seconds": time.perf_counter() - start,
                "scientific_gate_outcome": None, "completed_workers": [w["seed"] for w in workers]})
            raise
    try:
        summary = summarize_workers(workers, protocol)
    except Exception as error:
        write_json(output / "incomplete.json", {"completed": False, "failed_at": utcnow(), "reason": str(error),
            "scientific_gate_outcome": None, "completed_workers": [w["seed"] for w in workers]})
        raise
    stable = {"protocol_sha256": file_hash(protocol_path), "config_sha256": protocol["config_sha256"],
        "implementation_freeze_sha256": file_hash(freeze_path), "data_sha256": file_hash(data),
        "manifest_sha256": file_hash(manifest), "workers": [stable_worker(w) for w in workers], **summary}
    report = {"schema_version": 1, "completed": True, "config": protocol["config"], "stable_results": stable,
        "stable_result_sha256": digest(stable), "worker_measurements": workers, "limitations": protocol["limitations"],
        "scientific_gate_failure_is_valid_completed_result": True,
        "receipt_limitation": "Hashes and sufficient statistics retained; raw theta/gradient/moment arrays not published for independent offline reference recomputation."}
    report["observation_sha256"] = digest(report)
    write_json(output / "report.json", report)
    lines = ["# Short training histories and common-anchor actual AdamW update fidelity", "",
        "Two independent eight-step histories per schedule; three clone policies at steps 4 and 8. All twelve anchors must pass the unchanged joint gate.", "",
        "| Seed | History | Step | Norm-only relL2 | Treatment relL2 | Treatment cosine | Error ratio | Joint gate |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for w in workers:
        for h, item in w["histories"].items():
            for a in item["anchors"]:
                b, t = [r["update_comparison"]["aggregate"] for r in a["policies"][1:]]
                fmt = lambda value: "undefined" if value is None else f"{value:.9g}"
                lines.append(f"| {w['seed']} | {h} | {a['step']} | {fmt(b['relative_l2'])} | {fmt(t['relative_l2'])} | {fmt(t['cosine_similarity'])} | {fmt(a['gate']['treatment_to_norm_only_relative_l2_ratio'])} | {a['gate']['passed']} |")
    lines += ["", f"Primary all-anchor gate: **{summary['primary_gate_passed_all_anchors']}**.", "",
        "48 actual history steps and 36 discarded clone steps use numerical theta/m/v/t controls on all 76 parameter tensors. Audit source states remain unchanged and probe gradients are cleared before history resumes.", "",
        "Trajectory drift is descriptive, without a pass threshold. It mixes parameter, gradient, moment and history effects. These short synthetic trajectories provide no convergence, quality, efficiency, GPU, practical compression benefit, AttnRes or private-roadmap evidence. SaveScope v0.1 remains fresh-state only.", "",
        f"Stable SHA256: `{report['stable_result_sha256']}`", f"Observation SHA256: `{report['observation_sha256']}`", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--data", type=Path, default=ROOT / "fixtures/activation-history/data.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "fixtures/activation-history/manifest.json")
    parser.add_argument("--protocol", type=Path, default=ROOT / "fixtures/activation-history/protocol.json")
    parser.add_argument("--freeze", type=Path, default=ROOT / "fixtures/activation-history/implementation.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--freeze-implementation", action="store_true")
    args = parser.parse_args(argv)
    if args.freeze_implementation:
        print(canonical(freeze_implementation(args.freeze, args.protocol, args.data, args.manifest)))
    elif args.model_dir is None or args.output is None:
        parser.error("--model-dir and --output required for model execution")
    elif args.seed is not None:
        worker(args.model_dir, args.data, args.manifest, args.protocol, args.freeze, args.output, args.seed)
    else:
        report = run_probe(args.model_dir, args.data, args.manifest, args.protocol, args.freeze, args.output)
        print(canonical({"report": str(args.output / "report.json"), "stable_result_sha256": report["stable_result_sha256"],
                         "primary_passed": report["stable_results"]["primary_gate_passed_all_anchors"]}))


if __name__ == "__main__":
    main()
