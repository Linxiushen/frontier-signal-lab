"""Frozen-observer integration with bounded CPU Torch engineering controls.

Import and unit tests start no child and never import Torch. Only the frozen
acceptance CLI creates Windows jobs; only an authenticated/released child loads
site/Torch. Historical observer and scientific probes are imported unchanged.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import datetime as dt
import importlib
import math
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
from experiments import process_observer_probe as base

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
SOURCE_PATHS = ("experiments/workload_observer_probe.py", "tests/test_workload_observer.py")
DEPENDENCY_PATHS = ("experiments/process_observer.py", "experiments/process_observer_probe.py",
    "fixtures/process-observer/protocol.json", "fixtures/process-observer/implementation.json")
CONFIG = {"torch_version": "2.9.1+cpu", "intraop_threads": 2, "interop_threads": 2,
    "matrix_dimension": 1024, "manual_allocation_maximum_bytes": 67108864,
    "private_cap_increment_bytes": 50331648, "healthy32_minimum_delta_bytes": 25165824,
    "healthy64_minimum_delta_bytes": 58720256, "memory_bracket_tolerance_bytes": 4194304,
    "sampler_interval_seconds": 0.02, "maximum_recorded_sample_gap_seconds": 0.5,
    "handshake_timeout_seconds": 5.0, "import_workload_timeout_seconds": 12.0,
    "barrier_timeout_seconds": 5.0, "busy_timeout_seconds": 1.5,
    "busy_timeout_minimum_cpu_seconds": 0.25, "busy_backstop_seconds": 10.0,
    "cap_ready_to_termination_maximum_seconds": 1.0, "cleanup_timeout_seconds": 4.0,
    "case_timeout_seconds": 20.0, "total_timeout_seconds": 120.0, "maximum_json_bytes": 1048576,
    "prehandshake_expected_exit_code": 37, "import_failure_expected_exit_code": 38}
CASES = (("healthy32", "healthy", 33554432), ("healthy64", "healthy", 67108864),
    ("busy_timeout", "timeout", 0), ("busy_private_cap64", "private_cap", 67108864),
    ("prehandshake_exit37", "prehandshake_fail", 0), ("injected_import_failure38", "import_fail", 0))
NATIVE_ARGUMENTS = ("/d", "/q", "/c", "set /p workload_observer_gate=")


def deadline(stage_seconds, case_deadline, suite_deadline):
    return min(time.perf_counter() + stage_seconds, case_deadline, suite_deadline)


def wait_receipt(directory, filename, until, nonce, role="worker", poll=None):
    path = Path(directory) / filename
    while time.perf_counter() < until:
        if path.exists():
            return obs.validate_message(obs.read_small(path, CONFIG["maximum_json_bytes"]), nonce, role)
        failure_path = Path(directory) / "worker-failure.json"
        if failure_path.exists():
            failure = obs.validate_message(obs.read_small(failure_path), nonce, "worker")
            raise obs.ObserverError("worker failure: " + str(failure.get("error")))
        if poll is not None:
            poll()
        time.sleep(CONFIG["sampler_interval_seconds"])
    raise obs.ObserverError("message deadline exceeded: " + filename)


def worker_control(directory, filename, nonce, command, case_deadline, suite_deadline):
    receipt = wait_receipt(directory, filename, deadline(CONFIG["barrier_timeout_seconds"], case_deadline, suite_deadline), nonce, "controller")
    if receipt.get("command") != command:
        raise obs.ObserverError("unexpected worker barrier command")


def native_thread_count(backend, pid):
    snap = backend.k.CreateToolhelp32Snapshot(2, 0)
    if snap in (None, ct.c_void_p(-1).value):
        backend.checked(False, "CreateToolhelp32Snapshot thread count")
    entry = obs.PROCESSENTRY()
    entry.dwSize = ct.sizeof(entry)
    try:
        backend.checked(backend.k.Process32FirstW(snap, ct.byref(entry)), "Process32FirstW thread count")
        while True:
            if int(entry.th32ProcessID) == pid:
                return int(entry.cntThreads)
            if not backend.k.Process32NextW(snap, ct.byref(entry)):
                error = ct.get_last_error()
                if error != 18:
                    raise obs.ObserverError("Process32NextW thread count failed (WinError " + str(error) + ")")
                raise obs.ObserverError("actual interpreter absent from native thread-count snapshot")
    finally:
        backend.close(snap)


def native_process_cpu(backend, ref):
    created, exited, kernel, user = (obs.FILETIME() for _ in range(4))
    backend.checked(backend.k.GetProcessTimes(ref.handle, ct.byref(created), ct.byref(exited),
        ct.byref(kernel), ct.byref(user)), "GetProcessTimes native CPU")
    creation = (created.high << 32) | created.low
    if creation != ref.creation_filetime:
        raise obs.ObserverError("native CPU query process creation mismatch")
    return (((kernel.high << 32) | kernel.low) + ((user.high << 32) | user.low)) / 10_000_000


def parent_sample(job, actual, samples):
    sample = actual.reading()
    sample["native_cpu_seconds"] = native_process_cpu(job.backend, actual)
    samples.append(sample)
    return sample


def verify_native_child(job, actual, launch_receipt, native_path, expected_hash):
    if launch_receipt["pid"] != actual.pid:
        raise obs.ObserverError("native launch receipt sender is not actual interpreter")
    if (launch_receipt.get("command_arguments") != list(NATIVE_ARGUMENTS) or launch_receipt.get("close_fds") is not True
        or launch_receipt.get("stdin_anonymous_pipe") is not True or launch_receipt.get("shell") is not False
        or launch_receipt.get("creationflags") != 0x08000000 or launch_receipt.get("stdout_devnull") is not True
        or launch_receipt.get("stderr_devnull") is not True):
        raise obs.ObserverError("native launch contract differs from fixed control")
    child = job.retain(launch_receipt["native_pid"])
    job.member(actual)
    job.member(child)
    parents = job.backend.snapshot()
    if parents.get(child.pid) != actual.pid or child.creation_filetime < actual.creation_filetime:
        raise obs.ObserverError("native child parent/creation mismatch")
    query = job.backend.k.QueryFullProcessImageNameW
    query.argtypes = [obs.HANDLE, obs.DWORD, ct.c_wchar_p, ct.POINTER(obs.DWORD)]
    query.restype = obs.BOOL
    image = ct.create_unicode_buffer(32768)
    length = obs.DWORD(len(image))
    job.backend.checked(query(child.handle, 0, image, ct.byref(length)), "QueryFullProcessImageNameW native child")
    if os.path.normcase(os.path.realpath(image.value)) != os.path.normcase(os.path.realpath(native_path)):
        raise obs.ObserverError("native child image differs from frozen executable")
    image_hash = obs.sha256_file(image.value)
    if image_hash != expected_hash:
        raise obs.ObserverError("native executable bytes differ from freeze")
    return child, {"launch_receipt": launch_receipt,
        "os_identity": {"pid": child.pid, "creation_filetime": child.creation_filetime,
            "parent_pid": parents[child.pid]},
        "os_image": {"basename": Path(image.value).name, "sha256": image_hash, "matches_frozen": True},
        "job_member": True, "no_native_self_report": True}


def prepare_workload(backend):
    """Called exclusively after an authenticated parent's import release."""
    import site
    site.ENABLE_USER_SITE = False
    site.main()
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[variable] = "2"
    before_import = native_thread_count(backend, os.getpid())
    torch = importlib.import_module("torch")
    if str(torch.__version__) != CONFIG["torch_version"]:
        raise obs.ObserverError("actual Torch version differs from frozen CPU version")
    torch.set_num_threads(CONFIG["intraop_threads"])
    torch.set_num_interop_threads(CONFIG["interop_threads"])
    if (torch.get_num_threads(), torch.get_num_interop_threads()) != (2, 2):
        raise obs.ObserverError("actual Torch thread configuration mismatch")
    n = CONFIG["matrix_dimension"]
    inputs = torch.full((n, n), 1 / 32, dtype=torch.float32, device="cpu")
    parameter = torch.nn.Parameter(torch.full((n, n), 1 / 32, dtype=torch.float32, device="cpu"))
    optimizer = torch.optim.SGD([parameter], lr=0.001, momentum=0)
    original = parameter.detach().clone()
    busy_output = torch.zeros_like(inputs)
    counts = {"before_import": before_import, "before_operation": native_thread_count(backend, os.getpid())}
    operation_started = time.perf_counter()
    loss = (inputs @ parameter).square().mean()
    loss.backward()
    gradient_finite = bool(torch.isfinite(parameter.grad).all().item())
    optimizer.step()
    operation_finished = time.perf_counter()
    counts["after_operation"] = native_thread_count(backend, os.getpid())
    operation = {"forward_calls": 1, "backward_calls": 1, "optimizer_steps": 1,
        "loss": float(loss.detach().item()), "gradient_finite": gradient_finite,
        "parameters_finite": bool(torch.isfinite(parameter).all().item()),
        "parameter_changed": bool(torch.any(parameter.detach() != original).item()),
        "device": str(parameter.device), "dtype": str(parameter.dtype), "matrix_dimension": n,
        "started_perf_counter": operation_started, "completed_perf_counter": operation_finished,
        "wall_seconds": operation_finished - operation_started}
    if not math.isfinite(operation["loss"]) or not all(operation[key] for key in ("gradient_finite", "parameters_finite", "parameter_changed")):
        raise obs.ObserverError("single CPU engineering update was invalid")
    return torch, inputs, parameter.detach(), busy_output, {"torch_version": str(torch.__version__),
        "intraop_threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
        "native_thread_counts": counts, "operation": operation, "post_import_perf_counter": time.perf_counter()}


