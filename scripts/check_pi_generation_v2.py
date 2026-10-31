"""Portable integrity/acceptance replay; no Node, provider, model, SQLite or network."""
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.pi_generation_v2_audit import audit


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()



MANDATORY_SOURCES = frozenset((
    'experiments/pi_generation_v2_service.mjs', 'experiments/pi_generation_v2_audit.py',
    'experiments/pi_generation_v2_protocol.json', 'scripts/pi_generation_v2_worker.mjs',
    'scripts/run_pi_generation_v2.py', 'scripts/check_pi_generation_v2.py',
    'tests/pi_generation_v2_service.test.mjs', 'tests/test_pi_generation_v2_audit.py',
    'tests/test_pi_generation_v2_freeze.py', 'experiments/pi_durable_service_v2.mjs',
    'scripts/run_pi_durable_recovery_v3.py'))
PROTOCOL_CONSTANTS = {'suites_permitted': 1, 'retries': 0, 'suite_wall_seconds': 90,
    'process_wall_seconds': 20, 'condition_seconds': 8, 'node_max_old_space_mib': 128,
    'polled_process_private_bytes_ceiling': 268435456, 'output_bytes_ceiling': 20971520,
    'min_free_disk_bytes': 1073741824, 'poll_seconds': 0.02}
WORKLOAD_CONSTANTS = {'native_sessions': 2, 'sqlite_databases': 2,
    'conversations_per_session': 2, 'capacity_per_session': 2, 'process_stages': 3,
    'forced_kills_and_reopens': 2, 'total_unique_arrivals': 20, 'admitted': 14, 'overloaded': 6}


def relative_path(name):
    assert isinstance(name, str) and name and '\\' not in name and ':' not in name
    assert all(part not in ('', '.', '..') for part in name.split('/')), name
    return name


def local_path(root, name):
    path = root / relative_path(name)
    assert path.resolve().is_relative_to(root.resolve()), name
    return path


def hash_value(value):
    assert isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), value


def inventory(manifest):
    rows = manifest['files']
    assert isinstance(rows, list) and rows, 'Empty inventory'
    paths = [relative_path(row['path']) for row in rows]
    assert len(set(paths)) == len(paths), 'Duplicate inventory path'
    for row in rows:
        assert type(row['bytes']) is int and row['bytes'] >= 0
        hash_value(row['sha256'])
    if 'bytes' in manifest: assert manifest['bytes'] == sum(row['bytes'] for row in rows)
    if 'total_bytes' in manifest: assert manifest['total_bytes'] == sum(row['bytes'] for row in rows)
    return set(paths)


def validate_freeze(root, freeze):
    sources = freeze['source_sha256']
    assert set(sources) == MANDATORY_SOURCES, 'Incomplete or unexpected source closure'
    preserved = freeze['preserved_previous_source_sha256']
    assert preserved and {'experiments/pi_durable_service_v2.mjs',
                         'scripts/run_pi_durable_recovery_v3.py'} <= set(preserved)
    for mapping in (sources, preserved):
        for name, expected in mapping.items():
            hash_value(expected)
            assert digest(local_path(root, name)) == expected, name
    protocol_path = local_path(root, freeze['protocol_path'])
    assert freeze['protocol_path'] == 'experiments/pi_generation_v2_protocol.json'
    assert digest(protocol_path) == freeze['protocol_sha256']
    protocol = load(protocol_path)
    assert all(type(protocol[k]) is type(v) and protocol[k] == v for k, v in PROTOCOL_CONSTANTS.items())
    assert all(type(protocol['workload'][k]) is int and protocol['workload'][k] == v
               for k, v in WORKLOAD_CONSTANTS.items())
    assert protocol['workload']['provider_api_identity_contract'] == {'service0': 'default-dynamic', 'service1': 'frontier-faux-v2'}
    declared = datetime.fromisoformat(protocol['predeclared_at'])
    frozen = datetime.fromisoformat(freeze['frozen_at'])
    assert declared.utcoffset() is not None and frozen.utcoffset() is not None and frozen > declared
    hash_value(freeze['node_sha256'])
    local_path(root, freeze['runtime_directory']); local_path(root, freeze['output_directory'])
    manifest_path = local_path(root, freeze['runtime_manifest_path'])
    assert digest(manifest_path) == freeze['runtime_manifest_sha256']
    manifest = load(manifest_path)
    paths = inventory(manifest)
    assert {'package.json', 'package-lock.json'} <= paths
    assert all(p in ('package.json', 'package-lock.json') or p.startswith('node_modules/') for p in paths)
    assert any(p.startswith('node_modules/@earendil-works/pi-durable/') for p in paths)
    assert any(p.startswith('node_modules/@earendil-works/pi-ai/') for p in paths)
    assert any(p.startswith('node_modules/@earendil-works/chord/') for p in paths)
    review_path = local_path(root, freeze['pre_execution_review_path'])
    assert digest(review_path) == freeze['pre_execution_review_sha256']
    review = load(review_path)
    assert review['status'] in ('passed', 'passed_for_separate_freeze')
    assert review['source_sha256'] == sources
    assert review['reviewer_receipts']
    for receipt in review['reviewer_receipts']:
        path = local_path(root, receipt['path'])
        assert digest(path) == receipt['sha256']
        child = load(path)
        assert child['status'] in ('passed', 'passed_for_separate_freeze')
        assert child['source_sha256'] and set(child['source_sha256']) <= set(sources)
        assert all(sources[k] == v for k, v in child['source_sha256'].items())
    return protocol, manifest


