"""One preregistered, original, pure-thread ledger probe; main is opt-in only."""
import argparse
import datetime
import hashlib
import io
import json
import math
import random
from pathlib import Path
import sys
import threading
import time

if __package__:
    from . import trace_ledger as ledger_module
elif Path(__file__).resolve().parent.name == "experiments":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from experiments import trace_ledger as ledger_module
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import trace_ledger as ledger_module


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strict_json(raw):
    def finite(value):
        raise ValueError("Nonfinite JSON: " + value)
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("Nonfinite JSON numeric overflow")
        return parsed
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON key")
            value[key] = item
        return value
    return json.loads(raw, parse_constant=finite, parse_float=finite_float, object_pairs_hook=unique)


def decode_trace(raw, *, max_rows, max_row_bytes, max_total_bytes, expected_ids=None, expected_kind=None):
    """Reader checks saved bytes independently of the writer's memory state."""
    if type(raw) is not bytes or len(raw) > max_total_bytes or raw and not raw.endswith(b"\n"):
        raise ValueError("Trace byte cap/type/final newline rejected")
    lines = raw.splitlines(keepends=True)
    if len(lines) > max_rows:
        raise ValueError("Trace row count rejected")
    rows = []
    for index, line in enumerate(lines):
        if len(line) > max_row_bytes or not line.endswith(b"\n"):
            raise ValueError("Trace row byte/newline rejected")
        row = strict_json(line.decode("utf-8"))
        if (not isinstance(row, dict) or type(row.get("seq")) is not int or row["seq"] != index
                or not isinstance(row.get("kind"), str) or not row["kind"]):
            raise ValueError("Trace sequence/schema rejected")
        rows.append(row)
    if expected_ids is not None:
        if any(set(row) != {"kind", "seq", "item"} or type(row["item"]) is not str for row in rows):
            raise ValueError("Trace exact row schema rejected")
        ids = [row.get("item") for row in rows]
        if len(ids) != len(expected_ids) or len(set(ids)) != len(ids) or set(ids) != set(expected_ids):
            raise ValueError("Trace item custody rejected")
    if expected_kind is not None and any(row["kind"] != expected_kind for row in rows):
        raise ValueError("Trace arm kind rejected")
    return rows


