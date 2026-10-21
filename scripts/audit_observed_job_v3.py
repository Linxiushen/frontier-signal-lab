"""V3 saved-byte acceptance; corrected schema, no producer/native imports."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_inventory(snapshot, case, freeze, helper=False):
    nodes = snapshot["processes"]
    identities = {(n["pid"], n["creation_filetime"]) for n in nodes}
    assert len(identities) == len(nodes) == len({n["pid"] for n in nodes})
    assert snapshot["census_complete"] is True and snapshot["errors"] == []
    assert snapshot["truncated"] is False and snapshot["query_budget_exceeded"] is False
    assert snapshot["all_known_present"] is True
    assert set(snapshot["observed_pids"]) == {n["pid"] for n in nodes}
    assert snapshot["job_count_before"] == snapshot["job_count_after"] == len(nodes)
    assert snapshot["job_count_matches_before"] is True and snapshot["job_count_matches_after"] is True
    assert 0 <= snapshot["wall_seconds"] <= 5
    assert snapshot["wall_seconds"] == snapshot["completed_perf_counter"] - snapshot["started_perf_counter"]
    worker = case["worker_ref"]
    primary = [n for n in nodes if n["pid"] == worker["pid"]]
    assert len(primary) == 1
    primary = primary[0]
    assert primary["creation_filetime"] == worker["creation_filetime"]
    assert primary["parent_pid"] == case["parent_pid"] and primary["approved_known"] is True
    assert primary["policy_role"] == "worker"
    consoles = []
    helper_consoles = []
    helper_ref = case["helper_ready"] if helper else None
    for node in nodes:
        assert node["job_member"] is True and node["alive"] is True and not node.get("error")
        image = node["image"]
        assert image["queried_from_retained_handle"] is True and image["retained_identity_stable"] is True
        role = "worker" if node["pid"] == worker["pid"] or (helper and node["pid"] == case["helper_ready"]["pid"]) else "conhost"
        assert role in image["exact_path_matches"]
        assert image["basename"].lower() == ("conhost.exe" if role == "conhost" else freeze["worker_basename"].lower())
        assert image["sha256"] == freeze["executables_sha256"][role]
        assert image["normalized_path_sha256"] == freeze["executable_path_sha256"][role]
        if node != primary:
            expected_parent = (helper_ref if helper and role == "conhost"
                and node["parent_pid"] == helper_ref["pid"] else worker)
            assert node["parent_pid"] == expected_parent["pid"]
            assert node["creation_filetime"] >= expected_parent["creation_filetime"]
            assert node["approved_known"] is False
            if role == "conhost":
                if helper and node["parent_pid"] == helper_ref["pid"]:
                    helper_consoles.append(node)
                else:
                    consoles.append(node)
            else:
                assert node["creation_filetime"] == case["helper_ready"]["creation_filetime"]
    assert len(consoles) == 1 and len(nodes) == (4 if helper else 2)
    assert len(helper_consoles) == (1 if helper else 0)
    assert set(snapshot["unapproved_pids"]) == {n["pid"] for n in nodes if n != primary}
    console = consoles[0]
    pin = {"owner": worker, "auxiliary": {"pid": console["pid"], "creation_filetime": console["creation_filetime"]}}
    return identities, pin


def audit_trace(raw, case, protocol):
    result = case["shutdown"]
    state, worker = result["ledger"], case["worker_ref"]
    rows = state["records"]
    prefix = b"".join((json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode() for r in rows)
    assert len(prefix) == state["committed_bytes"]
    assert len(rows) == state["committed_rows"]
    assert [r["seq"] for r in rows] == list(range(len(rows)))
    assert rows[0]["kind"] == "started"
    assert {k: rows[0][k] for k in worker} == worker
    stamps = [r["emitted_perf_counter"] for r in rows]
    assert stamps == sorted(stamps) and all(type(r["native_thread_id"]) is int for r in rows)
    name = case["name"]
    if name in ("threaded_samples", "unregistered_python"):
        assert raw == prefix and result["trace_complete"] is True and result["trace_error"] is None
        assert state["poisoned"] is False and state["failure"] is None
        assert rows[-1]["kind"] == "closed" and rows[-1]["cleanup"] == result["native_cleanup"]
        assert case["write_calls"] == len(rows)
        if name == "unregistered_python":
            assert len(rows) == 2
        else:
            assert len(rows) == protocol["healthy_expected_rows"]
            samples = rows[1:-1]
            expected = {f"{t}:{i}" for t in range(protocol["sampler_threads"]) for i in range(protocol["samples_per_thread"])}
            assert len(samples) == len(expected) and {r["request_id"] for r in samples} == expected
            tids = case["sampler_native_thread_ids"]
            assert len(tids) == len(set(tids)) == protocol["sampler_threads"]
            assert set(tids) == {r["native_thread_id"] for r in samples}
            for row in samples:
                reading = row["reading"]
                assert row["kind"] == "sample" and {k: reading[k] for k in worker} == worker
                assert case["censuses"][0]["completed_perf_counter"] <= reading["perf_counter"] <= row["emitted_perf_counter"] <= case["censuses"][1]["started_perf_counter"]
                assert reading["memory"]["backend"] == "Windows GetProcessMemoryInfo"
                assert all(type(reading["memory"][k]) is int and reading["memory"][k] >= 0 for k in ("resident_bytes", "private_bytes", "peak_resident_bytes"))
    else:
        partial = name == "partial_write"
        assert len(rows) == 1 and result["trace_complete"] is False and case["later_sampling_refused"] is True
        expected = "LedgerIOError" if partial else "LedgerLimitError"
        assert case["expected_error"] == result["trace_error"]["error_type"] == expected
        assert result["trace_error"]["kind"] == "sample"
        assert state["poisoned"] is partial and raw == prefix + (b'{"emi' if partial else b'')
        assert case["write_calls"] == (2 if partial else 1)
        if partial:
            failure = state["failure"]
            assert failure["seq"] == 1 and failure["stage"] == "write" and failure["error_type"] == "OSError"
            assert failure["sink_may_have_uncommitted_bytes"] is True and failure["flush_completed"] is False
        else:
            assert state["failure"] is None


def audit(output, protocol_path, freeze_path, root):
    protocol, freeze = json.loads(protocol_path.read_bytes()), json.loads(freeze_path.read_bytes())
    report = json.loads((output / "report.json").read_bytes())
    assert report["passed"] is True
    assert report["protocol_sha256"] == freeze["protocol_sha256"] == sha(protocol_path)
    assert report["freeze_sha256"] == sha(freeze_path)
    assert report["executables_sha256"] == freeze["executables_sha256"]
    assert report["scientific_experiments"] == report["model_loads"] == report["optimizer_updates"] == 0
    assert datetime.fromisoformat(freeze["frozen_at"]) < datetime.fromisoformat(report["started_at"]) < datetime.fromisoformat(report["completed_at"])
    for path, digest in freeze["source_sha256"].items():
        assert sha(root / path) == digest, path
    assert [c["name"] for c in report["cases"]] == protocol["cases"]
    total_exits = total_rows = 0
    for case in report["cases"]:
        directory = output / case["name"]
        assert case == json.loads((directory / "result.json").read_bytes()) and case["passed"] is True
        assert case["error"] is None and "shutdown_error" not in case
        assert case["started_perf_counter"] < case["work_completed_perf_counter"] <= case["completed_perf_counter"]
        assert case["completed_perf_counter"] - case["started_perf_counter"] < protocol["case_seconds"]
        ready = json.loads((directory / "ready.json").read_bytes())
        assert ready == case["ready"] and ready["nonce"] == case["nonce"]
        assert {k: ready[k] for k in case["worker_ref"]} == case["worker_ref"]
        assert ready["parent_pid"] == case["parent_pid"] and ready["executable_sha256"] == freeze["executables_sha256"]["worker"]
        inventories, decisions = case["censuses"], case["decisions"]
        assert len(inventories) == len(decisions) == 2
        assert [s["label"] for s in inventories] == ["before_sampling", "before_cleanup"]
        first_ids, pin = audit_inventory(inventories[0], case, freeze)
        helper = case["name"] == "unregistered_python"
        last_ids, last_pin = audit_inventory(inventories[1], case, freeze, helper)
        assert pin == last_pin
        assert case["started_perf_counter"] <= ready["perf_counter"] <= inventories[0]["started_perf_counter"]
        assert inventories[0]["completed_perf_counter"] <= inventories[1]["started_perf_counter"]
        assert inventories[1]["completed_perf_counter"] <= case["work_completed_perf_counter"]
        for index, decision in enumerate(decisions):
            assert decision["label"] == inventories[index]["label"] and decision["pin"] == pin
            assert decision["training_permitted"] is False
            assert set(decision["admitted_pids"]) == {p for p, _ in first_ids}
            rejected = sorted(p for p, _ in last_ids - first_ids) if helper and index else []
            assert decision["rejected_pids"] == rejected
            assert decision["admitted"] is (not rejected)
            assert decision["errors"] == (["unregistered_process_identity"] if rejected else [])
        if helper:
            extra = json.loads((directory / "helper-ready.json").read_bytes())
            launch = json.loads((directory / "helper-launch.json").read_bytes())
            assert extra == case["helper_ready"] and launch == case["helper_launch"]
            assert launch["nonce"] == extra["nonce"] == case["nonce"]
            assert launch["pid"] == extra["pid"] and extra["parent_pid"] == case["worker_ref"]["pid"]
            assert extra["executable_sha256"] == freeze["executables_sha256"]["worker"]
            assert case["same_image_rejection"] is True and (extra["pid"], extra["creation_filetime"]) in last_ids - first_ids and len(last_ids - first_ids) == 2
            assert not (directory / "stop.json").exists()
        result = case["shutdown"]
        cleanup = result["native_cleanup"]
        assert cleanup["all_retained_handles_exited"] is True and cleanup["job_active_count"] == 0
        exits = cleanup["exit_codes"]
        assert {(r["pid"], r["creation_filetime"]) for r in exits} == last_ids and len(exits) == len(last_ids)
        assert all(type(r["exit_code"]) is int and r["exit_code"] != 259 for r in exits)
        primary_exit = next(r for r in exits if r["pid"] == case["worker_ref"]["pid"])
        assert primary_exit["exit_code"] == (0 if case["name"] == "threaded_samples" else 0xE003)
        assert result["handles_closed"] is True and result["native_errors"] == []
        if case["name"] == "threaded_samples":
            assert json.loads((directory / "stop.json").read_bytes()) == {"nonce": case["nonce"], "command": "stop"}
            finished = json.loads((directory / "finished.json").read_bytes())
            assert finished == case["finished"] and {k: finished[k] for k in case["worker_ref"]} == case["worker_ref"]
        raw = (directory / "trace.jsonl").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == case["trace_sha256"]
        audit_trace(raw, case, protocol)
        total_exits += len(exits)
        total_rows += result["ledger"]["committed_rows"]
    return {"passed": True, "cases": len(report["cases"]), "retained_exits": total_exits,
        "committed_rows": total_rows, "scope": "Independent saved bytes/identity/cleanup checks, no independent live or model/GPU/performance execution"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("output", "protocol", "freeze", "root"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.output, args.protocol, args.freeze, args.root)))
