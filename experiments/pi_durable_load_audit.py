"""Pure saved-record validation for the native bounded-burst caller."""
from collections import Counter
import json
import math
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def quantiles(values):
    assert values and all(math.isfinite(v) and v >= 0 for v in values)
    ordered = sorted(values)
    return {'n': len(values), 'min': ordered[0], 'max': ordered[-1],
            **{f'p{p}': ordered[math.ceil(p / 100 * len(ordered)) - 1] for p in (50, 95, 99)}}


def validate_records(capacity, identities, snapshots, events, native_tasks, document):
    assert capacity in (2, 4)
    assert len(identities['sessions']) == len(set(identities['sessions'])) == 4
    requests = identities['requests']
    assert len(requests) == 12
    assert {(r['stage'], r['index']) for r in requests} == {(s, i) for s in range(3) for i in range(4)}
    assert len({(r['session'], r['requestId']) for r in requests}) == 12
    for r in requests:
        assert r['session'] == identities['sessions'][r['index']]
        assert r['requestId'] == f"s{r['stage']}-r{r['index']}"
        assert r['payload'] == 'effect-' + r['requestId']
        assert r['status'] == ('admit' if r['index'] < capacity else 'overloaded')
    admitted = [r for r in requests if r['status'] == 'admit']
    final = snapshots[-1]['state']
    assert final == document and final['capacity'] == capacity and not final['active']
    assert len(final['requests']) == len(admitted) == 3 * capacity
    tasks = {t['id']: t for t in native_tasks}
    assert len(tasks) == len(native_tasks) == len(admitted)
    assert set(tasks) == {r['taskId'] for r in admitted} == {r['taskId'] for r in final['requests'].values()}
    assert set(identities['terminals']) == {str(t) for t in tasks}
    expected_effects, denied, cancelled, elapsed, committed_elapsed = {}, [], [], [], []
    for request in admitted:
        task = tasks[request['taskId']]
        assert task['state']['status'] == 'terminal'
        assert task['conversationId'] == request['session']
        assert task['input']['key'] == request['key'] and task['input']['payload'] == request['payload']
        assert final['requests'][request['key']]['taskId'] == request['taskId']
        if request['stage'] == 0 and request['index'] == 1:
            outcome = {'status': 'completed', 'result': 'denied'}
            denied.append(request['key'])
        elif request['stage'] == 1 and request['index'] == 0:
            outcome = {'status': 'aborted'}
            cancelled.append(request['key'])
        else:
            outcome = {'status': 'completed', 'result': 'committed'}
            expected_effects[request['key']] = {'count': 1, 'payload': request['payload']}
        assert task['state']['outcome'] == outcome
        terminal = identities['terminals'][str(request['taskId'])]
        assert terminal['outcome'] == outcome
        duration = terminal['at_epoch_ms'] - request['at_epoch_ms']
        assert duration >= 0
        elapsed.append(duration)
        if outcome.get('result') == 'committed':
            committed_elapsed.append(duration)
    assert final['effects'] == expected_effects and len(expected_effects) == 3 * capacity - 2
    assert final['denied'] == denied and final['cancelled'] == cancelled
    admissions = [e for e in events if e['type'] == 'admission']
    counts = Counter(e['status'] for e in admissions)
    expected_counts = {'admit': 3 * capacity, 'overloaded': 12 - 3 * capacity,
                       'duplicate': 3, 'conflict': 3, 'unauthorized': 3}
    assert set(counts) <= set(expected_counts)
    assert all(counts.get(k, 0) == v for k, v in expected_counts.items()) and len(admissions) == 21
    for stage in range(3):
        stage_calls = [e for e in admissions if e['stage'] == stage]
        assert len(stage_calls) == 7
        for request in [r for r in requests if r['stage'] == stage]:
            matches = [e for e in stage_calls if e['session'] == request['session'] and
                       e['requestId'] == request['requestId'] and e['status'] == request['status']]
            assert len(matches) == 1
            assert matches[0]['key'] == request['key']
            if request['status'] == 'admit':
                assert matches[0]['taskId'] == request['taskId']
        first = next(r for r in requests if r['stage'] == stage and r['index'] == 0)
        duplicate = next(e for e in stage_calls if e['status'] == 'duplicate')
        assert duplicate['key'] == first['key'] and duplicate['taskId'] == first['taskId']
        assert next(e for e in stage_calls if e['status'] == 'conflict')['key'] == first['key']
        unauthorized = next(e for e in stage_calls if e['status'] == 'unauthorized')
        assert unauthorized['session'] == first['session'] and unauthorized['version'] == 0
    assert not any(e['type'] in ('runtime-report', 'provider-access-denied', 'network-access-denied') for e in events)
    committed = [e for e in events if e['type'] == 'committed-state']
    sequences = [e['seq'] for e in committed]
    assert sequences and sequences == sorted(set(sequences))
    assert committed[-1]['state'] == final
    assert all(len(e['state']['active']) <= capacity for e in committed)
    assert max(len(e['state']['active']) for e in committed) == capacity
    recovered = [e for e in events if e['type'] == 'recovered-finish']
    expected_recovered = {(s + 1, r['taskId'], r['key']) for s in (0, 1) for r in admitted
                          if r['stage'] == s and not (s == 0 and r['index'] == 1) and not (s == 1 and r['index'] == 0)}
    assert len(recovered) == len(expected_recovered) == 2 * (capacity - 1)
    assert {(e['stage'], e['taskId'], e['key']) for e in recovered} == expected_recovered
    return {'unique_offered': 12, 'effect_eligible_offered': 10, 'admitted': len(admitted),
            'admission_counts': expected_counts, 'denied': 1, 'aborted': 1,
            'committed_effects': len(expected_effects), 'maximum_active': capacity, 'final_active': 0,
            'recovered_finish_tasks': len(recovered), 'document_sequences': sequences,
            'arrival_to_observed_terminal_epoch_ms': quantiles(elapsed),
            'committed_arrival_to_observed_terminal_epoch_ms': quantiles(committed_elapsed),
            'admission_ms': quantiles([e['elapsed_ms'] for e in admissions])}


