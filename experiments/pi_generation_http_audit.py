"""Finite saved-byte audit of the native caller and its separate HTTP effect DB."""
from collections import Counter
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from experiments.pi_generation_admission_audit import read_endpoint
from experiments.pi_generation_v2_audit import validate_native_chain


def load(path):
    return json.loads(Path(path).read_bytes())


def effect_endpoint(db):
    assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    return {'authority': [list(r) for r in db.execute('SELECT * FROM authority ORDER BY scope,conversation')],
            'effects': [{**json.loads(r[1]), 'count': r[2]} for r in db.execute('SELECT * FROM effects ORDER BY key')],
            'attempts': [list(r) for r in db.execute('SELECT * FROM attempts ORDER BY seq')]}


def expected_receipt(r):
    return {k: r[k] for k in ('key', 'payload', 'version', 'conversation')} | {
        'scope': f"service{r['service']}",
        'fingerprint': hashlib.sha256(r['payload'].encode()).hexdigest(), 'count': 1}


def validate_scoped_authority(authority, conversations, stage):
    expected = sorted([f'service{service}', c, stage + 1, int(not (stage == 0 and index == 0))]
                      for service, own in enumerate(conversations) for index, c in enumerate(own))
    assert authority == expected, 'Remote authority must isolate every native Session and conversation'


def endpoint_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def verify_copied_endpoint(directory, stage, service=None):
    """Re-read a stopped backup without creating WAL/SHM files or trusting JSON."""
    d = Path(directory)
    stem = f'effects-stage{stage}' if service is None else f'service{service}-stage{stage}'
    database = (d / f'{stem}.sqlite').resolve()
    assert database.is_file(), 'Missing stopped SQLite backup'
    # These copies are complete, closed SQLite backups, never a live/WAL endpoint.
    # immutable avoids auxiliary files changing the saved raw inventory.
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=0.02)) as db:
        actual = (effect_endpoint if service is None else read_endpoint)(db)
    expected = load(d / f'{stem}-endpoint.json')
    comparison = load(d / f'{stem}-copy-comparison.json')
    assert actual == expected, 'Copied SQLite endpoint differs from saved endpoint JSON'
    assert comparison['equal'] is True
    assert comparison['source_endpoint_sha256'] == comparison['copy_endpoint_sha256'] == endpoint_digest(actual)
    if service is not None:
        assert comparison['service'] == service and comparison['stage'] == stage
    return actual


def validate_trace_evidence(directory, events, execution):
    d = Path(directory)
    for group in ('processes', 'servers'):
        rows = execution[group]
        assert len(rows) == len({r['pid'] for r in rows}) == 3
        assert [r['stage'] for r in rows] == [0, 1, 2]
    for stage in range(3):
        ready = load(d / f'stage{stage}-ready.json')
        snapshot = load(d / f'stage{stage}-snapshot.json')
        sink = load(d / f'stage{stage}-sink.json')
        process = execution['processes'][stage]
        assert process['ready'] == ready
        assert ready['stage'] == snapshot['stage'] == stage
        assert ready['pid'] == snapshot['pid'] == process['pid']
        assert ready['pending'] == (4 if stage == 0 else 2 if stage == 1 else 0)
        assert ready['closed'] is (stage == 2)
        rows = [e for e in events if e['stage'] == stage]
        assert rows and all(e['pid'] == ready['pid'] for e in rows)
        assert sink['events'] == len(rows)
        assert sink['bytes'] == (d / f'stage{stage}.jsonl').stat().st_size
        assert all(math.isfinite(sink[k]) and sink[k] >= 0 for k in ('callback_ms', 'flush_ms'))
        server_ready = load(d / f'effect-server{stage}-ready.json')
        assert server_ready['stage'] == stage and server_ready['pid'] == execution['servers'][stage]['pid']
        server_events = [json.loads(line) for line in (d / f'effect-server{stage}.jsonl').read_text(encoding='utf-8').splitlines()]
        assert server_events and all(e['pid'] == server_ready['pid'] and e['stage'] == stage for e in server_events)
        assert [e for e in server_events if e['type'] == 'server-ready'] == [{'type': 'server-ready', **server_ready,
            **{k: server_events[0][k] for k in ('epoch_ms', 'monotonic_ns')}}]
        assert sum(e['type'] == 'server-closed' for e in server_events) == 1
        assert server_events[-1]['type'] == 'server-closed'
    assert len(events) == sum(load(d / f'stage{stage}-sink.json')['events'] for stage in range(3))


