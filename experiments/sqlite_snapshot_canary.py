"""Known SQLite WAL snapshot semantics, with an intentionally stale file-copy control.

One bounded suite; no retries. The writer owns a live WAL connection, commits
generation one, then holds an uncommitted generation two. A main-file-only copy
and the SQLite backup API are restored by two fresh reader processes each.
This is an independent storage canary, not an upstream agent implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = ROOT / "fixtures/sqlite-snapshot-canary/protocol.json"
TABLES = {"contexts": "session_id", "messages": "message_id", "receipts": "receipt_id"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def child_path(root, relative):
    """Reject absolute paths, traversal and existing symlink escapes."""
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in (".", "..") for p in relative.parts):
        raise ValueError("artifact path must be a nonempty relative descendant")
    root = Path(root).resolve()
    result = (root / relative).resolve()
    if result == root or not result.is_relative_to(root):
        raise ValueError("artifact path escapes output directory")
    return result


def validate_protocol(value):
    """The v1 experiment is fixed; CLI does not permit tuning after observation."""
    expected = {
        "schema_version": 1, "name": "sqlite-snapshot-correctness-canary-v1", "seed": 0,
        "journal_mode": "wal", "synchronous": 2, "wal_autocheckpoint": 0,
        "worker_timeout_seconds": 10, "suite_timeout_seconds": 60, "cleanup_timeout_seconds": 10,
        "crash_exit_code": 86, "fresh_readers_per_database": 2,
        "capture_order": ["main_file_copy", "sqlite_backup"],
        "reader_order": ["source", "main_file_copy", "sqlite_backup"],
    }
    for key, literal in expected.items():
        if value.get(key) != literal or type(value.get(key)) is not type(literal):
            raise ValueError("unsupported v1 protocol: " + key)
    snapshots = value.get("expected_snapshots", {})
    literal0 = {
        "contexts": [["session-0", 0, "turn-0", "ready"]],
        "messages": [["message-0", 0, "literal generation zero"]],
        "receipts": [["receipt-0", "message-0", 0, "committed"]],
    }
    literal1 = {
        "contexts": [["session-0", 1, "turn-1", "ready"]],
        "messages": [["message-0", 0, "literal generation zero"], ["message-1", 1, "literal generation one"]],
        "receipts": [["receipt-0", "message-0", 0, "committed"], ["receipt-1", "message-1", 1, "committed"]],
    }
    if snapshots != {"generation0": literal0, "generation1": literal1}:
        raise ValueError("v1 requires the fixed literal generation oracles")
    if value.get("uncommitted_generation2") != {
        "context": ["session-0", 2, "turn-2", "ready"],
        "message": ["message-2", 2, "uncommitted generation two"],
        "receipt": ["receipt-2", "message-2", 2, "committed"],
    }:
        raise ValueError("v1 requires the fixed uncommitted transaction")
    return value


def read_protocol(path):
    return validate_protocol(json.loads(Path(path).read_text(encoding="utf-8")))


def verify_freeze(protocol_path, producer_sha256, protocol_sha256):
    for label, expected, path in (("producer", producer_sha256, Path(__file__)),
                                   ("protocol", protocol_sha256, Path(protocol_path))):
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise ValueError("require frozen " + label + " SHA256")
        if file_hash(path) != expected:
            raise ValueError("frozen " + label + " SHA256 mismatch")


def verify_implementation_freeze(freeze_path, protocol_path):
    if freeze_path is None:
        raise ValueError("--freeze is required before creating an output or starting workers")
    freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
    required = {"experiments/sqlite_snapshot_canary.py", "tests/test_sqlite_snapshot_canary.py",
                "fixtures/sqlite-snapshot-canary/protocol.json"}
    if (freeze.get("schema_version") != 1 or type(freeze.get("schema_version")) is not int or
            freeze.get("experiment") != "sqlite-snapshot-correctness-canary-v1" or
            set(freeze.get("files", {})) != required):
        raise ValueError("freeze must bind exactly the v1 producer, tests and protocol")
    for relative, expected in freeze["files"].items():
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise ValueError("invalid implementation freeze SHA256")
        if file_hash(ROOT / relative) != expected:
            raise ValueError("implementation freeze mismatch: " + relative)
    verify_freeze(protocol_path, freeze["files"]["experiments/sqlite_snapshot_canary.py"],
                  freeze["files"]["fixtures/sqlite-snapshot-canary/protocol.json"])
    return freeze


def uncommitted_oracle(protocol):
    # Copy the literal generation-one oracle, then apply the fixed second write.
    snapshot = json.loads(canonical(protocol["expected_snapshots"]["generation1"]))
    second = protocol["uncommitted_generation2"]
    snapshot["contexts"] = [second["context"]]
    snapshot["messages"].append(second["message"])
    snapshot["receipts"].append(second["receipt"])
    return snapshot


def parse_writer_transcript(lines):
    parsed, errors = [], []
    for index, line in enumerate(lines):
        try:
            value = json.loads(line)
            if not isinstance(value, dict) or not isinstance(value.get("event"), str):
                raise ValueError("writer line must be an event object")
            parsed.append(value)
        except (ValueError, TypeError) as error:
            errors.append({"line": index + 1, "type": type(error).__name__, "message": str(error)})
    return {"events": parsed, "errors": errors}


def rows(connection):
    return {table: [list(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {key}")]
            for table, key in TABLES.items()}


def emit(event, **data):
    print(canonical({"event": event, "at": utc_now(), "pid": os.getpid(), **data}), flush=True)


def writer_worker(path, protocol):
    connection = sqlite3.connect(path, isolation_level=None, timeout=2)
    try:
        mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.executescript("""
        CREATE TABLE contexts(session_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                              turn_id TEXT NOT NULL, status TEXT NOT NULL);
        CREATE TABLE messages(message_id TEXT PRIMARY KEY, context_version INTEGER NOT NULL, body TEXT NOT NULL);
        CREATE TABLE receipts(receipt_id TEXT PRIMARY KEY, message_id TEXT NOT NULL,
                              context_version INTEGER NOT NULL, status TEXT NOT NULL);
        """)
        connection.execute("BEGIN IMMEDIATE")
        for table, entries in protocol["expected_snapshots"]["generation0"].items():
            for row in entries:
                connection.execute(f"INSERT INTO {table} VALUES({','.join('?' for _ in row)})", row)
        connection.commit()
        checkpoint = list(connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone())
        emit("baseline_ready", journal_mode=mode,
             synchronous=connection.execute("PRAGMA synchronous").fetchone()[0],
             wal_autocheckpoint=connection.execute("PRAGMA wal_autocheckpoint").fetchone()[0],
             checkpoint=checkpoint, snapshot=rows(connection), main_sha256=file_hash(path))
        if sys.stdin.readline().strip() != "commit_generation1":
            raise ValueError("expected commit_generation1 command")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE contexts SET version=1,turn_id='turn-1' WHERE session_id='session-0'")
        connection.execute("INSERT INTO messages VALUES('message-1',1,'literal generation one')")
        connection.execute("INSERT INTO receipts VALUES('receipt-1','message-1',1,'committed')")
        connection.commit()
        emit("generation1_committed", snapshot=rows(connection), main_sha256=file_hash(path))
        if sys.stdin.readline().strip() != "stage_generation2":
            raise ValueError("expected stage_generation2 command")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE contexts SET version=2,turn_id='turn-2' WHERE session_id='session-0'")
        second = protocol["uncommitted_generation2"]
        connection.execute("INSERT INTO messages VALUES(?,?,?)", second["message"])
        connection.execute("INSERT INTO receipts VALUES(?,?,?,?)", second["receipt"])
        emit("generation2_uncommitted", in_transaction=connection.in_transaction, snapshot=rows(connection))
        if sys.stdin.readline().strip() != "crash":
            raise ValueError("expected crash command")
        emit("fail_stop_requested", in_transaction=connection.in_transaction)
        os._exit(protocol["crash_exit_code"])
    finally:
        connection.close()


def open_readonly(path):
    # mode=ro refuses a missing database. No immutable flag or checkpoint is used.
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True,
                           isolation_level=None, timeout=2)


def reader_worker(path):
    connection = open_readonly(path)
    try:
        connection.execute("BEGIN")
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        snapshot = rows(connection)
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        connection.commit()
    finally:
        connection.close()
    emit("reader_closed", integrity_check=integrity, snapshot=snapshot,
         logical_sha256=digest(snapshot), journal_mode=mode, sqlite_version=sqlite3.sqlite_version)


def backup_worker(source, destination):
    source_connection = open_readonly(source)
    destination_connection = sqlite3.connect(destination, isolation_level=None, timeout=2)
    progress = []
    try:
        source_before = rows(source_connection)
        source_connection.backup(destination_connection, pages=1,
                                 progress=lambda status, remaining, total: progress.append(
                                     {"status": status, "remaining": remaining, "total": total}), sleep=0.01)
    finally:
        destination_connection.close()
        source_connection.close()
    emit("backup_closed", source_before=source_before, progress=progress,
         destination_sha256=file_hash(destination), sqlite_version=sqlite3.sqlite_version)


def evaluate_reads(observations, expected):
    """Compare independent reopenings to literal protocol truth, not writer claims."""
    gates = {}
    for arm, generation in (("source", "generation1"), ("main_file_copy", "generation0"),
                            ("sqlite_backup", "generation1")):
        actual = observations.get(arm, [])
        gates[arm + ":two_readers"] = len(actual) == 2
        for index, result in enumerate(actual):
            prefix = arm + f":reader{index + 1}:"
            gates[prefix + "integrity_ok"] = result.get("integrity_check") == ["ok"]
            gates[prefix + "literal_snapshot"] = result.get("snapshot") == expected[generation]
            gates[prefix + "logical_hash"] = result.get("logical_sha256") == digest(expected[generation])
        gates[arm + ":reopen_stable"] = (len(actual) == 2 and
            actual[0].get("snapshot") == actual[1].get("snapshot") and
            actual[0].get("logical_sha256") == actual[1].get("logical_sha256"))
    return gates


def run_probe(output, protocol_path=DEFAULT_PROTOCOL, *, freeze_path=None):
    freeze = verify_implementation_freeze(freeze_path, protocol_path)
    producer_sha256 = freeze["files"]["experiments/sqlite_snapshot_canary.py"]
    protocol_sha256 = freeze["files"]["fixtures/sqlite-snapshot-canary/protocol.json"]
    protocol = read_protocol(protocol_path)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = child_path(output, "live/source.sqlite3")
    source.parent.mkdir()
    paths = {"source": source, "main_file_copy": child_path(output, "main-file-copy.sqlite3"),
             "sqlite_backup": child_path(output, "sqlite-backup.sqlite3")}
    raw = child_path(output, "raw")
    raw.mkdir()
    worker_protocol = child_path(output, "protocol.json")
    shutil.copyfile(protocol_path, worker_protocol)
    worker_freeze = child_path(output, "implementation.json")
    shutil.copyfile(freeze_path, worker_freeze)
    # These workers use only stdlib. On Windows the base executable avoids a venv
    # launcher that could leave a separate Python descendant after timeout kill.
    worker_python = str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())
    if not Path(worker_python).is_file():
        raise ValueError("base Python executable is not an existing file")
    start = time.perf_counter()
    report = {"schema_version": 1, "experiment": protocol["name"], "started_at": utc_now(),
              "protocol_sha256": file_hash(protocol_path), "producer_sha256": file_hash(__file__),
              "worker_python": worker_python,
              "implementation_sha256": file_hash(freeze_path),
              "seed": protocol["seed"], "sqlite_version": sqlite3.sqlite_version,
              "suite_launches": 1, "retries": 0, "observations": {}, "gates": {},
              "limitations": protocol["limitations"], "error": None}
    writer = None
    writer_lines = []
    writer_queue = queue.Queue()
    events_path = child_path(output, "events.jsonl")

    def event(action, **data):
        with events_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical({"event": action, "at": utc_now(),
                                    "elapsed_seconds": time.perf_counter() - start, **data}) + "\n")

    def remaining():
        left = protocol["suite_timeout_seconds"] - (time.perf_counter() - start)
        if left <= 0:
            raise TimeoutError("suite deadline exhausted")
        return min(protocol["worker_timeout_seconds"], left)

    def command(value, expected):
        writer.stdin.write(value + "\n")
        writer.stdin.flush()
        event("writer_command", command=value)
        return await_writer(expected)

    def await_writer(expected):
        try:
            line = writer_queue.get(timeout=remaining())
        except queue.Empty as error:
            raise TimeoutError("writer acknowledgement deadline: " + expected) from error
        if line is None:
            raise RuntimeError("writer stdout closed before " + expected)
        value = json.loads(line)
        event("writer_ack", expected=expected, observed=value)
        if value.get("event") != expected:
            raise ValueError("unexpected writer acknowledgement")
        return value

    def worker(label, *args):
        argv = [worker_python, "-S", "-X", "utf8", str(Path(__file__).resolve()),
                "--protocol", str(worker_protocol), "--freeze", str(worker_freeze), *args]
        timeout = remaining()
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        event("worker_started", role=label, pid=process.pid, arguments=list(args))
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            try:
                process.kill()
            except OSError as kill_error:
                if process.poll() is None:
                    report["cleanup_error"] = "worker kill failed: " + str(kill_error)
            try:
                stdout, stderr = process.communicate(timeout=protocol["cleanup_timeout_seconds"])
                event("worker_timeout_killed_and_waited", role=label, pid=process.pid, exit_code=process.returncode)
            except subprocess.TimeoutExpired:
                stdout = (error.stdout or b"").decode("utf-8", errors="replace")
                stderr = (error.stderr or b"").decode("utf-8", errors="replace")
                report["cleanup_error"] = "worker exit unobserved after kill deadline: " + label
            (raw / (label + ".stdout")).write_text(stdout, encoding="utf-8", newline="\n")
            (raw / (label + ".stderr")).write_text(stderr, encoding="utf-8", newline="\n")
            raise TimeoutError("worker deadline: " + label) from error
        (raw / (label + ".jsonl")).write_text(stdout, encoding="utf-8", newline="\n")
        (raw / (label + ".stderr")).write_text(stderr, encoding="utf-8", newline="\n")
        event("worker_exited", role=label, pid=process.pid, exit_code=process.returncode)
        if process.returncode:
            raise RuntimeError(f"{label} exit {process.returncode}: {stderr[:300]}")
        lines = stdout.splitlines()
        if len(lines) != 1:
            raise ValueError("worker must return exactly one JSON event: " + label)
        result = json.loads(lines[0])
        expected_event = "backup_closed" if label == "backup" else "reader_closed"
        if result.get("event") != expected_event or result.get("pid") != process.pid:
            raise ValueError("worker event/PID does not match launched role: " + label)
        return result

    def physical_files(path):
        observed = {}
        for suffix in ("", "-wal", "-shm"):
            file = Path(str(path) + suffix)
            observed[file.name] = ({"exists": True, "bytes": file.stat().st_size,
                                    "sha256": file_hash(file)} if file.is_file() else {"exists": False})
        return observed

    thread = None
    try:
        writer = subprocess.Popen([worker_python, "-S", "-X", "utf8", str(Path(__file__).resolve()),
                                   "--protocol", str(worker_protocol), "--freeze", str(worker_freeze),
                                   "--writer", str(source)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, encoding="utf-8", bufsize=1)
        report["writer_pid"] = writer.pid

        def collect_writer():
            for line in writer.stdout:
                writer_lines.append(line)
                writer_queue.put(line)
            writer_queue.put(None)

        thread = threading.Thread(target=collect_writer, daemon=True)
        thread.start()
        baseline = await_writer("baseline_ready")
        committed = command("commit_generation1", "generation1_committed")
        staged = command("stage_generation2", "generation2_uncommitted")
        wal = Path(str(source) + "-wal")
        report["capture_barrier"] = {"baseline": baseline, "committed": committed, "staged": staged,
                                      "main_sha256": file_hash(source), "wal_bytes": wal.stat().st_size,
                                      "wal_sha256": file_hash(wal)}
        event("capture_barrier", **report["capture_barrier"])
        if writer.poll() is not None:
            raise RuntimeError("writer exited before main-file capture")
        shutil.copyfile(source, paths["main_file_copy"])
        event("main_file_copy_closed", sha256=file_hash(paths["main_file_copy"]))
        if writer.poll() is not None:
            raise RuntimeError("writer exited before backup capture")
        report["backup"] = worker("backup", "--backup", str(source), str(paths["sqlite_backup"]))
        if writer.poll() is not None:
            raise RuntimeError("writer exited before both captures completed")
        report["writer_alive_until_captures_completed"] = True
        writer.stdin.write("crash\n")
        writer.stdin.flush()
        event("writer_command", command="crash")
        report["writer_exit_code"] = writer.wait(timeout=remaining())
        event("writer_exited", exit_code=report["writer_exit_code"])
        report["before_any_reader_files"] = {arm: physical_files(path) for arm, path in paths.items()}
        event("physical_inventory", phase="after_fail_stop_before_any_reader", files=report["before_any_reader_files"])
        for arm in protocol["reader_order"]:
            report["observations"][arm] = []
            for index in range(protocol["fresh_readers_per_database"]):
                event("reader_file_observation", arm=arm, reader=index + 1,
                      phase="before_reader", files=physical_files(paths[arm]))
                result = worker(f"{arm}-reader{index + 1}", "--reader", str(paths[arm]))
                report["observations"][arm].append(result)
                event("reader_file_observation", arm=arm, reader=index + 1,
                      phase="after_reader_normal_close", files=physical_files(paths[arm]))
        report["gates"] = evaluate_reads(report["observations"], protocol["expected_snapshots"])
        report["gates"].update({
            "writer:wal": baseline["journal_mode"] == protocol["journal_mode"],
            "writer:full_sync": baseline["synchronous"] == protocol["synchronous"],
            "writer:no_autocheckpoint": baseline["wal_autocheckpoint"] == 0,
            "writer:baseline_checkpoint_truncated": baseline["checkpoint"] == [0, 0, 0],
            "writer:baseline_literal": baseline["snapshot"] == protocol["expected_snapshots"]["generation0"],
            "writer:commit1_literal": committed["snapshot"] == protocol["expected_snapshots"]["generation1"],
            "writer:uncommitted_transaction_open": staged["in_transaction"] is True,
            "writer:staged2_literal": staged["snapshot"] == uncommitted_oracle(protocol),
            "writer:ack_pid_matches_direct_child": all(value["pid"] == writer.pid for value in (baseline, committed, staged)),
            "writer:alive_until_captures_completed": report["writer_alive_until_captures_completed"],
            "capture:main_unchanged_since_checkpoint": baseline["main_sha256"] == committed["main_sha256"] ==
                report["capture_barrier"]["main_sha256"] == file_hash(paths["main_file_copy"]),
            "capture:live_wal_present": report["capture_barrier"]["wal_bytes"] > 32,
            "capture:backup_source_literal": report["backup"]["source_before"] == protocol["expected_snapshots"]["generation1"],
            "capture:backup_done_status": bool(report["backup"]["progress"]) and report["backup"]["progress"][-1]["status"] == sqlite3.SQLITE_DONE,
            "writer:fail_stop86": report["writer_exit_code"] == 86,
        })
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
        event("suite_error", **report["error"])
    finally:
        if writer is not None:
            if writer.poll() is None:
                try:
                    writer.kill()
                except OSError as kill_error:
                    if writer.poll() is None:
                        report["cleanup_error"] = "writer kill failed: " + str(kill_error)
                event("cleanup_kill_requested", pid=writer.pid)
                try:
                    writer.wait(timeout=protocol["cleanup_timeout_seconds"])
                except subprocess.TimeoutExpired:
                    report["cleanup_error"] = "writer exit unobserved after kill deadline"
            if thread is not None:
                thread.join(timeout=1)
                if thread.is_alive():
                    report["cleanup_error"] = "writer stdout collector did not finish"
            (raw / "writer.jsonl").write_text("".join(writer_lines), encoding="utf-8", newline="\n")
            if writer.poll() is not None:
                (raw / "writer.stderr").write_text(writer.stderr.read(), encoding="utf-8", newline="\n")
            report["writer_final_exit_code"] = writer.poll()
            transcript = parse_writer_transcript(writer_lines)
            report["writer_transcript"] = transcript
            report["gates"]["writer:complete_ack_transcript"] = (
                not transcript["errors"] and [entry["event"] for entry in transcript["events"]] ==
                ["baseline_ready", "generation1_committed", "generation2_uncommitted", "fail_stop_requested"] and
                all(entry.get("pid") == writer.pid for entry in transcript["events"]))
        try:
            verify_implementation_freeze(worker_freeze, worker_protocol)
            report["gates"]["freeze:unchanged_at_completion"] = True
        except (ValueError, OSError):
            report["gates"]["freeze:unchanged_at_completion"] = False
        report["completed_at"] = utc_now()
        report["wall_seconds"] = time.perf_counter() - start
        report["passed"] = (report["error"] is None and bool(report["gates"]) and
                            all(report["gates"].values()) and not report.get("cleanup_error"))
        event("suite_completed", passed=report["passed"])
        report["artifacts"] = {str(p.relative_to(output)).replace("\\", "/"):
                               {"bytes": p.stat().st_size, "sha256": file_hash(p)}
                               for p in sorted(output.rglob("*")) if p.is_file()}
        report["result_sha256"] = digest(report)
        child_path(output, "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                     encoding="utf-8", newline="\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/sqlite-snapshot-canary"))
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--freeze", type=Path)
    workers = parser.add_mutually_exclusive_group()
    workers.add_argument("--writer", type=Path, help=argparse.SUPPRESS)
    workers.add_argument("--reader", type=Path, help=argparse.SUPPRESS)
    workers.add_argument("--backup", type=Path, nargs=2, help=argparse.SUPPRESS)
    args = parser.parse_args()
    verify_implementation_freeze(args.freeze, args.protocol)
    protocol = read_protocol(args.protocol)
    if args.writer is not None:
        writer_worker(args.writer, protocol)
    elif args.reader is not None:
        reader_worker(args.reader)
    elif args.backup is not None:
        backup_worker(*args.backup)
    else:
        result = run_probe(args.output, args.protocol, freeze_path=args.freeze)
        print(f"SQLite snapshot canary passed={result['passed']}; SHA256 {result['result_sha256']}")
        return 0 if result["passed"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
