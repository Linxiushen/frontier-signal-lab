"""One frozen Windows-only, stdlib engineering acceptance for process observer.

No real child process is launched by importing this module or running its unit
tests. The acceptance CLI requires an implementation freeze and a fresh output.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import process_observer as obs

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
SOURCE_PATHS = ("experiments/process_observer.py", "experiments/process_observer_probe.py", "tests/test_process_observer.py")
CONFIG = {"maximum_explicit_allocation_bytes_per_process": 67108864,
    "healthy_allocation_bytes": 33554432, "cap_control_allocation_bytes": 67108864,
    "actual_private_cap_increment_bytes": 50331648, "memory_comparison_tolerance_bytes": 4194304,
    "minimum_32mib_resident_and_private_increase_bytes": 25165824,
    "minimum_64mib_resident_and_private_increase_bytes": 58720256,
    "sampler_interval_seconds": 0.02, "maximum_cap_detection_seconds": 1.0,
    "handshake_timeout_seconds": 8.0, "barrier_timeout_seconds": 8.0,
    "healthy_completion_timeout_seconds": 8.0, "timeout_control_seconds": 1.5,
    "cleanup_timeout_seconds": 4.0, "total_timeout_seconds": 90.0, "maximum_json_bytes": 1048576}
CASES = (("healthy32", 33554432, "healthy"), ("healthy64", 67108864, "healthy"),
    ("private_cap64", 67108864, "private_cap"), ("timeout_descendant", 0, "timeout"),
    ("job_close_descendant", 0, "job_close"))


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def public_error(error, *private_paths):
    message = type(error).__name__ + ": " + str(error)
    for path in sorted([str(ROOT), *(str(p) for p in private_paths)], key=len, reverse=True):
        if path:
            message = message.replace(path, "<local-path>")
    return message


def envelope(nonce, role, **fields):
    obs.validate_nonce(nonce)
    return {"nonce": nonce, "role": role, "pid": os.getpid(), **fields}


def control(directory, filename, nonce, command):
    obs.write_new(Path(directory) / filename, envelope(nonce, "controller", command=command))


def wait_json(path, deadline, nonce, role, *, poll=None, clock=time.perf_counter, sleep=time.sleep):
    path = Path(path)
    while True:
        if clock() >= deadline:
            raise obs.ObserverError("message deadline exceeded: " + path.name)
        if path.exists():
            return obs.validate_message(obs.read_small(path), nonce, role)
        if poll is not None:
            poll()
        for name in ("worker-failure.json", "descendant-failure.json"):
            failure = path.parent / name
            if failure.exists():
                payload = obs.read_small(failure)
                raise obs.ObserverError("child failure: " + str(payload.get("error", "unspecified")))
        sleep(CONFIG["sampler_interval_seconds"])


def wait_control(directory, filename, nonce, expected):
    message = wait_json(Path(directory) / filename, time.perf_counter() + CONFIG["barrier_timeout_seconds"], nonce, "controller")
    if message.get("command") != expected:
        raise obs.ObserverError("wrong barrier command: " + filename)
    return message


def publish_identity(backend, directory, filename, nonce, role):
    payload = envelope(nonce, role, parent_pid=os.getppid(), **backend.self_reading())
    payload["runtime_executable_basename"] = Path(sys.executable).name
    payload["runtime_executable_sha256"] = obs.sha256_file(sys.executable)
    obs.write_new(Path(directory) / filename, payload)


def worker_checkpoint(backend, directory, stage, nonce):
    obs.write_new(Path(directory) / (stage + "-before.json"), envelope(nonce, "worker", **backend.self_reading()))
    wait_control(directory, stage + "-parent-done.json", nonce, "parent-sampled")
    obs.write_new(Path(directory) / (stage + "-after.json"), envelope(nonce, "worker", **backend.self_reading()))
    wait_control(directory, stage + "-continue.json", nonce, "continue")


def descendant_worker(directory, nonce):
    backend = obs.WindowsBackend()
    try:
        publish_identity(backend, directory, "descendant-ready.json", nonce, "descendant")
        wait_control(directory, "descendant-finish.json", nonce, "finish")
    except BaseException as error:
        obs.write_new(Path(directory) / "descendant-failure.json", envelope(nonce, "descendant", error=public_error(error, directory, sys.executable)))
        raise


def main_worker(directory, nonce, descendant_nonce, count, mode):
    backend, allocation = obs.WindowsBackend(), None
    try:
        publish_identity(backend, directory, "worker-ready.json", nonce, "worker")
        wait_control(directory, "create-descendant.json", nonce, "create-descendant")
        # The child inherits job membership, but no handle to the job itself.
        child = subprocess.Popen([sys.executable, "-S", str(SCRIPT), "--descendant", "--directory", str(directory),
            "--nonce", descendant_nonce], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True, creationflags=0x08000000)
        obs.write_new(Path(directory) / "descendant-launcher.json", envelope(nonce, "worker", launcher_pid=child.pid))
        wait_control(directory, "begin-memory.json", nonce, "begin-memory")
        worker_checkpoint(backend, directory, "baseline", nonce)
        allocation = backend.allocate(count)
        worker_checkpoint(backend, directory, "allocated", nonce)
        if mode == "healthy":
            control(directory, "descendant-finish.json", descendant_nonce, "finish")
            code = child.wait(timeout=CONFIG["healthy_completion_timeout_seconds"])
            if code != 0:
                raise obs.ObserverError("healthy descendant launcher returned nonzero")
            backend.free(allocation)
            allocation = None
            obs.write_new(Path(directory) / "worker-completed.json", envelope(nonce, "worker",
                completed_at=utc_now(), descendant_launcher_returncode=code, explicit_allocation_bytes=count))
            return
        if mode not in ("timeout", "job_close"):
            raise obs.ObserverError("cap worker should be terminated while held at allocated barrier")
        obs.write_new(Path(directory) / "stalled.json", envelope(nonce, "worker", perf_counter=time.perf_counter()))
        # Finite internal backstop; parent must kill the job long before it expires.
        time.sleep(30)
        raise obs.ObserverError("termination control was not enforced")
    except BaseException as error:
        obs.write_new(Path(directory) / "worker-failure.json", envelope(nonce, "worker", error=public_error(error, directory, sys.executable)))
        raise
    finally:
        backend.free(allocation)


def validate_freeze(protocol_path, freeze_path, python_path):
    protocol, freeze = obs.read_small(protocol_path), obs.read_small(freeze_path)
    if protocol.get("config") != CONFIG or tuple(protocol.get("source_paths", ())) != SOURCE_PATHS:
        raise obs.ObserverError("protocol config/source paths differ from implementation")
    cases = [(c.get("id"), c.get("allocation_bytes"), c.get("mode")) for c in protocol.get("cases_in_order", [])]
    if cases != list(CASES):
        raise obs.ObserverError("protocol case order differs from implementation")
    if freeze.get("protocol_sha256") != obs.sha256_file(protocol_path):
        raise obs.ObserverError("protocol differs from implementation freeze")
    sources = freeze.get("new_source_files_sha256", {})
    if set(sources) != set(SOURCE_PATHS) or any(obs.sha256_file(ROOT / p) != sources[p] for p in SOURCE_PATHS):
        raise obs.ObserverError("source hashes differ from implementation freeze")
    if freeze.get("python_executable_sha256") != obs.sha256_file(python_path):
        raise obs.ObserverError("launch executable differs from implementation freeze")
    declared = dt.datetime.fromisoformat(protocol["predeclared_at"])
    frozen = dt.datetime.fromisoformat(freeze["frozen_at"])
    if declared.tzinfo is None or frozen.tzinfo is None or frozen < declared:
        raise obs.ObserverError("invalid protocol/freeze chronology")
    return protocol, freeze


def bracket(job, actual, directory, stage, nonce, samples, report, suite_deadline):
    deadline = min(suite_deadline, time.perf_counter() + CONFIG["barrier_timeout_seconds"])
    before = wait_json(directory / (stage + "-before.json"), deadline, nonce, "worker", poll=lambda: samples.append(actual.reading()))
    parent = actual.reading()
    samples.append(parent)
    control(directory, stage + "-parent-done.json", nonce, "parent-sampled")
    after = wait_json(directory / (stage + "-after.json"), deadline, nonce, "worker", poll=lambda: samples.append(actual.reading()))
    comparison = obs.compare_memory_bracket(before, parent, after, CONFIG["memory_comparison_tolerance_bytes"])
    receipt = {"self_before": before, "parent": parent, "self_after": after, "comparison": comparison}
    report.setdefault("memory_brackets", {})[stage] = receipt
    if not comparison["passed"]:
        raise obs.ObserverError("self/parent memory bracket failed: " + stage)
    job.member(actual)
    return receipt


def check_allocation(baseline, allocated, count):
    deltas = {key: allocated["parent"]["memory"][key] - baseline["parent"]["memory"][key]
              for key in ("resident_bytes", "private_bytes")}
    minimum = {0: 0, 33554432: CONFIG["minimum_32mib_resident_and_private_increase_bytes"],
               67108864: CONFIG["minimum_64mib_resident_and_private_increase_bytes"]}[count]
    return {"explicit_allocation_bytes": count, "parent_deltas_bytes": deltas,
            "minimum_required_increase_bytes": minimum,
            "passed": count == 0 or all(delta >= minimum for delta in deltas.values())}


def run_case(spec, python_path, output, suite_deadline):
    case_id, count, mode = spec
    directory = output / case_id
    directory.mkdir()
    nonce, descendant_nonce = secrets.token_hex(32), secrets.token_hex(32)
    report = {"id": case_id, "mode": mode, "started_at": utc_now(), "passed": False,
        "nonce": nonce, "descendant_nonce": descendant_nonce, "samples": [],
        "expected_explicit_allocation_bytes": count, "termination_path": None}
    job = None
    started = time.perf_counter()
    try:
        if started >= suite_deadline:
            raise obs.ObserverError("suite deadline exceeded before case")
        job = obs.WindowsJob()
        launcher = job.start_suspended([str(python_path), "-S", str(SCRIPT), "--worker", "--directory", str(directory),
            "--nonce", nonce, "--descendant-nonce", descendant_nonce, "--allocation-bytes", str(count), "--mode", mode], cwd=ROOT)
        report["launcher"] = {"pid": launcher.pid, "creation_filetime": launcher.creation_filetime,
            "assigned_while_suspended": True, "job_handle_inherited": False}
        handshake_deadline = min(suite_deadline, time.perf_counter() + CONFIG["handshake_timeout_seconds"])
        ready = wait_json(directory / "worker-ready.json", handshake_deadline, nonce, "worker")
        actual, ancestry = job.authenticate(ready, nonce, "worker", launcher)
        report["worker_identity"] = {"self_receipt": ready, "verified_ancestry": ancestry,
            "launcher_differs_from_interpreter": launcher.pid != actual.pid}
        control(directory, "create-descendant.json", nonce, "create-descendant")
        descendant_launch = wait_json(directory / "descendant-launcher.json", handshake_deadline, nonce, "worker")
        if descendant_launch["pid"] != actual.pid:
            raise obs.ObserverError("descendant launcher message is not from actual interpreter")
        descendant_launcher = job.retain(descendant_launch["launcher_pid"])
        job.member(descendant_launcher)
        desc_ready = wait_json(directory / "descendant-ready.json", handshake_deadline, descendant_nonce, "descendant")
        descendant, descendant_ancestry = job.authenticate(desc_ready, descendant_nonce, "descendant", actual)
        if descendant_launcher.pid not in [x["pid"] for x in descendant_ancestry]:
            raise obs.ObserverError("descendant ancestry omits its reported launcher")
        report["descendant_identity"] = {"self_receipt": desc_ready, "verified_ancestry": descendant_ancestry,
            "launcher_pid": descendant_launcher.pid, "actual_pid": descendant.pid}
        control(directory, "begin-memory.json", nonce, "begin-memory")
        baseline = bracket(job, actual, directory, "baseline", nonce, report["samples"], report, suite_deadline)
        private_limit = baseline["parent"]["memory"]["private_bytes"] + CONFIG["actual_private_cap_increment_bytes"]
        if mode == "private_cap":
            report["actual_interpreter_private_limit_bytes"] = private_limit
            report["cap_is_sampled_not_kernel_hard_ceiling"] = True
        control(directory, "baseline-continue.json", nonce, "continue")
        allocated = bracket(job, actual, directory, "allocated", nonce, report["samples"], report, suite_deadline)
        report["allocation_check"] = check_allocation(baseline, allocated, count)
        if not report["allocation_check"]["passed"]:
            raise obs.ObserverError("touched allocation did not produce declared resident/private increase")
        if mode == "private_cap":
            crossing = [s for s in report["samples"] if obs.memory_limit_crossed(s, private_limit)]
            if not crossing or not obs.memory_limit_crossed(allocated["parent"], private_limit):
                raise obs.ObserverError("actual interpreter private cap did not trigger")
            report["first_over_limit_sample"] = crossing[0]
            report["enforcement_reason"] = "memory_private_limit"
            report["termination_path"] = "TerminateJobObject"
            job.member(actual)
            job.member(descendant)
            report["termination_request_started_perf_counter"] = time.perf_counter()
            job.terminate()
            terminated_at = time.perf_counter()
            report["termination_request_returned_perf_counter"] = terminated_at
            report["allocation_ready_to_termination_seconds"] = terminated_at - allocated["self_before"]["perf_counter"]
            if not 0 <= report["allocation_ready_to_termination_seconds"] <= CONFIG["maximum_cap_detection_seconds"]:
                raise obs.ObserverError("memory enforcement exceeded declared1s ready-to-termination bound")
            report["cleanup"] = job.cleanup_receipt(CONFIG["cleanup_timeout_seconds"], require_zero=True)
        else:
            control(directory, "allocated-continue.json", nonce, "continue")
            if mode == "healthy":
                deadline = min(suite_deadline, time.perf_counter() + CONFIG["healthy_completion_timeout_seconds"])
                report["healthy_completion"] = wait_json(directory / "worker-completed.json", deadline, nonce, "worker")
                report["cleanup"] = job.cleanup_receipt(max(0, min(CONFIG["cleanup_timeout_seconds"], deadline - time.perf_counter())), require_zero=True)
                if any(item["exit_code"] != 0 for item in report["cleanup"]["exit_codes"]):
                    raise obs.ObserverError("healthy process had nonzero exit status")
                report["enforcement_reason"] = "normal_completion"
            else:
                stalled = wait_json(directory / "stalled.json", min(suite_deadline, time.perf_counter() + CONFIG["barrier_timeout_seconds"]), nonce, "worker")
                report["stalled_receipt"] = stalled
                if mode == "timeout":
                    control_start = time.perf_counter()
                    deadline = control_start + CONFIG["timeout_control_seconds"]
                    while time.perf_counter() < deadline:
                        if time.perf_counter() >= suite_deadline or not actual.alive() or not descendant.alive():
                            raise obs.ObserverError("timeout control exited early or suite expired")
                        report["samples"].append(actual.reading())
                        time.sleep(CONFIG["sampler_interval_seconds"])
                    control_completed = time.perf_counter()
                    report["timeout_control_started_perf_counter"] = control_start
                    report["timeout_control_completed_perf_counter"] = control_completed
                    report["timeout_deadline_perf_counter"] = deadline
                    report["timeout_wait_seconds"] = control_completed - control_start
                    report["enforcement_reason"] = "timeout"
                    report["termination_path"] = "TerminateJobObject"
                    job.member(actual)
                    job.member(descendant)
                    report["termination_request_started_perf_counter"] = time.perf_counter()
                    job.terminate()
                    report["termination_request_returned_perf_counter"] = time.perf_counter()
                    report["cleanup"] = job.cleanup_receipt(CONFIG["cleanup_timeout_seconds"], require_zero=True)
                elif mode == "job_close":
                    report["enforcement_reason"] = "explicit_job_handle_close_control"
                    report["termination_path"] = "KILL_ON_JOB_CLOSE; no TerminateJobObject"
                    job.member(actual)
                    job.member(descendant)
                    report["job_close_started_perf_counter"] = time.perf_counter()
                    job.close()
                    report["job_close_returned_perf_counter"] = time.perf_counter()
                    report["cleanup"] = job.cleanup_receipt(CONFIG["cleanup_timeout_seconds"], require_zero=False)
                    report["cleanup"]["job_active_count_after_close_not_queryable"] = True
                else:
                    raise obs.ObserverError("unknown case mode")
        report["passed"] = True
    except BaseException as error:
        report["error"] = public_error(error, directory, python_path, output)
        if job is not None:
            try:
                if job.handle is not None:
                    job.terminate()
                    report["failure_cleanup"] = job.cleanup_receipt(CONFIG["cleanup_timeout_seconds"], require_zero=True)
                else:
                    report["failure_cleanup"] = job.cleanup_receipt(CONFIG["cleanup_timeout_seconds"], require_zero=False)
            except BaseException as cleanup_error:
                report["cleanup_error"] = public_error(cleanup_error, directory, python_path, output)
    finally:
        if job is not None:
            try:
                job.close()
            except BaseException as error:
                report["passed"] = False
                report["job_close_error"] = public_error(error)
            try:
                job.close_refs()
            except BaseException as error:
                report["passed"] = False
                report["process_handle_close_error"] = public_error(error)
        report["completed_at"] = utc_now()
        report["wall_seconds"] = time.perf_counter() - started
        obs.write_new(directory / "case-report.json", report)
    return report


def acceptance(python_path, protocol_path, freeze_path, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = {"schema_version": 1, "experiment_id": "windows-interpreter-observer-engineering-v1",
        "kind": "stdlib engineering acceptance; no model or scientific run", "started_at": utc_now(),
        "passed": False, "cases": [], "platform": platform.platform(), "os_name": os.name,
        "python_version": platform.python_version(), "no_fallback": True,
        "limitations": ["Sampled private-byte termination is not a kernel hard ceiling or continuous/peak measurement.",
            "One-host Windows controlled payloads and cooperative descendants only; no adversarial escape proof.",
            "Historical activation-cost observer/results are unchanged; passing does not repair their memory measurements.",
            "No model/training/runtime-cost/quality claim; no Linux evidence substituted for Windows."]}
    try:
        protocol, freeze = validate_freeze(protocol_path, freeze_path, python_path)
        report.update(protocol_sha256=obs.sha256_file(protocol_path), implementation_sha256=obs.sha256_file(freeze_path),
            source_sha256=freeze["new_source_files_sha256"], launch_executable_basename=Path(python_path).name,
            launch_executable_sha256=obs.sha256_file(python_path), protocol_predeclared_at=protocol["predeclared_at"],
            implementation_frozen_at=freeze["frozen_at"])
        if os.name != "nt":
            raise obs.UnsupportedPlatform("Windows acceptance not executed; unsupported platform, no fallback")
        suite_deadline = started + CONFIG["total_timeout_seconds"]
        for spec in CASES:
            report["cases"].append(run_case(spec, Path(python_path).resolve(), output, suite_deadline))
        report["passed"] = (len(report["cases"]) == len(CASES) and all(c["passed"] for c in report["cases"])
                            and time.perf_counter() <= suite_deadline)
    except BaseException as error:
        report["error"] = public_error(error, python_path, output, protocol_path, freeze_path)
    report["completed_at"] = utc_now()
    report["wall_seconds"] = time.perf_counter() - started
    obs.write_new(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--descendant", action="store_true")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--nonce")
    parser.add_argument("--descendant-nonce")
    parser.add_argument("--allocation-bytes", type=int)
    parser.add_argument("--mode", choices=("healthy", "private_cap", "timeout", "job_close"))
    args = parser.parse_args(argv)
    if args.worker and args.descendant:
        parser.error("worker and descendant modes are mutually exclusive")
    if args.worker or args.descendant:
        if args.directory is None or args.nonce is None:
            parser.error("worker modes require directory and nonce")
        if args.descendant:
            descendant_worker(args.directory, args.nonce)
        else:
            if args.descendant_nonce is None or args.allocation_bytes is None or args.mode is None:
                parser.error("main worker requires descendant nonce, allocation and mode")
            main_worker(args.directory, args.nonce, args.descendant_nonce, args.allocation_bytes, args.mode)
        return 0
    if any(x is None for x in (args.python, args.protocol, args.freeze, args.output)):
        parser.error("acceptance requires python, protocol, freeze and fresh output")
    result = acceptance(args.python, args.protocol, args.freeze, args.output)
    print("process observer engineering acceptance: " + ("passed" if result["passed"] else "FAILED"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
