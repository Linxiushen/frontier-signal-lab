"""Verify archived bounded-load evidence; never open SQLite or execute Node."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.pi_durable_load_audit import audit_arm, load

RESULT = ROOT / 'results/pi-durable-load'
FIXTURE = ROOT / 'fixtures/pi-durable-load'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check():
    report = load(RESULT / 'report.json')
    freeze = load(FIXTURE / 'implementation.json')
    protocol = load(FIXTURE / 'protocol.json')
    manifest = load(RESULT / 'raw-manifest.json')
    assert sha(RESULT / 'raw-manifest.json') == report['raw_manifest_sha256']
    assert {p.relative_to(RESULT / 'raw').as_posix() for p in (RESULT / 'raw').rglob('*') if p.is_file()} == {r['path'] for r in manifest['files']}
    for row in manifest['files']:
        path = RESULT / 'raw' / row['path']
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256']
    for name, expected in {**freeze['preserved_previous_source_sha256'], **freeze['source_sha256']}.items():
        assert sha(ROOT / name) == expected, name
    assert sha(ROOT / freeze['protocol_path']) == sha(FIXTURE / 'protocol.json') == freeze['protocol_sha256']
    assert sha(FIXTURE / 'pre-execution-review.json') == freeze['pre_execution_review_sha256']
    assert sha(ROOT / freeze['runtime_manifest_path']) == freeze['runtime_manifest_sha256']
    raw = load(RESULT / 'raw/execution.json')
    assert raw['status'] == 'passed' and raw['scientific_suites'] == 1 and raw['retries'] == 0 and raw['model_loads'] == 0
    assert raw['freeze_sha256'] == sha(FIXTURE / 'implementation.json') == report['freeze_sha256']
    assert raw['elapsed_seconds'] < protocol['suite_wall_seconds']
    assert report['execution_accepted'] and len(raw['arms']) == 4
    assert [a['name'] for a in raw['arms']] == [a['name'] for a in protocol['workload']['arms_in_order']]
    for arm in raw['arms']:
        assert arm['status'] == 'passed'
        directory = RESULT / 'raw' / arm['name']
        result = audit_arm(directory, arm['capacity'])
        assert result == arm['acceptance']
        assert load(directory / 'execution.json')['acceptance'] == result
        for process in arm['processes']:
            assert process['elapsed_seconds'] < protocol['process_wall_seconds']
            assert all(m['PrivateUsage'] < protocol['polled_process_private_bytes_ceiling'] for m in process['memory_samples'])
        assert arm['database']['retained_document_sequences'][-1] == result['document_sequences'][-1]
    review = load(RESULT / 'independent-outcome-review.json')
    assert sha(RESULT / 'independent-outcome-review.json') == report['independent_review_sha256']
    assert review['status'] == 'passed'
    assert review['freeze_sha256'] == raw['freeze_sha256']
    assert review['raw_manifest_sha256'] == report['raw_manifest_sha256']
    assert review['all_source_hashes_match'] and review['original_raw_files_unchanged'] == len(manifest['files'])
    assert review['original_raw_bytes'] == manifest['total_bytes']
    assert review['total_processes'] == 12 and review['total_forced_kills'] == review['total_reopens'] == 8
    assert review['same_capacity_sink_logical_outcomes_match']
    assert manifest['total_bytes'] < protocol['output_bytes_ceiling']
    return {'record_verified': True, 'saved_suite_accepted': True, 'saved_arms': 4,
            'saved_process_starts': 12, 'saved_forced_kills_and_reopens': 8,
            'checker_native_or_database_executions': 0}


if __name__ == '__main__':
    print(json.dumps(check()))