def checkpoint(backend, directory, stage, nonce, case_deadline, suite_deadline):
    obs.write_new(directory / (stage + "-before.json"), base.envelope(nonce, "worker", **backend.self_reading()))
    worker_control(directory, stage + "-parent-done.json", nonce, "parent-sampled", case_deadline, suite_deadline)
    obs.write_new(directory / (stage + "-after.json"), base.envelope(nonce, "worker", **backend.self_reading()))
    worker_control(directory, stage + "-continue.json", nonce, "continue", case_deadline, suite_deadline)


def worker(directory, nonce, native_path, mode, manual_bytes, case_deadline, suite_deadline):
    if mode == "prehandshake_fail":
        os._exit(CONFIG["prehandshake_expected_exit_code"])
    backend, allocation, child = obs.WindowsBackend(), None, None
    try:
        base.publish_identity(backend, directory, "worker-ready.json", nonce, "worker")
        worker_control(directory, "create-native.json", nonce, "create-native", case_deadline, suite_deadline)
        child = subprocess.Popen([str(native_path), *NATIVE_ARGUMENTS], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
            creationflags=0x08000000, shell=False)
        obs.write_new(directory / "native-ready.json", base.envelope(nonce, "worker", native_pid=child.pid,
            command_arguments=list(NATIVE_ARGUMENTS), close_fds=True, stdin_anonymous_pipe=True,
            shell=False, creationflags=0x08000000, stdout_devnull=True, stderr_devnull=True))
        worker_control(directory, "import-release.json", nonce, "import", case_deadline, suite_deadline)
        if mode == "import_fail":
            missing = "workload_observer_missing_dependency_" + nonce
            try:
                importlib.import_module(missing)
            except ModuleNotFoundError as error:
                if error.name != missing:
                    raise
                obs.write_new(directory / "expected-import-failure.json", base.envelope(nonce, "worker",
                    stage="import", exception_type="ModuleNotFoundError", missing_module=missing,
                    torch_imported="torch" in sys.modules, optimizer_steps=0,
                    expected_exit_code=CONFIG["import_failure_expected_exit_code"]))
                os._exit(CONFIG["import_failure_expected_exit_code"])
            raise obs.ObserverError("injected missing module unexpectedly imported")
        torch, left, right, busy_output, receipt = prepare_workload(backend)
        obs.write_new(directory / "workload-ready.json", base.envelope(nonce, "worker", **receipt))
        checkpoint(backend, directory, "baseline", nonce, case_deadline, suite_deadline)
        allocation = backend.allocate(manual_bytes)
        checkpoint(backend, directory, "allocated", nonce, case_deadline, suite_deadline)
        if mode == "healthy":
            child.stdin.write(b"done\r\n")
            child.stdin.flush()
            child.stdin.close()
            wait_budget = deadline(CONFIG["barrier_timeout_seconds"], case_deadline, suite_deadline) - time.perf_counter()
            if wait_budget <= 0:
                raise obs.ObserverError("no remaining budget for healthy native exit")
            code = child.wait(timeout=wait_budget)
            if code != 0:
                raise obs.ObserverError("healthy native descendant did not exit0")
            backend.free(allocation)
            allocation = None
            obs.write_new(directory / "worker-completed.json", base.envelope(nonce, "worker",
                native_exit_code=code, native_released_nonempty_line=True, optimizer_steps=1))
            return
        if mode not in ("timeout", "private_cap"):
            raise obs.ObserverError("unexpected workload worker mode")
        busy_start = time.perf_counter()
        obs.write_new(directory / "busy-ready.json", base.envelope(nonce, "worker", perf_counter=busy_start,
            native_thread_count=native_thread_count(backend, os.getpid()), extra_backward_calls=0, extra_optimizer_steps=0))
        with torch.no_grad():
            torch.mm(left, right, out=busy_output)
            obs.write_new(directory / "busy-first-operation.json", base.envelope(nonce, "worker",
                completed_perf_counter=time.perf_counter(), matmul_iterations_completed=1,
                extra_backward_calls=0, extra_optimizer_steps=0))
            busy_backstop = min(busy_start + CONFIG["busy_backstop_seconds"], case_deadline, suite_deadline)
            while time.perf_counter() < busy_backstop:
                torch.mm(left, right, out=busy_output)
        raise obs.ObserverError("busy backstop expired without parent enforcement")
    except BaseException as error:
        obs.write_new(directory / "worker-failure.json", base.envelope(nonce, "worker",
            error=base.public_error(error, directory, native_path, sys.executable)))
        raise
    finally:
        backend.free(allocation)
        if child is not None and child.stdin is not None and not child.stdin.closed:
            child.stdin.close()


