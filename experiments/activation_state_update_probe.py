"""One frozen accumulated-state AdamW diagnostic, separate from SaveScope v0.1."""
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
from experiments import adamw_state_reference as native
from experiments.activation_gradient_probe import parameter_comparison, tensor_hash
from experiments.activation_norm_gradient_probe import validate_norm_coverage
from experiments.activation_training_probe import (
    batch_schedule, canonical, digest, file_hash, load_data, parameter_hash,
    require_torch, verify_model_assets, write_json,
)
from experiments.activation_update_probe import OPTIMIZER, GATE, _stable_gradient, update_fidelity_gate

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
PROTOCOL_SHA256 = "9b3a45c205defd8d1211c3f2ad2c60a447e057438a219e4f38e2cc1371706cca"
CONTEXTS = ("matched_step4", "fresh_step0")


def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def validate_protocol(path, data, manifest):
    if file_hash(path) != PROTOCOL_SHA256:
        raise ValueError("predeclared protocol bytes changed")
    protocol = json.loads(Path(path).read_text(encoding="utf-8"))
    config = protocol["config"]
    if (digest(config) != protocol["config_sha256"] or config["optimizer"] != OPTIMIZER
            or config["primary_gate"] != GATE or tuple(config["methods_in_order"]) != attention.METHODS
            or tuple(config["optimizer_contexts_in_order"]) != CONTEXTS):
        raise ValueError("predeclared config mismatch")
    if file_hash(data) != protocol["data_sha256"] or file_hash(manifest) != protocol["training_manifest_sha256"]:
        raise ValueError("data/manifest pin mismatch")
    if file_hash(ROOT / "results/activation-update/report.json") != protocol["prior_first_step_report_sha256"]:
        raise ValueError("prior negative first-step result changed")
    for name, expected in protocol["frozen_dependencies_sha256"].items():
        if file_hash(ROOT / name) != expected:
            raise ValueError("frozen dependency changed: " + name)
    for seed in config["seeds"]:
        schedule = batch_schedule(8, 24, 2, seed)
        expected = protocol["schedules"][str(seed)]
        if digest(schedule) != expected["all_steps_sha256"] or schedule[:4] != expected["warmup"] or schedule[4] != expected["probe"]:
            raise ValueError("predeclared schedule mismatch")
    return protocol


def freeze_implementation(path, protocol_path, data, manifest):
    protocol = validate_protocol(protocol_path, data, manifest)
    if Path(path).exists():
        raise ValueError("implementation freeze already exists")
    record = {"schema_version": 1, "frozen_at": utcnow(), "protocol_sha256": file_hash(protocol_path),
              "new_source_files_sha256": {p: file_hash(ROOT / p) for p in protocol["new_source_paths"]},
              "frozen_dependencies_sha256": protocol["frozen_dependencies_sha256"],
              "note": "Implementation and engineering tests fixed before scientific model execution; not an external timestamp attestation."}
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


def context_gates(context_records):
    if list(context_records) != list(CONTEXTS):
        raise ValueError("both optimizer contexts in declared order required")
    for context in CONTEXTS:
        if [r["method"] for r in context_records[context]] != list(attention.METHODS):
            raise ValueError("all policies in declared order required")
    gates = {context: update_fidelity_gate(context_records[context]) for context in CONTEXTS}
    return {"contexts": gates, "primary_context": CONTEXTS[0],
            "primary_passed": gates[CONTEXTS[0]]["passed"],
            "secondary_cannot_rescue_primary": True}


def validate_gradient(record, norms, attentions, method):
    validate_norm_coverage(record, norms, method)
    attention.validate_attention_coverage(record, attentions, method)
    relative = record["observed_vs_analytic_logits_gradient"]["relative_l2"]
    if (relative is None or not math.isfinite(relative) or relative > 1e-5
            or record["parameter_tensors_with_finite_gradients"] != 76
            or record["parameter_elements_with_finite_gradients"] != 14067712):
        raise ValueError("gradient/analytic CE control failed")


