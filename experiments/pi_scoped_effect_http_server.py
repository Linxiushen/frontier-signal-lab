"""Opt-in v2 loopback fixture with effect resources keyed by (scope, key).

The original frozen server/database remain unchanged. No legacy migration or
tenant authentication is provided. Scope is a trusted host namespace.
"""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import unquote

if __package__:
    from .pi_effect_http_server import EffectStore, identity
else:
    from pi_effect_http_server import EffectStore, identity


def scope_name(value):
    assert type(value) is str and 1 <= len(value) <= 64
    assert all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in value)
    return value


class ScopedEffectStore(EffectStore):
    def __init__(self, path):
        self.path, self.lock = str(path), threading.RLock()
        with self.connect() as db:
            columns = db.execute('PRAGMA table_info(effects)').fetchall()
            if columns and [(r[1], r[5]) for r in columns] != [('scope', 1), ('key', 2), ('identity', 0), ('count', 0)]:
                raise ValueError('Requires scoped effect schema v2; legacy migration is not supported')
            assert db.execute('PRAGMA user_version').fetchone()[0] in (0, 2)
            db.executescript('''PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS authority(scope TEXT NOT NULL, conversation NOT NULL, version INTEGER NOT NULL, allowed INTEGER NOT NULL, PRIMARY KEY(scope,conversation));
              CREATE TABLE IF NOT EXISTS effects(scope TEXT NOT NULL, key TEXT NOT NULL, identity TEXT NOT NULL, count INTEGER NOT NULL CHECK(count=1), PRIMARY KEY(scope,key));
              CREATE TABLE IF NOT EXISTS attempts(seq INTEGER PRIMARY KEY, method TEXT NOT NULL, scope TEXT NOT NULL, key TEXT NOT NULL, status INTEGER NOT NULL);
              PRAGMA user_version=2;
            ''')

    def effect(self, method, scope, key, value=None):
        assert method in ('GET', 'POST')
        scope_name(scope)
        assert type(key) is str
        if method == 'POST':
            identity(value)
            assert value['scope'] == scope and value['key'] == key
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT identity,count FROM effects WHERE scope=? AND key=?', (scope, key)).fetchone()
            if row:
                original = json.loads(row[0])
                status = 409 if method == 'POST' and original != value else 200
                result = {'error': 'identity-conflict'} if status == 409 else {**original, 'count': row[1]}
            elif method == 'GET':
                status, result = 404, {'error': 'missing'}
            else:
                authority = db.execute('SELECT version,allowed FROM authority WHERE scope=? AND conversation=?', (scope, value['conversation'])).fetchone()
                if authority != (value['version'], 1):
                    status, result = 403, {'error': 'current-authority-denied'}
                else:
                    db.execute('INSERT INTO effects VALUES(?,?,?,1)', (scope, key, json.dumps(value, sort_keys=True)))
                    status, result = 201, {**value, 'count': 1}
            db.execute('INSERT INTO attempts(method,scope,key,status) VALUES(?,?,?,?)', (method, scope, key, status))
            return status, result

    def snapshot(self):
        with self.lock, self.connect() as db:
            assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            return {'authority': [list(r) for r in db.execute('SELECT * FROM authority ORDER BY scope,conversation')],
                    'effects': [{**json.loads(r[0]), 'count': r[1]} for r in db.execute('SELECT identity,count FROM effects ORDER BY scope,key')],
                    'attempts': [list(r) for r in db.execute('SELECT * FROM attempts ORDER BY seq')]}


def serve(directory, stage):
    directory = Path(directory)
    store = ScopedEffectStore(directory / 'effects-scoped.sqlite')
    held, log_lock = set(), threading.Lock()
    log = (directory / f'effect-server{stage}.jsonl').open('x', encoding='utf-8')

    def emit(value):
        with log_lock:
            log.write(json.dumps({'pid': os.getpid(), 'stage': stage, 'epoch_ms': time.time_ns() // 1000000,
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
                assert self.headers.get('x-frontier-fixture') == 'local-fixture-v2-scoped'
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
                    assert set(value) == {'scope', 'key'} and type(value['key']) is str
                    held.add((scope_name(value['scope']), value['key']))
                    status, body = 200, {'ok': True}
                elif self.path == '/stop' and method == 'POST':
                    status, body = 200, {'ok': True}
                    threading.Thread(target=server.shutdown, daemon=True).start()
                elif self.path.startswith('/effects/') and '?' not in self.path:
                    parts = self.path[len('/effects/'):].split('/')
                    assert len(parts) == 2 and all(parts)
                    scope, key = scope_name(unquote(parts[0])), unquote(parts[1])
                    with store.lock:
                        status, body = store.effect(method, scope, key, value)
                        emit({'type': 'effect-request', 'method': method, 'scope': scope, 'key': key, 'status': status})
                    if method == 'POST' and status == 201 and (scope, key) in held:
                        emit({'type': 'reply-held-after-commit', 'scope': scope, 'key': key})
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
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, OSError):
                emit({'type': 'reply-client-disconnected', 'status': status})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = False
    server.stopping = threading.Event()
    ready = {'pid': os.getpid(), 'stage': stage, 'base': f'http://127.0.0.1:{server.server_port}/',
             'started_at': datetime.now(timezone.utc).isoformat(), 'protocol': 'scoped-v2'}
    ready_path = directory / f'effect-server{stage}-ready.json'
    temporary = ready_path.with_suffix('.tmp')
    temporary.write_text(json.dumps(ready), encoding='utf-8')
    os.replace(temporary, ready_path)
    emit({'type': 'server-ready', **ready})
    try:
        server.serve_forever(poll_interval=0.02)
    finally:
        server.stopping.set()
        server.server_close()
        (directory / f'effect-server{stage}-final.json').write_text(json.dumps(store.snapshot(), indent=2), encoding='utf-8')
        emit({'type': 'server-closed'})
        log.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', type=int, choices=range(3), required=True)
    args = parser.parse_args()
    serve(args.output, args.stage)
