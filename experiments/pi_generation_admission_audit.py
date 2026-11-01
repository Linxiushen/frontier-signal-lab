"""Saved-byte audit of actual native admission reconciliation; no execution."""
from collections import Counter
import hashlib
import json
import math
import re
from pathlib import Path
from experiments.pi_generation_v2_audit import validate_native_chain


def load(path): return json.loads(Path(path).read_bytes())


def read_endpoint(database):
    docs = database.execute('SELECT id FROM documents WHERE kind=?', (json.dumps('frontier.generation-admission-service'),)).fetchall()
    assert len(docs) == 1
    revisions = database.execute('SELECT seq,content FROM document_revisions WHERE document_id=? ORDER BY seq', (docs[0][0],)).fetchall()
    result = {'state': json.loads(revisions[-1][1]), 'document_sequences': [r[0] for r in revisions]}
    for table in ('tasks', 'entries', 'submissions', 'conversations'):
        result[table] = [json.loads(r[0]) for r in database.execute('SELECT record FROM ' + table + ' ORDER BY id')]
    assert database.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    return result


def audit(directory):
    d = Path(directory); ids = load(d/'identities.json'); requests = ids['requests']
    events = [json.loads(line) for stage in range(3) for line in (d/f'stage{stage}.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert len(requests) == 26 and len({(r['service'], r['key']) for r in requests}) == 26
    assert Counter(r['intent'] for r in requests) == {'recover':4,'deny':2,'pre-abort':2,'post-abort':2,'commit':6,'overload':6,'reserve-gap':2,'submit-gap':2}
    admitted = [r for r in requests if r['status'] == 'admit']; assert len(admitted) == 20
    assert len(ids['recovered']) == 8 and Counter(r['stage'] for r in ids['recovered']) == {1:4,2:4}
    expected = {}
    for service in range(2):
        for stage in range(3):
            for c in range(2):
                intent = ('recover' if c==0 else 'deny') if stage==0 else ('pre-abort' if c==0 else 'post-abort') if stage==1 else 'commit'
                expected[service,f's{stage}-db{service}-control{c}'] = (stage,ids['conversations'][service][c],intent)
            expected[service,f's{stage}-db{service}-overflow'] = (stage,ids['conversations'][service][0],'overload')
        expected[service,f's1-db{service}-recovery'] = (1,ids['conversations'][service][0],'recover')
        expected[service,f's0-db{service}-reserve-gap'] = (0,ids['conversations'][service][1],'reserve-gap')
        expected[service,f's1-db{service}-submit-gap'] = (1,ids['conversations'][service][1],'submit-gap')
        expected[service,f's2-db{service}-before-reserve'] = (2,ids['conversations'][service][0],'commit')
    assert {(r['service'],r['requestId']):(r['stage'],r['conversation'],r['intent']) for r in requests} == expected
    assert all(r['status']==('overloaded' if r['intent']=='overload' else 'admit') for r in requests)
    assert all(r['key']==f"{r['conversation']}:{r['requestId']}" and r['payload']=='payload-'+r['requestId'] and r['version']==r['stage']+1 for r in requests)
    assert not [e for e in events if e['type'] in ('network-access-denied','runtime-report')]
    identity = [e for e in events if e['type']=='provider-identity']; assert len(identity)==6
    apis = {(e['service'],e['stage']):e['api'] for e in identity}; assert len(apis)==6
    assert len({apis[0,g] for g in range(3)})==3 and all(re.fullmatch(r'faux:[0-9]+:[a-z0-9]+',apis[0,g]) for g in range(3))
    assert all(apis[1,g]=='frontier-faux-admission' for g in range(3))
    assert all((e['provider'],e['model'],e['mode'])==('faux','faux-1','default-dynamic' if e['service']==0 else 'configured-stable') for e in identity)
    providers = [e for e in events if e['type']=='provider-request']; assert len(providers)==20
    assert len({(e['service'],e['key']) for e in providers})==20
    by_key = {(r['service'],r['key']):r for r in admitted}
    assert {(e['service'],e['key']) for e in providers}==set(by_key)
    for e in providers:
        r=by_key[e['service'],e['key']]
        assert e['stage']==r['stage']+int(r['intent']=='reserve-gap') and e['api']==apis[e['service'],e['stage']]
        assert e['providerSession'] and 'frontier_effect' in e['offeredTools']
    faults = [e for e in events if e['type']=='admission-gap-held']
    assert Counter((e['stage'],e['phase']) for e in faults)=={(0,'after-link'):2,(0,'after-reserve'):2,(1,'after-link'):2,(1,'after-submit'):2}
    errors = [e for e in events if e['type']=='injected-before-reserve-error']
    assert len(errors)==2 and {(e['service'],e['key']) for e in errors}=={(r['service'],r['key']) for r in admitted if r['requestId'].endswith('before-reserve')}
    duplicates = [e for e in events if e['type']=='native-duplicate']; assert len(duplicates)==12
    expected_duplicates={(r['service'],r['key']) for r in admitted if '-control' in r['requestId']}
    assert {(e['service'],e['key']) for e in duplicates}==expected_duplicates
    assert all(e['stage']==by_key[e['service'],e['key']]['stage'] and e['submissionId']==by_key[e['service'],e['key']]['submissionId'] for e in duplicates)
    expected_recoveries={(r['stage']+1,r['service'],r['key'],r['submissionId'],r['intent']) for r in admitted if r['intent'] in ('recover','reserve-gap','submit-gap')}
    assert {(x['stage'],x['service'],x['key'],x['submissionId'],x['intent']) for x in ids['recovered']}==expected_recoveries
    before_resume=[e for e in events if e['type']=='recovery-before-resume']
    assert len(before_resume)==8
    assert {(e['stage'],e['service'],e['key']) for e in before_resume}=={x[:3] for x in expected_recoveries}
    for e in before_resume:
        assert e['state']==load(d/f"service{e['service']}-stage{e['stage']-1}-endpoint.json")['state']
    execution=load(d/'execution.json'); processes=execution['processes']
    assert len(processes)==len({p['pid'] for p in processes})==3
    assert [p['stage'] for p in processes]==[0,1,2] and [p['forced_termination'] for p in processes]==[True,True,False]
    for g in range(3):
        ready=load(d/f'stage{g}-ready.json'); sink=load(d/f'stage{g}-sink.json'); rows=[e for e in events if e['stage']==g]
        assert ready['pid']==processes[g]['pid'] and ready['stage']==g and ready['held']==(4 if g<2 else 0) and ready['closed']==(g==2)
        assert rows and all(e['pid']==ready['pid'] for e in rows)
        assert sink['events']==len(rows) and sink['bytes']==(d/f'stage{g}.jsonl').stat().st_size
        assert all(math.isfinite(sink[k]) and sink[k]>=0 for k in ('callback_ms','flush_ms'))
    for service in range(2):
        own=[r for r in admitted if r['service']==service]
        final=load(d/f'service{service}-stage2-endpoint.json'); state=final['state']
        assert len(final['conversations'])==2 and {c['id'] for c in final['conversations']}==set(ids['conversations'][service])
        assert len(final['submissions'])==10 and len(final['tasks'])==20
        assert Counter(t['kind'] for t in final['tasks'])=={'pi.generation':10,'pi.tool':10}
        assert all(t['state']['status']=='terminal' for t in final['tasks'])
        assert Counter(t['state']['outcome']['status'] for t in final['tasks'])=={'completed':16,'aborted':4}
        assert Counter(e['kind'] for e in final['entries'])['pi.user']==10
        assert not state['active'] and state['capacity']==2 and len(state['effects'])==8
        assert state['authority']=={str(c):{'version':3,'allowed':True} for c in ids['conversations'][service]}
        assert set(state['requests'])=={r['key'] for r in own}
        assert {s['id'] for s in final['submissions']}=={r['submissionId'] for r in own}
        all_chain=[]
        for r in own:
            stored=state['requests'][r['key']]
            target={'fingerprint':hashlib.sha256(r['payload'].encode()).hexdigest(),'conversation':r['conversation'],'requestId':r['requestId'],'payload':r['payload'],'version':r['version'],'submissionId':r['submissionId'],'terminal':r['terminal']}
            if r['intent'] in ('pre-abort','post-abort'): target['cancelled']=True
            assert stored==target
            effect=None if r['intent'] in ('deny','pre-abort') else {'count':1,'payload':r['payload']}
            assert state['effects'].get(r['key'])==effect
            enters=[e for e in events if e['type']=='tool-enter' and e['service']==service and e['key']==r['key']]
            assert len(enters)==(2 if r['intent'] in ('recover','submit-gap') else 1)
            proxy={**r,'intent':'recover' if r['intent']=='submit-gap' else 'commit' if r['intent']=='reserve-gap' else r['intent']}
            original_api=apis[service,r['stage']+int(r['intent']=='reserve-gap')]
            all_chain.extend(validate_native_chain(proxy,final,enters,expected_api=original_api))
            effects=[e['decision'] for e in events if e['type']=='tool-effect' and e['service']==service and e['key']==r['key']]
            assert effects==([] if r['intent']=='pre-abort' else ['denied'] if r['intent']=='deny' else ['commit','existing'] if r['intent'] in ('recover','submit-gap') else ['commit'])
        assert len(all_chain)==len(set(all_chain))==20
        for g in (0,1):
            endpoint=load(d/f'service{service}-stage{g}-endpoint.json'); held=load(d/f'stage{g}-snapshot.json')['held']; st=endpoint['state']
            assert st==load(d/f'stage{g}-snapshot.json')['states'][service]
            assert st['authority']=={str(c):{'version':g+1,'allowed':True} for c in ids['conversations'][service]}
            mine=[r for r in held if r['service']==service]; assert len(mine)==2
            assert st['active']=={r['key']:True for r in mine}
            assert len(st['requests'])==(3 if g==0 else 7) and len(endpoint['submissions'])==(2 if g==0 else 7)
            assert len(endpoint['tasks'])==2*len(endpoint['submissions'])
            for r in mine:
                host=st['requests'][r['key']]
                native=[n for n in endpoint['submissions'] if n.get('requestId')==r['requestId'] and n['conversationId']==r['conversation']]
                validate_gap_snapshot(r,host,native,st['effects'])
                if r['intent']!='reserve-gap':
                    final_r=by_key[service,r['key']]
                    enters=[e for e in events if e['type']=='tool-enter' and e['service']==service and e['key']==r['key'] and e['stage']==g]
                    validate_native_chain({**final_r,'intent':'recover'},endpoint,enters,False,expected_api=apis[service,g])
            assert all(t['id'] in {x['id'] for x in final['tasks']} for t in endpoint['tasks'])
        publications=[e for e in events if e['type']=='committed-state' and e['service']==service]
        assert publications and [p['seq'] for p in publications]==sorted({p['seq'] for p in publications})
        assert publications[-1]['state']==state and publications[-1]['seq']==final['document_sequences'][-1]
        assert all(len(p['state']['active'])<=2 for p in publications)
        assert max(len(p['state']['active']) for p in publications)==2
    terminal=[e for e in events if e['type']=='terminal']; assert len(terminal)==20
    assert {(e['service'],e['key']) for e in terminal}==set(by_key)
    assert all(e['submission']==by_key[e['service'],e['key']]['terminal'] for e in terminal)
    latencies=sorted(e['epoch_ms']-by_key[e['service'],e['key']]['offered_epoch_ms'] for e in terminal)
    assert all(x>=0 for x in latencies)
    return {'arrivals':26,'admitted':20,'overloaded':6,'native_generation_tasks':20,'native_tool_tasks':20,'faux_provider_calls':20,'local_effects':16,'recovered_reservations':8,'after_reserve_kills':2,'after_submit_kills':2,'after_link_kills':4,'before_reserve_errors':2,'maximum_active_per_session':2,'final_active':0,'terminal_latency_ms':{'n':20,**{f'p{p}':latencies[math.ceil(20*p/100)-1] for p in (50,95,99)}}}


def validate_gap_snapshot(request, host, natives, effects):
    key = request['key']
    assert host['conversation'] == request['conversation'] and host['requestId'] == request['requestId']
    assert host['payload'] == request['payload'] and host['version'] == request['version']
    assert host['fingerprint'] == hashlib.sha256(request['payload'].encode()).hexdigest()
    assert 'terminal' not in host and not host.get('cancelled')
    if request['intent'] == 'reserve-gap':
        assert 'submissionId' not in host and not natives and key not in effects
    else:
        assert len(natives) == 1 and natives[0]['id'] == request['submissionId']
        assert natives[0]['conversationId'] == request['conversation'] and natives[0]['requestId'] == request['requestId']
        assert effects[key] == {'count': 1, 'payload': request['payload']}
        if request['intent'] == 'submit-gap': assert 'submissionId' not in host
        else: assert host['submissionId'] == request['submissionId']
