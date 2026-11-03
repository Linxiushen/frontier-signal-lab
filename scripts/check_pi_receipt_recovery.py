"""Frozen public receipt recovery and saved evidence; never opens a native runtime."""
from datetime import datetime
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.pi_receipt_recovery_audit import audit
from scripts.check_pi_generation_cancellation import digest, hash_value, inventory, load, local_path
from scripts.check_pi_scoped_generation import (
    CONSTANTS, validate_freeze as validate_previous_freeze,
)

MANDATORY_SOURCES = frozenset((
    'experiments/pi_generation_receipt_service.mjs', 'tests/pi_generation_receipt_service.test.mjs',
    'experiments/pi_receipt_recovery_barriers.mjs', 'tests/pi_receipt_recovery_barriers.test.mjs',
    'experiments/pi_receipt_recovery_audit.py', 'experiments/pi_receipt_recovery_protocol.json',
    'scripts/pi_receipt_recovery_worker.mjs', 'scripts/run_pi_receipt_recovery.py',
    'scripts/check_pi_receipt_recovery.py', 'tests/test_pi_receipt_recovery_audit.py'))
PREVIOUS = 'fixtures/pi-scoped-generation/implementation.json'
OUTPUT = 'local-state/pi-receipt-recovery-20261103T031400Z'
WORKLOAD = {
    'native_sessions': 2, 'conversations_per_session': 2, 'capacity_per_session': 2,
    'native_processes': 3, 'forced_native_kills_and_reopens': 2,
    'independent_effect_server_processes': 3, 'graceful_effect_server_reopens': 2,
    'unique_arrivals': 12, 'host_reservations': 8, 'overload_refusals': 4,
    'total_admission_calls': 16, 'exact_host_retries': 2, 'changed_host_conflicts': 2,
    'generation_tasks': 8, 'tool_tasks': 8, 'official_local_faux_calls': 8,
    'effect_intents': 8, 'effect_rows': 6, 'effect_GET_attempts': 10,
    'effect_POST_attempts': 7, 'POST_created': 6, 'POST_denied': 1,
    'overlapping_reconcile_pairs': 2, 'superseded_refusals': 2,
    'host_authority_refusals_without_receipt': 1,
    'cancelled_before_remote_effect': 1, 'cancelled_after_remote_effect': 2,
    'recovered_reservation_observations': 8, 'host_terminals': 8,
    'native_terminal_tasks': 16, 'native_aborted_tasks': 4, 'final_active': 0,
}
RUNTIME_FIELDS = (
    'node', 'node_sha256', 'runtime_directory', 'runtime_manifest_path',
    'runtime_manifest_sha256', 'python', 'python_sha256', 'python_version',
    'sqlite_version', 'python_runtime_modules',
)


def source_hashes(root, mapping):
    assert mapping
    for name, expected in mapping.items():
        hash_value(expected)
        assert digest(local_path(root, name)) == expected, name


def review_receipts(root, freeze, *, complete_sources):
    path = local_path(root, freeze['pre_execution_review_path'])
    assert digest(path) == freeze['pre_execution_review_sha256']
    review = load(path)
    assert review['status'] in ('passed', 'passed_for_separate_freeze')
    assert review['source_sha256'] == freeze['source_sha256']
    receipts = review['reviewer_receipts']
    assert receipts and len({row['path'] for row in receipts}) == len(receipts)
    if complete_sources:
        assert review['status'] == 'passed_for_separate_freeze' and len(receipts) >= 2
    for row in receipts:
        path = local_path(root, row['path'])
        assert digest(path) == row['sha256']
        child = load(path)
        assert child['status'] in ('passed', 'passed_for_separate_freeze')
        if complete_sources:
            assert child['status'] == 'passed_for_separate_freeze'
            assert child['source_sha256'] == freeze['source_sha256']
        else:
            assert child['source_sha256'] and set(child['source_sha256']) <= set(freeze['source_sha256'])
            assert all(freeze['source_sha256'][k] == v for k, v in child['source_sha256'].items())


def portable_parent(root, freeze, visited):
    """Authenticate retained source/review bytes, without host binary imports."""
    source_hashes(root, freeze['source_sha256'])
    source_hashes(root, freeze['preserved_previous_source_sha256'])
    review_receipts(root, freeze, complete_sources=False)
    protocol = local_path(root, freeze['protocol_path'])
    assert digest(protocol) == freeze['protocol_sha256'] == freeze['source_sha256'][freeze['protocol_path']]
    previous_name = freeze.get('previous_freeze_path')
    if previous_name:
        assert previous_name not in visited, 'Cyclic freeze ancestry'
        visited.add(previous_name)
        path = local_path(root, previous_name)
        assert digest(path) == freeze['previous_freeze_sha256']
        previous = load(path)
        assert freeze['preserved_previous_source_sha256'] == {
            **previous['preserved_previous_source_sha256'], **previous['source_sha256']}
        portable_parent(root, previous, visited)