def check(root=ROOT):
    fixture = root / 'fixtures/pi-generation-v2'
    result = root / 'results/pi-generation-v2'
    freeze = load(fixture / 'implementation.json')
    protocol, _ = validate_freeze(root, freeze)
    checked = len(freeze['source_sha256']) + len(freeze['preserved_previous_source_sha256'])
    manifest = load(result / 'raw-manifest.json')
    raw = result / 'raw'
    actual = {p.relative_to(raw).as_posix() for p in raw.rglob('*') if p.is_file()}
    assert actual == inventory(manifest), 'Complete raw inventory mismatch'
    for row in manifest['files']:
        path = raw / row['path']
        assert path.resolve().is_relative_to(raw.resolve())
        assert path.stat().st_size == row['bytes'] and digest(path) == row['sha256'], row['path']
        checked += 1
    execution = load(raw / 'execution.json')
    assert execution['freeze_sha256'] == digest(fixture / 'implementation.json')
    assert execution['scientific_suites'] == 1 and execution['retries'] == 0 and execution['model_loads'] == 0
    assert execution['status'] in ('passed', 'failed'), 'Unfinished or unknown execution status'
    assert execution['limits'] == protocol['limits']
    assert math.isfinite(execution['elapsed_seconds']) and execution['elapsed_seconds'] >= 0
    if execution['status'] == 'failed': assert execution.get('error')
    report = load(result / 'report.json')
    assert report['execution_status'] == execution['status']
    accepted = execution['status'] == 'passed'
    if accepted:
        assert audit(raw) == execution['acceptance'] == report['acceptance']
        rows = execution['processes']
        assert len(rows) == 3 and len({p['pid'] for p in rows}) == 3
        assert [p['forced_termination'] for p in rows] == [True, True, False]
        assert all(p['returncode'] != 0 for p in rows[:2]) and rows[2]['returncode'] == 0
        assert all(p['ready']['pid'] == p['pid'] and p['ready']['stage'] == p['stage'] for p in rows)
        assert [p['stage'] for p in rows] == [0, 1, 2]
        assert all(math.isfinite(p['elapsed_seconds']) and 0 <= p['elapsed_seconds'] < protocol['process_wall_seconds'] for p in rows)
        assert execution['elapsed_seconds'] < protocol['suite_wall_seconds']
        assert sum(r['bytes'] for r in manifest['files']) < protocol['output_bytes_ceiling']
        assert all(p['memory_samples'] for p in rows)
        assert all(type(s['PrivateUsage']) is int and 0 <= s['PrivateUsage'] < protocol['polled_process_private_bytes_ceiling'] for p in rows for s in p['memory_samples'])
    assert report['execution_accepted'] == accepted
    assert report['raw_files'] == len(manifest['files'])
    assert report['raw_bytes'] == sum(r['bytes'] for r in manifest['files'])
    return {'status': 'passed', 'integrity_items': checked, 'execution_accepted': accepted,
            'scientific_suites': 1, 'scope': 'Saved bytes only; does not run native code or validate a model.'}


if __name__ == '__main__':
    print(json.dumps(check()))
