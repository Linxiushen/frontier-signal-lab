"""Post-outcome byte/SQLite observations. NEVER accepts or reruns the failed freeze."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import traceback

ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parent
RAW = RUN / 'h2-generation-native'
COPY = RUN / 'audit-copies/radar-generation'
OUT = RUN / 'h2-generation-preflight'
def load(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def save(path, data): path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
original = load(OUT / 'raw-manifest-radar.json')
def raw_unchanged():
    return ({p.relative_to(RAW).as_posix() for p in RAW.rglob('*') if p.is_file()} == {r['path'] for r in original['files']}
            and all(sha(RAW/r['path']) == r['sha256'] and (RAW/r['path']).stat().st_size == r['bytes'] for r in original['files']))
assert raw_unchanged()
report = {'status': 'observing', 'frozen_execution_status': 'failed', 'execution_accepted': False,
          'native_executions': 0, 'native_retries': 0, 'started_at': datetime.now(timezone.utc).isoformat(),
          'sqlite_scope': 'Only private audit-copies/radar-generation, read-only URI; original manifest saved before copy/read',
          'raw_file_count': len(original['files']), 'raw_bytes': original['bytes'], 'endpoints': []}
try:
    frozen_path = ROOT / 'fixtures/pi-generation/implementation.json'; frozen = load(frozen_path)
    execution = load(COPY / 'execution.json')
    assert execution['status'] == 'failed' and execution['freeze_sha256'] == sha(frozen_path)
    assert execution['scientific_suites'] == 1 and execution['retries'] == execution['model_loads'] == 0
    assert len(frozen['source_sha256']) == 11 and len(frozen['preserved_previous_source_sha256']) == 27
    for group in ('source_sha256', 'preserved_previous_source_sha256'):
        for name, digest in frozen[group].items(): assert sha(ROOT/name) == digest, name
    assert sha(ROOT/frozen['protocol_path']) == frozen['protocol_sha256']
    assert sha(ROOT/frozen['pre_execution_review_path']) == frozen['pre_execution_review_sha256']
    assert sha(Path(frozen['node'])) == frozen['node_sha256']
    manifest_path = ROOT/frozen['runtime_manifest_path']; assert sha(manifest_path) == frozen['runtime_manifest_sha256']
    runtime_manifest = load(manifest_path); runtime = ROOT/frozen['runtime_directory']
    actual_runtime = {p.relative_to(runtime).as_posix() for p in (runtime/'node_modules').rglob('*') if p.is_file()}
    actual_runtime.update(('package.json', 'package-lock.json'))
    assert actual_runtime == {r['path'] for r in runtime_manifest['files']}
    for row in runtime_manifest['files']:
        assert sha(runtime/row['path']) == row['sha256'] and (runtime/row['path']).stat().st_size == row['bytes']
    report['verified_source_counts'] = {'new': 11, 'preserved_prior': 27, 'runtime_files': len(runtime_manifest['files'])}
    report['freeze_sha256'] = sha(frozen_path)
    processes = execution['processes']; assert len(processes) == len({p['pid'] for p in processes}) == 3
    assert [p['forced_termination'] for p in processes] == [True, True, False]
    assert [p['stage'] for p in processes] == [0, 1, 2]
    assert all(p['returncode'] != 0 for p in processes[:2]) and processes[2]['returncode'] == 0
    assert all(p['elapsed_seconds'] < 20 and p['memory_samples'] for p in processes)
    assert all(s['PrivateUsage'] < 268435456 for p in processes for s in p['memory_samples'])
    report['processes'] = [{'pid':p['pid'], 'stage':p['stage'], 'returncode':p['returncode'],
                            'forced_termination':p['forced_termination'], 'elapsed_seconds':p['elapsed_seconds'],
                            'stderr_bytes':(COPY/f"stage{p['stage']}.stderr.txt").stat().st_size,
                            'stderr_sha256':sha(COPY/f"stage{p['stage']}.stderr.txt")} for p in processes]
    identities = load(COPY/'identities.json'); requests = identities['requests']
    assert len(requests) == 20 and Counter(r['status'] for r in requests) == {'admit':14,'overloaded':6}
    events = [json.loads(line) for stage in range(3) for line in (COPY/f'stage{stage}.jsonl').read_text(encoding='utf8').splitlines()]
    api_by_service_stage = {}; task_outcomes = Counter(); kinds = Counter(); effects = 0
    for service in range(2):
        for stage in range(3):
            path = COPY/f'service{service}-stage{stage}.sqlite'
            with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
                assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
                dids = db.execute('SELECT id FROM documents WHERE kind=?',(json.dumps('frontier.generation-service'),)).fetchall()
                assert len(dids) == 1
                revisions = db.execute('SELECT seq,content FROM document_revisions WHERE document_id=? ORDER BY seq',(dids[0][0],)).fetchall()
                endpoint = {'state':json.loads(revisions[-1][1]), 'document_sequences':[r[0] for r in revisions]}
                for table in ('tasks','entries','submissions','conversations'):
                    endpoint[table] = [json.loads(r[0]) for r in db.execute('SELECT record FROM '+table+' ORDER BY id')]
            assert endpoint == load(COPY/f'service{service}-stage{stage}-endpoint.json')
            assert endpoint['state'] == load(COPY/f'stage{stage}-snapshot.json')['states'][service]
            for entry in endpoint['entries']:
                if entry['kind'] != 'pi.assistant': continue
                message = entry['model'][0]
                assert re.fullmatch(r'faux:\d+:[a-z0-9]+', message['api'])
                assert (message['provider'],message['model'],message['stopReason']) == ('faux','faux-1','toolUse')
            if stage == 2:
                own = [r for r in requests if r['service'] == service and r['status']=='admit']
                assert len(own) == len(endpoint['submissions']) == 7
                tasks = {t['id']:t for t in endpoint['tasks']}; assert len(tasks)==14
                for t in tasks.values():
                    assert t['state']['status']=='terminal'; kinds[t['kind']]+=1;task_outcomes[t['state']['outcome']['status']]+=1
                expected = {r['key']:{'count':1,'payload':r['payload']} for r in own if r['intent'] not in ('deny','pre-abort')}
                assert endpoint['state']['effects'] == expected and not endpoint['state']['active'];effects+=len(expected)
                assert endpoint['state']['authority'] == {str(c):{'version':3,'allowed':True} for c in identities['conversations'][service]}
                for r in own:
                    enter = next(e for e in events if e['type']=='tool-enter' and e['service']==service and e['key']==r['key'])
                    tool = tasks[enter['taskId']]; assistant = next(e for e in endpoint['entries'] if e['id']==tool['input']['assistant'])
                    api = assistant['model'][0]['api']; api_by_service_stage.setdefault(f'{service}:{r["stage"]}',set()).add(api)
            report['endpoints'].append({'service':service,'stage':stage,'backup_sha256':sha(path),'full_saved_endpoint_matches':True,
                'tasks':len(endpoint['tasks']),'submissions':len(endpoint['submissions']),'effects':len(endpoint['state']['effects'])})
    assert all(len(v)==1 for v in api_by_service_stage.values()) and len(api_by_service_stage)==6
    assert len(set(next(iter(v)) for v in api_by_service_stage.values()))==6
    report['actual_faux_api_by_service_stage']={k:next(iter(v)) for k,v in api_by_service_stage.items()}
    report['native_observation']={'arrivals':20,'admitted':14,'overloaded':6,'task_kinds':dict(kinds),'terminal_outcomes':dict(task_outcomes),
        'effects':effects,'event_counts':dict(Counter(e['type'] for e in events)),
        'same_tool_id_recoveries':len(identities['recovered'])}
    assert kinds=={'pi.generation':14,'pi.tool':14} and task_outcomes=={'completed':20,'aborted':8} and effects==10
    # Post-outcome observation only: adapt exactly one known wrong frozen schema assertion in memory.
    # This does NOT change any frozen file, re-accept the freeze, or constitute another native attempt.
    source_path=ROOT/'experiments/pi_generation_audit.py'; source=source_path.read_text(encoding='utf8')
    old="assert (message['api'], message['provider'], message['model'], message['stopReason']) == ('faux', 'faux', 'faux-1', 'toolUse')"
    new="assert message['api'].startswith('faux:') and (message['provider'], message['model'], message['stopReason']) == ('faux', 'faux-1', 'toolUse')"
    assert source.count(old)==1
    namespace={'__name__':'post_outcome_observation_only','__file__':str(source_path)}
    exec(compile(source.replace(old,new),'<post-outcome-observation-only>','exec'),namespace)
    report['post_outcome_single_assertion_adaptation']={'frozen_source_sha256':sha(source_path),'old':old,'new':new,
        'interpretation':'Saved-record observation with only API assertion changed in memory; all other frozen assertions replayed. This is not frozen acceptance.'}
    try:
        report['post_outcome_replayed_observations']=namespace['audit'](COPY)
        report['remaining_frozen_assertions_observed']='passed_with_one_explicit_post_outcome_schema_adaptation'
    except BaseException:
        text=traceback.format_exc();(OUT/'additional-observation-failure-radar.txt').write_text(text,encoding='utf8')
        report['remaining_frozen_assertions_observed']='failed_after_single_schema_adaptation';report['additional_failure']=text
    report.update(status='failure_preserved_and_saved_observations_recorded',frozen_failure_line='experiments/pi_generation_audit.py:58',
                  failure_cause='Auditor incorrectly requires message.api=faux. Official fauxProvider defaults to a unique faux:<epoch>:<random> API and rewrites returned AssistantMessage.api via cloneMessage.',
                  suite_seconds=execution['elapsed_seconds'])
except BaseException:
    report.update(status='independent_observation_failed',error=traceback.format_exc())
finally:
    report['original_raw_unchanged']=raw_unchanged()
    if not report['original_raw_unchanged']: report.update(status='original_raw_changed')
    report['completed_at']=datetime.now(timezone.utc).isoformat()
    report['raw_manifest_sha256']=sha(OUT/'raw-manifest-radar.json')
    report['frozen_failure_trace_sha256']=sha(OUT/'frozen-audit-failure-radar.txt')
    save(OUT/'independent-outcome-review-radar.json',report)
    print(json.dumps({'status':report['status'],'sha256':sha(OUT/'independent-outcome-review-radar.json'),
        'additional_failure':report.get('additional_failure'),'error':report.get('error')}))
