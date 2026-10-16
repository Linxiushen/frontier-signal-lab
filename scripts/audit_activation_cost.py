"""Audit published cost receipts with the standard library; no model execution."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "fixtures/activation-cost/protocol.json"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def audit(report, protocol_path=None):
    count = 0

    def check(ok, label):
        nonlocal count
        count += 1
        if not ok:
            raise ValueError(label)

    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)

    def close(a, b, label):
        check(finite(a) and finite(b) and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), label)

    def fingerprint(value, label):
        check(isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value), label)

    def timestamp(value, label):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            raise ValueError(label) from None
        check(parsed.tzinfo is not None, label)
        return parsed.astimezone(dt.timezone.utc)

    protocol_raw = Path(PROTOCOL if protocol_path is None else protocol_path).read_bytes()
    check(len(protocol_raw) <= 1024 * 1024, "bounded protocol")
    protocol = json.loads(protocol_raw)
    check(type(report["schema_version"]) is int and report["schema_version"] == 1, "report schema")
    check(type(protocol["schema_version"]) is int and protocol["schema_version"] == 1, "protocol schema")
    check(digest(protocol["config"]) == protocol["config_sha256"], "declared config digest")
    check(report["protocol_sha256"] == hashlib.sha256(protocol_raw).hexdigest(), "declared protocol file")
    fingerprint(report["implementation_sha256"], "implementation digest format")
    check(report["completed"] is True, "incomplete experiment")
    check(report["scientific_screen_failure_is_completed_result"] is True, "failure preservation")
    check(digest({k: v for k, v in report.items() if k != "observation_sha256"}) == report["observation_sha256"], "observation digest")
    stable = report["stable_results"]
    check(digest(stable) == report["stable_result_sha256"], "stable digest")
    config = stable["config"]
    check(digest(config) == protocol["config_sha256"], "complete predeclared config")
    for name in ("train_sha256", "holdout_sha256"):
        fingerprint(stable[name], name)
        check(stable[name] == protocol[name], "declared " + name)
    check(config["seeds"] == [503, 701, 907] and config["token_steps"] == 64 and config["max_time_steps"] == 4096, "declared schedules")
    methods = ["dense", "model_except_norm_attention_saved_int8"]
    check(config["methods"] == methods and config["train_blocks"] == 128 and config["holdout_blocks"] == 64, "methods/data")
    expected = {(arm, seed, method) for arm in ("token", "time") for seed in config["seeds"] for method in methods}
    workers = report["workers"]
    key = lambda item: (item["arm"], item["seed"], item["method"])
    check(len(workers) == 12 and {key(w) for w in workers} == expected, "all12 workers")
    check(len({w["initial_parameter_sha256"] for w in workers}) == 1, "shared pinned initial weights")
    schedules = {}
    for seed in config["seeds"]:
        rng, flat = random.Random(seed), []
        while len(flat) < 8192:
            epoch = list(range(128)); rng.shuffle(epoch); flat.extend(epoch)
        schedules[seed] = [flat[i:i + 2] for i in range(0, 8192, 2)]
    profiles = report["profiles"]
    check(len(profiles) == 6 and {key(w) for w in profiles} == {("profile", s, m) for s in config["seeds"] for m in methods}, "all6 profiles")
    training_completions = []
    for w in workers + profiles:
        steps = w["steps_completed"]
        check(type(steps) is int and 0 < steps <= 4096, "actual steps")
        check(w["completed"] is True and w["final_validity"]["final_parameter_gradient_moments_finite"] is True, "final validity receipt")
        counters = w["final_validity"]["optimizer_counters"]
        check(len(counters) == 76 and all(type(x) is int for x in counters) and counters == [steps] * 76, "all76 native counters")
        check(type(w["training_target_positions"]) is int and w["training_target_positions"] == steps * 128, "training targets")
        losses = w["preupdate_batch_losses_recorded_after_updates"]
        check(len(losses) == steps and all(finite(x) and x >= 0 for x in losses), "complete finite loss trace")
        check(w["schedule_sha256"] == digest(schedules[w["seed"]]), "frozen full schedule")
        check(w["used_schedule_sha256"] == digest(schedules[w["seed"]][:steps]), "actual schedule prefix")
        check(w["train_sha256"] == stable["train_sha256"], "train pin")
        check(w["protocol_sha256"] == report["protocol_sha256"], "protocol pin")
        check(w["implementation_sha256"] == report["implementation_sha256"], "implementation pin")
        for name in ("initial_parameter_sha256", "final_parameter_sha256"):
            fingerprint(w[name], name)
        check(w["initial_parameter_sha256"] == workers[0]["initial_parameter_sha256"], "shared worker/profile initial state")
        if w["arm"] != "profile":
            fingerprint(w["checkpoint_sha256"], "checkpoint_sha256")
            check(w["checkpoint"] == "checkpoint.pt", "training checkpoint name")
        else:
            check(w["checkpoint"] is None and w["checkpoint_sha256"] is None, "profile not an endpoint")
        check(w["initial_parameter_sha256"] != w["final_parameter_sha256"], "changed endpoint")
        wall, cpu = w["training_loop_wall_seconds"], w["training_loop_cpu_seconds"]
        check(finite(wall) and wall > 0 and finite(cpu) and cpu >= 0, "measured clocks")
        close(w["loop_perf_counter_end"] - w["loop_perf_counter_start"], wall, "monotonic loop bounds")
        started = timestamp(w["started_at"], "worker start timestamp")
        completed = timestamp(w["completed_at"], "worker completion timestamp")
        check(started <= completed, "worker chronology")
        training_completions.append(completed)
        close(w["training_targets_per_second"], steps * 128 / wall, "throughput arithmetic")
        memory = w["memory_through_training_completion"]
        check(type(memory["peak_bytes"]) is int and type(memory["resident_bytes"]) is int
              and memory["peak_bytes"] >= memory["resident_bytes"] > 0, "lifetime peak/current order")
        if w["arm"] == "token":
            check(steps == 64 and w["time_control"] is None, "fixed token endpoint")
        elif w["arm"] == "time":
            t = w["time_control"]
            valid = 60.0 <= wall <= 61.0 and 0 < steps < 4096
            check(t["valid"] is valid and t["reached_budget"] is (wall >= 60.0), "time admissibility")
            check(t["step_cap_reached"] is (steps >= 4096), "step cap flag")
            close(t["overshoot_seconds"], wall - 60.0, "atomic overshoot")
            close(t["actual_loop_seconds"], wall, "time-control measured loop")
        else:
            check(steps == 2 and w["time_control"] is None, "two actual profile steps")
    endpoints = stable["endpoints"]
    check(len(endpoints) == 12 and {key(e) for e in endpoints} == expected, "all12 stable endpoint summaries")
    for endpoint in endpoints:
        worker = next(w for w in workers if key(w) == key(endpoint))
        check(all(endpoint[name] == worker[name] for name in
                  ("checkpoint_sha256", "initial_parameter_sha256", "final_parameter_sha256")), "stable endpoint identity")
    evaluation = stable["evaluation"]
    check(evaluation["completed"] is True and evaluation["started_only_after_all_training"] is True, "deferred evaluation receipt")
    evaluation_started = timestamp(evaluation["started_at"], "evaluation start timestamp")
    evaluation_completed = timestamp(evaluation["completed_at"], "evaluation completion timestamp")
    check(max(training_completions) <= evaluation_started <= evaluation_completed, "training before evaluation chronology")
    check(evaluation["initial_parameter_sha256"] == workers[0]["initial_parameter_sha256"], "evaluation initial state identity")
    check(evaluation["holdout_sha256"] == stable["holdout_sha256"], "heldout pin")
    scored = evaluation["endpoints"]
    check(len(scored) == 12 and {key(x) for x in scored} == expected, "every endpoint scored once")
    for item in [evaluation["initial"], *[x["evaluation"] for x in scored]]:
        values = item["block_mean_nll"]
        check(len(values) == 64 and all(finite(x) and x >= 0 for x in values), "64 finite evaluation blocks")
        check(type(item["scored_target_positions"]) is int and item["scored_target_positions"] == 4096, "4096 heldout target positions")
        close(item["mean_nll"], math.fsum(values) / 64, "full weighted NLL")
    comparisons = stable["screens"]["comparisons"]
    check(len(comparisons) == 6 and {(c["arm"], c["seed"]) for c in comparisons} == {(a, s) for a in ("token", "time") for s in config["seeds"]}, "all six comparisons")
    baseline = evaluation["initial"]["mean_nll"]
    for comparison in comparisons:
        arm, seed = comparison["arm"], comparison["seed"]
        pair = [next(w for w in workers if key(w) == (arm, seed, m)) for m in methods]
        scores = []
        for w, method in zip(pair, methods):
            e = next(x for x in scored if key(x) == (arm, seed, method))
            check(e["checkpoint_sha256"] == w["checkpoint_sha256"], "scored checkpoint identity")
            scores.append(e["evaluation"]["mean_nll"])
        dense, compressed = pair
        conditions = {"compressed_nll_no_worse_than_dense": scores[1] <= scores[0], "compressed_nll_below_initial": scores[1] < baseline}
        if arm == "token":
            conditions.update(compressed_loop_strictly_faster=compressed["training_loop_wall_seconds"] < dense["training_loop_wall_seconds"],
                compressed_lifetime_peak_strictly_lower=compressed["memory_through_training_completion"]["peak_bytes"] < dense["memory_through_training_completion"]["peak_bytes"])
        time_valid = arm != "time" or all(w["time_control"]["valid"] for w in pair)
        check(all(type(v) is bool for v in comparison["conditions"].values())
              and comparison["conditions"] == conditions
              and comparison["time_control_valid"] is time_valid, "prospective screen conditions")
        check(comparison["directional_screen_passed"] is (time_valid and all(conditions.values())), "screen outcome")
        for name, value in {"initial_nll": baseline, "dense_final_nll": scores[0], "compressed_final_nll": scores[1],
            "compressed_minus_dense_nll": scores[1] - scores[0], "dense_final_minus_initial_nll": scores[0] - baseline,
            "compressed_final_minus_initial_nll": scores[1] - baseline,
            "compressed_to_dense_wall_ratio": compressed["training_loop_wall_seconds"] / dense["training_loop_wall_seconds"],
            "compressed_minus_dense_lifetime_peak_bytes": compressed["memory_through_training_completion"]["peak_bytes"] - dense["memory_through_training_completion"]["peak_bytes"]}.items():
            close(comparison[name], value, name)
    check(stable["screens"]["all_token_directional_screens_passed"] is all(c["directional_screen_passed"] for c in comparisons if c["arm"] == "token"), "token aggregate")
    check(stable["screens"]["all_time_controls_and_directional_screens_passed"] is all(c["directional_screen_passed"] for c in comparisons if c["arm"] == "time"), "time aggregate")
    return {"schema_version": 1, "passed": True, "checks_passed": count,
        "report_stable_sha256": report["stable_result_sha256"], "report_observation_sha256": report["observation_sha256"],
        "screens": {k: v for k, v in stable["screens"].items() if k != "comparisons"},
        "limitation": "Receipt hash/algebra/completeness and timestamp-consistency audit against declared protocol only. Does not authenticate resealed receipts, independently inspect implementation freeze, remeasure OS peaks/clocks, recompute model losses/gradients or establish cryptographic isolation of public heldout bytes. Endpoint weights are not bundled."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.report.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("report exceeds 16 MiB")
    raw = args.report.read_bytes()
    result = audit(json.loads(raw))
    result["report_file_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write("\n")
    print(json.dumps({"passed": result["passed"], "checks": result["checks_passed"]}))


if __name__ == "__main__":
    main()