def validate_workload(receipt):
    op = receipt.get("operation", {})
    times = [op.get(key) for key in ("started_perf_counter", "completed_perf_counter", "wall_seconds")]
    valid_timing = (all(type(v) in (int, float) and math.isfinite(v) for v in times)
        and times[1] >= times[0] and math.isclose(times[2], times[1] - times[0], rel_tol=0, abs_tol=1e-12))
    return (receipt.get("torch_version") == CONFIG["torch_version"] and receipt.get("intraop_threads") == 2
        and receipt.get("interop_threads") == 2 and all(type(v) is int and v >= 1
            for v in receipt.get("native_thread_counts", {}).values())
        and set(receipt.get("native_thread_counts", {})) == {"before_import", "before_operation", "after_operation"}
        and all(type(op.get(k)) is int and op[k] == 1 for k in ("forward_calls", "backward_calls", "optimizer_steps"))
        and all(op.get(k) is True for k in ("gradient_finite", "parameters_finite", "parameter_changed"))
        and type(op.get("loss")) in (int, float) and math.isfinite(op["loss"])
        and valid_timing
        and op.get("device") == "cpu" and op.get("dtype") == "torch.float32" and op.get("matrix_dimension") == 1024)


def read_bracket(job, actual, directory, stage, nonce, report, case_deadline, suite_deadline):
    until = deadline(CONFIG["barrier_timeout_seconds"], case_deadline, suite_deadline)
    sample = lambda: parent_sample(job, actual, report["samples"])
    before = wait_receipt(directory, stage + "-before.json", until, nonce, poll=sample)
    parent = sample()
    base.control(directory, stage + "-parent-done.json", nonce, "parent-sampled")
    after = wait_receipt(directory, stage + "-after.json", until, nonce, poll=sample)
    comparison = obs.compare_memory_bracket(before, parent, after, CONFIG["memory_bracket_tolerance_bytes"])
    bracket = {"self_before": before, "parent": parent, "self_after": after, "comparison": comparison}
    report.setdefault("memory_brackets", {})[stage] = bracket
    if not comparison["passed"]:
        raise obs.ObserverError("memory bracket failed: " + stage)
    return bracket


