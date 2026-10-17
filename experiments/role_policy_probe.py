"""Separately frozen stdlib process-role admission controls; training forbidden.

The prior dual-identity census remains an immutable inventory dependency. This
module adds a narrow, environment-bound policy for its observed console topology.
Import and guarded mock tests create no processes or native backend.
"""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import dual_identity_census as dual

obs, base, work = dual.obs, dual.base, dual.work
ROOT, SCRIPT = Path(__file__).resolve().parents[1], Path(__file__).resolve()
EXPERIMENT_ID = "windows-role-policy-probe-v1"
SOURCE_PATHS = ("experiments/role_policy_probe.py", "tests/test_role_policy_probe.py")
DEPENDENCY_PATHS = ("experiments/dual_identity_census.py", *dual.DEPENDENCY_PATHS,
    "fixtures/dual-identity-census/protocol.json", "fixtures/dual-identity-census/implementation.json")
REVIEW_TOOL_PATHS = ("scripts/audit_role_policy_probe.py", "tests/test_role_policy_probe_auditor.py")
CONFIG = {"case_timeout_seconds": 20.0, "suite_timeout_seconds": 65.0,
    "stage_timeout_seconds": 5.0, "cleanup_timeout_seconds": 4.0,
    "maximum_descendants": 16, "maximum_depth": 16, "maximum_json_bytes": 1048576}
CASES = (("healthy_role_admission", "none"), ("injected_python_rejection", "python"),
    ("injected_native_rejection", "native"))
SELF_EXECUTABLE_ROLES = dict(dual.SELF_EXECUTABLE_ROLES)
RETAINED_OS_IMAGE_ROLES = dict(dual.RETAINED_OS_IMAGE_ROLES)
POLICY_CONTRACT = {"auxiliary_role": "console_auxiliary", "auxiliary_image_role": "conhost",
    "authorized_console_owner_roles": ["launcher", "native"], "auxiliaries_per_owner": 1,
    "pin_auxiliary_identity_across_stages": True, "allow_unregistered_same_image": False,
    "training_permitted": False}
CONTROL_PURPOSE = "fixed stdlib role-policy control only"


def budget(case_end, suite_end, seconds=None):
    now = time.perf_counter()
    end = min(case_end, suite_end, now + (CONFIG["stage_timeout_seconds"] if seconds is None else seconds))
    if end <= now:
        raise obs.ObserverError("nonrenewable case/suite deadline exhausted")
    return end


def reference(node):
    return {"pid": node["pid"], "creation_filetime": node["creation_filetime"]}


def image_matches(node, role, paths, hashes):
    image = node.get("image", {})
    return (node.get("job_member") is True and node.get("alive") is True
        and image.get("queried_from_retained_handle") is True and image.get("retained_identity_stable") is True
        and image.get("basename", "").lower() == paths[role].name.lower()
        and image.get("sha256") == hashes[role]
        and image.get("normalized_path_sha256") == dual.path_hash(paths[role])
        and role in image.get("exact_path_matches", []) and not node.get("error"))


