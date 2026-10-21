"""Frozen native acceptance for the ledger adapter; stdlib, no ML imports."""
import argparse
import ctypes as ct
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import process_observer as native
from experiments.observed_job import ObservedWindowsJob
from experiments.trace_ledger import BoundedJSONLLedger, LedgerIOError, LedgerLimitError

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("experiments/observed_job.py", "experiments/observed_job_probe.py",
    "experiments/process_observer.py", "experiments/trace_ledger.py",
    "tests/test_observed_job.py", "scripts/audit_observed_job.py")


def worker(directory, nonce, seconds):
    backend = native.WindowsBackend()
    ready = {**backend.self_reading(), "parent_pid": os.getppid(), "nonce": nonce,
        "executable_sha256": native.sha256_file(sys.executable)}
    native.write_new(directory / "ready.json", ready)
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        if (directory / "stop.json").exists():
            stop = native.read_small(directory / "stop.json")
            if stop != {"nonce": nonce, "command": "stop"}:
                raise RuntimeError("Wrong stop identity")
            native.write_new(directory / "finished.json", backend.self_reading())
            return
        time.sleep(0.01)
    raise TimeoutError("Worker backstop")


def image(job, ref):
    query = job.backend.k.QueryFullProcessImageNameW
    query.argtypes = [native.HANDLE, native.DWORD, ct.c_wchar_p, ct.POINTER(native.DWORD)]
    query.restype = native.BOOL
    buffer, size = ct.create_unicode_buffer(32768), native.DWORD(32768)
    job.backend.checked(query(ref.handle, 0, buffer, ct.byref(size)), "QueryFullProcessImageNameW")
    assert os.path.normcase(os.path.realpath(buffer.value)) == os.path.normcase(os.path.realpath(sys.executable))
    return native.sha256_file(buffer.value)


class FileSink:
    def __init__(self, stream, fault):
        self.stream, self.fault, self.writes = stream, fault, 0

    def write(self, data):
        self.writes += 1
        if self.fault and self.writes == 2:
            self.stream.write(data[:5]); self.stream.flush()
            raise OSError("Preregistered partial diagnostic write")
        return self.stream.write(data)

    def flush(self):
        self.stream.flush()


