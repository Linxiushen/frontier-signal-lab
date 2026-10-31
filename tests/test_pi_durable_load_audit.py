"""Independent negative controls for accepted-work identity and evidence gaps."""
import copy
import unittest

from experiments.pi_durable_load_audit import quantiles, validate_observation, validate_records


def records(capacity=2):
    sessions = [10, 20, 30, 40]
    identities = {'sessions': sessions, 'requests': [], 'terminals': {}}
    tasks, events, effects, denied, cancelled = [], [], {}, [], []
    active_state = {'capacity': capacity, 'requests': {}, 'active': {str(i): i for i in range(capacity)},
                    'effects': {}, 'denied': [], 'cancelled': []}
    events.append({'type': 'committed-state', 'seq': 1, 'state': copy.deepcopy(active_state)})
    for stage in range(3):
        for index, session in enumerate(sessions):
            request_id = f's{stage}-r{index}'; key = f'{session}:{request_id}'
            request = {'stage': stage, 'index': index, 'session': session, 'requestId': request_id,
                       'payload': 'effect-' + request_id, 'key': key, 'at_epoch_ms': 100,
                       'status': 'admit' if index < capacity else 'overloaded'}
            event = {'type': 'admission', 'stage': stage, 'session': session, 'requestId': request_id,
                     'key': key, 'status': request['status'], 'elapsed_ms': 1.0}
            if index < capacity:
                task_id = 1000 + stage * 4 + index; request['taskId'] = event['taskId'] = task_id
                if stage == 0 and index == 1:
                    outcome = {'status': 'completed', 'result': 'denied'}; denied.append(key)
                elif stage == 1 and index == 0:
                    outcome = {'status': 'aborted'}; cancelled.append(key)
                else:
                    outcome = {'status': 'completed', 'result': 'committed'}
                    effects[key] = {'count': 1, 'payload': request['payload']}
                tasks.append({'id': task_id, 'conversationId': session, 'input': {'key': key, 'payload': request['payload']},
                              'state': {'status': 'terminal', 'outcome': outcome}})
                identities['terminals'][str(task_id)] = {'at_epoch_ms': 150, 'outcome': outcome}
                active_state['requests'][key] = {'taskId': task_id}
                if stage < 2 and not (stage == 0 and index == 1) and not (stage == 1 and index == 0):
                    events.append({'type': 'recovered-finish', 'stage': stage + 1, 'taskId': task_id, 'key': key})
            identities['requests'].append(request); events.append(event)
        first = identities['requests'][stage * 4]
        events.extend([
            {'type': 'admission', 'stage': stage, 'status': 'duplicate', 'key': first['key'], 'taskId': first['taskId'],
             'session': first['session'], 'requestId': first['requestId'], 'elapsed_ms': 1.0},
            {'type': 'admission', 'stage': stage, 'status': 'conflict', 'key': first['key'],
             'session': first['session'], 'requestId': first['requestId'], 'elapsed_ms': 1.0},
            {'type': 'admission', 'stage': stage, 'status': 'unauthorized', 'key': f'{sessions[0]}:stale-{stage}',
             'session': first['session'], 'requestId': f'stale-{stage}', 'version': 0, 'elapsed_ms': 1.0}])
    final = {**active_state, 'active': {}, 'effects': effects, 'denied': denied, 'cancelled': cancelled}
    events.append({'type': 'committed-state', 'seq': 99, 'state': final})
    return [capacity, identities, [{'state': final}] * 3, events, tasks, copy.deepcopy(final)]


class PiDurableLoadAuditTests(unittest.TestCase):
    def test_both_fixed_capacities_have_distinct_denominators(self):
        for capacity, committed in ((2, 4), (4, 10)):
            result = validate_records(*records(capacity))
            self.assertEqual(result['committed_effects'], committed)
            self.assertEqual(result['effect_eligible_offered'], 10)

    def test_extra_or_wrong_payload_effect_is_rejected(self):
        for mutation in ('extra', 'payload'):
            values = records()
            if mutation == 'extra': values[2][-1]['state']['effects']['orphan'] = {'count': 1, 'payload': 'bad'}
            else: next(iter(values[2][-1]['state']['effects'].values()))['payload'] = 'bad'
            values[-1] = copy.deepcopy(values[2][-1]['state'])
            with self.assertRaises(AssertionError): validate_records(*values)

    def test_cross_conversation_task_assignment_is_rejected(self):
        values = records(); values[4][0]['conversationId'] = 20
        with self.assertRaises(AssertionError): validate_records(*values)

    def test_duplicate_alias_to_different_task_is_rejected(self):
        values = records()
        next(e for e in values[3] if e.get('status') == 'duplicate')['taskId'] += 1
        with self.assertRaises(AssertionError): validate_records(*values)

    def test_missing_recovered_finish_or_terminal_is_rejected(self):
        for missing in ('recovered', 'terminal'):
            values = records()
            if missing == 'recovered': values[3].remove(next(e for e in values[3] if e['type'] == 'recovered-finish'))
            else: values[1]['terminals'].pop(next(iter(values[1]['terminals'])))
            with self.assertRaises(AssertionError): validate_records(*values)

    def test_transient_capacity_overflow_is_rejected(self):
        values = records(); values[3][0]['state']['active']['excess'] = 999
        with self.assertRaises(AssertionError): validate_records(*values)

    def test_negative_clock_duration_and_nonfinite_timings_are_rejected(self):
        values = records(); next(iter(values[1]['terminals'].values()))['at_epoch_ms'] = 99
        with self.assertRaises(AssertionError): validate_records(*values)
        for invalid in (-1, float('nan'), float('inf')):
            with self.assertRaises(AssertionError): quantiles([invalid])

    def test_pid_stage_and_sink_byte_coverage_are_checked(self):
        processes = [{'pid': 50 + s, 'stage': s, 'forced_termination': s < 2,
                      'returncode': 1 if s < 2 else 0, 'memory_samples': [{}]} for s in range(3)]
        snapshots = [{'stage': s, 'pid': 50 + s, 'capacity': 2, 'sink': 'direct',
                      'state': {'active': {'held': 1} if s < 2 else {}, 'effects': {str(i): {} for i in range((1, 2, 4)[s])}}} for s in range(3)]
        events = [[{'pid': 50 + s, 'stage': s}] for s in range(3)]
        ready = [{'stage': s, 'pid': 50 + s, 'effectCount': (1, 2, 4)[s], 'closed': s == 2} for s in range(3)]
        sinks = [{'sink': 'direct', 'sinkCalls': 1, 'sinkBytes': 12, 'callback_ms': 0, 'final_flush_ms': 0} for _ in range(3)]
        args = [2, 'direct', processes, snapshots, events, ready, sinks, [12] * 3]
        validate_observation(*args)
        for mutation in ('pid', 'bytes', 'stage', 'nan'):
            bad = copy.deepcopy(args)
            if mutation == 'pid': bad[4][0][0]['pid'] = 777
            elif mutation == 'bytes': bad[6][0]['sinkBytes'] += 1
            elif mutation == 'stage': bad[3][0]['stage'] = 2
            else: bad[6][1]['callback_ms'] = float('nan')
            with self.assertRaises(AssertionError): validate_observation(*bad)


if __name__ == '__main__':
    unittest.main()
