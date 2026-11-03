"""One frozen public receipt-recovery native/effect-HTTP suite; no automatic retry."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.pi_receipt_recovery_audit import audit
from scripts.check_pi_receipt_recovery import local_path, validate_freeze
from scripts.run_pi_scoped_generation import capture_effect
from scripts.run_pi_generation_conflict import capture
from scripts.run_pi_durable_recovery_v3 import load, memory, now, observed_output_bytes, save, sha


def execute(freeze_path):
    full_start = time.monotonic(); full_started = now()
    frozen = load(freeze_path)
    own = Path(__file__).resolve().relative_to(ROOT).as_posix()
    assert frozen['source_sha256'].get(own) == sha(ROOT / own)
    protocol, manifest = validate_freeze(ROOT, frozen)
    assert datetime.fromisoformat(now()) > datetime.fromisoformat(frozen['frozen_at'])
    runtime = local_path(ROOT, frozen['runtime_directory']); node = Path(frozen['node'])
    assert sha(node) == frozen['node_sha256']
    actual = {p.relative_to(runtime).as_posix() for p in (runtime / 'node_modules').rglob('*') if p.is_file()}
    actual.update(('package.json', 'package-lock.json'))
    assert actual == {r['path'] for r in manifest['files']}
    for item in manifest['files']:
        path = local_path(runtime, item['path'])
        assert path.stat().st_size == item['bytes'] and sha(path) == item['sha256'], item['path']
    output = local_path(ROOT, frozen['output_directory'])
    assert not output.exists(), 'Existing scientific outcome must not be retried'
    assert shutil.disk_usage(output.parent).free >= protocol['min_free_disk_bytes']
    output.mkdir()
    suite = {'full_controller_started_at': full_started, 'authentication_elapsed_seconds': time.monotonic() - full_start,
             'started_at': now(), 'status': 'running', 'scientific_suites': 1, 'retries': 0,
             'model_loads': 0, 'freeze_sha256': sha(freeze_path), 'processes': [], 'servers': []}
    save(output / 'execution.json', suite)
    start = time.monotonic(); deadline = start + protocol['suite_wall_seconds']
    env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP') if k in os.environ}
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    def budget():
        assert time.monotonic() < deadline, 'Suite wall bound'
        assert observed_output_bytes(output) < protocol['output_bytes_ceiling'], 'Output byte ceiling'
    def sample(child, row, begun, cap):
        value = memory(child)
        row['memory_samples'].append({'elapsed': time.monotonic() - begun, **value})
        assert value['PrivateUsage'] < cap, 'Observed process private byte ceiling'
        assert time.monotonic() < min(deadline, begun + protocol['process_wall_seconds'])
        budget()
    try:
        for stage in range(3):
            server_start = time.monotonic()
            bootstrap = ('import runpy,sys;directory,script,*args=sys.argv[1:];'
                         'sys.path.insert(0,directory);sys.argv=[script,*args];'
                         'runpy.run_path(script,run_name="__main__")')
            argv = [frozen['python'], '-I', '-B', '-X', 'utf8', '-c', bootstrap,
                    str(ROOT / 'experiments'), str(ROOT / 'experiments/pi_scoped_effect_http_server.py'),
                    '--output', str(output), '--stage', str(stage)]
            server_row = {'stage': stage, 'argv': argv, 'started_at': now(), 'memory_samples': []}
            suite['servers'].append(server_row)
            with (output / f'effect-server{stage}.stdout').open('wb') as sout, (output / f'effect-server{stage}.stderr').open('wb') as serr:
                server = subprocess.Popen(argv, env=env, cwd=ROOT, stdout=sout, stderr=serr, creationflags=flags)
                server_row['pid'] = server.pid
                try:
                    ready = output / f'effect-server{stage}-ready.json'
                    while not ready.exists():
                        assert server.poll() is None, f'Effect server exited{server.returncode} before ready'
                        sample(server, server_row, server_start, protocol['server_private_bytes_ceiling']); time.sleep(protocol['poll_seconds'])
                    server_ready = load(ready)
                    assert server_ready['pid'] == server.pid and server_ready['stage'] == stage and server_ready['protocol'] == 'scoped-v2'
                    sample(server, server_row, server_start, protocol['server_private_bytes_ceiling'])
                    child_argv = [str(node), '--max-old-space-size=128', str(ROOT / 'scripts/pi_receipt_recovery_worker.mjs'),
                                  str(runtime), str(output), str(stage), server_ready['base']]
                    row = {'stage': stage, 'argv': child_argv, 'started_at': now(), 'memory_samples': [], 'forced_termination': False}
                    suite['processes'].append(row); begun = time.monotonic()
                    with (output / f'stage{stage}.stdout.txt').open('wb') as stdout, (output / f'stage{stage}.stderr.txt').open('wb') as stderr:
                        child = subprocess.Popen(child_argv, env=env, cwd=ROOT, stdout=stdout, stderr=stderr, creationflags=flags)
                        row['pid'] = child.pid
                        try:
                            ready = output / f'stage{stage}-ready.json'
                            while not ready.exists():
                                if child.poll() is not None:
                                    if ready.exists(): break
                                    raise RuntimeError(f'Native stage{stage} exited{child.returncode} before ready')
                                assert server.poll() is None, 'Independent effect server died'
                                sample(child, row, begun, protocol['polled_process_private_bytes_ceiling'])
                                sample(server, server_row, server_start, protocol['server_private_bytes_ceiling'])
                                time.sleep(protocol['poll_seconds'])
                            if not row['memory_samples'] and child.poll() is None:
                                sample(child, row, begun, protocol['polled_process_private_bytes_ceiling'])
                            assert row['memory_samples']
                            row['ready'] = load(ready)
                            assert row['ready']['pid'] == child.pid and row['ready']['stage'] == stage
                            if stage < 2:
                                assert child.poll() is None; child.kill(); row['forced_termination'] = True
                            child.wait(timeout=max(0.1, min(5, deadline - time.monotonic())))
                            assert child.returncode != 0 if stage < 2 else child.returncode == 0
                            assert time.monotonic() < min(deadline, begun + protocol['process_wall_seconds'])
                        finally:
                            if child.poll() is None:
                                child.kill(); child.wait(timeout=5); row['cleanup_forced'] = True
                            row.update(returncode=child.returncode, completed_at=now(), elapsed_seconds=time.monotonic() - begun)
                            save(output / 'execution.json', suite)
                    # Stop only after the native client has exited. This releases held replies,
                    # joins server request threads and leaves a stopped, independently persisted DB.
                    req = Request(server_ready['base'] + 'stop', data=b'{}', method='POST',
                                  headers={'x-frontier-fixture': 'local-fixture-v2-scoped'})
                    with urlopen(req, timeout=min(2, max(0.1, deadline - time.monotonic()))) as response:
                        assert response.status == 200 and json.loads(response.read(4096)) == {'ok': True}
                    server.wait(timeout=max(0.1, min(5, deadline - time.monotonic())))
                    assert server.returncode == 0
                    budget()
                finally:
                    if server.poll() is None:
                        server.kill(); server.wait(timeout=5); server_row['cleanup_forced'] = True
                    server_row.update(returncode=server.returncode, completed_at=now(), elapsed_seconds=time.monotonic() - server_start)
                    save(output / 'execution.json', suite)
            capture(output, stage, deadline); capture_effect(output, stage, deadline); budget()
        assert len({r['pid'] for r in suite['processes']}) == len({r['pid'] for r in suite['servers']}) == 3
        suite['acceptance'] = audit(output); suite['status'] = 'passed'
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
    print(json.dumps({'status': suite['status'], 'native_processes': len(suite['processes']), 'servers': len(suite['servers']), 'error': suite.get('error')}))
    return 0 if suite['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--freeze', type=Path, required=True)
    raise SystemExit(execute(parser.parse_args().freeze.resolve()))