def validate_recovery_evidence(directory, ids, admitted, events):
    expected = {(r['stage'] + 1, r['service'], r['key'], r['submissionId'])
                for r in admitted if r['intent'] in ('remote-deny', 'pre-cancel', 'post-cancel')}
    actual = [(r['stage'], r['service'], r['key'], r['submissionId']) for r in ids['recovered']]
    assert len(actual) == len(set(actual)) == len(expected) == 6 and set(actual) == expected
    before = [e for e in events if e['type'] == 'recovery-before-resume']
    assert len(before) == 6
    assert {(e['stage'], e['service'], e['key']) for e in before} == {r[:3] for r in expected}
    for e in before:
        prior = load(Path(directory) / f"service{e['service']}-stage{e['stage'] - 1}-endpoint.json")['state']
        assert e['state'] == prior, 'Recovery-before-resume must observe the exact prior stopped state'


def validate_preabort_evidence(directory, admitted, events, apis):
    """Bind paused recovery marks to all six original, stopped native chains."""
    expected = {(r['stage'] + 1, r['service'], r['key']): r for r in admitted
                if r['intent'] in ('remote-deny', 'pre-cancel', 'post-cancel')}
    marks = [e for e in events if e['type'] == 'recovery-native-preabort']
    identities = [(e['stage'], e['service'], e['key']) for e in marks]
    assert len(identities) == len(set(identities)) == len(expected) == 6
    assert set(identities) == set(expected), 'Preabort must cover each original recovery stage and service'
    for event in marks:
        r = expected[event['stage'], event['service'], event['key']]
        assert event['scheduling'] == 'paused'
        assert event['conversation'] == r['conversation'] and event['submissionId'] == r['submissionId']
        prior = load(Path(directory) / f"service{r['service']}-stage{r['stage']}-endpoint.json")
        identity = prior['state']['effectIntents'][r['key']]['identity']
        assert identity == {k: v for k, v in expected_receipt(r).items() if k != 'count'}, \
            'Stopped intent must retain the exact scoped remote identity'
        entered = [e for e in events if e['type'] == 'tool-enter' and e['key'] == r['key']
                   and e['service'] == r['service'] and e['stage'] == r['stage']]
        assert len(entered) == 1
        generation, tool = validate_native_chain(r, prior, entered, settled=False,
                                                expected_api=apis[r['service'], r['stage']])
        assert event['generationTaskId'] == generation and event['toolTaskId'] == tool, \
            'Preabort must mark the exact original generation and tool tasks'
        assert next(t for t in prior['tasks'] if t['id'] == tool)['state']['status'] == 'running'


def validate_task_coverage(chain_ids, tasks):
    native_ids = [t['id'] for t in tasks]
    assert len(chain_ids) == len(set(chain_ids)) == len(native_ids) == len(set(native_ids)) == 12
    assert set(chain_ids) == set(native_ids), 'Every native task must belong to exactly one original chain'


