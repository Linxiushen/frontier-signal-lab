"""Separate local SQLite effect endpoint; trusted fixture authority, no model/API.

Only the finite controller may expose this service, on loopback with an ephemeral
port. This is an opt-in engineering fixture, not tenant authentication or a
general external exactly-once service.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import unquote


def identity(value):
    assert set(value) == {'key', 'payload', 'version', 'conversation', 'scope', 'fingerprint'}
    assert all(type(value[k]) is str for k in ('key', 'payload', 'scope', 'fingerprint'))
    assert type(value['conversation']) is str or type(value['conversation']) is int and 0 < value['conversation'] <= 2 ** 53 - 1
    assert 1 <= len(value['scope']) <= 64 and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in value['scope'])
    assert type(value['version']) is int and abs(value['version']) <= 2 ** 53 - 1
    assert value['key'].startswith(str(value['conversation']) + ':')
    assert value['fingerprint'] == hashlib.sha256(value['payload'].encode()).hexdigest()
    return value


class EffectStore:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS authority(scope TEXT NOT NULL, conversation NOT NULL, version INTEGER NOT NULL, allowed INTEGER NOT NULL, PRIMARY KEY(scope,conversation));
              CREATE TABLE IF NOT EXISTS effects(key TEXT PRIMARY KEY, identity TEXT NOT NULL, count INTEGER NOT NULL CHECK(count=1));
              CREATE TABLE IF NOT EXISTS attempts(seq INTEGER PRIMARY KEY, method TEXT NOT NULL, key TEXT NOT NULL, status INTEGER NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=0.1)
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def authorize(self, conversation, version, allowed, scope='default'):
        assert type(conversation) is str or type(conversation) is int and 0 < conversation <= 2 ** 53 - 1
        assert type(scope) is str and 1 <= len(scope) <= 64 and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in scope)
        assert type(version) is int and type(allowed) is bool
        with self.lock, self.connect() as db:
            db.execute('INSERT OR REPLACE INTO authority VALUES(?,?,?,?)', (scope, conversation, version, int(allowed)))

    def effect(self, method, key, value=None):
        if method == 'POST':
            identity(value)
            assert value['key'] == key
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT identity,count FROM effects WHERE key=?', (key,)).fetchone()
            if row:
                receipt = {**json.loads(row[0]), 'count': row[1]}
                status = 409 if method == 'POST' and json.loads(row[0]) != value else 200
                result = {'error': 'identity-conflict'} if status == 409 else receipt
            elif method == 'GET':
                status, result = 404, {'error': 'missing'}
            else:
                authority = db.execute('SELECT version,allowed FROM authority WHERE scope=? AND conversation=?', (value['scope'], value['conversation'])).fetchone()
                if authority != (value['version'], 1):
                    status, result = 403, {'error': 'current-authority-denied'}
                else:
                    db.execute('INSERT INTO effects VALUES(?,?,1)', (key, json.dumps(value, sort_keys=True)))
                    status, result = 201, {**value, 'count': 1}
            db.execute('INSERT INTO attempts(method,key,status) VALUES(?,?,?)', (method, key, status))
            return status, result

    def snapshot(self):
        with self.lock, self.connect() as db:
            assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            return {'authority': [list(r) for r in db.execute('SELECT * FROM authority ORDER BY scope,conversation')],
                    'effects': [{**json.loads(r[1]), 'count': r[2]} for r in db.execute('SELECT * FROM effects ORDER BY key')],
                    'attempts': [list(r) for r in db.execute('SELECT * FROM attempts ORDER BY seq')]}


def serve(directory, stage):
    directory = Path(directory)
    store = EffectStore(directory / 'effects.sqlite')
    held = set()
    log_lock = threading.Lock()
    log = (directory / f'effect-server{stage}.jsonl').open('x', encoding='utf-8')
    def emit(value):
        with log_lock:
            log.write(json.dumps({'pid': __import__('os').getpid(), 'stage': stage, 'epoch_ms': time.time_ns() // 1000000,
                                  'monotonic_ns': time.monotonic_ns(), **value}) + '\n')
            log.flush()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.handle_request('GET')

        def do_POST(self):
            self.handle_request('POST')

        def handle_request(self, method):
            self.connection.settimeout(2)
            status, body = 400, {'error': 'invalid-request'}
            try:
                assert self.headers.get('x-frontier-fixture') == 'local-fixture-v1'
                assert self.headers.get('transfer-encoding') is None
                length = int(self.headers.get('content-length', '0'))
                assert 0 <= length <= 4096
                value = json.loads(self.rfile.read(length)) if length else None
                if self.path == '/snapshot' and method == 'GET':
                    status, body = 200, store.snapshot()
                elif self.path == '/authority' and method == 'POST':
                    assert set(value) == {'scope', 'conversation', 'version', 'allowed'}
                    store.authorize(**value)
                    status, body = 200, {'ok': True}
                elif self.path == '/hold' and method == 'POST':
                    assert set(value) == {'key'} and type(value['key']) is str
                    held.add(value['key']); status, body = 200, {'ok': True}
                elif self.path == '/stop' and method == 'POST':
                    status, body = 200, {'ok': True}
                    threading.Thread(target=server.shutdown, daemon=True).start()
                elif self.path.startswith('/effects/') and '?' not in self.path:
                    key = unquote(self.path[len('/effects/'):])
                    # Keep the saved observation in the same order as committed attempts.
                    # Release this lock before waiting on an intentionally withheld reply.
                    with store.lock:
                        status, body = store.effect(method, key, value)
                        emit({'type': 'effect-request', 'method': method, 'key': key, 'status': status})
                    if method == 'POST' and status == 201 and key in held:
                        emit({'type': 'reply-held-after-commit', 'key': key})
                        # Bound fixture reply withholding; controller stops this server after worker exit.
                        server.stopping.wait(8)
                else:
                    raise AssertionError('Unsupported endpoint')
            except (AssertionError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                emit({'type': 'request-rejected', 'error': type(error).__name__})
            raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers(); self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, OSError):
                emit({'type': 'reply-client-disconnected', 'status': status})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = False
    server.stopping = threading.Event()
    ready = {'pid': __import__('os').getpid(), 'stage': stage, 'base': f'http://127.0.0.1:{server.server_port}/',
             'started_at': datetime.now(timezone.utc).isoformat()}
    ready_path = directory / f'effect-server{stage}-ready.json'
    ready_temporary = ready_path.with_suffix('.tmp')
    ready_temporary.write_text(json.dumps(ready), encoding='utf-8')
    os.replace(ready_temporary, ready_path)
    emit({'type': 'server-ready', **ready})
    try:
        server.serve_forever(poll_interval=0.02)
    finally:
        server.stopping.set(); server.server_close()
        (directory / f'effect-server{stage}-final.json').write_text(json.dumps(store.snapshot(), indent=2), encoding='utf-8')
        emit({'type': 'server-closed'}); log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', type=int, choices=range(3), required=True)
    args = parser.parse_args()
    serve(args.output, args.stage)
