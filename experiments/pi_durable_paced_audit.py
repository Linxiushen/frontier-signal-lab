"""Saved-record acceptance for the finite time-paced, two-Session native caller."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from experiments.pi_durable_load_audit import quantiles


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def validate_identity(request, task, terminal, effect):
    assert task['state']['status'] == 'terminal'
    assert task['id'] == request['taskId'] and task['conversationId'] == request['conversation_id']
    assert task['input']['key'] == request['key'] and task['input']['payload'] == request['payload']
    assert task['input']['session'] == request['conversation_id']
    assert task['input']['version'] == request['stage'] + 1 and task['input']['hold'] == request['hold']
    intent = request['intent']
    outcome = {'status': 'aborted'} if intent in ('pre-abort', 'post-abort') else {
        'status': 'completed', 'result': 'denied' if intent == 'deny' else 'committed'}
    assert task['state']['outcome'] == terminal['outcome'] == outcome
    assert terminal['at_epoch_ms'] >= request['at_epoch_ms']
    expected = None if intent in ('pre-abort', 'deny') else {'count': 1, 'payload': request['payload']}
    assert effect == expected


def validate_controls(requests):
    controls = [r for r in requests if r['kind'] == 'control']
    assert len(controls) == 14
    assert Counter(r['intent'] for r in controls) == {'recover': 4, 'deny': 2, 'pre-abort': 2, 'post-abort': 2, 'commit': 4}
    assert all(r.get('taskId') for r in controls)
    assert len({(r['service'], r['taskId']) for r in controls}) == len(controls)
    return controls


def validate_queue(mode, requests, snapshots, events):
    loads = [r for r in requests if r['kind'] == 'load']
    assert len(loads) == 36 and len({r['id'] for r in loads}) == 36
    assert {(r['stage'], r['id']) for r in loads} == {
        (stage, f's{stage}-load{i}') for stage in range(3) for i in range(12)}
    finish = [entry for snapshot in snapshots for entry in snapshot['queue']['finished']]
    assert len(finish) == 36 and len({f['request']['id'] for f in finish}) == 36
    by_id = {f['request']['id']: f for f in finish}
    attempts = [e for e in events if e['type'] == 'queue-attempt']
    for r in loads:
        f = by_id[r['id']]
        assert f['request'] == r and f['finishedMs'] >= f['offeredMs']
        rows = [e for e in attempts if e['id'] == r['id']]
        assert len(rows) == f['attempts'] and 1 <= len(rows) <= (8 if mode == 'retry' else 1)
        assert [e['attempt'] for e in rows] == list(range(1, len(rows) + 1))
        assert rows[0]['atMs'] >= f['offeredMs']
        assert f['finishedMs'] >= rows[-1]['atMs']
        assert f['result'] == rows[-1]['result']
        assert all(e['result']['status'] == 'overloaded' for e in rows[:-1])
        pending_events = [e for e in events if e['type'] == 'queue-pending' and e['id'] == r['id']]
        queued = len(rows) > 1 or f['disposition'] == 'exhausted'
        assert len(pending_events) == int(queued)
        if queued:
            assert events.index(rows[0]) < events.index(pending_events[0])
            if len(rows) > 1: assert events.index(pending_events[0]) < events.index(rows[1])
        for before, after in zip(rows, rows[1:]):
            assert after['atMs'] - before['atMs'] >= 20
            assert after['atMs'] - f['offeredMs'] < 200
        admitted = f['disposition'] == 'admit'
        assert bool(r.get('taskId')) == admitted
        assert f['disposition'] in (('admit', 'refused') if mode == 'refuse' else ('admit', 'backpressured', 'exhausted'))
        assert f['result']['status'] == ('admit' if admitted else 'overloaded')
        if f['disposition'] == 'exhausted':
            assert f['attempts'] == 8 or f['finishedMs'] - f['offeredMs'] >= 200
        if f['disposition'] in ('backpressured', 'refused'):
            assert f['attempts'] == 1
        finish_events = [e for e in events if e['type'] == 'queue-finish' and e['id'] == r['id']]
        assert len(finish_events) == 1
        assert all(finish_events[0][k] == f[k] for k in ('disposition', 'attempts', 'result'))
        if admitted:
            assert f['result']['taskId'] == r['taskId'] and f['result']['key'] == r['key']
        assert r['service'] == int(r['id'].split('load')[1]) % 2
        assert r['scheduled_ms'] == int(r['id'].split('load')[1]) * 10
        assert r['offered_ms'] >= r['scheduled_ms']
    assert len(attempts) == sum(f['attempts'] for f in finish)
    assert len([e for e in events if e['type'] == 'queue-finish']) == 36
    assert all(not s['queue']['pending'] and 0 <= s['queue']['maximumPending'] <= (4 if mode == 'retry' else 0) for s in snapshots)
    assert all(0 <= e['pending'] <= 4 for e in events if e['type'] in ('queue-pending', 'queue-finish'))
    assert any(e['result']['status'] == 'overloaded' for e in attempts)
    if mode == 'retry':
        assert any(e['attempt'] > 1 for e in attempts)
    return {'unique_load_offered': 36, 'load_admission_attempts': len(attempts),
            'load_dispositions': dict(Counter(f['disposition'] for f in finish)),
            'maximum_pending': max(s['queue']['maximumPending'] for s in snapshots),
            'offered_lateness_ms': quantiles([r['offered_ms'] - r['scheduled_ms'] for r in loads])}


def audit_arm(directory, mode):
    directory = Path(directory)
    execution = load(directory / 'execution.json')
    ids = load(directory / 'identities.json')
    snapshots = [load(directory / f'stage{s}-snapshot.json') for s in range(3)]
    stages = [[json.loads(line) for line in (directory / f'stage{s}.jsonl').read_text(encoding='utf-8').splitlines()] for s in range(3)]
    events = [e for stage in stages for e in stage]
    processes = execution['processes']
    assert len(processes) == 3 and len({p['pid'] for p in processes}) == 3
    assert [p['forced_termination'] for p in processes] == [True, True, False]
    assert processes[0]['returncode'] != 0 and processes[1]['returncode'] != 0 and processes[2]['returncode'] == 0
    for s in range(3):
        ready, sink = load(directory / f'stage{s}-ready.json'), load(directory / f'stage{s}-sink.json')
        assert ready['stage'] == snapshots[s]['stage'] == processes[s]['stage'] == s
        assert ready['pid'] == snapshots[s]['pid'] == processes[s]['pid']
        assert ready['closed'] == (s == 2) and ready['held'] == (2 if s < 2 else 0)
        assert ready['mode'] == snapshots[s]['mode'] == mode
        assert len(stages[s]) == sink['events']
        assert (directory / f'stage{s}.jsonl').stat().st_size == sink['bytes']
        assert all(e['stage'] == s and e['pid'] == ready['pid'] for e in stages[s])
        assert all(math.isfinite(sink[k]) and sink[k] >= 0 for k in ('callback_ms', 'final_flush_ms'))
    assert len(ids['conversations']) == 2 and all(len(set(c)) == 2 for c in ids['conversations'])
    requests = ids['requests']
    assert len(requests) == len({r['id'] for r in requests}) == 50
    controls = validate_controls(requests)
    for r in requests:
        assert r['conversation'] == (0 if r['kind'] == 'load' or r['id'].endswith('recovery') else int(r['id'][-1]))
        assert r['hold'] == (r['intent'] != 'commit')
        assert r['payload'] == 'payload-' + r['id']
        if r.get('taskId'):
            assert r['key'] == f"{ids['conversations'][r['service']][r['conversation']]}:{r['id']}"
    metrics = validate_queue(mode, requests, snapshots, events)
    terminal_durations, committed_durations = [], []
    total_effects, load_effects, terminal_count = 0, 0, 0
    control_effects = Counter()
    recovered_count = 0
    for service in range(2):
        database = execution['databases'][service]
        final = snapshots[-1]['states'][service]
        assert database['integrity'] == 'ok' and database['document'] == final
        assert set(database['conversation_ids']) == set(ids['conversations'][service])
        assert len(database['conversation_ids']) == 2
        assert final['capacity'] == 2 and not final['active']
        for stage, snapshot in enumerate(snapshots):
            expected_auth = {str(c): {'version': stage + 1, 'allowed': True} for c in ids['conversations'][service]}
            if stage == 0: expected_auth[str(ids['conversations'][service][1])] = {'version': 99, 'allowed': False}
            assert snapshot['states'][service]['authority'] == expected_auth
        admitted = [r for r in requests if r['service'] == service and r.get('taskId')]
        tasks = {t['id']: t for t in database['tasks']}
        assert len(tasks) == len(database['tasks']) == len(admitted)
        assert set(tasks) == {r['taskId'] for r in admitted} == {v['taskId'] for v in final['requests'].values()}
        assert set(final['requests']) == {r['key'] for r in admitted}
        effects, denied, cancelled = {}, [], []
        for r in admitted:
            terminal = ids['terminals'][f"{service}:{r['taskId']}"]
            validate_identity({**r, 'conversation_id': ids['conversations'][service][r['conversation']]},
                              tasks[r['taskId']], terminal, final['effects'].get(r['key']))
            assert final['requests'][r['key']] == {'taskId': r['taskId'], 'fingerprint': hashlib.sha256(r['payload'].encode()).hexdigest()}
            duration = terminal['at_epoch_ms'] - r['at_epoch_ms']; terminal_durations.append(duration)
            if r['intent'] not in ('deny', 'pre-abort'):
                effects[r['key']] = {'count': 1, 'payload': r['payload']}
                if r['kind'] == 'load':
                    load_effects += 1; committed_durations.append(duration)
            if r['intent'] == 'deny': denied.append(r['key'])
            if r['intent'] in ('pre-abort', 'post-abort'): cancelled.append(r['key'])
            if r['kind'] == 'control': control_effects[r['intent']] += int(r['key'] in final['effects'])
        assert final['effects'] == effects and final['denied'] == denied and sorted(final['cancelled']) == sorted(cancelled)
        total_effects += len(effects); terminal_count += len(tasks)
        commits = [e for e in events if e['type'] == 'committed-state' and e['service'] == service]
        assert commits and [e['seq'] for e in commits] == sorted({e['seq'] for e in commits})
        assert commits[-1]['state'] == final
        assert all(len(e['state']['active']) <= 2 for e in commits)
        assert max(len(e['state']['active']) for e in commits) == 2
        assert commits[-1]['seq'] == database['retained_document_sequences'][-1]
        calls = [e for e in events if e['type'] == 'admission' and e['service'] == service]
        counts = Counter(e['status'] for e in calls)
        assert counts['duplicate'] == counts['conflict'] == counts['unauthorized'] == 3
        assert counts['admit'] == len(admitted)
        native_load = [e for e in calls if '-load' in e['requestId']]
        queue_load = [e for e in events if e['type'] == 'queue-attempt' and next(r for r in requests if r['id'] == e['id'])['service'] == service]
        assert Counter(e['requestId'] for e in native_load) == Counter(e['id'] for e in queue_load)
        for r in [r for r in requests if r['kind'] == 'load' and r['service'] == service]:
            native_rows = [e for e in native_load if e['requestId'] == r['id']]
            queued_rows = [e for e in queue_load if e['id'] == r['id']]
            assert [e['status'] for e in native_rows] == [e['result']['status'] for e in queued_rows]
        recovered = [e for e in events if e['type'] == 'recovered-finish' and e['service'] == service]
        assert len(recovered) == 2 and {e['stage'] for e in recovered} == {1, 2}
        assert {(e['stage'], e['id'], e['key'], e['taskId']) for e in recovered} == {
            (r['stage'] + 1, r['id'], r['key'], r['taskId']) for r in admitted if r['intent'] == 'recover'}
        assert all(e['recovered_state']['status'] == 'pending' and e['recovered_state']['checkpoint']['phase'] == 'finish' for e in recovered)
        recovered_count += len(recovered)
    assert len(ids['terminals']) == terminal_count
    assert not any(e['type'] in ('runtime-report', 'provider-access-denied', 'network-access-denied') for e in events)
    assert load_effects == metrics['load_dispositions'].get('admit', 0)
    # Load may be entirely refused in baseline. Do not invent a latency sample.
    return {**metrics, 'control_offered': len(controls), 'control_admitted': len(controls), 'total_terminal_tasks': terminal_count,
            'exact_effects': total_effects, 'load_effects': load_effects,
            'post_abort_effects_retained': control_effects['post-abort'], 'pre_abort_effects': control_effects['pre-abort'], 'denied_effects': control_effects['deny'],
            'all_admitted_observed_terminal_ms': quantiles(terminal_durations),
            'load_committed_observed_terminal_ms': quantiles(committed_durations) if committed_durations else None,
            'native_admission_ms': quantiles([e['elapsed_ms'] for e in events if e['type'] == 'admission']),
            'recovered_finish_tasks': recovered_count, 'final_active': 0, 'observed_maximum_active_per_session': 2}
