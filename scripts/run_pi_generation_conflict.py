"""One separately frozen native busy/error/collision suite; no retries."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.pi_generation_conflict_audit import audit, read_endpoint
from scripts.check_pi_generation_conflict import local_path, validate_freeze
from scripts.run_pi_durable_recovery_v3 import load, memory, now, observed_output_bytes, save, sha


def capture(directory, stage, deadline):
    def within_deadline(*_):
        assert time.monotonic() < deadline, "SQLite capture observed deadline"
    # Progress callbacks bound observed work, not blocking OS I/O or an uninterruptible SQLite call.
    within_deadline()
    for service in range(2):
        within_deadline()
        source = directory / f'service{service}.sqlite'
        destination = directory / f'service{service}-stage{stage}.sqlite'
        assert not destination.exists()
        # SQLite backup includes committed WAL pages; a readonly source may create/change auxiliary files.
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=0.02) as database:
            database.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            original_endpoint = read_endpoint(database)
            within_deadline()
            with sqlite3.connect(destination, timeout=0.02) as copied:
                database.backup(copied, pages=16, progress=within_deadline, sleep=0.02)
        with sqlite3.connect(destination.as_uri() + '?mode=ro', uri=True, timeout=0.02) as copied:
            copied.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            within_deadline()
            copied_endpoint = read_endpoint(copied)
            assert copied_endpoint == original_endpoint, 'Full stopped-source/copied SQLite endpoint comparison'
            save(directory / f'service{service}-stage{stage}-endpoint.json', copied_endpoint)
            digest_endpoint = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            save(directory / f'service{service}-stage{stage}-copy-comparison.json', {
                'service': service, 'stage': stage, 'equal': True,
                'source_endpoint_sha256': digest_endpoint(original_endpoint),
                'copy_endpoint_sha256': digest_endpoint(copied_endpoint)})
            within_deadline()


def execute(freeze_path):
    full_start = time.monotonic(); full_started_at = now()
    frozen = load(freeze_path)
    own = Path(__file__).resolve().relative_to(ROOT).as_posix()
    assert frozen['source_sha256'].get(own) == sha(ROOT / own), 'Requires new own exact source freeze'
    protocol, manifest = validate_freeze(ROOT, frozen)
    assert datetime.fromisoformat(now()) > datetime.fromisoformat(frozen['frozen_at'])
    runtime = local_path(ROOT, frozen['runtime_directory']); node = Path(frozen['node'])
    assert sha(node) == frozen['node_sha256']
    actual = {p.relative_to(runtime).as_posix() for p in (runtime / 'node_modules').rglob('*') if p.is_file()}
    actual.update(('package.json', 'package-lock.json'))
    assert actual == {r['path'] for r in manifest['files']}
    for row in manifest['files']:
        path = local_path(runtime, row['path'])
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], row['path']
    output = local_path(ROOT, frozen['output_directory'])
    assert not output.exists(), 'Existing outcome must never be retried'
    assert shutil.disk_usage(output.parent).free >= protocol['min_free_disk_bytes']
    output.mkdir()
    authentication_elapsed = time.monotonic() - full_start
    suite = {'full_controller_started_at': full_started_at, 'authentication_elapsed_seconds': authentication_elapsed,
             'started_at': now(), 'status': 'running', 'scientific_suites': 1, 'retries': 0,
             'model_loads': 0, 'freeze_sha256': sha(freeze_path), 'processes': []}
    save(output / 'execution.json', suite)
    start = time.monotonic(); deadline = start + protocol['suite_wall_seconds']
    def budget():
        assert time.monotonic() < deadline, 'Suite wall bound'
        assert observed_output_bytes(output) < protocol['output_bytes_ceiling'], 'Output byte ceiling'
    env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
    try:
        for stage in range(3):
            argv = [str(node), '--max-old-space-size=128', str(ROOT / 'scripts/pi_generation_conflict_worker.mjs'),
                    str(runtime), str(output), str(stage)]
            row = {'stage': stage, 'argv': argv, 'started_at': now(), 'memory_samples': [], 'forced_termination': False}
            suite['processes'].append(row); process_start = time.monotonic()
            with (output / f'stage{stage}.stdout.txt').open('wb') as stdout, (output / f'stage{stage}.stderr.txt').open('wb') as stderr:
                child = subprocess.Popen(argv, env=env, cwd=ROOT, stdout=stdout, stderr=stderr,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                row['pid'] = child.pid
                try:
                    ready = output / f'stage{stage}-ready.json'
                    while not ready.exists():
                        if child.poll() is not None:
                            if ready.exists(): break
                            raise RuntimeError(f'stage{stage} exited{child.returncode} before ready')
                        sample = memory(child)
                        row['memory_samples'].append({'elapsed': time.monotonic() - process_start, **sample})
                        assert sample['PrivateUsage'] < protocol['polled_process_private_bytes_ceiling']
                        assert time.monotonic() < min(deadline, process_start + protocol['process_wall_seconds'])
                        budget(); time.sleep(protocol['poll_seconds'])
                    if not row['memory_samples'] and child.poll() is None:
                        sample = memory(child)
                        row['memory_samples'].append({'elapsed': time.monotonic() - process_start, **sample})
                        assert sample['PrivateUsage'] < protocol['polled_process_private_bytes_ceiling']
                    assert row['memory_samples'], 'No observed worker memory sample'
                    row['ready'] = load(ready)
                    assert row['ready']['pid'] == child.pid and row['ready']['stage'] == stage
                    if stage < 2:
                        assert child.poll() is None
                        child.kill(); row['forced_termination'] = True
                    child.wait(timeout=max(0.1, min(5, deadline - time.monotonic(), process_start + protocol['process_wall_seconds'] - time.monotonic())))
                    assert child.returncode != 0 if stage < 2 else child.returncode == 0
                    assert time.monotonic() < min(deadline, process_start + protocol['process_wall_seconds']), 'Process wall bound'
                    budget()
                finally:
                    if child.poll() is None:
                        child.kill(); child.wait(timeout=5); row['cleanup_forced'] = True
                    row.update(returncode=child.returncode, completed_at=now(), elapsed_seconds=time.monotonic() - process_start)
                    save(output / 'execution.json', suite)
                capture(output, stage, deadline); budget()
        assert len({r['pid'] for r in suite['processes']}) == 3
        suite['acceptance'] = audit(output)
        suite['status'] = 'passed'
    except BaseException as error:
        suite.update(status='failed', error=repr(error))
    finally:
        suite.update(completed_at=now(), elapsed_seconds=time.monotonic() - start,
                     full_controller_elapsed_seconds=time.monotonic() - full_start, limits=protocol['limits'])
        save(output / 'execution.json', suite)
        if suite['status'] == 'passed':
            try: budget()
            except AssertionError as error:
                suite.update(status='failed', error=repr(error)); save(output / 'execution.json', suite)
    print(json.dumps({'status': suite['status'], 'processes': len(suite['processes']), 'error': suite.get('error')}))
    return 0 if suite['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--freeze', required=True, type=Path)
    raise SystemExit(execute(parser.parse_args().freeze.resolve()))
