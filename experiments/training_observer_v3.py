"""Offline pinned-Pythia dense-harness engineering integration, version 3.

Importing this file and its mock tests never loads ML packages or starts a child.
Only a root-reviewed freeze permits the single Windows acceptance suite. Frozen
historical loaders, training helpers and process observers are reused unchanged.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import datetime as dt
import importlib
import hashlib
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
EXPERIMENT_ID = "windows-pinned-pythia-training-observer-integration-v3"
SOURCE_PATHS = ("experiments/training_observer_v3.py", "tests/test_training_observer_v3.py")
REVIEW_TOOL_PATHS = ("scripts/audit_training_observer_v3.py", "tests/test_training_observer_v3_auditor.py")
DEPENDENCY_PATHS = ("experiments/activation_cost_probe.py", "scripts/capture_real_activation.py",
    "experiments/process_observer.py", "experiments/process_observer_probe.py",
    "experiments/workload_observer_probe.py", "fixtures/process-observer/protocol.json",
    "fixtures/process-observer/implementation.json", "fixtures/workload-observer/protocol.json",
    "fixtures/workload-observer/implementation.json", "fixtures/activation-cost/train.json",
    "fixtures/activation-cost/manifest.json", "fixtures/activation-cost/protocol.json",
    "fixtures/activation-cost/implementation.json", "experiments/training_observer_probe.py",
    "experiments/role_policy_probe.py", "experiments/dual_identity_census.py",
    "fixtures/role-policy-probe/protocol.json", "fixtures/role-policy-probe/implementation.json",
    "experiments/training_observer_v2.py", "fixtures/training-observer-v2/protocol.json",
    "fixtures/training-observer-v2/implementation.json")
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
                label, "training-v3", report.get("pinned_auxiliaries", {}),
                report["case_deadline_perf_counter"], report["suite_deadline_perf_counter"]),
            report["parent_query_costs"])
    finally:
        report["_paths"] = paths
    if decision.get("admitted") is not True:
        raise obs.ObserverError("training-v3 current role policy rejected held stage")
    report["pinned_auxiliaries"] = decision["pinned_auxiliaries"]
    return snapshot


CONTROL_PURPOSE = "pinned offline training observer v3; fixed engineering controls"
CONTROL_PLAN = [("create-native.json", "create-native", "before_native", 0)]
for _stage_index, _stage in enumerate((*STAGES, "allocated"), 1):
    CONTROL_PLAN.extend([(_stage + "-parent-done.json", "parent-sampled", _stage, _stage_index),
        (_stage + "-continue.json", "continue", _stage, _stage_index)])
CONTROL_PLAN.append(("finish.json", "finish", "allocated", 5))
CONTROL_PLAN = tuple(CONTROL_PLAN)
PROVIDER_DENIED_EVENTS = ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname",
    "socket.gethostbyname_ex", "socket.gethostbyaddr", "socket.sendto", "socket.bind")


PROVIDER_POLICY_ID = "urllib3-ipv6-loopback-capability-probe-v1"
PROVIDER_SOURCE_RELATIVE_PATH = "urllib3/util/connection.py"
PROVIDER_SOURCE_SHA256 = "2633bbdb69731e5ccb5cf4e4afd65605d86c7979cc5633126f50c92d5ad74a74"
PROVIDER_FRAME_SCOPE = "contiguous_initial_urllib3_frames"
PROVIDER_CONFIG = {"version_label": "2.8.0", "family_code": 23, "type_code": 1,
    "protocol": 0, "maximum_allowed_probes_per_ML_worker": 1,
    "maximum_diagnostic_events": 4, "maximum_saved_frames": 8,
    "maximum_scanned_frames": 9, "maximum_source_file_bytes": 1048576,
    "caller_function": "_has_ipv6", "caller_line": 127,
    "module_function": "<module>", "module_line": 137}
PROVIDER_PHASES = ("preimport", "import", "postimport", "load", "postload", "train",
    "postupdate", "allocated", "busy", "complete", "injected_import")


def source_digest(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(PROVIDER_CONFIG["maximum_source_file_bytes"] + 1)
    if not 0 < len(raw) <= PROVIDER_CONFIG["maximum_source_file_bytes"]:
        raise obs.ObserverError("provider diagnostic source file outside byte bound")
    return hashlib.sha256(raw).hexdigest()


def safe_code(value):
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 65535 else None


def endpoint_classification(address):
    """Store a fixed classification, never the hostname/address/actual port."""
    shape = "tuple2" if type(address) is tuple and len(address) == 2 else "tuple4" if type(address) is tuple and len(address) == 4 else "string" if type(address) is str else "other"
    host = address[0] if type(address) is tuple and address else address if type(address) is str else None
    port = address[1] if type(address) is tuple and len(address) >= 2 else None
    host_kind = ("exact_ipv6_loopback" if type(host) is str and host == "::1" else
        "ipv4_loopback" if type(host) is str and host == "127.0.0.1" else
        "other_string" if type(host) is str else "not_string")
    port_kind = ("ephemeral_zero" if type(port) is int and port == 0 else
        "nonzero_integer" if type(port) is int and 0 < port <= 65535 else "invalid_or_unavailable")
    return {"shape": shape, "host_kind": host_kind, "port_kind": port_kind, "address_logged": False}


class LocalProviderGuard:
    """A narrowly declared Python capability policy, never a native sandbox.

    Saved frames cover only the initial contiguous urllib3 caller segment,
    stopping at the first outside-package frame. Its filename is resolved to
    classify the boundary; no outside paths/locals are recorded or outside
    source bytes read. More than8 consecutive package frames fails closed.
    """
    def __init__(self, provider_source, allow_local_probe):
        self.provider_source = Path(provider_source).resolve()
        if self.provider_source.parts[-3:] != ("urllib3", "util", "connection.py"):
            raise obs.ObserverError("provider source must explicitly name frozen urllib3/util/connection.py")
        if source_digest(self.provider_source) != PROVIDER_SOURCE_SHA256:
            raise obs.ObserverError("explicit provider source bytes differ from fixed capability policy")
        self.package_root = self.provider_source.parents[2]
        self.urllib3_root = self.provider_source.parents[1]
        self.provider_identity = {"package_relative_path": PROVIDER_SOURCE_RELATIVE_PATH,
            "sha256": PROVIDER_SOURCE_SHA256, "normalized_path_sha256": dual.path_hash(self.provider_source)}
        self.installed = False
        self.probe_denials = 0
        self.probing = False
        self.phase = "preimport"
        self.allowed_budget = 1 if allow_local_probe is True else 0
        self.allowed_count = 0
        self.observed_count = 0
        self.overflow_count = 0
        self.unexpected_denied_events = []
        self.events = []

    def set_phase(self, phase):
        if phase not in PROVIDER_PHASES:
            raise obs.ObserverError("unknown provider-policy phase")
        self.phase = phase

    def capture_frames(self, frame):
        rows, scanned, boundary, errors = [], 0, "stack_end", []
        complete = True
        while frame is not None:
            scanned += 1
            if scanned > PROVIDER_CONFIG["maximum_scanned_frames"]:
                boundary, complete = "limit", False
                break
            try:
                path = Path(frame.f_code.co_filename).resolve()
                try:
                    relative = path.relative_to(self.package_root).as_posix()
                except ValueError:
                    boundary = "outside_selected_package"
                    break
                if not relative.startswith("urllib3/"):
                    boundary = "outside_selected_package"
                    break
                if len(rows) >= PROVIDER_CONFIG["maximum_saved_frames"]:
                    boundary, complete = "limit", False
                    break
                name, line = frame.f_code.co_name, frame.f_lineno
                if (len(relative) > 256 or ".." in Path(relative).parts or path.suffix != ".py"
                    or type(name) is not str or len(name) > 128 or not (name == "<module>" or name.isidentifier())
                    or type(line) is not int or not 0 < line < 1000000):
                    raise ValueError("unsafe source-frame metadata")
                rows.append({"package_relative_path": relative, "function": name, "line": line,
                    "sha256": source_digest(path), "normalized_path_sha256": dual.path_hash(path)})
            except (OSError, ValueError, TypeError, AttributeError, obs.ObserverError):
                boundary, complete = "unsafe", False
                errors.append("source_frame_metadata_or_hash_unavailable")
                break
            frame = frame.f_back
        return {"frames": rows, "frame_scope": PROVIDER_FRAME_SCOPE, "frame_boundary": boundary,
            "frames_scanned_count": min(scanned, PROVIDER_CONFIG["maximum_scanned_frames"]),
            "saved_frame_count": len(rows), "frames_truncated": boundary == "limit",
            "source_hashes_complete": complete, "diagnostic_errors": errors}

    def capture_event(self, event, args, frame):
        family = kind = protocol = None
        address = None
        errors = []
        try:
            if event in ("socket.bind", "socket.connect", "socket.sendto"):
                sock = args[0]
                family, kind, protocol = (safe_code(getattr(sock, key)) for key in ("family", "type", "proto"))
                address = args[1] if event != "socket.sendto" else args[-1]
            elif event == "socket.getaddrinfo":
                address = (args[0], args[1])
                family, kind, protocol = (safe_code(args[index]) for index in (2, 3, 4))
            else:
                address = args[0] if args else None
        except (IndexError, TypeError, ValueError, AttributeError):
            errors.append("socket_metadata_unavailable")
        value = {"event_index": self.observed_count - 1, "event": event,
            "perf_counter": time.perf_counter(), "phase": self.phase,
            "socket_family_code": family, "socket_type_code": kind, "socket_protocol": protocol,
            "endpoint": endpoint_classification(address), **self.capture_frames(frame)}
        value["diagnostic_errors"].extend(errors)
        return value

    def matches_local_probe(self, value):
        frames = value["frames"]
        expected = [("_has_ipv6", 127), ("<module>", 137)]
        return (self.phase == "import" and self.allowed_count < self.allowed_budget
            and value["event"] == "socket.bind" and value["socket_family_code"] == 23
            and value["socket_type_code"] == 1 and value["socket_protocol"] == 0
            and value["endpoint"] == {"shape": "tuple2", "host_kind": "exact_ipv6_loopback",
                "port_kind": "ephemeral_zero", "address_logged": False}
            and value["source_hashes_complete"] is True and value["frames_truncated"] is False
            and value["diagnostic_errors"] == [] and value["frame_boundary"] == "outside_selected_package"
            and len(frames) == 2 and value["saved_frame_count"] == 2 and value["frames_scanned_count"] == 3
            and all(row["package_relative_path"] == PROVIDER_SOURCE_RELATIVE_PATH
                and row["sha256"] == PROVIDER_SOURCE_SHA256
                and row["normalized_path_sha256"] == self.provider_identity["normalized_path_sha256"]
                and row["function"] == function and row["line"] == line
                for row, (function, line) in zip(frames[:2], expected)))

    def audit(self, event, args):
        if event not in PROVIDER_DENIED_EVENTS:
            return
        if self.probing:
            self.probe_denials += 1
            raise PermissionError("synthetic local-only provider denial probe")
        self.observed_count += 1
        if len(self.events) >= PROVIDER_CONFIG["maximum_diagnostic_events"]:
            self.overflow_count += 1
            raise PermissionError("provider diagnostic event budget exhausted")
        value = self.capture_event(event, args, sys._getframe(1))
        allowed = self.matches_local_probe(value)
        value["decision"] = "allowed_local_capability_probe" if allowed else "denied"
        self.events.append(value)
        if allowed:
            self.allowed_count += 1
            return
        self.unexpected_denied_events.append(event)
        raise PermissionError("local-only training denies Python provider event: " + event)

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
        import copy
        return {"installed": self.installed, "python_audit_only": True,
            "native_network_sandbox": False, "external_providers_permitted": False,
            "synthetic_probe_denials": self.probe_denials,
            "unexpected_denied_events": list(self.unexpected_denied_events),
            "denied_audit_events": list(PROVIDER_DENIED_EVENTS), "policy_id": PROVIDER_POLICY_ID,
            "phase": self.phase, "provider_source": dict(self.provider_identity),
            "allowed_local_probe_budget": self.allowed_budget, "allowed_local_probe_count": self.allowed_count,
            "diagnostic_event_limit": PROVIDER_CONFIG["maximum_diagnostic_events"],
            "diagnostic_overflow_count": self.overflow_count, "observed_event_count": self.observed_count,
            "diagnostic_events": copy.deepcopy(self.events)}


def validate_provider(value, phase=None, expected_budget=1):
    if not isinstance(value, dict):
        return False
    phase = value.get("phase") if phase is None else phase
    expected_count = 0 if phase in ("preimport", "injected_import") else 1
    source = value.get("provider_source", {})
    events = value.get("diagnostic_events", [])
    if not isinstance(source, dict) or not isinstance(events, list):
        return False
    valid = (phase in PROVIDER_PHASES and value.get("phase") == phase
        and value.get("installed") is True and value.get("python_audit_only") is True
        and value.get("native_network_sandbox") is False and value.get("external_providers_permitted") is False
        and type(value.get("synthetic_probe_denials")) is int and value["synthetic_probe_denials"] == 1
        and value.get("unexpected_denied_events") == []
        and value.get("denied_audit_events") == list(PROVIDER_DENIED_EVENTS)
        and value.get("policy_id") == PROVIDER_POLICY_ID
        and source.get("package_relative_path") == PROVIDER_SOURCE_RELATIVE_PATH
        and source.get("sha256") == PROVIDER_SOURCE_SHA256 and is_hash(source.get("normalized_path_sha256"))
        and all(type(value.get(key)) is int and value[key] == expected for key, expected in (
            ("allowed_local_probe_budget", expected_budget), ("allowed_local_probe_count", expected_count),
            ("diagnostic_event_limit", 4), ("diagnostic_overflow_count", 0), ("observed_event_count", expected_count)))
        and isinstance(events, list) and len(events) == expected_count)
    if not valid:
        return False
    if not events:
        return True
    row = events[0]
    if not isinstance(row, dict):
        return False
    frames = row.get("frames", [])
    return (row.get("event_index") == 0 and type(row.get("event_index")) is int
        and row.get("event") == "socket.bind" and row.get("phase") == "import"
        and row.get("decision") == "allowed_local_capability_probe"
        and type(row.get("perf_counter")) in (int, float) and math.isfinite(row["perf_counter"])
        and all(type(row.get(k)) is int and row[k] == v for k, v in (
            ("socket_family_code", 23), ("socket_type_code", 1), ("socket_protocol", 0)))
        and row.get("endpoint") == {"shape": "tuple2", "host_kind": "exact_ipv6_loopback",
            "port_kind": "ephemeral_zero", "address_logged": False}
        and row.get("frame_scope") == PROVIDER_FRAME_SCOPE
        and row.get("frame_boundary") == "outside_selected_package"
        and row.get("frames_truncated") is False and row.get("source_hashes_complete") is True
        and row.get("diagnostic_errors") == [] and isinstance(frames, list) and len(frames) == 2
        and type(row.get("saved_frame_count")) is int and row["saved_frame_count"] == len(frames)
        and type(row.get("frames_scanned_count")) is int
        and row["frames_scanned_count"] == 3
        and all(isinstance(frame, dict) and type(frame.get("line")) is int and 0 < frame["line"] < 1000000
            and isinstance(frame.get("function"), str) and len(frame["function"]) <= 128
            and (frame["function"] == "<module>" or frame["function"].isidentifier())
            and isinstance(frame.get("package_relative_path"), str) and len(frame["package_relative_path"]) <= 256
            and frame["package_relative_path"].startswith("urllib3/")
            and ".." not in Path(frame["package_relative_path"]).parts
            and "\\" not in frame["package_relative_path"] and ":" not in frame["package_relative_path"]
            and is_hash(frame.get("sha256")) and is_hash(frame.get("normalized_path_sha256")) for frame in frames)
        and all(frame.get("package_relative_path") == PROVIDER_SOURCE_RELATIVE_PATH
            and frame.get("sha256") == PROVIDER_SOURCE_SHA256
            and frame.get("normalized_path_sha256") == source["normalized_path_sha256"]
            and frame.get("function") == function and frame.get("line") == line
            for frame, (function, line) in zip(frames[:2], (("_has_ipv6", 127), ("<module>", 137)))))


def verify_provider_custody(report, mode):
    """Check exact frozen source and unchanged cumulative import diagnostics."""
    if mode == "prehandshake_fail":
        return
    stages = report["stages"]
    expected_source = {"package_relative_path": PROVIDER_SOURCE_RELATIVE_PATH,
        "sha256": PROVIDER_SOURCE_SHA256,
        "normalized_path_sha256": report["provider_source_path_sha256"]}
    rows = [("preimport", stages["preimport"]["provider_guard"])]
    if mode == "import_fail":
        rows.append(("injected_import", report["import_failure_receipt"]["provider_guard"]))
    else:
        rows.extend((label, stages[label]["provider_guard"]) for label in (*STAGES[1:], "allocated"))
        if mode == "healthy":
            rows.append(("complete", report["healthy_completion"]["provider_guard"]))
        else:
            rows.extend(("busy", report[key]["provider_guard"]) for key in ("busy_ready", "busy_first_operation"))
        imported = stages["postimport"]
        event_time = imported["provider_guard"]["diagnostic_events"][0]["perf_counter"]
        start, end = imported.get("import_started_perf_counter"), imported.get("import_completed_perf_counter")
        if (type(start) not in (int, float) or type(end) not in (int, float)
            or not math.isfinite(start) or not math.isfinite(end) or not start <= event_time <= end):
            raise obs.ObserverError("provider event outside authenticated import interval")
    expected_events = None
    for phase, value in rows:
        if not validate_provider(value, phase, 0 if mode == "import_fail" else 1) or value["provider_source"] != expected_source:
            raise obs.ObserverError("provider receipt differs from exact frozen source/policy")
        if phase != "preimport" and mode != "import_fail":
            if expected_events is None:
                expected_events = value["diagnostic_events"]
            elif value["diagnostic_events"] != expected_events:
                raise obs.ObserverError("provider cumulative event identity changed after import")
    report["provider_custody_verified"] = True


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
        training_v3_authorized=True, role_policy_admitted=True,
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
        or value.get("training_v3_authorized") is not True or value.get("role_policy_admitted") is not True
        or value.get("role_decision_label") != label or type(value.get("role_decision_index")) is not int
        or value["role_decision_index"] != decision_index or type(value.get("control_index")) is not int
        or value["control_index"] != state["next_index"]
        or type(emitted) not in (int, float) or not math.isfinite(emitted)
        or not state["last_emitted"] <= emitted <= accepted <= min(case_end, suite_end)):
        raise obs.ObserverError("timestamped training-v3 control custody differs")
    state["next_index"] += 1
    state["last_emitted"] = emitted
    obs.write_new(directory / filename.replace(".json", "-accepted.json"),
        base.envelope(nonce, "worker", filename=filename, control_envelope=value,
            accepted_perf_counter=accepted, next_control_index=state["next_index"]))
    return value


def memory_stage(backend, directory, stage, nonce, case_deadline, suite_deadline,
        control_state, provider_guard, **details):
    provider_guard.set_phase(stage)
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


def worker(directory, nonce, native_path, provider_source, model_dir, fixture, mode, manual_bytes, case_deadline, suite_deadline):
    if mode == "prehandshake_fail":
        os._exit(CONFIG["prehandshake_expected_exit_code"])
    backend, allocation, child = obs.WindowsBackend(), None, None
    state = {"next_index": 0, "last_emitted": 0.0}
    guard = LocalProviderGuard(provider_source, mode in ("healthy", "timeout", "private_cap"))
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
            guard.set_phase("injected_import")
            import_started = time.perf_counter()
            missing = "training_observer_v3_missing_dependency_" + nonce
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
        guard.set_phase("import")
        import_started = time.perf_counter()
        torch, transformers = import_packages()
        import_completed = time.perf_counter()
        memory_stage(backend, directory, "postimport", nonce, case_deadline, suite_deadline, state, guard,
            import_started_perf_counter=import_started, import_completed_perf_counter=import_completed,
            torch_version=str(torch.__version__), transformers_version=str(transformers.__version__))
        guard.set_phase("load")
        model, optimizer, batches, model_info = prepare_model(torch, model_dir, fixture)
        memory_stage(backend, directory, "postload", nonce, case_deadline, suite_deadline, state, guard, model=model_info)
        guard.set_phase("train")
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
            guard.set_phase("complete")
            obs.write_new(directory / "worker-completed.json", base.envelope(nonce, "worker",
                native_exit_code=0, native_released_nonempty_line=True, model_loads=1, optimizer_steps=2,
                provider_guard=guard.receipt()))
            return
        if mode not in ("timeout", "private_cap"):
            raise obs.ObserverError("unknown busy training integration mode")
        guard.set_phase("busy")
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
            provider_guard=guard.receipt(), phase=guard.phase, failure_perf_counter=time.perf_counter(),
            error=base.public_error(error, directory, native_path, provider_source, model_dir, fixture, sys.executable)))
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
    if ready["pid"] != actual.pid or ready.get("stage") != label or type(ready.get("native_thread_count")) is not int or ready["native_thread_count"] < 1:
        raise obs.ObserverError("stage identity/thread count differs")
    if not validate_provider(ready.get("provider_guard", {}), label, 0 if report["mode"] == "import_fail" else 1):
        raise obs.ObserverError("stage provider guard differs from fixed local probe policy")
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
        raise obs.ObserverError("training-v3 cleanup does not cover exact retained role identities")
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
        raise obs.ObserverError("training-v3 emitted control count differs from fixed mode")
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


def run_case(spec, python_path, base_python_path, native_path, conhost_path, provider_source, model_dir, fixture, freeze, output, suite_deadline):
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
        "provider_source_sha256": freeze["provider_source_sha256"],
        "provider_source_path_sha256": freeze["provider_source_path_sha256"],
        "_paths": {"launcher": python_path, "base_python": base_python_path, "native": native_path, "conhost": conhost_path}}
    job, actual = None, None
    try:
        if started >= suite_deadline:
            raise obs.ObserverError("suite deadline expired before case")
        job = obs.WindowsJob()
        launcher = job.start_suspended([str(python_path), "-S", str(SCRIPT), "--worker", "--directory", str(directory),
            "--nonce", nonce, "--native", str(native_path), "--provider-source", str(provider_source), "--model-dir", str(model_dir), "--fixture", str(fixture),
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
                    or failure.get("missing_module") != "training_observer_v3_missing_dependency_" + nonce
                    or failure.get("torch_imported") is not False or failure.get("transformers_imported") is not False
                    or failure.get("model_loads") != 0 or failure.get("optimizer_steps") != 0
                    or failure.get("expected_exit_code") != 38 or not validate_provider(failure.get("provider_guard", {}), "injected_import", 0)):
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
                        or not validate_provider(done.get("provider_guard", {}), "complete", 1)):
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
                        or any(not validate_provider(r.get("provider_guard", {}), "busy", 1) for r in (busy, first))):
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
        if (directory / "worker-failure.json").exists():
            raise obs.ObserverError("worker failure receipt prevents successful case")
        verify_cleanup(report, mode)
        verify_provider_custody(report, mode)
        verify_controls(directory, report, mode, actual.pid if mode != "prehandshake_fail" else None)
        report["passed"] = True
    except BaseException as error:
        report["error"] = base.public_error(error, directory, output, python_path, base_python_path, native_path, provider_source, model_dir, fixture)
        if job is not None:
            try:
                job.terminate()
                report["failure_cleanup"] = work.cleanup(job, case_deadline, suite_deadline)
            except BaseException as cleanup_error:
                report["cleanup_error"] = base.public_error(cleanup_error)
    finally:
        failure_path = directory / "worker-failure.json"
        if failure_path.exists():
            report["passed"] = False
            try:
                failure = obs.validate_message(obs.read_small(failure_path), nonce, "worker")
                if actual is not None and failure["pid"] != actual.pid:
                    raise obs.ObserverError("worker failure receipt identity differs")
                report["worker_failure_receipt"] = failure
            except BaseException as error:
                report["worker_failure_custody_error"] = base.public_error(error, directory, provider_source)
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


def validate_freeze(protocol_path, freeze_path, python_path, base_python_path, native_path, conhost_path, provider_source, model_dir, fixture):
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
    provider = protocol.get("provider_custody", {})
    if (provider.get("policy_id") != PROVIDER_POLICY_ID or provider.get("provider_config") != PROVIDER_CONFIG
        or provider.get("provider_source_relative_path") != PROVIDER_SOURCE_RELATIVE_PATH
        or provider.get("provider_source_sha256") != PROVIDER_SOURCE_SHA256
        or provider.get("frame_scope") != PROVIDER_FRAME_SCOPE
        or Path(provider_source).resolve().parts[-3:] != ("urllib3", "util", "connection.py")
        or source_digest(provider_source) != PROVIDER_SOURCE_SHA256
        or freeze.get("provider_source_sha256") != PROVIDER_SOURCE_SHA256
        or freeze.get("provider_source_path_sha256") != dual.path_hash(provider_source)):
        raise obs.ObserverError("explicit provider source/policy differs from new freeze")
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


def acceptance(python_path, base_python_path, native_path, conhost_path, provider_source, model_dir, fixture, protocol_path, freeze_path, output):
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
        protocol, freeze = validate_freeze(protocol_path, freeze_path, python_path, base_python_path, native_path, conhost_path, provider_source, model_dir, fixture)
        report.update(protocol_sha256=obs.sha256_file(protocol_path), implementation_sha256=obs.sha256_file(freeze_path),
            source_sha256=freeze["new_source_files_sha256"], frozen_dependencies_sha256=freeze["frozen_dependency_files_sha256"],
            launch_executable_sha256=freeze["python_executable_sha256"], actual_worker_expected_os_image_sha256=freeze["base_python_executable_sha256"],
            native_executable_sha256=freeze["native_executable_sha256"], executables_sha256=freeze["executables_sha256"],
            executable_path_sha256=freeze["executable_path_sha256"], review_tools_sha256=freeze["review_tools_sha256"], model_id=cost.MODEL_ID, model_revision=cost.MODEL_REVISION,
            model_assets={name: {"bytes": size, "sha256": h} for name, (size, h) in cost.PINNED_ASSETS.items()},
            protocol_predeclared_at=protocol["predeclared_at"], implementation_frozen_at=freeze["frozen_at"],
            provider_source_sha256=freeze["provider_source_sha256"], provider_source_path_sha256=freeze["provider_source_path_sha256"],
            provider_policy_id=PROVIDER_POLICY_ID)
        if os.name != "nt":
            raise obs.UnsupportedPlatform("Windows training integration unavailable; no fallback")
        suite_deadline = started + CONFIG["total_timeout_seconds"]
        for spec in CASES:
            report["cases"].append(run_case(spec, Path(python_path).resolve(), Path(base_python_path).resolve(),
                Path(native_path).resolve(), Path(conhost_path).resolve(), Path(provider_source).resolve(), Path(model_dir).resolve(), Path(fixture).resolve(), freeze, output, suite_deadline))
        report["passed"] = len(report["cases"]) == 5 and all(c["passed"] for c in report["cases"]) and time.perf_counter() <= suite_deadline
    except BaseException as error:
        report["error"] = base.public_error(error, output, python_path, base_python_path, native_path, provider_source, model_dir, fixture, protocol_path, freeze_path)
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
    for name in ("python", "base-python", "native", "conhost", "provider-source", "model-dir", "fixture", "protocol", "freeze", "output", "directory"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--nonce")
    parser.add_argument("--mode", choices=tuple(sorted({s[1] for s in CASES})))
    parser.add_argument("--manual-bytes", type=int)
    parser.add_argument("--case-deadline", type=float)
    parser.add_argument("--suite-deadline", type=float)
    args = parser.parse_args(argv)
    if args.worker:
        if any(v is None for v in (args.directory, args.nonce, args.native, args.provider_source, args.model_dir, args.fixture, args.mode, args.manual_bytes, args.case_deadline, args.suite_deadline)):
            parser.error("worker requires directory/nonce/native/provider-source/model-dir/fixture/mode/manual-bytes/deadlines")
        obs.validate_nonce(args.nonce)
        if args.manual_bytes not in (0, CONFIG["manual_allocation_bytes"]):
            parser.error("manual allocation outside fixed0/64MiB controls")
        worker(args.directory, args.nonce, args.native, args.provider_source, args.model_dir, args.fixture, args.mode, args.manual_bytes, args.case_deadline, args.suite_deadline)
        return 0
    if any(v is None for v in (args.python, args.base_python, args.native, args.conhost, args.provider_source, args.model_dir, args.fixture, args.protocol, args.freeze, args.output)):
        parser.error("acceptance requires python/base-python/native/conhost/provider-source/model-dir/fixture/protocol/freeze/fresh output")
    result = acceptance(args.python, args.base_python, args.native, args.conhost, args.provider_source, args.model_dir, args.fixture, args.protocol, args.freeze, args.output)
    print("pinned Pythia training observer engineering acceptance: " + ("passed" if result["passed"] else "FAILED"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
