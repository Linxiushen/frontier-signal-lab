"""Fail-closed evaluation reservations for a single trusted resumable caller.

Reserve the episode AND its scoring allowance before entering a native runner.
An uncertain reservation is burned on recovery, never automatically replayed.
This trades availability for an at-most-entry budget; it is not external exactly-once
execution, a sandbox, or protection against a caller that bypasses this interface.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def verify_files(versions: dict[str, str]) -> None:
    """Hash the actual evaluator/runner bytes before any reservation or native call."""
    for filename, expected in versions.items():
        if digest(Path(filename).read_bytes()) != expected:
            raise ValueError(f"version mismatch: {filename}")


class BudgetLedger:
    def __init__(self, path: Path, identity: str, development_limit: int):
        if development_limit < 1:
            raise ValueError("positive development limit required")
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self._initialize(identity, development_limit)
        except BaseException:
            self.db.close()
            raise
        self.limit = development_limit

    def _initialize(self, identity: str, development_limit: int) -> None:
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(
                key TEXT PRIMARY KEY, phase TEXT NOT NULL, model TEXT NOT NULL,
                data_hash TEXT NOT NULL, status TEXT NOT NULL,
                reward REAL, receipt TEXT);
        """)
        with self.transaction():
            existing = dict(self.db.execute("SELECT key,value FROM metadata"))
            expected = {"identity": identity, "development_limit": str(development_limit)}
            if existing and any(existing.get(k) != v for k, v in expected.items()):
                raise ValueError("ledger identity or budget changed")
            for k, v in expected.items():
                self.db.execute("INSERT OR IGNORE INTO metadata VALUES (?,?)", (k, v))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def winner(self) -> str | None:
        row = self.db.execute("SELECT value FROM metadata WHERE key='winner'").fetchone()
        return row[0] if row else None

    def reserve(self, key: str, phase: str, model: str, data_hash: str) -> bool:
        """True grants exactly one entry; False is an existing, non-replayable attempt."""
        if phase not in {"development", "final"}:
            raise ValueError("unknown phase")
        with self.transaction():
            old = self.db.execute("SELECT * FROM attempts WHERE key=?", (key,)).fetchone()
            if old:
                if (old["phase"], old["model"], old["data_hash"]) != (phase, model, data_hash):
                    raise ValueError("attempt identity reused with different content")
                return False
            count = self.db.execute("SELECT count(*) FROM attempts WHERE phase=?", (phase,)).fetchone()[0]
            winner = self.winner()
            if phase == "development":
                if winner is not None or count >= self.limit:
                    raise ValueError("development closed or budget exhausted")
            elif winner != model or count >= 1:
                raise ValueError("final requires sealed winner and unused final allowance")
            self.db.execute("INSERT INTO attempts VALUES (?,?,?,?, 'reserved',NULL,NULL)", (key, phase, model, data_hash))
            return True

    def recover(self) -> int:
        """Only call after proving the previous owner is stopped; uncertain work burns."""
        with self.transaction():
            return self.db.execute("UPDATE attempts SET status='burned' WHERE status='reserved'").rowcount

    def complete(self, key: str, reward: float, receipt: dict) -> None:
        if not math.isfinite(reward):
            raise ValueError("nonfinite reward")
        encoded = canonical(receipt)
        with self.transaction():
            n = self.db.execute("UPDATE attempts SET status='completed', reward=?, receipt=? WHERE key=? AND status='reserved'", (reward, encoded, key)).rowcount
            if n != 1:
                raise ValueError("completion needs an owned reservation")

    def seal_winner(self) -> str:
        with self.transaction():
            old = self.winner()
            if old is not None:
                return old
            if self.db.execute("SELECT count(*) FROM attempts WHERE status='reserved'").fetchone()[0]:
                raise ValueError("recover uncertain attempts before selection")
            rows = self.db.execute("SELECT model FROM attempts WHERE phase='development' AND status='completed' ORDER BY reward DESC, key ASC").fetchall()
            if not rows:
                raise ValueError("no completed development evaluation")
            winner = rows[0][0]
            self.db.execute("INSERT INTO metadata VALUES ('winner',?)", (winner,))
            return winner

    def snapshot(self) -> dict:
        return {"metadata": dict(self.db.execute("SELECT key,value FROM metadata")),
                "attempts": [dict(r) for r in self.db.execute("SELECT * FROM attempts ORDER BY rowid")]}

    def close(self) -> None:
        self.db.close()