def validate_observation(capacity, sink, processes, snapshots, stage_events, ready, sinks, raw_bytes):
    assert len(processes) == len(snapshots) == len(stage_events) == len(ready) == len(sinks) == 3
    assert len({p['pid'] for p in processes}) == 3
    assert [p['stage'] for p in processes] == [0, 1, 2]
    assert [p['forced_termination'] for p in processes] == [True, True, False]
    assert processes[0]['returncode'] != 0 and processes[1]['returncode'] != 0 and processes[2]['returncode'] == 0
    for stage in range(3):
        assert snapshots[stage]['stage'] == ready[stage]['stage'] == stage
        assert snapshots[stage]['pid'] == ready[stage]['pid'] == processes[stage]['pid']
        assert snapshots[stage]['capacity'] == capacity and snapshots[stage]['sink'] == sink
        assert all(e['pid'] == processes[stage]['pid'] and e['stage'] == stage for e in stage_events[stage])
        assert len(snapshots[stage]['state']['active']) == (capacity - 1 if stage < 2 else 0)
        assert ready[stage]['effectCount'] == len(snapshots[stage]['state']['effects']) == (stage + 1) * capacity - (stage + 1 if stage < 2 else 2)
        assert sinks[stage]['sink'] == sink and sinks[stage]['sinkCalls'] == len(stage_events[stage])
        assert sinks[stage]['sinkBytes'] == raw_bytes[stage]
        assert all(math.isfinite(sinks[stage][key]) and sinks[stage][key] >= 0 for key in ('callback_ms', 'final_flush_ms'))
        assert processes[stage]['memory_samples']
    assert ready[2]['closed'] is True


def audit_arm(directory, capacity):
    directory = Path(directory)
    execution = load(directory / 'execution.json')
    snapshots = [load(directory / f'stage{s}-snapshot.json') for s in range(3)]
    logs = [(directory / f'stage{s}.jsonl').read_bytes() for s in range(3)]
    stage_events = [[json.loads(line) for line in raw.decode('utf-8').splitlines()] for raw in logs]
    validate_observation(capacity, execution['sink'], execution['processes'], snapshots, stage_events,
                         [load(directory / f'stage{s}-ready.json') for s in range(3)],
                         [load(directory / f'stage{s}-sink.json') for s in range(3)], [len(raw) for raw in logs])
    events = [event for entries in stage_events for event in entries]
    return validate_records(capacity, load(directory / 'identities.json'), snapshots, events,
                            execution['database']['tasks'], execution['database']['document'])
