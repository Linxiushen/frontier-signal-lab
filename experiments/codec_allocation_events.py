"""Pure reduction of raw CPU allocator events; imports no ML packages.

Pointer names are opaque producer-assigned strings. Each positive event starts
a pointer epoch. Tree traversal never orders equal-timestamp events in time.
"""
from __future__ import annotations


def _integer(value):
    return type(value) is int


def _marker_valid(row):
    return (type(row) is dict and type(row.get("id")) is str and
            row.get("kind") in ("pack", "unpack", "boundary") and
            all(_integer(row.get(key)) for key in ("start_ns", "end_ns", "start_tid")) and
            row["start_ns"] < row["end_ns"])


def reduce_events(events, markers, references):
    problems, unknown_frees, allocations = [], [], []
    active, by_pointer, marker_map = {}, {}, {}
    for marker in markers:
        if not _marker_valid(marker):
            problems.append({"kind": "invalid_marker"})
        elif marker["id"] in marker_map:
            problems.append({"kind": "duplicate_marker_id", "id": marker["id"]})
        else:
            marker_map[marker["id"]] = marker
    good_events, ordinals, tied = [], set(), {}
    for event in events:
        if (type(event) is not dict or event.get("device") != "cpu" or
                type(event.get("ptr")) is not str or
                not all(_integer(event.get(key)) for key in ("t_ns", "ordinal", "bytes", "start_tid")) or
                event["bytes"] == 0):
            problems.append({"kind": "invalid_or_non_cpu_event"})
            continue
        if event["ordinal"] in ordinals:
            problems.append({"kind": "duplicate_tree_ordinal"})
        ordinals.add(event["ordinal"])
        good_events.append(event)
        tied.setdefault((event["ptr"], event["t_ns"]), []).append(event)
    ambiguous = {key for key, rows in tied.items() if len(rows) > 1}
    for ptr, stamp in sorted(ambiguous):
        problems.append({"kind": "same_pointer_equal_timestamp", "ptr": ptr, "t_ns": stamp})
    for event in sorted(good_events, key=lambda row: (row["t_ns"], row["ordinal"])):
        ptr, size = event["ptr"], event["bytes"]
        if size > 0:
            if ptr in active:
                problems.append({"kind": "allocation_before_prior_free", "ptr": ptr,
                                 "ordinal": event["ordinal"]})
                active.pop(ptr)["ambiguous"] = True
            row = {"id": "allocation-" + str(len(allocations)), "ptr": ptr, "bytes": size,
                   "created_ns": event["t_ns"], "created_ordinal": event["ordinal"],
                   "create_tid": event["start_tid"], "allocation_id": event.get("allocation_id"),
                   "destroyed_ns": None, "destroyed_ordinal": None, "destroy_tid": None,
                   "ambiguous": (ptr, event["t_ns"]) in ambiguous}
            allocations.append(row)
            active[ptr] = row
            by_pointer.setdefault(ptr, []).append(row)
        else:
            row = active.pop(ptr, None)
            if row is None:
                unknown_frees.append(dict(event))
                continue
            row["destroyed_ns"], row["destroyed_ordinal"] = event["t_ns"], event["ordinal"]
            row["destroy_tid"] = event["start_tid"]
            row["ambiguous"] |= (ptr, event["t_ns"]) in ambiguous
            if -size != row["bytes"]:
                problems.append({"kind": "free_size_mismatch", "allocation": row["id"]})
                row["ambiguous"] = True
            given = event.get("allocation_id")
            if given is not None and row["allocation_id"] is not None and given != row["allocation_id"]:
                problems.append({"kind": "free_allocation_id_mismatch", "allocation": row["id"]})
                row["ambiguous"] = True
    bindings, counts = [], {}
    for ref in references:
        if type(ref) is dict and type(ref.get("observation_id")) is str:
            key = ref["observation_id"]
            counts[key] = counts.get(key, 0) + 1
    for key, count in counts.items():
        if count > 1:
            problems.append({"kind": "duplicate_observation_id", "id": key})
    for ref in references:
        if (type(ref) is not dict or type(ref.get("observation_id")) is not str or
                type(ref.get("storage_id")) is not str or type(ref.get("ptr")) is not str or
                not _integer(ref.get("nbytes")) or ref["nbytes"] <= 0 or ref.get("at") not in ("entry", "exit") or
                ref.get("marker_id") not in marker_map):
            problems.append({"kind": "invalid_reference_or_missing_marker"})
            bindings.append({**(ref if type(ref) is dict else {}), "allocation": None,
                             "candidate_count": 0, "status": "unknown"})
            continue
        marker = marker_map[ref["marker_id"]]
        stamp = marker["start_ns"] if ref["at"] == "entry" else marker["end_ns"]
        candidates = [] if counts[ref["observation_id"]] > 1 else [row for row in by_pointer.get(ref["ptr"], [])
            if row["created_ns"] < stamp and (row["destroyed_ns"] is None or row["destroyed_ns"] > stamp)
            and row["bytes"] == ref["nbytes"] and not row["ambiguous"]]
        bindings.append({**ref, "allocation": candidates[0]["id"] if len(candidates) == 1 else None,
                         "candidate_count": len(candidates), "status": "bound" if len(candidates) == 1 else "unknown"})
    callback_summaries = []
    for marker in marker_map.values():
        if marker["kind"] not in ("pack", "unpack"):
            continue
        start, end, tid = marker["start_ns"], marker["end_ns"], marker["start_tid"]
        refs = [row for row in bindings if row.get("marker_id") == marker["id"]]
        outputs = {row["allocation"] for row in refs if row.get("at") == "exit" and row["allocation"] is not None}
        created = [row for row in allocations if start < row["created_ns"] < end and row["create_tid"] == tid]
        temporaries = [row for row in created if row["id"] not in outputs and row["destroyed_ns"] is not None
                       and row["destroyed_ns"] < end and row["destroy_tid"] == tid]
        at_time = {}
        for row in temporaries:
            for stamp, delta in ((row["created_ns"], row["bytes"]), (row["destroyed_ns"], -row["bytes"])):
                at_time.setdefault(stamp, []).append(delta)
        reasons = []
        if any(row["ambiguous"] for row in created):
            reasons.append("ambiguous_created_allocation")
        if any(start <= row["t_ns"] <= end for row in unknown_frees):
            reasons.append("unknown_baseline_free_in_callback")
        if any(start <= row["t_ns"] <= end and row["start_tid"] != tid for row in good_events):
            reasons.append("foreign_thread_event_overlap")
        if any(row["t_ns"] in (start, end) for row in good_events):
            reasons.append("event_at_marker_endpoint")
        if any(any(delta > 0 for delta in values) and any(delta < 0 for delta in values) for values in at_time.values()):
            reasons.append("mixed_sign_equal_timestamp_peak_unknown")
        if any(row.get("required") and row["status"] != "bound" for row in refs):
            reasons.append("required_reference_unknown")
        live = peak = 0
        for stamp in sorted(at_time):
            live += sum(at_time[stamp])
            peak = max(peak, live)
        valid = not reasons and not problems
        callback_summaries.append({"id": marker["id"], "kind": marker["kind"],
            "allocation_events_created": len(created), "requested_bytes_created": sum(row["bytes"] for row in created),
            "temporary_allocation_count": len(temporaries),
            "temporary_requested_live_max_bytes": peak if valid else None,
            "returned_allocation_ids": sorted(outputs), "valid": valid, "unknown_reasons": reasons,
            "meaning": "Measured same-thread allocations created and destroyed strictly inside this callback, excluding identified returned backing; not process peak"})
    return {"allocations": allocations, "bindings": bindings, "callback_summaries": callback_summaries,
            "problems": problems, "unknown_preexisting_frees": unknown_frees,
            "right_censored_allocation_ids": [row["id"] for row in allocations if row["destroyed_ns"] is None],
            "allocation_ids_missing": sum(row.get("allocation_id") is None for row in good_events),
            "identity_policy": "pointer epochs; optional allocation IDs must agree; equal-time same-pointer events unknown",
            "valid": bool(good_events) and not problems}


