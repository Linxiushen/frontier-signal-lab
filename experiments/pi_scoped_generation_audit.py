"""Independent saved-byte audit of the finite scoped-v2 native caller.

Reads closed SQLite backups and JSON only; never opens the native runtime,
starts a server, resumes a task or changes scientific acceptance records.
"""
from collections import Counter
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from experiments.pi_generation_conflict_audit import read_endpoint
from experiments.pi_generation_v2_audit import validate_native_chain


def load(path):
    return json.loads(Path(path).read_bytes())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def typed(events, kind):
    """Filter heterogeneous event kinds before accessing their typed payloads."""
    assert all(isinstance(e, dict) and isinstance(e.get('type'), str) for e in events)
    return [e for e in events if e['type'] == kind]


def expected_receipt(request):
    return {k: request[k] for k in ('key', 'payload', 'conversation', 'version')} | {
        'scope': f"service{request['service']}",
        'fingerprint': hashlib.sha256(request['payload'].encode()).hexdigest(), 'count': 1}


def read_scoped_endpoint(database):
    """Read the exact composite-key v2 schema, rejecting legacy key-only data."""
    assert database.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    assert database.execute('PRAGMA user_version').fetchone() == (2,), 'Requires scoped-v2 database'
    schemas = {
        'authority': [('scope', 1), ('conversation', 2), ('version', 0), ('allowed', 0)],
        'effects': [('scope', 1), ('key', 2), ('identity', 0), ('count', 0)],
        'attempts': [('seq', 1), ('method', 0), ('scope', 0), ('key', 0), ('status', 0)],
    }
    for table, expected in schemas.items():
        assert [(r[1], r[5]) for r in database.execute('PRAGMA table_info(' + table + ')')] == expected, table
    authority = [list(r) for r in database.execute('SELECT scope,conversation,version,allowed FROM authority ORDER BY scope,conversation')]
    effects = []
    for scope, key, encoded, count in database.execute('SELECT scope,key,identity,count FROM effects ORDER BY scope,key'):
        value = json.loads(encoded)
        assert set(value) == {'scope', 'key', 'conversation', 'version', 'payload', 'fingerprint'}
        assert value['scope'] == scope and value['key'] == key and type(count) is int and count == 1
        assert re.fullmatch(r'[a-z0-9-]{1,64}', scope) and isinstance(key, str)
        assert type(value['conversation']) is int and type(value['version']) is int
        assert isinstance(value['payload'], str) and value['fingerprint'] == hashlib.sha256(value['payload'].encode()).hexdigest()
        effects.append({**value, 'count': count})
    attempts = [list(r) for r in database.execute('SELECT seq,method,scope,key,status FROM attempts ORDER BY seq')]
    assert [r[0] for r in attempts] == list(range(1, len(attempts) + 1))
    return {'authority': authority, 'effects': effects, 'attempts': attempts}


def verify_copied_endpoint(directory, stage, service=None):
    d = Path(directory)
    stem = f'effects-stage{stage}' if service is None else f'service{service}-stage{stage}'
    path = (d / f'{stem}.sqlite').resolve()
    assert path.is_file(), 'Missing immutable stopped database copy'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=0.02)) as db:
        actual = (read_scoped_endpoint if service is None else read_endpoint)(db)
    assert actual == load(d / f'{stem}-endpoint.json'), 'Copied SQL differs from saved endpoint'
    comparison = load(d / f'{stem}-copy-comparison.json')
    assert comparison['equal'] is True
    assert comparison['source_endpoint_sha256'] == comparison['copy_endpoint_sha256'] == digest(actual)
    if service is not None:
        assert comparison['service'] == service and comparison['stage'] == stage
    return actual


def validate_inventory(ids):
    conversations, requests = ids['conversations'], ids['requests']
    assert len(conversations) == 2 and conversations[0] == conversations[1], 'Native numeric IDs must repeat across isolated Sessions'
    assert all(len(c) == len(set(c)) == 2 and all(type(x) is int and x > 0 for x in c) for c in conversations)
    expected = {}
    for service in range(2):
        for stage in range(3):
            for c, intent in ((0, ('revoke', 'post', 'final')[stage]), (1, ('cancel', 'live', 'final')[stage]), (0, 'overload')):
                conversation = conversations[service][c]
                request_id = f's{stage}-{intent}'
                expected[service, f'{conversation}:{request_id}'] = (stage, conversation, request_id, intent)
    assert len(requests) == len({(r['service'], r['key']) for r in requests}) == len(expected) == 18
    assert {(r['service'], r['key']): (r['stage'], r['conversation'], r['requestId'], r['intent']) for r in requests} == expected
    for r in requests:
        assert r['scope'] == f"service{r['service']}" and r['version'] == r['stage'] + 1
        assert r['payload'] == f"service{r['service']}/{r['requestId']}"
        assert r['status'] == ('overloaded' if r['intent'] == 'overload' else 'admit')
        if r['status'] == 'admit':
            assert type(r['submissionId']) is int and r['submissionId'] > 0
        else:
            assert 'submissionId' not in r and 'terminal' not in r
    admitted = [r for r in requests if r['status'] == 'admit']
    assert len(admitted) == len({(r['service'], r['submissionId']) for r in admitted}) == 12
    return requests, admitted, {(r['service'], r['key']): r for r in admitted}


