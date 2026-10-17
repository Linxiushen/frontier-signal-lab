"""Versioned dual self-path / retained OS-image census, with no ML workloads.

Derived from frozen child_image_census.py SHA256 999707e2b92b3e7b7a75b252b740c20efd1d770bf76eea745f65fa3c1de90ed4.
This new experiment does not modify or reclassify that rejected frozen result.

Import and mocked tests start no process. Only the root-reviewed frozen CLI may
run the two stdlib identity controls; all older probes remain unchanged.
"""
from __future__ import annotations
import argparse
import ctypes as ct
import datetime as dt
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import process_observer as obs
from experiments import process_observer_probe as base
from experiments import workload_observer_probe as work

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
EXPERIMENT_ID = "windows-dual-identity-census-v1"
SOURCE_PATHS = ("experiments/dual_identity_census.py", "tests/test_dual_identity_census.py")
DEPENDENCY_PATHS = ("experiments/process_observer.py", "experiments/process_observer_probe.py",
    "experiments/workload_observer_probe.py", "fixtures/process-observer/protocol.json",
    "fixtures/process-observer/implementation.json", "fixtures/workload-observer/protocol.json",
    "fixtures/workload-observer/implementation.json")
REVIEW_TOOL_PATHS = ("scripts/audit_dual_identity_census.py", "tests/test_dual_identity_census_auditor.py")
CONFIG = {"case_timeout_seconds": 20.0, "suite_timeout_seconds": 45.0,
    "stage_timeout_seconds": 5.0, "cleanup_timeout_seconds": 4.0,
    "maximum_descendants": 16, "maximum_depth": 16, "maximum_json_bytes": 1048576}
CASES = (("native_census_graceful", False), ("injected_python_rejection", True))
SELF_EXECUTABLE_ROLES = {"worker": "launcher", "helper": "base_python"}
RETAINED_OS_IMAGE_ROLES = {"worker": "base_python", "helper": "base_python"}


def canonical_path(path):
    return os.path.normcase(os.path.realpath(path))


def path_hash(path):
    return hashlib.sha256(canonical_path(path).encode("utf-8")).hexdigest()


def self_executable_identity(executable=None):
    """A self-reported file path identity, never an OS process-image claim."""
    executable = sys.executable if executable is None else executable
    return {"source": "sys.executable", "basename": Path(executable).name,
        "sha256": obs.sha256_file(executable), "normalized_path_sha256": path_hash(executable)}


def publish_identity(backend, directory, filename, nonce, role):
    payload = base.envelope(nonce, role, parent_pid=os.getppid(), **backend.self_reading())
    payload["self_executable"] = self_executable_identity()
    obs.write_new(Path(directory) / filename, payload)


def verify_self_executable(message, role, paths, hashes):
    """Verify the declared self-path role independently of retained OS image."""
    expected_role = SELF_EXECUTABLE_ROLES[role]
    value = message.get("self_executable", {})
    if (type(value) is not dict or set(value) != {"source", "basename", "sha256", "normalized_path_sha256"}
        or value.get("source") != "sys.executable" or value.get("basename") != paths[expected_role].name
        or value.get("sha256") != hashes[expected_role]
        or value.get("normalized_path_sha256") != path_hash(paths[expected_role])):
        raise obs.ObserverError("self executable path/content differs from declared " + expected_role + " role")
    return {"self_executable_expected_role": expected_role,
        "retained_os_image_expected_role": RETAINED_OS_IMAGE_ROLES[role]}


def budget(case_end, suite_end, seconds=None):
    now = time.perf_counter()
    until = min(case_end, suite_end, now + (CONFIG["stage_timeout_seconds"] if seconds is None else seconds))
    if until <= now:
        raise obs.ObserverError("nonrenewable case/suite deadline exhausted")
    return until


def control(directory, name, nonce, command):
    obs.write_new(Path(directory) / name, base.envelope(nonce, "controller", command=command,
        training_permitted=False, purpose="stdlib identity census only"))


def wait(directory, name, nonce, role, case_end, suite_end):
    return base.wait_json(Path(directory) / name, budget(case_end, suite_end), nonce, role)


def require_control(directory, name, nonce, command, case_end, suite_end):
    message = wait(directory, name, nonce, "controller", case_end, suite_end)
    if message.get("command") != command or message.get("training_permitted") is not False:
        raise obs.ObserverError("census-only controller contract differs")