def run_case(name, output, protocol, suite_deadline):
    directory = output / name; directory.mkdir()
    nonce = secrets.token_hex(32)
    limits = dict(protocol["limits"])
    if name == "row_cap": limits["max_rows"] = 1
    record = {"name": name, "nonce": nonce, "parent_pid": os.getpid(), "error": None}
    with (directory / "trace.jsonl").open("xb") as stream:
        sink = FileSink(stream, name == "partial_write")
        session = ObservedWindowsJob(BoundedJSONLLedger(sink, **limits))
        try:
            ref = session.start([sys.executable, "-S", "-B", str(Path(__file__).resolve()),
                "--worker", str(directory), nonce, str(protocol["worker_backstop_seconds"])], cwd=ROOT)
            deadline = min(suite_deadline, time.perf_counter() + protocol["handshake_seconds"])
            while not (directory / "ready.json").exists():
                if time.perf_counter() >= deadline: raise TimeoutError("Worker ready")
                time.sleep(0.01)
            ready = native.read_small(directory / "ready.json")
            record["ready"] = ready
            record["native_identity"] = {"pid": ref.pid, "creation_filetime": ref.creation_filetime,
                "parent_pid": session.job.backend.snapshot().get(ref.pid),
                "image_sha256": image(session.job, ref), "job_active_count": session.job.active_count(),
                "job_member": session.job.member(ref)}
            identity = record["native_identity"]
            assert ready["nonce"] == nonce and ready["pid"] == ref.pid
            assert ready["creation_filetime"] == ref.creation_filetime
            assert identity["parent_pid"] == ready["parent_pid"] == os.getpid()
            assert identity["image_sha256"] == ready["executable_sha256"] == native.sha256_file(sys.executable)
            assert identity["job_active_count"] == 1 and identity["job_member"] is True
            if name == "threaded_samples":
                barrier = threading.Barrier(protocol["sampler_threads"])
                errors, ids = [], []
                def sample(worker_id):
                    try:
                        ids.append(threading.get_native_id())
                        barrier.wait(protocol["thread_join_seconds"])
                        for index in range(protocol["samples_per_thread"]):
                            session.sample(f"{worker_id}:{index}")
                    except BaseException as error: errors.append(type(error).__name__)
                threads = [threading.Thread(target=sample, args=(i,), daemon=True)
                    for i in range(protocol["sampler_threads"])]
                for thread in threads: thread.start()
                for thread in threads:
                    thread.join(max(0, min(protocol["thread_join_seconds"], suite_deadline - time.perf_counter())))
                assert not errors and all(not t.is_alive() for t in threads), errors
                record["sampler_native_thread_ids"] = ids
                native.write_new(directory / "stop.json", {"nonce": nonce, "command": "stop"})
                while ref.alive():
                    if time.perf_counter() >= deadline: raise TimeoutError("Healthy worker exit")
                    time.sleep(0.01)
            else:
                expected = LedgerLimitError if name == "row_cap" else LedgerIOError
                try: session.sample("rejected-sample")
                except expected as error: record["expected_error"] = type(error).__name__
                else: raise AssertionError("Sink control did not reject")
                writes = sink.writes
                try: session.sample("forbidden-retry")
                except native.ObserverError: record["later_sampling_refused"] = True
                else: raise AssertionError("Failed trace was reused")
                assert sink.writes == writes
        except BaseException as error:
            record["error"] = type(error).__name__ + ": " + str(error)
        finally:
            try: record["shutdown"] = session.shutdown(protocol["cleanup_seconds"])
            except BaseException as error: record["shutdown_error"] = type(error).__name__ + ": " + str(error)
            record["write_calls"] = sink.writes
    record["trace_sha256"] = native.sha256_file(directory / "trace.jsonl")
    record["passed"] = record["error"] is None and "shutdown_error" not in record
    native.write_new(directory / "result.json", record)
    return record


def run(protocol_path, freeze_path, output):
    protocol, freeze = native.read_small(protocol_path), native.read_small(freeze_path)
    assert protocol["id"] == "native-observer-ledger-integration-v1"
    assert freeze["protocol_sha256"] == native.sha256_file(protocol_path)
    assert freeze["output_directory"] == output.relative_to(ROOT).as_posix()
    assert freeze["source_sha256"] == {p: native.sha256_file(ROOT / p) for p in SOURCES}
    assert freeze["python_executable_sha256"] == native.sha256_file(sys.executable)
    started = datetime.now(timezone.utc)
    assert datetime.fromisoformat(freeze["frozen_at"]) < started
    output.mkdir(exist_ok=False)
    report = {"started_at": started.isoformat(), "protocol_sha256": native.sha256_file(protocol_path),
        "freeze_sha256": native.sha256_file(freeze_path), "python_executable_sha256": native.sha256_file(sys.executable),
        "cases": [], "scientific_experiments": 0, "model_loads": 0, "optimizer_updates": 0}
    deadline = time.perf_counter() + protocol["suite_seconds"]
    for name in protocol["cases"]:
        if time.perf_counter() >= deadline: raise TimeoutError("Suite deadline")
        case = run_case(name, output, protocol, deadline)
        report["cases"].append(case)
        if not case["passed"]: break
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = len(report["cases"]) == len(protocol["cases"]) and all(c["passed"] for c in report["cases"]) and time.perf_counter() < deadline
    native.write_new(output / "report.json", report)
    print(json.dumps({"passed": report["passed"], "cases": [(c["name"], c["passed"]) for c in report["cases"]]}))
    return report["passed"]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(Path(sys.argv[2]), sys.argv[3], float(sys.argv[4]))
    else:
        parser = argparse.ArgumentParser()
        parser.add_argument("--protocol", type=Path, required=True)
        parser.add_argument("--freeze", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args()
        raise SystemExit(0 if run(args.protocol.resolve(), args.freeze.resolve(), args.output.resolve()) else 1)
