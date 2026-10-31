"""Preserve the rejected Pi service attempt without Node, SQLite opens or execution."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / 'results/pi-durable-service-v1'
FIXTURE = ROOT / 'fixtures/pi-durable-service-v1'


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check():
    report = load(RESULT / 'report.json')
    frozen = load(FIXTURE / 'implementation.json')
    raw = load(RESULT / 'raw-manifest.json')['files']
    assert {p.name for p in (RESULT / 'raw').iterdir()} == {r['path'] for r in raw}
    for row in raw:
        path = RESULT / 'raw' / row['path']
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256']
    for name, expected in frozen['source_sha256'].items():
        assert sha(ROOT / name) == expected, name
    assert sha(FIXTURE / 'protocol.json') == frozen['protocol_sha256']
    assert sha(FIXTURE / 'runtime-manifest.json') == frozen['runtime_manifest_sha256']
    execution = load(RESULT / 'raw/execution.json')
    assert execution['freeze_sha256'] == sha(FIXTURE / 'implementation.json')
    assert execution['status'] == 'failed' and execution['scientific_suites'] == 1
    assert len(execution['processes']) == 1
    process = execution['processes'][0]
    assert process['stage'] == 0 and process['returncode'] == 1
    assert not process['forced_termination'] and not process.get('cleanup_forced', False)
    error = (RESULT / 'raw/stage0.stderr.txt').read_text(encoding='utf-8')
    assert "Cannot read properties of undefined (reading 'abortSignal')" in error
    assert 'at Object.open' in error and 'at openService' in error
    assert report['execution_accepted'] is False
    assert all(report[key] == 0 for key in ('forced_terminations', 'process_restarts',
        'admission_attempts', 'tasks_created', 'effects_committed', 'model_loads', 'retries'))
    assert report['stage0_workload_started'] is False
    assert report['remaining_stages_unexecuted'] == [1, 2]
    assert report['independent_review_sha256'] == sha(RESULT / 'independent-failure-preservation-review.json')
    return {'record_preserved': True, 'execution_accepted': False,
            'native_processes_in_saved_record': 1, 'saved_restarts': 0,
            'auditor_runtime_or_database_executions': 0}


if __name__ == '__main__':
    print(json.dumps(check()))