def disposition(r):
    if (r['service'], r['stage'], r['intent']) == (0, 0, 'revoke'):
        return 'denied', True
    if (r['service'], r['stage'], r['intent']) == (1, 0, 'cancel'):
        return 'aborted', True
    if (r['service'], r['stage'], r['intent']) == (0, 1, 'live'):
        return 'denied', False
    return 'committed', (r['service'], r['stage'], r['intent']) == (0, 1, 'post')


def validate_attempts(admitted, attempts):
    assert len(attempts) == 27 and [a[0] for a in attempts] == list(range(1, 28))
    assert all(len(a) == 5 and a[2] in ('service0', 'service1') for a in attempts)
    assert Counter((a[1], a[4]) for a in attempts) == {('GET', 404): 12, ('GET', 200): 1,
        ('POST', 201): 9, ('POST', 403): 1, ('POST', 200): 2, ('POST', 409): 2}
    expected_pairs = {(f"service{r['service']}", r['key']) for r in admitted}
    assert {(a[2], a[3]) for a in attempts} == expected_pairs
    for r in admitted:
        own = [(a[1], a[4]) for a in attempts if (a[2], a[3]) == (r['scope'], r['key'])]
        status, _ = disposition(r)
        want = [('GET', 404)]
        if status == 'committed':
            want += [('POST', 201)]
            if (r['service'], r['stage'], r['intent']) == (0, 1, 'post'):
                want += [('GET', 200)]
            if r['intent'] == 'post':
                want += [('POST', 200), ('POST', 409)]
        elif (r['service'], r['stage'], r['intent']) == (0, 0, 'revoke'):
            want += [('POST', 403)]
        assert own == want, (r['scope'], r['key'], own)


def validate_recoveries(directory, ids, admitted, events, apis):
    d = Path(directory)
    expected = {(r['stage'] + 1, r['service'], r['key'], r['submissionId']): r for r in admitted
                if r['stage'] == 0 or (r['service'], r['stage'], r['intent']) == (0, 1, 'post')}
    actual = [(r['stage'], r['service'], r['key'], r['submissionId']) for r in ids['recovered']]
    assert len(actual) == len(set(actual)) == len(expected) == 5 and set(actual) == set(expected)
    before = typed(events, 'recovery-before-resume')
    assert len(before) == 5 and {(e['stage'], e['service'], e['key']) for e in before} == {k[:3] for k in expected}
    for e in before:
        assert e['state'] == load(d / f"service{e['service']}-stage{e['stage'] - 1}-endpoint.json")['state']
    negatives = {k[:3]: r for k, r in expected.items() if disposition(r)[1]}
    marks = typed(events, 'recovery-native-preabort')
    assert len(marks) == 3 and {(e['stage'], e['service'], e['key']) for e in marks} == set(negatives)
    for e in marks:
        r = negatives[e['stage'], e['service'], e['key']]
        prior = load(d / f"service{r['service']}-stage{r['stage']}-endpoint.json")
        enters = [x for x in typed(events, 'tool-enter') if x['service'] == r['service'] and x['key'] == r['key'] and x['stage'] == r['stage']]
        generation, tool = validate_native_chain(r, prior, enters, settled=False, expected_api=apis[r['service'], r['stage']])
        assert (e['scheduling'], e['conversation'], e['submissionId'], e['generationTaskId'], e['toolTaskId']) == (
            'paused', r['conversation'], r['submissionId'], generation, tool)


