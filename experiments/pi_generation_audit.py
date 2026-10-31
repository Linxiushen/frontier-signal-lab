"""Pure saved-record checks for the fixed native GenerationTask/faux/tool slice."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def read_endpoint(database):
    """Read native JSON-encoded document address and full table records, no live code."""
    docs = [r[0] for r in database.execute('SELECT id FROM documents WHERE kind = ?',
                                          (json.dumps('frontier.generation-service'),))]
    assert len(docs) == 1, 'Expected one exact encoded service document'
    revisions = database.execute('SELECT seq,content FROM document_revisions WHERE document_id=? ORDER BY seq', (docs[0],)).fetchall()
    assert revisions
    result = {'state': json.loads(revisions[-1][1]), 'document_sequences': [r[0] for r in revisions]}
    for table in ('tasks', 'entries', 'submissions', 'conversations'):
        result[table] = [json.loads(r[0]) for r in database.execute('SELECT record FROM ' + table + ' ORDER BY id')]
    assert database.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    return result


def validate_effect(request, effect):
    expected = None if request['intent'] in ('deny', 'pre-abort', 'overload') else {
        'count': 1, 'payload': request['payload']}
    assert effect == expected, request['key']


def validate_native_chain(request, endpoint, tool_entries, settled=True):
    """Join exact native submission -> user/assistant entry -> generation -> tool."""
    r = request
    tables = {}
    for table in ('tasks', 'entries', 'submissions'):
        rows = endpoint[table]
        tables[table] = {row['id']: row for row in rows}
        assert len(tables[table]) == len(rows), table
    submission = tables['submissions'][r['submissionId']]
    assert submission['type'] == 'input' and submission['requestId'] == r['requestId']
    assert submission['conversationId'] == r['conversation']
    user = tables['entries'][submission['entry']]
    assert user['kind'] == 'pi.user' and user['conversationId'] == r['conversation']
    assert len(user['model']) == 1 and user['model'][0]['role'] == 'user'
    args = {'key': r['key'], 'payload': r['payload'], 'version': r['version']}
    assert json.loads(user['model'][0]['content']) == args
    assert tool_entries and len({e['taskId'] for e in tool_entries}) == 1
    tool = tables['tasks'][tool_entries[0]['taskId']]
    assert tool['kind'] == 'pi.tool' and tool['version'] == 2
    assert tool['conversationId'] == r['conversation'] and tool['background'] is False
    assert tool['input']['kind'] == 'model'
    assistant = tables['entries'][tool['input']['assistant']]
    assert assistant['kind'] == 'pi.assistant' and assistant['conversationId'] == r['conversation']
    assert len(assistant['model']) == 1 and assistant['model'][0]['role'] == 'assistant'
    message = assistant['model'][0]
    assert (message['api'], message['provider'], message['model'], message['stopReason']) == ('faux', 'faux', 'faux-1', 'toolUse')
    calls = [c for c in assistant['model'][0]['content'] if c['type'] == 'toolCall']
    assert len(calls) == 1
    call = calls[0]
    call_id = 'call-' + hashlib.sha256(r['key'].encode()).hexdigest()[:24]
    assert call == {'type': 'toolCall', 'id': call_id, 'name': 'frontier_effect', 'arguments': args}
    assert tool['input'] == {'kind': 'model', 'assistant': assistant['id'], 'callId': call_id}
    assert all(e['conversation'] == r['conversation'] and e['callId'] == call_id for e in tool_entries)
    generation = tables['tasks'][tool['owner']]
    assert assistant['byTaskId'] == generation['id']
    assert generation['kind'] == 'pi.generation' and generation['version'] == 1
    assert generation['input'] == {} and generation['conversationId'] == r['conversation']
    assert generation['background'] is False and 'owner' not in generation
    if settled:
        assert submission == r['terminal']
        aborted = r['intent'] in ('pre-abort', 'post-abort')
        assert submission['status'] == ('unanswered' if aborted else 'done')
        if aborted: assert submission['reason'] == 'aborted'
        else: assert submission['answer'] == assistant['id']
        for t in (generation, tool):
            assert t['state']['status'] == 'terminal'
            assert t['state']['outcome']['status'] == ('aborted' if aborted else 'completed')
        results = [e for e in endpoint['entries'] if e['kind'] == 'pi.tool-result' and e.get('byTaskId') == tool['id']]
        assert len(results) == 1 and results[0]['conversationId'] == r['conversation']
        assert len(results[0]['model']) == 1
        result = results[0]['model'][0]
        assert result['role'] == 'toolResult' and result['toolCallId'] == call_id and result['toolName'] == 'frontier_effect'
        assert result['isError'] == (aborted or r['intent'] == 'deny')
        if not aborted:
            assert result['content'] == [{'type': 'text', 'text': 'denied' if r['intent'] == 'deny' else 'existing' if r['intent'] == 'recover' else 'commit'}]
    else:
        assert submission['status'] == 'placed'
        assert tool['state']['checkpoint'] == {'phase': 'execute', 'arguments': args, 'replay': 'safe'}
        assert generation['state']['status'] == 'waiting'
        checkpoint = generation['state']['checkpoint']
        assert checkpoint['phase'] == 'tools' and checkpoint['assistant'] == assistant['id']
        assert checkpoint['tools'] == [tool['id']] and checkpoint['pending'] == []
        assert generation['state']['on'] == [tool['id']] and generation['state']['policy'] == 'allSettled'
    return generation['id'], tool['id']


def validate_state(state, own, conversations, stage, held):
    admitted = [r for r in own if r['stage'] <= stage and r['status'] == 'admit']
    assert state['capacity'] == 2 and set(state['requests']) == {r['key'] for r in admitted}
    expected_auth = {str(c): {'version': stage + 1, 'allowed': True} for c in conversations}
    if stage == 0: expected_auth[str(conversations[1])] = {'version': 99, 'allowed': False}
    assert state['authority'] == expected_auth
    expected_effects = {}
    for r in admitted:
        stored = state['requests'][r['key']]
        expected = {'fingerprint': hashlib.sha256(r['payload'].encode()).hexdigest(),
                    'conversation': r['conversation'], 'payload': r['payload'], 'version': r['version'],
                    'submissionId': r['submissionId']}
        if r['key'] not in held: expected['terminal'] = r['terminal']
        assert stored == expected
        if r['intent'] not in ('deny', 'pre-abort'): expected_effects[r['key']] = {'count': 1, 'payload': r['payload']}
    assert state['effects'] == expected_effects
    assert state['active'] == {key: True for key in held}


def audit(directory):
    directory = Path(directory)
    identities = load(directory / 'identities.json')
    requests = identities['requests']
    assert len(requests) == 20 and len({(r['service'], r['key']) for r in requests}) == 20
    assert Counter(r['intent'] for r in requests) == {
        'recover': 4, 'deny': 2, 'pre-abort': 2, 'post-abort': 2, 'commit': 4, 'overload': 6}
    assert len(identities['recovered']) == 4
    assert Counter(r['stage'] for r in identities['recovered']) == {1: 2, 2: 2}
    events = [load_line for stage in range(3) for load_line in
              (json.loads(line) for line in (directory / f'stage{stage}.jsonl').read_text(encoding='utf8').splitlines())]
    execution = load(directory / 'execution.json')
    processes = execution['processes']
    assert len(processes) == len({p['pid'] for p in processes}) == 3
    assert [p['stage'] for p in processes] == [0, 1, 2]
    assert [p['forced_termination'] for p in processes] == [True, True, False]
    assert all(p['returncode'] != 0 for p in processes[:2]) and processes[2]['returncode'] == 0
    for stage in range(3):
        ready = load(directory / f'stage{stage}-ready.json')
        snapshot = load(directory / f'stage{stage}-snapshot.json')
        sink = load(directory / f'stage{stage}-sink.json')
        rows = [e for e in events if e['stage'] == stage]
        assert ready['stage'] == snapshot['stage'] == stage
        assert ready['pid'] == snapshot['pid'] == processes[stage]['pid']
        assert ready['held'] == (2 if stage < 2 else 0) and ready['closed'] == (stage == 2)
        assert all(e['pid'] == ready['pid'] for e in rows)
        assert sink['events'] == len(rows)
        assert sink['bytes'] == (directory / f'stage{stage}.jsonl').stat().st_size
        assert all(math.isfinite(sink[k]) and sink[k] >= 0 for k in ('callback_ms', 'flush_ms'))
    for r in requests:
        assert r['stage'] in (0, 1, 2) and r['service'] in (0, 1)
        assert r['version'] == r['stage'] + 1
        assert r['payload'] == 'payload-' + r['requestId']
        assert r['key'] == f"{r['conversation']}:{r['requestId']}"
        assert r['conversation'] in identities['conversations'][r['service']]
        assert r['status'] == ('overloaded' if r['intent'] == 'overload' else 'admit')
    expected_requests = {}
    for stage in range(3):
        for service in range(2):
            for c in range(2):
                intent = ('recover' if c == 0 else 'deny') if stage == 0 else ('pre-abort' if c == 0 else 'post-abort') if stage == 1 else 'commit'
                expected_requests[service, f's{stage}-db{service}-control{c}'] = (stage, identities['conversations'][service][c], intent)
            expected_requests[service, f's{stage}-db{service}-overflow'] = (stage, identities['conversations'][service][0], 'overload')
            if stage == 1: expected_requests[service, f's1-db{service}-recovery'] = (stage, identities['conversations'][service][0], 'recover')
    assert {(r['service'], r['requestId']): (r['stage'], r['conversation'], r['intent']) for r in requests} == expected_requests
    assert not [e for e in events if e['type'] in ('network-access-denied', 'runtime-report')]
    admitted = [r for r in requests if r['status'] == 'admit']
    assert len(admitted) == 14
    provider = [e for e in events if e['type'] == 'provider-request']
    assert len(provider) == 14 and len({(e['service'], e['key']) for e in provider}) == 14
    admitted_keys = {(r['service'], r['key']) for r in admitted}
    assert {(e['service'], e['key']) for e in provider} == admitted_keys
    by_key = {(r['service'], r['key']): r for r in admitted}
    assert all(e['stage'] == by_key[e['service'], e['key']]['stage'] for e in provider)
    assert all(e['providerSession'] for e in provider)
    assert len({(e['service'], e['providerSession']) for e in provider}) == 4
    assert len([e for e in events if e['type'] == 'native-duplicate']) == 12
    native_duplicates = [e for e in events if e['type'] == 'native-duplicate']
    expected_duplicate_keys = {(r['service'], r['key']) for r in admitted if not r['requestId'].endswith('recovery')}
    assert {(e['service'], e['key']) for e in native_duplicates} == expected_duplicate_keys
    assert all(e['submissionId'] == by_key[e['service'], e['key']]['submissionId'] and
               e['stage'] == by_key[e['service'], e['key']]['stage'] for e in native_duplicates)
    terminal = [e for e in events if e['type'] == 'terminal']
    assert len(terminal) == 14 and len({(e['service'], e['key']) for e in terminal}) == 14
    assert {(e['service'], e['key']) for e in terminal} == admitted_keys
    assert all(e['submission'] == by_key[e['service'], e['key']]['terminal'] for e in terminal)
    assert all(e['stage'] == by_key[e['service'], e['key']]['stage'] +
               int(by_key[e['service'], e['key']]['intent'] == 'recover') for e in terminal)
    all_enters = [e for e in events if e['type'] == 'tool-enter']
    assert len(all_enters) == 18 and {(e['service'], e['key']) for e in all_enters} == admitted_keys
    assert len([e for e in events if e['type'] == 'tool-effect']) == 16
    expected_recovery = {(r['stage'] + 1, r['service'], r['key'], r['submissionId']) for r in admitted if r['intent'] == 'recover'}
    assert {(r['stage'], r['service'], r['key'], r['submissionId']) for r in identities['recovered']} == expected_recovery
    recovery_events = [e for e in events if e['type'] == 'recovery-before-resume']
    assert len(recovery_events) == 4
    assert {(r['stage'], r['service'], r['key'], r['submissionId']) for r in recovery_events} == expected_recovery
    for service in range(2):
        endpoint = load(directory / f'service{service}-stage2-endpoint.json')
        state = endpoint['state']
        assert len(endpoint['conversations']) == 2
        assert sorted(r['id'] for r in endpoint['conversations']) == sorted(identities['conversations'][service])
        assert not state['active'] and state['capacity'] == 2
        assert len(state['requests']) == 7 and len(state['effects']) == 5
        tasks = endpoint['tasks']
        entry_kinds = Counter(e['kind'] for e in endpoint['entries'])
        assert entry_kinds['pi.user'] == entry_kinds['pi.assistant'] == entry_kinds['pi.tool-result'] == 7
        assert set(entry_kinds) <= {'pi.user', 'pi.assistant', 'pi.tool-result', 'pi.system'}
        assert Counter(t['kind'] for t in tasks) == {'pi.generation': 7, 'pi.tool': 7}
        assert all(t['state']['status'] == 'terminal' for t in tasks)
        assert Counter(t['state']['outcome']['status'] for t in tasks) == {'completed': 10, 'aborted': 4}
        assert len(endpoint['submissions']) == 7
        by_submission = {s['id']: s for s in endpoint['submissions']}
        own = [r for r in requests if r['service'] == service]
        validate_state(state, own, identities['conversations'][service], 2, set())
        assert len({r['submissionId'] for r in own if r['status'] == 'admit'}) == 7
        assert set(by_submission) == {r['submissionId'] for r in own if r['status'] == 'admit'}
        native_chain_ids = []
        for r in own:
            validate_effect(r, state['effects'].get(r['key']))
            if r['intent'] == 'overload':
                assert 'submissionId' not in r and r['key'] not in state['requests']
                continue
            stored = state['requests'][r['key']]
            assert stored['payload'] == r['payload'] and stored['version'] == r['version']
            assert stored['submissionId'] == r['submissionId']
            submission = by_submission[r['submissionId']]
            assert submission == r['terminal'] == stored['terminal']
            expected = 'unanswered' if r['intent'] in ('pre-abort', 'post-abort') else 'done'
            assert submission['status'] == expected and submission['conversationId'] == r['conversation']
            if expected == 'unanswered': assert submission['reason'] == 'aborted'
            tool_entries = [e for e in events if e.get('service') == service and e['type'] == 'tool-enter' and e['key'] == r['key']]
            assert len(tool_entries) == (2 if r['intent'] == 'recover' else 1)
            assert len({e['taskId'] for e in tool_entries}) == 1
            tool = next(t for t in tasks if t['id'] == tool_entries[0]['taskId'])
            assert tool['kind'] == 'pi.tool' and tool['conversationId'] == r['conversation']
            native_chain_ids.extend(validate_native_chain(r, endpoint, tool_entries))
            assert [e['stage'] for e in tool_entries] == ([r['stage'], r['stage'] + 1] if r['intent'] == 'recover' else [r['stage']])
            effects = [e for e in events if e['type'] == 'tool-effect' and e['service'] == service and e['key'] == r['key']]
            expected_decisions = [] if r['intent'] == 'pre-abort' else ['commit', 'existing'] if r['intent'] == 'recover' else ['denied'] if r['intent'] == 'deny' else ['commit']
            assert [e['decision'] for e in effects] == expected_decisions
            assert all(e['taskId'] == tool['id'] for e in effects)
        assert len(native_chain_ids) == len(set(native_chain_ids)) == len(tasks)
        calls = [e for e in events if e['type'] == 'admission' and e['service'] == service]
        assert Counter(e['status'] for e in calls) == {'admit': 7, 'overloaded': 3, 'duplicate': 6, 'conflict': 6, 'unauthorized': 6}
        for r in own:
            decision = [e for e in calls if e['requestId'] == r['requestId'] and e['status'] == r['status']]
            assert len(decision) == 1 and decision[0]['key'] == r['key']
            assert decision[0]['payload'] == r['payload'] and decision[0]['version'] == r['version']
            if r['status'] == 'admit': assert decision[0]['submissionId'] == r['submissionId']
        publications = [e for e in events if e['type'] == 'committed-state' and e['service'] == service]
        assert publications and [p['seq'] for p in publications] == sorted({p['seq'] for p in publications})
        assert publications[-1]['state'] == state
        assert publications[-1]['seq'] == endpoint['document_sequences'][-1]
        assert max(len(e['state']['active']) for e in publications) == 2
        for stage in (0, 1):
            held_endpoint = load(directory / f'service{service}-stage{stage}-endpoint.json')
            stage_admitted = [r for r in own if r['status'] == 'admit' and r['stage'] <= stage]
            assert len(held_endpoint['submissions']) == len({s['id'] for s in held_endpoint['submissions']}) == len(stage_admitted)
            assert {s['id'] for s in held_endpoint['submissions']} == {r['submissionId'] for r in stage_admitted}
            assert len(held_endpoint['tasks']) == len({t['id'] for t in held_endpoint['tasks']}) == 2 * len(stage_admitted)
            assert set(t['id'] for t in held_endpoint['tasks']) <= set(t['id'] for t in tasks)
            final_tasks = {t['id']: t for t in tasks}
            assert all(t == final_tasks[t['id']] for t in held_endpoint['tasks'] if t['state']['status'] == 'terminal')
            held = load(directory / f'stage{stage}-snapshot.json')['held']
            own_held = [r for r in held if r['service'] == service]
            assert len(own_held) == 1
            r = own_held[0]
            assert r['intent'] == 'recover' and r['stage'] == stage
            canonical = by_key[service, r['key']]
            assert all(r[k] == canonical[k] for k in r)
            assert held_endpoint['state'] == load(directory / f'stage{stage}-snapshot.json')['states'][service]
            validate_state(held_endpoint['state'], own, identities['conversations'][service], stage, {r['key']})
            validate_effect(r, held_endpoint['state']['effects'].get(r['key']))
            live = [t for t in held_endpoint['tasks'] if t['state']['status'] != 'terminal']
            assert Counter(t['kind'] for t in live) == {'pi.generation': 1, 'pi.tool': 1}
            tool = next(t for t in live if t['kind'] == 'pi.tool')
            generation = next(t for t in live if t['kind'] == 'pi.generation')
            assert tool['state']['checkpoint']['phase'] == 'execute'
            assert generation['state']['status'] == 'waiting' and generation['state']['checkpoint']['phase'] == 'tools'
            assert generation['state']['checkpoint']['tools'] == [tool['id']]
            final_entries = [e for e in events if e.get('service') == service and e['type'] == 'tool-enter' and e['key'] == r['key']]
            assert validate_native_chain(r, held_endpoint, final_entries[:1], settled=False) == validate_native_chain(canonical, endpoint, final_entries)
            before_resume = next(e for e in recovery_events if e['service'] == service and e['key'] == r['key'])
            assert before_resume['state'] == held_endpoint['state']
    states = [e['state'] for e in events if e['type'] == 'committed-state']
    assert states and max(len(s['active']) for s in states) == 2
    assert all(len(s['active']) <= s['capacity'] == 2 for s in states)
    latencies = sorted(e['epoch_ms'] - next(r['offered_epoch_ms'] for r in admitted
        if r['service'] == e['service'] and r['key'] == e['key']) for e in terminal)
    assert all(x >= 0 for x in latencies)
    return {'admitted': 14, 'overloaded': 6, 'native_generation_tasks': 14, 'native_tool_tasks': 14,
            'faux_provider_calls': len(provider), 'local_effects': 10, 'recoveries': 4,
            'terminal_latency_ms': {'n': len(latencies), **{
                f'p{p}': latencies[math.ceil(len(latencies) * p / 100) - 1] for p in (50, 95, 99)}},
            'maximum_active_per_session': 2, 'final_active': 0}