def concurrent_arm(name, protocol, suite_deadline):
    workers = protocol["workers"]
    each = protocol["rows_per_worker"] if name == "all-admitted" else protocol["cap_attempts_per_worker"]
    count = workers * each
    ids = [f"{index:08d}" for index in range(count)]
    random.Random(protocol["seed"] + ["all-admitted", "row-cap", "byte-cap"].index(name)).shuffle(ids)
    max_rows = protocol["cap_commits"] if name == "row-cap" else count
    total_bytes = protocol["max_total_bytes"]
    if name == "byte-cap":
        # Independently compute exact7-row budget. All IDs have the same width.
        total_bytes = sum(len((json.dumps({"kind": name, "seq": index, "item": "00000000"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()) for index in range(protocol["cap_commits"]))
    sink = io.BytesIO()
    ledger = ledger_module.BoundedJSONLLedger(sink, max_rows=max_rows,
        max_row_bytes=protocol["max_row_bytes"], max_total_bytes=total_bytes)
    barrier = threading.Barrier(workers)
    deadline = min(time.perf_counter() + protocol["thread_join_seconds"], suite_deadline)
    outcomes, errors, guard = [], [], threading.Lock()
    def writer(index):
        try:
            barrier.wait(timeout=max(0, deadline - time.perf_counter()))
            for item in ids[index * each:(index + 1) * each]:
                if time.perf_counter() >= deadline:
                    raise TimeoutError("Nonrenewable thread deadline")
                try:
                    row = ledger.append(name, item=item)
                    outcome = {"item": item, "status": "committed", "seq": row["seq"]}
                except ledger_module.LedgerLimitError:
                    outcome = {"item": item, "status": "cap_rejected"}
                with guard:
                    outcomes.append(outcome)
        except BaseException as exc:
            with guard:
                errors.append(type(exc).__name__)
    threads = [threading.Thread(target=writer, args=(index,), name=f"ledger-writer-{index}", daemon=True) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max(0, deadline - time.perf_counter()))
    stopped = all(not thread.is_alive() for thread in threads)
    if not stopped or errors or time.perf_counter() >= deadline:
        # Never call a possibly held ledger lock or snapshot an active sink.
        raise RuntimeError("Pure-thread stop/error/deadline rejection: " + str(errors))
    raw, state = sink.getvalue(), ledger.snapshot()
    accepted_ids = [row["item"] for row in outcomes if row["status"] == "committed"]
    rows = decode_trace(raw, max_rows=max_rows, max_row_bytes=protocol["max_row_bytes"],
        max_total_bytes=total_bytes, expected_ids=accepted_ids, expected_kind=name)
    wanted = count if name == "all-admitted" else protocol["cap_commits"]
    if (len(rows) != wanted or len(outcomes) != count or state["records"] != rows or state["poisoned"]
            or state["committed_bytes"] != len(raw) or state["committed_rows"] != len(rows)
            or len([row for row in outcomes if row["status"] == "cap_rejected"]) != count - wanted
            or len(set(row["item"] for row in outcomes)) != count
            or set(row["item"] for row in outcomes) != set(ids)
            or any(rows[row["seq"]]["item"] != row["item"] for row in outcomes if row["status"] == "committed")):
        raise ValueError("Concurrent saved bytes/state/admission rejection")
    return {"accepted": True, "arm": name, "workers_stopped": stopped, "attempts": count,
        "committed": wanted, "cap_rejected": count - wanted, "max_rows": max_rows,
        "max_row_bytes": protocol["max_row_bytes"], "max_total_bytes": total_bytes,
        "bytes": len(raw), "outcomes": sorted(outcomes, key=lambda row: row["item"])}, raw


class FaultSink:
    def __init__(self, mode):
        self.mode, self.bytes = mode, io.BytesIO()
        self.write_calls = self.flush_calls = 0
        self.ledger = None

    def write(self, data):
        self.write_calls += 1
        if self.mode == "recursive-write":
            self.ledger.append("inner")
        if self.mode == "short-write":
            return self.bytes.write(data[:-1])
        if self.mode == "write-exception":
            self.bytes.write(data[:5])
            raise OSError("Declared partial write failure")
        return self.bytes.write(data)

    def flush(self):
        self.flush_calls += 1
        if self.mode == "flush-exception":
            raise OSError("Declared flush failure")


def fault_arm(name):
    sink = FaultSink(name)
    ledger = ledger_module.BoundedJSONLLedger(sink)
    sink.ledger = ledger
    try:
        ledger.append("fault", item="00000000")
    except ledger_module.LedgerIOError:
        pass
    else:
        raise ValueError("Declared I/O fault was accepted")
    before = (sink.write_calls, sink.flush_calls, sink.bytes.getvalue())
    try:
        ledger.append("must_not_retry")
    except ledger_module.LedgerPoisonedError:
        pass
    else:
        raise ValueError("Poisoned ledger admitted a later append")
    state = ledger.snapshot()
    if (state["committed_rows"] != 0 or state["committed_bytes"] != 0 or not state["poisoned"]
            or state["failure"]["seq"] != 0 or not state["failure"]["sink_may_have_uncommitted_bytes"]
            or before != (sink.write_calls, sink.flush_calls, sink.bytes.getvalue())):
        raise ValueError("Uncertain I/O state was hidden or retried")
    return {"accepted": True, "arm": name, "snapshot": state, "write_calls": sink.write_calls,
        "flush_calls": sink.flush_calls, "tail_status": "uncertain and uncommitted; never merged into accepted prefix"}, sink.bytes.getvalue()


def reader_controls(protocol):
    line = b'{"item":"00000000","kind":"control","seq":0}\n'
    valid = dict(max_rows=2, max_row_bytes=512, max_total_bytes=1024)
    cases = {"duplicate_sequence": line + line,
        "missing_sequence": line + line.replace(b'"seq":0', b'"seq":2'),
        "truncated": line[:-1], "oversized": b"x" * 1025,
        "duplicate_key": b'{"kind":"a","seq":0,"seq":0}\n',
        "nonfinite": b'{"kind":"a","seq":0,"x":NaN}\n',
        "numeric_overflow": b'{"kind":"a","seq":0,"x":1e999}\n'}
    for name, raw in cases.items():
        try:
            decode_trace(raw, **valid)
        except (ValueError, UnicodeError):
            continue
        raise ValueError("Saved-reader mutation accepted: " + name)
    return {name: "rejected" for name in cases}


def verify_freeze(path, protocol_path, output):
    freeze = strict_json(Path(path).read_text(encoding="utf-8"))
    if (freeze.get("schema_version") != 1 or freeze.get("kind") != "thread-ledger-execution-freeze"
            or Path(freeze["output_directory"]).resolve() != output.resolve()):
        raise ValueError("Wrong independent freeze/output")
    required = {Path(__file__).resolve(), Path(ledger_module.__file__).resolve(), protocol_path.resolve()}
    declared = {Path(name).resolve(strict=True): digest for name, digest in freeze["files"].items()}
    if not required <= declared.keys() or any(sha(name) != digest for name, digest in declared.items()):
        raise ValueError("Frozen input bytes missing/changed")
    return freeze


def run(protocol_path, output, freeze_path):
    protocol_path, output, freeze_path = map(lambda value: Path(value).resolve(), [protocol_path, output, freeze_path])
    verify_freeze(freeze_path, protocol_path, output)
    protocol = strict_json(protocol_path.read_text(encoding="utf-8"))
    expected = {"schema_version": 1, "experiment": "thread-ledger-serialization", "seed": 20261019,
        "workers": 4, "rows_per_worker": 64, "max_row_bytes": 512, "max_total_bytes": 65536,
        "cap_attempts_per_worker": 8, "cap_commits": 7, "thread_join_seconds": 5, "suite_seconds": 10,
        "suites": 1, "retries": 0, "target_launches": 0, "network_calls": 0,
        "arm_order": ["all-admitted", "row-cap", "byte-cap", "short-write", "write-exception", "flush-exception", "recursive-write"]}
    if any(protocol.get(key) != value for key, value in expected.items()):
        raise ValueError("Preregistered bounded protocol changed")
    def no_runtime(event, args):
        if event in ["subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn", "ctypes.dlopen"] or event.startswith("socket."):
            raise RuntimeError("Pure-thread suite denied capability: " + event)
    sys.addaudithook(no_runtime)
    output.mkdir(parents=True, exist_ok=False)
    began = time.perf_counter()
    result = {"schema_version": 1, "experiment": protocol["experiment"], "accepted": False, "failure": None,
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "seed": protocol["seed"],
        "protocol_sha256": sha(protocol_path), "freeze_sha256": sha(freeze_path), "arms": [],
        "source_hashes": {str(Path(__file__).resolve()): sha(__file__), str(Path(ledger_module.__file__).resolve()): sha(ledger_module.__file__)},
        "runtime": {"version": sys.version, "implementation": sys.implementation.name, "platform": sys.platform},
        "target_launches": 0, "network_calls": 0, "retries": 0, "scope": protocol["scope"]}
    try:
        for name in protocol["arm_order"]:
            if time.perf_counter() >= began + protocol["suite_seconds"]:
                raise TimeoutError("Nonrenewable suite deadline")
            arm, raw = concurrent_arm(name, protocol, began + protocol["suite_seconds"]) if name in protocol["arm_order"][:3] else fault_arm(name)
            trace = output / (name + ".jsonl")
            with trace.open("xb") as stream:
                if stream.write(raw) != len(raw):
                    raise OSError("Saved trace short write")
                stream.flush()
            saved = trace.read_bytes()
            if saved != raw:
                raise ValueError("Saved trace bytes differ from stopped sink bytes")
            if name in protocol["arm_order"][:3]:
                decode_trace(saved, max_rows=arm["max_rows"], max_row_bytes=arm["max_row_bytes"],
                    max_total_bytes=arm["max_total_bytes"], expected_kind=name,
                    expected_ids=[row["item"] for row in arm["outcomes"] if row["status"] == "committed"])
                arm["saved_prefix_independently_validated"] = True
            else:
                arm["saved_prefix_independently_validated"] = False
            arm.update(trace=trace.name, trace_sha256=hashlib.sha256(saved).hexdigest(), trace_bytes=len(saved),
                saved_bytes_match_stopped_sink=True)
            result["arms"].append(arm)
        result["reader_controls"] = reader_controls(protocol)
        verify_freeze(freeze_path, protocol_path, output)
        result["accepted"] = True
    except BaseException as exc:
        result["failure"] = type(exc).__name__ + ": " + str(exc)
    result["wall_seconds"] = time.perf_counter() - began
    if result["wall_seconds"] >= protocol["suite_seconds"]:
        result["accepted"], result["failure"] = False, "Suite deadline exceeded"
    result["completed_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with (output / "result.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.protocol, args.output, args.freeze)
    print(json.dumps({"accepted": result["accepted"], "failure": result["failure"], "output": str(args.output)}))
    raise SystemExit(0 if result["accepted"] else 1)