def validate_effect_controls(admitted, events):
    expected = {r['key']: r for r in admitted if r['intent'] == 'post-cancel'}
    assert len(expected) == 2
    for kind in ('duplicate-effect-control', 'changed-effect-control'):
        controls = [e for e in events if e['type'] == kind]
        assert len(controls) == 2 and {e['key'] for e in controls} == set(expected)
        for event in controls:
            r = expected[event['key']]
            assert event['stage'] == 2 and event['service'] == r['service']
            if kind == 'duplicate-effect-control':
                assert event['status'] == 200 and event['receipt'] == expected_receipt(r)
            else:
                payload = 'changed-' + r['payload']
                assert event['status'] == 409 and event['payload'] == payload
                assert event['fingerprint'] == hashlib.sha256(payload.encode()).hexdigest(), \
                    'Conflict control must use a valid fingerprint of the changed payload'


def validate_attempts(admitted, attempts):
    assert [r[0] for r in attempts] == list(range(1, 29))
    assert Counter((r[1], r[3]) for r in attempts) == {('GET', 404): 12, ('GET', 200): 2,
        ('POST', 201): 8, ('POST', 403): 2, ('POST', 200): 2, ('POST', 409): 2}
    for r in admitted:
        own = [a for a in attempts if a[2] == r['key']]
        want = [('GET', 404), ('POST', 403)] if r['intent'] == 'remote-deny' else [('GET', 404)] if r['intent'] == 'pre-cancel' else (
            [('GET', 404), ('POST', 201), ('GET', 200), ('POST', 200), ('POST', 409)] if r['intent'] == 'post-cancel' else [('GET', 404), ('POST', 201)])
        assert [(a[1], a[3]) for a in own] == want, r['key']



