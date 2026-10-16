"""Reject inconsistent resealed receipts without ML or reading heldout content."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts import audit_activation_cost as auditor


PROTOCOL_BYTES = auditor.PROTOCOL.read_bytes()
PROTOCOL = json.loads(PROTOCOL_BYTES)
METHODS = ("dense", "model_except_norm_attention_saved_int8")
SEEDS = (503, 701, 907)


def seal_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def fingerprint(label):
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def reseal(report):
    report["stable_result_sha256"] = seal_hash(report["stable_results"])
    report["observation_sha256"] = seal_hash({k: v for k, v in report.items()
                                             if k != "observation_sha256"})
    return report


def score(value):
    return {"mean_nll": value, "block_mean_nll": [value] * 64,
            "scored_target_positions": 4096}


def synthetic_receipt():
    """Known outcomes, arbitrary non-artifact digests; no claim of execution."""
    workers, profiles, endpoints, scored, comparisons = [], [], [], [], []
    protocol_hash = hashlib.sha256(PROTOCOL_BYTES).hexdigest()
    for arm in ("token", "time", "profile"):
        for seed in SEEDS:
            for method in METHODS:
                compressed = method == METHODS[1]
                steps = 2 if arm == "profile" else 64
                wall = 60.5 if arm == "time" else (0.25 if arm == "profile" else (1.0 if compressed else 2.0))
                checkpoint = None if arm == "profile" else fingerprint(f"checkpoint:{arm}:{seed}:{method}")
                schedule = PROTOCOL["schedules"][str(seed)]
                used_hash = (seal_hash(schedule["token_batches"][:2]) if arm == "profile"
                             else schedule["token_schedule_sha256"])
                w = {"arm": arm, "seed": seed, "method": method, "completed": True,
                     "steps_completed": steps, "training_target_positions": steps * 128,
                     "final_validity": {"final_parameter_gradient_moments_finite": True,
                                        "optimizer_counters": [steps] * 76},
                     "preupdate_batch_losses_recorded_after_updates": [1.5] * steps,
                     "schedule_sha256": schedule["time_schedule_sha256"],
                     "used_schedule_sha256": used_hash,
                     "train_sha256": PROTOCOL["train_sha256"],
                     "protocol_sha256": protocol_hash,
                     "implementation_sha256": fingerprint("synthetic-freeze"),
                     "initial_parameter_sha256": "a" * 64,
                     "final_parameter_sha256": fingerprint(f"endpoint:{arm}:{seed}:{method}"),
                     "checkpoint": None if arm == "profile" else "checkpoint.pt",
                     "checkpoint_sha256": checkpoint,
                     "training_loop_wall_seconds": wall, "training_loop_cpu_seconds": wall / 2,
                     "loop_perf_counter_start": 4096.0, "loop_perf_counter_end": 4096.0 + wall,
                     "started_at": "2026-10-16T15:00:00+00:00",
                     "completed_at": "2026-10-16T15:01:01+00:00",
                     "training_targets_per_second": steps * 128 / wall,
                     "memory_through_training_completion": {
                         "peak_bytes": 100 if compressed else 200, "resident_bytes": 80},
                     "time_control": ({"valid": True, "reached_budget": True,
                                       "step_cap_reached": False, "overshoot_seconds": 0.5,
                                       "actual_loop_seconds": wall} if arm == "time" else None)}
                if arm == "profile":
                    profiles.append(w)
                else:
                    workers.append(w)
                    endpoints.append({k: w[k] for k in ("arm", "seed", "method",
                        "checkpoint_sha256", "initial_parameter_sha256", "final_parameter_sha256")})
                    scored.append({"arm": arm, "seed": seed, "method": method,
                                   "checkpoint_sha256": checkpoint,
                                   "evaluation": score(1.0 if compressed else 1.25)})
            if arm != "profile":
                conditions = {"compressed_nll_no_worse_than_dense": True,
                              "compressed_nll_below_initial": True}
                if arm == "token":
                    conditions.update(compressed_loop_strictly_faster=True,
                                      compressed_lifetime_peak_strictly_lower=True)
                comparisons.append({"arm": arm, "seed": seed, "initial_nll": 2.0,
                    "dense_final_nll": 1.25, "compressed_final_nll": 1.0,
                    "compressed_minus_dense_nll": -0.25,
                    "dense_final_minus_initial_nll": -0.75,
                    "compressed_final_minus_initial_nll": -1.0,
                    "compressed_to_dense_wall_ratio": 1.0 if arm == "time" else 0.5,
                    "compressed_minus_dense_lifetime_peak_bytes": -100,
                    "time_control_valid": True, "conditions": conditions,
                    "directional_screen_passed": True})
    return reseal({"schema_version": 1, "completed": True,
        "scientific_screen_failure_is_completed_result": True,
        "protocol_sha256": protocol_hash, "implementation_sha256": fingerprint("synthetic-freeze"),
        "workers": workers, "profiles": profiles,
        "stable_results": {"config": copy.deepcopy(PROTOCOL["config"]),
            "train_sha256": PROTOCOL["train_sha256"], "holdout_sha256": PROTOCOL["holdout_sha256"],
            "endpoints": endpoints,
            "evaluation": {"completed": True, "started_only_after_all_training": True,
                "started_at": "2026-10-16T15:02:00+00:00", "completed_at": "2026-10-16T15:03:00+00:00",
                "initial_parameter_sha256": "a" * 64, "holdout_sha256": PROTOCOL["holdout_sha256"],
                "initial": score(2.0), "endpoints": scored},
            "screens": {"comparisons": comparisons, "all_token_directional_screens_passed": True,
                        "all_time_controls_and_directional_screens_passed": True}}})


class ReceiptValidityTests(unittest.TestCase):
    def setUp(self):
        self.report = synthetic_receipt()

    def rejects(self, label):
        with self.assertRaisesRegex(ValueError, label):
            auditor.audit(reseal(self.report))

    def test_complete_synthetic_receipt_passes_without_model_or_data(self):
        self.assertTrue(auditor.audit(self.report)["passed"])

    def test_resealed_wrong_mean_nll_is_rejected(self):
        self.report["stable_results"]["evaluation"]["initial"]["mean_nll"] = 2.25
        self.rejects("full weighted NLL")

    def test_resealed_negative_block_nll_is_rejected(self):
        self.report["stable_results"]["evaluation"]["initial"] = score(-1.0)
        self.rejects("64 finite evaluation blocks")

    def test_changed_seed_cannot_replace_a_declared_worker(self):
        self.report["workers"][0]["seed"] = 504
        self.rejects("all12 workers")

    def test_native_counter_cannot_be_missing_or_rounded(self):
        for bad in ([64] * 75, [63] + [64] * 75, [64.0] * 76):
            with self.subTest(counter=bad[:1], count=len(bad)):
                report = synthetic_receipt()
                report["workers"][0]["final_validity"]["optimizer_counters"] = bad
                with self.assertRaisesRegex(ValueError, "all76 native counters"):
                    auditor.audit(reseal(report))

    def test_profile_receipt_must_crosslink_protocol_train_implementation_schedule(self):
        for field in ("protocol_sha256", "implementation_sha256", "train_sha256", "schedule_sha256", "used_schedule_sha256"):
            with self.subTest(field=field):
                report = synthetic_receipt()
                report["profiles"][0][field] = "f" * 64
                with self.assertRaises(ValueError):
                    auditor.audit(reseal(report))

    def test_profile_counter_is_also_a_real_step_counter(self):
        self.report["profiles"][0]["final_validity"]["optimizer_counters"][0] = 1
        self.rejects("all76 native counters")

    def test_truthy_string_is_not_completion(self):
        self.report["workers"][0]["completed"] = "true"
        self.rejects("final validity receipt")

    def test_resealed_optimizer_change_violates_declared_protocol(self):
        self.report["stable_results"]["config"]["optimizer"]["learning_rate"] = 0.01
        self.rejects("complete predeclared config")

    def test_config_numeric_alias_cannot_replace_declared_boolean(self):
        self.report["stable_results"]["config"]["optimizer"]["foreach"] = 0
        self.rejects("complete predeclared config")

    def test_resealed_changed_protocol_pin_is_rejected(self):
        self.report["protocol_sha256"] = "f" * 64
        self.rejects("declared protocol file")

    def test_resealed_stable_endpoint_identity_must_match_worker(self):
        self.report["stable_results"]["endpoints"][0]["final_parameter_sha256"] = "f" * 64
        self.rejects("stable endpoint identity")

    def test_resealed_evaluation_initial_digest_must_match_workers(self):
        self.report["stable_results"]["evaluation"]["initial_parameter_sha256"] = "f" * 64
        self.rejects("evaluation initial state identity")

    def test_resealed_scored_checkpoint_must_match_worker(self):
        self.report["stable_results"]["evaluation"]["endpoints"][0]["checkpoint_sha256"] = "f" * 64
        self.rejects("scored checkpoint identity")

    def test_evaluation_started_before_last_profile_is_rejected(self):
        self.report["profiles"][-1]["completed_at"] = "2026-10-16T15:02:01+00:00"
        self.rejects("training before evaluation chronology")

    def test_monotonic_loop_span_must_match_measured_wall(self):
        self.report["workers"][0]["loop_perf_counter_end"] += 0.25
        self.rejects("monotonic loop bounds")

    def test_resealed_time_cap_cannot_be_reported_as_valid(self):
        w = next(w for w in self.report["workers"] if w["arm"] == "time")
        self.make_capped(w)
        w["time_control"]["valid"] = True
        self.rejects("time admissibility")

    @staticmethod
    def make_capped(w):
        w["steps_completed"] = 4096
        w["training_target_positions"] = 4096 * 128
        w["training_targets_per_second"] = 4096 * 128 / 60.5
        w["final_validity"]["optimizer_counters"] = [4096] * 76
        w["preupdate_batch_losses_recorded_after_updates"] = [1.5] * 4096
        w["used_schedule_sha256"] = PROTOCOL["schedules"][str(w["seed"])]["time_schedule_sha256"]
        w["time_control"].update(valid=False, step_cap_reached=True)

    def test_consistently_reported_capped_result_is_retained_as_failed_screen(self):
        w = next(w for w in self.report["workers"] if w["arm"] == "time")
        self.make_capped(w)
        screens = self.report["stable_results"]["screens"]
        comparison = next(c for c in screens["comparisons"] if c["arm"] == "time" and c["seed"] == w["seed"])
        comparison.update(time_control_valid=False, directional_screen_passed=False)
        screens["all_time_controls_and_directional_screens_passed"] = False
        result = auditor.audit(reseal(self.report))
        self.assertTrue(result["passed"])
        self.assertFalse(result["screens"]["all_time_controls_and_directional_screens_passed"])

    def test_steps_beyond_declared_cap_are_structurally_impossible(self):
        w = next(w for w in self.report["workers"] if w["arm"] == "time")
        w["steps_completed"] = 4097
        self.rejects("actual steps")

    def test_time_control_cannot_claim_a_different_measured_loop(self):
        w = next(w for w in self.report["workers"] if w["arm"] == "time")
        w["time_control"]["actual_loop_seconds"] = 61.0
        self.rejects("time-control measured loop")

    def test_resealed_directional_condition_cannot_be_inverted(self):
        c = self.report["stable_results"]["screens"]["comparisons"][0]
        c["conditions"]["compressed_nll_no_worse_than_dense"] = False
        c["directional_screen_passed"] = False
        self.rejects("prospective screen conditions")

    def test_screen_numeric_alias_is_not_a_boolean_condition(self):
        c = self.report["stable_results"]["screens"]["comparisons"][0]
        c["conditions"]["compressed_nll_no_worse_than_dense"] = 1
        self.rejects("prospective screen conditions")

    def test_resealed_aggregate_cannot_hide_failed_or_passed_pair(self):
        self.report["stable_results"]["screens"]["all_token_directional_screens_passed"] = False
        self.rejects("token aggregate")

    def test_unsealed_change_is_rejected_before_algebra(self):
        self.report["workers"][0]["steps_completed"] = 1
        with self.assertRaisesRegex(ValueError, "observation digest"):
            auditor.audit(self.report)

    def test_stable_digest_is_checked_even_with_resealed_outer_observation(self):
        self.report["stable_result_sha256"] = "f" * 64
        self.report["observation_sha256"] = seal_hash({k: v for k, v in self.report.items() if k != "observation_sha256"})
        with self.assertRaisesRegex(ValueError, "stable digest"):
            auditor.audit(self.report)

    def test_cli_audits_unicode_paths_without_site_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "合成 收据.json"
            output = Path(directory) / "独立 审计.json"
            source.write_text(json.dumps(self.report, ensure_ascii=False), encoding="utf-8")
            child = subprocess.run([sys.executable, "-S", str(Path(auditor.__file__).resolve()),
                "--report", str(source), "--output", str(output)], cwd=directory,
                capture_output=True, text=True, check=False, timeout=20)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["passed"])


if __name__ == "__main__":
    unittest.main()
