"""Read-only independent outcome audit; no workers or scientific executions."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent
PRE = RUN / 'h2-paced-preflight'
RAW = RUN / 'h2-paced-native'
COPY = RUN / 'audit-copies/radar-paced'
sys.path.insert(0, str(ROOT))
from experiments.pi_durable_paced_audit import audit_arm

def load(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p, value): p.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
def inventory(directory):
    return {p.relative_to(directory).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
            for p in sorted(directory.rglob('*')) if p.is_file()}

suite = load(RAW / 'execution.json')
assert suite['status'] in ('passed', 'failed'), 'Wait for final suite outcome'
assert not COPY.exists(), 'Never overwrite independent audit copies'
before = inventory(RAW)
COPY.parent.mkdir(exist_ok=True)
shutil.copytree(RAW, COPY)
assert inventory(COPY) == before
report = {'reviewer': 'radar0401', 'started_at': datetime.now(timezone.utc).isoformat(),
          'status': 'reviewing', 'suite_reported_status': suite['status'], 'native_executions': 0,
          'sqlite_open_scope': 'Copied SQLite/WAL/SHM only, read-only URI; original bytes hashed before/after',
          'arms': [], 'raw_file_count': len(before), 'raw_bytes': sum(r['bytes'] for r in before.values())}
try:
    frozen_path = ROOT / 'fixtures/pi-durable-paced/implementation.json'
    frozen = load(frozen_path)
    assert suite['freeze_sha256'] == sha(frozen_path)
    assert suite['scientific_suites'] == 1 and suite['retries'] == suite['model_loads'] == 0
    own_review = load(PRE / 'independent-review-radar.json')
    assert frozen['source_sha256'] == own_review['source_sha256'] and len(frozen['source_sha256']) == 10
    for name, digest in {**frozen['preserved_previous_source_sha256'], **frozen['source_sha256']}.items():
        assert sha(ROOT / name) == digest, name
    assert sha(ROOT / frozen['protocol_path']) == frozen['protocol_sha256']
    assert sha(ROOT / 'fixtures/pi-durable-paced/protocol.json') == frozen['protocol_sha256']
    assert sha(ROOT / frozen['pre_execution_review_path']) == frozen['pre_execution_review_sha256']
    assert sha(Path(frozen['node'])) == frozen['node_sha256']
    manifest_path = ROOT / frozen['runtime_manifest_path']
    assert sha(manifest_path) == frozen['runtime_manifest_sha256']
    runtime = ROOT / frozen['runtime_directory']; manifest = load(manifest_path)
    actual = {p.relative_to(runtime).as_posix() for p in (runtime/'node_modules').rglob('*') if p.is_file()}
    actual.update(('package.json', 'package-lock.json'))
    assert actual == {r['path'] for r in manifest['files']}
    for row in manifest['files']: assert sha(runtime / row['path']) == row['sha256'], row['path']
    report['runtime_verified_files'] = len(manifest['files'])
    assert suite['status'] == 'passed', suite.get('error')
    assert [a['name'] for a in suite['arms']] == ['refuse', 'retry']
    pids = []
    for mode in ('refuse', 'retry'):
        directory = COPY / mode; execution = load(directory/'execution.json')
        identities = load(directory/'identities.json'); requests = identities['requests']
        assert len(requests) == len({r['id'] for r in requests}) == 50
        assert Counter(r['kind'] for r in requests) == {'load': 36, 'control': 14}
        snapshots = [load(directory/f'stage{s}-snapshot.json') for s in range(3)]
        events = [json.loads(line) for s in range(3) for line in (directory/f'stage{s}.jsonl').read_text(encoding='utf-8').splitlines()]
        processes = execution['processes']; pids.extend(p['pid'] for p in processes)
        assert len(processes) == 3
        assert [p['forced_termination'] for p in processes] == [True, True, False]
        assert [p['stage'] for p in processes] == [0, 1, 2]
        assert all(p['elapsed_seconds'] < 20 and p['memory_samples'] for p in processes)
        assert all(m['PrivateUsage'] < 268435456 for p in processes for m in p['memory_samples'])
        for service in range(2):
            with sqlite3.connect((directory/f'service{service}.sqlite').as_uri()+'?mode=ro', uri=True) as db:
                assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
                tasks = [json.loads(row[0]) for row in db.execute('SELECT record FROM tasks ORDER BY id')]
                convs = [json.loads(row[0]) for row in db.execute('SELECT record FROM conversations ORDER BY id')]
                docids = db.execute('SELECT id FROM documents WHERE kind=?', (json.dumps('frontier.service'),)).fetchall()
                assert len(docids) == 1
                revisions = db.execute('SELECT seq,content FROM document_revisions WHERE document_id=? ORDER BY seq', (docids[0][0],)).fetchall()
            endpoint = execution['databases'][service]; state = json.loads(revisions[-1][1])
            assert tasks == endpoint['tasks']
            assert [c['id'] for c in convs] == endpoint['conversation_ids']
            assert [r[0] for r in revisions] == endpoint['retained_document_sequences']
            assert state == endpoint['document'] == snapshots[-1]['states'][service]
            assert set(c['id'] for c in convs) == set(identities['conversations'][service]) and len(convs) == 2
            admitted = [r for r in requests if r['service']==service and r.get('taskId')]
            assert len(tasks) == len(admitted) and {t['id'] for t in tasks} == {r['taskId'] for r in admitted}
            taskmap = {t['id']:t for t in tasks}; expected_effects = {}
            for r in admitted:
                t = taskmap[r['taskId']]; cid = identities['conversations'][service][r['conversation']]
                assert t['conversationId'] == cid and t['state']['status'] == 'terminal'
                assert t['input'] == {'key':r['key'], 'payload':r['payload'], 'session':cid, 'version':r['stage']+1, 'hold':r['hold']}
                outcome = {'status':'aborted'} if r['intent'] in ('pre-abort','post-abort') else {'status':'completed','result':'denied' if r['intent']=='deny' else 'committed'}
                assert t['state']['outcome'] == identities['terminals'][f"{service}:{t['id']}"]['outcome'] == outcome
                if r['intent'] not in ('deny','pre-abort'): expected_effects[r['key']]={'count':1,'payload':r['payload']}
            assert state['effects'] == expected_effects and not state['active']
            for stage, snap in enumerate(snapshots):
                expected = {str(c):{'version':stage+1,'allowed':True} for c in identities['conversations'][service]}
                if stage == 0: expected[str(identities['conversations'][service][1])]={'version':99,'allowed':False}
                assert snap['states'][service]['authority'] == expected
        accepted = audit_arm(directory, mode)
        assert accepted == execution['acceptance']
        assert execution['load_effects_per_arm_wall_second'] == accepted['load_effects']/execution['elapsed_seconds']
        report['arms'].append({'mode':mode,'independently_recomputed_acceptance':accepted,
                              'arm_wall_seconds':execution['elapsed_seconds'],
                              'load_effects_per_arm_wall_second':execution['load_effects_per_arm_wall_second']})
    assert len(pids) == len(set(pids)) == 6
    assert sum(p['forced_termination'] for a in suite['arms'] for p in a['processes']) == 4
    assert report['raw_bytes'] < 20971520
    report.update(status='passed', freeze_sha256=sha(frozen_path), distinct_processes=6, forced_kills_and_reopens=4)
except Exception as error:
    report.update(status='failed', error=repr(error))
finally:
    after = inventory(RAW)
    report['original_raw_unchanged'] = before == after
    if before != after: report.update(status='failed', error='Original raw byte inventory changed during audit')
    raw_manifest = {'scope':'Complete native output union across root and both arms, including every SQLite/WAL/SHM present before audit',
                    'files': before, 'file_count':len(before), 'bytes':sum(r['bytes'] for r in before.values())}
    save(PRE/'raw-manifest.json', raw_manifest)
    report.update(completed_at=datetime.now(timezone.utc).isoformat(),raw_manifest_sha256=sha(PRE/'raw-manifest.json'))
    save(PRE/'independent-outcome-review.json', report)
    print(json.dumps({'status':report['status'],'path':str(PRE/'independent-outcome-review.json'),
                      'sha256':sha(PRE/'independent-outcome-review.json'),'error':report.get('error')}))