def sampling_summary(samples, start, end):
    selected = [s for s in samples if start <= s["perf_counter"] <= end]
    points = [start] + [s["perf_counter"] for s in selected] + [end]
    gap = max(b - a for a, b in zip(points, points[1:]))
    cpu_delta = selected[-1]["native_cpu_seconds"] - selected[0]["native_cpu_seconds"] if len(selected) >= 2 else 0
    return {"started_perf_counter": start, "completed_perf_counter": end, "wall_seconds": end - start,
        "samples_count": len(selected), "maximum_gap_including_boundaries_seconds": gap,
        "native_cpu_delta_seconds": cpu_delta,
        "gap_gate_passed": bool(selected) and gap <= CONFIG["maximum_recorded_sample_gap_seconds"]}


def cleanup(job, case_deadline, suite_deadline):
    budget = min(CONFIG["cleanup_timeout_seconds"], case_deadline - time.perf_counter(), suite_deadline - time.perf_counter())
    if budget <= 0:
        raise obs.ObserverError("no remaining budget for verified cleanup")
    return job.cleanup_receipt(budget, require_zero=True)


def live_member_receipts(job, *refs):
    records = []
    for ref in refs:
        job.member(ref)
        records.append({"pid": ref.pid, "creation_filetime": ref.creation_filetime,
            "job_member": True, "alive": True, "verified_perf_counter": time.perf_counter()})
    return records