def audit(directory):
    d = Path(directory); ids = load(d / 'identities.json'); requests = ids['requests']
    events = [json.loads(line) for stage in range(3) for line in (d / f'stage{stage}.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    expected = {}
    for s in range(2):
        assert len(ids['conversations'][s]) == len(set(ids['conversations'][s])) == 2
        for stage, c, intent in [(0, 0, 'remote-deny'), (0, 1, 'pre-cancel'), (0, 0, 'overload'),
                                 (1, 0, 'post-cancel'), (1, 1, 'commit'),
                                 (2, 0, 'commit'), (2, 1, 'commit'), (2, 0, 'overload')]:
            expected[s, f's{stage}-db{s}-{intent}-{c}'] = (stage, ids['conversations'][s][c], intent)
    assert len(requests) == 16
    assert {(r['service'], r['requestId']): (r['stage'], r['conversation'], r['intent']) for r in requests} == expected
    assert all(r['key'] == f"{r['conversation']}:{r['requestId']}" and r['payload'] == 'payload-' + r['requestId']
               and r['version'] == r['stage'] + 1 and r['status'] == ('overloaded' if r['intent'] == 'overload' else 'admit') for r in requests)
    admitted = [r for r in requests if r['intent'] != 'overload']; by_key = {r['key']: r for r in admitted}
    assert len(admitted) == len(by_key) == len(ids['native']) == 12
    assert {(r['service'], r['key'], r['submissionId']) for r in ids['native']} == {
        (r['service'], r['key'], r['submissionId']) for r in admitted}
    for native in ids['native']:
        original = by_key[native['key']]
        assert all(native[k] == original[k] for k in ('service', 'stage', 'intent', 'conversation',
            'requestId', 'payload', 'version', 'submissionId', 'offered_epoch_ms', 'status'))
        assert native['terminal'] == original['terminal']
    assert len(ids['recovered']) == 6 and Counter(r['stage'] for r in ids['recovered']) == {1: 4, 2: 2}
    execution = load(d / 'execution.json')
    validate_trace_evidence(d, events, execution)
    validate_recovery_evidence(d, ids, admitted, events)
    assert not [e for e in events if e['type'] in ('network-access-denied', 'runtime-report')]
    identities = [e for e in events if e['type'] == 'provider-identity']
    apis = {(e['service'], e['stage']): e['api'] for e in identities}; assert len(identities) == len(apis) == 6
    assert len({apis[0, stage] for stage in range(3)}) == 3
    assert all(re.fullmatch(r'faux:[0-9]+:[a-z0-9]+', apis[0, stage]) for stage in range(3))
    assert all(apis[1, stage] == 'frontier-faux-http' for stage in range(3))
    assert all((e['provider'], e['model'], e['mode']) == ('faux', 'faux-1', 'default-dynamic' if e['service'] == 0 else 'configured-stable') for e in identities)
    validate_preabort_evidence(d, admitted, events, apis)
    for kind in ('tool-enter', 'provider-request', 'terminal'):
        rows = [e for e in events if e['type'] == kind]
        assert len(rows) == 12 and {e['key'] for e in rows} == set(by_key), kind
        assert all(e['service'] == by_key[e['key']]['service'] for e in rows)
        if kind == 'terminal':
            assert all(e['terminal'] == by_key[e['key']]['terminal'] for e in rows)
        elif kind == 'provider-request':
            assert all(e['stage'] == by_key[e['key']]['stage'] and e['api'] == apis[e['service'], e['stage']]
                       and e['providerSession'] and 'frontier_effect' in e['offeredTools'] for e in rows)
    for r in admitted:
        assert [e['stage'] for e in events if e['type'] == 'tool-enter' and e['key'] == r['key']] == [r['stage']]
        terminal_stage = r['stage'] if r['intent'] == 'commit' else r['stage'] + 1
        assert [e['stage'] for e in events if e['type'] == 'terminal' and e['key'] == r['key']] == [terminal_stage]
    remote = load(d / 'effect-server2-final.json')
    effectful = [r for r in admitted if r['intent'] in ('commit', 'post-cancel')]
    receipts = {r['key']: expected_receipt(r) for r in effectful}
    assert {r['key']: r for r in remote['effects']} == receipts and len(receipts) == 8
    validate_attempts(admitted, remote['attempts'])
    validate_effect_controls(admitted, events)
    for stage, effect_count, attempt_count, active_count in [(0, 0, 0, 4), (1, 4, 14, 2), (2, 8, 28, 0)]:
        snapshot = load(d / f'stage{stage}-snapshot.json')
        assert len(snapshot['pending']) == active_count
        server = verify_copied_endpoint(d, stage)
        assert server == load(d / f'effect-server{stage}-final.json')
        assert len(server['effects']) == effect_count and len(server['attempts']) == attempt_count
        validate_scoped_authority(server['authority'], ids['conversations'], stage)
        initial = load(d / f'effect-server{stage}-initial-snapshot.json')
        if stage:
            assert initial == load(d / f'effect-server{stage - 1}-final.json')
        else:
            assert initial == {'authority': [], 'effects': [], 'attempts': []}
        assert load(d / f'effects-stage{stage}-endpoint.json') == server
        assert load(d / f'effects-stage{stage}-copy-comparison.json')['equal'] is True
        server_events = [json.loads(line) for line in (d / f'effect-server{stage}.jsonl').read_text(encoding='utf-8').splitlines()]
        before_count = 0 if stage == 0 else 0 if stage == 1 else 14
        observed = [e for e in server_events if e['type'] == 'effect-request']
        assert [(e['method'], e['key'], e['status']) for e in observed] == [(r[1], r[2], r[3]) for r in server['attempts'][before_count:]]
        assert not [e for e in server_events if e['type'] == 'request-rejected']
        held = [e['key'] for e in server_events if e['type'] == 'reply-held-after-commit']
        assert len(held) == (2 if stage == 1 else 0)
        assert set(held) == ({r['key'] for r in admitted if r['intent'] == 'post-cancel'} if stage == 1 else set())
        for s in range(2):
            endpoint = verify_copied_endpoint(d, stage, s); state = endpoint['state']
            assert state == snapshot['states'][s]
            assert len(state['active']) == active_count // 2
            assert len(state['requests']) == len(state['effectIntents']) == 2 * (stage + 1)
            assert len(endpoint['submissions']) == 2 * (stage + 1) and len(endpoint['tasks']) == 4 * (stage + 1)
            assert len(state['effects']) == (0 if stage == 0 else 1 if stage == 1 else 4)
            assert state['authority'] == {str(c): {'version': stage + 1, 'allowed': True} for c in ids['conversations'][s]}
            assert load(d / f'service{s}-stage{stage}-copy-comparison.json')['equal'] is True
            for intent in state['effectIntents'].values():
                assert intent['identity']['fingerprint'] == hashlib.sha256(intent['identity']['payload'].encode()).hexdigest()
    task_statuses = []
    for s in range(2):
        endpoint = load(d / f'service{s}-stage2-endpoint.json'); state = endpoint['state']
        own = [r for r in admitted if r['service'] == s]
        assert len(state['requests']) == len(state['effectIntents']) == len(endpoint['submissions']) == 6
        assert len(endpoint['tasks']) == 12 and len(state['effects']) == 4 and state['active'] == {}
        chain_ids = []
        for r in own:
            request = state['requests'][r['key']]
            assert all(request[k] == r[k] for k in ('conversation', 'requestId', 'payload', 'version', 'submissionId', 'terminal'))
            intent = state['effectIntents'][r['key']]
            assert intent['identity'] == {k: v for k, v in expected_receipt(r).items() if k != 'count'}
            if r['intent'] in ('commit', 'post-cancel'):
                assert intent['status'] == 'committed' and intent['receipt'] == receipts[r['key']]
                assert state['effects'][r['key']] == {'payload': r['payload'], 'count': 1, 'receipt': receipts[r['key']]}
            else:
                assert intent['status'] == ('denied' if r['intent'] == 'remote-deny' else 'aborted')
                assert r['key'] not in state['effects']
            assert bool(request.get('cancelled')) == (r['intent'] in ('pre-cancel', 'post-cancel'))
            assert bool(request.get('effectDenied')) == (r['intent'] == 'remote-deny')
            mapped = {**r, 'intent': 'pre-abort' if r['intent'] != 'commit' else 'commit'}
            enters = [e for e in events if e['type'] == 'tool-enter' and e['key'] == r['key']]
            chain_ids.extend(validate_native_chain(mapped, endpoint, enters, expected_api=apis[s, r['stage']]))
        validate_task_coverage(chain_ids, endpoint['tasks'])
        task_statuses.extend(t['state']['outcome']['status'] for t in endpoint['tasks'])
        pubs = [e for e in events if e['type'] == 'committed-state' and e['service'] == s]
        assert pubs and pubs[-1]['state'] == state and all(len(e['state']['active']) <= 2 for e in pubs)
        assert [e['seq'] for e in pubs] == sorted({e['seq'] for e in pubs})
        assert pubs[-1]['seq'] == endpoint['document_sequences'][-1]
        assert max(len(e['state']['active']) for e in pubs) == 2
    assert Counter(task_statuses) == {'aborted': 12, 'completed': 12}
    acknowledgements = [e for e in events if e['type'] == 'effect-acknowledged']
    assert Counter(e['source'] for e in acknowledgements) == {'created': 6, 'lookup': 2}
    assert {e['key']: e['receipt'] for e in acknowledgements} == receipts
    latencies = sorted(e['epoch_ms'] - by_key[e['key']]['offered_epoch_ms'] for e in events if e['type'] == 'terminal')
    assert len(latencies) == 12 and all(x >= 0 for x in latencies)
    return {'arrivals': 16, 'host_reservations': 12, 'overloaded': 4, 'native_generation_tasks': 12,
            'native_tool_tasks': 12, 'faux_provider_calls': 12, 'remote_effects': 8, 'effect_GETs': 14, 'effect_POSTs': 14,
            'host_terminals': 12, 'native_terminal_tasks': 24, 'recovered_reservations': 6, 'final_active': 0,
            'terminal_latency_ms': {'n': 12, **{f'p{p}': latencies[math.ceil(12 * p / 100) - 1] for p in (50, 95, 99)}}}