def evaluate_policy(snapshot, known, paths, hashes, pinned_auxiliaries):
    """Pure admission decision over a complete inventory; no native calls.

    A recognized file never registers a PID. Every auxiliary must have one exact
    currently registered owner identity, and cannot replace a previously held one.
    """
    value = {"label": snapshot["label"], "admitted": False, "training_permitted": False,
        "primary_roles": [], "auxiliary_roles": [], "admitted_pids": [], "rejected_pids": [],
        "rejections": [], "errors": [], "pinned_auxiliaries": copy.deepcopy(pinned_auxiliaries)}
    nodes = snapshot.get("processes", [])
    by_pid = {node["pid"]: node for node in nodes}
    if (snapshot.get("census_complete") is not True or snapshot.get("errors") or len(by_pid) != len(nodes)
        or set(by_pid) != set(snapshot.get("observed_pids", []))
        or snapshot.get("job_count_before") != len(nodes) or snapshot.get("job_count_after") != len(nodes)):
        value["errors"].append("incomplete_or_inconsistent_inventory")
    by_role = {role: pid for pid, (_, role) in known.items()}
    if (len(by_role) != len(known) or set(by_role) not in ({"launcher", "base_python"}, {"launcher", "base_python", "native"})):
        value["errors"].append("invalid_primary_role_set")
    approved = set()
    for pid, (created, role) in known.items():
        node = by_pid.get(pid, {})
        parent_role = {"base_python": "launcher", "native": "base_python"}.get(role)
        parent_pid = by_role.get(parent_role)
        parent = by_pid.get(parent_pid, {}) if parent_role else None
        okay = (node.get("creation_filetime") == created and node.get("policy_role") == role
            and node.get("approved_known") is True and role in paths and image_matches(node, role, paths, hashes))
        if parent_role:
            okay = (okay and node.get("parent_pid") == parent_pid and parent.get("creation_filetime") == known.get(parent_pid, (None,))[0]
                and type(node.get("creation_filetime")) is int and type(parent.get("creation_filetime")) is int
                and parent["creation_filetime"] <= node["creation_filetime"])
        if not okay:
            value["errors"].append("primary_identity_or_topology_mismatch:" + role)
            continue
        approved.add(pid)
        value["primary_roles"].append({**reference(node), "role": role,
            "parent_ref": reference(parent) if parent is not None else None,
            "frozen_image_sha256": hashes[role], "frozen_path_sha256": dual.path_hash(paths[role])})
    owners = {pid: role for role, pid in by_role.items() if role in ("launcher", "native") and pid in approved}
    candidates = {role: [] for role in owners.values()}
    reasons = {}
    for pid, node in by_pid.items():
        if pid in known:
            continue
        parent_pid = node.get("parent_pid")
        if image_matches(node, "conhost", paths, hashes) and parent_pid in owners:
            owner = by_pid[parent_pid]
            if (type(node.get("creation_filetime")) is int
                and owner["creation_filetime"] <= node["creation_filetime"]):
                candidates[owners[parent_pid]].append(node)
                continue
        reasons[pid] = ("unregistered_parent_identity" if image_matches(node, "conhost", paths, hashes)
            else "unregistered_process_identity")
    proposed = copy.deepcopy(pinned_auxiliaries)
    for owner_pid, role in owners.items():
        owner, matches = by_pid[owner_pid], candidates[role]
        if len(matches) != 1:
            value["errors"].append("auxiliary_cardinality_mismatch:" + role)
            for node in matches: reasons[node["pid"]] = "auxiliary_cardinality_mismatch"
            continue
        node = matches[0]
        pin = {"owner_ref": reference(owner), "auxiliary_ref": reference(node),
            "frozen_image_sha256": hashes["conhost"], "frozen_path_sha256": dual.path_hash(paths["conhost"])}
        if role in pinned_auxiliaries and pinned_auxiliaries[role] != pin:
            value["errors"].append("auxiliary_identity_replaced:" + role)
            reasons[node["pid"]] = "auxiliary_identity_replaced"
            continue
        proposed[role] = pin
        approved.add(node["pid"])
        value["auxiliary_roles"].append({**reference(node), "role": "console_auxiliary",
            "parent_ref": reference(owner), "owner_role": role,
            "frozen_image_sha256": hashes["conhost"], "frozen_path_sha256": dual.path_hash(paths["conhost"])})
    if not set(pinned_auxiliaries) <= set(owners.values()):
        value["errors"].append("previous_console_owner_missing")
    value["admitted_pids"] = sorted(approved)
    value["rejected_pids"] = sorted(set(by_pid) - approved)
    value["rejections"] = [{**reference(by_pid[pid]), "reason": reasons.get(pid, "primary_contract_mismatch")}
        for pid in value["rejected_pids"]]
    if value["rejected_pids"]:
        value["errors"].append("unregistered_processes_present")
    value["admitted"] = not value["errors"]
    if value["admitted"]:
        value["pinned_auxiliaries"] = proposed
    return value


