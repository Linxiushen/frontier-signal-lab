"""Offline pinned-Pythia dense-harness engineering integration, version 2.

Importing this file and its mock tests never loads ML packages or starts a child.
Only a root-reviewed freeze permits the single Windows acceptance suite. Frozen
historical loaders, training helpers and process observers are reused unchanged.
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
from experiments import activation_cost_probe as cost
from experiments import process_observer as obs
from experiments import process_observer_probe as base
from experiments import workload_observer_probe as work
from experiments import role_policy_probe as role
from experiments import dual_identity_census as dual

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
EXPERIMENT_ID = "windows-pinned-pythia-training-observer-integration-v2"
SOURCE_PATHS = ("experiments/training_observer_v2.py", "tests/test_training_observer_v2.py")
REVIEW_TOOL_PATHS = ("scripts/audit_training_observer_v2.py", "tests/test_training_observer_v2_auditor.py")
DEPENDENCY_PATHS = ("experiments/activation_cost_probe.py", "scripts/capture_real_activation.py",
    "experiments/process_observer.py", "experiments/process_observer_probe.py",
    "experiments/workload_observer_probe.py", "fixtures/process-observer/protocol.json",
    "fixtures/process-observer/implementation.json", "fixtures/workload-observer/protocol.json",
    "fixtures/workload-observer/implementation.json", "fixtures/activation-cost/train.json",
    "fixtures/activation-cost/manifest.json", "fixtures/activation-cost/protocol.json",
    "fixtures/activation-cost/implementation.json", "experiments/training_observer_probe.py",
    "experiments/role_policy_probe.py", "experiments/dual_identity_census.py",
    "fixtures/role-policy-probe/protocol.json", "fixtures/role-policy-probe/implementation.json")
CONFIG = {"torch_version": "2.9.1+cpu", "transformers_version": "4.57.3",
    "seed": 503, "optimizer_steps": 2, "intraop_threads": 1, "interop_threads": 1,
    "train_blocks": 128, "batch_size": 2, "sequence_input_tokens": 64,
    "trainable_parameter_count": 14067712, "parameter_tensors": 76,
    "manual_allocation_bytes": 67108864, "private_cap_increment_bytes": 50331648,
    "minimum_allocation_delta_bytes": 58720256, "memory_bracket_tolerance_bytes": 4194304,
    "sampler_interval_seconds": 0.02, "maximum_recorded_sample_gap_seconds": 0.5,
    "handshake_timeout_seconds": 5.0, "import_timeout_seconds": 20.0,
    "load_timeout_seconds": 25.0, "training_timeout_seconds": 15.0,
    "barrier_timeout_seconds": 5.0, "overhead_window_seconds": 0.4,
    "busy_timeout_seconds": 1.5, "busy_minimum_cpu_seconds": 0.25,
    "busy_backstop_seconds": 10.0, "cap_ready_to_termination_maximum_seconds": 1.0,
    "cleanup_timeout_seconds": 4.0, "case_timeout_seconds": 60.0,
    "total_timeout_seconds": 180.0, "prehandshake_expected_exit_code": 37,
    "import_failure_expected_exit_code": 38}
CASES = (("healthy_dense2", "healthy", 67108864),
    ("dense2_busy_deadline", "timeout", 0), ("dense2_private_cap64", "private_cap", 67108864),
    ("prehandshake_exit37", "prehandshake_fail", 0),
    ("injected_import_failure38", "import_fail", 0))
STAGES = ("preimport", "postimport", "postload", "postupdate")
OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
    "TOKENIZERS_PARALLELISM": "false", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"}


def stage_deadline(seconds, case_deadline, suite_deadline):
    return min(time.perf_counter() + seconds, case_deadline, suite_deadline)


def wait(directory, name, nonce, case_deadline, suite_deadline, seconds=None, poll=None):
    return work.wait_receipt(directory, name, stage_deadline(
        CONFIG["barrier_timeout_seconds"] if seconds is None else seconds,
        case_deadline, suite_deadline), nonce, poll=poll)


def os_image(backend, ref, expected_path, expected_hash):
    """Query the retained handle, never sys.executable or a worker image claim."""
    query = backend.k.QueryFullProcessImageNameW
    query.argtypes = [obs.HANDLE, obs.DWORD, ct.c_wchar_p, ct.POINTER(obs.DWORD)]
    query.restype = obs.BOOL
    image, size = ct.create_unicode_buffer(32768), obs.DWORD(32768)
    backend.checked(query(ref.handle, 0, image, ct.byref(size)), "QueryFullProcessImageNameW actual image")
    if os.path.normcase(os.path.realpath(image.value)) != os.path.normcase(os.path.realpath(expected_path)):
        raise obs.ObserverError("OS process image differs from frozen expected executable")
    if obs.sha256_file(image.value) != expected_hash:
        raise obs.ObserverError("OS process image bytes differ from freeze")
    if backend.creation(ref.handle) != ref.creation_filetime or int(backend.k.GetProcessId(ref.handle)) != ref.pid:
        raise obs.ObserverError("OS process image query retained identity changed")
    return {"pid": ref.pid, "creation_filetime": ref.creation_filetime,
        "basename": Path(image.value).name, "sha256": expected_hash,
        "queried_from_retained_handle": True, "matches_frozen_path_and_hash": True,
        "verified_perf_counter": time.perf_counter()}


def timed_call(kind, function, overhead):
    wall0, cpu0 = time.perf_counter(), time.process_time()
    result = function()
    wall1, cpu1 = time.perf_counter(), time.process_time()
    overhead.append({"kind": kind, "started_perf_counter": wall0,
        "completed_perf_counter": wall1, "wall_seconds": wall1 - wall0,
        "started_process_cpu_seconds": cpu0, "completed_process_cpu_seconds": cpu1,
        "parent_process_cpu_seconds": cpu1 - cpu0})
    return result


def sample(job, actual, report):
    return timed_call("actual_interpreter_memory_and_cpu_query",
        lambda: work.parent_sample(job, actual, report["samples"]), report["parent_query_costs"])


def descendants_at_snapshot(parents, root):
    selected = {root}
    for _ in range(16):
        found = {pid for pid, parent in parents.items() if parent in selected}
        if found <= selected:
            return selected
        selected.update(found)
    raise obs.ObserverError("descendant tree exceeds bounded16level snapshot traversal")


def inventory(job, launcher, actual, native, report, label):
    """Current role census; the frozen evaluator remains a no-ML identity rule.

    Training authorization belongs to this new protocol, never to the immutable
    role-policy producer's training_permitted=False metadata.
    """
    known = {launcher.pid: (launcher.creation_filetime, "launcher"),
        actual.pid: (actual.creation_filetime, "base_python")}
    if native is not None:
        known[native.pid] = (native.creation_filetime, "native")
    paths = report.pop("_paths")
    try:
        snapshot, decision = timed_call("held_role_census_and_liveness",
            lambda: role.policy_stage(job, launcher, known, paths, report["executables_sha256"], report,
                label, "training-v2", report.get("pinned_auxiliaries", {}),
                report["case_deadline_perf_counter"], report["suite_deadline_perf_counter"]),
            report["parent_query_costs"])
    finally:
        report["_paths"] = paths
    if decision.get("admitted") is not True:
        raise obs.ObserverError("training-v2 current role policy rejected held stage")
    report["pinned_auxiliaries"] = decision["pinned_auxiliaries"]
    return snapshot


CONTROL_PURPOSE = "pinned offline training observer v2; fixed engineering controls"
CONTROL_PLAN = [("create-native.json", "create-native", "before_native", 0)]
for _stage_index, _stage in enumerate((*STAGES, "allocated"), 1):
    CONTROL_PLAN.extend([(_stage + "-parent-done.json", "parent-sampled", _stage, _stage_index),
        (_stage + "-continue.json", "continue", _stage, _stage_index)])
CONTROL_PLAN.append(("finish.json", "finish", "allocated", 5))
CONTROL_PLAN = tuple(CONTROL_PLAN)
PROVIDER_DENIED_EVENTS = ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname",
    "socket.gethostbyname_ex", "socket.gethostbyaddr", "socket.sendto", "socket.bind")


class LocalProviderGuard:
    """Deny Python-audited outbound/listening socket actions, no native sandbox."""
    def __init__(self):
        self.installed = False
        self.probe_denials = 0
        self.unexpected_denied_events = []
        self.probing = False

    def audit(self, event, args):
        if event in PROVIDER_DENIED_EVENTS:
            if self.probing:
                self.probe_denials += 1
            else:
                self.unexpected_denied_events.append(event)
            raise PermissionError("local-only training denies Python socket provider I/O: " + event)

    def install(self):
        sys.addaudithook(self.audit)
        self.installed = True
        self.probing = True
        try:
            try:
                sys.audit("socket.connect", None, ("127.0.0.1", 9))
            except PermissionError:
                pass
            else:
                raise obs.ObserverError("provider guard synthetic audit denial missing")
        finally:
            self.probing = False
        if self.probe_denials != 1:
            raise obs.ObserverError("provider guard exact probe count differs")

    def receipt(self):
        return {"installed": self.installed, "python_audit_only": True,
            "native_network_sandbox": False, "external_providers_permitted": False,
            "synthetic_probe_denials": self.probe_denials,
            "unexpected_denied_events": list(self.unexpected_denied_events),
            "denied_audit_events": list(PROVIDER_DENIED_EVENTS)}


def validate_provider(value):
    return (value.get("installed") is True and value.get("python_audit_only") is True
        and value.get("native_network_sandbox") is False and value.get("external_providers_permitted") is False
        and type(value.get("synthetic_probe_denials")) is int and value["synthetic_probe_denials"] == 1
        and value.get("unexpected_denied_events") == []
        and value.get("denied_audit_events") == list(PROVIDER_DENIED_EVENTS))


def control(directory, filename, nonce, command, report):
    decision = report["role_decisions"][-1]
    now = time.perf_counter()
    index = len(report.setdefault("controller_controls", []))
    if (decision.get("admitted") is not True or decision.get("completed_perf_counter", now + 1) > now
        or index >= len(CONTROL_PLAN)
        or (filename, command, decision.get("label"), decision.get("decision_index")) != CONTROL_PLAN[index]
        or now >= min(report["case_deadline_perf_counter"], report["suite_deadline_perf_counter"])):
        raise obs.ObserverError("training control lacks current completed role admission/budget")
    message = base.envelope(nonce, "controller", command=command, purpose=CONTROL_PURPOSE,
        training_v2_authorized=True, role_policy_admitted=True,
        role_decision_index=decision["decision_index"], role_decision_label=decision["label"],
        control_index=index, emitted_perf_counter=now)
    obs.write_new(directory / filename, message)
    report["controller_controls"].append({"filename": filename, **message})


def require_control(directory, filename, nonce, command, label, decision_index, state, case_end, suite_end):
    value = base.wait_json(directory / filename,
        stage_deadline(CONFIG["barrier_timeout_seconds"], case_end, suite_end), nonce, "controller")
    accepted = time.perf_counter()
    emitted = value.get("emitted_perf_counter")
    if (value.get("command") != command or value.get("purpose") != CONTROL_PURPOSE
        or value.get("training_v2_authorized") is not True or value.get("role_policy_admitted") is not True
        or value.get("role_decision_label") != label or type(value.get("role_decision_index")) is not int
        or value["role_decision_index"] != decision_index or type(value.get("control_index")) is not int
        or value["control_index"] != state["next_index"]
        or type(emitted) not in (int, float) or not math.isfinite(emitted)
        or not state["last_emitted"] <= emitted <= accepted <= min(case_end, suite_end)):
        raise obs.ObserverError("timestamped training-v2 control custody differs")
    state["next_index"] += 1
    state["last_emitted"] = emitted
    obs.write_new(directory / filename.replace(".json", "-accepted.json"),
        base.envelope(nonce, "worker", filename=filename, control_envelope=value,
            accepted_perf_counter=accepted, next_control_index=state["next_index"]))
    return value


def memory_stage(backend, directory, stage, nonce, case_deadline, suite_deadline,
        control_state, provider_guard, **details):
    stage_index = {"preimport": 1, "postimport": 2, "postload": 3, "postupdate": 4, "allocated": 5}[stage]
    obs.write_new(directory / (stage + "-ready.json"), base.envelope(nonce, "worker", stage=stage,
        stage_ready_perf_counter=time.perf_counter(),
        provider_guard=provider_guard.receipt(),
        native_thread_count=work.native_thread_count(backend, os.getpid()), **details))
    obs.write_new(directory / (stage + "-before.json"), base.envelope(nonce, "worker", **backend.self_reading()))
    require_control(directory, stage + "-parent-done.json", nonce, "parent-sampled", stage,
        stage_index, control_state, case_deadline, suite_deadline)
    obs.write_new(directory / (stage + "-after.json"), base.envelope(nonce, "worker", **backend.self_reading()))
    require_control(directory, stage + "-continue.json", nonce, "continue", stage,
        stage_index, control_state, case_deadline, suite_deadline)


def import_packages():
    os.environ.update(OFFLINE_ENV)
    import site
    site.ENABLE_USER_SITE = False
    site.main()
    torch, transformers = importlib.import_module("torch"), importlib.import_module("transformers")
    if str(torch.__version__) != CONFIG["torch_version"] or str(transformers.__version__) != CONFIG["transformers_version"]:
        raise obs.ObserverError("actual ML package version differs from fixed local versions")
    return torch, transformers


def prepare_model(torch, model_dir, fixture):
    preparation_start = time.perf_counter()
    cost.verify_model_assets(model_dir)
    manifest, _, _ = cost.validate_fixture(fixture, verify_holdout=False)
    blocks = cost.load_blocks(Path(fixture) / "train.json", "train", CONFIG["train_blocks"])
    schedule = cost.batch_schedule(CONFIG["train_blocks"], CONFIG["optimizer_steps"], CONFIG["batch_size"], CONFIG["seed"])
    load_start = time.perf_counter()
    model = cost.load_model(model_dir, CONFIG["seed"])
    load_end = time.perf_counter()
    optimizer = cost.optimizer_for(model)
    all_tokens = torch.tensor(blocks, dtype=torch.long)
    batches = [all_tokens[indices] for indices in schedule]
    initial = cost.parameter_hash(model)
    preparation_end = time.perf_counter()
    info = {"model_id": cost.MODEL_ID, "model_revision": cost.MODEL_REVISION,
        "train_sha256": manifest["train_sha256"], "schedule": schedule,
        "schedule_sha256": cost.digest(schedule), "seed": CONFIG["seed"],
        "trainable_parameter_count": sum(p.numel() for p in model.parameters()),
        "parameter_tensors": len(list(model.parameters())), "initial_parameter_sha256": initial,
        "batch_shapes": [list(t.shape) for t in batches], "device": "cpu", "dtype": "torch.float32",
        "intraop_threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "loader_local_files_only": True, "trust_remote_code": False, "attention": "eager",
        "holdout_opened": False, "offline_environment": dict(OFFLINE_ENV),
        "model_load_timing": {"started_perf_counter": load_start, "completed_perf_counter": load_end,
            "wall_seconds": load_end - load_start,
            "boundary": "unchanged cost.load_model call only; offline local load and CPU/eval/layout/thread checks; engineering duration"},
        "preparation_timing": {"started_perf_counter": preparation_start, "completed_perf_counter": preparation_end,
            "wall_seconds": preparation_end - preparation_start,
            "boundary": "asset/train fixture verification, fixed schedule, local model load, optimizer/batches and initial parameter digest; excludes import/stage barrier"}}
    return model, optimizer, batches, info


def two_dense_updates(model, optimizer, batches):
    config = cost.preset_config()
    config.update(token_steps=CONFIG["optimizer_steps"], max_token_loop_seconds=CONFIG["training_timeout_seconds"])
    loop = cost.training_loop(model, optimizer, batches, "token", "dense", [], config=config)
    valid = cost.final_validity(model, optimizer, CONFIG["optimizer_steps"])
    return {"method": "dense", "arm": "token", "optimizer": config["optimizer"],
        "loop": loop, "final_validity": valid, "final_parameter_sha256": cost.parameter_hash(model),
        "no_checkpoint_written": True, "no_holdout_evaluation": True,
        "boundary": "two engineering updates only; losses are trajectory diagnostics, not quality/rescue evidence"}


def worker(directory, nonce, native_path, model_dir, fixture, mode, manual_bytes, case_deadline, suite_deadline):
    if mode == "prehandshake_fail":
        os._exit(CONFIG["prehandshake_expected_exit_code"])
    backend, allocation, child = obs.WindowsBackend(), None, None
    state = {"next_index": 0, "last_emitted": 0.0}
    guard = LocalProviderGuard()
    guard.install()
    try:
        dual.publish_identity(backend, directory, "worker-ready.json", nonce, "worker")
        require_control(directory, "create-native.json", nonce, "create-native", "before_native", 0, state, case_deadline, suite_deadline)
        native_launch_started = time.perf_counter()
        child = subprocess.Popen([str(native_path), *work.NATIVE_ARGUMENTS], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
            creationflags=0x08000000, shell=False)
        obs.write_new(directory / "native-ready.json", base.envelope(nonce, "worker", native_pid=child.pid,
            launch_started_perf_counter=native_launch_started, launch_completed_perf_counter=time.perf_counter(),
            command_arguments=list(work.NATIVE_ARGUMENTS), close_fds=True, stdin_anonymous_pipe=True,
            shell=False, creationflags=0x08000000, stdout_devnull=True, stderr_devnull=True))
        memory_stage(backend, directory, "preimport", nonce, case_deadline, suite_deadline, state, guard,
            torch_imported="torch" in sys.modules, transformers_imported="transformers" in sys.modules)
        if mode == "import_fail":
            import_started = time.perf_counter()
            missing = "training_observer_v2_missing_dependency_" + nonce
            try:
                importlib.import_module(missing)
            except ModuleNotFoundError as error:
                if error.name != missing:
                    raise
                obs.write_new(directory / "expected-import-failure.json", base.envelope(nonce, "worker",
                    stage="import", exception_type="ModuleNotFoundError", missing_module=missing, provider_guard=guard.receipt(),
                    import_started_perf_counter=import_started, failure_perf_counter=time.perf_counter(),
                    torch_imported="torch" in sys.modules, transformers_imported="transformers" in sys.modules,
                    model_loads=0, optimizer_steps=0, expected_exit_code=38))
                os._exit(CONFIG["import_failure_expected_exit_code"])
            raise obs.ObserverError("injected import unexpectedly succeeded")
        import_started = time.perf_counter()
        torch, transformers = import_packages()
        import_completed = time.perf_counter()
        memory_stage(backend, directory, "postimport", nonce, case_deadline, suite_deadline, state, guard,
            import_started_perf_counter=import_started, import_completed_perf_counter=import_completed,
            torch_version=str(torch.__version__), transformers_version=str(transformers.__version__))
        model, optimizer, batches, model_info = prepare_model(torch, model_dir, fixture)
        memory_stage(backend, directory, "postload", nonce, case_deadline, suite_deadline, state, guard, model=model_info)
        operation = two_dense_updates(model, optimizer, batches)
        memory_stage(backend, directory, "postupdate", nonce, case_deadline, suite_deadline, state, guard, operation=operation)
        allocation = backend.allocate(manual_bytes)
        memory_stage(backend, directory, "allocated", nonce, case_deadline, suite_deadline, state, guard,
            manual_allocation_bytes=manual_bytes)
        if mode == "healthy":
            require_control(directory, "finish.json", nonce, "finish", "allocated", 5, state, case_deadline, suite_deadline)
            child.stdin.write(b"done\r\n")
            child.stdin.flush()
            child.stdin.close()
            budget = stage_deadline(CONFIG["barrier_timeout_seconds"], case_deadline, suite_deadline) - time.perf_counter()
            if budget <= 0 or child.wait(timeout=budget) != 0:
                raise obs.ObserverError("healthy native child failed normal completion")
            backend.free(allocation)
            allocation = None
            obs.write_new(directory / "worker-completed.json", base.envelope(nonce, "worker",
                native_exit_code=0, native_released_nonempty_line=True, model_loads=1, optimizer_steps=2,
                provider_guard=guard.receipt()))
            return
        if mode not in ("timeout", "private_cap"):
            raise obs.ObserverError("unknown busy training integration mode")
        busy_start = time.perf_counter()
        obs.write_new(directory / "busy-ready.json", base.envelope(nonce, "worker", perf_counter=busy_start,
            provider_guard=guard.receipt(),
            extra_backward_calls=0, extra_optimizer_steps=0, model_forward_no_grad=True))
        with torch.no_grad():
            logits = model(input_ids=batches[0][:, :-1].contiguous(), use_cache=False).logits
            del logits
            obs.write_new(directory / "busy-first-operation.json", base.envelope(nonce, "worker",
                completed_perf_counter=time.perf_counter(), model_forward_iterations_completed=1,
                provider_guard=guard.receipt(),
                extra_backward_calls=0, extra_optimizer_steps=0, model_forward_no_grad=True))
            backstop = min(busy_start + CONFIG["busy_backstop_seconds"], case_deadline, suite_deadline)
            while time.perf_counter() < backstop:
                logits = model(input_ids=batches[0][:, :-1].contiguous(), use_cache=False).logits
                del logits
        raise obs.ObserverError("busy backstop expired without parent enforcement")
    except BaseException as error:
        obs.write_new(directory / "worker-failure.json", base.envelope(nonce, "worker",
            error=base.public_error(error, directory, native_path, model_dir, fixture, sys.executable)))
        raise
    finally:
        backend.free(allocation)
        if child is not None and child.stdin is not None and not child.stdin.closed:
            child.stdin.close()


def validate_model(info):
    expected_schedule = cost.batch_schedule(128, 2, 2, 503)
    return (all(type(info.get(k)) is int for k in ("seed", "trainable_parameter_count",
            "parameter_tensors", "intraop_threads", "interop_threads"))
        and info.get("model_id") == cost.MODEL_ID and info.get("model_revision") == cost.MODEL_REVISION
        and info.get("train_sha256") == "8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681"
        and info.get("schedule") == expected_schedule and info.get("schedule_sha256") == cost.digest(expected_schedule)
        and info.get("seed") == 503 and info.get("batch_shapes") == [[2, 65], [2, 65]]
        and info.get("trainable_parameter_count") == 14067712 and info.get("parameter_tensors") == 76
        and info.get("device") == "cpu" and info.get("dtype") == "torch.float32"
        and info.get("intraop_threads") == 1 and info.get("interop_threads") == 1
        and info.get("deterministic_algorithms") is True and info.get("loader_local_files_only") is True
        and info.get("trust_remote_code") is False and info.get("attention") == "eager"
        and info.get("holdout_opened") is False and info.get("offline_environment") == OFFLINE_ENV
        and valid_interval(info.get("model_load_timing", {}), CONFIG["load_timeout_seconds"])
        and valid_interval(info.get("preparation_timing", {}), CONFIG["load_timeout_seconds"])
        and info["preparation_timing"]["started_perf_counter"] <= info["model_load_timing"]["started_perf_counter"]
        <= info["model_load_timing"]["completed_perf_counter"] <= info["preparation_timing"]["completed_perf_counter"]
        and is_hash(info.get("initial_parameter_sha256")))


def is_hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def valid_interval(value, maximum):
    start, end, wall = (value.get(k) for k in ("started_perf_counter", "completed_perf_counter", "wall_seconds"))
    return (all(type(v) in (int, float) and math.isfinite(v) for v in (start, end, wall))
        and 0 <= wall <= maximum and end >= start
        and math.isclose(wall, end - start, rel_tol=0, abs_tol=1e-12))


def validate_operation(operation, initial):
    loop, valid = operation.get("loop", {}), operation.get("final_validity", {})
    losses = loop.get("preupdate_batch_losses_recorded_after_updates", [])
    start, end, wall = (loop.get(k) for k in ("loop_perf_counter_start", "loop_perf_counter_end", "training_loop_wall_seconds"))
    timing = (all(type(v) in (int, float) and math.isfinite(v) for v in (start, end, wall))
        and 0 <= wall <= CONFIG["training_timeout_seconds"] and end >= start
        and math.isclose(wall, end - start, rel_tol=0, abs_tol=1e-12))
    return (operation.get("method") == "dense" and operation.get("arm") == "token"
        and operation.get("optimizer") == cost.preset_config()["optimizer"]
        and type(loop.get("steps_completed")) is int and loop["steps_completed"] == 2
        and loop.get("training_target_positions") == 256 and timing
        and isinstance(losses, list) and len(losses) == 2
        and all(type(v) in (int, float) and math.isfinite(v) for v in losses)
        and valid.get("final_parameter_gradient_moments_finite") is True
        and valid.get("optimizer_counters") == [2] * 76
        and all(type(v) is int for v in valid["optimizer_counters"])
        and is_hash(operation.get("final_parameter_sha256")) and operation["final_parameter_sha256"] != initial
        and operation.get("no_checkpoint_written") is True and operation.get("no_holdout_evaluation") is True)


def read_stage(job, launcher, actual, native, directory, label, nonce, report,
        case_deadline, suite_deadline, timeout=None):
    ready = wait(directory, label + "-ready.json", nonce, case_deadline, suite_deadline,
        seconds=timeout, poll=lambda: sample(job, actual, report))
    if ready["pid"] != actual.pid or ready.get("stage") != label or type(ready.get("native_thread_count")) is not int or ready["native_thread_count"] < 1 or not validate_provider(ready.get("provider_guard", {})):
        raise obs.ObserverError("stage identity/thread count differs")
    report.setdefault("stages", {})[label] = ready
    # Keep the frozen worker handshake/comparator, instrument all new parent
    # sampling calls rather than silently omitting the bracket's parent query.
    until = stage_deadline(CONFIG["barrier_timeout_seconds"], case_deadline, suite_deadline)
    poll = lambda: sample(job, actual, report)
    before = work.wait_receipt(directory, label + "-before.json", until, nonce, poll=poll)
    parent = sample(job, actual, report)
    inventory(job, launcher, actual, native, report, label)
    control(directory, label + "-parent-done.json", nonce, "parent-sampled", report)
    after = work.wait_receipt(directory, label + "-after.json", until, nonce, poll=poll)
    comparison = obs.compare_memory_bracket(before, parent, after, CONFIG["memory_bracket_tolerance_bytes"])
    bracket = {"self_before": before, "parent": parent, "self_after": after, "comparison": comparison}
    report.setdefault("memory_brackets", {})[label] = bracket
    if not comparison["passed"]:
        raise obs.ObserverError("training stage memory bracket failed: " + label)
    return bracket


def overhead_windows(job, actual, report, case_deadline, suite_deadline):
    """Matched idle holds describe parent query cost; no training-impact claim."""
    parent = obs.ProcessRef(job.backend, job.backend.k.GetCurrentProcess())
    rows = []
    # Borrowed pseudo-handle is never retained/closed by ProcessRef here.
    for enabled in (False, True):
        start, cpu0 = time.perf_counter(), work.native_process_cpu(job.backend, parent)
        until = min(start + CONFIG["overhead_window_seconds"], case_deadline, suite_deadline)
        if until < start + CONFIG["overhead_window_seconds"]:
            raise obs.ObserverError("insufficient budget for fixed overhead window")
        query_start, sample_start = len(report["parent_query_costs"]), len(report["samples"])
        while time.perf_counter() < until:
            if enabled:
                sample(job, actual, report)
                timed_call("Toolhelp_process_tree_snapshot", job.backend.snapshot, report["parent_query_costs"])
            time.sleep(min(CONFIG["sampler_interval_seconds"], max(0, until - time.perf_counter())))
        end, cpu1 = time.perf_counter(), work.native_process_cpu(job.backend, parent)
        rows.append({"sampling_enabled": enabled, "started_perf_counter": start,
            "completed_perf_counter": end, "wall_seconds": end - start,
            "parent_native_cpu_start_seconds": cpu0, "parent_native_cpu_end_seconds": cpu1,
            "parent_native_cpu_delta_seconds": cpu1 - cpu0,
            "query_cost_index_start": query_start, "query_cost_index_end": len(report["parent_query_costs"]),
            "sample_index_start": sample_start, "sample_index_end": len(report["samples"])})
    report["held_parent_overhead_windows"] = rows
    report["parent_overhead_boundary"] = "idle held worker, fixed nonsampling then sampling; OS CPU quantized; query clocks include instrumentation; no causal training slowdown estimate"


def verify_cleanup(report, mode):
    cleanup = report["cleanup"]
    expected = ({(row["pid"], row["creation_filetime"]) for row in report["censuses"][-1]["processes"]}
        if report["censuses"] else {(report["launcher"]["pid"], report["launcher"]["creation_filetime"])})
    exits = cleanup.get("exit_codes", [])
    if (cleanup.get("all_retained_handles_exited") is not True or cleanup.get("job_active_count") != 0
        or len(exits) != len(expected)
        or {(row["pid"], row["creation_filetime"]) for row in exits} != expected):
        raise obs.ObserverError("training-v2 cleanup does not cover exact retained role identities")
    if mode == "healthy" and (len(exits) != 5 or any(row["exit_code"] != 0 for row in exits)):
        raise obs.ObserverError("healthy five-role cleanup is not exact exit0")
    if mode in ("timeout", "private_cap"):
        held_python = {row["pid"] for row in report["role_decisions"][-1]["primary_roles"]
            if row["role"] in ("launcher", "base_python")}
        if any(row["exit_code"] != 0xE003 for row in exits if row["pid"] in held_python):
            raise obs.ObserverError("busy held Python identities lack exact Job termination exit")
    if mode == "import_fail":
        python_pids = {row["pid"] for row in report["role_decisions"][-1]["primary_roles"]
            if row["role"] in ("launcher", "base_python")}
        if any(row["exit_code"] != 38 for row in exits if row["pid"] in python_pids):
            raise obs.ObserverError("precise import-failure Python identities lack exit38")
    report["cleanup_exact_retained_identity_set"] = True


def verify_controls(directory, report, mode, actual_pid):
    rows = report.get("controller_controls", [])
    expected_count = {"healthy": 12, "timeout": 11, "private_cap": 11,
        "prehandshake_fail": 0, "import_fail": 3}[mode]
    if len(rows) != expected_count:
        raise obs.ObserverError("training-v2 emitted control count differs from fixed mode")
    report["worker_controls"] = []
    for index, row in enumerate(rows):
        accepted = obs.read_small(directory / row["filename"].replace(".json", "-accepted.json"))
        emitted = {k: v for k, v in row.items() if k != "filename"}
        if (accepted.get("pid") != actual_pid or accepted.get("role") != "worker"
            or accepted.get("nonce") != report["nonce"] or accepted.get("filename") != row["filename"]
            or accepted.get("control_envelope") != emitted or accepted.get("next_control_index") != index + 1
            or not row["emitted_perf_counter"] <= accepted.get("accepted_perf_counter", -1)
            <= report["case_deadline_perf_counter"]):
            raise obs.ObserverError("saved worker control acceptance differs from emitted envelope/timing")
        report["worker_controls"].append(accepted)
    accepted_by_name = {row["filename"]: row["accepted_perf_counter"] for row in report["worker_controls"]}
    actions = []
    if mode != "prehandshake_fail":
        actions.append(("create-native.json", report["native_descendant"]["launch_receipt"]["launch_started_perf_counter"]))
    if mode == "import_fail":
        actions.append(("preimport-continue.json", report["import_failure_receipt"]["import_started_perf_counter"]))
    elif mode not in ("prehandshake_fail",):
        actions.extend([("preimport-continue.json", report["stages"]["postimport"]["import_started_perf_counter"]),
            ("postimport-continue.json", report["stages"]["postload"]["model"]["preparation_timing"]["started_perf_counter"]),
            ("postload-continue.json", report["stages"]["postupdate"]["operation"]["loop"]["loop_perf_counter_start"]),
            ("postupdate-continue.json", report["memory_brackets"]["allocated"]["self_before"]["perf_counter"])])
        if mode in ("timeout", "private_cap"):
            actions.append(("allocated-continue.json", report["busy_ready"]["perf_counter"]))
    if any(accepted_by_name[name] > started for name, started in actions):
        raise obs.ObserverError("worker action precedes its authenticated control acceptance")
    report["control_custody_verified"] = True


def run_case(spec, python_path, base_python_path, native_path, conhost_path, model_dir, fixture, freeze, output, suite_deadline):
    case_id, mode, manual_bytes = spec
    directory = output / case_id
    directory.mkdir()
    nonce, started = secrets.token_hex(32), time.perf_counter()
    case_deadline = min(started + CONFIG["case_timeout_seconds"], suite_deadline)
    report = {"id": case_id, "mode": mode, "nonce": nonce, "manual_allocation_bytes": manual_bytes,
        "started_at": base.utc_now(), "started_perf_counter": started, "passed": False,
        "samples": [], "parent_query_costs": [], "outcome": None, "censuses": [], "role_decisions": [],
        "case_deadline_perf_counter": case_deadline, "suite_deadline_perf_counter": suite_deadline,
        "executables_sha256": dict(freeze["executables_sha256"]),
        "executable_path_sha256": dict(freeze["executable_path_sha256"]),
        "_paths": {"launcher": python_path, "base_python": base_python_path, "native": native_path, "conhost": conhost_path}}
    job = None
    try:
        if started >= suite_deadline:
            raise obs.ObserverError("suite deadline expired before case")
        job = obs.WindowsJob()
        launcher = job.start_suspended([str(python_path), "-S", str(SCRIPT), "--worker", "--directory", str(directory),
            "--nonce", nonce, "--native", str(native_path), "--model-dir", str(model_dir), "--fixture", str(fixture),
            "--mode", mode, "--manual-bytes", str(manual_bytes), "--case-deadline", str(case_deadline),
            "--suite-deadline", str(suite_deadline)], cwd=ROOT)
        report["launcher"] = {"pid": launcher.pid, "creation_filetime": launcher.creation_filetime,
            "assigned_while_suspended": True, "job_handle_inherited": False}
        until = stage_deadline(CONFIG["handshake_timeout_seconds"], case_deadline, suite_deadline)
        if mode == "prehandshake_fail":
            code = work.require_exit(launcher, 37, until)
            absent = not (directory / "worker-ready.json").exists()
            report["prehandshake_control"] = {"exit_code": code, "handshake_absent": absent,
                "actual_interpreter_identity_unavailable": True}
            if not absent:
                raise obs.ObserverError("prehandshake control unexpectedly authenticated")
            report["cleanup"] = work.cleanup(job, case_deadline, suite_deadline)
            report["outcome"] = "expected_prehandshake_exit37"
        else:
            ready = work.wait_receipt(directory, "worker-ready.json", until, nonce)
            actual, ancestry = job.authenticate(ready, nonce, "worker", launcher)
            report["worker_identity"] = {"self_receipt": ready, "verified_ancestry": ancestry,
                "launcher_differs_from_interpreter": launcher.pid != actual.pid,
                "os_image": os_image(job.backend, actual, base_python_path, freeze["base_python_executable_sha256"]),
                **dual.verify_self_executable(ready, "worker", report["_paths"], report["executables_sha256"])}
            report["launcher"]["os_image"] = os_image(job.backend, launcher, python_path, freeze["python_executable_sha256"])
            if launcher.pid == actual.pid:
                raise obs.ObserverError("frozen venv launcher must differ from actual interpreter")
            inventory(job, launcher, actual, None, report, "before_native")
            control(directory, "create-native.json", nonce, "create-native", report)
            native_ready = work.wait_receipt(directory, "native-ready.json", until, nonce)
            native, report["native_descendant"] = work.verify_native_child(job, actual, native_ready,
                native_path, freeze["native_executable_sha256"])
            read_stage(job, launcher, actual, native, directory, "preimport", nonce, report, case_deadline, suite_deadline)
            preimport = report["stages"]["preimport"]
            if preimport.get("torch_imported") is not False or preimport.get("transformers_imported") is not False:
                raise obs.ObserverError("ML imported before authenticated release")
            control(directory, "preimport-continue.json", nonce, "continue", report)
            if mode == "import_fail":
                failure = wait(directory, "expected-import-failure.json", nonce, case_deadline, suite_deadline)
                report["import_failure_receipt"] = failure
                if (failure["pid"] != actual.pid or failure.get("stage") != "import"
                    or failure.get("exception_type") != "ModuleNotFoundError"
                    or failure.get("missing_module") != "training_observer_v2_missing_dependency_" + nonce
                    or failure.get("torch_imported") is not False or failure.get("transformers_imported") is not False
                    or failure.get("model_loads") != 0 or failure.get("optimizer_steps") != 0
                    or failure.get("expected_exit_code") != 38 or not validate_provider(failure.get("provider_guard", {}))):
                    raise obs.ObserverError("injected import failure differs from precise control")
                exit_until = stage_deadline(5, case_deadline, suite_deadline)
                work.require_exit(actual, 38, exit_until)
                work.require_exit(launcher, 38, exit_until)
                report["expected_worker_exit_code"] = 38
                job.terminate()
                report["cleanup"] = work.cleanup(job, case_deadline, suite_deadline)
                report["outcome"] = "expected_injected_import_failure38"
            else:
                for label, timeout in (("postimport", CONFIG["import_timeout_seconds"]),
                        ("postload", CONFIG["load_timeout_seconds"]), ("postupdate", CONFIG["training_timeout_seconds"])):
                    read_stage(job, launcher, actual, native, directory, label, nonce, report, case_deadline, suite_deadline, timeout)
                    details = report["stages"][label]
                    if label == "postimport" and (details.get("torch_version") != CONFIG["torch_version"] or details.get("transformers_version") != CONFIG["transformers_version"]):
                        raise obs.ObserverError("imported ML versions differ")
                    if label == "postload" and not validate_model(details.get("model", {})):
                        raise obs.ObserverError("pinned model/loader/schedule contract failed")
                    if label == "postupdate":
                        if not validate_operation(details.get("operation", {}), report["stages"]["postload"]["model"]["initial_parameter_sha256"]):
                            raise obs.ObserverError("two dense training updates contract failed")
                        if mode == "healthy":
                            overhead_windows(job, actual, report, case_deadline, suite_deadline)
                    control(directory, label + "-continue.json", nonce, "continue", report)
                baseline = report["memory_brackets"]["postupdate"]
                private_limit = baseline["parent"]["memory"]["private_bytes"] + CONFIG["private_cap_increment_bytes"]
                allocated = read_stage(job, launcher, actual, native, directory, "allocated", nonce, report, case_deadline, suite_deadline)
                report["allocation_check"] = base.check_allocation(baseline, allocated, manual_bytes)
                if not report["allocation_check"]["passed"]:
                    raise obs.ObserverError("post-training touched allocation delta failed")
                if mode == "healthy":
                    report["healthy_memory_limit_disabled"] = True
                    report["prefinish_live_members"] = work.live_member_receipts(job, actual, native)
                    control(directory, "allocated-continue.json", nonce, "continue", report)
                    control(directory, "finish.json", nonce, "finish", report)
                    done = wait(directory, "worker-completed.json", nonce, case_deadline, suite_deadline)
                    report["healthy_completion"] = done
                    if (done["pid"] != actual.pid or done.get("native_exit_code") != 0
                        or done.get("native_released_nonempty_line") is not True
                        or done.get("model_loads") != 1 or done.get("optimizer_steps") != 2
                        or not validate_provider(done.get("provider_guard", {}))):
                        raise obs.ObserverError("healthy training completion differs")
                    report["cleanup"] = work.cleanup(job, case_deadline, suite_deadline)
                    if any(row["exit_code"] != 0 for row in report["cleanup"]["exit_codes"]):
                        raise obs.ObserverError("healthy retained process exited nonzero")
                    report["outcome"] = "normal_completion"
                else:
                    control(directory, "allocated-continue.json", nonce, "continue", report)
                    busy = wait(directory, "busy-ready.json", nonce, case_deadline, suite_deadline, poll=lambda: sample(job, actual, report))
                    first = wait(directory, "busy-first-operation.json", nonce, case_deadline, suite_deadline, poll=lambda: sample(job, actual, report))
                    report["busy_ready"], report["busy_first_operation"] = busy, first
                    if (busy["pid"] != actual.pid or first["pid"] != actual.pid or first.get("model_forward_iterations_completed") != 1
                        or any(r.get(k) != 0 for r in (busy, first) for k in ("extra_backward_calls", "extra_optimizer_steps"))
                        or any(r.get("model_forward_no_grad") is not True for r in (busy, first))
                        or any(not validate_provider(r.get("provider_guard", {})) for r in (busy, first))):
                        raise obs.ObserverError("busy forward control differs")
                    if mode == "timeout":
                        until = min(busy["perf_counter"] + CONFIG["busy_timeout_seconds"], case_deadline, suite_deadline)
                        report["busy_deadline_perf_counter"] = until
                        while time.perf_counter() < until:
                            sample(job, actual, report)
                            time.sleep(CONFIG["sampler_interval_seconds"])
                        report["outcome"] = "timeout"
                    else:
                        report["actual_interpreter_private_limit_bytes"] = private_limit
                        crossing = [s for s in report["samples"] if s["perf_counter"] >= allocated["self_before"]["perf_counter"] and obs.memory_limit_crossed(s, private_limit)]
                        if not crossing or not obs.memory_limit_crossed(sample(job, actual, report), private_limit):
                            raise obs.ObserverError("post-training private threshold did not cross")
                        report["first_over_limit_sample"] = crossing[0]
                        report["outcome"] = "memory_private_limit"
                    sample(job, actual, report)
                    summary = work.sampling_summary(report["samples"], busy["perf_counter"], time.perf_counter())
                    report["busy_sampling"] = summary
                    if not summary["gap_gate_passed"] or (mode == "timeout" and summary["native_cpu_delta_seconds"] < CONFIG["busy_minimum_cpu_seconds"]):
                        raise obs.ObserverError("active model-forward sampling/CPU progress failed")
                    inventory(job, launcher, actual, native, report, "pretermination")
                    report["pretermination_live_members"] = work.live_member_receipts(job, actual, native)
                    report["termination_request_started_perf_counter"] = time.perf_counter()
                    job.terminate()
                    report["termination_request_returned_perf_counter"] = time.perf_counter()
                    if mode == "private_cap":
                        latency = report["termination_request_returned_perf_counter"] - allocated["self_before"]["perf_counter"]
                        report["allocation_ready_to_termination_seconds"] = latency
                        if not 0 <= latency <= CONFIG["cap_ready_to_termination_maximum_seconds"]:
                            raise obs.ObserverError("private threshold exceeded fixed1s response bound")
                    report["cleanup"] = work.cleanup(job, case_deadline, suite_deadline)
        if time.perf_counter() > case_deadline:
            raise obs.ObserverError("training integration case exceeded wall budget")
        verify_cleanup(report, mode)
        verify_controls(directory, report, mode, actual.pid if mode != "prehandshake_fail" else None)
        report["passed"] = True
    except BaseException as error:
        report["error"] = base.public_error(error, directory, output, python_path, base_python_path, native_path, model_dir, fixture)
        if job is not None:
            try:
                job.terminate()
                report["failure_cleanup"] = work.cleanup(job, case_deadline, suite_deadline)
            except BaseException as cleanup_error:
                report["cleanup_error"] = base.public_error(cleanup_error)
    finally:
        if job is not None:
            for field, action in (("job_close_error", job.close), ("process_handle_close_error", job.close_refs)):
                try:
                    action()
                except BaseException as error:
                    report[field] = base.public_error(error)
                    report["passed"] = False
    report.pop("_paths", None)
    report["completed_at"] = base.utc_now()
    report["completed_perf_counter"] = time.perf_counter()
    report["wall_seconds"] = report["completed_perf_counter"] - started
    if report["completed_perf_counter"] > case_deadline:
        report["passed"] = False
        report["case_wall_budget_exceeded"] = True
    return report


def validate_freeze(protocol_path, freeze_path, python_path, base_python_path, native_path, conhost_path, model_dir, fixture):
    protocol, freeze = obs.read_small(protocol_path), obs.read_small(freeze_path)
    if (protocol.get("experiment_id") != EXPERIMENT_ID or protocol.get("config") != CONFIG
        or tuple(protocol.get("source_paths", [])) != SOURCE_PATHS
        or tuple(protocol.get("frozen_dependency_paths", [])) != DEPENDENCY_PATHS
        or tuple(protocol.get("review_tool_paths", [])) != REVIEW_TOOL_PATHS
        or protocol.get("control_plan") != [{"filename": f, "command": c, "decision_label": l,
            "decision_index": i} for f, c, l, i in CONTROL_PLAN]
        or protocol.get("provider_custody", {}).get("denied_python_audit_events") != list(PROVIDER_DENIED_EVENTS)
        or protocol.get("provider_custody", {}).get("external_providers_permitted") is not False
        or protocol.get("provider_custody", {}).get("native_network_sandbox") is not False
        or [(c["id"], c["mode"], c["manual_allocation_bytes"]) for c in protocol.get("cases_in_order", [])] != list(CASES)):
        raise obs.ObserverError("training protocol/config/paths/case order differs")
    expected_assets = {name: {"bytes": size, "sha256": h} for name, (size, h) in cost.PINNED_ASSETS.items()}
    declared_model = protocol.get("model", {})
    if (declared_model.get("id") != cost.MODEL_ID or declared_model.get("revision") != cost.MODEL_REVISION
        or declared_model.get("assets") != expected_assets or declared_model.get("planned_model_loads") != 3
        or declared_model.get("planned_optimizer_updates") != 6):
        raise obs.ObserverError("protocol pinned model/assets/bounded execution differ")
    if freeze.get("protocol_sha256") != obs.sha256_file(protocol_path):
        raise obs.ObserverError("training protocol not frozen")
    for field, paths in (("new_source_files_sha256", SOURCE_PATHS), ("frozen_dependency_files_sha256", DEPENDENCY_PATHS), ("review_tools_sha256", REVIEW_TOOL_PATHS)):
        values = freeze.get(field, {})
        if set(values) != set(paths) or any(obs.sha256_file(ROOT / p) != values[p] for p in paths):
            raise obs.ObserverError("training source/dependency differs from freeze: " + field)
    for field, path in (("python_executable_sha256", python_path), ("base_python_executable_sha256", base_python_path), ("native_executable_sha256", native_path)):
        if freeze.get(field) != obs.sha256_file(path):
            raise obs.ObserverError("executable differs from training freeze: " + field)
    paths = {"launcher": python_path, "base_python": base_python_path, "native": native_path, "conhost": conhost_path}
    system32 = Path(os.environ["SystemRoot"]) / "System32"
    if (dual.canonical_path(native_path) != dual.canonical_path(system32 / "cmd.exe")
        or dual.canonical_path(conhost_path) != dual.canonical_path(system32 / "conhost.exe")
        or freeze.get("executables_sha256") != {role: obs.sha256_file(path) for role, path in paths.items()}
        or freeze.get("executable_path_sha256") != {role: dual.path_hash(path) for role, path in paths.items()}):
        raise obs.ObserverError("exact four executable files/opaque paths differ from freeze")
    if Path(native_path).name.lower() != "cmd.exe":
        raise obs.ObserverError("training native child must be frozen cmd.exe")
    declared, frozen = (dt.datetime.fromisoformat(v) for v in (protocol["predeclared_at"], freeze["frozen_at"]))
    if declared.tzinfo is None or frozen.tzinfo is None or not declared <= frozen <= dt.datetime.now(dt.timezone.utc):
        raise obs.ObserverError("invalid training freeze chronology")
    cost.verify_model_assets(model_dir)
    cost.validate_fixture(fixture, verify_holdout=False)
    if Path(fixture).resolve() != (ROOT / "fixtures/activation-cost").resolve():
        raise obs.ObserverError("training fixture must be exact frozen local fixture")
    return protocol, freeze


def acceptance(python_path, base_python_path, native_path, conhost_path, model_dir, fixture, protocol_path, freeze_path, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    report = {"schema_version": 1, "experiment_id": EXPERIMENT_ID, "started_at": base.utc_now(),
        "started_perf_counter": started, "passed": False, "cases": [], "no_fallback": True,
        "kind": "pinned offline pretrained loader and two-dense-step harness engineering; no new cost/quality/compression science",
        "platform": platform.platform(), "os_name": os.name,
        "planned_model_loads": 3, "planned_optimizer_updates": 6,
        "boundaries": ["stage snapshots bound child discovery; no provider behavior validated",
            "OS thread counts describe processes; no exact kernel thread ownership proof",
            "current stage memory and process lifetime peaks are distinct; no isolated backward peak or memory saving claim",
            "private cap is sampled post-training threshold, permits overshoot, not an import/training hard cap",
            "held overhead windows are descriptive; no causal estimate of training slowdown",
            "historical RSS/cap and scientific negatives remain unchanged"]}
    try:
        protocol, freeze = validate_freeze(protocol_path, freeze_path, python_path, base_python_path, native_path, conhost_path, model_dir, fixture)
        report.update(protocol_sha256=obs.sha256_file(protocol_path), implementation_sha256=obs.sha256_file(freeze_path),
            source_sha256=freeze["new_source_files_sha256"], frozen_dependencies_sha256=freeze["frozen_dependency_files_sha256"],
            launch_executable_sha256=freeze["python_executable_sha256"], actual_worker_expected_os_image_sha256=freeze["base_python_executable_sha256"],
            native_executable_sha256=freeze["native_executable_sha256"], executables_sha256=freeze["executables_sha256"],
            executable_path_sha256=freeze["executable_path_sha256"], review_tools_sha256=freeze["review_tools_sha256"], model_id=cost.MODEL_ID, model_revision=cost.MODEL_REVISION,
            model_assets={name: {"bytes": size, "sha256": h} for name, (size, h) in cost.PINNED_ASSETS.items()},
            protocol_predeclared_at=protocol["predeclared_at"], implementation_frozen_at=freeze["frozen_at"])
        if os.name != "nt":
            raise obs.UnsupportedPlatform("Windows training integration unavailable; no fallback")
        suite_deadline = started + CONFIG["total_timeout_seconds"]
        for spec in CASES:
            report["cases"].append(run_case(spec, Path(python_path).resolve(), Path(base_python_path).resolve(),
                Path(native_path).resolve(), Path(conhost_path).resolve(), Path(model_dir).resolve(), Path(fixture).resolve(), freeze, output, suite_deadline))
        report["passed"] = len(report["cases"]) == 5 and all(c["passed"] for c in report["cases"]) and time.perf_counter() <= suite_deadline
    except BaseException as error:
        report["error"] = base.public_error(error, output, python_path, base_python_path, native_path, model_dir, fixture, protocol_path, freeze_path)
    report["completed_at"] = base.utc_now()
    report["completed_perf_counter"] = time.perf_counter()
    report["wall_seconds"] = report["completed_perf_counter"] - started
    if report["wall_seconds"] > CONFIG["total_timeout_seconds"]:
        report["passed"] = False
        report["final_wall_budget_exceeded"] = True
    obs.write_new(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("python", "base-python", "native", "conhost", "model-dir", "fixture", "protocol", "freeze", "output", "directory"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--nonce")
    parser.add_argument("--mode", choices=tuple(sorted({s[1] for s in CASES})))
    parser.add_argument("--manual-bytes", type=int)
    parser.add_argument("--case-deadline", type=float)
    parser.add_argument("--suite-deadline", type=float)
    args = parser.parse_args(argv)
    if args.worker:
        if any(v is None for v in (args.directory, args.nonce, args.native, args.model_dir, args.fixture, args.mode, args.manual_bytes, args.case_deadline, args.suite_deadline)):
            parser.error("worker requires directory/nonce/native/model-dir/fixture/mode/manual-bytes/deadlines")
        obs.validate_nonce(args.nonce)
        if args.manual_bytes not in (0, CONFIG["manual_allocation_bytes"]):
            parser.error("manual allocation outside fixed0/64MiB controls")
        worker(args.directory, args.nonce, args.native, args.model_dir, args.fixture, args.mode, args.manual_bytes, args.case_deadline, args.suite_deadline)
        return 0
    if any(v is None for v in (args.python, args.base_python, args.native, args.conhost, args.model_dir, args.fixture, args.protocol, args.freeze, args.output)):
        parser.error("acceptance requires python/base-python/native/model-dir/fixture/protocol/freeze/fresh output")
    result = acceptance(args.python, args.base_python, args.native, args.conhost, args.model_dir, args.fixture, args.protocol, args.freeze, args.output)
    print("pinned Pythia training observer engineering acceptance: " + ("passed" if result["passed"] else "FAILED"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
