"""Negative evidence controls for cancellation boundaries and bounded load records."""
import copy
import unittest

from experiments.pi_durable_paced_audit import validate_controls, validate_identity, validate_queue


def identity(intent):
    request = {'intent': intent, 'taskId': 7, 'conversation_id': 9, 'key': '9:a', 'payload': 'payload', 'at_epoch_ms': 100, 'stage': 1, 'hold': intent != 'commit'}
    outcome = {'status': 'aborted'} if intent in ('pre-abort', 'post-abort') else {'status': 'completed', 'result': 'denied' if intent == 'deny' else 'committed'}
    task = {'id': 7, 'conversationId': 9, 'input': {'key': '9:a', 'payload': 'payload', 'session': 9, 'version': 2, 'hold': request['hold']}, 'state': {'status': 'terminal', 'outcome': outcome}}
    terminal = {'at_epoch_ms': 200, 'outcome': outcome}
    effect = None if intent in ('deny', 'pre-abort') else {'count': 1, 'payload': 'payload'}
    return [request, task, terminal, effect]


def queue_records(mode):
    requests, snapshots, events = [], [], []
    for stage in range(3):
        finished = []
        for i in range(12):
            r = {'id': f's{stage}-load{i}', 'kind': 'load', 'stage': stage, 'service': i % 2,
                 'scheduled_ms': i * 10, 'offered_ms': i * 10 + 0.5}
            requests.append(r)
            status = 'refused' if mode == 'refuse' else 'backpressured'
            result = {'status': 'overloaded'}
            if mode == 'retry' and i < 4:
                r.update(taskId=i + 1, key=f'key-{stage}-{i}'); status = 'admit'
                result = {'status': 'admit', 'taskId': r['taskId'], 'key': r['key']}
            count = 2 if status == 'admit' else 1
            events.append({'type': 'queue-attempt', 'id': r['id'], 'attempt': 1, 'atMs': 100, 'result': {'status': 'overloaded'}})
            if count == 2:
                events.append({'type': 'queue-pending', 'id': r['id'], 'pending': 4})
                events.append({'type': 'queue-attempt', 'id': r['id'], 'attempt': 2, 'atMs': 121, 'result': result})
            finished.append({'request': r, 'disposition': status, 'result': result, 'offeredMs': 100, 'finishedMs': 122, 'attempts': count})
            events.append({'type': 'queue-finish', 'id': r['id'], 'disposition': status, 'attempts': count, 'result': result, 'pending': 0})
        snapshots.append({'queue': {'finished': finished, 'pending': [], 'maximumPending': 4 if mode == 'retry' else 0}})
    return [mode, requests, snapshots, events]


