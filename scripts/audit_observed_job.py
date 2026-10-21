"""Read-only saved-byte audit; imports no observer/producer and starts no work."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(output, protocol_path, freeze_path, root):
    protocol = json.loads(protocol_path.read_bytes()); freeze = json.loads(freeze_path.read_bytes())
    report = json.loads((output / "report.json").read_bytes())
    assert report["passed"] and report["protocol_sha256"] == freeze["protocol_sha256"] == sha(protocol_path)
    assert report["freeze_sha256"] == sha(freeze_path)
    assert report["scientific_experiments"] == report["model_loads"] == report["optimizer_updates"] == 0
    assert datetime.fromisoformat(freeze["frozen_at"]) < datetime.fromisoformat(report["started_at"]) < datetime.fromisoformat(report["completed_at"])
    assert report["python_executable_sha256"] == freeze["python_executable_sha256"]
    for path, digest in freeze["source_sha256"].items(): assert sha(root / path) == digest, path
    assert [c["name"] for c in report["cases"]] == protocol["cases"]
    for case in report["cases"]:
        name = case["name"]; directory = output / name
        assert case == json.loads((directory / "result.json").read_bytes()) and case["passed"]
        raw = (directory / "trace.jsonl").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == case["trace_sha256"]
        result = case["shutdown"]; state = result["ledger"]; identity = case["native_identity"]
        ready = json.loads((directory / "ready.json").read_bytes()); assert ready == case["ready"]
        assert identity["pid"] == ready["pid"] and identity["creation_filetime"] == ready["creation_filetime"]
        assert identity["parent_pid"] == ready["parent_pid"] == case["parent_pid"]
        assert identity["job_active_count"] == 1 and identity["job_member"] is True
        assert identity["image_sha256"] == ready["executable_sha256"] == freeze["python_executable_sha256"]
        assert ready["nonce"] == case["nonce"]
        cleanup = result["native_cleanup"]
        assert cleanup["all_retained_handles_exited"] and cleanup["job_active_count"] == 0
        assert len(cleanup["exit_codes"]) == 1
        exit_row = cleanup["exit_codes"][0]
        assert (exit_row["pid"], exit_row["creation_filetime"]) == (identity["pid"], identity["creation_filetime"])
        assert exit_row["exit_code"] == (0 if name == "threaded_samples" else 0xE003)
        assert result["handles_closed"] and result["native_errors"] == []
        prefix = b"".join((json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode() for r in state["records"])
        assert len(prefix) == state["committed_bytes"] and raw.startswith(prefix)
        rows = state["records"]; assert [r["seq"] for r in rows] == list(range(state["committed_rows"]))
        assert rows[0]["kind"] == "started" and rows[0]["pid"] == identity["pid"]
        assert rows[0]["creation_filetime"] == identity["creation_filetime"]
        stamps = [r["emitted_perf_counter"] for r in rows]; assert stamps == sorted(stamps)
        if name == "threaded_samples":
            assert len(rows) == protocol["healthy_expected_rows"] and raw == prefix
            assert result["trace_complete"] and state["failure"] is None and not state["poisoned"]
            assert rows[-1]["kind"] == "closed" and rows[-1]["cleanup"] == cleanup
            samples = rows[1:-1]
            universe = {f"{w}:{i}" for w in range(protocol["sampler_threads"]) for i in range(protocol["samples_per_thread"])}
            assert len(samples) == len(universe) and {s["request_id"] for s in samples} == universe
            tids = case["sampler_native_thread_ids"]; assert len(tids) == len(set(tids)) == protocol["sampler_threads"]
            assert {s["native_thread_id"] for s in samples} == set(tids)
            for sample in samples:
                reading = sample["reading"]
                assert sample["kind"] == "sample" and reading["pid"] == identity["pid"] and reading["creation_filetime"] == identity["creation_filetime"]
                assert ready["perf_counter"] <= reading["perf_counter"] <= sample["emitted_perf_counter"]
                assert reading["memory"]["backend"] == "Windows GetProcessMemoryInfo"
                assert all(type(reading["memory"][k]) is int and reading["memory"][k] >= 0 for k in ["resident_bytes", "private_bytes", "peak_resident_bytes"])
            assert case["write_calls"] == len(rows)
        else:
            assert len(rows) == 1 and not result["trace_complete"] and case["later_sampling_refused"]
            expected = "LedgerLimitError" if name == "row_cap" else "LedgerIOError"
            assert case["expected_error"] == result["trace_error"]["error_type"] == expected
            assert state["poisoned"] == (name == "partial_write")
            assert raw == prefix + (b'{"kin' if name == "partial_write" else b'')
            assert case["write_calls"] == (2 if name == "partial_write" else 1)
            if name == "partial_write":
                assert state["failure"]["seq"] == 1 and state["failure"]["stage"] == "write"
                assert state["failure"]["sink_may_have_uncommitted_bytes"] and not state["failure"]["flush_completed"]
    return {"passed": True, "cases": len(report["cases"]), "scope": "Saved bytes, identities and cleanup receipts; no independent live-process, training, distributed or performance execution"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ["output", "protocol", "freeze", "root"]: parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.output, args.protocol, args.freeze, args.root)))