def image_identity(backend, ref, exact_paths, system32, value=None):
    value = {} if value is None else value
    query = backend.k.QueryFullProcessImageNameW
    query.argtypes = [obs.HANDLE, obs.DWORD, ct.c_wchar_p, ct.POINTER(obs.DWORD)]
    query.restype = obs.BOOL
    buffer, size = ct.create_unicode_buffer(32768), obs.DWORD(32768)
    backend.checked(query(ref.handle, 0, buffer, ct.byref(size)), "QueryFullProcessImageNameW census")
    normalized = canonical_path(buffer.value)
    matches = sorted(name for name, path in exact_paths.items() if normalized == canonical_path(path))
    try:
        under_system32 = os.path.commonpath((normalized, canonical_path(system32))) == canonical_path(system32)
    except ValueError:
        under_system32 = False
    value.update({"basename": Path(normalized).name, "sha256": None,
        "normalized_path_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        "exact_path_matches": matches, "path_classification": "exact_executable" if matches else "system32" if under_system32 else "other",
        "queried_from_retained_handle": True})
    value["sha256"] = obs.sha256_file(buffer.value)
    if backend.creation(ref.handle) != ref.creation_filetime or int(backend.k.GetProcessId(ref.handle)) != ref.pid:
        raise obs.ObserverError("retained identity changed during OS image query/hash")
    value["retained_identity_stable"] = True
    return value


def bounded_tree(parents, root):
    selected, frontier = {root}, {root}
    for _ in range(CONFIG["maximum_depth"]):
        children = {pid for pid, parent in parents.items() if parent in frontier and pid not in selected}
        if not children:
            return sorted(selected), False
        selected.update(children)
        frontier = children
    remaining = any(parent in frontier and pid not in selected for pid, parent in parents.items())
    return sorted(selected), remaining


def census(job, launcher, known, exact_paths, hashes, system32, report, label, case_end, suite_end):
    started = time.perf_counter()
    until = budget(case_end, suite_end)
    row = {"label": label, "started_perf_counter": started, "training_permitted": False,
        "processes": [], "unapproved_pids": [], "errors": [],
        "coverage": "one bounded Toolhelp snapshot plus retained queries; not continuous child coverage or provider attestation"}
    report.setdefault("censuses", []).append(row)
    row["job_count_before"] = job.active_count()
    parents = job.backend.snapshot()
    selected, truncated = bounded_tree(parents, launcher.pid)
    row.update(observed_pids=selected, snapshot_observed_count=len(selected), truncated=truncated,
        query_budget_exceeded=len(selected) > CONFIG["maximum_descendants"] + 1)
    for index, pid in enumerate(sorted(selected, key=lambda p: (p not in known, p))):
        node = {"pid": pid, "parent_pid": parents.get(pid), "policy_role": "unapproved", "approved_known": False}
        row["processes"].append(node)
        phase = "query_budget"
        try:
            if time.perf_counter() >= until:
                raise obs.ObserverError("census query deadline exhausted")
            if index > CONFIG["maximum_descendants"]:
                raise obs.ObserverError("descendant OS-query budget exceeded; cached PID/parent retained")
            expected = known.get(pid)
            phase = "retain_identity"
            ref = job.retain(pid, expected[0] if expected else None)
            node["creation_filetime"] = ref.creation_filetime
            phase = "live_job_membership_before_image"
            job.member(ref)
            node.update(job_member=True, alive=True)
            node["image"] = {}
            phase = "OS_image_and_file_hash"
            image_identity(job.backend, ref, exact_paths, system32, node["image"])
            phase = "live_job_membership_after_image"
            job.member(ref)
            if expected:
                _, role = expected
                phase = "frozen_known_image_gate"
                if role not in node["image"]["exact_path_matches"] or node["image"]["sha256"] != hashes[role]:
                    raise obs.ObserverError("known process image differs from frozen executable")
                node.update(policy_role=role, approved_known=True)
        except BaseException as error:
            # OS file errors may embed an unknown user's absolute image path.
            # Keep error type/stage/native code without that exception string.
            node["error"] = type(error).__name__ + " during " + phase
            if type(getattr(error, "winerror", None)) is int: node["winerror"] = error.winerror
            row["errors"].append({"pid": pid, "error": node["error"]})
        if not node["approved_known"]:
            row["unapproved_pids"].append(pid)
    row["job_count_after"] = job.active_count()
    by_pid = {node["pid"]: node for node in row["processes"]}
    for node in row["processes"]:
        parent = by_pid.get(node["parent_pid"])
        if parent and "creation_filetime" in parent and "creation_filetime" in node and parent["creation_filetime"] > node["creation_filetime"]:
            row["errors"].append({"pid": node["pid"], "error": "snapshot parent was created after child"})
    row["job_count_matches_before"] = row["job_count_before"] == len(selected)
    row["job_count_matches_after"] = row["job_count_after"] == len(selected)
    row["all_known_present"] = set(known) <= set(selected)
    row["completed_perf_counter"] = time.perf_counter()
    row["wall_seconds"] = row["completed_perf_counter"] - started
    row["census_complete"] = (not truncated and not row["query_budget_exceeded"] and not row["errors"] and row["all_known_present"]
        and row["job_count_matches_before"] and row["job_count_matches_after"] and row["completed_perf_counter"] <= until)
    if not row["census_complete"]:
        raise obs.ObserverError("bounded child-image census incomplete; evidence retained")
    return row


