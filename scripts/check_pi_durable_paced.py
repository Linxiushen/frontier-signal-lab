"""Check archived paced evidence using saved bytes, never Node or SQLite."""
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.pi_durable_paced_audit import audit_arm, load

RESULT = ROOT / 'results/pi-durable-paced'
FIXTURE = ROOT / 'fixtures/pi-durable-paced'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounded_relative(name):
    path = PurePosixPath(name)
    assert name and '\\' not in name and not path.is_absolute()
    assert all(part not in ('', '.', '..') and ':' not in part for part in path.parts)
    assert path.as_posix() == name
    return path


def finite_nonnegative(value):
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    assert math.isfinite(value) and value >= 0
    return value


def check():
    report = load(RESULT / 'report.json')
    freeze_path = FIXTURE / 'implementation.json'
    freeze = load(freeze_path)
    protocol = load(FIXTURE / 'protocol.json')
    manifest_path = RESULT / 'raw-manifest.json'
    manifest = load(manifest_path)
    assert sha(manifest_path) == report['raw_manifest_sha256']
    rows = [{'path': name, **row} for name, row in manifest['files'].items()]
    names = [str(bounded_relative(row['path'])) for row in rows]
    raw_dir = RESULT / 'raw'
    assert len(names) == len(set(names)) == manifest['file_count'] == report['raw_files']
    assert {p.relative_to(raw_dir).as_posix() for p in raw_dir.rglob('*') if p.is_file()} == set(names)
    for row in rows:
        path = raw_dir / row['path']
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256']
    assert sum(row['bytes'] for row in rows) == manifest['bytes'] == report['raw_bytes']
    assert manifest['bytes'] < protocol['output_bytes_ceiling']
    for mapping in ('preserved_previous_source_sha256', 'source_sha256'):
        for name, expected in freeze[mapping].items():
            assert sha(ROOT / str(bounded_relative(name))) == expected, name
    assert sha(ROOT / freeze['protocol_path']) == sha(FIXTURE / 'protocol.json') == freeze['protocol_sha256']
    assert sha(ROOT / freeze['runtime_manifest_path']) == freeze['runtime_manifest_sha256']
    assert freeze['free_disk_bytes_at_freeze'] >= protocol['min_free_disk_bytes']
    pre_path = FIXTURE / 'pre-execution-review.json'
    assert sha(pre_path) == freeze['pre_execution_review_sha256']
    pre = load(pre_path)
    assert pre['status'] == 'passed_for_separate_freeze'
    assert pre['source_sha256'] == freeze['source_sha256']
    assert len(pre['reviews']) == 2
    for receipt in pre['reviews']:
        path = ROOT / str(bounded_relative(receipt['path']))
        assert sha(path) == receipt['sha256']
        review = load(path)
        assert review['status'] == 'passed_for_separate_freeze'
        assert review['source_sha256'] == freeze['source_sha256']

    raw = load(raw_dir / 'execution.json')
    assert raw['status'] == report['status'] == 'passed'
    assert raw['scientific_suites'] == report['scientific_suites'] == protocol['suites_permitted'] == 1
    assert raw['retries'] == report['retries'] == protocol['retries'] == 0
    assert raw['model_loads'] == report['model_loads'] == 0
    assert raw['freeze_sha256'] == sha(freeze_path) == report['freeze_sha256']
    assert datetime.fromisoformat(protocol['predeclared_at']) < datetime.fromisoformat(freeze['frozen_at']) < datetime.fromisoformat(raw['started_at'])
    assert finite_nonnegative(raw['elapsed_seconds']) < protocol['suite_wall_seconds']
    assert report['suite_wall_seconds'] == raw['elapsed_seconds']
    assert all(report[key] == raw[key] for key in ('started_at', 'completed_at', 'limits'))
    assert raw['limits'] == protocol['limits']
    assert report['execution_accepted'] is True
    order = protocol['workload']['arms_in_order']
    assert [arm['name'] for arm in order] == ['refuse', 'retry']
    assert [arm['name'] for arm in raw['arms']] == [arm['name'] for arm in report['arms']] == ['refuse', 'retry']
    processes = kills = reopens = 0
    for definition, arm, shown in zip(order, raw['arms'], report['arms']):
        assert arm['mode'] == shown['mode'] == definition['mode']
        assert arm['status'] == 'passed'
        directory = raw_dir / arm['name']
        assert load(directory / 'execution.json') == arm
        acceptance = audit_arm(directory, arm['mode'])
        assert acceptance == arm['acceptance']
        assert all(shown[key] == value for key, value in acceptance.items())
        assert shown['load_effects_per_offered'] == acceptance['load_effects'] / acceptance['unique_load_offered']
        assert shown['arm_wall_seconds_including_endpoint_audit'] == arm['elapsed_seconds']
        assert shown['process_stages_wall_seconds'] == arm['process_stages_wall_seconds']
        duration = finite_nonnegative(arm['elapsed_seconds'])
        assert duration > 0
        rate = acceptance['load_effects'] / duration
        assert arm['load_effects_per_arm_wall_second'] == shown['load_effects_per_arm_wall_second'] == rate
        assert len(arm['processes']) == protocol['acceptance']['native_processes_per_arm'] == 3
        assert len(arm['databases']) == protocol['workload']['databases_per_arm'] == 2
        samples = [sample for process in arm['processes'] for sample in process['memory_samples']]
        sinks = [load(directory / f'stage{stage}-sink.json') for stage in range(3)]
        snapshots = [load(directory / f'stage{stage}-snapshot.json') for stage in range(3)]
        assert shown['process_ids'] == [process['pid'] for process in arm['processes']]
        assert shown['returncodes'] == [process['returncode'] for process in arm['processes']]
        assert shown['max_sampled_private_bytes'] == max(sample['PrivateUsage'] for sample in samples)
        assert shown['max_queried_OS_working_set_highwater_bytes'] == max(sample['PeakWorkingSetSize'] for sample in samples)
        for field, key in [('sink_callback_ms', 'callback_ms'), ('sink_final_flush_ms', 'final_flush_ms'),
                           ('sink_events', 'events'), ('sink_bytes', 'bytes')]:
            assert shown[field] == sum(sink[key] for sink in sinks)
        assert shown['sqlite_main_bytes'] == sum((directory / f'service{service}.sqlite').stat().st_size for service in range(2))
        assert shown['raw_arm_bytes'] == sum(row['bytes'] for row in rows if row['path'].startswith(arm['name'] + '/'))
        assert shown['observed_maximum_attempts_per_load'] == max(
            entry['attempts'] for snapshot in snapshots for entry in snapshot['queue']['finished'])
        assert shown['retained_endpoint_document_sequences'] == [database['retained_document_sequences'] for database in arm['databases']]
        for process in arm['processes']:
            assert finite_nonnegative(process['elapsed_seconds']) < protocol['process_wall_seconds']
            assert process['memory_samples']
            for sample in process['memory_samples']:
                assert finite_nonnegative(sample['PrivateUsage']) < protocol['polled_process_private_bytes_ceiling']
                finite_nonnegative(sample['WorkingSetSize'])
                finite_nonnegative(sample['PeakWorkingSetSize'])
            processes += 1
            kills += int(process['forced_termination'])
        reopens += len(arm['processes']) - 1
    assert processes == report['native_process_starts'] == 6
    assert kills == report['forced_kills'] == 4
    assert reopens == report['reopens'] == 4
    review_path = RESULT / 'independent-outcome-review.json'
    assert sha(review_path) == report['independent_review_sha256']
    review = load(review_path)
    assert review['status'] == 'passed'
    assert review['suite_reported_status'] == raw['status']
    assert review['freeze_sha256'] == raw['freeze_sha256']
    assert review['raw_manifest_sha256'] == report['raw_manifest_sha256']
    assert review['raw_file_count'] == len(rows) and review['raw_bytes'] == manifest['bytes']
    assert review['original_raw_unchanged'] is True and review['native_executions'] == 0
    assert review['distinct_processes'] == processes and review['forced_kills_and_reopens'] == kills == reopens
    assert [arm['mode'] for arm in review['arms']] == ['refuse', 'retry']
    for original, independent in zip(raw['arms'], review['arms']):
        assert independent['independently_recomputed_acceptance'] == original['acceptance']
        assert independent['arm_wall_seconds'] == original['elapsed_seconds']
        assert independent['load_effects_per_arm_wall_second'] == original['load_effects_per_arm_wall_second']
    runtime_manifest = load(ROOT / freeze['runtime_manifest_path'])
    assert review['runtime_verified_files'] == len(runtime_manifest['files'])
    checks = {entry['label']: entry for entry in pre['preflight']['checks']}
    assert all(entry['exit_code'] == 0 for entry in checks.values())
    full = '\n'.join(checks['python-full-final']['tail'])
    count = int(re.search(r'Ran (\d+) tests', full).group(1))
    skipped = int(re.search(r'skipped=(\d+)', full).group(1))
    focused = '\n'.join(checks['python-focused-final']['tail'])
    node = '\n'.join(checks['node-controls-final']['tail'])
    validation = report['validation']
    assert validation['final_python_methods'] == count
    assert validation['final_python_passed'] == count - skipped and validation['final_python_skipped'] == skipped
    assert validation['final_focused_python'] == int(re.search(r'Ran (\d+) tests', focused).group(1))
    assert validation['final_pure_node_controls'] == int(re.search(r'tests (\d+)', node).group(1))
    assert report['H1_min_free_disk_bytes_unchanged'] == 5 * 1024**3
    assert report['H1_native_execution_started'] is False
    return {'record_verified': True, 'saved_suite_accepted': True, 'saved_arms': 2,
            'saved_process_starts': processes, 'saved_forced_kills_and_reopens': kills,
            'raw_files': len(rows), 'raw_bytes': manifest['bytes'],
            'checker_native_or_database_executions': 0}


if __name__ == '__main__':
    print(json.dumps(check()))
