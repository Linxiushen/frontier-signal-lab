"""Post-outcome preservation check, not the frozen native acceptance auditor.

Reads saved bytes only. It imports no producer and launches no processes.
The extra native process was not identified by the failed run.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(output, protocol_path, freeze_path, root):
    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def read(path):
        return json.loads(path.read_bytes())

    protocol, freeze = read(protocol_path), read(freeze_path)
    report = read(output / "report.json")
    require(protocol["id"] == "native-observer-ledger-integration-v1", "protocol identity")
    require(report["protocol_sha256"] == freeze["protocol_sha256"] == sha(protocol_path), "protocol hash")
    require(report["freeze_sha256"] == sha(freeze_path), "freeze hash")
    for path, digest in freeze["source_sha256"].items():
        require(sha(root / path) == digest, "frozen source: " + path)
    require(datetime.fromisoformat(freeze["frozen_at"]) < datetime.fromisoformat(report["started_at"])
            < datetime.fromisoformat(report["completed_at"]), "execution chronology")
    require(report["passed"] is False, "native acceptance must remain false")
    require(all(report[k] == 0 for k in ["scientific_experiments", "model_loads", "optimizer_updates"]), "no science/model work")
    require(protocol["cases"] == ["threaded_samples", "row_cap", "partial_write"], "planned cases")
    require(len(report["cases"]) == 1, "stop after first failed case")
    case = report["cases"][0]
    directory = output / "threaded_samples"
    require(case == read(directory / "result.json"), "case/report equality")
    require(case["name"] == "threaded_samples" and case["passed"] is False
            and case["error"] == "AssertionError: ", "saved generic failure")
    require(not any(k in case for k in ["sampler_native_thread_ids", "shutdown_error", "expected_error"]), "unexpected progressed/cleanup fields")
    require(not any((directory / n).exists() for n in ["stop.json", "finished.json"]), "worker stop not reached")
    require(not any((output / n).exists() for n in protocol["cases"][1:]), "unrun cases")
    ready, identity = read(directory / "ready.json"), case["native_identity"]
    require(ready == case["ready"] and ready["nonce"] == case["nonce"], "ready nonce")
    require(identity["pid"] == ready["pid"] and identity["creation_filetime"] == ready["creation_filetime"], "worker identity")
    require(identity["parent_pid"] == ready["parent_pid"] == case["parent_pid"], "parent identity")
    require(identity["image_sha256"] == ready["executable_sha256"] == report["python_executable_sha256"]
            == freeze["python_executable_sha256"], "pinned executable hash")
    require(identity["job_active_count"] == 2 and identity["job_member"] is True, "failed one-process topology")
    shutdown = case["shutdown"]
    cleanup, state = shutdown["native_cleanup"], shutdown["ledger"]
    require(cleanup["all_retained_handles_exited"] is True and cleanup["job_active_count"] == 0, "retained exit and empty Job")
    require(cleanup["exit_codes"] == [{"pid": identity["pid"], "creation_filetime": identity["creation_filetime"], "exit_code": 0xE003}], "only retained worker exit")
    require(shutdown["handles_closed"] is True and shutdown["native_errors"] == [], "handle closes")
    require(shutdown["trace_complete"] is True and shutdown["trace_error"] is None
            and state["failure"] is None and state["poisoned"] is False, "two lifecycle writes only")
    rows = state["records"]
    raw = (directory / "trace.jsonl").read_bytes()
    canonical = b"".join((json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode() for r in rows)
    require(raw == canonical and hashlib.sha256(raw).hexdigest() == case["trace_sha256"], "exact canonical trace")
    require(state["committed_rows"] == case["write_calls"] == len(rows) == 2
            and state["committed_bytes"] == len(raw) == 521, "trace byte/row inventory")
    require([r["seq"] for r in rows] == [0, 1] and [r["kind"] for r in rows] == ["started", "closed"], "zero recorded samples")
    require(rows[0]["pid"] == identity["pid"] and rows[0]["creation_filetime"] == identity["creation_filetime"], "start identity")
    require(rows[1]["cleanup"] == cleanup and rows[0]["native_thread_id"] == rows[1]["native_thread_id"], "cleanup trace identity")
    require(rows[0]["emitted_perf_counter"] < ready["perf_counter"] <= cleanup["started_perf_counter"]
            <= cleanup["completed_perf_counter"] <= rows[1]["emitted_perf_counter"], "saved lifecycle order")
    require(cleanup["timeout_seconds"] == protocol["cleanup_seconds"] == 4
            and 0 <= cleanup["wall_seconds"] < 4, "saved cleanup duration")
    return {"preservation_passed": True, "native_acceptance": False,
            "cases_run": 1, "cases_planned": 3, "recorded_samples": 0,
            "model_loads": 0, "optimizer_updates": 0,
            "retained_exits": 1, "job_active_count_after_cleanup": 0,
            "extra_process_identity": "not captured; no retrospective attribution",
            "scope": "Post-outcome saved-byte/source check by the same agent; no independent live execution or acceptance upgrade"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("results/observed-job/raw"))
    parser.add_argument("--protocol", type=Path, default=Path("fixtures/observed-job/protocol.json"))
    parser.add_argument("--freeze", type=Path, default=Path("fixtures/observed-job/implementation.json"))
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    print(json.dumps(check(args.output, args.protocol, args.freeze, args.root)))
