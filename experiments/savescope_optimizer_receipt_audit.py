"""Audit saved tiny AdamW integration receipts with the Python standard library.

This reads JSON and frozen source files only. It never imports SaveScope, Torch
or NumPy, executes a model, or recreates an experiment. Dense saved tensor values
permit independent numerical checks. Compressed-arm intervals and caller object
preservation remain producer receipts bound to frozen source, not independent
observations of their tensors, pointers, versions, or RNG state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[1]
SHAPES = {
    "extra": [8], "reserve": [8], "project.weight": [64, 32],
    "project.bias": [64], "norm.weight": [64], "norm.bias": [64],
    "head.weight": [8, 64], "head.bias": [8],
}
UNUSED = {"extra", "reserve"}
POLICIES = ["dense", "int8", "int8_keep_sensitive"]
CONTROL_NAMES = {
    "all_policy_arms_valid", "caller_values_groups_state_rng_unchanged",
    "caller_parameter_grad_storage_versions_unchanged",
    "caller_optimizer_storage_versions_unchanged", "unequal_input_steps",
    "unused_initialized_state_retains_counter", "unused_lazy_state_stays_absent",
    "all_native_parameter_hashes_match", "all_native_update_hashes_match",
    "all_used_native_gradient_hashes_match", "fresh_reset_produces_different_update",
    "caller_unchanged_after_fresh_control", "negative_variance_refuses_before_forward",
    "invalid_state_not_repaired_or_mutated", "callback_exception_preserved",
    "caller_unchanged_after_callback_error",
}
EPS32, TINY32 = 2.0 ** -23, 2.0 ** -126


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_bytes(), parse_constant=no_constant,
                      object_pairs_hook=unique_object)


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def flattened(value, shape):
    if not shape:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("tensor scalar is not a finite number")
        if float(value) != f32(value):
            raise ValueError("saved tensor value is not exactly float32")
        return [float(value)]
    if not isinstance(value, list) or len(value) != shape[0]:
        raise ValueError("saved tensor shape differs: " + str(shape))
    return [number for child in value for number in flattened(child, shape[1:])]


def tensor_hash(values, shape):
    header = json.dumps({"dtype": "float32", "shape": shape}, sort_keys=True).encode()
    return hashlib.sha256(header + b"\0" + struct.pack("<" + "f" * len(values), *values)).hexdigest()


def tensor(value, shape):
    values = flattened(value, shape)
    return values, tensor_hash(values, shape)


def indexed(rows):
    result = {row["name"]: row for row in rows}
    if len(result) != len(rows) or set(result) != set(SHAPES):
        raise ValueError("parameter rows must contain each expected name once")
    return result


def finite_nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def close(a, b):
    return math.isclose(a, b, rel_tol=2e-10, abs_tol=1e-20)


class Review:
    def __init__(self):
        self.checks = {}
        self.details = {}
        self.inputs = {}

    def check(self, name, condition, detail=None):
        if name in self.checks:
            raise ValueError("duplicate review check: " + name)
        self.checks[name] = bool(condition)
        if detail is not None:
            self.details[name] = detail

    def read(self, path):
        self.inputs[str(path.resolve())] = sha(path)
        return read_json(path)


def inspect_trajectory(review, trajectory):
    labels = ["initial"] + ["warmup_" + str(i) for i in range(1, 5)] + ["native_dense_reference_after"]
    review.check("trajectory_labels", [row["label"] for row in trajectory] == labels)
    if len(trajectory) != 6:
        raise ValueError("expected six saved trajectory nodes")
    nodes = []
    for index, row in enumerate(trajectory):
        values = row["values"]
        review.check("trajectory_names_" + str(index), set(values) == set(SHAPES))
        node = {}
        for name, shape in SHAPES.items():
            param, param_hash = tensor(values[name]["parameter"], shape)
            state = values[name]["state"]
            step = 0 if index == 0 or name == "reserve" else (
                min((index + 1) // 2, 2) if name == "extra" else index)
            if index == 5 and name != "extra" and name != "reserve":
                step = 5
            review.check(f"state_keys_{index}_{name}", set(state) == (
                {"step", "exp_avg", "exp_avg_sq"} if step else set()))
            state_values, state_hashes = {}, {}
            for key, value in state.items():
                state_values[key], state_hashes[key] = tensor(value, [] if key == "step" else shape)
            review.check(f"counter_{index}_{name}", (state_values.get("step", [0])[0] == step))
            review.check(f"nonnegative_variance_{index}_{name}",
                         all(v >= 0 for v in state_values.get("exp_avg_sq", [])))
            node[name] = {"parameter": param, "parameter_hash": param_hash,
                          "state": state_values, "state_hashes": state_hashes, "step": step}
        if index in (1, 2, 3, 4):
            review.check("finite_warmup_loss_" + str(index), finite_nonnegative(row["loss"]))
        nodes.append(node)
    for i in range(1, 6):
        review.check("reserve_unchanged_" + str(i), nodes[i]["reserve"] == nodes[0]["reserve"])
    for i in (2, 4, 5):
        review.check("initialized_unused_extra_unchanged_" + str(i), nodes[i]["extra"] == nodes[i - 1]["extra"])
    return nodes


def check_summaries(review, arm, policy):
    review.check(policy + "_valid", arm["numerically_valid"] is True and math.isfinite(arm["loss"]))
    for kind in ("gradient", "update"):
        summary = arm[kind]
        rows = indexed(summary["per_parameter"])
        review.check(policy + "_" + kind + "_shape_counts", summary["tensors"] == 8 and
                     summary["elements"] == 2776 and summary["finite"] is True and
                     summary["present_tensors"] == (6 if kind == "gradient" else 8) and
                     finite_nonnegative(summary["l2"]) and all(
                         row["shape"] == SHAPES[name] and row["elements"] == math.prod(SHAPES[name]) and
                         row["finite"] is True and finite_nonnegative(row["l2"]) and
                         row["present"] is (name not in UNUSED if kind == "gradient" else True)
                         for name, row in rows.items()))
    review.check(policy + "_unused_gradients", set(arm["gradient"]["unused_parameters"]) == UNUSED)
    review.check(policy + "_cloned_step_receipt", arm["update"]["executed"] is True and
                 arm["update"]["clone_storages_disjoint"] is True)


def check_interval_receipts(review, arm, policy, source):
    ref = arm["update"]["independent_reference"]
    expected_bound = {
        "float32_epsilon_multiplier": 8, "float32_tiny_multiplier": 8,
        "moment_scale": "sum(abs(each recurrence input))",
        "parameter_interval": "four m/v corners plus float32 update rounding padding",
    }
    review.check(policy + "_interval_kind_and_bound", ref["kind"] ==
                 "numpy_float64_accumulated_adamw_transition" and ref["rounding_bound"] == expected_bound and
                 ref["all_parameter_and_moment_checks_passed"] is True)
    rows = indexed(ref["per_parameter"])
    for name, row in rows.items():
        review.check(f"{policy}_interval_steps_{name}", row["optimizer_step_before"] == source[name]["step"] and
                     row["optimizer_step"] == source[name]["step"] + int(name not in UNUSED) and
                     row["initialized_before"] is bool(source[name]["step"]) and
                     row["gradient_present"] is (name not in UNUSED))
        for kind in ("parameter", "exp_avg", "exp_avg_sq"):
            receipt = row[kind]
            review.check(f"{policy}_interval_receipt_{name}_{kind}",
                         receipt["passed"] is True and receipt["finite"] is True and
                         receipt["kind"] == ("four_corner_moment_interval" if kind == "parameter" else "input_scale_rounding") and
                         finite_nonnegative(receipt["max_absolute_error"]) and
                         finite_nonnegative(receipt["max_interval_width"]) and
                         receipt["max_absolute_error"] <= receipt["max_interval_width"] / 2 + 1e-20)
    return rows


def dense_numbers(review, before, after, gradients, dense, protocol):
    gradient_rows = indexed(dense["gradient"]["per_parameter"])
    update_rows = indexed(dense["update"]["per_parameter"])
    controls = indexed(dense["update"]["independent_reference"]["per_parameter"])
    review.check("direct_dense_gradient_names", set(gradients) == set(SHAPES) - UNUSED)
    options = protocol["optimizer"]
    b1, b2 = options["betas"]
    lr, decay, eps = options["lr"], options["weight_decay"], options["eps"]
    checked_scalars = 0
    for name, shape in SHAPES.items():
        old, new = before[name], after[name]
        grad = tensor(gradients[name], shape)[0] if name not in UNUSED else [0.0] * len(old["parameter"])
        review.check("dense_gradient_hash_" + name, tensor_hash(grad, shape) == gradient_rows[name]["sha256"])
        delta = [f32(a - b) for a, b in zip(new["parameter"], old["parameter"])]
        review.check("dense_native_update_hash_" + name, tensor_hash(delta, shape) == update_rows[name]["sha256"])
        review.check("dense_native_parameter_hash_" + name,
                     new["parameter_hash"] == controls[name]["parameter_sha256_after"])
        m0 = old["state"].get("exp_avg", [0.0] * len(grad))
        v0 = old["state"].get("exp_avg_sq", [0.0] * len(grad))
        actual_m = new["state"].get("exp_avg", [0.0] * len(grad))
        actual_v = new["state"].get("exp_avg_sq", [0.0] * len(grad))
        stats = {key: {"max_absolute_error": 0.0, "max_interval_width": 0.0, "passed": True}
                 for key in ("parameter", "exp_avg", "exp_avg_sq")}
        for i, (theta, g, mean0, square0) in enumerate(zip(old["parameter"], grad, m0, v0)):
            if name in UNUSED:
                low, high, mean, square, dm, dv = theta, theta, mean0, square0, 0.0, 0.0
            else:
                mean = b1 * mean0 + (1 - b1) * g
                square = b2 * square0 + (1 - b2) * g * g
                dm = 8 * EPS32 * (abs(b1 * mean0) + abs((1 - b1) * g)) + 8 * TINY32
                dv = 8 * EPS32 * (abs(b2 * square0) + abs((1 - b2) * g * g)) + 8 * TINY32
                counter = old["step"] + 1

                def parameter(m, v):
                    return theta * (1 - lr * decay) - lr * (m / (1 - b1 ** counter)) / (
                        math.sqrt(v / (1 - b2 ** counter)) + eps)

                corners = [parameter(m, v) for m in (mean - dm, mean + dm)
                           for v in (max(0, square - dv), square + dv)]
                low, high = min(corners), max(corners)
                padding = 8 * EPS32 * (abs(theta) + max(abs(low - theta), abs(high - theta))) + 8 * TINY32
                low, high = low - padding, high + padding
            intervals = {"parameter": (new["parameter"][i], low, high),
                         "exp_avg": (actual_m[i], mean - dm, mean + dm),
                         "exp_avg_sq": (actual_v[i], square - dv, square + dv)}
            for key, (actual, low, high) in intervals.items():
                stats[key]["passed"] &= low <= actual <= high
                stats[key]["max_absolute_error"] = max(stats[key]["max_absolute_error"], abs(actual - (low + high) / 2))
                stats[key]["max_interval_width"] = max(stats[key]["max_interval_width"], high - low)
                checked_scalars += 1
        for key, observed in stats.items():
            review.check(f"dense_recomputed_interval_{name}_{key}", observed["passed"], observed)
            review.check(f"dense_interval_summary_matches_{name}_{key}", all(close(observed[field], controls[name][key][field])
                         for field in ("max_absolute_error", "max_interval_width")))
    review.details["dense_independently_checked_scalar_intervals"] = checked_scalars


def audit_saved(review, result, protocol_path, freeze_path):
    protocol = review.read(protocol_path)
    freeze = review.read(freeze_path)
    report_path, trajectory_path = result / "report.json", result / "trajectory.json"
    report, trajectory = review.read(report_path), review.read(trajectory_path)
    public_root = ROOT.resolve()
    for relative, expected in freeze["files"].items():
        path = (public_root / relative).resolve()
        if not path.is_relative_to(public_root):
            raise ValueError("freeze source outside repository")
        actual = sha(path)
        review.inputs[str(path)] = actual
        review.check("frozen_source_" + relative, actual == expected)
    review.check("required_sources_frozen", {"experiments/savescope_optimizer_probe.py", "savescope/audit.py",
                 "savescope/optimizer_state.py"} <= set(freeze["files"]))
    review.check("protocol_and_freeze_bindings", freeze["protocol_sha256"] == sha(protocol_path) == report["protocol_sha256"] and
                 report["implementation_freeze_sha256"] == sha(freeze_path))
    review.check("one_suite_frozen_before_execution", freeze["kind"] == "savescope_accumulated_adamw_implementation_freeze" and
                 freeze["actual_suites_before_freeze"] == 0 and freeze["allowed_actual_suites"] == 1 and
                 dt.datetime.fromisoformat(freeze["frozen_at"]) < dt.datetime.fromisoformat(report["started_at"]))
    review.check("report_payload_hash", report["payload_sha256"] == digest({k: v for k, v in report.items() if k != "payload_sha256"}))
    review.check("trajectory_file_hash", report["trajectory_sha256"] == sha(trajectory_path))
    review.check("fixed_protocol", protocol["kind"] == "savescope_accumulated_adamw_product_integration" and
                 protocol["seed"] == 20261018 and protocol["warmup_steps"] == 4 and protocol["device"] == "cpu" and
                 protocol["dtype"] == "float32" and protocol["threads"] == 1 and protocol["batch_shape"] == [4, 16, 32] and
                 protocol["hidden"] == 64 and protocol["outputs"] == 8 and protocol["policies"] == POLICIES and
                 protocol["optimizer"] == {"lr": .001, "betas": [.8, .95], "eps": .000001, "weight_decay": .01})
    review.check("execution_budget_declaration", protocol["execution_budget"] == {"actual_suites": 1,
                 "pretrained_model_loads": 0, "source_warmup_updates": 4, "cloned_native_updates": 5, "retries": 0})
    review.check("execution_counters_and_outcome", report["status"] == "passed" and report["kind"] == protocol["kind"] and
                 all(report[key] == value for key, value in {"actual_suites": 1, "retries": 0, "pretrained_model_loads": 0,
                     "warmup_updates_completed": 4, "direct_reference_updates_completed": 1,
                     "stateful_arms_completed": 3, "fresh_control_arms_completed": 1}.items()))
    review.check("all_16_producer_controls_recorded", set(report["checks"]) == CONTROL_NAMES and all(v is True for v in report["checks"].values()))
    review.check("claim_limit_preserved", report["claim_limit"] == protocol["claim_limit"])
    start, end = (dt.datetime.fromisoformat(report[key]) for key in ("started_at", "completed_at"))
    review.check("ordered_aware_execution_times", start.utcoffset() is not None and end.utcoffset() is not None and start < end)
    nodes = inspect_trajectory(review, trajectory)
    source, final = nodes[4], nodes[5]
    audit = report["audit"]
    review.check("model_shape_and_scope_metadata", audit["kind"] == "savescope_audit" and audit["mode"] == "executed" and
                 audit["model"]["parameter_tensors"] == 8 and audit["model"]["trainable_parameter_tensors"] == 8 and
                 audit["model"]["trainable_elements"] == 2776 and audit["model"]["device"] == "cpu" and
                 audit["model"]["parameter_dtype"] == "float32")
    snapshot = audit["optimizer"]["snapshot"]
    review.check("source_snapshot_payload", snapshot["payload_sha256"] == digest({k: v for k, v in snapshot.items() if k != "payload_sha256"}))
    review.check("snapshot_receipt_contract", snapshot["kind"] == "caller_adamw_single_group_snapshot" and
                 snapshot["mapping"] == "exact Parameter object identities" and snapshot["options"] == protocol["optimizer"] and
                 snapshot["caller_optimizer_stepped"] is False and snapshot["source_state_storages_disjoint"] is True)
    snapshot_rows = indexed(snapshot["parameters"])
    inputs = report["input_receipt"]
    review.check("input_parameter_names", set(inputs["parameters"]) == set(SHAPES))
    review.check("source_optimizer_metadata", audit["optimizer"]["type"] == "AdamW" and
                 audit["optimizer"]["initial_state"] == "captured caller AdamW state for every arm" and
                 all(audit["optimizer"][key] == value for key, value in protocol["optimizer"].items()))
    group = inputs["groups"]
    review.check("input_group_options", len(group) == 1 and all(group[0][key] == value for key, value in protocol["optimizer"].items()) and
                 all(group[0].get(key, False) is False for key in ("amsgrad", "maximize", "foreach", "capturable", "differentiable", "fused")))
    for name, source_row in source.items():
        receipt, captured = snapshot_rows[name], inputs["parameters"][name]
        review.check("source_input_parameter_hash_" + name,
                     source_row["parameter_hash"] == receipt["parameter_sha256"] == captured["parameter"] and captured["grad"] is None)
        review.check("source_input_state_hashes_" + name,
                     source_row["state_hashes"] == captured["state"] and receipt["step"] == source_row["step"] and
                     receipt["initialized"] is bool(source_row["step"]) and
                     {key[:-7]: value for key, value in receipt.items() if key.endswith("_sha256") and key != "parameter_sha256"} == source_row["state_hashes"])
    review.check("policy_order", [arm["policy"] for arm in audit["arms"]] == POLICIES)
    for arm in audit["arms"]:
        check_summaries(review, arm, arm["policy"])
        controls = check_interval_receipts(review, arm, arm["policy"], source)
        gradients, updates = (indexed(arm[key]["per_parameter"]) for key in ("gradient", "update"))
        for name in UNUSED:
            zeros = tensor_hash([0.0] * math.prod(SHAPES[name]), SHAPES[name])
            review.check(arm["policy"] + "_unused_zero_hashes_" + name,
                         gradients[name]["sha256"] == updates[name]["sha256"] == zeros and
                         controls[name]["parameter_sha256_after"] == source[name]["parameter_hash"])
    dense_numbers(review, source, final, trajectory[-1]["gradients"], audit["arms"][0], protocol)
    fresh = report["fresh_control"]
    review.check("fresh_reset_metadata", fresh["optimizer"]["initial_state"] == "fresh zero moments for every arm" and
                 "snapshot" not in fresh["optimizer"] and len(fresh["arms"]) == 1 and fresh["arms"][0]["policy"] == "dense")
    fresh_arm = fresh["arms"][0]
    check_summaries(review, fresh_arm, "fresh_dense")
    fresh_ref = fresh_arm["update"]["independent_reference"]
    review.check("fresh_reference_kind", fresh_ref["kind"] == "numpy_float64_closed_form_adamw_first_step" and
                 fresh_ref["all_parameter_and_moment_checks_passed"] is True)
    fresh_rows = indexed(fresh_ref["per_parameter"])
    review.check("fresh_counters", all(row["optimizer_step"] == int(name not in UNUSED) for name, row in fresh_rows.items()))
    for name, row in fresh_rows.items():
        for key in ("parameter", "exp_avg", "exp_avg_sq"):
            receipt = row[key]
            review.check("fresh_receipt_" + name + "_" + key, receipt["passed"] is True and
                         receipt["finite"] is True and finite_nonnegative(receipt["max_absolute_error"]) and
                         finite_nonnegative(receipt["max_fraction_of_allowed_error"]) and
                         receipt["max_fraction_of_allowed_error"] <= 1)
    review.check("fresh_and_accumulated_dense_same_gradient", fresh_arm["gradient"] == audit["arms"][0]["gradient"] and
                 fresh_arm["loss"] == audit["arms"][0]["loss"])
    old_updates, reset_updates = (indexed(value["update"]["per_parameter"]) for value in (audit["arms"][0], fresh_arm))
    review.check("fresh_reset_used_update_hash_differs", any(old_updates[name]["sha256"] != reset_updates[name]["sha256"] for name in set(SHAPES) - UNUSED))
    review.check("fresh_reset_unused_update_hashes_equal", all(old_updates[name]["sha256"] == reset_updates[name]["sha256"] for name in UNUSED))
    review.check("negative_variance_error_recorded", report["negative_state_error"] == "AdamW second moment must be nonnegative")
    viewer_path = result / "viewer" / "report.json"
    viewer = review.read(viewer_path)
    review.check("viewer_contains_exact_audit", viewer["audit_result"] == audit)
    review.check("viewer_content_payload", viewer["content_sha256"] == digest({k: v for k, v in viewer.items() if k != "content_sha256"}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=ROOT / "fixtures/savescope-optimizer-state/protocol.json")
    parser.add_argument("--freeze", type=Path, default=ROOT / "fixtures/savescope-optimizer-state/implementation.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    review = Review()
    error = None
    try:
        audit_saved(review, args.result, args.protocol, args.freeze)
    except (KeyError, ValueError, TypeError, OSError, OverflowError, struct.error) as exc:
        error = type(exc).__name__ + ": " + str(exc)
        review.check("review_completed_without_structural_error", False, error)
    else:
        review.check("review_completed_without_structural_error", True)
    record = {
        "kind": "stdlib_saved_optimizer_receipt_review", "reviewed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "passed": error is None and all(review.checks.values()), "checks": review.checks,
        "details": review.details, "input_sha256": review.inputs, "reviewer_sha256": sha(Path(__file__)),
        "limitations": [
            "Saved JSON and frozen source only; no model, optimizer, Torch, NumPy, suite or scientific replay executed.",
            "Dense native parameter, gradient and update hashes plus m/v/t intervals recomputed from saved float32 values with stdlib.",
            "Warmup gradients were not saved; warmup steps/state/parameters were checked for structure, consistency and source hash binding, not independently regenerated.",
            "Compressed native tensor values were not saved; their three-policy interval receipts were checked structurally and bound to frozen source, not numerically regenerated.",
            "Caller pointer/version/RNG preservation and clone storage disjointness are source-bound producer controls, not independent runtime measurements.",
            "One tiny common-state diagnostic is not training quality, convergence, performance, memory saving, GPU or trajectory equivalence evidence.",
        ],
    }
    record["payload_sha256"] = digest(record)
    serialized = json.dumps(record, indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
    print(json.dumps({"passed": record["passed"], "checks": len(record["checks"]),
                      "failed_checks": [name for name, passed in record["checks"].items() if not passed],
                      "payload_sha256": record["payload_sha256"]}))
    raise SystemExit(0 if record["passed"] else 1)


if __name__ == "__main__":
    main()
