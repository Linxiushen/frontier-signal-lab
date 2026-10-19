"""Read-only, portable audit of the frozen pure-thread JSONL fixture.

Does not import the producer, run threads, or repair any trace. Use
--implementation and --source-root to additionally verify frozen source bytes.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

ARMS = ["all-admitted", "row-cap", "byte-cap", "short-write",
        "write-exception", "flush-exception", "recursive-write"]
CONTROLS = {"duplicate_sequence", "missing_sequence", "truncated", "oversized",
            "duplicate_key", "nonfinite", "numeric_overflow"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def constant(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("Nonfinite numeric overflow")
        return parsed
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(raw, parse_constant=constant, parse_float=number,
                      object_pairs_hook=unique)


def encoded(row):
    return (json.dumps(row, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def bounded_read(path, limit):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Artifact exceeds audit byte ceiling: " + str(path))
    return raw


def audit(protocol_path, result_dir, implementation_path=None, source_root=None):
    """Validate saved artifacts only; raise ValueError on any contradictory gate."""
    protocol_path, result_dir = Path(protocol_path), Path(result_dir)
    checks, artifacts = [], {}
    def require(condition, name):
        if not condition:
            raise ValueError(name)
        checks.append(name)
    def read(path, ceiling):
        raw = bounded_read(path, ceiling)
        artifacts[str(path)] = {"sha256": sha(raw), "bytes": len(raw)}
        return raw

    protocol_raw = read(protocol_path, 65536)
    protocol = strict_json(protocol_raw)
    fixed = {"schema_version": 1, "experiment": "thread-ledger-serialization",
             "seed": 20261019, "workers": 4, "rows_per_worker": 64,
             "max_row_bytes": 512, "max_total_bytes": 65536,
             "cap_attempts_per_worker": 8, "cap_commits": 7,
             "thread_join_seconds": 5, "suite_seconds": 10,
             "suites": 1, "retries": 0, "target_launches": 0, "network_calls": 0,
             "arm_order": ARMS}
    require(all(type(protocol.get(k)) is type(v) and protocol[k] == v for k, v in fixed.items()), "exact bounded protocol")
    result_raw = read(result_dir / "result.json", 1048576)
    result = strict_json(result_raw)
    require(result.get("schema_version") == 1 and result.get("experiment") == fixed["experiment"]
            and result.get("accepted") is True and result.get("failure") is None,
            "producer reports accepted fixture")
    require(result.get("protocol_sha256") == sha(protocol_raw) and result.get("seed") == fixed["seed"],
            "protocol hash and seed")
    require(all(result.get(k) == 0 for k in ["retries", "target_launches", "network_calls"]),
            "no declared runtime targets, network or retry")
    require(type(result.get("wall_seconds")) in [float, int]
            and 0 <= result["wall_seconds"] < fixed["suite_seconds"], "suite deadline")
    started, completed = [dt.datetime.fromisoformat(result[k].replace("Z", "+00:00"))
                          for k in ["started_at_utc", "completed_at_utc"]]
    require(started.tzinfo is not None and completed.tzinfo is not None
            and 0 <= (completed - started).total_seconds() < fixed["suite_seconds"],
            "UTC interval within suite ceiling")
    runtime = result.get("runtime", {})
    require(runtime.get("implementation") and runtime.get("version") and runtime.get("platform"),
            "runtime identity recorded")
    arms = result.get("arms")
    require(isinstance(arms, list) and [a.get("arm") for a in arms] == ARMS,
            "seven exact ordered arms")
    summaries = []
    fault_row = encoded({"kind": "fault", "seq": 0, "item": "00000000"})
    for index, arm in enumerate(arms):
        name = ARMS[index]
        require(arm.get("accepted") is True and arm.get("trace") == name + ".jsonl",
                name + ": accepted control and exact trace basename")
        raw = read(result_dir / (name + ".jsonl"), fixed["max_total_bytes"])
        require(arm.get("trace_sha256") == sha(raw) and arm.get("trace_bytes") == len(raw)
                and arm.get("saved_bytes_match_stopped_sink") is True,
                name + ": saved trace bytes and hash")
        if index < 3:
            count = fixed["workers"] * (fixed["rows_per_worker"] if index == 0 else fixed["cap_attempts_per_worker"])
            wanted = count if index == 0 else fixed["cap_commits"]
            max_rows = fixed["cap_commits"] if name == "row-cap" else count
            total = (sum(len(encoded({"kind": name, "seq": seq, "item": "00000000"}))
                         for seq in range(wanted)) if name == "byte-cap" else fixed["max_total_bytes"])
            require(arm.get("max_rows") == max_rows and arm.get("max_row_bytes") == fixed["max_row_bytes"]
                    and arm.get("max_total_bytes") == total, name + ": independently recomputed caps")
            require(len(raw) <= total and raw.endswith(b"\n"), name + ": total bytes and final newline")
            lines = raw.split(b"\n")[:-1]
            require(len(lines) == wanted and len(lines) <= max_rows, name + ": admitted row count")
            rows = []
            for seq, line in enumerate(lines):
                require(len(line) + 1 <= fixed["max_row_bytes"], name + ": row byte cap")
                row = strict_json(line.decode("utf-8"))
                require(type(row) is dict and set(row) == {"kind", "seq", "item"}
                        and type(row["seq"]) is int and row["seq"] == seq
                        and row["kind"] == name and type(row["item"]) is str,
                        name + ": exact schema and contiguous sequence")
                require(encoded(row) == line + b"\n", name + ": exact canonical row bytes")
                rows.append(row)
            outcomes = arm.get("outcomes", [])
            universe = {f"{value:08d}" for value in range(count)}
            require(len(outcomes) == count
                    and [o.get("item") for o in outcomes] == sorted(universe),
                    name + ": exact original attempted ID universe")
            require(all(o.get("status") in ["committed", "cap_rejected"] for o in outcomes),
                    name + ": known admission outcomes")
            admitted = [o for o in outcomes if o["status"] == "committed"]
            refused = [o for o in outcomes if o["status"] == "cap_rejected"]
            require(len(admitted) == wanted and len(refused) == count - wanted
                    and all(set(o) == {"item", "status", "seq"} for o in admitted)
                    and all(set(o) == {"item", "status"} for o in refused),
                    name + ": exact admission and refusal counts")
            require(len({row["item"] for row in rows}) == wanted
                    and {row["item"] for row in rows} == {o["item"] for o in admitted},
                    name + ": unique saved and admitted IDs")
            require(all(type(o["seq"]) is int and 0 <= o["seq"] < wanted
                        and rows[o["seq"]]["item"] == o["item"] for o in admitted),
                    name + ": outcome-to-saved-sequence mapping")
            require(arm.get("workers_stopped") is True and arm.get("attempts") == count
                    and arm.get("committed") == wanted and arm.get("cap_rejected") == count - wanted
                    and arm.get("bytes") == len(raw)
                    and arm.get("saved_prefix_independently_validated") is True,
                    name + ": stopped workers and result counters")
            summaries.append({"arm": name, "committed": wanted, "refused": count-wanted, "bytes": len(raw)})
        else:
            tails = {"short-write": fault_row[:-1], "write-exception": fault_row[:5],
                     "flush-exception": fault_row, "recursive-write": b""}
            require(raw == tails[name], name + ": exact declared uncertain tail")
            snapshot = arm.get("snapshot", {})
            failure = snapshot.get("failure", {})
            require(snapshot.get("committed_rows") == snapshot.get("committed_bytes") == 0
                    and snapshot.get("records") == [] and snapshot.get("poisoned") is True
                    and snapshot.get("commit_scope") == "exact binary write plus successful flush; no fsync/power-loss claim",
                    name + ": zero committed prefix and permanent poison")
            flushed = name == "flush-exception"
            expected_return = len(fault_row) if flushed else len(fault_row)-1 if name == "short-write" else None
            require(set(failure) == {"seq", "row_bytes", "row_sha256", "stage", "write_return",
                    "flush_completed", "sink_may_have_uncommitted_bytes", "error_type"}
                    and failure.get("seq") == 0 and failure.get("row_bytes") == len(fault_row)
                    and failure.get("row_sha256") == sha(fault_row)
                    and failure.get("stage") == ("flush" if flushed else "write")
                    and failure.get("write_return") == expected_return
                    and failure.get("flush_completed") is False
                    and failure.get("sink_may_have_uncommitted_bytes") is True
                    and failure.get("error_type") == ("LedgerReentrantError" if name == "recursive-write" else "OSError"),
                    name + ": explicit failed attempt identity")
            require(arm.get("write_calls") == 1 and arm.get("flush_calls") == int(flushed)
                    and arm.get("saved_prefix_independently_validated") is False
                    and arm.get("tail_status") == "uncertain and uncommitted; never merged into accepted prefix",
                    name + ": no retry I/O or accepted tail claim")
            summaries.append({"arm": name, "committed": 0, "uncertain_tail_bytes": len(raw), "poisoned": True})
    require(result.get("reader_controls") == {name: "rejected" for name in CONTROLS},
            "seven recorded reader rejection controls")

    source_binding = {"verified": False, "reason": "No implementation file supplied"}
    if implementation_path is not None:
        impl_raw = read(Path(implementation_path), 65536)
        implementation = strict_json(impl_raw)
        require(result.get("freeze_sha256") == sha(impl_raw), "implementation freeze raw hash")
        require(implementation.get("schema_version") == 1
                and implementation.get("kind") == "thread-ledger-execution-freeze", "implementation schema and kind")
        files = implementation.get("files")
        require(isinstance(files, dict) and bool(files), "implementation source map")
        base = Path(source_root or ".").resolve()
        digests = {}
        for relative, digest in files.items():
            path = Path(relative)
            require(not path.is_absolute() and ".." not in path.parts
                    and re.fullmatch(r"[0-9a-f]{64}", digest or "") is not None,
                    "portable relative implementation path and digest")
            resolved = (base / path).resolve()
            require(resolved.is_relative_to(base), "implementation source stays inside source root")
            content = read(resolved, 1048576)
            require(sha(content) == digest, "frozen source hash: " + relative)
            require(path.name not in digests, "unambiguous frozen source basename")
            digests[path.name] = digest
        sources = result.get("source_hashes", {})
        observed = {name.replace("\\", "/").rsplit("/", 1)[-1]: digest
                    for name, digest in sources.items()}
        require(set(observed) == {"trace_ledger.py", "trace_ledger_probe.py"}
                and all(digests.get(name) == digest for name, digest in observed.items()),
                "producer source identities match frozen source bytes")
        source_binding = {"verified": True, "implementation_sha256": sha(impl_raw)}
    return {"passed_audit": True, "producer_accepted": result["accepted"],
            "checks": len(checks), "protocol_sha256": sha(protocol_raw),
            "result_sha256": sha(result_raw), "artifacts": artifacts,
            "arms": summaries, "source_binding": source_binding,
            "limits": ["Saved artifacts only; no thread scheduling reproduction or performance estimate.",
                       "Flush is not fsync/power-loss durability; uncertain tails are retained, not accepted rows.",
                       "This fixture does not repair prior native topology/events or clear H1/H2/H3/H4 gates."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--result-dir", required=True, type=Path)
    parser.add_argument("--implementation", type=Path)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.protocol, args.result_dir, args.implementation, args.source_root)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
        result = {"passed_audit": False, "error": type(error).__name__ + ": " + str(error)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return 0 if result["passed_audit"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

