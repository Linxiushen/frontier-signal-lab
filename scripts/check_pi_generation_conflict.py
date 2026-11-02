"""Integrity-only gate for the separate error/collision preparation and saved result."""
from datetime import datetime
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.pi_generation_conflict_audit import audit
from scripts.check_pi_generation_cancellation import digest, hash_value, inventory, load, local_path

MANDATORY_SOURCES = frozenset((
    'experiments/pi_generation_conflict_service.mjs', 'experiments/pi_generation_conflict_audit.py',
    'experiments/pi_generation_conflict_protocol.json', 'scripts/pi_generation_conflict_worker.mjs',
    'scripts/run_pi_generation_conflict.py', 'scripts/check_pi_generation_conflict.py',
    'tests/pi_generation_conflict_service.test.mjs', 'tests/test_pi_generation_conflict.py'))
CONSTANTS = {'suites_permitted': 1, 'retries': 0, 'suite_wall_seconds': 90,
             'process_wall_seconds': 20, 'condition_seconds': 8, 'node_max_old_space_mib': 128,
             'polled_process_private_bytes_ceiling': 268435456, 'output_bytes_ceiling': 20971520,
             'min_free_disk_bytes': 1073741824, 'poll_seconds': 0.02}
WORKLOAD = {'native_sessions': 2, 'sqlite_databases': 2, 'conversations_per_session': 2,
            'capacity_per_session': 2, 'process_stages': 3, 'forced_kills_and_reopens': 2,
            'total_unique_arrivals': 18, 'durable_host_reservations': 14, 'overloaded': 4,
            'expected_native_submissions': 12, 'expected_native_generation_tasks': 10,
            'expected_native_tool_tasks': 10, 'expected_faux_provider_calls': 10, 'expected_local_effects': 6}


def validate_freeze(root, freeze):
    sources = freeze['source_sha256']; assert set(sources) == MANDATORY_SOURCES
    assert freeze['previous_freeze_path'] == 'fixtures/pi-generation-cancellation/implementation.json'
    prior_path = local_path(root, freeze['previous_freeze_path'])
    assert digest(prior_path) == freeze['previous_freeze_sha256']
    prior = load(prior_path)
    preserved = {**prior['preserved_previous_source_sha256'], **prior['source_sha256']}
    assert freeze['preserved_previous_source_sha256'] == preserved
    for mapping in (sources, preserved):
        for name, expected in mapping.items():
            hash_value(expected); assert digest(local_path(root, name)) == expected, name
    assert freeze['protocol_path'] == 'experiments/pi_generation_conflict_protocol.json'
    protocol_path = local_path(root, freeze['protocol_path'])
    assert digest(protocol_path) == freeze['protocol_sha256'] == sources[freeze['protocol_path']]
    protocol = load(protocol_path)
    assert all(type(protocol[k]) is type(v) and protocol[k] == v for k, v in CONSTANTS.items())
    assert all(type(protocol['workload'][k]) is int and protocol['workload'][k] == v for k, v in WORKLOAD.items())
    assert protocol['workload']['provider_api_identity_contract'] == {'service0': 'default-dynamic', 'service1': 'frontier-faux-conflict'}
    declared = datetime.fromisoformat(protocol['predeclared_at']); frozen = datetime.fromisoformat(freeze['frozen_at'])
    assert declared.utcoffset() is not None and frozen.utcoffset() is not None and frozen > declared
    for k in ('node', 'node_sha256', 'runtime_directory', 'runtime_manifest_path', 'runtime_manifest_sha256'):
        assert freeze[k] == prior[k], 'Same already pinned native runtime'
    manifest_path = local_path(root, freeze['runtime_manifest_path'])
    assert digest(manifest_path) == freeze['runtime_manifest_sha256']
    manifest = load(manifest_path); inventory(manifest)
    local_path(root, freeze['output_directory'])
    review_path = local_path(root, freeze['pre_execution_review_path'])
    assert digest(review_path) == freeze['pre_execution_review_sha256']
    review = load(review_path)
    assert review['status'] == 'passed_for_separate_freeze' and review['source_sha256'] == sources
    assert review['reviewer_receipts']
    for receipt in review['reviewer_receipts']:
        path = local_path(root, receipt['path']); assert digest(path) == receipt['sha256']
        child = load(path)
        assert child['status'] == 'passed_for_separate_freeze'
        assert child['source_sha256'] and set(child['source_sha256']) <= set(sources)
        assert all(sources[k] == v for k, v in child['source_sha256'].items())
    return protocol, manifest


def check(root=ROOT):
    fixture = root / 'fixtures/pi-generation-conflict'; result = root / 'results/pi-generation-conflict'
    freeze = load(fixture / 'implementation.json'); protocol, _ = validate_freeze(root, freeze)
    manifest = load(result / 'raw-manifest.json'); raw = result / 'raw'
    assert {p.relative_to(raw).as_posix() for p in raw.rglob('*') if p.is_file()} == inventory(manifest)
    for row in manifest['files']:
        path = local_path(raw, row['path'])
        assert path.stat().st_size == row['bytes'] and digest(path) == row['sha256']
    execution = load(raw / 'execution.json'); report = load(result / 'report.json')
    assert execution['freeze_sha256'] == digest(fixture / 'implementation.json')
    assert execution['scientific_suites'] == 1 and execution['retries'] == 0 and execution['model_loads'] == 0
    assert execution['status'] in ('passed', 'failed') and execution['limits'] == protocol['limits']
    assert report['execution_status'] == execution['status']
    accepted = execution['status'] == 'passed'; assert report['execution_accepted'] == accepted
    assert execution['full_controller_elapsed_seconds'] >= execution['authentication_elapsed_seconds'] >= 0
    assert execution['full_controller_elapsed_seconds'] >= execution['elapsed_seconds'] >= 0
    if accepted:
        assert audit(raw) == execution['acceptance'] == report['acceptance']
        rows = execution['processes']; assert len(rows) == len({r['pid'] for r in rows}) == 3
        assert [r['forced_termination'] for r in rows] == [True, True, False]
        assert all(r['returncode'] != 0 for r in rows[:2]) and rows[2]['returncode'] == 0
        assert all(math.isfinite(r['elapsed_seconds']) and 0 <= r['elapsed_seconds'] < protocol['process_wall_seconds'] for r in rows)
        assert execution['elapsed_seconds'] < protocol['suite_wall_seconds']
        assert sum(r['bytes'] for r in manifest['files']) < protocol['output_bytes_ceiling']
        assert all(r['memory_samples'] for r in rows)
        assert all(type(s['PrivateUsage']) is int and 0 <= s['PrivateUsage'] < protocol['polled_process_private_bytes_ceiling'] for r in rows for s in r['memory_samples'])
    else:
        assert execution.get('error')
    assert report['raw_files'] == len(manifest['files']) and report['raw_bytes'] == sum(r['bytes'] for r in manifest['files'])
    return {'status': 'passed', 'execution_accepted': accepted, 'raw_files': len(manifest['files']),
            'source_pins': len(freeze['source_sha256']) + len(freeze['preserved_previous_source_sha256']),
            'scope': 'Saved bytes only; no native or model execution.'}


if __name__ == '__main__':
    print(json.dumps(check()))
