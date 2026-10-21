"""Native ledger integration with retained direct-worker/console admission.

This separately frozen version preserves the rejected v1. It reuses the same
adapter, native observer and ledger. Only the CLI launches stdlib workers; import
and pure policy controls do not launch processes or load models.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import traceback

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import dual_identity_census as dual
from experiments import process_observer as native
from experiments.observed_job import ObservedWindowsJob
from experiments.observed_job_probe import FileSink
from experiments.trace_ledger import BoundedJSONLLedger, LedgerIOError, LedgerLimitError

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "experiments/observed_job_probe_v2.py", "experiments/observed_job.py",
    "experiments/observed_job_probe.py", "experiments/process_observer.py",
    "experiments/trace_ledger.py", "experiments/dual_identity_census.py",
    "experiments/process_observer_probe.py", "experiments/workload_observer_probe.py",
    "tests/test_observed_job_v2.py", "scripts/audit_observed_job_v2.py",
)


def image_matches(node, role, paths, hashes):
    image = node.get("image", {})
    return (node.get("job_member") is True and node.get("alive") is True
        and image.get("queried_from_retained_handle") is True
        and image.get("retained_identity_stable") is True
        and image.get("basename", "").lower() == paths[role].name.lower()
        and image.get("sha256") == hashes[role]
        and image.get("normalized_path_sha256") == dual.path_hash(paths[role])
        and role in image.get("exact_path_matches", []) and not node.get("error"))


def decide(snapshot, worker_ref, parent_pid, paths, hashes, pin=None):
    """Admit one exact direct worker and one exact, identity-pinned conhost.

    File recognition cannot register another Python process. A complete bounded
    inventory is required at both held stages, not continuous isolation.
    """
    nodes = snapshot.get("processes", [])
    by_pid = {n["pid"]: n for n in nodes}
    errors, approved, proposed = [], set(), None
    if (snapshot.get("census_complete") is not True or snapshot.get("errors")
        or len(by_pid) != len(nodes) or set(by_pid) != set(snapshot.get("observed_pids", []))
        or snapshot.get("job_count_before") != len(nodes) or snapshot.get("job_count_after") != len(nodes)):
        errors.append("incomplete_inventory")
    worker = by_pid.get(worker_ref["pid"], {})
    if (worker.get("creation_filetime") == worker_ref["creation_filetime"]
        and worker.get("parent_pid") == parent_pid and worker.get("approved_known") is True
        and image_matches(worker, "worker", paths, hashes)):
        approved.add(worker_ref["pid"])
    else:
        errors.append("direct_worker_identity")
    auxiliaries = [n for n in nodes if n["pid"] != worker_ref["pid"]
        and n.get("parent_pid") == worker_ref["pid"]
        and type(n.get("creation_filetime")) is int
        and n["creation_filetime"] >= worker_ref["creation_filetime"]
        and image_matches(n, "conhost", paths, hashes)]
    if len(auxiliaries) != 1:
        errors.append("console_cardinality")
    else:
        auxiliary = auxiliaries[0]
        proposed = {"owner": dict(worker_ref), "auxiliary": {
            "pid": auxiliary["pid"], "creation_filetime": auxiliary["creation_filetime"]}}
        if pin is not None and proposed != pin:
            errors.append("console_identity_replaced")
        elif worker_ref["pid"] in approved:
            approved.add(auxiliary["pid"])
    rejected = sorted(set(by_pid) - approved)
    if rejected:
        errors.append("unregistered_process_identity")
    return {"label": snapshot["label"], "admitted": not errors,
        "errors": errors, "admitted_pids": sorted(approved), "rejected_pids": rejected,
        "pin": copy.deepcopy(proposed), "training_permitted": False}


def worker(directory, nonce, seconds, helper=False):
    backend = native.WindowsBackend()
    ready = {**backend.self_reading(), "parent_pid": os.getppid(), "nonce": nonce,
        "executable_sha256": native.sha256_file(sys.executable)}
    native.write_new(directory / ("helper-ready.json" if helper else "ready.json"), ready)
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if not helper and (directory / "inject.json").exists() and not (directory / "helper-launch.json").exists():
            assert native.read_small(directory / "inject.json") == {"nonce": nonce, "command": "inject"}
            child = subprocess.Popen([sys.executable, "-S", "-B", str(Path(__file__).resolve()),
                "--helper", str(directory), nonce, str(seconds)], close_fds=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000, shell=False)
            native.write_new(directory / "helper-launch.json", {"nonce": nonce, "pid": child.pid})
        if not helper and (directory / "stop.json").exists():
            assert native.read_small(directory / "stop.json") == {"nonce": nonce, "command": "stop"}
            native.write_new(directory / "finished.json", backend.self_reading())
            return
        time.sleep(0.01)
    raise TimeoutError("Stdlib worker backstop")


def wait_file(path, end):
    while not path.exists():
        if time.perf_counter() >= end:
            raise TimeoutError("Waiting for " + path.name)
        time.sleep(0.01)
    if time.perf_counter() >= end:
        raise TimeoutError("Expired handshake: " + path.name)
    return native.read_small(path)


def run_case(name, output, protocol, paths, hashes, suite_end):
    directory = output / name
    directory.mkdir()
    started = time.perf_counter()
    case_end = min(suite_end, started + protocol["case_seconds"])
    nonce = secrets.token_hex(32)
    limits = dict(protocol["limits"])
    if name == "row_cap":
        limits["max_rows"] = 1
    record = {"name": name, "nonce": nonce, "parent_pid": os.getpid(), "error": None,
        "started_perf_counter": started, "censuses": [], "decisions": []}
    with (directory / "trace.jsonl").open("xb") as stream:
        sink = FileSink(stream, name == "partial_write")
        session = ObservedWindowsJob(BoundedJSONLLedger(sink, **limits))
        try:
            ref = session.start([sys.executable, "-S", "-B", str(Path(__file__).resolve()),
                "--worker", str(directory), nonce, str(protocol["worker_backstop_seconds"])], cwd=ROOT)
            record["worker_ref"] = {"pid": ref.pid, "creation_filetime": ref.creation_filetime}
            ready = wait_file(directory / "ready.json", min(case_end, time.perf_counter() + protocol["handshake_seconds"]))
            record["ready"] = ready
            assert ready["nonce"] == nonce and ready["pid"] == ref.pid
            assert ready["creation_filetime"] == ref.creation_filetime
            assert ready["parent_pid"] == os.getpid() and ready["executable_sha256"] == hashes["worker"]
            known = {ref.pid: (ref.creation_filetime, "worker")}
            def stage(label, pin=None):
                inventory = dual.census(session.job, ref, known, paths, hashes, paths["conhost"].parent,
                    record, label, case_end, suite_end)
                decision = decide(inventory, record["worker_ref"], os.getpid(), paths, hashes, pin)
                record["decisions"].append(decision)
                return decision
            initial = stage("before_sampling")
            assert initial["admitted"], initial
            if name == "threaded_samples":
                barrier = threading.Barrier(protocol["sampler_threads"])
                failures, ids = [], []
                def sample(worker_id):
                    try:
                        ids.append(threading.get_native_id())
                        barrier.wait(protocol["thread_join_seconds"])
                        for index in range(protocol["samples_per_thread"]):
                            session.sample(f"{worker_id}:{index}")
                    except BaseException as error:
                        failures.append(type(error).__name__)
                threads = [threading.Thread(target=sample, args=(i,), daemon=True)
                    for i in range(protocol["sampler_threads"])]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(max(0, min(protocol["thread_join_seconds"], case_end - time.perf_counter())))
                record["sampler_native_thread_ids"] = ids
                assert not failures and all(not t.is_alive() for t in threads), failures
            elif name == "unregistered_python":
                native.write_new(directory / "inject.json", {"nonce": nonce, "command": "inject"})
                launch = wait_file(directory / "helper-launch.json", case_end)
                helper = wait_file(directory / "helper-ready.json", case_end)
                record["helper_launch"], record["helper_ready"] = launch, helper
                assert launch["nonce"] == helper["nonce"] == nonce
                assert launch["pid"] == helper["pid"] and helper["parent_pid"] == ref.pid
                assert helper["executable_sha256"] == hashes["worker"]
            else:
                expected = LedgerLimitError if name == "row_cap" else LedgerIOError
                try:
                    session.sample("rejected-sample")
                except expected as error:
                    record["expected_error"] = type(error).__name__
                else:
                    raise AssertionError("Diagnostic control did not refuse")
                writes = sink.writes
                try:
                    session.sample("forbidden-retry")
                except native.ObserverError:
                    record["later_sampling_refused"] = True
                else:
                    raise AssertionError("Failed trace reused")
                assert sink.writes == writes
            final = stage("before_cleanup", initial["pin"])
            if name == "unregistered_python":
                helper = record["helper_ready"]
                node = next(n for n in record["censuses"][-1]["processes"] if n["pid"] == helper["pid"])
                assert node["creation_filetime"] == helper["creation_filetime"]
                assert image_matches(node, "worker", paths, hashes) and node["approved_known"] is False
                assert not final["admitted"] and helper["pid"] in final["rejected_pids"]
                assert final["errors"] == ["unregistered_process_identity"]
                record["same_image_rejection"] = True
            else:
                assert final["admitted"], final
            record["work_completed_perf_counter"] = time.perf_counter()
            assert record["work_completed_perf_counter"] < case_end
            if name == "threaded_samples":
                native.write_new(directory / "stop.json", {"nonce": nonce, "command": "stop"})
                while ref.alive():
                    if time.perf_counter() >= case_end:
                        raise TimeoutError("Healthy worker exit")
                    time.sleep(0.01)
                record["finished"] = native.read_small(directory / "finished.json")
        except BaseException as error:
            record["error"] = type(error).__name__ + ": " + str(error)
            record["error_traceback"] = traceback.format_exc()
        finally:
            try:
                record["shutdown"] = session.shutdown(protocol["cleanup_seconds"])
            except BaseException as error:
                record["shutdown_error"] = type(error).__name__ + ": " + str(error)
            record["write_calls"] = sink.writes
    record["trace_sha256"] = native.sha256_file(directory / "trace.jsonl")
    record["completed_perf_counter"] = time.perf_counter()
    record["passed"] = record["error"] is None and "shutdown_error" not in record and record["completed_perf_counter"] < case_end
    native.write_new(directory / "result.json", record)
    return record


def run(protocol_path, freeze_path, output):
    protocol, freeze = native.read_small(protocol_path), native.read_small(freeze_path)
    assert protocol["id"] == "native-observer-ledger-integration-v2"
    assert freeze["actual_suites_permitted"] == 1 and freeze["retries"] == 0
    assert freeze["model_loads_permitted"] == 0
    assert freeze["protocol_sha256"] == native.sha256_file(protocol_path)
    assert freeze["output_directory"] == output.relative_to(ROOT).as_posix()
    assert freeze["source_sha256"] == {p: native.sha256_file(ROOT / p) for p in SOURCES}
    paths = {"worker": Path(sys.executable), "conhost": Path(os.environ["SystemRoot"]) / "System32" / "conhost.exe"}
    hashes = {k: native.sha256_file(p) for k, p in paths.items()}
    assert hashes == freeze["executables_sha256"]
    assert {k: dual.path_hash(p) for k, p in paths.items()} == freeze["executable_path_sha256"]
    started = datetime.now(timezone.utc)
    assert datetime.fromisoformat(freeze["frozen_at"]) < started
    output.mkdir(exist_ok=False)
    report = {"started_at": started.isoformat(), "protocol_sha256": native.sha256_file(protocol_path),
        "freeze_sha256": native.sha256_file(freeze_path), "executables_sha256": hashes,
        "cases": [], "scientific_experiments": 0, "model_loads": 0, "optimizer_updates": 0}
    suite_end = time.perf_counter() + protocol["suite_seconds"]
    for name in protocol["cases"]:
        assert time.perf_counter() < suite_end, "Suite deadline"
        case = run_case(name, output, protocol, paths, hashes, suite_end)
        report["cases"].append(case)
        if not case["passed"]:
            break
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = len(report["cases"]) == len(protocol["cases"]) and all(c["passed"] for c in report["cases"]) and time.perf_counter() < suite_end
    native.write_new(output / "report.json", report)
    print(json.dumps({"passed": report["passed"], "cases": [(c["name"], c["passed"]) for c in report["cases"]]}))
    return report["passed"]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--worker", "--helper"):
        worker(Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]), sys.argv[1] == "--helper")
    else:
        parser = argparse.ArgumentParser()
        for name in ("protocol", "freeze", "output"):
            parser.add_argument("--" + name, type=Path, required=True)
        args = parser.parse_args()
        raise SystemExit(0 if run(args.protocol.resolve(), args.freeze.resolve(), args.output.resolve()) else 1)
