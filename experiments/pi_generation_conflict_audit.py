"""Saved-record acceptance for one finite native error/collision caller; no execution."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from experiments.pi_generation_admission_audit import read_endpoint
from experiments.pi_generation_v2_audit import validate_native_chain


def load(path):
    return json.loads(Path(path).read_bytes())


def validate_host(request, host):
    expected = {k: request[k] for k in ('conversation', 'requestId', 'payload', 'version')}
    expected['fingerprint'] = hashlib.sha256(request['payload'].encode()).hexdigest()
    if request['intent'] in ('pre-abort', 'post-abort', 'busy-cancel', 'content-collision'):
        expected['cancelled'] = True
    if 'submissionId' in request:
        expected['submissionId'] = request['submissionId']
    if 'terminal' in request:
        expected['terminal'] = request['terminal']
    assert host == expected, 'Exact original host identity, intent, native link and disposition'


def validate_event_stage(type_, event, request):
    expected = (2 if request['intent'] in ('post-abort', 'commit') else 1) if type_ == 'terminal' else request['stage']
    assert event['stage'] == expected, 'Exact lifecycle event stage'


def audit(directory):
    d = Path(directory)
    ids = load(d / 'identities.json'); requests = ids['requests']; native = ids['native']
    events = [json.loads(line) for stage in range(3) for line in
              (d / f'stage{stage}.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert len(requests) == 18 and len({(r['service'], r['key']) for r in requests}) == 18
    expected = {}
    for s in range(2):
        assert len(ids['conversations'][s]) == len(set(ids['conversations'][s])) == 2
        for stage, c, intent in [(0, 0, 'pre-abort'), (0, 0, 'busy-deny' if s == 0 else 'busy-cancel'),
                                 (0, 1, 'overload'), (1, 0, 'type-collision'), (1, 1, 'content-collision'),
                                 (1, 0, 'post-abort'), (2, 0, 'commit'), (2, 1, 'commit'), (2, 0, 'overload')]:
            expected[s, f's{stage}-db{s}-{intent}-{c}'] = (stage, ids['conversations'][s][c], intent)
    assert {(r['service'], r['requestId']): (r['stage'], r['conversation'], r['intent']) for r in requests} == expected
    assert all(r['key'] == f"{r['conversation']}:{r['requestId']}" and r['payload'] == 'payload-' + r['requestId']
               and r['version'] == r['stage'] + 1 and r['status'] == ('overloaded' if r['intent'] == 'overload'
                   else 'reserved-error' if r['intent'].startswith('busy-') else 'admit') for r in requests)
    admitted = [r for r in requests if r['intent'] != 'overload']; by_key = {(r['service'], r['key']): r for r in admitted}
    assert len(admitted) == 14 and len(native) == 10
    assert len({(r['service'], r['submissionId']) for r in native}) == 10
    assert not [e for e in events if e['type'] in ('network-access-denied', 'runtime-report')]
    identity = [e for e in events if e['type'] == 'provider-identity']; assert len(identity) == 6
    apis = {(e['service'], e['stage']): e['api'] for e in identity}; assert len(apis) == 6
    assert len({apis[0, g] for g in range(3)}) == 3
    assert all(re.fullmatch(r'faux:[0-9]+:[a-z0-9]+', apis[0, g]) for g in range(3))
    assert all(apis[1, g] == 'frontier-faux-conflict' for g in range(3))
    assert all((e['provider'], e['model'], e['mode']) == ('faux', 'faux-1',
        'default-dynamic' if e['service'] == 0 else 'configured-stable') for e in identity)
    expected_events = {
        'native-busy': [r for r in admitted if r['intent'].startswith('busy-')],
        'native-type-error': [r for r in admitted if r['intent'] == 'type-collision'],
        'native-content-reuse': [r for r in admitted if r['intent'] == 'content-collision'],
        'fixture-native-dispose': [r for r in admitted if r['intent'] == 'content-collision'],
        'native-identity-conflict': [r for r in admitted if r['intent'].endswith('collision')],
        'reservation-held': [r for r in admitted if r['intent'].endswith('collision')],
        'cancel-mark-held': [r for r in admitted if r['intent'] in ('pre-abort', 'post-abort', 'busy-cancel')],
        'provider-request': native, 'tool-enter': native,
        'tool-effect': [r for r in native if r['intent'] in ('post-abort', 'commit')], 'terminal': admitted}
    for type_, rows in expected_events.items():
        own = [e for e in events if e['type'] == type_]
        assert len(own) == len(rows) and {(e['service'], e['key']) for e in own} == {(r['service'], r['key']) for r in rows}, type_
        for e in own:
            validate_event_stage(type_, e, by_key[e['service'], e['key']])
    for e in [e for e in events if e['type'] == 'native-busy']:
        assert e['name'] == 'ConversationBusy' and e['message'] == f"Conversation {by_key[e['service'], e['key']]['conversation']} is busy"
    for e in [e for e in events if e['type'] == 'native-identity-conflict']:
        assert {k: e[k] for k in ('status', 'nativeSubmissionId', 'nativeType')} == by_key[e['service'], e['key']]['terminal']
    for e in [e for e in events if e['type'] == 'cancel-mark-held']:
        assert e['phase'] == 'after-cancel-mark'
    for e in [e for e in events if e['type'] == 'native-type-error']:
        r = by_key[e['service'], e['key']]
        assert e['name'] == 'Error' and e['message'] == f"Request {r['requestId']} already identifies a submission of type write"
        assert e['submissionId'] == r['nativeSubmissionId']
    for e in [e for e in events if e['type'] == 'native-content-reuse']:
        assert e['before'] == e['after'] and e['after']['status'] == 'placed'
        assert e['submissionId'] == e['after']['id'] == by_key[e['service'], e['key']]['nativeSubmissionId']
    for e in [e for e in events if e['type'] == 'fixture-native-dispose']:
        original = next(r for r in native if r['service'] == e['service'] and r['key'] == e['key'])
        assert e['submissionId'] == original['submissionId'] and e['terminal'] == original['terminal']
    for e in [e for e in events if e['type'] == 'provider-request']:
        assert e['api'] == apis[e['service'], e['stage']] and e['providerSession'] and 'frontier_effect' in e['offeredTools']
    recovery = {(r['stage'] + 1, r['service'], r['key']) for r in admitted
                if r['intent'] in ('pre-abort', 'post-abort', 'busy-deny', 'busy-cancel')}
    assert len(ids['recovered']) == 6 and {(r['stage'], r['service'], r['key']) for r in ids['recovered']} == recovery
    for r in ids['recovered']:
        assert r.get('submissionId') == by_key[r['service'], r['key']].get('submissionId')
    before = [e for e in events if e['type'] == 'recovery-before-resume']
    assert len(before) == 6 and {(e['stage'], e['service'], e['key']) for e in before} == recovery
    for e in before:
        assert e['state'] == load(d / f"service{e['service']}-stage{e['stage'] - 1}-endpoint.json")['state']
    execution = load(d / 'execution.json'); processes = execution['processes']
    assert len(processes) == len({p['pid'] for p in processes}) == 3
    assert [p['stage'] for p in processes] == [0, 1, 2]
    assert [p['forced_termination'] for p in processes] == [True, True, False]
    for g in range(3):
        ready = load(d / f'stage{g}-ready.json'); sink = load(d / f'stage{g}-sink.json')
        own = [e for e in events if e['stage'] == g]
        assert ready['pid'] == processes[g]['pid'] and ready['stage'] == g and ready['pending'] == (4, 2, 0)[g] and ready['closed'] == (g == 2)
        assert own and all(e['pid'] == ready['pid'] for e in own)
        assert sink['events'] == len(own) and sink['bytes'] == (d / f'stage{g}.jsonl').stat().st_size
        assert all(math.isfinite(sink[k]) and sink[k] >= 0 for k in ('callback_ms', 'flush_ms'))
        for s in range(2):
            receipt = load(d / f'service{s}-stage{g}-copy-comparison.json')
            endpoint = load(d / f'service{s}-stage{g}-endpoint.json')
            expected_digest = hashlib.sha256(json.dumps(endpoint, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            assert receipt == {'service': s, 'stage': g, 'equal': True,
                               'source_endpoint_sha256': expected_digest, 'copy_endpoint_sha256': expected_digest}
    for s in range(2):
        final = load(d / f'service{s}-stage2-endpoint.json'); state = final['state']
        own = [r for r in admitted if r['service'] == s]; own_native = [r for r in native if r['service'] == s]
        assert len(final['conversations']) == 2 and {c['id'] for c in final['conversations']} == set(ids['conversations'][s])
        assert len(final['submissions']) == 6 and len(final['tasks']) == 10
        assert Counter(t['kind'] for t in final['tasks']) == {'pi.generation': 5, 'pi.tool': 5}
        assert all(t['state']['status'] == 'terminal' for t in final['tasks'])
        assert Counter(t['state']['outcome']['status'] for t in final['tasks']) == {'completed': 4, 'aborted': 6}
        kinds = Counter(e['kind'] for e in final['entries'])
        assert kinds['pi.user'] == kinds['pi.assistant'] == kinds['pi.tool-result'] == 5 and kinds['frontier.fixture'] == 1
        assert set(kinds) <= {'pi.user', 'pi.assistant', 'pi.tool-result', 'pi.system', 'frontier.fixture'}
        assert not state['active'] and state['capacity'] == 2
        assert state['authority'] == {str(c): {'version': 3, 'allowed': True} for c in ids['conversations'][s]}
        assert set(state['requests']) == {r['key'] for r in own}
        assert state['effects'] == {r['key']: {'count': 1, 'payload': r['payload']} for r in own_native if r['intent'] in ('post-abort', 'commit')}
        chain_ids = []
        for r in own:
            validate_host(r, state['requests'][r['key']])
            assert r.get('terminal'), 'Every durable host reservation boundedly disposed'
            if r['intent'].startswith('busy-'):
                assert r['terminal'] == {'status': 'denied-before-submit' if r['intent'] == 'busy-deny' else 'cancelled-before-submit'}
                assert not [n for n in final['submissions'] if n.get('requestId') == r['requestId']]
            elif r['intent'].endswith('collision'):
                assert r['terminal'] == {'status': 'native-conflict', 'nativeSubmissionId': r['nativeSubmissionId'],
                                         'nativeType': 'write' if r['intent'] == 'type-collision' else 'input'}
        for r in own_native:
            enters = [e for e in events if e['type'] == 'tool-enter' and e['service'] == s and e['key'] == r['key']]
            assert len(enters) == 1 and enters[0]['stage'] == r['stage'], 'No tool replay after two process reopens'
            chain_ids.extend(validate_native_chain(r, final, enters, expected_api=apis[s, r['stage']]))
            effects = [e for e in events if e['type'] == 'tool-effect' and e['service'] == s and e['key'] == r['key']]
            assert [e['decision'] for e in effects] == (['commit'] if r['intent'] in ('post-abort', 'commit') else [])
            assert all(e['taskId'] == enters[0]['taskId'] and e['stage'] == r['stage'] for e in effects)
        assert len(chain_ids) == len(set(chain_ids)) == 10
        write = next(r for r in own if r['intent'] == 'type-collision')
        record = next(n for n in final['submissions'] if n['id'] == write['nativeSubmissionId'])
        assert (record['type'], record['status'], record['requestId'], record['conversationId']) == ('write', 'done', write['requestId'], write['conversation'])
        entry = next(e for e in final['entries'] if e['id'] == record['entry'])
        assert entry['kind'] == 'frontier.fixture' and entry['data'] == {'original': write['key']} and 'model' not in entry
        assert {n['id'] for n in final['submissions']} == {r['submissionId'] for r in own_native} | {write['nativeSubmissionId']}
        for g in (0, 1):
            endpoint = load(d / f'service{s}-stage{g}-endpoint.json'); snapshot = load(d / f'stage{g}-snapshot.json')
            st = endpoint['state']; assert st == snapshot['states'][s]
            pending = [r for r in snapshot['pending'] if r['service'] == s]
            assert len(pending) == (2 if g == 0 else 1)
            assert st['active'] == {r['key']: True for r in pending}
            assert len(st['requests']) == (2 if g == 0 else 5)
            assert len(endpoint['submissions']) == (1 if g == 0 else 4)
            assert len(endpoint['tasks']) == (2 if g == 0 else 6) and len(st['effects']) == g
            expected_auth = {str(c): {'version': g + 1, 'allowed': True} for c in ids['conversations'][s]}
            if g == 0 and s == 0: expected_auth[str(ids['conversations'][s][0])] = {'version': 99, 'allowed': False}
            assert st['authority'] == expected_auth
            for r in pending:
                assert 'terminal' not in r
                validate_host(r, st['requests'][r['key']])
                if r['intent'].startswith('busy-'):
                    assert 'submissionId' not in r and not [n for n in endpoint['submissions'] if n.get('requestId') == r['requestId']]
                else:
                    enters = [e for e in events if e['type'] == 'tool-enter' and e['service'] == s and e['key'] == r['key']]
                    validate_native_chain(r, endpoint, enters, False, expected_api=apis[s, g])
            assert {t['id'] for t in endpoint['tasks']} <= set(chain_ids)
        pubs = [e for e in events if e['type'] == 'committed-state' and e['service'] == s]
        assert pubs and [e['seq'] for e in pubs] == sorted({e['seq'] for e in pubs})
        assert pubs[-1]['state'] == state and pubs[-1]['seq'] == final['document_sequences'][-1]
        assert all(len(e['state']['active']) <= 2 for e in pubs) and max(len(e['state']['active']) for e in pubs) == 2
    terminal = [e for e in events if e['type'] == 'terminal']
    assert all(e['terminal'] == by_key[e['service'], e['key']]['terminal'] for e in terminal)
    latencies = sorted(e['epoch_ms'] - by_key[e['service'], e['key']]['offered_epoch_ms'] for e in terminal)
    assert all(x >= 0 for x in latencies)
    return {'arrivals': 18, 'durable_host_reservations': 14, 'overloaded': 4, 'native_busy_errors': 2,
            'native_type_errors': 2, 'native_content_reuses': 2, 'host_quarantines': 4,
            'native_submissions': 12, 'native_generation_tasks': 10, 'native_tool_tasks': 10,
            'faux_provider_calls': 10, 'local_effects': 6, 'host_terminals': 14, 'native_terminal_tasks': 20,
            'recovered_reservations': 6, 'maximum_active_per_session': 2, 'final_active': 0,
            'terminal_latency_ms': {'n': 14, **{f'p{p}': latencies[math.ceil(14 * p / 100) - 1] for p in (50, 95, 99)}}}