def policy_stage(job, launcher, known, paths, hashes, report, label, requested_control, pins, case_end, suite_end):
    until = budget(case_end, suite_end)
    snapshot = dual.census(job, launcher, known, paths, hashes, paths["conhost"].parent,
        report, label, case_end, suite_end)
    decision = evaluate_policy(snapshot, known, paths, hashes, pins)
    decision.update(census_index=len(report["censuses"]) - 1, decision_index=len(report["role_decisions"]),
        requested_control=requested_control, permitted_control=requested_control if decision["admitted"] else "reject",
        held_liveness=[], started_perf_counter=snapshot["started_perf_counter"])
    report["role_decisions"].append(decision)
    decision["job_count_before"] = job.active_count()
    for node in snapshot["processes"]:
        if time.perf_counter() >= until:
            raise obs.ObserverError("held-liveness stage deadline exhausted")
        ref = job.retain(node["pid"], node["creation_filetime"])
        job.member(ref)
        if (job.backend.creation(ref.handle) != ref.creation_filetime
            or int(job.backend.k.GetProcessId(ref.handle)) != ref.pid):
            raise obs.ObserverError("held-liveness retained PID/creation changed")
        decision["held_liveness"].append({"pid": ref.pid, "creation_filetime": ref.creation_filetime,
            "job_member": True, "alive": True, "verified_perf_counter": time.perf_counter()})
    decision["job_count_after"] = job.active_count()
    decision["completed_perf_counter"] = time.perf_counter()
    decision["wall_seconds"] = decision["completed_perf_counter"] - decision["started_perf_counter"]
    if (decision["job_count_before"] != len(snapshot["processes"])
        or decision["job_count_after"] != len(snapshot["processes"])
        or decision["completed_perf_counter"] > until):
        raise obs.ObserverError("held-liveness count/deadline differs from complete census")
    return snapshot, decision


def control(directory, name, nonce, command, decision):
    if (decision.get("admitted") is not True or decision.get("permitted_control") != command
        or decision.get("training_permitted") is not False):
        raise obs.ObserverError("role policy did not admit the fixed stdlib control")
    obs.write_new(Path(directory) / name, base.envelope(nonce, "controller", command=command,
        training_permitted=False, purpose=CONTROL_PURPOSE, role_policy_admitted=True,
        role_decision_index=decision["decision_index"], role_decision_label=decision["label"]))


def wait(directory, name, nonce, role, case_end, suite_end):
    return base.wait_json(Path(directory) / name, budget(case_end, suite_end), nonce, role)


def require_control(directory, name, nonce, command, decision_index, case_end, suite_end):
    value = wait(directory, name, nonce, "controller", case_end, suite_end)
    if (value.get("command") != command or value.get("training_permitted") is not False
        or value.get("purpose") != CONTROL_PURPOSE or value.get("role_policy_admitted") is not True
        or type(value.get("role_decision_index")) is not int or value.get("role_decision_index") != decision_index
        or value.get("role_decision_label") != ("before_native", "after_native", "after_injection")[decision_index]):
        raise obs.ObserverError("fixed stdlib role-policy controller contract differs")


def native_launch(directory, filename, nonce, native_path):
    child = subprocess.Popen([str(native_path), *work.NATIVE_ARGUMENTS], stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=0x08000000, shell=False)
    obs.write_new(directory / filename, base.envelope(nonce, "worker", native_pid=child.pid,
        command_arguments=list(work.NATIVE_ARGUMENTS), close_fds=True, stdin_anonymous_pipe=True,
        shell=False, creationflags=0x08000000, stdout_devnull=True, stderr_devnull=True))
    return child


