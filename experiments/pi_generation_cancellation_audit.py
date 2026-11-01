"""Prepared saved-byte acceptance; no native execution or evidence of a run."""
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


def validate_host(request, host, terminal):
    expected = {k: request[k] for k in ('conversation', 'requestId', 'payload', 'version')}
    expected['fingerprint'] = hashlib.sha256(request['payload'].encode()).hexdigest()
    if request['intent'] in ('pre-cancel', 'post-cancel', 'pending-cancel'):
        expected['cancelled'] = True
    if 'submissionId' in request:
        expected['submissionId'] = request['submissionId']
    if terminal:
        expected['terminal'] = request['terminal']
    assert host == expected, 'Exact durable reservation, cancellation, native link and terminal identity'


def validate_effects(request, events, endpoint):
    """Bind every effect observation to the actual native tool, including extra rows."""
    r = request
    own = [e for e in events if e.get('service') == r['service'] and e.get('key') == r['key']]
    enters = [e for e in own if e['type'] == 'tool-enter']
    effects = [e for e in own if e['type'] == 'tool-effect']
    if r['intent'] in ('pending-deny', 'pending-cancel'):
        assert not enters and not effects and 'submissionId' not in r
        assert r['key'] not in endpoint['state']['effects']
        assert not [n for n in endpoint['submissions'] if n.get('requestId') == r['requestId']
                    and n['conversationId'] == r['conversation']]
        return []
    assert len(enters) == 1 and enters[0]['stage'] == r['stage'], 'No tool execution after durable cancellation/reopen'
    proxy = {**r, 'intent': {'pre-cancel': 'pre-abort', 'post-cancel': 'post-abort'}.get(r['intent'], r['intent'])}
    api = request['expected_api']
    chain = validate_native_chain(proxy, endpoint, enters, expected_api=api)
    expected_effects = [] if r['intent'] == 'pre-cancel' else ['commit']
    assert [e['decision'] for e in effects] == expected_effects
    assert all(e['taskId'] == chain[1] and e['stage'] == r['stage'] for e in effects), 'Exact effect task identity'
    expected = None if r['intent'] == 'pre-cancel' else {'count': 1, 'payload': r['payload']}
    assert endpoint['state']['effects'].get(r['key']) == expected
    return chain


def validate_cardinality(endpoint, native_count, completed, aborted):
    for table in ('tasks', 'submissions', 'entries'):
        assert len(endpoint[table]) == len({r['id'] for r in endpoint[table]}), 'Unique native record identities'
    assert len(endpoint['submissions']) == native_count and len(endpoint['tasks']) == 2 * native_count
    assert Counter(t['kind'] for t in endpoint['tasks']) == {'pi.generation': native_count, 'pi.tool': native_count}
    assert all(t['state']['status'] == 'terminal' for t in endpoint['tasks'])
    assert Counter(t['state']['outcome']['status'] for t in endpoint['tasks']) == {'completed': completed, 'aborted': aborted}
    kinds = Counter(e['kind'] for e in endpoint['entries'])
    assert kinds['pi.user'] == kinds['pi.assistant'] == kinds['pi.tool-result'] == native_count, 'Exact final entry counts'
    assert set(kinds) <= {'pi.user', 'pi.assistant', 'pi.tool-result', 'pi.system'}


