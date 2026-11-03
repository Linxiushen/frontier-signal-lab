"""Independent stopped-byte checks for one finite receipt recovery caller.

Only immutable SQLite copies and saved JSON are read. This module never opens
the native runtime, sends HTTP, resumes work, or upgrades scientific records.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import quote, unquote

from experiments.pi_generation_v2_audit import validate_native_chain
from experiments.pi_scoped_generation_audit import (
    expected_receipt, load, typed, verify_copied_endpoint,
)


def validate_inventory(ids):
    conversations, requests = ids['conversations'], ids['requests']
    assert len(conversations) == 2 and conversations[0] == conversations[1]
    assert all(len(c) == len(set(c)) == 2 and all(type(v) is int and v > 0 for v in c)
               for c in conversations), 'Exact repeated native IDs in distinct scopes'
    expected = {}
    for service in range(2):
        for stage in (0, 2):
            for c, intent in ((0, 'race' if stage == 0 else 'negative'),
                              (1, 'positive'), (0, 'overload')):
                conversation = conversations[service][c]
                request_id = f's{stage}-{intent}'
                expected[service, f'{conversation}:{request_id}'] = (
                    stage, conversation, request_id, intent)
    assert len(requests) == len({(r['service'], r['key']) for r in requests}) == 12
    assert {(r['service'], r['key']): (r['stage'], r['conversation'], r['requestId'], r['intent'])
            for r in requests} == expected
    for r in requests:
        assert type(r['service']) is int and r['scope'] == f"service{r['service']}"
        assert type(r['version']) is int and r['version'] == (1 if r['stage'] == 0 else 2)
        assert r['payload'] == f"service{r['service']}/{r['requestId']}"
        assert r['status'] == ('overloaded' if r['intent'] == 'overload' else 'admit')
        if r['status'] == 'admit':
            assert type(r['submissionId']) is int and r['submissionId'] > 0
        else:
            assert 'submissionId' not in r and 'terminal' not in r
    admitted = [r for r in requests if r['status'] == 'admit']
    assert len(admitted) == len({(r['service'], r['submissionId']) for r in admitted}) == 8
    positives = {(r['service'], r['key']): r for r in admitted
                 if r['stage'] == 2 and r['intent'] == 'positive'}
    for name, status in (('retries', 'duplicate'), ('conflicts', 'conflict')):
        rows = ids[name]
        assert len(rows) == 2 and {(r['service'], r['key']) for r in rows} == set(positives)
        for row in rows:
            assert row['status'] == status
            if status == 'duplicate':
                assert row['submissionId'] == positives[row['service'], row['key']]['submissionId']
    return requests, admitted, {(r['service'], r['key']): r for r in admitted}


def disposition(request):
    if request['stage'] == 2 and request['intent'] == 'negative':
        return 'denied' if request['service'] == 0 else 'aborted'
    return 'committed'


def validate_attempts(admitted, attempts):
    assert len(attempts) == 17 and [a[0] for a in attempts] == list(range(1, 18))
    assert all(len(a) == 5 and a[2] in ('service0', 'service1') for a in attempts)
    assert Counter((a[1], a[4]) for a in attempts) == {
        ('GET', 404): 10, ('POST', 201): 6, ('POST', 403): 1}
    assert {(a[2], a[3]) for a in attempts} == {(r['scope'], r['key']) for r in admitted}
    for r in admitted:
        own = [(a[1], a[4]) for a in attempts if (a[2], a[3]) == (r['scope'], r['key'])]
        want = [('GET', 404)]
        if r['intent'] == 'race':
            want += [('GET', 404)]
            if r['service'] == 1:
                want += [('POST', 403)]
            want += [('POST', 201)]
        elif r['intent'] == 'positive':
            want += [('POST', 201)]
        assert own == want, (r['scope'], r['key'], own)


def validate_final_chain(request, endpoint, tool_entries, *, expected_api,
                         native_aborted, decision):
    """Join native rows while separating tool decisions from native outcomes."""
    r = request
    tables = {}
    for table in ('tasks', 'entries', 'submissions'):
        rows = endpoint[table]
        tables[table] = {row['id']: row for row in rows}
        assert len(tables[table]) == len(rows)
    submission = tables['submissions'][r['submissionId']]
    assert submission == r['terminal']
    assert (submission['type'], submission['requestId'], submission['conversationId']) == (
        'input', r['requestId'], r['conversation'])
    user = tables['entries'][submission['entry']]
    assert user['kind'] == 'pi.user' and user['conversationId'] == r['conversation']
    assert len(user['model']) == 1 and user['model'][0]['role'] == 'user'
    args = {k: r[k] for k in ('key', 'payload', 'version')}
    assert json.loads(user['model'][0]['content']) == args
    assert tool_entries and len({e['taskId'] for e in tool_entries}) == 1
    tool = tables['tasks'][tool_entries[0]['taskId']]
    assert (tool['kind'], tool['version'], tool['conversationId'], tool['background']) == (
        'pi.tool', 2, r['conversation'], False)
    assert tool['input']['kind'] == 'model'
    assistant = tables['entries'][tool['input']['assistant']]
    assert assistant['kind'] == 'pi.assistant' and assistant['conversationId'] == r['conversation']
    assert len(assistant['model']) == 1
    message = assistant['model'][0]
    assert (message['role'], message['api'], message['provider'], message['model'], message['stopReason']) == (
        'assistant', expected_api, 'faux', 'faux-1', 'toolUse')
    call_id = 'call-' + hashlib.sha256(r['key'].encode()).hexdigest()[:24]
    assert [c for c in message['content'] if c['type'] == 'toolCall'] == [
        {'type': 'toolCall', 'id': call_id, 'name': 'frontier_effect', 'arguments': args}]
    assert tool['input'] == {'kind': 'model', 'assistant': assistant['id'], 'callId': call_id}
    assert all(e['conversation'] == r['conversation'] and e['callId'] == call_id for e in tool_entries)
    generation = tables['tasks'][tool['owner']]
    assert assistant['byTaskId'] == generation['id']
    assert (generation['kind'], generation['version'], generation['conversationId'], generation['background']) == (
        'pi.generation', 1, r['conversation'], False)
    assert generation['input'] == {} and 'owner' not in generation
    assert submission['status'] == ('unanswered' if native_aborted else 'done')
    if native_aborted:
        assert submission['reason'] == 'aborted' and decision is None
    else:
        assert submission['answer'] == assistant['id']
        assert decision in ('existing', 'commit', 'denied', 'aborted')
    for task in (generation, tool):
        assert task['state']['status'] == 'terminal'
        assert task['state']['outcome']['status'] == ('aborted' if native_aborted else 'completed')
    results = [e for e in endpoint['entries'] if e['kind'] == 'pi.tool-result' and e.get('byTaskId') == tool['id']]
    assert len(results) == 1 and results[0]['conversationId'] == r['conversation']
    assert len(results[0]['model']) == 1
    result = results[0]['model'][0]
    assert (result['role'], result['toolCallId'], result['toolName']) == ('toolResult', call_id, 'frontier_effect')
    assert result['isError'] is (native_aborted or decision in ('denied', 'aborted'))
    if not native_aborted:
        assert result['content'] == [{'type': 'text', 'text': decision}]
    return generation['id'], tool['id']


def validate_races(directory, admitted, events):
    d = Path(directory)
    races = [r for r in admitted if r['intent'] == 'race']
    for r in races:
        s, key = r['service'], r['key']
        own = [(i, e) for i, e in enumerate(events) if e.get('service') == s and e.get('key') == key]

        def one(kind, **fields):
            matches = [(i, e) for i, e in own if e['type'] == kind and all(e.get(k) == v for k, v in fields.items())]
            assert len(matches) == 1, (s, kind, fields)
            return matches[0]

        late = 'late-refusal' if s else 'late-missing'
        order = [one('reconcile-start', label='first')[0],
                 one('race-lookup-missing', call=1)[0],
                 one('race-apply-ready', call=1)[0],
                 one('race-held', label='first-apply')[0],
                 one('reconcile-start', label='second')[0],
                 one('race-lookup-missing', call=2)[0]]
        if s:
            order += [one('race-apply-ready', call=2)[0], one('race-apply-result', call=2)[0]]
            assert one('race-apply-result', call=2)[1]['result'] == {'denied': True}
        order += [one('race-held', label=late)[0], one('race-released', label='first-apply')[0],
                  one('race-apply-result', call=1)[0], one('effect-acknowledged', source='created')[0],
                  one('reconcile-finish', label='first')[0], one('race-first-acknowledged')[0]]
        first = one('race-apply-result', call=1)[1]['result']
        assert first == {'receipt': expected_receipt(r), 'created': True}
        released = one('race-released', label=late)[0]
        ack_index = order[-1]
        if s:
            remote = [(i, e) for i, e in enumerate(events) if e['type'] == 'remote-authority'
                      and e['scope'] == r['scope'] and e['conversation'] == r['conversation'] and e['stage'] == 1]
            assert [e['allowed'] for _, e in remote] == [False, True, False]
            assert order[3] < remote[0][0] < order[4]
            assert one('race-held', label=late)[0] < remote[1][0] < one('race-released', label='first-apply')[0]
            assert ack_index < remote[2][0] < released
        else:
            withdrawn = one('host-authority-withdrawn')[0]
            assert ack_index < withdrawn < released
        superseded = one('effect-disposition-superseded')[1]
        assert superseded['status'] == 'denied' and superseded['by'] == 'committed'
        order += [released, one('effect-disposition-superseded')[0], one('reconcile-finish', label='second')[0],
                  one('race-receipt-preserved')[0], one('cancel-mark-held')[0]]
        assert order == sorted(set(order)), 'Real transport, acknowledgement and stale callback ordering'
        assert not [e for _, e in own if e['type'] == 'effect-refused']
        for name, kind in (('acknowledged', 'race-first-acknowledged'), ('preserved', 'race-receipt-preserved')):
            state = load(d / f'race{s}-{name}.json')
            assert state == one(kind)[1]['state']
            assert state['effectIntents'][key] == {
                'identity': {k: v for k, v in expected_receipt(r).items() if k != 'count'},
                'status': 'committed', 'receipt': expected_receipt(r)}
            assert state['effects'][key] == {'count': 1, 'payload': r['payload'], 'receipt': expected_receipt(r)}
            assert 'effectDenied' not in state['requests'][key]
        path = f"/effects/{r['scope']}/{quote(key, safe='')}"
        transport = [(i, e) for i, e in enumerate(events) if e['type'] == 'http-result'
                     and e.get('service') == s and e.get('path') == path and e['stage'] == 1]
        assert [(e['method'], e['status']) for _, e in transport] == (
            [('GET', 404), ('GET', 404), ('POST', 403), ('POST', 201)] if s else
            [('GET', 404), ('GET', 404), ('POST', 201)])
        assert transport[0][0] < one('race-lookup-missing', call=1)[0]
        assert transport[1][0] < one('race-lookup-missing', call=2)[0]
        if s:
            assert transport[2][0] < one('race-apply-result', call=2)[0]


def audit(directory):
    d = Path(directory)
    ids = load(d / 'identities.json')
    requests, admitted, by_key = validate_inventory(ids)
    events = [json.loads(line) for g in range(3) for line in
              (d / f'stage{g}.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert not typed(events, 'network-access-denied') and not typed(events, 'runtime-report')
    assert not typed(events, 'native-identity-conflict')
    identities = typed(events, 'provider-identity')
    apis = {(e['service'], e['stage']): e['api'] for e in identities}
    assert len(identities) == len(apis) == 6 and set(apis) == {(s, g) for s in range(2) for g in range(3)}
    assert len({apis[0, g] for g in range(3)}) == 3
    assert all(re.fullmatch(r'faux:[0-9]+:[a-z0-9]+', apis[0, g]) for g in range(3))
    assert all(apis[1, g] == 'frontier-faux-receipts' for g in range(3))
    assert all((e['provider'], e['model'], e['mode']) == ('faux', 'faux-1',
        'default-dynamic' if e['service'] == 0 else 'configured-stable') for e in identities)
    providers, enters, terminals = (typed(events, k) for k in ('provider-request', 'tool-enter', 'terminal'))
    assert len(providers) == len(terminals) == 8 and len(enters) == 10
    for rows in (providers, terminals, enters):
        assert {(e['service'], e['key']) for e in rows} == set(by_key)
    for e in providers:
        r = by_key[e['service'], e['key']]
        assert e['stage'] == r['stage'] and e['api'] == apis[r['service'], r['stage']]
        assert e['providerSession'] and 'frontier_effect' in e['offeredTools']
    calls = typed(events, 'admission')
    assert len(calls) == 16 and Counter(e['status'] for e in calls) == {
        'admit': 8, 'overloaded': 4, 'duplicate': 2, 'conflict': 2}
    for r in requests:
        own = [e for e in calls if e['service'] == r['service'] and e['key'] == r['key'] and e['status'] == r['status']]
        assert len(own) == 1 and all(own[0][k] == r[k] for k in ('conversation', 'requestId', 'payload', 'version'))
        if r['status'] == 'admit':
            assert own[0]['submissionId'] == r['submissionId']
    assert all(math.isfinite(e['elapsed_ms']) and e['elapsed_ms'] >= 0 for e in calls)
    recoveries = {(g, r['service'], r['key'], r['submissionId']) for g in (1, 2) for r in admitted if r['stage'] == 0}
    assert len(ids['recovered']) == 8 and {(r['stage'], r['service'], r['key'], r['submissionId']) for r in ids['recovered']} == recoveries
    before = typed(events, 'recovery-before-resume')
    assert len(before) == 8 and {(e['stage'], e['service'], e['key']) for e in before} == {r[:3] for r in recoveries}
    for e in before:
        assert e['state'] == load(d / f"service{e['service']}-stage{e['stage'] - 1}-endpoint.json")['state']
    validate_races(d, admitted, events)
    execution = load(d / 'execution.json')
    for group in ('processes', 'servers'):
        rows = execution[group]
        assert len(rows) == len({r['pid'] for r in rows}) == 3 and [r['stage'] for r in rows] == [0, 1, 2]
    assert [r['forced_termination'] for r in execution['processes']] == [True, True, False]
    assert all(r['returncode'] != 0 for r in execution['processes'][:2]) and execution['processes'][2]['returncode'] == 0
    assert all(r['returncode'] == 0 for r in execution['servers'])
    endpoints = {}
    remotes = {}
    for g in range(3):
        ready, snapshot, sink = (load(d / f'stage{g}-{name}.json') for name in ('ready', 'snapshot', 'sink'))
        assert execution['processes'][g]['ready'] == ready
        assert ready['stage'] == snapshot['stage'] == g
        assert ready['pid'] == snapshot['pid'] == execution['processes'][g]['pid']
        assert ready['pending'] == (4, 4, 0)[g] and ready['closed'] is (g == 2)
        own_events = [e for e in events if e['stage'] == g]
        assert own_events and all(e['pid'] == ready['pid'] for e in own_events)
        assert sink['events'] == len(own_events) and sink['bytes'] == (d / f'stage{g}.jsonl').stat().st_size
        assert all(math.isfinite(sink[k]) and sink[k] >= 0 for k in ('callback_ms', 'flush_ms'))
        remote = remotes[g] = verify_copied_endpoint(d, g)
        assert remote == load(d / f'effect-server{g}-final.json') == snapshot['server']
        assert len(remote['effects']) == (0, 4, 6)[g] and len(remote['attempts']) == (0, 11, 17)[g]
        expected_auth = sorted([f'service{s}', c, 2 if g == 2 else 1,
                                int(not (g == 1 and s == 1 and i == 0))]
                               for s, cs in enumerate(ids['conversations']) for i, c in enumerate(cs))
        assert remote['authority'] == expected_auth
        initial = load(d / f'effect-server{g}-initial-snapshot.json')
        assert initial == (remotes[g - 1] if g else {'authority': [], 'effects': [], 'attempts': []})
        server_ready = load(d / f'effect-server{g}-ready.json')
        assert server_ready['stage'] == g and server_ready['pid'] == execution['servers'][g]['pid'] and server_ready['protocol'] == 'scoped-v2'
        server_events = [json.loads(line) for line in (d / f'effect-server{g}.jsonl').read_text(encoding='utf-8').splitlines()]
        assert server_events and all(e['stage'] == g and e['pid'] == server_ready['pid'] for e in server_events)
        assert len(typed(server_events, 'server-ready')) == len(typed(server_events, 'server-closed')) == 1
        assert server_events[-1]['type'] == 'server-closed'
        assert not typed(server_events, 'request-rejected') and not typed(server_events, 'reply-held-after-commit')
        observed = typed(server_events, 'effect-request')
        start = (0, 0, 11)[g]
        assert [(e['method'], e['scope'], e['key'], e['status']) for e in observed] == [tuple(a[1:]) for a in remote['attempts'][start:]]
        for s in range(2):
            endpoint = endpoints[s, g] = verify_copied_endpoint(d, g, s)
            state = endpoint['state']
            own = [r for r in admitted if r['service'] == s and r['stage'] <= g]
            assert state == snapshot['states'][s] and state['capacity'] == 2
            assert set(state['requests']) == set(state['effectIntents']) == {r['key'] for r in own}
            assert len(endpoint['submissions']) == len(own) and len(endpoint['tasks']) == 2 * len(own)
            assert set(state['effects']) == {r['key'] for r in own if g > 0 and disposition(r) == 'committed'}
            pending = [r for r in snapshot['pending'] if r['service'] == s]
            assert len(pending) == (2 if g < 2 else 0) and state['active'] == {r['key']: True for r in pending}
            host_auth = {str(c): {'version': 2 if g == 2 else 1, 'allowed': True} for c in ids['conversations'][s]}
            if s == 0 and g > 0:
                host_auth[str(ids['conversations'][s][0])]['allowed'] = False
            assert state['authority'] == host_auth
            for r in own:
                stored, intent = state['requests'][r['key']], state['effectIntents'][r['key']]
                expected_host = {k: r[k] for k in ('conversation', 'requestId', 'payload', 'version', 'submissionId')}
                expected_host['fingerprint'] = hashlib.sha256(r['payload'].encode()).hexdigest()
                cancelled = (r['intent'] == 'race' and g > 0) or (r['stage'] == 2 and r['intent'] == 'negative' and s == 1)
                if cancelled:
                    expected_host['cancelled'] = True
                if g == 2:
                    expected_host['terminal'] = r['terminal']
                    if disposition(r) == 'denied':
                        expected_host['effectDenied'] = True
                assert stored == expected_host
                expected_intent = {'identity': {k: v for k, v in expected_receipt(r).items() if k != 'count'},
                                   'status': 'pending' if g == 0 else disposition(r)}
                if expected_intent['status'] == 'committed':
                    expected_intent['receipt'] = expected_receipt(r)
                    assert state['effects'][r['key']] == {'count': 1, 'payload': r['payload'], 'receipt': expected_receipt(r)}
                assert intent == expected_intent
    expected_effects = {(r['scope'], r['key']): expected_receipt(r) for r in admitted if disposition(r) == 'committed'}
    assert len(expected_effects) == 6 and {(r['scope'], r['key']): r for r in remotes[2]['effects']} == expected_effects
    validate_attempts(admitted, remotes[2]['attempts'])
    acks = typed(events, 'effect-acknowledged')
    assert len(acks) == 6 and {(e['service'], e['key']) for e in acks} == {
        (r['service'], r['key']) for r in admitted if disposition(r) == 'committed'}
    for e in acks:
        r = by_key[e['service'], e['key']]
        assert e['source'] == 'created' and e['receipt'] == expected_receipt(r)
        assert e['stage'] == (1 if r['stage'] == 0 else 2)
    superseded = typed(events, 'effect-disposition-superseded')
    assert len(superseded) == 2 and {(e['stage'], e['service'], e['key']) for e in superseded} == {
        (1, r['service'], r['key']) for r in admitted if r['intent'] == 'race'}
    assert all(e['status'] == 'denied' and e['by'] == 'committed' for e in superseded)
    refused = typed(events, 'effect-refused')
    assert len(refused) == 2 and {(e['stage'], e['service'], e['key'], e['status']) for e in refused} == {
        (2, r['service'], r['key'], disposition(r)) for r in admitted if r['intent'] == 'negative'}
    recovered = load(d / 'stage2-recovered.json')
    assert recovered['server'] == remotes[1], 'Recovery acknowledges history without HTTP effect attempts'
    preaborts = typed(events, 'recovery-native-preabort')
    races = [r for r in admitted if r['intent'] == 'race']
    assert len(preaborts) == 2 and {(e['stage'], e['service'], e['key']) for e in preaborts} == {(2, r['service'], r['key']) for r in races}
    effects = typed(events, 'tool-effect')
    assert len(effects) == 6
    for s in range(2):
        endpoint = endpoints[s, 2]
        own = [r for r in admitted if r['service'] == s]
        assert len(endpoint['conversations']) == 2 and {c['id'] for c in endpoint['conversations']} == set(ids['conversations'][s])
        assert Counter(t['kind'] for t in endpoint['tasks']) == {'pi.generation': 4, 'pi.tool': 4}
        assert Counter(t['state']['outcome']['status'] for t in endpoint['tasks']) == {'completed': 6, 'aborted': 2}
        kinds = Counter(e['kind'] for e in endpoint['entries'])
        assert kinds['pi.user'] == kinds['pi.assistant'] == kinds['pi.tool-result'] == 4
        assert set(kinds) <= {'pi.user', 'pi.assistant', 'pi.tool-result', 'pi.system'}
        chain_ids = []
        for r in own:
            selected = [e for e in enters if e['service'] == s and e['key'] == r['key']]
            replay = r['stage'] == 0 and r['intent'] == 'positive'
            assert [e['stage'] for e in selected] == ([0, 2] if replay else [r['stage']])
            native_aborted = r['intent'] == 'race'
            decision = None if native_aborted else 'existing' if replay else (
                disposition(r) if r['intent'] == 'negative' else 'commit')
            chain_ids.extend(validate_final_chain(r, endpoint, selected, expected_api=apis[s, r['stage']],
                                                  native_aborted=native_aborted, decision=decision))
            own_effects = [e for e in effects if e['service'] == s and e['key'] == r['key']]
            assert [e['decision'] for e in own_effects] == ([] if native_aborted else [decision])
            assert all(e['stage'] == 2 and e['taskId'] == selected[0]['taskId'] for e in own_effects)
            terminal = [e for e in terminals if e['service'] == s and e['key'] == r['key']]
            assert len(terminal) == 1 and terminal[0]['stage'] == 2 and terminal[0]['terminal'] == r['terminal']
            assert terminal[0]['epoch_ms'] == r['terminal_epoch_ms'] >= r['offered_epoch_ms']
            if r['stage'] == 0:
                original = selected[:1]
                for g in (0, 1):
                    assert validate_native_chain(r, endpoints[s, g], original, settled=False,
                                                 expected_api=apis[s, 0]) == tuple(chain_ids[-2:])
                if native_aborted:
                    mark = next(e for e in preaborts if e['service'] == s)
                    assert (mark['scheduling'], mark['conversation'], mark['submissionId'], mark['generationTaskId'], mark['toolTaskId']) == (
                        'paused', r['conversation'], r['submissionId'], *chain_ids[-2:])
            assert recovered['states'][s]['requests'].get(r['key'], {}).get('terminal') == (r['terminal'] if r['stage'] == 0 else None)
        assert len(chain_ids) == len(set(chain_ids)) == 8
        pubs = [e for e in typed(events, 'committed-state') if e['service'] == s]
        assert pubs and [e['seq'] for e in pubs] == sorted({e['seq'] for e in pubs})
        assert pubs[-1]['state'] == endpoint['state'] and pubs[-1]['seq'] == endpoint['document_sequences'][-1]
        assert max(len(e['state']['active']) for e in pubs) == 2 and all(len(e['state']['active']) <= 2 for e in pubs)
        committed = {}
        for e in pubs:
            state = e['state']
            for key, value in committed.items():
                assert state['effects'].get(key) == value and state['effectIntents'][key]['status'] == 'committed'
                assert state['effectIntents'][key]['receipt'] == value['receipt']
            committed.update(state['effects'])
    holds = typed(events, 'cancel-mark-held')
    assert len(holds) == 3 and {(e['stage'], e['service'], e['key']) for e in holds} == (
        {(1, r['service'], r['key']) for r in races} |
        {(2, r['service'], r['key']) for r in admitted if r['stage'] == 2 and r['service'] == 1 and r['intent'] == 'negative'})
    latencies = sorted(e['epoch_ms'] - by_key[e['service'], e['key']]['offered_epoch_ms'] for e in terminals)
    http = typed(events, 'http-result')
    assert all('error' not in e and math.isfinite(e['elapsed_ms']) and e['elapsed_ms'] >= 0 for e in http)
    assert all(type(e['request_body_bytes']) is int and 0 <= e['request_body_bytes'] <= 4096 and
               type(e['response_body_bytes']) is int and 0 <= e['response_body_bytes'] <= 16384 for e in http)
    effect_http = [e for e in http if e['path'].startswith('/effects/')]
    observed_effect_http = []
    for e in effect_http:
        parts = e['path'].split('/')
        assert len(parts) == 4 and parts[:2] == ['', 'effects']
        scope, key = parts[2], unquote(parts[3])
        assert scope == f"service{e['service']}" and (e['service'], key) in by_key
        observed_effect_http.append((e['method'], scope, key, e['status']))
    sql_http = [tuple(a[1:]) for a in remotes[2]['attempts']]
    assert len(effect_http) == 17 and Counter(observed_effect_http) == Counter(sql_http)
    for r in admitted:
        identity = r['scope'], r['key']
        assert [a for a in observed_effect_http if a[1:3] == identity] == [a for a in sql_http if a[1:3] == identity]
    admission_latencies = sorted(e['elapsed_ms'] for e in calls)
    return {'arrivals': 12, 'admitted': 8, 'overloaded': 4, 'duplicate_retries': 2, 'conflicting_retries': 2,
            'native_generation_tasks': 8, 'native_tool_tasks': 8, 'faux_provider_calls': 8,
            'native_aborted_tasks': 4, 'native_completed_tasks': 12, 'local_effects': 6,
            'http_effect_attempts': 17, 'stale_callback_superseded': 2, 'public_reconcile_calls_in_races': 4,
            'recovered_reservations': 8, 'maximum_active_per_session': 2, 'final_active': 0,
            'terminal_latency_ms': {'n': 8, 'max': max(latencies),
                                    **{f'p{p}': latencies[math.ceil(8 * p / 100) - 1] for p in (50, 95, 99)}},
            'admission_latency_ms': {'n': len(calls), 'max': max(admission_latencies),
                                     **{f'p{p}': admission_latencies[math.ceil(len(calls) * p / 100) - 1]
                                        for p in (50, 95)},
                                     'scope': 'All16 public admission calls, including2duplicate/2conflict retries.'},
            'observed_http': {'requests': len(http), 'latency_ms_sum': sum(e['elapsed_ms'] for e in http),
                              'request_body_bytes': sum(e['request_body_bytes'] for e in http),
                              'response_body_bytes': sum(e['response_body_bytes'] for e in http)}}