def require_exit(ref, expected, until):
    while time.perf_counter() < until:
        if not ref.alive():
            code = ref.exit_code()
            if code != expected:
                raise obs.ObserverError("unexpected exit status: " + str(code))
            return code
        time.sleep(CONFIG["sampler_interval_seconds"])
    raise obs.ObserverError("expected process exit deadline exceeded")


def run_case(spec, python_path, native_path, native_hash, output, suite_deadline):
    case_id, mode, manual_bytes = spec
    directory = output / case_id
    directory.mkdir()
    nonce = secrets.token_hex(32)
    started = time.perf_counter()
    case_deadline = min(started + CONFIG["case_timeout_seconds"], suite_deadline)
    report = {"id": case_id, "mode": mode, "expected_manual_allocation_bytes": manual_bytes, "nonce": nonce,
        "started_at": base.utc_now(), "passed": False, "samples": [], "outcome": None}
    job = None
    try:
        if started >= suite_deadline:
            raise obs.ObserverError("suite expired before case")
        job = obs.WindowsJob()
        launcher = job.start_suspended([str(python_path), "-S", str(SCRIPT), "--worker", "--directory", str(directory),
            "--nonce", nonce, "--native", str(native_path), "--mode", mode, "--manual-bytes", str(manual_bytes),
            "--case-deadline", str(case_deadline), "--suite-deadline", str(suite_deadline)], cwd=ROOT)
        report["launcher"] = {"pid": launcher.pid, "creation_filetime": launcher.creation_filetime,
            "assigned_while_suspended": True, "job_handle_inherited": False}
        until = deadline(CONFIG["handshake_timeout_seconds"], case_deadline, suite_deadline)
        if mode == "prehandshake_fail":
            code = require_exit(launcher, CONFIG["prehandshake_expected_exit_code"], until)
            absent = not (directory / "worker-ready.json").exists()
            report["prehandshake_control"] = {"exit_code": code, "handshake_absent": absent,
                "actual_interpreter_identity_unavailable": True}
            if not absent:
                raise obs.ObserverError("prehandshake control unexpectedly authenticated")
            report["cleanup"] = cleanup(job, case_deadline, suite_deadline)
            report["outcome"] = "expected_prehandshake_exit37"
        else:
            ready = wait_receipt(directory, "worker-ready.json", until, nonce)
            actual, ancestry = job.authenticate(ready, nonce, "worker", launcher)
            report["worker_identity"] = {"self_receipt": ready, "verified_ancestry": ancestry,
                "launcher_differs_from_interpreter": launcher.pid != actual.pid}
            base.control(directory, "create-native.json", nonce, "create-native")
            native_ready = wait_receipt(directory, "native-ready.json", until, nonce)
            native, report["native_descendant"] = verify_native_child(job, actual, native_ready, native_path, native_hash)
            base.control(directory, "import-release.json", nonce, "import")
            import_until = deadline(CONFIG["import_workload_timeout_seconds"], case_deadline, suite_deadline)
            if mode == "import_fail":
                failure = wait_receipt(directory, "expected-import-failure.json", import_until, nonce)
                report["import_failure_receipt"] = failure
                if (failure["pid"] != actual.pid or failure.get("missing_module") != "workload_observer_missing_dependency_" + nonce
                    or failure.get("exception_type") != "ModuleNotFoundError" or failure.get("torch_imported") is not False
                    or failure.get("optimizer_steps") != 0 or failure.get("expected_exit_code") != 38):
                    raise obs.ObserverError("injected import failure did not match fixed control")
                require_exit(actual, 38, import_until)
                require_exit(launcher, 38, import_until)
                report["expected_worker_exit_code"] = 38
                job.terminate()
                report["cleanup"] = cleanup(job, case_deadline, suite_deadline)
                report["outcome"] = "expected_injected_import_failure38"
            else:
                ready_work = wait_receipt(directory, "workload-ready.json", import_until, nonce,
                    poll=lambda: parent_sample(job, actual, report["samples"]))
                report["workload_ready"] = ready_work
                if ready_work["pid"] != actual.pid or not validate_workload(ready_work):
                    raise obs.ObserverError("Torch workload/thread receipt failed")
                baseline = read_bracket(job, actual, directory, "baseline", nonce, report, case_deadline, suite_deadline)
                private_limit = baseline["parent"]["memory"]["private_bytes"] + CONFIG["private_cap_increment_bytes"]
                base.control(directory, "baseline-continue.json", nonce, "continue")
                allocated = read_bracket(job, actual, directory, "allocated", nonce, report, case_deadline, suite_deadline)
                report["allocation_check"] = base.check_allocation(baseline, allocated, manual_bytes)
                if not report["allocation_check"]["passed"]:
                    raise obs.ObserverError("manual allocation delta gate failed")
                base.control(directory, "allocated-continue.json", nonce, "continue")
                if mode == "healthy":
                    completed = wait_receipt(directory, "worker-completed.json", deadline(CONFIG["barrier_timeout_seconds"], case_deadline, suite_deadline), nonce)
                    report["healthy_completion"] = completed
                    if (completed["pid"] != actual.pid or completed.get("native_exit_code") != 0
                        or completed.get("native_released_nonempty_line") is not True or completed.get("optimizer_steps") != 1):
                        raise obs.ObserverError("healthy completion contract failed")
                    report["cleanup"] = cleanup(job, case_deadline, suite_deadline)
                    if any(item["exit_code"] != 0 for item in report["cleanup"]["exit_codes"]):
                        raise obs.ObserverError("healthy control exited nonzero")
                    report["outcome"] = "normal_completion"
                else:
                    poll = lambda: parent_sample(job, actual, report["samples"])
                    busy = wait_receipt(directory, "busy-ready.json", deadline(CONFIG["barrier_timeout_seconds"], case_deadline, suite_deadline), nonce, poll=poll)
                    first = wait_receipt(directory, "busy-first-operation.json", deadline(CONFIG["barrier_timeout_seconds"], case_deadline, suite_deadline), nonce, poll=poll)
                    report["busy_ready"], report["busy_first_operation"] = busy, first
                    if busy["pid"] != actual.pid or first["pid"] != actual.pid or first.get("matmul_iterations_completed") != 1:
                        raise obs.ObserverError("busy first-operation control invalid")
                    if any(r.get(key) != 0 for r in (busy, first) for key in ("extra_backward_calls", "extra_optimizer_steps")):
                        raise obs.ObserverError("busy phase performed extra optimizer/backward work")
                    busy_start = busy["perf_counter"]
                    if mode == "timeout":
                        busy_deadline = busy_start + CONFIG["busy_timeout_seconds"]
                        report["busy_deadline_perf_counter"] = busy_deadline
                        while time.perf_counter() < busy_deadline:
                            if time.perf_counter() >= case_deadline or time.perf_counter() >= suite_deadline:
                                raise obs.ObserverError("busy control exceeded case/suite budget")
                            job.member(native)
                            poll()
                            time.sleep(CONFIG["sampler_interval_seconds"])
                        report["outcome"] = "timeout"
                    elif mode == "private_cap":
                        report["actual_interpreter_private_limit_bytes"] = private_limit
                        crossing = [s for s in report["samples"] if obs.memory_limit_crossed(s, private_limit)
                            and s["perf_counter"] >= allocated["self_before"]["perf_counter"]]
                        if not crossing or not obs.memory_limit_crossed(poll(), private_limit):
                            raise obs.ObserverError("post-import manual private threshold did not cross")
                        report["first_over_limit_sample"] = crossing[0]
                        report["outcome"] = "memory_private_limit"
                    else:
                        raise obs.ObserverError("unknown busy mode")
                    poll()
                    busy_end = time.perf_counter()
                    summary = sampling_summary(report["samples"], busy_start, busy_end)
                    report["busy_sampling"] = summary
                    if not summary["gap_gate_passed"] or (mode == "timeout" and summary["native_cpu_delta_seconds"] < CONFIG["busy_timeout_minimum_cpu_seconds"]):
                        raise obs.ObserverError("busy sampling/CPU progress gate failed")
                    report["pretermination_live_members"] = live_member_receipts(job, actual, native)
                    report["termination_request_started_perf_counter"] = time.perf_counter()
                    job.terminate()
                    report["termination_request_returned_perf_counter"] = time.perf_counter()
                    if mode == "private_cap":
                        latency = report["termination_request_returned_perf_counter"] - allocated["self_before"]["perf_counter"]
                        report["allocation_ready_to_termination_seconds"] = latency
                        if not 0 <= latency <= CONFIG["cap_ready_to_termination_maximum_seconds"]:
                            raise obs.ObserverError("private cap termination exceeded1s bound")
                    report["cleanup"] = cleanup(job, case_deadline, suite_deadline)
        if time.perf_counter() > case_deadline:
            raise obs.ObserverError("case wall budget exceeded")
        report["passed"] = True
    except BaseException as error:
        report["error"] = base.public_error(error, directory, output, python_path, native_path)
        if job is not None:
            try:
                job.terminate()
                report["failure_cleanup"] = cleanup(job, case_deadline, suite_deadline)
            except BaseException as cleanup_error:
                report["cleanup_error"] = base.public_error(cleanup_error)
    finally:
        if job is not None:
            for label, action in (("job_close_error", job.close), ("process_handle_close_error", job.close_refs)):
                try:
                    action()
                except BaseException as error:
                    report["passed"] = False
                    report[label] = base.public_error(error)
        report["completed_at"] = base.utc_now()
        final_perf = time.perf_counter()
        report["wall_seconds"] = final_perf - started
        if final_perf > case_deadline or final_perf > suite_deadline:
            report["passed"] = False
            report["final_wall_budget_exceeded"] = True
        obs.write_new(directory / "case-report.json", report)
    return report


