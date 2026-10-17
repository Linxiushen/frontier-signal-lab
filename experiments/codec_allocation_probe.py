"""Matched actual codec allocation/cost diagnostic, without optimizer or quality rescue.

Importing this module loads no ML package and starts no process. Only a reviewed
freeze permits the one eight-worker study. Existing v3 Windows Job, retained
identity, role, provider-policy and cleanup helpers are reused unchanged.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import training_observer_v3 as prior
from experiments import process_observer as obs
from experiments import process_observer_probe as base
from experiments import workload_observer_probe as work
from experiments import dual_identity_census as dual
from experiments import activation_cost_probe as cost
from experiments import codec_allocation_events as reduction


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
EXPERIMENT_ID = "pythia14m-matched-codec-allocation-cost-v1"
SOURCE_PATHS = ("experiments/codec_allocation_probe.py", "experiments/codec_allocation_events.py",
                "tests/test_codec_allocation_probe.py", "tests/test_codec_allocation_events.py")
REVIEW_PATHS = ("scripts/audit_codec_allocation.py",)
DEPENDENCY_PATHS = tuple(dict.fromkeys((*prior.DEPENDENCY_PATHS, "experiments/training_observer_v3.py",
    "fixtures/training-observer-v3/protocol.json", "fixtures/training-observer-v3/implementation.json")))
CONFIG = {"seed": 503, "batch_indices": [116, 73], "batch_shape": [2, 65],
    "forward_calls_per_worker": 1, "backward_calls_per_worker": 1, "optimizer_updates": 0,
    "intraop_threads": 1, "interop_threads": 1, "maximum_native_threads": 32,
    "profile_memory": True, "record_shapes": False, "with_stack": False,
    "case_timeout_seconds": 90.0, "total_timeout_seconds": 480.0,
    "handshake_timeout_seconds": 5.0, "import_timeout_seconds": 20.0, "load_timeout_seconds": 25.0,
    "study_timeout_seconds": 30.0, "barrier_timeout_seconds": 5.0, "cleanup_timeout_seconds": 4.0,
    "maximum_tree_nodes": 100000, "maximum_allocation_events": 20000,
    "maximum_storage_records": 4096, "maximum_callbacks": 2048,
    "maximum_references": 8192, "maximum_markers": 2052, "maximum_boundaries": 4,
    "maximum_json_file_bytes": 33554432, "maximum_case_output_bytes": 50331648,
    "maximum_output_bytes": 402653184, "hard_native_private_memory_cap_enforced": False,
    "active_memory_sampler": False}
CASES = tuple({"id": f"{i:02d}_{'on' if enabled else 'off'}_{method}",
               "observer_enabled": enabled, "method": method}
              for i, (enabled, method) in enumerate(
                  [(False, m) for m in ("dense", "int8", "int8", "dense")] +
                  [(True, m) for m in ("dense", "int8", "int8", "dense")], 1))
STAGES = ("preimport", "postimport", "postload", "poststudy", "complete")
PHASES = {"preimport": "preimport", "postimport": "postimport", "postload": "postload",
          "poststudy": "postupdate", "complete": "complete"}
BOUNDARIES = ("after_forward_loss", "after_backward", "after_loss_logits_delete", "after_zero_grad")
LIMITS = [
    "One frozen eight-worker suite, one load/forward/exact-CE/backward per worker, no optimizer, holdout or repeated trial",
    "Same-method OFF/ON loss and gradient byte equality controls instrumentation mathematics, not compression accuracy or model quality",
    "Dense uses the same exact saved-tensor hooks and protected module scopes; this is a hooked dense baseline",
    "Two observations per method/observer setting; elapsed ratios are descriptive, not causal speed or efficiency claims",
    "Raw events measure reported PyTorch CPU allocator requested bytes, not OS resident/private capacity, process peak or GPU memory",
    "StorageWeakRef expiry concerns backing strong ownership; neither it nor allocator free establishes OS memory returned",
    "ON-only registry/profiler/held boundaries perturb lifetimes and timing; OFF has no corresponding allocator or owner result",
    "Only callback-created allocations destroyed before return count as temporary workspace; returned payload allocations stay separate",
    "Missing allocator IDs use predeclared pointer epochs only; equal-time same-pointer events and unresolved bindings remain unknown",
    "Unknown baseline frees and right-censored live tails are retained; incomplete source/payload coverage rejects the measurement gate",
    "No record_shapes/with_stack, export-memory-timeline fallback, interface substitution, seed/lr/threshold rescue or automatic retry",
    "Historical six failed training-cost/final-quality screens and invalid old parent RSS remain unchanged; no sealed quality gate is rerun",
    "Held role checks are not continuous process isolation, and the Python audit provider guard is not an OS network sandbox",
    "Metadata/file/deadline limits are enforced; no active memory sampler or hard native private-memory cap is present",
]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def write_bounded(path, value):
    encoded = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > CONFIG["maximum_json_file_bytes"]:
        raise obs.ObserverError("codec JSON file byte bound exceeded")
    current = sum(row.stat().st_size for row in Path(path).parent.rglob("*") if row.is_file())
    bound = CONFIG["maximum_case_output_bytes"] if Path(path).parent.name in {row["id"] for row in CASES} else CONFIG["maximum_output_bytes"]
    if current + len(encoded) > bound:
        raise obs.ObserverError("codec directory output byte bound exceeded")
    obs.write_new(path, value)


def finite_clock(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def case_spec(case_id):
    matches = [value for value in CASES if value["id"] == case_id]
    if len(matches) != 1:
        raise ValueError("case is outside the predeclared order")
    return dict(matches[0])


def protocol_template(predeclared_at):
    return {"schema_version": 1, "experiment_id": EXPERIMENT_ID, "predeclared_at": predeclared_at,
        "config": CONFIG, "cases_in_order": list(CASES), "source_paths": list(SOURCE_PATHS),
        "review_tool_paths": list(REVIEW_PATHS),
        "saved_receipt_rejection_controls": ["raw_byte_mutation", "poststudy_stale_hash", "gradient_equality_corruption"],
        "frozen_dependency_paths": list(DEPENDENCY_PATHS), "stages": list(STAGES), "boundaries": list(BOUNDARIES),
        "model": {"id": cost.MODEL_ID, "revision": cost.MODEL_REVISION,
                  "assets": {name: {"bytes": size, "sha256": value} for name, (size, value) in cost.PINNED_ASSETS.items()},
                  "planned_model_loads": 8, "planned_forwards": 8, "planned_backwards": 8, "planned_optimizer_updates": 0},
        "training": {"train_sha256": "8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681",
                     "batch_indices": [116, 73], "exact_layernorm_scopes": 13, "exact_attention_scopes": 6,
                     "expected_outer_saves": 33, "expected_outer_eligible_saves": 19,
                     "int8_expected_compressed_outer_saves": 19,
                     "holdout_opened": False, "final_quality_gate_changed": False},
        "allocator_identity_policy": "pointer epochs; optional allocation IDs must agree; equal-time same-pointer events unknown",
        "measurement_gate": "raw CPU Allocation events present; all eligible saved-source/payload and decoded observations bound uniquely; owner probes agree where bound; no reduction problems",
        "stop": "Any protocol/identity/provider/thread/deadline/math/trace failure is retained; do not retry or replace the measurement interface",
        "provider_custody": {"policy_id": prior.PROVIDER_POLICY_ID,
            "provider_config": prior.PROVIDER_CONFIG, "provider_source_sha256": prior.PROVIDER_SOURCE_SHA256,
            "denied_python_audit_events": list(prior.PROVIDER_DENIED_EVENTS), "external_providers_permitted": False,
            "native_network_sandbox": False}, "limitations": LIMITS}


def validate_protocol(protocol):
    if protocol != protocol_template(protocol.get("predeclared_at")):
        raise obs.ObserverError("codec allocation protocol/order/literal settings differ")
    declared = dt.datetime.fromisoformat(protocol["predeclared_at"])
    if declared.tzinfo is None or declared > dt.datetime.now(dt.timezone.utc):
        raise obs.ObserverError("invalid predeclaration time")
    return protocol


def budget(seconds, case_end, suite_end):
    until = min(time.perf_counter() + seconds, case_end - CONFIG["cleanup_timeout_seconds"],
                suite_end - CONFIG["cleanup_timeout_seconds"])
    if until <= time.perf_counter():
        raise obs.ObserverError("nonrenewable codec case/suite budget exhausted")
    return until


def validate_freeze(protocol_path, freeze_path, paths, provider_source, model_dir, fixture):
    protocol, freeze = validate_protocol(obs.read_small(protocol_path)), obs.read_small(freeze_path)
    if freeze.get("protocol_sha256") != obs.sha256_file(protocol_path):
        raise obs.ObserverError("codec protocol differs from freeze")
    for field, required in (("new_source_files_sha256", SOURCE_PATHS),
                            ("frozen_dependency_files_sha256", DEPENDENCY_PATHS),
                            ("review_tool_files_sha256", REVIEW_PATHS)):
        hashes = freeze.get(field, {})
        if set(hashes) != set(required) or any(obs.sha256_file(ROOT / name) != hashes[name] for name in required):
            raise obs.ObserverError("codec source/dependency freeze differs: " + field)
    if (freeze.get("executables_sha256") != {name: obs.sha256_file(path) for name, path in paths.items()} or
            freeze.get("executable_path_sha256") != {name: dual.path_hash(path) for name, path in paths.items()} or
            freeze.get("provider_source_sha256") != prior.PROVIDER_SOURCE_SHA256 or
            obs.sha256_file(provider_source) != prior.PROVIDER_SOURCE_SHA256 or
            freeze.get("provider_source_path_sha256") != dual.path_hash(provider_source)):
        raise obs.ObserverError("frozen executable/provider custody differs")
    frozen = dt.datetime.fromisoformat(freeze["frozen_at"])
    if not dt.datetime.fromisoformat(protocol["predeclared_at"]) <= frozen <= dt.datetime.now(dt.timezone.utc):
        raise obs.ObserverError("invalid freeze chronology")
    cost.verify_model_assets(model_dir)
    cost.validate_fixture(fixture, verify_holdout=False)
    if Path(fixture).resolve() != (ROOT / "fixtures/activation-cost").resolve():
        raise obs.ObserverError("only the fixed existing natural-text fixture is permitted")
    return protocol, freeze


def require_control(directory, name, nonce, index, state, case_end, suite_end):
    value = work.wait_receipt(directory, name, budget(CONFIG["barrier_timeout_seconds"], case_end, suite_end), nonce, "controller")
    now = time.perf_counter()
    if (value.get("purpose") != EXPERIMENT_ID or value.get("control_index") != index or
            value.get("stage") != name.split("-continue")[0].split("-finish")[0] or
            value.get("admitted") is not True or value.get("command") != ("finish" if name == "complete-finish.json" else "continue") or
            type(value.get("control_index")) is not int or
            not finite_clock(value.get("emitted_perf_counter")) or
            not state["last_emitted"] < value["emitted_perf_counter"] <= now < min(case_end, suite_end) or state["next_index"] != index):
        raise obs.ObserverError("codec control ordering/custody mismatch")
    state.update(next_index=index + 1, last_emitted=value["emitted_perf_counter"])
    write_bounded(directory / name.replace(".json", "-accepted.json"), base.envelope(nonce, "worker",
        filename=name, control_envelope=value, accepted_perf_counter=now, next_control_index=index + 1))


def held_stage(backend, directory, stage, nonce, state, guard, case_end, suite_end, **details):
    guard.set_phase(PHASES[stage])
    write_bounded(directory / (stage + "-ready.json"), base.envelope(nonce, "worker", stage=stage,
        stage_ready_perf_counter=time.perf_counter(), provider_guard=guard.receipt(),
        native_thread_count=work.native_thread_count(backend, os.getpid()), **details))
    require_control(directory, stage + "-continue.json", nonce, STAGES.index(stage), state, case_end, suite_end)


class LifetimeRegistry:
    """Only weak StorageImpl handles and primitive metadata persist here."""
    def __init__(self, weak_type):
        self.weak_type, self.handles, self.rows, self.lookup = weak_type, [], [], {}
        self.references, self.callbacks, self.boundaries = [], [], []

    def add(self, tensor, role, marker_id, at, required):
        if len(self.references) >= CONFIG["maximum_references"]:
            raise obs.ObserverError("bounded storage reference count exceeded")
        storage = tensor.untyped_storage()
        handle = self.weak_type(storage)
        key = int(handle.cdata)
        index = self.lookup.get(key)
        if index is None:
            if len(self.rows) >= CONFIG["maximum_storage_records"]:
                raise obs.ObserverError("bounded storage metadata exceeded")
            index = len(self.rows)
            self.lookup[key] = index
            self.handles.append(handle)
            self.rows.append({"storage_id": "storage-" + str(index), "ptr": int(storage.data_ptr()),
                              "nbytes": int(storage.nbytes()), "roles": []})
        else:
            del handle
        row = self.rows[index]
        if row["ptr"] != int(storage.data_ptr()) or row["nbytes"] != int(storage.nbytes()):
            raise obs.ObserverError("same StorageImpl resized or changed backing during study")
        if role not in row["roles"]:
            row["roles"].append(role)
        self.references.append({"observation_id": "observation-" + str(len(self.references)),
            "storage_id": row["storage_id"], "ptr": row["ptr"], "nbytes": row["nbytes"],
            "role": role, "marker_id": marker_id, "at": at, "required": bool(required)})
        return row["storage_id"]

    def owner_snapshot(self, torch, label):
        if len(self.boundaries) >= CONFIG["maximum_boundaries"]:
            raise obs.ObserverError("bounded owner boundary count exceeded")
        marker_id = "codec_boundary_" + label
        with torch.profiler.record_function(marker_id):
            values = [{"storage_id": row["storage_id"], "expired": bool(handle.expired())}
                      for row, handle in zip(self.rows, self.handles)]
        self.boundaries.append({"marker_id": marker_id, "owners": values})


class InstrumentedCodec:
    def __init__(self, torch, parameters, compress, registry, scope):
        self.torch, self.registry, self.scope = torch, registry, scope
        self.codec = cost.CostCodec(parameters, compress=compress)
        self.counts = {"pack": 0, "unpack": 0, "eligible": 0, "compressed": 0}

    def pack(self, tensor):
        registry = self.registry
        if len(registry.callbacks) >= CONFIG["maximum_callbacks"]:
            raise obs.ObserverError("bounded callback count exceeded")
        marker = "codec_pack_" + str(len(registry.callbacks))
        eligible = self.codec.eligible(tensor)
        source = registry.add(tensor, "eligible_source" if eligible else "exact_source", marker, "entry", eligible)
        with self.torch.profiler.record_function(marker):
            start = time.perf_counter()
            payload = self.codec.pack(tensor)
            end = time.perf_counter()
            compressed = isinstance(payload, tuple)
            returned = [registry.add(item, "compressed_payload" if compressed else "exact_payload", marker,
                                     "exit", eligible or compressed)
                        for item in (payload if compressed else (payload,))]
        registry.callbacks.append({"id": marker, "kind": "pack", "scope": self.scope,
            "source_storage": source, "returned_storages": returned, "eligible": eligible,
            "compressed": compressed, "codec_wall_seconds": end - start})
        self.counts["pack"] += 1
        self.counts["eligible"] += int(eligible)
        self.counts["compressed"] += int(compressed)
        return payload

    def unpack(self, payload):
        registry = self.registry
        if len(registry.callbacks) >= CONFIG["maximum_callbacks"]:
            raise obs.ObserverError("bounded callback count exceeded")
        marker = "codec_unpack_" + str(len(registry.callbacks))
        compressed = isinstance(payload, tuple)
        with self.torch.profiler.record_function(marker):
            start = time.perf_counter()
            result = self.codec.unpack(payload)
            end = time.perf_counter()
            returned = registry.add(result, "decoded" if compressed else "exact_unpacked", marker,
                                    "exit", compressed)
        registry.callbacks.append({"id": marker, "kind": "unpack", "scope": self.scope,
            "returned_storages": [returned], "compressed": compressed, "codec_wall_seconds": end - start})
        self.counts["unpack"] += 1
        return result


def opaque_trace(events, registry_rows, references):
    mapping = {}
    def pointer(value):
        if value not in mapping:
            mapping[value] = "pointer-" + str(len(mapping))
        return mapping[value]
    for row in events:
        row["ptr"] = pointer(row["ptr"])
    for row in registry_rows:
        row["ptr"] = pointer(row["ptr"])
    for row in references:
        row["ptr"] = pointer(row["ptr"])


def extract_trace(profiler):
    """Raw Allocation events only: never sum nested op memory totals."""
    from torch._C._profiler import _EventType
    result = profiler.profiler.kineto_results
    if result is None:
        raise obs.ObserverError("raw profiler result unavailable; no alternative interface permitted")
    events, markers, ordinal = [], [], 0
    stack = list(reversed(result.experimental_event_tree()))
    while stack:
        node = stack.pop()
        ordinal += 1
        if ordinal > CONFIG["maximum_tree_nodes"]:
            raise obs.ObserverError("raw profiler tree node budget exceeded")
        kind, fields = node.typed
        if kind == _EventType.Allocation:
            if len(events) >= CONFIG["maximum_allocation_events"]:
                raise obs.ObserverError("raw allocator event budget exceeded")
            events.append({"ordinal": ordinal, "t_ns": int(node.start_time_ns), "start_tid": int(node.start_tid),
                "ptr": int(fields.ptr), "bytes": int(fields.alloc_size), "device": str(fields.device),
                "allocation_id": None if fields.allocation_id is None else int(fields.allocation_id),
                "total_allocated": int(fields.total_allocated), "total_reserved": int(fields.total_reserved)})
        if node.name.startswith(("codec_pack_", "codec_unpack_", "codec_boundary_")):
            if len(markers) >= CONFIG["maximum_markers"]:
                raise obs.ObserverError("bounded marker count exceeded")
            name = node.name
            category = "pack" if name.startswith("codec_pack_") else "unpack" if name.startswith("codec_unpack_") else "boundary"
            markers.append({"id": name, "kind": category, "start_ns": int(node.start_time_ns),
                            "end_ns": int(node.end_time_ns), "start_tid": int(node.start_tid), "ordinal": ordinal})
        stack.extend(reversed(node.children))
    return events, markers


def gradient_hash_and_validity(torch, model):
    result = hashlib.sha256()
    names, finite = [], True
    for name, parameter in model.named_parameters():
        gradient = parameter.grad
        names.append(name)
        if gradient is None or gradient.dtype != torch.float32 or not gradient.is_contiguous():
            raise obs.ObserverError("all pinned gradients must be contiguous CPU float32")
        finite &= bool(torch.isfinite(gradient).all())
        result.update(canonical({"name": name, "shape": list(gradient.shape), "dtype": str(gradient.dtype)}).encode())
        result.update(memoryview(gradient.detach().numpy()).cast("B"))
    return {"sha256": result.hexdigest(), "finite": finite, "count": len(names)}


def perform_study(torch, model, batch, spec, profiler, registry):
    norms, attentions = cost.preservation_modules(model)
    parameters = list(model.parameters())
    if spec["observer_enabled"]:
        outer = InstrumentedCodec(torch, parameters, spec["method"] == "int8", registry, "outer")
        exact = {name: InstrumentedCodec(torch, parameters, False, registry, name) for name, _ in norms + attentions}
    else:
        outer = cost.CostCodec(parameters, compress=spec["method"] == "int8")
        exact = None
    model.zero_grad(set_to_none=True)
    start = time.perf_counter()
    with torch.autograd.graph.saved_tensors_hooks(outer.pack, outer.unpack):
        with cost.preserve_scopes(norms + attentions, exact):
            logits = model(input_ids=batch[:, :-1].contiguous(), use_cache=False).logits
    loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]), batch[:, 1:].contiguous().reshape(-1))
    forward_end = time.perf_counter()
    if registry is not None:
        registry.owner_snapshot(torch, BOUNDARIES[0])
    backward_start = time.perf_counter()
    loss.backward()
    backward_end = time.perf_counter()
    if registry is not None:
        registry.owner_snapshot(torch, BOUNDARIES[1])
    loss_value = float(loss.detach())
    del loss, logits
    if registry is not None:
        registry.owner_snapshot(torch, BOUNDARIES[2])
    # Gradient byte hash and finiteness are post-operator validation, not timed
    # codec/math work and not a quality evaluation.
    gradient = gradient_hash_and_validity(torch, model)
    model.zero_grad(set_to_none=True)
    if registry is not None:
        registry.owner_snapshot(torch, BOUNDARIES[3])
    result = {"spec": spec, "forward_calls": 1, "backward_calls": 1, "optimizer_updates": 0,
        "loss": loss_value, "gradient": gradient, "forward_loss_wall_seconds": forward_end - start,
        "backward_wall_seconds": backward_end - backward_start,
        "forward_plus_backward_wall_seconds": forward_end - start + backward_end - backward_start,
        "forward_started_perf_counter": start, "backward_completed_perf_counter": backward_end,
        "exact_norm_scopes": len(norms), "exact_attention_scopes": len(attentions),
        "holdout_opened": False, "checkpoint_written": False, "observer_enabled": registry is not None}
    if registry is not None:
        result["codec_counts"] = {"outer": outer.counts,
                                  "exact": {name: value.counts for name, value in exact.items()}}
    return result


def prepare(torch, model_dir, fixture):
    start = time.perf_counter()
    cost.verify_model_assets(model_dir)
    manifest, _, _ = cost.validate_fixture(fixture, verify_holdout=False)
    blocks = cost.load_blocks(Path(fixture) / "train.json", "train", 128)
    model = cost.load_model(model_dir, CONFIG["seed"])
    batch = torch.tensor([blocks[index] for index in CONFIG["batch_indices"]], dtype=torch.long)
    info = {"model_id": cost.MODEL_ID, "model_revision": cost.MODEL_REVISION,
        "train_sha256": manifest["train_sha256"], "batch_indices": CONFIG["batch_indices"],
        "batch_shape": list(batch.shape), "batch_sha256": hashlib.sha256(memoryview(batch.numpy()).cast("B")).hexdigest(),
        "initial_parameter_sha256": cost.parameter_hash(model), "seed": CONFIG["seed"],
        "parameter_tensors": len(list(model.parameters())), "parameter_elements": sum(p.numel() for p in model.parameters()),
        "intraop_threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "holdout_opened": False, "optimizer_created": False, "load_wall_seconds": time.perf_counter() - start}
    return model, batch, info


def finalize_trace(profiler, registry, operation, directory):
    events, markers = extract_trace(profiler)
    rows = [dict(row, roles=list(row["roles"])) for row in registry.rows]
    references = [dict(row) for row in registry.references]
    opaque_trace(events, rows, references)
    reduced = reduction.reduce_events(events, markers, references)
    marker_map = {marker["id"]: marker for marker in markers}
    boundaries = []
    for boundary in registry.boundaries:
        marker = marker_map.get(boundary["marker_id"])
        if marker is None:
            raise obs.ObserverError("missing boundary marker in raw allocator tree")
        boundaries.append(reduction.boundary_summary(reduced, marker, boundary["owners"]))
    required = [value for value in reduced["bindings"] if value["required"]]
    required_ids = {value["storage_id"] for value in required}
    required_owners = [row for boundary in boundaries for row in boundary["rows"] if row["storage_id"] in required_ids]
    callbacks = registry.callbacks
    gates = {"raw_cpu_events_present": bool(events), "event_reduction_valid": reduced["valid"],
        "all_required_observations_uniquely_bound": bool(required) and all(row["status"] == "bound" for row in required),
        "required_owner_agreement": bool(required_owners) and all(row["agreement"] is True for row in required_owners),
        "four_owner_boundaries": len(boundaries) == 4,
        "callback_markers_complete": all(row["id"] in marker_map for row in callbacks),
        "all_callback_summaries_valid": len(reduced["callback_summaries"]) == len(callbacks) and
            all(row["valid"] for row in reduced["callback_summaries"]),
        "outer33save_calls": operation["codec_counts"]["outer"]["pack"] == 33,
        "outer19eligible_saves": operation["codec_counts"]["outer"]["eligible"] == 19,
        "outer19compressed_or_zero": operation["codec_counts"]["outer"]["compressed"] == (19 if operation["spec"]["method"] == "int8" else 0)}
    trace = {"schema_version": 1, "profile_memory": True, "record_shapes": False, "with_stack": False,
        "events": events, "markers": markers, "storage_records": rows, "references": references,
        "callbacks": callbacks, "boundaries": boundaries, "reduced": reduced, "measurement_gates": gates,
        "measurement_valid": all(gates.values())}
    write_bounded(directory / "allocation-trace.json", trace)
    operation.update(trace_sha256=obs.sha256_file(directory / "allocation-trace.json"),
        measurement_valid=trace["measurement_valid"], measurement_gates=gates,
        profiler_settings={"profile_memory": True, "record_shapes": False, "with_stack": False},
        callback_pack_wall_seconds=sum(row["codec_wall_seconds"] for row in callbacks if row["kind"] == "pack"),
        callback_unpack_wall_seconds=sum(row["codec_wall_seconds"] for row in callbacks if row["kind"] == "unpack"))


def worker(directory, nonce, provider_source, model_dir, fixture, spec, case_end, suite_end):
    backend, state = obs.WindowsBackend(), {"next_index": 0, "last_emitted": 0.0}
    guard = prior.LocalProviderGuard(provider_source, True)
    guard.install()
    try:
        dual.publish_identity(backend, directory, "worker-ready.json", nonce, "worker")
        held_stage(backend, directory, "preimport", nonce, state, guard, case_end, suite_end,
                   torch_imported="torch" in sys.modules, transformers_imported="transformers" in sys.modules)
        guard.set_phase("import")
        torch, transformers = prior.import_packages()
        held_stage(backend, directory, "postimport", nonce, state, guard, case_end, suite_end,
                   torch_version=str(torch.__version__), transformers_version=str(transformers.__version__))
        profiler = None
        registry = None
        if spec["observer_enabled"]:
            from torch.multiprocessing.reductions import StorageWeakRef
            registry = LifetimeRegistry(StorageWeakRef)
            profiler = torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU],
                profile_memory=True, record_shapes=False, with_stack=False, with_flops=False, with_modules=False)
        # Start before model load so eligible activation allocations are in the
        # trace. No shape tracing/export-memory-timeline substitution is allowed.
        with profiler if profiler is not None else nullcontext():
            guard.set_phase("load")
            model, batch, info = prepare(torch, model_dir, fixture)
            held_stage(backend, directory, "postload", nonce, state, guard, case_end, suite_end, model=info)
            guard.set_phase("train")
            operation = perform_study(torch, model, batch, spec, profiler, registry)
        operation["final_parameter_sha256"] = cost.parameter_hash(model)
        operation["parameters_unchanged"] = operation["final_parameter_sha256"] == info["initial_parameter_sha256"]
        if profiler is not None:
            finalize_trace(profiler, registry, operation, directory)
        else:
            operation.update(trace_sha256=None, measurement_valid=None, measurement_gates=None,
                             profiler_settings=None, callback_pack_wall_seconds=None, callback_unpack_wall_seconds=None)
        write_bounded(directory / "operation.json", operation)
        held_stage(backend, directory, "poststudy", nonce, state, guard, case_end, suite_end,
                   operation_sha256=obs.sha256_file(directory / "operation.json"),
                   intraop_threads=torch.get_num_threads(), interop_threads=torch.get_num_interop_threads())
        held_stage(backend, directory, "complete", nonce, state, guard, case_end, suite_end,
                   model_loads=1, forward_calls=1, backward_calls=1, optimizer_updates=0)
        require_control(directory, "complete-finish.json", nonce, 5, state, case_end, suite_end)
        write_bounded(directory / "worker-completed.json", base.envelope(nonce, "worker", spec=spec,
            model_loads=1, forward_calls=1, backward_calls=1, optimizer_updates=0, provider_guard=guard.receipt()))
    except BaseException as error:
        write_bounded(directory / "worker-failure.json", base.envelope(nonce, "worker", phase=guard.phase,
            provider_guard=guard.receipt(), error=base.public_error(error, directory, provider_source, model_dir, fixture)))
        raise


def validate_operation(operation, spec):
    return (operation.get("spec") == spec and operation.get("forward_calls") == 1 and
        operation.get("backward_calls") == 1 and operation.get("optimizer_updates") == 0 and
        operation.get("observer_enabled") is spec["observer_enabled"] and operation.get("parameters_unchanged") is True and
        operation.get("gradient", {}).get("finite") is True and operation.get("gradient", {}).get("count") == 76 and
        prior.is_hash(operation.get("gradient", {}).get("sha256")) and
        prior.is_hash(operation.get("final_parameter_sha256")) and
        type(operation.get("loss")) in (int, float) and math.isfinite(operation["loss"]) and
        operation.get("exact_norm_scopes") == 13 and operation.get("exact_attention_scopes") == 6 and
        operation.get("holdout_opened") is False and operation.get("checkpoint_written") is False and
        all(type(operation.get(name)) in (int, float) and 0 <= operation[name] <= CONFIG["study_timeout_seconds"]
            for name in ("forward_loss_wall_seconds", "backward_wall_seconds", "forward_plus_backward_wall_seconds")) and
        (operation.get("measurement_valid") is True and prior.is_hash(operation.get("trace_sha256")) and
         type(operation.get("measurement_gates")) is dict and bool(operation["measurement_gates"]) and
         all(value is True for value in operation["measurement_gates"].values()) if spec["observer_enabled"] else
         all(operation.get(name) is None for name in ("trace_sha256", "measurement_valid", "measurement_gates", "profiler_settings",
                                                     "callback_pack_wall_seconds", "callback_unpack_wall_seconds"))))


def validate_model(info):
    return (info.get("model_id") == cost.MODEL_ID and info.get("model_revision") == cost.MODEL_REVISION and
        info.get("train_sha256") == protocol_template("unused")["training"]["train_sha256"] and
        info.get("batch_indices") == [116, 73] and info.get("batch_shape") == [2, 65] and
        prior.is_hash(info.get("batch_sha256")) and prior.is_hash(info.get("initial_parameter_sha256")) and
        info.get("parameter_tensors") == 76 and info.get("parameter_elements") == 14067712 and
        info.get("optimizer_created") is False and info.get("holdout_opened") is False and
        info.get("seed") == 503 and info.get("intraop_threads") == 1 and info.get("interop_threads") == 1 and
        info.get("deterministic_algorithms") is True)


def validate_acceptance(accepted, expected, pid, filename, index, waited, case_end, suite_end):
    return (accepted.get("pid") == pid and accepted.get("filename") == filename and
        accepted.get("control_envelope") == expected and type(accepted.get("next_control_index")) is int and
        accepted["next_control_index"] == index + 1 and finite_clock(accepted.get("accepted_perf_counter")) and
        expected["emitted_perf_counter"] <= accepted["accepted_perf_counter"] <= waited["completed_perf_counter"] and
        accepted["accepted_perf_counter"] < min(case_end, suite_end))


def wait_acceptance(directory, filename, nonce, actual, index, report, case_end, suite_end):
    waited = {"started_perf_counter": time.perf_counter()}
    accepted = work.wait_receipt(directory, filename.replace(".json", "-accepted.json"),
        budget(CONFIG["barrier_timeout_seconds"], case_end, suite_end), nonce)
    waited["completed_perf_counter"] = time.perf_counter()
    expected = {k: v for k, v in report["controller_controls"][-1].items() if k != "filename"}
    if not validate_acceptance(accepted, expected, actual.pid, filename, index, waited, case_end, suite_end):
        raise obs.ObserverError("worker did not accept exact timely codec control")
    report["worker_controls"].append({**accepted, "parent_wait": waited})


def verify_cleanup(report):
    cleanup = report["cleanup"]
    exits = cleanup.get("exit_codes", [])
    expected = {(row["pid"], row["creation_filetime"]) for row in report["censuses"][-1]["processes"]}
    if (cleanup.get("all_retained_handles_exited") is not True or cleanup.get("job_active_count") != 0 or
            len(exits) != len(expected) or {(row["pid"], row["creation_filetime"]) for row in exits} != expected or
            not all(row["exit_code"] == 0 for row in exits)):
        raise obs.ObserverError("codec cleanup lacks exact retained census identity set and exit0")
    report["cleanup_exact_retained_identity_set"] = True


def parent_control(directory, stage, nonce, index, report, finish=False):
    now = time.perf_counter()
    decision = report["role_decisions"][-1]
    if decision.get("admitted") is not True or decision["label"] != stage or decision["completed_perf_counter"] > now:
        raise obs.ObserverError("codec control lacks current exact role admission")
    name = stage + ("-finish.json" if finish else "-continue.json")
    value = base.envelope(nonce, "controller", purpose=EXPERIMENT_ID, stage=stage,
        command="finish" if finish else "continue", control_index=index, admitted=True, emitted_perf_counter=now)
    write_bounded(directory / name, value)
    report["controller_controls"].append({"filename": name, **value})
    return name


def run_case(paths, provider_source, model_dir, fixture, freeze, output, spec, suite_end):
    directory = output / spec["id"]
    directory.mkdir()
    nonce, start = secrets.token_hex(32), time.perf_counter()
    case_end = min(start + CONFIG["case_timeout_seconds"], suite_end)
    report = {"id": spec["id"], "spec": spec, "nonce": nonce, "started_at": base.utc_now(),
        "started_perf_counter": start, "case_deadline_perf_counter": case_end, "suite_deadline_perf_counter": suite_end,
        "passed": False, "stages": {}, "controller_controls": [], "worker_controls": [],
        "censuses": [], "role_decisions": [], "samples": [], "parent_query_costs": [],
        "executables_sha256": freeze["executables_sha256"], "executable_path_sha256": freeze["executable_path_sha256"],
        "_paths": paths}
    job = actual = None
    try:
        job = obs.WindowsJob()
        launcher = job.start_suspended([str(paths["launcher"]), "-S", "-X", "utf8", str(SCRIPT), "--worker",
            "--directory", str(directory), "--nonce", nonce, "--case-id", spec["id"],
            "--provider-source", str(provider_source), "--model-dir", str(model_dir), "--fixture", str(fixture),
            "--case-deadline", str(case_end), "--suite-deadline", str(suite_end)], cwd=ROOT)
        report["launcher"] = {"pid": launcher.pid, "creation_filetime": launcher.creation_filetime,
                              "assigned_while_suspended": True, "job_handle_inherited": False}
        ready = work.wait_receipt(directory, "worker-ready.json", budget(5, case_end, suite_end), nonce)
        actual, ancestry = job.authenticate(ready, nonce, "worker", launcher)
        if actual.pid == launcher.pid:
            raise obs.ObserverError("expected verified venv launcher/actual interpreter distinction")
        report["worker_identity"] = {"self_receipt": ready, "verified_ancestry": ancestry,
            "launcher_differs_from_interpreter": True,
            "os_image": prior.os_image(job.backend, actual, paths["base_python"], freeze["executables_sha256"]["base_python"]),
            **dual.verify_self_executable(ready, "worker", paths, freeze["executables_sha256"])}
        report["launcher"]["os_image"] = prior.os_image(job.backend, launcher, paths["launcher"], freeze["executables_sha256"]["launcher"])
        for index, stage in enumerate(STAGES):
            timeout = {"preimport": 5, "postimport": 20, "postload": 25, "poststudy": 30, "complete": 5}[stage]
            value = work.wait_receipt(directory, stage + "-ready.json", budget(timeout, case_end, suite_end), nonce)
            if (value["pid"] != actual.pid or value.get("stage") != stage or
                    not finite_clock(value.get("stage_ready_perf_counter")) or
                    not start <= value["stage_ready_perf_counter"] <= time.perf_counter() < min(case_end, suite_end) or
                    (index > 0 and value["stage_ready_perf_counter"] < report["worker_controls"][-1]["accepted_perf_counter"]) or
                    type(value.get("native_thread_count")) is not int or
                    not 1 <= value["native_thread_count"] <= CONFIG["maximum_native_threads"] or
                    not prior.validate_provider(value.get("provider_guard", {}), PHASES[stage], 0 if stage == "preimport" else 1)):
                raise obs.ObserverError("codec held identity/provider/thread gate failed: " + stage)
            report["stages"][stage] = value
            if stage == "preimport" and (value.get("torch_imported") is not False or value.get("transformers_imported") is not False):
                raise obs.ObserverError("ML imported before admitted release")
            if stage == "postload":
                info = value.get("model", {})
                if not validate_model(info):
                    raise obs.ObserverError("codec pinned model/batch/thread preparation differs")
            if stage == "poststudy":
                path = directory / "operation.json"
                if obs.sha256_file(path) != value.get("operation_sha256"):
                    raise obs.ObserverError("operation file is not bound to worker receipt")
                operation = obs.read_small(path)
                report["operation"] = operation
                if not validate_operation(operation, spec):
                    raise obs.ObserverError("codec operation/measurement gate failed; preserve, do not retry")
                if operation["final_parameter_sha256"] != report["stages"]["postload"]["model"]["initial_parameter_sha256"]:
                    raise obs.ObserverError("codec final parameter bytes differ from postload")
                if spec["observer_enabled"] and obs.sha256_file(directory / "allocation-trace.json") != operation["trace_sha256"]:
                    raise obs.ObserverError("raw allocator trace hash differs")
            prior.inventory(job, launcher, actual, None, report, stage)
            filename = parent_control(directory, stage, nonce, index, report)
            wait_acceptance(directory, filename, nonce, actual, index, report, case_end, suite_end)
        report["prefinish_live_members"] = work.live_member_receipts(job, actual, launcher)
        filename = parent_control(directory, "complete", nonce, 5, report, finish=True)
        wait_acceptance(directory, filename, nonce, actual, 5, report, case_end, suite_end)
        done = work.wait_receipt(directory, "worker-completed.json", budget(5, case_end, suite_end), nonce)
        if (done["pid"] != actual.pid or done.get("spec") != spec or done.get("model_loads") != 1 or
                done.get("forward_calls") != 1 or done.get("backward_calls") != 1 or done.get("optimizer_updates") != 0 or
                not prior.validate_provider(done.get("provider_guard", {}), "complete", 1)):
            raise obs.ObserverError("completion receipt mismatch")
        report["completion"] = done
        report["cleanup"] = work.cleanup(job, case_end, suite_end)
        verify_cleanup(report)
        report["passed"] = True
    except BaseException as error:
        report["error"] = base.public_error(error, directory, output, *paths.values(), provider_source, model_dir, fixture)
        if job is not None:
            try:
                job.terminate()
                report["failure_cleanup"] = work.cleanup(job, case_end, suite_end)
            except BaseException as cleanup_error:
                report["cleanup_error"] = base.public_error(cleanup_error)
    finally:
        failure_path = directory / "worker-failure.json"
        if failure_path.exists():
            report["passed"] = False
            try:
                report["worker_failure"] = obs.read_small(failure_path)
            except BaseException as error:
                report["worker_failure_read_error"] = base.public_error(error)
        if job is not None:
            for name, function in (("job_close_error", job.close), ("process_handle_close_error", job.close_refs)):
                try:
                    function()
                except BaseException as error:
                    report[name], report["passed"] = base.public_error(error), False
        report.pop("_paths", None)
        report["completed_perf_counter"] = time.perf_counter()
        report["wall_seconds"] = report["completed_perf_counter"] - start
        report["completed_at"] = base.utc_now()
    return report


def math_controls(cases):
    groups = {}
    for case in cases:
        operation = case.get("operation")
        if operation is not None:
            groups.setdefault(case["spec"]["method"], []).append(case)
    return {method: {"four_matched_operations": len(values) == 4,
                     "loss_identical": len({value["operation"]["loss"] for value in values}) == 1,
                     "gradient_bytes_identical": len({value["operation"]["gradient"]["sha256"] for value in values}) == 1,
                     "initial_parameter_bytes_identical": len({value["stages"]["postload"]["model"]["initial_parameter_sha256"] for value in values}) == 1,
                     "batch_bytes_identical": len({value["stages"]["postload"]["model"]["batch_sha256"] for value in values}) == 1}
            for method, values in groups.items()}


def acceptance(paths, provider_source, model_dir, fixture, protocol_path, freeze_path, output):
    protocol, freeze = validate_freeze(protocol_path, freeze_path, paths, provider_source, model_dir, fixture)
    output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    suite_end = start + CONFIG["total_timeout_seconds"]
    report = {"schema_version": 1, "experiment_id": EXPERIMENT_ID, "started_at": base.utc_now(),
        "started_perf_counter": start, "cases": [], "suite_launches": 1, "retries": 0, "passed": False,
        "protocol_sha256": obs.sha256_file(protocol_path), "implementation_sha256": obs.sha256_file(freeze_path),
        "limitations": LIMITS}
    try:
        for spec in CASES:
            case = run_case(paths, provider_source, model_dir, fixture, freeze, output, dict(spec), suite_end)
            report["cases"].append(case)
            write_bounded(output / (spec["id"] + "-result.json"), case)
            if not case["passed"]:
                break
        report["math_controls"] = math_controls(report["cases"])
        report["passed"] = (len(report["cases"]) == 8 and all(case["passed"] for case in report["cases"]) and
            set(report["math_controls"]) == {"dense", "int8"} and
            all(all(values.values()) for values in report["math_controls"].values()))
    except BaseException as error:
        report["error"] = base.public_error(error, output, *paths.values(), provider_source, model_dir, fixture, protocol_path, freeze_path)
    report["completed_at"] = base.utc_now()
    report["wall_seconds"] = time.perf_counter() - start
    report["result_sha256"] = digest(report)
    write_bounded(output / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("python", "base-python", "native", "conhost", "provider-source", "model-dir", "fixture", "protocol", "freeze", "output", "directory"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--nonce")
    parser.add_argument("--case-id")
    parser.add_argument("--case-deadline", type=float)
    parser.add_argument("--suite-deadline", type=float)
    args = parser.parse_args(argv)
    if args.worker:
        worker(args.directory.resolve(), args.nonce, args.provider_source.resolve(), args.model_dir.resolve(),
               args.fixture.resolve(), case_spec(args.case_id), args.case_deadline, args.suite_deadline)
        return 0
    required = (args.python, args.base_python, args.native, args.conhost, args.provider_source,
                args.model_dir, args.fixture, args.protocol, args.freeze, args.output)
    if any(value is None for value in required):
        parser.error("acceptance needs exact local paths/protocol/freeze/fresh output")
    paths = {"launcher": args.python.resolve(), "base_python": args.base_python.resolve(),
             "native": args.native.resolve(), "conhost": args.conhost.resolve()}
    report = acceptance(paths, args.provider_source.resolve(), args.model_dir.resolve(), args.fixture.resolve(),
                        args.protocol.resolve(), args.freeze.resolve(), args.output.resolve())
    print("codec allocation passed=" + str(report["passed"]) + " result_sha256=" + report["result_sha256"])
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