def helper(directory, nonce, case_end, suite_end):
    backend = obs.WindowsBackend()
    publish_identity(backend, directory, "helper-ready.json", nonce, "helper")
    # Parent deliberately never releases this rejection control.
    require_control(directory, "helper-finish.json", nonce, "finish", case_end, suite_end)
    raise obs.ObserverError("rejected helper unexpectedly released")


def worker(directory, nonce, helper_nonce, base_python, native_path, injected, case_end, suite_end):
    backend, child = obs.WindowsBackend(), None
    try:
        publish_identity(backend, directory, "worker-ready.json", nonce, "worker")
        obs.write_new(directory / "worker-census-state.json", base.envelope(nonce, "worker", training_permitted=False,
            torch_imported="torch" in sys.modules, transformers_imported="transformers" in sys.modules, model_loads=0, optimizer_steps=0))
        require_control(directory, "before-native-continue.json", nonce, "create-native", case_end, suite_end)
        child = subprocess.Popen([str(native_path), *work.NATIVE_ARGUMENTS], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=0x08000000, shell=False)
        obs.write_new(directory / "native-ready.json", base.envelope(nonce, "worker", native_pid=child.pid,
            command_arguments=list(work.NATIVE_ARGUMENTS), close_fds=True, stdin_anonymous_pipe=True,
            shell=False, creationflags=0x08000000, stdout_devnull=True, stderr_devnull=True))
        require_control(directory, "after-native-continue.json", nonce, "create-helper" if injected else "finish", case_end, suite_end)
        if injected:
            launched = subprocess.Popen([str(base_python), "-S", str(SCRIPT), "--helper", "--directory", str(directory),
                "--nonce", helper_nonce, "--case-end", str(case_end), "--suite-end", str(suite_end)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, creationflags=0x08000000, shell=False)
            obs.write_new(directory / "helper-launch.json", base.envelope(nonce, "worker", helper_launcher_pid=launched.pid,
                base_executable_sha256=obs.sha256_file(base_python), shell=False, close_fds=True, creationflags=0x08000000))
            require_control(directory, "rejected-worker-finish.json", nonce, "finish", case_end, suite_end)
            raise obs.ObserverError("rejected worker unexpectedly released")
        child.stdin.write(b"done\r\n"); child.stdin.flush(); child.stdin.close()
        remaining = budget(case_end, suite_end) - time.perf_counter()
        if remaining <= 0 or child.wait(timeout=remaining) != 0:
            raise obs.ObserverError("native census control did not exit0")
        obs.write_new(directory / "worker-completed.json", base.envelope(nonce, "worker", native_exit_code=0,
            native_released_nonempty_line=True, training_permitted=False, torch_imported="torch" in sys.modules,
            transformers_imported="transformers" in sys.modules, model_loads=0, optimizer_steps=0))
    except BaseException as error:
        obs.write_new(directory / "worker-failure.json", base.envelope(nonce, "worker",
            error=base.public_error(error, directory, base_python, native_path)))
        raise
    finally:
        if child is not None and child.stdin is not None and not child.stdin.closed:
            child.stdin.close()


def cleanup(job, case_end, suite_end):
    remaining = budget(case_end, suite_end, CONFIG["cleanup_timeout_seconds"]) - time.perf_counter()
    if remaining <= 0:
        raise obs.ObserverError("cleanup budget exhausted")
    return job.cleanup_receipt(remaining, require_zero=True)


def run_case(spec, paths, hashes, output, suite_end):
    name, injected = spec
    directory = output / name; directory.mkdir()
    started = time.perf_counter(); case_end = min(started + CONFIG["case_timeout_seconds"], suite_end)
    nonce, helper_nonce = secrets.token_hex(32), secrets.token_hex(32)
    report = {"id": name, "injected": injected, "nonce": nonce, "helper_nonce": helper_nonce,
        "started_at": base.utc_now(), "started_perf_counter": started, "passed": False,
        "training_permitted": False, "model_loads": 0, "optimizer_steps": 0, "censuses": []}
    job = None
    try:
        budget(case_end, suite_end)
        job = obs.WindowsJob()
        launcher = job.start_suspended([str(paths["launcher"]), "-S", str(SCRIPT), "--worker", "--directory", str(directory),
            "--nonce", nonce, "--helper-nonce", helper_nonce, "--base-python", str(paths["base_python"]),
            "--native", str(paths["native"]), *( ["--injected"] if injected else [] ),
            "--case-end", str(case_end), "--suite-end", str(suite_end)], cwd=ROOT)
        report["launcher"] = {"pid": launcher.pid, "creation_filetime": launcher.creation_filetime,
            "assigned_while_suspended": True, "job_handle_inherited": False}
        ready = wait(directory, "worker-ready.json", nonce, "worker", case_end, suite_end)
        actual, chain = job.authenticate(ready, nonce, "worker", launcher)
        report["worker_identity"] = {"self_receipt": ready, "verified_ancestry": chain}
        report["worker_identity"].update(verify_self_executable(ready, "worker", paths, hashes))
        state = wait(directory, "worker-census-state.json", nonce, "worker", case_end, suite_end)
        report["worker_census_state"] = state
        if (state["pid"] != actual.pid or any(state.get(k) is not False for k in ("training_permitted", "torch_imported", "transformers_imported"))
            or state.get("model_loads") != 0 or state.get("optimizer_steps") != 0):
            raise obs.ObserverError("census worker imported or permitted a workload")
        known = {launcher.pid: (launcher.creation_filetime, "launcher"), actual.pid: (actual.creation_filetime, "base_python")}
        system32 = Path(os.environ["SystemRoot"]) / "System32"
        before = census(job, launcher, known, paths, hashes, system32, report, "before_native", case_end, suite_end)
        report["before_native_unapproved_pids"] = before["unapproved_pids"]
        control(directory, "before-native-continue.json", nonce, "create-native")
        native_ready = wait(directory, "native-ready.json", nonce, "worker", case_end, suite_end)
        native, report["native_descendant"] = work.verify_native_child(job, actual, native_ready, paths["native"], hashes["native"])
        known[native.pid] = (native.creation_filetime, "native")
        census(job, launcher, known, paths, hashes, system32, report, "after_native", case_end, suite_end)
        if injected:
            control(directory, "after-native-continue.json", nonce, "create-helper")
            launch = wait(directory, "helper-launch.json", nonce, "worker", case_end, suite_end)
            message = wait(directory, "helper-ready.json", helper_nonce, "helper", case_end, suite_end)
            extra, ancestry = job.authenticate(message, helper_nonce, "helper", actual)
            report["injected_helper"] = {"launch_receipt": launch, "self_receipt": message, "verified_ancestry": ancestry}
            report["injected_helper"].update(verify_self_executable(message, "helper", paths, hashes))
            if (launch["pid"] != actual.pid or launch.get("helper_launcher_pid") != extra.pid
                or launch.get("base_executable_sha256") != hashes["base_python"] or launch.get("shell") is not False
                or launch.get("close_fds") is not True or launch.get("creationflags") != 0x08000000):
                raise obs.ObserverError("injected helper launch identity differs")
            final = census(job, launcher, known, paths, hashes, system32, report, "after_helper", case_end, suite_end)
            helper_node = next((node for node in final["processes"] if node["pid"] == extra.pid), {})
            if (extra.pid not in final["unapproved_pids"] or helper_node.get("approved_known") is not False
                or helper_node.get("image", {}).get("sha256") != hashes["base_python"]
                or "base_python" not in helper_node.get("image", {}).get("exact_path_matches", [])):
                raise obs.ObserverError("nonce helper was not retained as unapproved base-Python image")
            report["rejection"] = {"helper_pid": extra.pid, "training_permitted": False, "ML_release_absent": True,
                "reason": "helper PID/creation is outside fixed known-role policy even though its image is identified"}
            report["pretermination_live_members"] = work.live_member_receipts(job, actual, native, extra)
            report["termination_started_perf_counter"] = time.perf_counter(); job.terminate()
            report["termination_returned_perf_counter"] = time.perf_counter()
            report["outcome"] = "identified_helper_rejected_no_training"
        else:
            report["prefinish_live_members"] = work.live_member_receipts(job, actual, native)
            control(directory, "after-native-continue.json", nonce, "finish")
            done = wait(directory, "worker-completed.json", nonce, "worker", case_end, suite_end)
            report["completion"] = done
            if (done["pid"] != actual.pid or done.get("native_exit_code") != 0 or done.get("native_released_nonempty_line") is not True
                or any(done.get(k) is not False for k in ("training_permitted", "torch_imported", "transformers_imported"))
                or done.get("model_loads") != 0 or done.get("optimizer_steps") != 0):
                raise obs.ObserverError("graceful census completion differs")
            report["outcome"] = "graceful_census_no_training"
        report["cleanup"] = cleanup(job, case_end, suite_end)
        if not injected:
            primary = {launcher.pid, actual.pid, native.pid}
            if any(x["exit_code"] != 0 for x in report["cleanup"]["exit_codes"] if x["pid"] in primary):
                raise obs.ObserverError("known graceful controls exited nonzero")
        report["passed"] = time.perf_counter() <= case_end
    except BaseException as error:
        report["error"] = base.public_error(error, directory, output, *(paths.values()))
        if job is not None:
            try:
                job.terminate(); report["failure_cleanup"] = cleanup(job, case_end, suite_end)
            except BaseException as cleanup_error:
                report["cleanup_error"] = base.public_error(cleanup_error)
    finally:
        if job is not None:
            for field, action in (("job_close_error", job.close), ("process_handle_close_error", job.close_refs)):
                try: action()
                except BaseException as error:
                    report[field] = base.public_error(error); report["passed"] = False
    report["completed_at"] = base.utc_now(); report["completed_perf_counter"] = time.perf_counter()
    report["wall_seconds"] = report["completed_perf_counter"] - started
    if report["completed_perf_counter"] > case_end:
        report["passed"] = False
        report["case_wall_budget_exceeded"] = True
    return report


def validate_freeze(protocol_path, freeze_path, paths):
    protocol, freeze = obs.read_small(protocol_path), obs.read_small(freeze_path)
    if (protocol.get("config") != CONFIG or protocol.get("experiment_id") != EXPERIMENT_ID
        or tuple(protocol.get("source_paths", [])) != SOURCE_PATHS or tuple(protocol.get("frozen_dependency_paths", [])) != DEPENDENCY_PATHS
        or tuple(protocol.get("review_tool_paths", [])) != REVIEW_TOOL_PATHS
        or [(c["id"], c["injected"]) for c in protocol.get("cases_in_order", [])] != list(CASES)
        or protocol.get("self_executable_roles") != SELF_EXECUTABLE_ROLES
        or protocol.get("retained_os_image_roles") != RETAINED_OS_IMAGE_ROLES
        or protocol.get("training_permitted") is not False or freeze.get("protocol_sha256") != obs.sha256_file(protocol_path)):
        raise obs.ObserverError("census protocol/config/hash differs")
    for field, names in (("new_source_files_sha256", SOURCE_PATHS), ("frozen_dependency_files_sha256", DEPENDENCY_PATHS),
            ("review_tools_sha256", REVIEW_TOOL_PATHS)):
        values = freeze.get(field, {})
        if set(values) != set(names) or any(obs.sha256_file(ROOT / n) != values[n] for n in names):
            raise obs.ObserverError("census source/dependency freeze differs: " + field)
    hashes = {role: obs.sha256_file(path) for role, path in paths.items()}
    if freeze.get("executables_sha256") != hashes or paths["native"].name.lower() != "cmd.exe":
        raise obs.ObserverError("census executable freeze differs")
    if freeze.get("executable_path_sha256") != {role: path_hash(path) for role, path in paths.items()}:
        raise obs.ObserverError("census opaque executable path freeze differs")
    declared, frozen = (dt.datetime.fromisoformat(v) for v in (protocol["predeclared_at"], freeze["frozen_at"]))
    if declared.tzinfo is None or frozen.tzinfo is None or not declared <= frozen <= dt.datetime.now(dt.timezone.utc):
        raise obs.ObserverError("invalid census freeze chronology")
    return protocol, freeze, hashes


def acceptance(python_path, base_python_path, native_path, protocol_path, freeze_path, output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = {"schema_version": 1, "experiment_id": EXPERIMENT_ID, "started_at": base.utc_now(),
        "started_perf_counter": started, "training_permitted": False, "model_loads": 0, "optimizer_steps": 0,
        "os_name": os.name, "no_fallback": True,
        "self_executable_roles": dict(SELF_EXECUTABLE_ROLES), "retained_os_image_roles": dict(RETAINED_OS_IMAGE_ROLES),
        "passed": False, "cases": [], "scope": "identity census and rejection only; no loader/training/provider/GPU acceptance; no old child identification"}
    paths = {"launcher": Path(python_path).resolve(), "base_python": Path(base_python_path).resolve(), "native": Path(native_path).resolve()}
    try:
        protocol, freeze, hashes = validate_freeze(protocol_path, freeze_path, paths)
        report.update(protocol_sha256=obs.sha256_file(protocol_path), implementation_sha256=obs.sha256_file(freeze_path),
            source_sha256=freeze["new_source_files_sha256"], dependencies_sha256=freeze["frozen_dependency_files_sha256"],
            review_tools_sha256=freeze["review_tools_sha256"],
            executables_sha256=hashes, executable_path_sha256=dict(freeze["executable_path_sha256"]),
            protocol_predeclared_at=protocol["predeclared_at"], implementation_frozen_at=freeze["frozen_at"])
        if os.name != "nt":
            raise obs.UnsupportedPlatform("Windows census only; no fallback")
        suite_end = started + CONFIG["suite_timeout_seconds"]
        for spec in CASES:
            report["cases"].append(run_case(spec, paths, hashes, output, suite_end))
        report["passed"] = len(report["cases"]) == 2 and all(c["passed"] for c in report["cases"]) and time.perf_counter() <= suite_end
    except BaseException as error:
        report["error"] = base.public_error(error, output, protocol_path, freeze_path, *(paths.values()))
    report["completed_at"] = base.utc_now(); report["completed_perf_counter"] = time.perf_counter()
    report["wall_seconds"] = report["completed_perf_counter"] - started
    if report["wall_seconds"] > CONFIG["suite_timeout_seconds"]:
        report["passed"] = False
    obs.write_new(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("python", "base-python", "native", "protocol", "freeze", "output", "directory"):
        parser.add_argument("--" + name, type=Path)
    for name in ("worker", "helper", "injected"): parser.add_argument("--" + name, action="store_true")
    for name in ("nonce", "helper-nonce"): parser.add_argument("--" + name)
    for name in ("case-end", "suite-end"): parser.add_argument("--" + name, type=float)
    args = parser.parse_args(argv)
    if args.worker or args.helper:
        if any(v is None for v in (args.directory, args.nonce, args.case_end, args.suite_end)):
            parser.error("child requires directory, nonce and fixed deadlines")
        obs.validate_nonce(args.nonce)
        if args.helper: helper(args.directory, args.nonce, args.case_end, args.suite_end)
        else:
            if any(v is None for v in (args.helper_nonce, args.base_python, args.native)):
                parser.error("worker requires helper nonce and explicit frozen executables")
            obs.validate_nonce(args.helper_nonce)
            worker(args.directory, args.nonce, args.helper_nonce, args.base_python, args.native, args.injected, args.case_end, args.suite_end)
        return 0
    if any(v is None for v in (args.python, args.base_python, args.native, args.protocol, args.freeze, args.output)):
        parser.error("acceptance requires python, base-python, native, protocol, freeze and fresh output")
    report = acceptance(args.python, args.base_python, args.native, args.protocol, args.freeze, args.output)
    print("dual identity census: " + ("passed (training remains forbidden)" if report["passed"] else "FAILED"))
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
