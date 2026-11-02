"""Source/runtime freeze and saved evidence checks, without native execution."""
from datetime import datetime
import importlib
import json
import math
from pathlib import Path
import platform
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.pi_generation_concurrent_http_audit import audit
from scripts.check_pi_generation_cancellation import digest, hash_value, inventory, load, local_path

MANDATORY_SOURCES = frozenset((
    'experiments/pi_concurrent_admission.mjs', 'experiments/pi_generation_concurrent_http_audit.py',
    'experiments/pi_generation_concurrent_http_protocol.json', 'scripts/pi_generation_concurrent_http_worker.mjs',
    'scripts/run_pi_generation_concurrent_http.py', 'scripts/check_pi_generation_concurrent_http.py',
    'tests/pi_concurrent_admission.test.mjs', 'tests/test_pi_generation_concurrent_http.py'))
CONSTANTS = {'suites_permitted': 1, 'retries': 0, 'suite_wall_seconds': 90, 'process_wall_seconds': 20,
             'condition_seconds': 8, 'node_max_old_space_mib': 128,
             'polled_process_private_bytes_ceiling': 268435456, 'server_private_bytes_ceiling': 134217728,
             'output_bytes_ceiling': 33554432, 'min_free_disk_bytes': 1073741824, 'poll_seconds': 0.02,
             'http_wall_ms': 2000, 'http_request_bytes': 4096, 'http_response_bytes': 16384}
WORKLOAD = {'native_sessions': 2, 'conversations_per_session': 2, 'capacity_per_session': 2,
            'native_processes': 3, 'forced_native_kills_and_reopens': 2,
            'independent_effect_server_processes': 3, 'graceful_effect_server_reopens': 2,
            'unique_arrivals': 16, 'host_reservations': 12, 'overload_refusals': 4,
            'generation_tasks': 12, 'tool_tasks': 12, 'official_local_faux_calls': 12,
            'effect_intents': 12, 'effect_rows': 8, 'effect_GET_attempts': 14, 'effect_POST_attempts': 14,
            'POST_created': 8, 'POST_denied': 2, 'POST_duplicate': 2, 'POST_identity_conflict': 2,
            'normal_native_completions': 6, 'cancelled_after_remote_effect': 2,
            'cancelled_before_remote_effect': 2, 'remote_authority_refusals': 2,
            'host_terminals': 12, 'native_terminal_tasks': 24, 'recovered_host_reservations': 6,
            'final_active': 0, 'total_admission_calls': 28, 'concurrent_rounds': 6, 'callers_per_round': 3,
            'concurrent_exact_retries': 6, 'changed_content_conflicts': 6}
PYTHON_MODULES = ('argparse', 'contextlib', 'datetime', 'hashlib', 'http.server', 'json', 'pathlib',
                  'socket', 'socketserver', 'sqlite3', 'sqlite3.dbapi2', 'threading', 'time', 'urllib.parse',
                  '_socket', '_sqlite3', '_hashlib', '_json', '_datetime', '_thread', 'os')


def python_runtime_modules():
    result = []
    for name in PYTHON_MODULES:
        module = importlib.import_module(name)
        path = getattr(module, '__file__', None)
        result.append({'name': name, 'path': str(Path(path).resolve()), 'sha256': digest(Path(path))}
                      if path else {'name': name, 'origin': module.__spec__.origin})
    return result


def validate_workload(workload):
    assert set(workload) == set(WORKLOAD)
    assert all(type(workload[k]) is int and workload[k] == value for k, value in WORKLOAD.items())