def audit(directory):
    d = Path(directory); ids = load(d / 'identities.json'); requests = ids['requests']
    events = [json.loads(line) for stage in range(3) for line in
              (d / f'stage{stage}.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    assert len(requests) == 18 and len({(r['service'], r['key']) for r in requests}) == 18
    expected = {}
    for s in range(2):
        assert len(ids['conversations'][s]) == len(set(ids['conversations'][s])) == 2
        for g in range(3):
            for c in range(2):
                intent = ('pre-cancel' if c == 0 else 'pending-deny') if g == 0 else (
                    'post-cancel' if c == 0 else 'pending-cancel') if g == 1 else 'commit'
                expected[s, f's{g}-db{s}-{intent}-{c}'] = (g, ids['conversations'][s][c], intent)
            expected[s, f's{g}-db{s}-overload-0'] = (g, ids['conversations'][s][0], 'overload')
    assert {(r['service'], r['requestId']): (r['stage'], r['conversation'], r['intent']) for r in requests} == expected
    assert all(r['key'] == f"{r['conversation']}:{r['requestId']}" and r['payload'] == 'payload-' + r['requestId']
               and r['version'] == r['stage'] + 1 and r['status'] == ('overloaded' if r['intent'] == 'overload' else 'admit') for r in requests)
    admitted = [r for r in requests if r['status'] == 'admit']; by_key = {(r['service'], r['key']): r for r in admitted}
    native = [r for r in admitted if r['intent'] not in ('pending-deny', 'pending-cancel')]
    assert len(admitted) == 12 and len(native) == 8
    assert not [e for e in events if e['type'] in ('network-access-denied', 'runtime-report')]
    identity = [e for e in events if e['type'] == 'provider-identity']
    assert len(identity) == 6
    apis = {(e['service'], e['stage']): e['api'] for e in identity}; assert len(apis) == 6
    assert len({apis[0, g] for g in range(3)}) == 3
    assert all(re.fullmatch(r'faux:[0-9]+:[a-z0-9]+', apis[0, g]) for g in range(3))
    assert all(apis[1, g] == 'frontier-faux-cancellation' for g in range(3))
    assert all((e['provider'], e['model'], e['mode']) == ('faux', 'faux-1',
        'default-dynamic' if e['service'] == 0 else 'configured-stable') for e in identity)
    for type_, count, expected_keys in (
        ('provider-request', 8, {(r['service'], r['key']) for r in native}),
        ('tool-enter', 8, {(r['service'], r['key']) for r in native}),
        ('tool-effect', 6, {(r['service'], r['key']) for r in native if r['intent'] != 'pre-cancel'}),
        ('native-duplicate', 8, {(r['service'], r['key']) for r in native}),
        ('reservation-held', 4, {(r['service'], r['key']) for r in admitted if r['intent'].startswith('pending-')}),
        ('cancel-mark-held', 6, {(r['service'], r['key']) for r in admitted if r['intent'] in ('pre-cancel', 'post-cancel', 'pending-cancel')})):
        own = [e for e in events if e['type'] == type_]
        assert len(own) == count and {(e['service'], e['key']) for e in own} == expected_keys, type_
        assert all(e['stage'] == by_key[e['service'], e['key']]['stage'] for e in own)
    for e in [e for e in events if e['type'] == 'provider-request']:
        assert e['api'] == apis[e['service'], e['stage']] and e['providerSession'] and 'frontier_effect' in e['offeredTools']
    for e in [e for e in events if e['type'] == 'native-duplicate']:
        assert e['submissionId'] == by_key[e['service'], e['key']]['submissionId']
    for e in [e for e in events if e['type'] in ('reservation-held', 'cancel-mark-held')]:
        assert e['phase'] == ('after-reserve' if e['type'] == 'reservation-held' else 'after-cancel-mark')
    expected_recovery = {(r['stage'] + 1, r['service'], r['key']) for r in admitted if r['stage'] < 2}
    assert len(ids['recovered']) == 8 and {(r['stage'], r['service'], r['key']) for r in ids['recovered']} == expected_recovery
    for r in ids['recovered']:
        original = by_key[r['service'], r['key']]
        assert r['intent'] == original['intent'] and r.get('submissionId') == original.get('submissionId')
    before = [e for e in events if e['type'] == 'recovery-before-resume']
    assert len(before) == 8 and {(e['stage'], e['service'], e['key']) for e in before} == expected_recovery
    for e in before:
        assert e['state'] == load(d / f"service{e['service']}-stage{e['stage'] - 1}-endpoint.json")['state']
    execution = load(d / 'execution.json'); processes = execution['processes']
    assert len(processes) == len({p['pid'] for p in processes}) == 3
    assert [p['stage'] for p in processes] == [0, 1, 2] and [p['forced_termination'] for p in processes] == [True, True, False]
    for g in range(3):
        ready = load(d / f'stage{g}-ready.json'); sink = load(d / f'stage{g}-sink.json')
        own = [e for e in events if e['stage'] == g]
        assert ready['pid'] == processes[g]['pid'] and ready['stage'] == g and ready['held'] == (4 if g < 2 else 0) and ready['closed'] == (g == 2)
        assert own and all(e['pid'] == ready['pid'] for e in own)
        assert sink['events'] == len(own) and sink['bytes'] == (d / f'stage{g}.jsonl').stat().st_size
        assert all(math.isfinite(sink[k]) and sink[k] >= 0 for k in ('callback_ms', 'flush_ms'))
    for s in range(2):
        final = load(d / f'service{s}-stage2-endpoint.json'); state = final['state']
        own = [r for r in admitted if r['service'] == s]
        assert len(final['conversations']) == 2 and {c['id'] for c in final['conversations']} == set(ids['conversations'][s])
        validate_cardinality(final, 4, 4, 4)
        assert not state['active'] and state['capacity'] == 2 and len(state['effects']) == 3
        assert state['authority'] == {str(c): {'version': 3, 'allowed': True} for c in ids['conversations'][s]}
        assert set(state['requests']) == {r['key'] for r in own}
        assert {n['id'] for n in final['submissions']} == {r['submissionId'] for r in own if 'submissionId' in r}
        chain_ids = []
        for r in own:
            validate_host(r, state['requests'][r['key']], True)
            if r['intent'].startswith('pending-'):
                assert r['terminal'] == {'status': 'denied-before-submit' if r['intent'] == 'pending-deny' else 'cancelled-before-submit'}
            chain_ids.extend(validate_effects({**r, 'expected_api': apis[s, r['stage']]}, events, final))
        assert len(chain_ids) == len(set(chain_ids)) == 8
        for g in (0, 1):
            endpoint = load(d / f'service{s}-stage{g}-endpoint.json'); snapshot = load(d / f'stage{g}-snapshot.json')
            st = endpoint['state']; assert st == snapshot['states'][s]
            expected_auth = {str(c): {'version': g + 1, 'allowed': True} for c in ids['conversations'][s]}
            if g == 0: expected_auth[str(ids['conversations'][s][1])] = {'version': 99, 'allowed': False}
            assert st['authority'] == expected_auth and st['capacity'] == 2
            held = [r for r in snapshot['held'] if r['service'] == s]
            assert len(held) == 2 and {r['key'] for r in held} == {r['key'] for r in own if r['stage'] == g}
            assert st['active'] == {r['key']: True for r in held}
            assert len(st['requests']) == 2 * (g + 1) and len(endpoint['submissions']) == g + 1
            assert len(endpoint['tasks']) == 2 * (g + 1)
            assert len(st['effects']) == g
            for r in held:
                canonical = by_key[s, r['key']]
                assert all(r[k] == canonical[k] for k in r) and 'terminal' not in r
                validate_host(r, st['requests'][r['key']], False)
                if r['intent'].startswith('pending-'):
                    assert r['heldPhase'] == 'after-reserve' and 'submissionId' not in r
                    assert not [n for n in endpoint['submissions'] if n.get('requestId') == r['requestId']]
                else:
                    enters = [e for e in events if e['type'] == 'tool-enter' and e['service'] == s and e['key'] == r['key']]
                    original = validate_native_chain(r, endpoint, enters, False, expected_api=apis[s, g])
                    assert all(i in chain_ids for i in original)
            assert {t['id'] for t in endpoint['tasks']} <= {t['id'] for t in final['tasks']}
        pubs = [e for e in events if e['type'] == 'committed-state' and e['service'] == s]
        assert pubs and [e['seq'] for e in pubs] == sorted({e['seq'] for e in pubs})
        assert pubs[-1]['state'] == state and pubs[-1]['seq'] == final['document_sequences'][-1]
        assert all(len(e['state']['active']) <= 2 for e in pubs) and max(len(e['state']['active']) for e in pubs) == 2
    terminal = [e for e in events if e['type'] == 'terminal']
    assert len(terminal) == 12 and {(e['service'], e['key']) for e in terminal} == set(by_key)
    assert all(e['terminal'] == by_key[e['service'], e['key']]['terminal'] for e in terminal)
    latencies = sorted(e['epoch_ms'] - by_key[e['service'], e['key']]['offered_epoch_ms'] for e in terminal)
    assert all(x >= 0 for x in latencies)
    return {'arrivals': 18, 'admitted': 12, 'overloaded': 6, 'native_generation_tasks': 8,
            'native_tool_tasks': 8, 'faux_provider_calls': 8, 'local_effects': 6,
            'denied_before_submit': 2, 'cancelled_before_submit': 2, 'cancel_mark_crash_checkpoints': 6,
            'recovered_reservations': 8, 'maximum_active_per_session': 2, 'final_active': 0,
            'terminal_latency_ms': {'n': 12, **{f'p{p}': latencies[math.ceil(12 * p / 100) - 1] for p in (50, 95, 99)}}}
