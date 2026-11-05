"""Durable physical HTTP admission for a single trusted evaluation fixture.

Every complete body submitted to receive spends a slot, including invalid, failed
and duplicate calls. Framing and body-read failures before receive are outside
this admission API and can be unrecorded by the fixture handler.
This caps provider admissions, not inbound traffic or general service resources.
The caller must stop exhausted native work; this is not tenant authentication.
"""
from pathlib import Path
from contextlib import closing
import sqlite3


class HttpBudget:
    def __init__(self, path: Path, identity: str, total: int, per_attempt: int):
        if total < 1 or per_attempt < 1:
            raise ValueError("positive physical limits required")
        self.path, self.identity = path, identity
        self.total, self.per_attempt = total, per_attempt
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=DELETE")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS arrivals(
                    seq INTEGER PRIMARY KEY, attempt TEXT NOT NULL, body_hash TEXT NOT NULL,
                    admitted INTEGER NOT NULL, reason TEXT NOT NULL, attempt_ordinal INTEGER NOT NULL,
                    response_status INTEGER, write_completed INTEGER NOT NULL DEFAULT 0);
            """)
            expected = {"identity": identity, "total": str(total), "per_attempt": str(per_attempt)}
            existing = dict(db.execute("SELECT key,value FROM metadata"))
            if existing and existing != expected:
                raise ValueError("HTTP budget identity or limits changed")
            db.executemany("INSERT OR IGNORE INTO metadata VALUES (?,?)", expected.items())

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def receive(self, attempt: str, body_hash: str) -> dict:
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            seq = db.execute("SELECT count(*)+1 FROM arrivals").fetchone()[0]
            previous = db.execute("SELECT body_hash FROM arrivals WHERE attempt=? ORDER BY seq", (attempt,)).fetchall()
            ordinal = len(previous) + 1
            reason = ("total_exhausted" if seq > self.total else
                      "attempt_exhausted" if ordinal > self.per_attempt else
                      "content_conflict" if any(row[0] != body_hash for row in previous) else "admitted")
            db.execute("INSERT INTO arrivals(seq,attempt,body_hash,admitted,reason,attempt_ordinal) VALUES (?,?,?,?,?,?)",
                       (seq, attempt, body_hash, int(reason == "admitted"), reason, ordinal))
            db.commit()
            return {"seq": seq, "attempt_ordinal": ordinal, "admitted": reason == "admitted", "reason": reason}
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def response(self, seq: int, status: int, written: bool) -> None:
        with closing(self.connect()) as db, db:
            n = db.execute("UPDATE arrivals SET response_status=?,write_completed=? WHERE seq=?",
                           (status, int(written), seq)).rowcount
            if n != 1:
                raise ValueError("unknown physical arrival")

    def snapshot(self) -> dict:
        db = self.connect()
        try:
            db.row_factory = sqlite3.Row
            return {"metadata": dict(db.execute("SELECT key,value FROM metadata")),
                    "arrivals": [dict(row) for row in db.execute("SELECT * FROM arrivals ORDER BY seq")]}
        finally:
            db.close()