def validate_freeze(root, freeze):
    sources = freeze['source_sha256']; assert set(sources) == MANDATORY_SOURCES
    assert freeze['previous_freeze_path'] == 'fixtures/pi-generation-http/implementation.json'
    previous_path = local_path(root, freeze['previous_freeze_path'])
    assert digest(previous_path) == freeze['previous_freeze_sha256']
    previous = load(previous_path)
    assert freeze['preserved_previous_source_sha256'] == {**previous['preserved_previous_source_sha256'], **previous['source_sha256']}
    for mapping in (sources, freeze['preserved_previous_source_sha256']):
        for name, expected in mapping.items():
            hash_value(expected); assert digest(local_path(root, name)) == expected, name
    for name in ('node', 'node_sha256', 'runtime_directory', 'runtime_manifest_path', 'runtime_manifest_sha256'):
        assert freeze[name] == previous[name]
    assert freeze['protocol_path'] == 'experiments/pi_generation_concurrent_http_protocol.json'
    assert digest(local_path(root, freeze['protocol_path'])) == freeze['protocol_sha256'] == sources[freeze['protocol_path']]
    protocol = load(local_path(root, freeze['protocol_path']))
    assert all(type(protocol[k]) is type(v) and protocol[k] == v for k, v in CONSTANTS.items())
    validate_workload(protocol['workload'])
    declared = datetime.fromisoformat(protocol['predeclared_at']); frozen = datetime.fromisoformat(freeze['frozen_at'])
    assert declared.utcoffset() is not None and frozen.utcoffset() is not None and frozen > declared
    assert digest(Path(freeze['python'])) == freeze['python_sha256']
    assert Path(sys.executable).resolve() == Path(freeze['python']).resolve()
    assert platform.python_version() == freeze['python_version'] and sqlite3.sqlite_version == freeze['sqlite_version']
    assert freeze['python_runtime_modules'] == python_runtime_modules()
    manifest = local_path(root, freeze['runtime_manifest_path'])
    assert digest(manifest) == freeze['runtime_manifest_sha256']
    manifest = load(manifest); inventory(manifest)
    local_path(root, freeze['output_directory'])
    review_path = local_path(root, freeze['pre_execution_review_path'])
    assert digest(review_path) == freeze['pre_execution_review_sha256']
    review = load(review_path)
    assert review['status'] == 'passed_for_separate_freeze' and review['source_sha256'] == sources
    assert len(review['reviewer_receipts']) >= 2
    for receipt in review['reviewer_receipts']:
        path = local_path(root, receipt['path']); assert digest(path) == receipt['sha256']
        child = load(path); assert child['status'] == 'passed_for_separate_freeze'
        assert child['source_sha256'] and set(child['source_sha256']) <= set(sources)
        assert all(sources[k] == v for k, v in child['source_sha256'].items())
    return protocol, manifest


def check(root=ROOT):
    fixture = root / 'fixtures/pi-generation-concurrent-http'; result = root / 'results/pi-generation-concurrent-http'
    freeze = load(fixture / 'implementation.json'); protocol, _ = validate_freeze(root, freeze)
    raw = result / 'raw'; manifest = load(result / 'raw-manifest.json')
    assert {p.relative_to(raw).as_posix() for p in raw.rglob('*') if p.is_file()} == inventory(manifest)
    for row in manifest['files']:
        path = local_path(raw, row['path']); assert path.stat().st_size == row['bytes'] and digest(path) == row['sha256']
    execution = load(raw / 'execution.json'); report = load(result / 'report.json')
    assert execution['freeze_sha256'] == digest(fixture / 'implementation.json')
    assert execution['scientific_suites'] == 1 and execution['retries'] == execution['model_loads'] == 0
    assert execution['status'] == report['execution_status'] in ('passed', 'failed')
    assert report['execution_accepted'] == (execution['status'] == 'passed')
    assert execution['limits'] == protocol['limits']
    assert all(math.isfinite(execution[k]) and execution[k] >= 0 for k in (
        'elapsed_seconds', 'authentication_elapsed_seconds', 'full_controller_elapsed_seconds'))
    assert execution['full_controller_elapsed_seconds'] >= execution['elapsed_seconds']
    assert report['raw_files'] == len(manifest['files'])
    assert report['raw_bytes'] == sum(row['bytes'] for row in manifest['files'])
    if execution['status'] == 'passed':
        assert audit(raw) == execution['acceptance'] == report['acceptance']
        assert len(execution['processes']) == len({r['pid'] for r in execution['processes']}) == 3
        assert len(execution['servers']) == len({r['pid'] for r in execution['servers']}) == 3
        assert [r['forced_termination'] for r in execution['processes']] == [True, True, False]
        assert all(r['returncode'] != 0 for r in execution['processes'][:2]) and execution['processes'][2]['returncode'] == 0
        assert all(r['returncode'] == 0 for r in execution['servers'])
        assert all(not r.get('cleanup_forced') for group in ('processes', 'servers') for r in execution[group])
        assert execution['elapsed_seconds'] < protocol['suite_wall_seconds']
        assert sum(row['bytes'] for row in manifest['files']) < protocol['output_bytes_ceiling']
        for group, cap in [('processes', protocol['polled_process_private_bytes_ceiling']), ('servers', protocol['server_private_bytes_ceiling'])]:
            for row in execution[group]:
                assert row['memory_samples'] and math.isfinite(row['elapsed_seconds']) and 0 <= row['elapsed_seconds'] < protocol['process_wall_seconds']
                assert all(type(sample['PrivateUsage']) is int and 0 <= sample['PrivateUsage'] < cap for sample in row['memory_samples'])
    else:
        assert execution.get('error')
    # Read-only immutable backup audits must not change the raw inventory.
    assert {p.relative_to(raw).as_posix() for p in raw.rglob('*') if p.is_file()} == inventory(manifest)
    return {'status': 'passed', 'execution_accepted': report['execution_accepted'], 'raw_files': len(manifest['files']),
            'scope': 'Frozen sources and saved bytes only; no native, HTTP service or model execution.'}


if __name__ == '__main__':
    print(json.dumps(check()))
