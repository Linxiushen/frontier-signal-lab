"""Audit saved native evidence without Node, database opens or runtime execution."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / 'results/pi-durable-service-v3'
FIXTURE = ROOT / 'fixtures/pi-durable-service-v3'


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check():
    report = load(RESULT / 'report.json')
    frozen = load(FIXTURE / 'implementation.json')
    manifest = load(RESULT / 'raw-manifest.json')
    assert sha(RESULT / 'raw-manifest.json') == report['raw_manifest_sha256']
    assert {p.name for p in (RESULT / 'raw').iterdir()} == {r['path'] for r in manifest['files']}
    for row in manifest['files']:
        path = RESULT / 'raw' / row['path']
        assert path.stat().st_size == row['bytes'] and sha(path) == row['sha256']
    for name, expected in {**frozen['source_sha256'], **frozen['preserved_v2_source_sha256'],
                           **frozen['preserved_v1_source_sha256']}.items():
        assert sha(ROOT / name) == expected, name
    assert sha(ROOT / frozen['protocol_path']) == frozen['protocol_sha256']
    assert sha(FIXTURE / 'protocol.json') == frozen['protocol_sha256']
    assert sha(ROOT / frozen['runtime_manifest_path']) == frozen['runtime_manifest_sha256']
    assert sha(FIXTURE / 'pre-execution-review.json') == frozen['pre_execution_review_sha256']
    execution = load(RESULT / 'raw/execution.json')
    assert execution['freeze_sha256'] == sha(FIXTURE / 'implementation.json') == report['freeze_sha256']
    assert execution['status'] == 'passed' and execution['scientific_suites'] == 1
    assert report['execution_accepted'] is True and report['retries'] == 0
    processes = execution['processes']
    assert len(processes) == len({p['pid'] for p in processes}) == 3
    assert [p['stage'] for p in processes] == [0, 1, 2]
    assert [p['forced_termination'] for p in processes] == [True, True, False]
    assert [p['returncode'] for p in processes] == [1, 1, 0]
    protocol = load(FIXTURE / 'protocol.json')
    assert all(p['elapsed_seconds'] < protocol['process_wall_seconds'] for p in processes)
    assert all(m['PrivateUsage'] < protocol['polled_process_private_bytes_ceiling']
               for p in processes for m in p['memory_samples'])
    counts, sequences, states = Counter(), [], []
    for stage in range(3):
        ready = load(RESULT / f'raw/stage{stage}-ready.json')
        assert ready['pid'] == processes[stage]['pid'] and ready['stage'] == stage
        assert ready['effectCount'] == [1, 3, 4][stage]
        for line in (RESULT / f'raw/stage{stage}.jsonl').read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            assert event['pid'] == processes[stage]['pid']
            assert event['type'] not in ('runtime-report', 'provider-access-denied', 'network-access-denied')
            if event['type'] == 'admission':
                counts[event['status']] += 1
            if event['type'] == 'committed-state':
                sequences.append(event['seq'])
                states.append(event['state'])
    assert dict(counts) == {'admit': 6, 'overloaded': 1, 'duplicate': 3, 'unauthorized': 1, 'conflict': 1}
    assert sequences and sequences == sorted(set(sequences))
    assert max(len(s['active']) for s in states) == 2
    assert all(len(s['active']) <= 2 for s in states)
    acceptance = execution['acceptance']
    final = load(RESULT / 'raw/stage2-snapshot.json')['state']
    assert states[-1] == final == acceptance['final_document']
    assert sequences == acceptance['observed_document_sequences']
    assert sequences[-1] == acceptance['retained_document_sequences'][-1]
    assert acceptance['sqlite_integrity'] == 'ok'
    assert len(final['requests']) == 6 and not final['active'] and len(final['effects']) == 4
    assert len(final['denied']) == len(final['cancelled']) == 1
    assert not set(final['denied'] + final['cancelled']) & set(final['effects'])
    identities = load(RESULT / 'raw/identities-final.json')
    tasks = {t['id']: t for t in acceptance['native_tasks']}
    assert len(tasks) == 6 and set(tasks) == {r['taskId'] for r in final['requests'].values()}
    assert all(t['state']['status'] == 'terminal' for t in tasks.values())
    for name in ('one', 'two', 'progress', 'final'):
        identity = identities[name]
        assert tasks[identity['taskId']]['state']['outcome'] == {'status': 'completed', 'result': 'committed'}
        assert final['effects'][identity['key']] == {'count': 1, 'payload': 'effect-' + name}
    assert tasks[identities['denied']['taskId']]['state']['outcome'] == {'status': 'completed', 'result': 'denied'}
    assert tasks[identities['cancelled']['taskId']]['state']['outcome'] == {'status': 'aborted'}
    assert report['independent_review_sha256'] == sha(RESULT / 'independent-outcome-review.json')
    review = load(RESULT / 'independent-outcome-review.json')
    assert review['status'] == 'passed' and review['all_source_hashes_match']
    assert review['original_raw_files_unchanged'] == len(manifest['files'])
    assert review['freeze_sha256'] == execution['freeze_sha256']
    assert review['admissions'] == dict(counts) and review['effects'] == final['effects']
    return {'record_verified': True, 'saved_frozen_execution_accepted': True,
            'saved_processes': 3, 'saved_restarts': 2, 'saved_admission_calls': sum(counts.values()),
            'saved_local_effects': 4, 'auditor_runtime_or_database_executions': 0}


if __name__ == '__main__':
    print(json.dumps(check()))