def validate_freeze(protocol_path, freeze_path, python_path, native_path):
    protocol, freeze = obs.read_small(protocol_path), obs.read_small(freeze_path)
    if protocol.get("config") != CONFIG or tuple(protocol.get("source_paths", [])) != SOURCE_PATHS or tuple(protocol.get("frozen_dependency_paths", [])) != DEPENDENCY_PATHS:
        raise obs.ObserverError("protocol integration config/paths differ")
    if [(c["id"], c["mode"], c["manual_allocation_bytes"]) for c in protocol["cases_in_order"]] != list(CASES):
        raise obs.ObserverError("protocol fixed case order differs")
    if freeze.get("protocol_sha256") != obs.sha256_file(protocol_path):
        raise obs.ObserverError("protocol not frozen")
    for field, paths in (("new_source_files_sha256", SOURCE_PATHS), ("frozen_dependency_files_sha256", DEPENDENCY_PATHS)):
        values = freeze.get(field, {})
        if set(values) != set(paths) or any(obs.sha256_file(ROOT / p) != values[p] for p in paths):
            raise obs.ObserverError("source/dependency differs from freeze: " + field)
    for field, path in (("python_executable_sha256", python_path), ("native_executable_sha256", native_path)):
        if freeze.get(field) != obs.sha256_file(path):
            raise obs.ObserverError("executable differs from freeze: " + field)
    declared, frozen = (dt.datetime.fromisoformat(v) for v in (protocol["predeclared_at"], freeze["frozen_at"]))
    if declared.tzinfo is None or frozen.tzinfo is None or not declared <= frozen <= dt.datetime.now(dt.timezone.utc):
        raise obs.ObserverError("invalid integration freeze chronology")
    if Path(native_path).name.lower() != "cmd.exe":
        raise obs.ObserverError("native executable must be frozen cmd.exe")
    return protocol, freeze