def validate_controls(ids, admitted, events):
    finals = {(r['service'], r['key']): r for r in admitted if r['stage'] == 2}
    for name, status in (('retries', 'duplicate'), ('conflicts', 'conflict')):
        rows = ids[name]
        assert len(rows) == 4 and {(r['service'], r['key']) for r in rows} == set(finals)
        for row in rows:
            assert row['status'] == status
            if status == 'duplicate':
                assert row['submissionId'] == finals[row['service'], row['key']]['submissionId']
    posts = {(r['service'], r['key']): r for r in admitted if r['intent'] == 'post'}
    for kind in ('duplicate-effect-control', 'changed-effect-control'):
        rows = typed(events, kind)
        assert len(rows) == 2 and {(e['service'], e['key']) for e in rows} == set(posts)
        for e in rows:
            assert e['stage'] == 2
            if kind == 'duplicate-effect-control':
                assert e['receipt'] == expected_receipt(posts[e['service'], e['key']])
            else:
                assert e['status'] == 409


def audit(directory):
    d = Path(directory)
    ids = load(d / 'identities.json')
    requests, admitted, by_key = validate_inventory(ids)
    events = [json.loads(line) for stage in range(3) for line in (d / f'stage{stage}.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert not typed(events, 'network-access-denied') and not typed(events, 'runtime-report')
    identities = typed(events, 'provider-identity')
    apis = {(e['service'], e['stage']): e['api'] for e in identities}
    assert len(identities) == len(apis) == 6 and set(apis) == {(s, g) for s in range(2) for g in range(3)}
    assert len({apis[0, g] for g in range(3)}) == 3
    assert all(re.fullmatch(r'faux:[0-9]+:[a-z0-9]+', apis[0, g]) for g in range(3))
    assert all(apis[1, g] == 'frontier-faux-scoped' for g in range(3))
    assert all((e['provider'], e['model'], e['mode']) == ('faux', 'faux-1', 'default-dynamic' if e['service'] == 0 else 'configured-stable') for e in identities)
    providers, terminals, enters = (typed(events, k) for k in ('provider-request', 'terminal', 'tool-enter'))
    assert len(enters) == 14 and {(e['service'], e['key']) for e in enters} == set(by_key)
    for rows in (providers, terminals):
        assert len(rows) == 12 and {(e['service'], e['key']) for e in rows} == set(by_key)
    for e in providers:
        r = by_key[e['service'], e['key']]
        assert e['stage'] == r['stage'] and e['api'] == apis[r['service'], r['stage']]
        assert e['providerSession'] and 'frontier_effect' in e['offeredTools']
    validate_recoveries(d, ids, admitted, events, apis)
    validate_controls(ids, admitted, events)
    calls = typed(events, 'admission')
    assert len(calls) == 26 and Counter(e['status'] for e in calls) == {'admit': 12, 'overloaded': 6, 'duplicate': 4, 'conflict': 4}
    for r in requests:
        own = [e for e in calls if e['service'] == r['service'] and e['key'] == r['key'] and e['status'] == r['status']]
        assert len(own) == 1 and all(own[0][k] == r[k] for k in ('conversation', 'requestId', 'payload', 'version'))
        if r['status'] == 'admit':
            assert own[0]['submissionId'] == r['submissionId']
    for e in calls:
        assert math.isfinite(e['elapsed_ms']) and e['elapsed_ms'] >= 0
    execution = load(d / 'execution.json')
    for group in ('processes', 'servers'):
        group_rows = execution[group]
        assert len(group_rows) == len({r['pid'] for r in group_rows}) == 3
        assert [r['stage'] for r in group_rows] == [0, 1, 2]
    assert [r['forced_termination'] for r in execution['processes']] == [True, True, False]
    assert all(r['returncode'] != 0 for r in execution['processes'][:2]) and execution['processes'][2]['returncode'] == 0
    assert all(r['returncode'] == 0 for r in execution['servers'])
    endpoints = {}
    for stage in range(3):
        ready, snapshot, sink = (load(d / f'stage{stage}-{n}.json') for n in ('ready', 'snapshot', 'sink'))
        assert execution['processes'][stage]['ready'] == ready
        assert ready['stage'] == snapshot['stage'] == stage
        assert ready['pid'] == snapshot['pid'] == execution['processes'][stage]['pid']
        assert ready['pending'] == (4, 1, 0)[stage] and ready['closed'] is (stage == 2)
        own = [e for e in events if e['stage'] == stage]
        assert own and all(e['pid'] == ready['pid'] for e in own)
        assert sink['events'] == len(own) and sink['bytes'] == (d / f'stage{stage}.jsonl').stat().st_size
        assert all(math.isfinite(sink[k]) and sink[k] >= 0 for k in ('callback_ms', 'flush_ms'))
        remote = verify_copied_endpoint(d, stage)
        assert remote == load(d / f'effect-server{stage}-final.json') == snapshot['server']
        assert len(remote['effects']) == (0, 5, 9)[stage] and len(remote['attempts']) == (0, 14, 27)[stage]
        auth = sorted([f'service{s}', c, stage + 1, int(not (s == 0 and i == 0 and stage < 2))]
                      for s, cs in enumerate(ids['conversations']) for i, c in enumerate(cs))
        assert remote['authority'] == auth
        initial = load(d / f'effect-server{stage}-initial-snapshot.json')
        assert initial == (load(d / f'effect-server{stage - 1}-final.json') if stage else {'authority': [], 'effects': [], 'attempts': []})
        server_ready = load(d / f'effect-server{stage}-ready.json')
        assert server_ready['stage'] == stage and server_ready['pid'] == execution['servers'][stage]['pid'] and server_ready['protocol'] == 'scoped-v2'
        server_events = [json.loads(line) for line in (d / f'effect-server{stage}.jsonl').read_text(encoding='utf-8').splitlines()]
        assert server_events and all(e['stage'] == stage and e['pid'] == server_ready['pid'] for e in server_events)
        assert len(typed(server_events, 'server-ready')) == len(typed(server_events, 'server-closed')) == 1
        assert server_events[-1]['type'] == 'server-closed' and not typed(server_events, 'request-rejected')
        observed = typed(server_events, 'effect-request')
        start = (0, 0, 14)[stage]
        assert [(e['method'], e['scope'], e['key'], e['status']) for e in observed] == [tuple(a[1:]) for a in remote['attempts'][start:]]
        held = typed(server_events, 'reply-held-after-commit')
        assert [(e['scope'], e['key']) for e in held] == ([(r['scope'], r['key']) for r in admitted if (r['service'], r['stage'], r['intent']) == (0, 1, 'post')] if stage == 1 else [])
        for service in range(2):
            endpoint = endpoints[service, stage] = verify_copied_endpoint(d, stage, service)
            state = endpoint['state']; own_requests = [r for r in admitted if r['service'] == service and r['stage'] <= stage]
            assert state == snapshot['states'][service] and state['capacity'] == 2
            assert set(state['requests']) == set(state['effectIntents']) == {r['key'] for r in own_requests}
            assert len(endpoint['submissions']) == len(own_requests) and len(endpoint['tasks']) == 2 * len(own_requests)
            pending = [r for r in snapshot['pending'] if r['service'] == service]
            assert len(pending) == (2 if stage == 0 else int(service == 0) if stage == 1 else 0)
            assert state['active'] == {r['key']: True for r in pending}
            host_auth = {str(c): {'version': stage + 1, 'allowed': True} for c in ids['conversations'][service]}
            if stage == 1 and service == 0:
                host_auth[str(ids['conversations'][0][1])] = {'version': 2, 'allowed': False}
            assert state['authority'] == host_auth
            for r in own_requests:
                assert state['effectIntents'][r['key']]['identity'] == {k: v for k, v in expected_receipt(r).items() if k != 'count'}
    receipts = {(r['scope'], r['key']): expected_receipt(r) for r in admitted if disposition(r)[0] == 'committed'}
    remote = load(d / 'effect-server2-final.json')
    assert len(receipts) == 9 and {(r['scope'], r['key']): r for r in remote['effects']} == receipts
    validate_attempts(admitted, remote['attempts'])
    statuses = []
    for service in range(2):
        final = endpoints[service, 2]; state = final['state']; chain_ids = []
        own = [r for r in admitted if r['service'] == service]
        assert {c['id'] for c in final['conversations']} == set(ids['conversations'][service]) and len(final['conversations']) == 2
        assert Counter(t['kind'] for t in final['tasks']) == {'pi.generation': 6, 'pi.tool': 6}
        assert all(t['state']['status'] == 'terminal' for t in final['tasks'])
        assert set(state['effects']) == {r['key'] for r in own if disposition(r)[0] == 'committed'}
        for r in own:
            stored = state['requests'][r['key']]; intent = state['effectIntents'][r['key']]
            assert all(stored[k] == r[k] for k in ('conversation', 'requestId', 'payload', 'version', 'submissionId', 'terminal'))
            assert stored['fingerprint'] == hashlib.sha256(r['payload'].encode()).hexdigest()
            status, aborted = disposition(r)
            assert intent['status'] == status
            assert bool(stored.get('cancelled')) is ((service, r['stage'], r['intent']) in ((1, 0, 'cancel'), (0, 1, 'post')))
            assert bool(stored.get('effectDenied')) is (status == 'denied')
            if status == 'committed':
                receipt = receipts[r['scope'], r['key']]
                assert intent['receipt'] == receipt and state['effects'][r['key']] == {'count': 1, 'payload': r['payload'], 'receipt': receipt}
            selected = [e for e in enters if e['service'] == service and e['key'] == r['key']]
            replay = r['stage'] == 0 and not aborted
            assert [e['stage'] for e in selected] == ([0, 1] if replay else [r['stage']])
            mapped = {**r, 'intent': 'pre-abort' if aborted else 'deny' if status == 'denied' else 'recover' if replay else 'commit'}
            chain_ids.extend(validate_native_chain(mapped, final, selected, expected_api=apis[service, r['stage']]))
            terminal = next(e for e in terminals if (e['service'], e['key']) == (service, r['key']))
            expected_stage = 1 if r['stage'] == 0 else 2 if (service, r['stage'], r['intent']) == (0, 1, 'post') else r['stage']
            assert terminal['stage'] == expected_stage and terminal['terminal'] == r['terminal']
            assert terminal['epoch_ms'] == r['terminal_epoch_ms'] >= r['offered_epoch_ms']
            for stage in range(r['stage'], 2):
                earlier = endpoints[service, stage]
                original = [e for e in selected if e['stage'] == r['stage']]
                settled = any(e['stage'] <= stage for e in terminals if (e['service'], e['key']) == (service, r['key']))
                validate_native_chain(mapped, earlier, original, settled=settled, expected_api=apis[service, r['stage']])
        assert len(chain_ids) == len(set(chain_ids)) == len(final['tasks']) == 12
        assert set(chain_ids) == {t['id'] for t in final['tasks']}
        statuses.extend(t['state']['outcome']['status'] for t in final['tasks'])
        pubs = [e for e in typed(events, 'committed-state') if e['service'] == service]
        assert pubs and pubs[-1]['state'] == state and pubs[-1]['seq'] == final['document_sequences'][-1]
        assert [e['seq'] for e in pubs] == sorted({e['seq'] for e in pubs})
        assert max(len(e['state']['active']) for e in pubs) == 2 and all(len(e['state']['active']) <= 2 for e in pubs)
    assert Counter(statuses) == {'aborted': 6, 'completed': 18}
    ack = typed(events, 'effect-acknowledged')
    assert len(ack) == 9 and Counter(e['source'] for e in ack) == {'created': 8, 'lookup': 1}
    assert {(f"service{e['service']}", e['key']): e['receipt'] for e in ack} == receipts
    recovered = load(d / 'stage2-recovered.json')
    post = next(r for r in admitted if (r['service'], r['stage'], r['intent']) == (0, 1, 'post'))
    assert next(a for a in recovered['server']['authority'] if a[:2] == [post['scope'], post['conversation']]) == [post['scope'], post['conversation'], 2, 0]
    assert recovered['states'][0]['requests'][post['key']]['cancelled'] is True
    assert recovered['states'][0]['effectIntents'][post['key']]['receipt'] == expected_receipt(post)
    latencies = sorted(e['epoch_ms'] - by_key[e['service'], e['key']]['offered_epoch_ms'] for e in terminals)
    http = typed(events, 'http-result')
    assert all(math.isfinite(e['elapsed_ms']) and e['elapsed_ms'] >= 0 and 0 <= e['request_body_bytes'] <= 4096 and 0 <= e['response_body_bytes'] <= 16384 for e in http)
    return {'arrivals': 18, 'host_reservations': 12, 'overloaded': 6, 'admission_calls': 26,
            'exact_retries': 4, 'changed_conflicts': 4, 'native_generation_tasks': 12, 'native_tool_tasks': 12,
            'faux_provider_calls': 12, 'remote_effects': 9, 'effect_GETs': 13, 'effect_POSTs': 14,
            'host_terminals': 12, 'native_terminal_tasks': 24, 'recovered_reservations': 5,
            'maximum_active_per_session': 2, 'final_active': 0,
            'terminal_latency_ms': {'n': 12, **{f'p{p}': latencies[math.ceil(12 * p / 100) - 1] for p in (50, 95)}, 'max': max(latencies)},
            'admission_latency_ms': {'n': len(calls), 'max': max(e['elapsed_ms'] for e in calls)},
            'HTTP_request_body_bytes': sum(e['request_body_bytes'] for e in http),
            'HTTP_response_body_bytes': sum(e['response_body_bytes'] for e in http)}