def boundary_summary(reduced, marker, owner_rows):
    """Compare weak strong-ownership probes with strict allocator intervals."""
    allocation_map = {row["id"]: row for row in reduced["allocations"]}
    by_storage = {}
    for binding in reduced["bindings"]:
        if binding["allocation"] is not None:
            by_storage.setdefault(binding["storage_id"], set()).add(binding["allocation"])
    result, live_ids = [], set()
    for owner in owner_rows:
        candidates = by_storage.get(owner["storage_id"], set())
        status, agreement, allocation_id = "unknown", None, None
        if len(candidates) == 1 and _marker_valid(marker):
            allocation_id = next(iter(candidates))
            allocation = allocation_map[allocation_id]
            start, end = marker["start_ns"], marker["end_ns"]
            created, freed = allocation["created_ns"], allocation["destroyed_ns"]
            if start <= created <= end or (freed is not None and start <= freed <= end):
                status = "changed_or_tied_during_probe"
            else:
                alive = created < start and (freed is None or freed > end)
                status = "live" if alive else "not_live"
                agreement = alive == (not owner["expired"])
                if alive:
                    live_ids.add(allocation_id)
        result.append({**owner, "allocation": allocation_id, "allocator_status": status, "agreement": agreement})
    unknown = sum(row["agreement"] is None for row in result)
    selected = sum(allocation_map[key]["bytes"] for key in live_ids)
    return {"marker_id": marker["id"], "rows": result,
            "bound_unique_live_requested_bytes": selected if unknown == 0 else None,
            "selected_bound_subset_requested_bytes": selected,
            "selected_bound_subset_complete": unknown == 0,
            "known_owner_rows": len(result) - unknown, "total_owner_rows": len(result),
            "unknown_owners": unknown, "disagreements": sum(row["agreement"] is False for row in result),
            "meaning": "Selected uniquely bound saved-source/payload/decoded requested-byte subset with explicit owner coverage; not all saved or process memory"}