def acceptance(python_path, native_path, protocol_path, freeze_path, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = {"schema_version": 1, "experiment_id": "windows-torch-workload-observer-integration-v1",
        "kind": "CPU engineering integration; no pretrained model or scientific rerun", "started_at": base.utc_now(),
        "platform": platform.platform(), "os_name": os.name, "passed": False, "cases": [], "no_fallback": True}
    try:
        protocol, freeze = validate_freeze(protocol_path, freeze_path, python_path, native_path)
        report.update(protocol_sha256=obs.sha256_file(protocol_path), implementation_sha256=obs.sha256_file(freeze_path),
            source_sha256=freeze["new_source_files_sha256"], frozen_dependencies_sha256=freeze["frozen_dependency_files_sha256"],
            launch_executable_basename=Path(python_path).name, launch_executable_sha256=obs.sha256_file(python_path),
            native_executable_basename=Path(native_path).name, native_executable_sha256=obs.sha256_file(native_path),
            protocol_predeclared_at=protocol["predeclared_at"], implementation_frozen_at=freeze["frozen_at"])
        if os.name != "nt":
            raise obs.UnsupportedPlatform("Windows workload acceptance unsupported; no fallback")
        suite_deadline = started + CONFIG["total_timeout_seconds"]
        for spec in CASES:
            report["cases"].append(run_case(spec, Path(python_path).resolve(), Path(native_path).resolve(),
                freeze["native_executable_sha256"], output, suite_deadline))
        report["passed"] = len(report["cases"]) == 6 and all(c["passed"] for c in report["cases"]) and time.perf_counter() <= suite_deadline
    except BaseException as error:
        report["error"] = base.public_error(error, output, python_path, native_path, protocol_path, freeze_path)
    report["completed_at"] = base.utc_now()
    report["wall_seconds"] = time.perf_counter() - started
    if report["wall_seconds"] > CONFIG["total_timeout_seconds"]:
        report["passed"] = False
        report["final_wall_budget_exceeded"] = True
    obs.write_new(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("python", "native", "protocol", "freeze", "output", "directory"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--nonce")
    parser.add_argument("--mode", choices=tuple(sorted({c[1] for c in CASES})))
    parser.add_argument("--manual-bytes", type=int)
    parser.add_argument("--case-deadline", type=float)
    parser.add_argument("--suite-deadline", type=float)
    args = parser.parse_args(argv)
    if args.worker:
        if any(v is None for v in (args.directory, args.nonce, args.native, args.mode, args.manual_bytes, args.case_deadline, args.suite_deadline)):
            parser.error("worker requires directory, nonce, native, mode and manual-bytes")
        obs.validate_nonce(args.nonce)
        if not 0 <= args.manual_bytes <= CONFIG["manual_allocation_maximum_bytes"]:
            parser.error("manual allocation exceeds64MiB bound")
        worker(args.directory, args.nonce, args.native, args.mode, args.manual_bytes, args.case_deadline, args.suite_deadline)
        return 0
    if any(v is None for v in (args.python, args.native, args.protocol, args.freeze, args.output)):
        parser.error("acceptance requires python, native, protocol, freeze and fresh output")
    report = acceptance(args.python, args.native, args.protocol, args.freeze, args.output)
    print("workload observer engineering acceptance: " + ("passed" if report["passed"] else "FAILED"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
