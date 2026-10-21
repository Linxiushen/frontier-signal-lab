"""Post-outcome preservation, never the frozen v2 acceptance gate.

The frozen auditor rejects the partial tail and its unrun fourth-case inventory
assumption also fails. This checker reads those receipts without retrying native
work, editing frozen code, or upgrading acceptance.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

from scripts import audit_observed_job_v2 as frozen


def check(output, protocol_path, freeze_path, root):
    read = lambda p: json.loads(p.read_bytes())
    protocol, freeze = read(protocol_path), read(freeze_path)
    report = read(output / "report.json")
    assert report["passed"] is True
    assert report["protocol_sha256"] == freeze["protocol_sha256"] == frozen.sha(protocol_path)
    assert report["freeze_sha256"] == frozen.sha(freeze_path)
    assert report["executables_sha256"] == freeze["executables_sha256"]
    assert report["scientific_experiments"] == report["model_loads"] == report["optimizer_updates"] == 0
    assert datetime.fromisoformat(freeze["frozen_at"]) < datetime.fromisoformat(report["started_at"]) < datetime.fromisoformat(report["completed_at"])
    for path, digest in freeze["source_sha256"].items():
        assert frozen.sha(root / path) == digest, path
    assert [c["name"] for c in report["cases"]] == protocol["cases"]
    assert protocol["cases"] == ["threaded_samples", "row_cap", "partial_write", "unregistered_python"]
    # Failure remains observable through the original, unchanged auditor.
    try:
        frozen.audit(output, protocol_path, freeze_path, root)
    except AssertionError as error:
        tb = error.__traceback__
        while tb.tb_next:
            tb = tb.tb_next
        assert tb.tb_frame.f_code.co_name == "audit_trace"
        assert "raw == prefix" in (root / "scripts/audit_observed_job_v2.py").read_text().splitlines()[tb.tb_lineno-1]
    else:
        raise AssertionError("Frozen audit unexpectedly accepted")
    total_exits = total_rows = 0
    for case in report["cases"]:
        directory = output / case["name"]
        assert case == read(directory / "result.json") and case["passed"] is True
        assert case["error"] is None and "shutdown_error" not in case
        assert case["started_perf_counter"] < case["work_completed_perf_counter"] <= case["completed_perf_counter"]
        assert case["completed_perf_counter"] - case["started_perf_counter"] < protocol["case_seconds"]
        ready = read(directory / "ready.json")
        worker = case["worker_ref"]
        assert ready == case["ready"] and ready["nonce"] == case["nonce"]
        assert {k: ready[k] for k in worker} == worker
        assert ready["parent_pid"] == case["parent_pid"]
        assert ready["executable_sha256"] == freeze["executables_sha256"]["worker"]
        inventories = case["censuses"]
        assert len(inventories) == len(case["decisions"]) == 2
        first_ids, pin = frozen.audit_inventory(inventories[0], case, freeze)
        helper = case["name"] == "unregistered_python"
        if not helper:
            last_ids, last_pin = frozen.audit_inventory(inventories[1], case, freeze)
            assert last_pin == pin
        else:
            # This is a post-outcome four-node observation, not a new preregistered
            # acceptance topology. Original auditor assumes three direct children.
            last = inventories[1]
            try:
                frozen.audit_inventory(last, case, freeze, helper=True)
            except AssertionError:
                pass
            else:
                raise AssertionError("Frozen fourth-case assumption unexpectedly accepted")
            extra = read(directory / "helper-ready.json")
            launch = read(directory / "helper-launch.json")
            assert extra == case["helper_ready"] and launch == case["helper_launch"]
            assert launch["nonce"] == extra["nonce"] == case["nonce"]
            assert launch["pid"] == extra["pid"] and extra["parent_pid"] == worker["pid"]
            assert extra["executable_sha256"] == freeze["executables_sha256"]["worker"]
            assert case["same_image_rejection"] is True and not (directory / "stop.json").exists()
            nodes = last["processes"]
            last_ids = {(n["pid"], n["creation_filetime"]) for n in nodes}
            assert len(last_ids) == len(nodes) == len({n["pid"] for n in nodes}) == 4
            assert last["census_complete"] is True and last["errors"] == []
            assert last["truncated"] is False and last["query_budget_exceeded"] is False
            assert last["job_count_before"] == last["job_count_after"] == len(nodes)
            assert set(last["observed_pids"]) == {n["pid"] for n in nodes}
            assert 0 <= last["wall_seconds"] <= 5
            by_pid = {n["pid"]: n for n in nodes}
            assert set(n["pid"] for n in nodes if n["approved_known"]) == {worker["pid"]}
            assert set(last["unapproved_pids"]) == set(by_pid) - {worker["pid"]}
            for node in nodes:
                assert node["job_member"] is True and node["alive"] is True and not node.get("error")
                role = "worker" if node["pid"] in (worker["pid"], extra["pid"]) else "conhost"
                image = node["image"]
                assert image["queried_from_retained_handle"] is True and image["retained_identity_stable"] is True
                assert role in image["exact_path_matches"]
                assert image["sha256"] == freeze["executables_sha256"][role]
                assert image["normalized_path_sha256"] == freeze["executable_path_sha256"][role]
                if node["pid"] != worker["pid"]:
                    parent = by_pid[node["parent_pid"]]
                    assert parent["creation_filetime"] <= node["creation_filetime"]
            assert by_pid[extra["pid"]]["creation_filetime"] == extra["creation_filetime"]
            assert by_pid[worker["pid"]]["creation_filetime"] == worker["creation_filetime"]
            assert by_pid[worker["pid"]]["parent_pid"] == case["parent_pid"]
            assert by_pid[pin["auxiliary"]["pid"]]["creation_filetime"] == pin["auxiliary"]["creation_filetime"]
            assert by_pid[pin["auxiliary"]["pid"]]["parent_pid"] == worker["pid"]
            rejected = set(by_pid) - {p for p, _ in first_ids}
            assert extra["pid"] in rejected and len(rejected) == 2
            auxiliary = next(by_pid[p] for p in rejected if p != extra["pid"])
            assert auxiliary["parent_pid"] == extra["pid"] and "conhost" in auxiliary["image"]["exact_path_matches"]
        assert inventories[0]["completed_perf_counter"] <= inventories[1]["started_perf_counter"]
        assert inventories[1]["completed_perf_counter"] <= case["work_completed_perf_counter"]
        for index, decision in enumerate(case["decisions"]):
            rejected = sorted(p for p, _ in last_ids - first_ids) if helper and index else []
            assert decision["pin"] == pin and decision["rejected_pids"] == rejected
            assert set(decision["admitted_pids"]) == {p for p, _ in first_ids}
            assert decision["admitted"] is (not rejected) and decision["training_permitted"] is False
            assert decision["errors"] == (["unregistered_process_identity"] if rejected else [])
        result = case["shutdown"]
        cleanup = result["native_cleanup"]
        assert cleanup["all_retained_handles_exited"] is True and cleanup["job_active_count"] == 0
        exits = cleanup["exit_codes"]
        assert {(r["pid"], r["creation_filetime"]) for r in exits} == last_ids and len(exits) == len(last_ids)
        assert all(type(r["exit_code"]) is int and r["exit_code"] != 259 for r in exits)
        assert next(r for r in exits if r["pid"] == worker["pid"])["exit_code"] == (0 if case["name"] == "threaded_samples" else 0xE003)
        assert result["handles_closed"] is True and result["native_errors"] == []
        raw = (directory / "trace.jsonl").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == case["trace_sha256"]
        if case["name"] != "partial_write":
            frozen.audit_trace(raw, case, protocol)
        else:
            state = result["ledger"]
            prefix = b"".join((json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False)+"\n").encode() for r in state["records"])
            assert state["committed_rows"] == len(state["records"]) == 1
            assert state["committed_bytes"] == len(prefix) and raw == prefix + b'{"emi'
            assert state["records"][0]["kind"] == "started" and state["records"][0]["seq"] == 0
            assert {k: state["records"][0][k] for k in worker} == worker
            assert result["trace_complete"] is False and state["poisoned"] is True
            assert result["trace_error"] == {"kind": "sample", "error_type": "LedgerIOError"}
            assert case["later_sampling_refused"] is True and case["write_calls"] == 2
            assert case["expected_error"] == "LedgerIOError"
            failure = state["failure"]
            assert failure["seq"] == 1 and failure["stage"] == "write" and failure["error_type"] == "OSError"
            assert failure["write_return"] is None and failure["flush_completed"] is False
            assert failure["sink_may_have_uncommitted_bytes"] is True and failure["row_bytes"] > 5
        total_exits += len(exits)
        total_rows += result["ledger"]["committed_rows"]
    return {"preservation_passed": True, "frozen_acceptance": False,
        "producer_cases_passed": 4, "retained_exits": total_exits, "committed_rows": total_rows,
        "model_loads": 0, "optimizer_updates": 0,
        "mismatches": ["Sorted JSON sample starts with emitted_perf_counter; actual five-byte tail is {\"emi, frozen literal is {\"kin.",
            "Injected Python has its own retained conhost child; policy rejects both, frozen auditor expects only three nodes and direct worker parents."],
        "scope": "Post-outcome saved-byte preservation by same agent; not preregistered acceptance, independent live execution, model quality or performance"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name, default in [("output", "results/observed-job-v2/raw"), ("protocol", "fixtures/observed-job-v2/protocol.json"),
        ("freeze", "fixtures/observed-job-v2/implementation.json"), ("root", ".")]:
        parser.add_argument("--" + name, type=Path, default=Path(default))
    args = parser.parse_args()
    print(json.dumps(check(args.output, args.protocol, args.freeze, args.root)))