def worker(model_dir, data, manifest, protocol_path, freeze_path, output, seed):
    started_at, started = utcnow(), time.perf_counter()
    protocol = validate_protocol(protocol_path, data, manifest)
    validate_freeze(freeze_path, protocol, protocol_path, started_at=started_at)
    config = protocol["config"]
    if seed not in config["seeds"]:
        raise ValueError("undeclared seed")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    timer = threading.Timer(config["max_seconds_per_worker"], attention._budget_exit)
    timer.daemon = True
    timer.start()
    try:
        arrays, _ = load_data(data, manifest)
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
        cls = attention.attention_type()
        norms = [n for n, m in model.named_modules() if isinstance(m, torch.nn.LayerNorm)]
        attentions = [n for n, m in model.named_modules() if isinstance(m, cls)]
        if (len(named) != 76 or sum(p.numel() for _, p in named) != 14067712
                or len(norms) != 13 or len(attentions) != 6 or model.config._attn_implementation != "eager"
                or any((isinstance(m, torch.nn.Dropout) and m.p != 0)
                    or (isinstance(m, cls) and m.attention_dropout != 0) for m in model.modules())):
            raise ValueError("model/scope/dropout coverage mismatch")
        schedule = batch_schedule(8, 24, 2, seed)
        initial = parameter_hash(model)
        optimizer = native.make_optimizer(named)
        warmup = []
        for step, selected in enumerate(schedule[:4], 1):
            tokens = torch.from_numpy(arrays["train"][selected])
            before = native.state_hash(named, optimizer)
            gradient = attention.backward_once(model, tokens, "dense")
            validate_gradient(gradient, norms, attentions, "dense")
            inputs = native.capture_step_inputs(named, optimizer)
            optimizer.step()
            check = native.check_native_step(inputs, named, optimizer)
            del inputs
            if any(r["optimizer_step"] != step for r in check["per_parameter"]):
                raise ValueError("unexpected warmup optimizer counter")
            warmup.append({"step": step, "batch_indices": selected, "batch_tokens_sha256": tensor_hash(tokens),
                "state_sha256_before": before, "state_sha256_after": native.state_hash(named, optimizer),
                "gradient_diagnostic": gradient, "checker_receipts": check})
        warmed = parameter_hash(model)
        frozen = native.freeze_optimizer_state(named, optimizer)
        state = native.state_hash(named, optimizer)
        frozen_hash = native.frozen_state_hash(frozen)
        if initial == warmed or any(row["step"] != 4 for row in frozen.values()):
            raise ValueError("actual dense warmup did not establish step4 state")
        if not any(bool(row["exp_avg"].any()) and bool(row["exp_avg_sq"].any()) for row in frozen.values()):
            raise ValueError("matched context needs nonzero real accumulated moments")
        tokens = torch.from_numpy(arrays["train"][schedule[4]])
        references = None
        updates = {context: None for context in CONTEXTS}
        records = {context: [] for context in CONTEXTS}
        gradients = []
        for method in attention.METHODS:
            if native.state_hash(named, optimizer) != state or native.frozen_state_hash(frozen) != frozen_hash:
                raise ValueError("audit-point state changed")
            gradient = attention.backward_once(model, tokens, method)
            validate_gradient(gradient, norms, attentions, method)
            if references is None:
                references = {n: p.grad.detach().clone() for n, p in named}
            gradient["parameter_gradient_comparison"] = parameter_comparison(model, references)
            if gradients and any(gradient[k] != gradients[0][k] for k in ("logits_sha256", "forward_loss")):
                raise ValueError("compression altered forward loss/logits")
            gradients.append(gradient)
            for context in CONTEXTS:
                record, retained = native.clone_step(named, frozen if context == "matched_step4" else None, updates[context])
                if context == "matched_step4" and (record["initial_full_state_sha256"] != state
                        or record["initial_state_sha256"] != frozen_hash):
                    raise ValueError("matched clone did not start at the actual warmed optimizer state")
                if updates[context] is None:
                    updates[context] = retained
                expected = config["native_expected_steps"][context]
                if (any(t != expected for t in record["optimizer_steps"].values())
                        or any(t != expected - 1 for t in record["input_steps"].values())):
                    raise ValueError("clone optimizer context step mismatch")
                if native.state_hash(named, optimizer) != state or native.frozen_state_hash(frozen) != frozen_hash:
                    raise ValueError("clone modified original warm optimizer state")
                records[context].append({"method": method, **record})
        for context in CONTEXTS:
            if len({r["initial_full_state_sha256"] for r in records[context]}) != 1:
                raise ValueError("policies did not share identical optimizer starting state")
        if parameter_hash(model) != warmed:
            raise ValueError("probes modified fixed audit-point weights")
    finally:
        timer.cancel()
    elapsed = time.perf_counter() - started
    if elapsed > config["max_seconds_per_worker"]:
        raise ValueError("worker exceeded declared budget")
    result = {"seed": seed, "completed": True, "pid": os.getpid(), "started_at": started_at,
        "completed_at": utcnow(), "wall_seconds_descriptive_only": elapsed,
        "initial_parameter_sha256": initial, "warmed_parameter_sha256": warmed,
        "warmed_full_state_sha256": state, "frozen_optimizer_state_sha256": frozen_hash,
        "probe_parameters_and_warm_optimizer_unchanged": True, "schedule_sha256": digest(schedule),
        "batch_indices": schedule[4], "batch_tokens_sha256": tensor_hash(tokens),
        "warmup": warmup, "gradients": gradients, "contexts": records, "gates": context_gates(records),
        "counts": {"dense_warmup_backwards": 4, "probe_backwards": 3, "native_warmup_steps": 4, "native_clone_steps": 6},
        "protocol_sha256": file_hash(protocol_path), "implementation_freeze_sha256": file_hash(freeze_path),
        "config_sha256": protocol["config_sha256"],
        "runtime": {"torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version(),
            "transformers": importlib.metadata.version("transformers"), "attention_class": attention.ATTENTION_CLASS_NAME,
            "attention_class_source_sha256": file_hash(sys.modules[cls.__module__].__file__),
            "system": platform.system(), "machine": platform.machine(), "threads": 1, "device": "cpu",
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled()}}
    write_json(output / "worker.json", result)
    return result


