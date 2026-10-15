"""Independent SQLite legacy-binding migration and fail-stop recovery diagnostic.

Uses a generic local schema, not OpenClaw code or a reproduction of its behavior.
Two error-reporting policies preserve original rows. Progress and diagnostic gaps
are measured from reopened databases, not inferred from policy labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


POLICIES = ("silent_skip", "warn_preserve")
CRASHPOINTS = ("none", "after_row_write", "after_diagnostic_step", "before_commit", "after_commit")
CRASH_EXIT = 86
TABLES = ("legacy_bindings", "obligations", "bindings", "warnings", "migration_state")
SOURCE = "https://github.com/openclaw/openclaw/pull/173018#discussion_r4282004743"
# Ground truth belongs to the fixed fixture specification, not to the decoder.
EXPECTED_INVALID_IDS = frozenset(("02-missing", "03-truncated", "04-version"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def connect(path):
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def fixtures():
    """All six obligations are accepted; none has executed a business result."""
    base = {"version": 1, "state": "active", "requester_evidence": "confirmed",
            "delivery_evidence": "retryable"}
    def payload(task, **changes):
        return canonical(dict(base, assignment_id=task, **changes))
    return [
        ("01-valid", "task-valid", payload("task-valid")),
        ("02-missing", "task-missing", canonical(base)),
        ("03-truncated", "task-truncated", '{"version":1,"assignment_id":'),
        ("04-version", "task-version", payload("task-version", version=99)),
        ("05-unknown", "task-unknown", payload("task-unknown", requester_evidence="unknown")),
        ("06-terminal", "task-terminal", payload("task-terminal", delivery_evidence="terminal")),
    ]


def initialize(path):
    connection = connect(path)
    try:
        connection.executescript("""
        CREATE TABLE legacy_bindings(binding_id TEXT PRIMARY KEY, value_json TEXT NOT NULL);
        CREATE TABLE obligations(task_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('accepted','runnable','blocked','done')),
          reason TEXT, FOREIGN KEY(binding_id) REFERENCES legacy_bindings(binding_id));
        CREATE TABLE bindings(binding_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL UNIQUE,
          state TEXT NOT NULL CHECK(state IN ('active','retired')), payload_json TEXT NOT NULL,
          FOREIGN KEY(binding_id) REFERENCES legacy_bindings(binding_id));
        CREATE TABLE warnings(binding_id TEXT PRIMARY KEY, code TEXT NOT NULL,
          original_sha256 TEXT NOT NULL, FOREIGN KEY(binding_id) REFERENCES legacy_bindings(binding_id));
        CREATE TABLE migration_state(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL,
          diagnostic_status TEXT NOT NULL, policy TEXT);
        INSERT INTO migration_state VALUES(1,0,'not_run',NULL);
        """)
        connection.execute("BEGIN IMMEDIATE")
        for binding_id, task_id, raw in fixtures():
            connection.execute("INSERT INTO legacy_bindings VALUES(?,?)", (binding_id, raw))
            connection.execute("INSERT INTO obligations VALUES(?,?,'accepted',NULL)", (task_id, binding_id))
        connection.commit()
    finally:
        connection.close()


def decode(raw, expected_task):
    """Return a typed generic record, or a stable diagnostic code."""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, "invalid_json"
    if not isinstance(value, dict):
        return None, "not_an_object"
    if type(value.get("version")) is not int or value["version"] != 1:
        return None, "unsupported_version"
    if not isinstance(value.get("assignment_id"), str) or not value["assignment_id"]:
        return None, "missing_assignment_id"
    if value["assignment_id"] != expected_task:
        return None, "assignment_mismatch"
    if value.get("state") not in ("active", "retired"):
        return None, "invalid_state"
    if value.get("requester_evidence") not in ("confirmed", "unknown"):
        return None, "invalid_requester_evidence"
    if value.get("delivery_evidence") not in ("retryable", "terminal"):
        return None, "invalid_delivery_evidence"
    return value, None


def checkpoint(name, crashpoint):
    if name == crashpoint:
        # No finally/close/rollback: test SQLite recovery after process fail-stop.
        os._exit(CRASH_EXIT)


def migrate(path, policy, crashpoint="none"):
    if policy not in POLICIES or crashpoint not in CRASHPOINTS:
        raise ValueError("unknown policy or crashpoint")
    connection = connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("SELECT l.binding_id,l.value_json,o.task_id FROM legacy_bindings l "
                                  "JOIN obligations o USING(binding_id) ORDER BY l.binding_id").fetchall()
        diagnostic_checkpoint_done = False
        row_checkpoint_done = False
        for binding_id, raw, task_id in rows:
            value, error = decode(raw, task_id)
            if error:
                if policy == "warn_preserve":
                    connection.execute("INSERT OR REPLACE INTO warnings VALUES(?,?,?)",
                                       (binding_id, error, hashlib.sha256(raw.encode("utf-8")).hexdigest()))
                    connection.execute("UPDATE obligations SET state='blocked',reason=? WHERE task_id=? AND state!='done'",
                                       (error, task_id))
                # silent_skip leaves both the original row and accepted obligation intact.
                if not diagnostic_checkpoint_done:
                    checkpoint("after_diagnostic_step", crashpoint)
                    diagnostic_checkpoint_done = True
                continue
            unknown = value["requester_evidence"] == "unknown"
            terminal = value["delivery_evidence"] == "terminal"
            retired = value["state"] == "retired" or (terminal and not unknown)
            state = "retired" if retired else "active"
            connection.execute("INSERT OR REPLACE INTO bindings VALUES(?,?,?,?)",
                               (binding_id, task_id, state, canonical(value)))
            reason = "unknown_requester_evidence" if unknown else ("terminal_binding" if retired else None)
            connection.execute("UPDATE obligations SET state=?,reason=? WHERE task_id=? AND state!='done'",
                               ("blocked" if reason else "runnable", reason, task_id))
            if not row_checkpoint_done:
                checkpoint("after_row_write", crashpoint)
                row_checkpoint_done = True
        issues = connection.execute("SELECT COUNT(*) FROM warnings").fetchone()[0]
        connection.execute("UPDATE migration_state SET version=1,diagnostic_status=?,policy=? WHERE id=1",
                           ("needs_attention" if issues else "clean", policy))
        checkpoint("before_commit", crashpoint)
        connection.commit()
        checkpoint("after_commit", crashpoint)
    finally:
        connection.close()


def snapshot(path):
    """Read actual durable rows after closing/reopening, excluding runtime paths."""
    connection = connect(path)
    try:
        result = {}
        for table in TABLES:
            cursor = connection.execute(f"SELECT * FROM {table} ORDER BY 1")
            columns = [column[0] for column in cursor.description]
            result[table] = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return result
    finally:
        connection.close()


def sql_snapshot(path):
    connection = connect(path)
    try:
        return "\n".join(connection.iterdump()) + "\n"
    finally:
        connection.close()


def measure(disk):
    """Metrics use rows and independent fixture obligations, never policy names."""
    originals = {row[0]: row[2] for row in fixtures()}
    observed = {row["binding_id"]: row["value_json"] for row in disk["legacy_bindings"]}
    obligations = disk["obligations"]
    states = {state: sum(row["state"] == state for row in obligations)
              for state in ("accepted", "runnable", "blocked", "done")}
    invalid = EXPECTED_INVALID_IDS.intersection(observed)
    warning_ids = {row["binding_id"] for row in disk["warnings"]}
    state = disk["migration_state"][0]
    binding_states = {row["binding_id"]: row["state"] for row in disk["bindings"]}
    # Independent fixture truth: 05-unknown starts active with unknown evidence.
    unknown_retired = int(binding_states.get("05-unknown") == "retired")
    return {
        "accepted_obligations_total": len(fixtures()),
        "visible_obligations": len(obligations),
        "missing_obligations": len({row[1] for row in fixtures()} - {row["task_id"] for row in obligations}),
        **{("accepted_obligations_current" if key == "accepted" else f"{key}_obligations"): value
           for key, value in states.items()},
        "unresolved_obligations": len(obligations) - states["done"],
        "invalid_binding_rows": len(invalid),
        "invalid_rows_without_warning": len(set(invalid) - warning_ids),
        "invalid_rows_accepted_into_bindings": len(invalid.intersection(binding_states)),
        "false_clean": bool(invalid and state["diagnostic_status"] == "clean"),
        "original_rows_preserved": observed == originals,
        "original_rows_sha256": digest(sorted(observed.items())),
        "unknown_evidence_newly_retired": unknown_retired,
        "diagnostic_status": state["diagnostic_status"],
        "schema_version": state["version"],
    }


def worker(path, policy, crashpoint):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--db", str(path),
                             "--policy", policy, "--crashpoint", crashpoint],
                            capture_output=True, text=True, timeout=20)
    expected = 0 if crashpoint == "none" else CRASH_EXIT
    if result.returncode != expected:
        raise RuntimeError(f"worker exit {result.returncode}, expected {expected}: {result.stderr[:500]}")
    return result.returncode


def run_probe(policies=POLICIES, crashpoints=CRASHPOINTS):
    if not policies or any(p not in POLICIES for p in policies):
        raise ValueError("provide known policies")
    if not crashpoints or any(c not in CRASHPOINTS for c in crashpoints):
        raise ValueError("provide known crashpoints")
    runs = []
    for policy in policies:
        for crashpoint in crashpoints:
            with tempfile.TemporaryDirectory(prefix="sqlite-migration-probe-") as directory:
                path = Path(directory) / "adapter.sqlite3"
                initialize(path)
                before = snapshot(path)
                exit_code = worker(path, policy, crashpoint)
                after_fault = snapshot(path)
                sql_fault = sql_snapshot(path)
                worker(path, policy, "none")  # Fresh interpreter and fresh DB connection.
                recovered = snapshot(path)
                sql_recovered = sql_snapshot(path)
                migrate(path, policy)
                replayed = snapshot(path)
                expected_committed = crashpoint in ("none", "after_commit")
                atomic = after_fault == (recovered if expected_committed else before)
                runs.append({
                    "policy": policy, "crashpoint": crashpoint, "worker_exit_code": exit_code,
                    "transaction_atomic": atomic, "replay_idempotent": replayed == recovered,
                    "metrics": measure(recovered),
                    "snapshots": {"before": before, "after_fault": after_fault,
                                  "after_recovery": recovered, "after_replay": replayed},
                    "snapshot_sha256": {"before": digest(before), "after_fault": digest(after_fault),
                                        "after_recovery": digest(recovered), "after_replay": digest(replayed)},
                    "sql_snapshots": {"after_fault": sql_fault, "after_recovery": sql_recovered},
                })
    report = {
        "schema_version": 1,
        "experiment": "independent generic SQLite legacy-binding migration and recovery",
        "config": {"randomness": "none", "policies": list(policies), "crashpoints": list(crashpoints),
                   "fixture_rows": len(fixtures()), "child_processes_per_trace": 2,
                   "journal_mode": "WAL", "synchronous": "FULL", "transaction": "BEGIN IMMEDIATE"},
        "public_inspiration": {"url": SOURCE,
                               "role": "Public review and subsequent warning fix motivate an independent diagnostic; no current upstream defect is asserted and no upstream code is executed."},
        "limitations": [
            "Generic fixture and schema, not an OpenClaw reproduction, migration compatibility test, or confirmed deployed defect.",
            "A subsequent upstream revision added malformed-binding warnings; this historical silent/warn comparison does not assert that the current upstream proposal remains silent.",
            "Both policies retain every original value_json row; silent_skip can report clean despite undecodable rows. It does not delete assignments.",
            "warn_preserve makes unresolved obligations explicit; retaining or blocking a task is not business completion or automatic data repair.",
            "No task executes a business result, so done_obligations must remain zero. Runnable is eligibility, not evidence of eventual completion.",
            "Unknown requester evidence never authorizes newly retiring an active binding. Existing retired state is preserved; only explicit terminal evidence with confirmed requester creates a retirement in this fixture.",
            "Malformed-row ground truth is the fixed fixture specification, independent of decode(). Original-row hashes cover SQLite TEXT values re-encoded as UTF-8, not original database-file bytes.",
            "Replay idempotence means logical rows remain equal, not zero writes; INSERT OR REPLACE may rewrite physical storage. Re-migration preserves independently completed obligations.",
            "Hard process exits exercise local SQLite transaction rollback and restart; they do not simulate power loss, disk corruption, network partitions, concurrent writers, or torn storage writes.",
            "No external side effect or exactly-once delivery is tested. No compaction or stale-turn scheduler is implemented.",
            "The finite selected checkpoints and fixtures establish neither production reliability nor general liveness. SQL snapshots are logical database dumps, not physical disk forensic images.",
        ],
        "runs": runs,
    }
    report["result_sha256"] = digest(report)
    return report


def render_markdown(report):
    lines = ["# SQLite migration recovery probe", "",
             "Independent generic schema with real SQLite transactions and subprocess fail-stop exits. No upstream implementation is reproduced.", "",
             "Both policies preserve the raw legacy rows. False-clean diagnostics and unresolved obligations are measured separately from data loss.", "",
             "| Policy | Crash point | Atomic | Replay idempotent | Raw preserved | False clean | Accepted total | Still accepted | Runnable | Blocked | Done |",
             "|---|---|---|---|---|---|---:|---:|---:|---:|---:|"]
    for row in report["runs"]:
        m = row["metrics"]
        lines.append(f"| {row['policy']} | {row['crashpoint']} | {row['transaction_atomic']} | "
                     f"{row['replay_idempotent']} | {m['original_rows_preserved']} | {m['false_clean']} | "
                     f"{m['accepted_obligations_total']} | {m['accepted_obligations_current']} | "
                     f"{m['runnable_obligations']} | {m['blocked_obligations']} | {m['done_obligations']} |")
    lines.extend(["", "`Accepted total` is the fixed admission obligation count; `Still accepted` means no runnable/blocked/done classification. Blocking is not success. None of these tasks executes a business result.", "",
                  "Each trace includes actual reopened rows, logical SQL dumps, transaction/replay checks and snapshot hashes. Counterexamples include false-clean diagnostics as negative results.", "",
                  f"Result SHA256 (canonical JSON excluding result_sha256): `{report['result_sha256']}`", "",
                  "## Limits", ""])
    lines.extend("- " + item for item in report["limitations"])
    lines.extend(["", "Public inspiration: " + SOURCE, ""])
    return "\n".join(lines)


def write_report(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "probe.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8", newline="\n")
    (output / "report.md").write_text(render_markdown(report), encoding="utf-8", newline="\n")
    sql_dir = output / "sql"
    counterexamples = output / "counterexamples"
    sql_dir.mkdir(exist_ok=True)
    counterexamples.mkdir(exist_ok=True)
    for row in report["runs"]:
        stem = row["policy"] + "--" + row["crashpoint"]
        for phase, sql in row["sql_snapshots"].items():
            (sql_dir / f"{stem}--{phase}.sql").write_text(sql, encoding="utf-8", newline="\n")
        metrics = row["metrics"]
        if (metrics["false_clean"] or not metrics["original_rows_preserved"]
                or metrics["missing_obligations"] or metrics["invalid_rows_accepted_into_bindings"]
                or metrics["unknown_evidence_newly_retired"]
                or not row["transaction_atomic"] or not row["replay_idempotent"]):
            (counterexamples / f"{stem}.json").write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n",
                                                         encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/sqlite-migration"))
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--db", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--policy", choices=POLICIES, default=POLICIES[0], help=argparse.SUPPRESS)
    parser.add_argument("--crashpoint", choices=CRASHPOINTS, default="none", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.db is None or not args.db.is_file():
            parser.error("worker requires an existing --db file")
        migrate(args.db, args.policy, args.crashpoint)
    else:
        report = run_probe()
        write_report(report, args.output)
        print(f"Wrote {len(report['runs'])} traces to {args.output}; SHA256 {report['result_sha256']}")


if __name__ == "__main__":
    main()