class PacedAuditTest(unittest.TestCase):
    def test_controls_cannot_be_omitted_or_share_a_native_task(self):
        controls = [{'kind': 'control', 'intent': intent, 'service': i % 2, 'taskId': i + 1}
                    for i, intent in enumerate(['recover'] * 4 + ['deny'] * 2 + ['pre-abort'] * 2 + ['post-abort'] * 2 + ['commit'] * 4)]
        self.assertEqual(len(validate_controls(controls)), 14)
        for mutation in ('missing', 'unadmitted', 'duplicate'):
            rows = copy.deepcopy(controls)
            if mutation == 'missing': rows.pop()
            if mutation == 'unadmitted': rows[4].pop('taskId')
            if mutation == 'duplicate': rows[4]['taskId'] = rows[2]['taskId']
            with self.assertRaises(AssertionError): validate_controls(rows)

    def test_cancellation_effect_boundaries(self):
        for intent in ('commit', 'recover', 'deny', 'pre-abort', 'post-abort'):
            validate_identity(*identity(intent))
        for intent in ('deny', 'pre-abort'):
            args = identity(intent); args[3] = {'count': 1, 'payload': 'payload'}
            with self.assertRaises(AssertionError): validate_identity(*args)
        args = identity('post-abort'); args[3] = None
        with self.assertRaises(AssertionError): validate_identity(*args)

    def test_wrong_effect_identity_and_payload_rejected(self):
        for corruption in ('count', 'payload', 'task', 'conversation', 'terminal', 'time', 'session', 'version', 'hold'):
            args = identity('commit')
            if corruption == 'count': args[3]['count'] = 2
            if corruption == 'payload': args[3]['payload'] = 'changed'
            if corruption == 'task': args[1]['id'] = 8
            if corruption == 'conversation': args[1]['conversationId'] = 10
            if corruption == 'terminal': args[1]['state']['status'] = 'running'
            if corruption == 'time': args[2]['at_epoch_ms'] = 99
            if corruption == 'session': args[1]['input']['session'] = 10
            if corruption == 'version': args[1]['input']['version'] = 1
            if corruption == 'hold': args[1]['input']['hold'] = True
            with self.assertRaises(AssertionError): validate_identity(*args)

    def test_both_bounded_caller_records(self):
        for mode in ('refuse', 'retry'):
            result = validate_queue(*queue_records(mode))
            self.assertEqual(result['unique_load_offered'], 36)

    def test_missing_or_duplicated_disposition_rejected(self):
        for mutation in ('missing', 'duplicate', 'event'):
            args = queue_records('retry')
            if mutation == 'missing': args[2][0]['queue']['finished'].pop()
            if mutation == 'duplicate': args[2][0]['queue']['finished'].append(copy.deepcopy(args[2][0]['queue']['finished'][0]))
            if mutation == 'event': args[3].remove(next(e for e in args[3] if e['type'] == 'queue-finish'))
            with self.assertRaises(AssertionError): validate_queue(*args)

    def test_queue_capacity_and_attempt_timing_rejected(self):
        for mutation in ('capacity', 'early', 'late', 'attempts', 'unexhausted'):
            args = queue_records('retry')
            row = next(e for e in args[3] if e['type'] == 'queue-attempt' and e['attempt'] == 2)
            if mutation == 'capacity': args[2][0]['queue']['maximumPending'] = 5
            if mutation == 'early': row['atMs'] = 119
            if mutation == 'late': row['atMs'] = 300
            if mutation == 'attempts': args[2][0]['queue']['finished'][0]['attempts'] = 9
            if mutation == 'unexhausted': args[2][0]['queue']['finished'][5]['disposition'] = 'exhausted'
            with self.assertRaises(AssertionError): validate_queue(*args)

    def test_refusal_cannot_hide_retry_or_pending(self):
        for mutation in ('attempt', 'pending'):
            args = queue_records('refuse')
            if mutation == 'pending': args[2][0]['queue']['pending'].append({'id': 'lost'})
            else: args[2][0]['queue']['finished'][0]['attempts'] = 2
            with self.assertRaises(AssertionError): validate_queue(*args)

    def test_false_last_result_prefix_or_queued_provenance_rejected(self):
        for mutation in ('last', 'prefix', 'pending'):
            args = queue_records('retry')
            rows = [e for e in args[3] if e['type'] == 'queue-attempt' and e['id'] == 's0-load0']
            if mutation == 'last': rows[-1]['result'] = {'status': 'overloaded'}
            if mutation == 'prefix': rows[0]['result'] = {'status': 'admit'}
            if mutation == 'pending': args[3].remove(next(e for e in args[3] if e['type'] == 'queue-pending'))
            with self.assertRaises(AssertionError): validate_queue(*args)

    def test_exhaustion_with_native_overload_key_is_valid(self):
        args = queue_records('retry')
        f = args[2][0]['queue']['finished'][5]
        result = {'status': 'overloaded', 'key': 'native-key'}
        f.update(disposition='exhausted', result=result, finishedMs=300)
        attempt = next(e for e in args[3] if e['type'] == 'queue-attempt' and e['id'] == 's0-load5')
        attempt['result'] = result
        index = args[3].index(attempt)
        args[3].insert(index + 1, {'type': 'queue-pending', 'id': 's0-load5', 'pending': 1})
        finish = next(e for e in args[3] if e['type'] == 'queue-finish' and e['id'] == 's0-load5')
        finish.update(disposition='exhausted', result=result)
        self.assertEqual(validate_queue(*args)['load_dispositions']['exhausted'], 1)


if __name__ == '__main__':
    unittest.main()