def summarize_workers(workers, protocol):
    if [w["seed"] for w in workers] != protocol["config"]["seeds"] or any(not w["completed"] for w in workers):
        raise ValueError("all declared workers must complete")
    totals = {key: sum(w["counts"][key] for w in workers) for key in workers[0]["counts"]}
    expected = {k: v for k, v in protocol["config"]["expected_counts"].items() if k != "workers"}
    if totals != expected or len(workers) != protocol["config"]["expected_counts"]["workers"]:
        raise ValueError("declared execution counts differ")
    if len({w["initial_parameter_sha256"] for w in workers}) != 1:
        raise ValueError("workers did not share pinned pretrained weights")
    return {"counts": {"workers": len(workers), **totals},
            "primary_gate_passed_all_seeds": all(context_gates(w["contexts"])["primary_passed"] for w in workers),
            "secondary_gate_passed_all_seeds": all(context_gates(w["contexts"])["contexts"]["fresh_step0"]["passed"] for w in workers)}


def run_probe(model_dir, data, manifest, protocol_path, freeze_path, output):
    protocol = validate_protocol(protocol_path, data, manifest)
    validate_freeze(freeze_path, protocol, protocol_path, started_at=utcnow())
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("fresh nonexistent output directory required; no scientific retry in place")
    output.mkdir(parents=True)
    env = os.environ.copy()
    env.update({k: "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    workers = []
    for seed in protocol["config"]["seeds"]:
        directory = output / "workers" / f"seed-{seed}"
        directory.mkdir(parents=True)
        command = [sys.executable, str(SCRIPT), "--seed", str(seed)]
        for name, value in (("model-dir", model_dir), ("data", data), ("manifest", manifest),
                            ("protocol", protocol_path), ("freeze", freeze_path), ("output", directory)):
            command.extend(["--" + name, str(Path(value).resolve())])
        start = time.perf_counter()
        try:
            child = subprocess.run(command, env=env, capture_output=True, text=True,
                timeout=protocol["config"]["parent_worker_timeout_seconds"], check=False)
            (directory / "stdout.txt").write_text(child.stdout, encoding="utf-8")
            (directory / "stderr.txt").write_text(child.stderr, encoding="utf-8")
            if child.returncode:
                raise RuntimeError(f"state update worker {seed} failed exit={child.returncode}: {child.stderr[-2000:]}")
            w = json.loads((directory / "worker.json").read_text(encoding="utf-8"))
            w["parent_wall_seconds_descriptive_only"] = time.perf_counter() - start
            w["worker_file_sha256"] = file_hash(directory / "worker.json")
            workers.append(w)
        except Exception as error:
            if isinstance(error, subprocess.TimeoutExpired):
                for name, content in (("stdout.txt", error.stdout), ("stderr.txt", error.stderr)):
                    if content is not None:
                        (directory / name).write_text(content.decode("utf-8", errors="replace")
                            if isinstance(content, bytes) else content, encoding="utf-8")
            write_json(output / "incomplete.json", {"completed": False, "seed": seed, "failed_at": utcnow(),
                "reason": str(error), "parent_wall_seconds": time.perf_counter() - start,
                "scientific_gate_outcome": None, "completed_workers": [w["seed"] for w in workers]})
            raise
    summary = summarize_workers(workers, protocol)
    stable_workers = []
    for w in workers:
        item = {k: w[k] for k in ("seed", "initial_parameter_sha256", "warmed_parameter_sha256", "warmed_full_state_sha256",
            "frozen_optimizer_state_sha256", "probe_parameters_and_warm_optimizer_unchanged", "schedule_sha256", "batch_indices",
            "batch_tokens_sha256", "contexts", "gates", "counts")}
        item["gradients"] = [_stable_gradient(g) for g in w["gradients"]]
        item["warmup"] = [{**{k: v for k, v in step.items() if k != "gradient_diagnostic"},
                           "gradient_diagnostic": _stable_gradient(step["gradient_diagnostic"])} for step in w["warmup"]]
        stable_workers.append(item)
    stable = {"protocol_sha256": file_hash(protocol_path), "config_sha256": protocol["config_sha256"],
        "implementation_freeze_sha256": file_hash(freeze_path), "data_sha256": file_hash(data),
        "training_manifest_sha256": file_hash(manifest), "workers": stable_workers, **summary}
    report = {"schema_version": 1, "completed": True, "config": protocol["config"], "stable_results": stable,
        "stable_result_sha256": digest(stable), "worker_measurements": workers, "limitations": protocol["limitations"],
        "scientific_gate_failure_is_valid_completed_result": True,
        "receipt_limitation": "Hashes and sufficient statistics retained; raw theta/gradient/moment arrays not published for independent offline reference recomputation."}
    report["observation_sha256"] = digest(report)
    write_json(output / "report.json", report)
    lines = ["# Accumulated-state actual AdamW update fidelity", "",
        "Four actual dense warmup steps, then fixed warmed weights. Matched step4 is primary; fresh step0 is secondary.", "",
        "| Seed | Context | Norm-only relL2 | Attention-preserved relL2 | Treatment cosine | Error ratio | Joint gate |",
        "| --- | --- | --- | --- | --- | --- | --- |"]
    for w in workers:
        for context in CONTEXTS:
            a, b = [r["update_comparison"]["aggregate"] for r in w["contexts"][context][1:]]
            g = w["gates"]["contexts"][context]
            lines.append(f"| {w['seed']} | {context} | {a['relative_l2']:.9g} | {b['relative_l2']:.9g} | {b['cosine_similarity']:.9g} | {g['treatment_to_norm_only_relative_l2_ratio']:.9g} | {g['passed']} |")
    lines += ["", f"Primary all-seed gate: **{summary['primary_gate_passed_all_seeds']}**.", "",
        "12 native warmup steps and18 independent clone steps passed numerical theta/m/v/t controls. All76 parameters were checked per step. CE,13norm and6actual attention scopes passed. Source audit-point weights and state remained unchanged during probes.", "",
        "The three schedules overlap. Four warmup steps do not establish convergence or quality. No training-trajectory, efficiency, memory, GPU or AttnRes claim. SaveScope v0.1 remains fresh-state only.", "",
        f"Stable SHA256: `{report['stable_result_sha256']}`", f"Observation SHA256: `{report['observation_sha256']}`", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--data", type=Path, default=ROOT / "fixtures/activation-training/data.json")
    parser.add_argument("--manifest", type=Path, default=ROOT / "fixtures/activation-training/manifest.json")
    parser.add_argument("--protocol", type=Path, default=ROOT / "fixtures/activation-state-update/protocol.json")
    parser.add_argument("--freeze", type=Path, default=ROOT / "fixtures/activation-state-update/implementation.json")
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
                         "primary_passed": report["stable_results"]["primary_gate_passed_all_seeds"]}))


if __name__ == "__main__":
    main()
