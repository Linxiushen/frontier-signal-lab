"""Preserve the rejected native record without Node, SQLite opens or execution."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / 'results/pi-durable-service-v2'
FIXTURE = ROOT / 'fixtures/pi-durable-service-v2'


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check():
    report = load(RESULT / 'report.json')
    frozen = load(FIXTURE / 'implementation.json')
    manifest = load(RESULT / 'raw-manifest.json')
    assert sha(RESULT / 'raw-manifest.json') == report['raw_manifest_sha256']
    raw = manifest['files']
    assert {p.name for p in (RESULT / 'raw').iterdir()} == {r['path'] for r in raw}
    for row in raw:
        path = RESULT / 'raw' / row['path']
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256']
    for name, expected in {**frozen['source_sha256'], **frozen['preserved_v1_source_sha256']}.items():
        assert sha(ROOT / name) == expected, name
    assert sha(ROOT / frozen['protocol_path']) == frozen['protocol_sha256']
    assert sha(FIXTURE / 'protocol.json') == frozen['protocol_sha256']
    assert sha(ROOT / frozen['runtime_manifest_path']) == frozen['runtime_manifest_sha256']
    assert sha(FIXTURE / 'pre-execution-review.json') == frozen['pre_execution_review_sha256']
    execution = load(RESULT / 'raw/execution.json')
    assert execution['freeze_sha256'] == sha(FIXTURE / 'implementation.json') == report['freeze_sha256']
    assert execution['status'] == 'failed' and execution['scientific_suites'] == 1
    assert 'NoneType' in execution['error'] and report['execution_accepted'] is False
    processes = execution['processes']
    assert len(processes) == len({p['pid'] for p in processes}) == 3
    assert [p['stage'] for p in processes] == [0, 1, 2]
    assert [p['forced_termination'] for p in processes] == [True, True, False]
    assert [p['returncode'] for p in processes] == [1, 1, 0]
    counts = Counter()
    sequences = []
    for stage in range(3):
        ready = load(RESULT / f'raw/stage{stage}-ready.json')
        assert ready['pid'] == processes[stage]['pid'] and ready['stage'] == stage
        assert ready['effectCount'] == [1, 3, 4][stage]
        for line in (RESULT / f'raw/stage{stage}.jsonl').read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            if event['type'] == 'admission':
                counts[event['status']] += 1
            if event['type'] == 'committed-state':
                sequences.append(event['seq'])
                assert len(event['state']['active']) <= 2
    assert dict(counts) == {'admit': 6, 'overloaded': 1, 'duplicate': 3, 'unauthorized': 1, 'conflict': 1}
    assert len(sequences) == 20 and sequences == sorted(set(sequences)) and sequences[-1] == 31
    assert report['independent_review_sha256'] == sha(RESULT / 'independent-outcome-preservation-review.json')
    review = load(RESULT / 'independent-outcome-preservation-review.json')
    assert review['execution_accepted'] is False and review['raw_originals_unchanged']
    assert review['postoutcome_all_checks_true']
    return {'record_preserved': True, 'execution_accepted': False,
            'saved_processes': 3, 'saved_restarts': 2, 'saved_admission_calls': sum(counts.values()),
            'auditor_runtime_or_database_executions': 0}


if __name__ == '__main__':
    print(json.dumps(check()))