def worker(directory, nonce, helper_nonce, base_python, native_path, injection, case_end, suite_end):
    backend, child, extra = obs.WindowsBackend(), None, None
    try:
        dual.publish_identity(backend, directory, "worker-ready.json", nonce, "worker")
        obs.write_new(directory / "worker-policy-state.json", base.envelope(nonce, "worker", training_permitted=False,
            torch_imported="torch" in sys.modules, transformers_imported="transformers" in sys.modules, model_loads=0, optimizer_steps=0))
        require_control(directory, "before-native-continue.json", nonce, "create-native", 0, case_end, suite_end)
        child = native_launch(directory, "native-ready.json", nonce, native_path)
        require_control(directory, "after-native-continue.json", nonce,
            "finish" if injection == "none" else "create-injection", 1, case_end, suite_end)
        if injection == "python":
            extra = subprocess.Popen([str(base_python), "-S", str(SCRIPT), "--helper", "--directory", str(directory),
                "--nonce", helper_nonce, "--case-end", str(case_end), "--suite-end", str(suite_end)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, creationflags=0x08000000, shell=False)
            obs.write_new(directory / "helper-launch.json", base.envelope(nonce, "worker", helper_launcher_pid=extra.pid,
                base_executable_sha256=obs.sha256_file(base_python), shell=False, close_fds=True, creationflags=0x08000000))
        elif injection == "native":
            extra = native_launch(directory, "injected-native-ready.json", nonce, native_path)
        if injection != "none":
            require_control(directory, "rejected-worker-finish.json", nonce, "finish", 2, case_end, suite_end)
            raise obs.ObserverError("rejected worker unexpectedly released")
        child.stdin.write(b"done\r\n"); child.stdin.flush(); child.stdin.close()
        remaining = budget(case_end, suite_end) - time.perf_counter()
        if remaining <= 0 or child.wait(timeout=remaining) != 0:
            raise obs.ObserverError("registered native control did not exit0")
        obs.write_new(directory / "worker-completed.json", base.envelope(nonce, "worker", native_exit_code=0,
            native_released_nonempty_line=True, training_permitted=False, torch_imported="torch" in sys.modules,
            transformers_imported="transformers" in sys.modules, model_loads=0, optimizer_steps=0))
    except BaseException as error:
        obs.write_new(directory / "worker-failure.json", base.envelope(nonce, "worker",
            error=base.public_error(error, directory, base_python, native_path)))
        raise
    finally:
        for value in (child, extra):
            if value is not None and value.stdin is not None and not value.stdin.closed:
                value.stdin.close()


def verify_rejection(snapshot, decision, previous, extra, paths, hashes, injection):
    """A negative control passes only for its exact unexpected live identity."""
    by_pid = {node["pid"]: node for node in snapshot["processes"]}
    node = by_pid.get(extra.pid, {})
    role = "base_python" if injection == "python" else "native"
    parent = next(row for row in previous["primary_roles"] if row["role"] == "base_python")
    others = [row for row in snapshot["processes"] if row["pid"] in decision["rejected_pids"] and row["pid"] != extra.pid]
    if (decision["admitted"] is not False or decision["errors"] != ["unregistered_processes_present"]
        or decision["admitted_pids"] != previous["admitted_pids"] or len(previous["admitted_pids"]) != 5
        or decision["primary_roles"] != previous["primary_roles"] or decision["auxiliary_roles"] != previous["auxiliary_roles"]
        or node.get("creation_filetime") != extra.creation_filetime or extra.pid not in decision["rejected_pids"]
        or node.get("parent_pid") != parent["pid"] or extra.creation_filetime < parent["creation_filetime"]
        or not image_matches(node, role, paths, hashes) or len(others) > 1
        or any(row.get("parent_pid") != extra.pid or row.get("creation_filetime", -1) < extra.creation_filetime
            or not image_matches(row, "conhost", paths, hashes) for row in others)
        or len(snapshot["processes"]) != 6 + len(others)):
        raise obs.ObserverError("negative control failed for a reason other than the exact injected identity/topology")
    return {"injected_ref": {"pid": extra.pid, "creation_filetime": extra.creation_filetime},
        "injected_kind": injection, "decision_index": decision["decision_index"],
        "unexpected_pids": decision["rejected_pids"], "original_five_identities_unchanged": True,
        "training_permitted": False, "ML_release_absent": True,
        "reason": "authenticated unexpected identity remains unregistered despite matching frozen image/path"}


def cleanup(job, case_end, suite_end):
    remaining = budget(case_end, suite_end, CONFIG["cleanup_timeout_seconds"]) - time.perf_counter()
    if remaining <= 0: raise obs.ObserverError("cleanup budget exhausted")
    return job.cleanup_receipt(remaining, require_zero=True)


def run_case(spec, paths, hashes, output, suite_end):
    name, injection = spec
    directory = output / name; directory.mkdir()
    started = time.perf_counter(); case_end = min(started + CONFIG["case_timeout_seconds"], suite_end)
    nonce, helper_nonce = secrets.token_hex(32), secrets.token_hex(32)
    report = {"id": name, "injection": injection, "nonce": nonce, "helper_nonce": helper_nonce,
        "started_at": base.utc_now(), "started_perf_counter": started, "passed": False,
        "training_permitted": False, "model_loads": 0, "optimizer_steps": 0, "censuses": [], "role_decisions": []}
    job = None
    try:
        budget(case_end, suite_end)
        job = obs.WindowsJob()
        launcher = job.start_suspended([str(paths["launcher"]), "-S", str(SCRIPT), "--worker", "--directory", str(directory),
            "--nonce", nonce, "--helper-nonce", helper_nonce, "--base-python", str(paths["base_python"]),
            "--native", str(paths["native"]), "--injection", injection,
            "--case-end", str(case_end), "--suite-end", str(suite_end)], cwd=ROOT)
        report["launcher"] = {"pid": launcher.pid, "creation_filetime": launcher.creation_filetime,
            "assigned_while_suspended": True, "job_handle_inherited": False}
        ready = wait(directory, "worker-ready.json", nonce, "worker", case_end, suite_end)
        actual, chain = job.authenticate(ready, nonce, "worker", launcher)
        report["worker_identity"] = {"self_receipt": ready, "verified_ancestry": chain,
            **dual.verify_self_executable(ready, "worker", paths, hashes)}
        state = wait(directory, "worker-policy-state.json", nonce, "worker", case_end, suite_end)
        report["worker_policy_state"] = state
        if (state["pid"] != actual.pid or any(state.get(k) is not False for k in ("training_permitted", "torch_imported", "transformers_imported"))
            or state.get("model_loads") != 0 or state.get("optimizer_steps") != 0 or launcher.pid == actual.pid):
            raise obs.ObserverError("role-policy worker state or split interpreter identity differs")
        known = {launcher.pid: (launcher.creation_filetime, "launcher"), actual.pid: (actual.creation_filetime, "base_python")}
        _, before = policy_stage(job, launcher, known, paths, hashes, report, "before_native", "create-native", {}, case_end, suite_end)
        control(directory, "before-native-continue.json", nonce, "create-native", before)
        native_ready = wait(directory, "native-ready.json", nonce, "worker", case_end, suite_end)
        native, report["native_descendant"] = work.verify_native_child(job, actual, native_ready, paths["native"], hashes["native"])
        known[native.pid] = (native.creation_filetime, "native")
        _, after = policy_stage(job, launcher, known, paths, hashes, report, "after_native",
            "finish" if injection == "none" else "create-injection", before["pinned_auxiliaries"], case_end, suite_end)
        control(directory, "after-native-continue.json", nonce,
            "finish" if injection == "none" else "create-injection", after)
        if injection != "none":
            if injection == "python":
                launch = wait(directory, "helper-launch.json", nonce, "worker", case_end, suite_end)
                message = wait(directory, "helper-ready.json", helper_nonce, "helper", case_end, suite_end)
                extra, ancestry = job.authenticate(message, helper_nonce, "helper", actual)
                report["injected_process"] = {"kind": injection, "launch_receipt": launch, "self_receipt": message,
                    "verified_ancestry": ancestry, **dual.verify_self_executable(message, "helper", paths, hashes)}
                if (launch["pid"] != actual.pid or launch.get("helper_launcher_pid") != extra.pid
                    or launch.get("base_executable_sha256") != hashes["base_python"] or launch.get("shell") is not False
                    or launch.get("close_fds") is not True or launch.get("creationflags") != 0x08000000):
                    raise obs.ObserverError("injected helper launch identity differs")
            else:
                launch = wait(directory, "injected-native-ready.json", nonce, "worker", case_end, suite_end)
                extra, receipt = work.verify_native_child(job, actual, launch, paths["native"], hashes["native"])
                report["injected_process"] = {"kind": injection, **receipt}
            final, rejected = policy_stage(job, launcher, known, paths, hashes, report, "after_injection", "finish",
                after["pinned_auxiliaries"], case_end, suite_end)
            report["rejection"] = verify_rejection(final, rejected, after, extra, paths, hashes, injection)
            report["termination_started_perf_counter"] = time.perf_counter(); job.terminate()
            report["termination_returned_perf_counter"] = time.perf_counter()
            report["outcome"] = "unregistered_" + injection + "_rejected_no_training"
        else:
            done = wait(directory, "worker-completed.json", nonce, "worker", case_end, suite_end)
            report["completion"] = done
            if (done["pid"] != actual.pid or done.get("native_exit_code") != 0 or done.get("native_released_nonempty_line") is not True
                or any(done.get(k) is not False for k in ("training_permitted", "torch_imported", "transformers_imported"))
                or done.get("model_loads") != 0 or done.get("optimizer_steps") != 0):
                raise obs.ObserverError("graceful role-policy completion differs")
            report["outcome"] = "graceful_role_admission_no_training"
        report["cleanup"] = cleanup(job, case_end, suite_end)
        expected_exits = {(node["pid"], node["creation_filetime"]) for node in report["censuses"][-1]["processes"]}
        exit_rows = report["cleanup"].get("exit_codes", [])
        if (report["cleanup"].get("all_retained_handles_exited") is not True or report["cleanup"].get("job_active_count") != 0
            or len(exit_rows) != len(expected_exits)
            or {(row["pid"], row["creation_filetime"]) for row in exit_rows} != expected_exits):
            raise obs.ObserverError("cleanup does not cover exact last held identity set")
        if injection == "none":
            if len(exit_rows) != 5 or any(x["exit_code"] != 0 for x in exit_rows):
                raise obs.ObserverError("graceful five-role controls exited nonzero")
        else:
            killed_python = {launcher.pid, actual.pid} | ({extra.pid} if injection == "python" else set())
            if any(row["exit_code"] != 0xE003 for row in exit_rows if row["pid"] in killed_python):
                raise obs.ObserverError("held Python controls lack exact Job termination exit")
        report["passed"] = time.perf_counter() <= case_end
    except BaseException as error:
        report["error"] = base.public_error(error, directory, output, *(paths.values()))
        if job is not None:
            try: job.terminate(); report["failure_cleanup"] = cleanup(job, case_end, suite_end)
            except BaseException as cleanup_error: report["cleanup_error"] = base.public_error(cleanup_error)
    finally:
        if job is not None:
            for field, action in (("job_close_error", job.close), ("process_handle_close_error", job.close_refs)):
                try: action()
                except BaseException as error: report[field] = base.public_error(error); report["passed"] = False
    report["completed_at"] = base.utc_now(); report["completed_perf_counter"] = time.perf_counter()
    report["wall_seconds"] = report["completed_perf_counter"] - started
    if report["completed_perf_counter"] > case_end:
        report["passed"] = False; report["case_wall_budget_exceeded"] = True
    return report


def validate_freeze(protocol_path, freeze_path, paths):
    protocol, freeze = obs.read_small(protocol_path), obs.read_small(freeze_path)
    if (protocol.get("config") != CONFIG or protocol.get("experiment_id") != EXPERIMENT_ID
        or tuple(protocol.get("source_paths", [])) != SOURCE_PATHS or tuple(protocol.get("frozen_dependency_paths", [])) != DEPENDENCY_PATHS
        or tuple(protocol.get("review_tool_paths", [])) != REVIEW_TOOL_PATHS
        or [(c["id"], c["injection"]) for c in protocol.get("cases_in_order", [])] != list(CASES)
        or protocol.get("policy_contract") != POLICY_CONTRACT
        or protocol.get("self_executable_roles") != SELF_EXECUTABLE_ROLES
        or protocol.get("retained_os_image_roles") != RETAINED_OS_IMAGE_ROLES
        or protocol.get("training_permitted") is not False or freeze.get("protocol_sha256") != obs.sha256_file(protocol_path)):
        raise obs.ObserverError("role-policy protocol/config/hash differs")
    for field, names in (("new_source_files_sha256", SOURCE_PATHS), ("frozen_dependency_files_sha256", DEPENDENCY_PATHS),
            ("review_tools_sha256", REVIEW_TOOL_PATHS)):
        values = freeze.get(field, {})
        if set(values) != set(names) or any(obs.sha256_file(ROOT / n) != values[n] for n in names):
            raise obs.ObserverError("role-policy source/dependency freeze differs: " + field)
    if set(paths) != {"launcher", "base_python", "native", "conhost"}:
        raise obs.ObserverError("role-policy exact executable role set differs")
    system32 = Path(os.environ["SystemRoot"]) / "System32"
    if (dual.canonical_path(paths["native"]) != dual.canonical_path(system32 / "cmd.exe")
        or dual.canonical_path(paths["conhost"]) != dual.canonical_path(system32 / "conhost.exe")):
        raise obs.ObserverError("native/auxiliary paths differ from exact System32 images")
    hashes = {role: obs.sha256_file(path) for role, path in paths.items()}
    if freeze.get("executables_sha256") != hashes:
        raise obs.ObserverError("role-policy executable freeze differs")
    if freeze.get("executable_path_sha256") != {role: dual.path_hash(path) for role, path in paths.items()}:
        raise obs.ObserverError("role-policy opaque executable path freeze differs")
    declared, frozen = (dt.datetime.fromisoformat(v) for v in (protocol["predeclared_at"], freeze["frozen_at"]))
    if declared.tzinfo is None or frozen.tzinfo is None or not declared <= frozen <= dt.datetime.now(dt.timezone.utc):
        raise obs.ObserverError("invalid role-policy freeze chronology")
    return protocol, freeze, hashes


def acceptance(python_path, base_python_path, native_path, conhost_path, protocol_path, freeze_path, output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = {"schema_version": 1, "experiment_id": EXPERIMENT_ID, "started_at": base.utc_now(),
        "started_perf_counter": started, "training_permitted": False, "model_loads": 0, "optimizer_steps": 0,
        "os_name": os.name, "no_fallback": True, "policy_contract": dict(POLICY_CONTRACT),
        "self_executable_roles": dict(SELF_EXECUTABLE_ROLES), "retained_os_image_roles": dict(RETAINED_OS_IMAGE_ROLES),
        "passed": False, "cases": [], "scope": "bounded stdlib role admission only; no training/loader/provider/production proof; no old child identification"}
    paths = {role: Path(path).resolve() for role, path in zip(("launcher", "base_python", "native", "conhost"),
        (python_path, base_python_path, native_path, conhost_path))}
    try:
        protocol, freeze, hashes = validate_freeze(protocol_path, freeze_path, paths)
        report.update(protocol_sha256=obs.sha256_file(protocol_path), implementation_sha256=obs.sha256_file(freeze_path),
            source_sha256=freeze["new_source_files_sha256"], dependencies_sha256=freeze["frozen_dependency_files_sha256"],
            review_tools_sha256=freeze["review_tools_sha256"], executables_sha256=hashes,
            executable_path_sha256=dict(freeze["executable_path_sha256"]),
            protocol_predeclared_at=protocol["predeclared_at"], implementation_frozen_at=freeze["frozen_at"])
        if os.name != "nt": raise obs.UnsupportedPlatform("Windows role-policy control only; no fallback")
        suite_end = started + CONFIG["suite_timeout_seconds"]
        for spec in CASES: report["cases"].append(run_case(spec, paths, hashes, output, suite_end))
        report["passed"] = len(report["cases"]) == 3 and all(c["passed"] for c in report["cases"]) and time.perf_counter() <= suite_end
    except BaseException as error:
        report["error"] = base.public_error(error, output, protocol_path, freeze_path, *(paths.values()))
    report["completed_at"] = base.utc_now(); report["completed_perf_counter"] = time.perf_counter()
    report["wall_seconds"] = report["completed_perf_counter"] - started
    if report["wall_seconds"] > CONFIG["suite_timeout_seconds"]: report["passed"] = False
    obs.write_new(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("python", "base-python", "native", "conhost", "protocol", "freeze", "output", "directory"):
        parser.add_argument("--" + name, type=Path)
    for name in ("worker", "helper"): parser.add_argument("--" + name, action="store_true")
    for name in ("nonce", "helper-nonce"): parser.add_argument("--" + name)
    parser.add_argument("--injection", choices=("none", "python", "native"), default="none")
    for name in ("case-end", "suite-end"): parser.add_argument("--" + name, type=float)
    args = parser.parse_args(argv)
    if args.worker or args.helper:
        if any(v is None for v in (args.directory, args.nonce, args.case_end, args.suite_end)):
            parser.error("child requires directory, nonce and fixed deadlines")
        obs.validate_nonce(args.nonce)
        if args.helper: dual.helper(args.directory, args.nonce, args.case_end, args.suite_end)
        else:
            if any(v is None for v in (args.helper_nonce, args.base_python, args.native)):
                parser.error("worker requires helper nonce and explicit frozen executables")
            obs.validate_nonce(args.helper_nonce)
            worker(args.directory, args.nonce, args.helper_nonce, args.base_python, args.native, args.injection, args.case_end, args.suite_end)
        return 0
    if any(v is None for v in (args.python, args.base_python, args.native, args.conhost, args.protocol, args.freeze, args.output)):
        parser.error("acceptance requires all four executables, protocol, freeze and fresh output")
    report = acceptance(args.python, args.base_python, args.native, args.conhost, args.protocol, args.freeze, args.output)
    print("role policy: " + ("passed (training remains forbidden)" if report["passed"] else "FAILED"))
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