def validate_freeze(root, freeze, *, authenticate_runtime=True):
    sources = freeze['source_sha256']
    assert set(sources) == MANDATORY_SOURCES
    assert freeze['previous_freeze_path'] == PREVIOUS
    previous_path = local_path(root, PREVIOUS)
    assert digest(previous_path) == freeze['previous_freeze_sha256']
    previous = load(previous_path)
    assert freeze['preserved_previous_source_sha256'] == {
        **previous['preserved_previous_source_sha256'], **previous['source_sha256']}
    source_hashes(root, sources)
    source_hashes(root, freeze['preserved_previous_source_sha256'])
    assert all(freeze[k] == previous[k] for k in RUNTIME_FIELDS)
    if authenticate_runtime:
        # This checks the complete old freeze's sources and local runtime identity.
        # It never replays the old failed scientific acceptance audit.
        _, manifest = validate_previous_freeze(root, previous)
    else:
        portable_parent(root, previous, {PREVIOUS})
        manifest_path = local_path(root, freeze['runtime_manifest_path'])
        assert digest(manifest_path) == freeze['runtime_manifest_sha256']
        manifest = load(manifest_path)
        inventory(manifest)
    for name in ('node_sha256', 'python_sha256', 'runtime_manifest_sha256'):
        hash_value(freeze[name])
    assert freeze['protocol_path'] == 'experiments/pi_receipt_recovery_protocol.json'
    protocol_path = local_path(root, freeze['protocol_path'])
    assert digest(protocol_path) == freeze['protocol_sha256'] == sources[freeze['protocol_path']]
    protocol = load(protocol_path)
    assert protocol['id'] == 'pi-receipt-recovery-native-v1'
    assert all(type(protocol[k]) is type(v) and protocol[k] == v for k, v in CONSTANTS.items())
    assert set(protocol['workload']) == set(WORKLOAD)
    assert all(type(protocol['workload'][k]) is int and protocol['workload'][k] == v
               for k, v in WORKLOAD.items())
    declared = datetime.fromisoformat(protocol['predeclared_at'])
    frozen = datetime.fromisoformat(freeze['frozen_at'])
    assert declared.utcoffset() is not None and frozen.utcoffset() is not None and frozen > declared
    assert freeze['output_directory'] == OUTPUT
    local_path(root, OUTPUT)
    review_receipts(root, freeze, complete_sources=True)
    return protocol, manifest


def check(root=ROOT):
    fixture = root / 'fixtures/pi-receipt-recovery'
    result = root / 'results/pi-receipt-recovery'
    freeze = load(fixture / 'implementation.json')
    protocol, _ = validate_freeze(root, freeze, authenticate_runtime=False)
    raw = result / 'raw'
    manifest = load(result / 'raw-manifest.json')

    def verify_raw():
        assert {p.relative_to(raw).as_posix() for p in raw.rglob('*') if p.is_file()} == inventory(manifest)
        for row in manifest['files']:
            path = local_path(raw, row['path'])
            assert path.stat().st_size == row['bytes'] and digest(path) == row['sha256']

    verify_raw()
    execution = load(raw / 'execution.json')
    report = load(result / 'report.json')
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
        assert all(r['returncode'] != 0 for r in execution['processes'][:2])
        assert execution['processes'][2]['returncode'] == 0
        assert all(r['returncode'] == 0 for r in execution['servers'])
        assert all(not r.get('cleanup_forced') for group in ('processes', 'servers') for r in execution[group])
        assert execution['elapsed_seconds'] < protocol['suite_wall_seconds']
        assert report['raw_bytes'] < protocol['output_bytes_ceiling']
        for group, cap in [('processes', protocol['polled_process_private_bytes_ceiling']),
                           ('servers', protocol['server_private_bytes_ceiling'])]:
            for row in execution[group]:
                assert row['memory_samples']
                assert math.isfinite(row['elapsed_seconds']) and 0 <= row['elapsed_seconds'] < protocol['process_wall_seconds']
                assert all(type(s['PrivateUsage']) is int and 0 <= s['PrivateUsage'] < cap
                           for s in row['memory_samples'])
    else:
        # No supplemental observer, CI or later audit can turn a failed freeze green.
        assert execution.get('error')
    verify_raw()
    return {'status': 'passed', 'execution_accepted': report['execution_accepted'],
            'raw_files': len(manifest['files']), 'runtime_reauthenticated': False,
            'scope': 'Portable frozen source/review and saved-byte audit only; no native, server, model or network execution.'}


if __name__ == '__main__':
    print(json.dumps(check()))
