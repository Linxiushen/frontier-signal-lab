"""Prepared v3 controller; requires its own future freeze, never retries v2."""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def now():
    return datetime.now(timezone.utc).isoformat()
def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))
def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

class ProcessMemory(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
        *[(key, ctypes.c_size_t) for key in ('PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage',
        'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]]

def memory(process):
    counters = ProcessMemory(); counters.cb = ctypes.sizeof(counters)
    method = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
    method.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemory), wintypes.DWORD]
    method.restype = wintypes.BOOL
    if not method(int(process._handle), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {key: int(getattr(counters, key)) for key in ('PeakWorkingSetSize', 'WorkingSetSize', 'PrivateUsage')}

def observed_output_bytes(output):
    # Atomic worker saves can rename a temporary path between listing and stat.
    # A vanished path no longer belongs to this current-directory observation.
    total = 0
    for path in output.iterdir():
        try:
            if path.is_file():
                total += path.stat().st_size
        except FileNotFoundError:
            continue
    return total

def read_service_document(database):
    # Native Pi SQLite address columns store JSON-serialized document kinds.
    document_ids = [row[0] for row in database.execute(
        'SELECT id FROM documents WHERE kind = ?',
        (json.dumps('frontier.service'),))]
    if len(document_ids) != 1:
        raise ValueError('Expected exactly one frontier.service document')
    revisions = database.execute(
        'SELECT seq, content FROM document_revisions WHERE document_id = ? '
        'ORDER BY seq', (document_ids[0],)).fetchall()
    if not revisions:
        raise ValueError('Missing frontier.service document revision')
    return json.loads(revisions[-1][1]), [row[0] for row in revisions]


def execute(freeze_path):
    frozen = load(freeze_path)
    # Check our own controller identity before reading protocol or starting work.
    own_path = Path(__file__).resolve()
    own_name = own_path.relative_to(ROOT).as_posix()
    assert frozen['source_sha256'].get(own_name) == sha(own_path), (
        'This controller requires its own exact source hash in a new freeze')
    protocol_path = ROOT / frozen['protocol_path']; protocol = load(protocol_path)
    assert datetime.fromisoformat(now()) > datetime.fromisoformat(frozen['frozen_at']) > datetime.fromisoformat(protocol['predeclared_at'])
    assert protocol['suites_permitted'] == 1 and protocol['retries'] == 0
    for name, expected in frozen['source_sha256'].items():
        assert sha(ROOT / name) == expected, name
    assert sha(protocol_path) == frozen['protocol_sha256']
    node = Path(frozen['node']); runtime = ROOT / frozen['runtime_directory']
    assert sha(node) == frozen['node_sha256']
    manifest = load(ROOT / frozen['runtime_manifest_path'])
    assert sha(ROOT / frozen['runtime_manifest_path']) == frozen['runtime_manifest_sha256']
    actual_paths = {p.relative_to(runtime).as_posix() for p in (runtime / 'node_modules').rglob('*') if p.is_file()}
    actual_paths.update(('package.json', 'package-lock.json'))
    assert actual_paths == {item['path'] for item in manifest['files']}, 'Runtime byte inventory changed'
    for item in manifest['files']:
        assert sha(runtime / item['path']) == item['sha256'], item['path']
    output = ROOT / frozen['output_directory']
    assert not output.exists(), 'An existing output is never retried'
    assert shutil.disk_usage(output.parent).free >= protocol['min_free_disk_bytes']
    output.mkdir()
    report = {'started_at': now(), 'status': 'running', 'processes': [], 'scientific_suites': 1,
              'pretrained_model_loads': 0, 'freeze_sha256': sha(freeze_path)}
    end = time.monotonic() + protocol['suite_wall_seconds']
    env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP') if key in os.environ}
    try:
        for stage in range(3):
            argv = [str(node), '--max-old-space-size=128', str(ROOT / 'scripts/pi_durable_recovery_worker_v2.mjs'),
                    str(runtime), str(output), str(stage)]
            start = time.monotonic()
            row = {'stage': stage, 'started_at': now(), 'argv': argv, 'memory_samples': [], 'forced_termination': False}
            report['processes'].append(row)
            with (output / f'stage{stage}.stdout.txt').open('wb') as stdout, (output / f'stage{stage}.stderr.txt').open('wb') as stderr:
                child = subprocess.Popen(argv, env=env, cwd=ROOT, stdout=stdout, stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                row['pid'] = child.pid
                try:
                    ready = output / f'stage{stage}-ready.json'
                    while not ready.exists():
                        if child.poll() is not None:
                            if ready.exists():
                                break
                            raise RuntimeError(f'Stage{stage} exited{child.returncode} before ready')
                        sample = memory(child); row['memory_samples'].append({'elapsed': time.monotonic() - start, **sample})
                        assert sample['PrivateUsage'] < protocol['polled_process_private_bytes_ceiling'], 'Private memory ceiling'
                        assert time.monotonic() < min(end, start + protocol['process_wall_seconds']), 'Wall deadline'
                        assert observed_output_bytes(output) < protocol['output_bytes_ceiling'], 'Output ceiling'
                        time.sleep(protocol['poll_seconds'])
                    row['ready'] = load(ready)
                    assert row['ready']['pid'] == child.pid and row['ready']['stage'] == stage
                    if stage < 2:
                        assert child.poll() is None
                        child.kill(); row['forced_termination'] = True
                    child.wait(timeout=max(0.1, min(5, end - time.monotonic(), start + protocol['process_wall_seconds'] - time.monotonic())))
                    row['returncode'] = child.returncode
                    assert child.returncode != 0 if stage < 2 else child.returncode == 0
                    assert time.monotonic() < min(end, start + protocol['process_wall_seconds']), 'Post-ready wall deadline'
                    assert observed_output_bytes(output) < protocol['output_bytes_ceiling'], 'Post-ready output ceiling'
                finally:
                    if child.poll() is None:
                        child.kill(); child.wait(timeout=5); row['cleanup_forced'] = True
                    row['returncode'] = child.returncode
                    row['completed_at'] = now(); row['elapsed_seconds'] = time.monotonic() - start
                    save(output / 'execution.json', report)
        assert len({r['pid'] for r in report['processes']}) == 3
        final = load(output / 'stage2-snapshot.json')['state']
        with sqlite3.connect((output / 'service.sqlite').as_uri() + '?mode=ro', uri=True) as database:
            integrity = database.execute('PRAGMA integrity_check').fetchall()
            assert integrity == [('ok',)]
            tasks = [json.loads(row[0]) for row in database.execute('SELECT record FROM tasks ORDER BY id')]
            assert len(tasks) == 6 and all(t['state']['status'] == 'terminal' for t in tasks)
            assert {t['id'] for t in tasks} == {value['taskId'] for value in final['requests'].values()}
            by_id = {task['id']: task for task in tasks}
            identities = load(output / 'identities-final.json')
            for name in ('one', 'two', 'progress', 'final'):
                task = by_id[identities[name]['taskId']]
                assert task['state']['outcome'] == {'status': 'completed', 'result': 'committed'}
                assert final['effects'][identities[name]['key']] == {
                    'count': 1, 'payload': 'effect-' + name}
            assert by_id[identities['denied']['taskId']]['state']['outcome'] == {
                'status': 'completed', 'result': 'denied'}
            assert by_id[identities['cancelled']['taskId']]['state']['outcome'] == {'status': 'aborted'}
            document, document_sequences = read_service_document(database)
            assert document == final
        states = []
        sequences = []
        admissions = []
        for stage in range(3):
            events = [json.loads(line) for line in (output / f'stage{stage}.jsonl').read_text().splitlines()]
            assert not any(event['type'] in ('runtime-report', 'provider-access-denied', 'network-access-denied') for event in events)
            committed = [event for event in events if event['type'] == 'committed-state']
            assert committed and [x['seq'] for x in committed] == sorted(set(x['seq'] for x in committed))
            states.extend(event['state'] for event in committed)
            sequences.extend(event['seq'] for event in committed)
            admissions.extend(event for event in events if event['type'] == 'admission')
        # Session-scope base checkpoints compact older SQLite revisions. Verify the
        # retained endpoint, without claiming that the DB preserves trace history.
        assert sequences == sorted(set(sequences))
        assert sequences[-1] == document_sequences[-1] and states[-1] == final
        assert {status: sum(a['status'] == status for a in admissions) for status in ('admit', 'duplicate', 'overloaded', 'unauthorized', 'conflict')} == {'admit': 6, 'duplicate': 3, 'overloaded': 1, 'unauthorized': 1, 'conflict': 1}
        assert max(len(state['active']) for state in states) == 2
        assert all(len(state['active']) <= 2 for state in states)
        assert len(final['requests']) == 6 and len(final['effects']) == 4
        assert all(value['count'] == 1 for value in final['effects'].values())
        assert len(final['denied']) == len(final['cancelled']) == 1
        assert not set(final['denied'] + final['cancelled']) & set(final['effects'])
        report.update(status='passed', acceptance={'sqlite_integrity': 'ok', 'native_tasks': tasks,
            'final_document': final, 'committed_states': len(states), 'max_active': 2, 'effects': 4,
            'admission_attempts': len(admissions), 'retained_document_sequences': document_sequences,
            'observed_document_sequences': sequences,
            'all_effect_counts_one': all(value['count'] == 1 for value in final['effects'].values())})
    except Exception as error:
        report.update(status='failed', error=repr(error))
    finally:
        report['completed_at'] = now()
        report['scope'] = protocol['limits']
        save(output / 'execution.json', report)
    print(json.dumps({'status': report['status'], 'processes': len(report['processes']), 'output': str(output), 'error': report.get('error')}))
    return 0 if report['status'] == 'passed' else 1

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--freeze', type=Path, required=True)
    raise SystemExit(execute(parser.parse_args().freeze.resolve()))
