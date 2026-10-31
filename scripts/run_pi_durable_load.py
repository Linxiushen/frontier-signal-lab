"""One future frozen four-arm bounded-burst suite; no implicit rerun or model use."""
from datetime import datetime
import argparse
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
from experiments.pi_durable_load_audit import audit_arm
from scripts.run_pi_durable_recovery_v3 import load, memory, now, observed_output_bytes, read_service_document, save, sha


def execute(freeze_path):
    frozen = load(freeze_path)
    own = Path(__file__).resolve().relative_to(ROOT).as_posix()
    assert frozen['source_sha256'].get(own) == sha(ROOT / own), 'Requires own new exact source freeze'
    protocol = load(ROOT / frozen['protocol_path'])
    assert datetime.fromisoformat(now()) > datetime.fromisoformat(frozen['frozen_at']) > datetime.fromisoformat(protocol['predeclared_at'])
    assert protocol['suites_permitted'] == 1 and protocol['retries'] == 0
    assert sha(ROOT / frozen['protocol_path']) == frozen['protocol_sha256']
    for name, digest in frozen['source_sha256'].items():
        assert sha(ROOT / name) == digest, name
    runtime = ROOT / frozen['runtime_directory']; node = Path(frozen['node'])
    assert sha(node) == frozen['node_sha256']
    manifest_path = ROOT / frozen['runtime_manifest_path']
    assert sha(manifest_path) == frozen['runtime_manifest_sha256']
    manifest = load(manifest_path)
    actual = {p.relative_to(runtime).as_posix() for p in (runtime / 'node_modules').rglob('*') if p.is_file()}
    actual.update(('package.json', 'package-lock.json'))
    assert actual == {r['path'] for r in manifest['files']}
    for row in manifest['files']:
        assert sha(runtime / row['path']) == row['sha256'], row['path']
    output = ROOT / frozen['output_directory']
    assert not output.exists(), 'Existing outcome must never be retried'
    assert shutil.disk_usage(output.parent).free >= protocol['min_free_disk_bytes']
    output.mkdir()
    suite = {'started_at': now(), 'status': 'running', 'scientific_suites': 1, 'retries': 0,
             'model_loads': 0, 'freeze_sha256': sha(freeze_path), 'arms': []}
    suite_start = time.monotonic(); deadline = suite_start + protocol['suite_wall_seconds']
    def check_budget():
        assert time.monotonic() < deadline, 'Suite wall deadline'
        size = observed_output_bytes(output) + sum(observed_output_bytes(p) for p in output.iterdir() if p.is_dir())
        assert size < protocol['output_bytes_ceiling'], 'Complete suite output ceiling'
    env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
    try:
        for arm in protocol['workload']['arms_in_order']:
            directory = output / arm['name']; directory.mkdir()
            result = {'name': arm['name'], 'capacity': arm['capacity'], 'sink': arm['sink'],
                      'started_at': now(), 'processes': []}
            suite['arms'].append(result); arm_start = time.monotonic()
            for stage in range(3):
                argv = [str(node), '--max-old-space-size=128', str(ROOT / 'scripts/pi_durable_load_worker.mjs'),
                        str(runtime), str(directory), str(stage), str(arm['capacity']), arm['sink']]
                row = {'stage': stage, 'argv': argv, 'started_at': now(), 'memory_samples': [], 'forced_termination': False}
                result['processes'].append(row); start = time.monotonic()
                with (directory / f'stage{stage}.stdout.txt').open('wb') as stdout, (directory / f'stage{stage}.stderr.txt').open('wb') as stderr:
                    child = subprocess.Popen(argv, env=env, cwd=ROOT, stdout=stdout, stderr=stderr,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
                    row['pid'] = child.pid
                    try:
                        ready = directory / f'stage{stage}-ready.json'
                        while not ready.exists():
                            if child.poll() is not None:
                                if ready.exists(): break
                                raise RuntimeError(f"{arm['name']}/stage{stage} exited{child.returncode} before ready")
                            sample = memory(child)
                            row['memory_samples'].append({'elapsed': time.monotonic() - start, **sample})
                            assert sample['PrivateUsage'] < protocol['polled_process_private_bytes_ceiling'], 'Private memory ceiling'
                            assert time.monotonic() < min(deadline, start + protocol['process_wall_seconds']), 'Wall deadline'
                            check_budget()
                            time.sleep(protocol['poll_seconds'])
                        row['ready'] = load(ready)
                        assert row['ready']['pid'] == child.pid and row['ready']['stage'] == stage
                        if stage < 2:
                            assert child.poll() is None
                            child.kill(); row['forced_termination'] = True
                        child.wait(timeout=max(0.1, min(5, deadline - time.monotonic(), start + protocol['process_wall_seconds'] - time.monotonic())))
                        assert child.returncode != 0 if stage < 2 else child.returncode == 0
                        assert time.monotonic() < min(deadline, start + protocol['process_wall_seconds'])
                        check_budget()
                    finally:
                        if child.poll() is None:
                            child.kill(); child.wait(timeout=5); row['cleanup_forced'] = True
                        row.update(returncode=child.returncode, completed_at=now(), elapsed_seconds=time.monotonic() - start)
                        save(directory / 'execution.json', result)
                        check_budget()
            assert len({p['pid'] for p in result['processes']}) == 3
            result['process_stages_wall_seconds'] = time.monotonic() - arm_start
            with sqlite3.connect((directory / 'service.sqlite').as_uri() + '?mode=ro', uri=True) as database:
                assert database.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
                tasks = [json.loads(r[0]) for r in database.execute('SELECT record FROM tasks ORDER BY id')]
                conversations = [json.loads(r[0]) for r in database.execute('SELECT record FROM conversations ORDER BY id')]
                assert len(conversations) == 4
                document, sequences = read_service_document(database)
            result['database'] = {'integrity': 'ok', 'tasks': tasks, 'conversation_ids': [r['id'] for r in conversations],
                                  'document': document, 'retained_document_sequences': sequences}
            save(directory / 'execution.json', result)
            result['acceptance'] = audit_arm(directory, arm['capacity'])
            assert result['acceptance']['document_sequences'][-1] == sequences[-1]
            assert set(result['database']['conversation_ids']) == set(load(directory / 'identities.json')['sessions'])
            result.update(status='passed', completed_at=now(), elapsed_seconds=time.monotonic() - arm_start)
            result['elapsed_scope'] = 'Startup/gatedwork/restarts, endpointDBread and controller acceptance audit included; runtime manifest verification excluded.'
            result['committed_effects_per_arm_wall_second'] = result['acceptance']['committed_effects'] / result['elapsed_seconds']
            save(directory / 'execution.json', result); save(output / 'execution.json', suite)
            check_budget()
        for capacity in (2, 4):
            pair = [a['acceptance'] for a in suite['arms'] if a['capacity'] == capacity]
            keys = ('unique_offered', 'effect_eligible_offered', 'admitted', 'admission_counts', 'denied', 'aborted',
                    'committed_effects', 'maximum_active', 'final_active', 'recovered_finish_tasks')
            assert {k: pair[0][k] for k in keys} == {k: pair[1][k] for k in keys}
        check_budget(); suite['status'] = 'passed'
    except Exception as error:
        suite.update(status='failed', error=repr(error))
    finally:
        suite.update(completed_at=now(), elapsed_seconds=time.monotonic() - suite_start, limits=protocol['limits'])
        save(output / 'execution.json', suite)
        if suite['status'] == 'passed':
            try:
                check_budget()
            except AssertionError as error:
                suite.update(status='failed', error=repr(error))
                save(output / 'execution.json', suite)
    print(json.dumps({'status': suite['status'], 'arms': len(suite['arms']), 'error': suite.get('error')}))
    return 0 if suite['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--freeze', required=True, type=Path)
    raise SystemExit(execute(parser.parse_args().freeze.resolve()))
