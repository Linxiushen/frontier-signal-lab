"""Post-outcome saved-byte review; never repairs frozen v2 acceptance.

No producer, ML import, process launch or workload execution. The frozen auditor
passed every healthy check except its old raw-file inventory, which omitted the
seven new progress files. Preserve that rejection and review the complete file
set before replaying the unchanged checks on their original payload subset.
"""
import argparse
import hashlib
import json
from pathlib import Path

from scripts import audit_training_ledger_v2 as frozen

ROOT = Path(__file__).resolve().parents[1]
PROGRESS = {f"import-progress-{i:02d}.json" for i in range(7)}
REJECTION = "healthy:exact_raw_identity_controls_stages_loop_completion_files"
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()


def payload_sets(case, directory):
    """Require the exact union, retaining all progress and fault-only receipts."""
    original = frozen.raw_payloads(case)
    expected = dict(original)
    for row in case["controller_controls"]:
        expected[row["filename"]] = {k: v for k, v in row.items() if k != "filename"}
    if case["id"] == "partial_pretrain":
        # Parent failed during this query, before receiving the after bracket.
        name = "pretrain-before.json"
        expected[name] = json.loads((directory / name).read_bytes())
        before = expected[name]
        wid = case["worker_identity"]["self_receipt"]
        replay = frozen.Replay()
        frozen.reading(replay, before, (wid["pid"], wid["creation_filetime"]),
                       case["stages"]["pretrain"]["stage_ready_perf_counter"],
                       case["completed_perf_counter"], "fault:pretrain-before")
        replay.message(before, case["nonce"], "worker", wid["pid"], "fault:pretrain-before")
        assert all(c["passed"] for c in replay.checks)
        for row in case["controller_controls"]:
            name = row["filename"].replace(".json", "-accepted.json")
            expected[name] = json.loads((directory / name).read_bytes())
    paths = list(directory.glob("*.json"))
    assert {p.name for p in paths} == set(expected) | PROGRESS, "exact raw-file union differs"
    assert {p.name for p in directory.iterdir()} == set(expected) | PROGRESS | {"trace.jsonl"}, "unexpected raw file/tail"
    actual = {p.name: json.loads(p.read_bytes()) for p in paths}
    assert {name: actual[name] for name in expected} == expected, "original payload differs"
    return actual, {name: actual[name] for name in original}


def review(output, protocol_path, freeze_path, root=ROOT):
    report = json.loads((output / "report.json").read_bytes())
    protocol = json.loads(protocol_path.read_bytes())
    freeze = json.loads(freeze_path.read_bytes())
    assert report["id"] == protocol["id"] == "actual-pretrained-training-ledger-v2"
    assert report["passed"] is True
    assert report["protocol_sha256"] == freeze["protocol_sha256"] == sha(protocol_path)
    assert report["freeze_sha256"] == sha(freeze_path)
    assert all(sha(root / p) == h for p, h in freeze["source_sha256"].items())
    assert protocol["limits"] == frozen.LIMITS and protocol["training_config"] == frozen.CONFIG
    assert protocol["cases"] == [c["id"] for c in report["cases"]] == ["healthy", "partial_pretrain"]
    started, completed = frozen.stamp(report["started_at"]), frozen.stamp(report["completed_at"])
    assert frozen.stamp(protocol["predeclared_at"]) <= frozen.stamp(freeze["frozen_at"]) <= started <= completed
    start, end = report["started_perf_counter"], report["completed_perf_counter"]
    assert end - start <= 240
    healthy, fault = report["cases"]
    assert healthy["completed_perf_counter"] <= fault["started_perf_counter"]
    all_raw, old_raw = payload_sets(healthy, output / "healthy")
    original_checks = frozen.healthy(healthy, freeze, all_raw, start, end, started, completed)
    failures = [c for c in original_checks if not c["passed"]]
    assert failures == [{"check": REJECTION, "passed": False}], failures
    projected = frozen.healthy(healthy, freeze, old_raw, start, end, started, completed)
    assert all(c["passed"] for c in projected), [c for c in projected if not c["passed"]]
    payload_sets(fault, output / "partial_pretrain")
    assert frozen.fault_checks(fault, healthy, output / "partial_pretrain", freeze)
    progress = {c["id"]: frozen.audit_progress(c, output / c["id"], freeze) for c in (healthy, fault)}
    ledger = {c["id"]: frozen.ledger_checks(c, (output / c["id"] / "trace.jsonl").read_bytes()) for c in (healthy, fault)}
    return {"post_outcome_preservation": True, "frozen_saved_byte_acceptance": False,
            "original_healthy_checks": len(original_checks),
            "original_healthy_checks_passed": len(original_checks) - len(failures),
            "frozen_rejections": failures, "projected_healthy_checks_passed": len(projected),
            "progress": progress, "ledger": ledger, "model_loads": 2, "optimizer_updates": 16,
            "retained_exits": sum(len(c["cleanup"]["exit_codes"]) for c in (healthy, fault)),
            "jobs_empty": sum(c["cleanup"]["job_active_count"] == 0 for c in (healthy, fault)),
            "boundary": "Post-outcome schema reconciliation, not preregistered acceptance, timeout attribution, cost/quality or production validation."}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for name in ("output", "protocol", "freeze"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(review(a.output, a.protocol, a.freeze), indent=2))
