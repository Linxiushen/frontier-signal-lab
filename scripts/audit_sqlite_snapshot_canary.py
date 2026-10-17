"""Verify saved canary receipts without opening SQLite or starting processes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def audit(directory):
    directory = Path(directory).resolve()
    report = json.loads((directory / "report.json").read_bytes())
    checks = {}

    def check(name, condition):
        checks[name] = bool(condition)

    payload = dict(report)
    claimed = payload.pop("result_sha256")
    check("canonical_result_hash", digest(payload) == claimed)
    freeze = json.loads((directory / "implementation.json").read_bytes())
    check("freeze_binding", report["producer_sha256"] == freeze["files"]["experiments/sqlite_snapshot_canary.py"]
          and report["protocol_sha256"] == freeze["files"]["fixtures/sqlite-snapshot-canary/protocol.json"]
          and hashlib.sha256((directory / "implementation.json").read_bytes()).hexdigest() == report["implementation_sha256"]
          and hashlib.sha256((directory / "protocol.json").read_bytes()).hexdigest() == report["protocol_sha256"])
    for name, receipt in report["artifacts"].items():
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or path == directory:
            raise ValueError("artifact escapes result directory")
        check("artifact:" + name, path.is_file() and path.stat().st_size == receipt["bytes"]
              and hashlib.sha256(path.read_bytes()).hexdigest() == receipt["sha256"])
    check("producer_acceptance", report["passed"] and report["error"] is None
          and report["gates"] and all(report["gates"].values()))
    check("single_suite_no_retries", report["suite_launches"] == 1 and report["retries"] == 0)
    # Independent literal truth, not a producer-generated expected snapshot.
    zero = {"contexts": [["session-0", 0, "turn-0", "ready"]],
            "messages": [["message-0", 0, "literal generation zero"]],
            "receipts": [["receipt-0", "message-0", 0, "committed"]]}
    one = {"contexts": [["session-0", 1, "turn-1", "ready"]],
           "messages": zero["messages"] + [["message-1", 1, "literal generation one"]],
           "receipts": zero["receipts"] + [["receipt-1", "message-1", 1, "committed"]]}
    for arm, expected in (("source", one), ("main_file_copy", zero), ("sqlite_backup", one)):
        observed = report["observations"][arm]
        check(arm + ":two_readers", len(observed) == 2)
        for index, value in enumerate(observed, 1):
            raw = json.loads((directory / "raw" / f"{arm}-reader{index}.jsonl").read_bytes())
            check(f"{arm}:{index}:raw_binding", raw == value and raw["event"] == "reader_closed")
            check(f"{arm}:{index}:oracle", raw["snapshot"] == expected
                  and raw["logical_sha256"] == digest(expected) and raw["integrity_check"] == ["ok"])
    writer = [json.loads(line) for line in (directory / "raw/writer.jsonl").read_text().splitlines()]
    check("writer_order", [v["event"] for v in writer] == ["baseline_ready", "generation1_committed",
                                                          "generation2_uncommitted", "fail_stop_requested"])
    check("writer_identity", all(v["pid"] == report["writer_pid"] for v in writer))
    check("writer_settings", writer[0]["journal_mode"] == "wal" and writer[0]["synchronous"] == 2
          and writer[0]["wal_autocheckpoint"] == 0)
    check("capture_raw_binding", [report["capture_barrier"][key] for key in ("baseline", "committed", "staged")]
          == writer[:3])
    check("writer_checkpoint_and_commit", writer[0]["checkpoint"] == [0, 0, 0]
          and writer[0]["snapshot"] == zero and writer[1]["snapshot"] == one)
    two = {"contexts": [["session-0", 2, "turn-2", "ready"]],
           "messages": one["messages"] + [["message-2", 2, "uncommitted generation two"]],
           "receipts": one["receipts"] + [["receipt-2", "message-2", 2, "committed"]]}
    check("writer_uncommitted", writer[2]["snapshot"] == two
          and writer[2]["in_transaction"] is True and writer[3]["in_transaction"] is True)
    check("fail_stop_and_cleanup", report["writer_exit_code"] == 86
          and report["writer_final_exit_code"] == 86 and not report.get("cleanup_error"))
    backup = json.loads((directory / "raw/backup.jsonl").read_bytes())
    check("backup_raw_binding", backup == report["backup"] and backup["event"] == "backup_closed")
    check("backup_completion", backup["source_before"] == one and backup["progress"][-1]["status"] == 101)
    events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    times = [v["elapsed_seconds"] for v in events]
    check("ordered_parent_trace", times == sorted(times))
    names = [v["event"] for v in events]
    crash = next(i for i, v in enumerate(events) if v["event"] == "writer_command" and v["command"] == "crash")
    backup_done = next(i for i, v in enumerate(events) if v["event"] == "worker_exited" and v["role"] == "backup")
    check("capture_before_crash", names.index("capture_barrier") < names.index("main_file_copy_closed") < backup_done < crash)
    launched = {v["role"]: v["pid"] for v in events if v["event"] == "worker_started"}
    exits = {v["role"]: (v["pid"], v["exit_code"]) for v in events if v["event"] == "worker_exited"}
    check("seven_child_exit_receipts", len(launched) == len(exits) == 7
          and all(exits[role] == (pid, 0) for role, pid in launched.items()))
    check("backup_pid_binding", backup["pid"] == launched["backup"])
    check("reader_pid_binding", all(v["pid"] == launched[f"{arm}-reader{index}"]
          for arm, values in report["observations"].items() for index, v in enumerate(values, 1)))
    check("six_independent_reader_processes", len({v["pid"] for arm in report["observations"].values()
                                                 for v in arm}) == 6)
    return {"passed": all(checks.values()), "checks": checks,
            "result_sha256": claimed,
            "scope": "Saved byte custody and literal outcomes; no SQLite execution or production claim."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
