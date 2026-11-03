"""Offline malformed saved-evidence controls; no native runtime or HTTP."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import quote

from experiments.pi_receipt_recovery_audit import (
    expected_receipt, validate_attempts, validate_final_chain, validate_inventory,
    validate_races,
)


def inventory():
    ids = {'conversations': [[2, 8], [2, 8]], 'requests': [], 'retries': [], 'conflicts': []}
    for service in range(2):
        for stage in (0, 2):
            for c, intent in ((0, 'race' if stage == 0 else 'negative'),
                              (1, 'positive'), (0, 'overload')):
                request_id = f's{stage}-{intent}'
                conversation = ids['conversations'][service][c]
                r = {'stage': stage, 'service': service, 'scope': f'service{service}',
                     'conversation': conversation, 'requestId': request_id, 'intent': intent,
                     'version': 1 if stage == 0 else 2, 'key': f'{conversation}:{request_id}',
                     'payload': f'service{service}/{request_id}',
                     'status': 'overloaded' if intent == 'overload' else 'admit'}
                if intent != 'overload':
                    r['submissionId'] = stage * 10 + c + 3
                ids['requests'].append(r)
                if stage == 2 and intent == 'positive':
                    ids['retries'].append({'service': service, 'key': r['key'],
                                           'status': 'duplicate', 'submissionId': r['submissionId']})
                    ids['conflicts'].append({'service': service, 'key': r['key'], 'status': 'conflict'})
    return ids


def attempts(admitted):
    rows = []
    for r in admitted:
        pairs = [('GET', 404)]
        if r['intent'] == 'race':
            pairs += [('GET', 404)]
            if r['service']:
                pairs += [('POST', 403)]
            pairs += [('POST', 201)]
        elif r['intent'] == 'positive':
            pairs += [('POST', 201)]
        for method, status in pairs:
            rows.append([len(rows) + 1, method, r['scope'], r['key'], status])
    return rows


def chain(*, native_aborted=False, decision='aborted'):
    r = next(r for r in inventory()['requests'] if r['service'] == 1 and r['stage'] == 2 and r['intent'] == 'negative')
    args = {k: r[k] for k in ('key', 'payload', 'version')}
    call_id = 'call-' + hashlib.sha256(r['key'].encode()).hexdigest()[:24]
    r['terminal'] = {'id': r['submissionId'], 'type': 'input', 'requestId': r['requestId'],
                     'conversationId': r['conversation'], 'entry': 10,
                     'status': 'unanswered' if native_aborted else 'done',
                     **({'reason': 'aborted'} if native_aborted else {'answer': 11})}
    outcome = {'status': 'terminal', 'outcome': {'status': 'aborted' if native_aborted else 'completed'}}
    generation = {'id': 20, 'kind': 'pi.generation', 'version': 1, 'conversationId': r['conversation'],
                  'background': False, 'input': {}, 'state': copy.deepcopy(outcome)}
    tool = {'id': 21, 'kind': 'pi.tool', 'version': 2, 'conversationId': r['conversation'],
            'background': False, 'owner': 20, 'state': copy.deepcopy(outcome),
            'input': {'kind': 'model', 'assistant': 11, 'callId': call_id}}
    entries = [
        {'id': 10, 'kind': 'pi.user', 'conversationId': r['conversation'],
         'model': [{'role': 'user', 'content': json.dumps(args)}]},
        {'id': 11, 'kind': 'pi.assistant', 'conversationId': r['conversation'], 'byTaskId': 20,
         'model': [{'role': 'assistant', 'api': 'fixture-api', 'provider': 'faux', 'model': 'faux-1',
                    'stopReason': 'toolUse', 'content': [{'type': 'toolCall', 'id': call_id,
                                                       'name': 'frontier_effect', 'arguments': args}]}]},
        {'id': 12, 'kind': 'pi.tool-result', 'conversationId': r['conversation'], 'byTaskId': 21,
         'model': [{'role': 'toolResult', 'toolCallId': call_id, 'toolName': 'frontier_effect',
                    'isError': native_aborted or decision in ('denied', 'aborted'),
                    'content': [{'type': 'text', 'text': 'native cancellation' if native_aborted else decision}]}]},
    ]
    endpoint = {'tasks': [generation, tool], 'entries': entries, 'submissions': [copy.deepcopy(r['terminal'])]}
    enters = [{'taskId': 21, 'conversation': r['conversation'], 'callId': call_id}]
    return r, endpoint, enters


def race_evidence(directory):
    admitted = validate_inventory(inventory())[1]
    events = []
    for r in [r for r in admitted if r['intent'] == 'race']:
        s, key = r['service'], r['key']
        path = f"/effects/{r['scope']}/{quote(key, safe='')}"

        def emit(kind, **fields):
            events.append({'type': kind, 'stage': 1, 'service': s, 'key': key, **fields})

        def remote(allowed):
            events.append({'type': 'remote-authority', 'stage': 1, 'scope': r['scope'],
                           'conversation': r['conversation'], 'allowed': allowed})

        late = 'late-refusal' if s else 'late-missing'
        emit('reconcile-start', label='first')
        emit('http-result', method='GET', path=path, status=404)
        emit('race-lookup-missing', call=1)
        emit('race-apply-ready', call=1)
        emit('race-held', label='first-apply')
        if s:
            remote(False)
        emit('reconcile-start', label='second')
        emit('http-result', method='GET', path=path, status=404)
        emit('race-lookup-missing', call=2)
        if s:
            emit('race-apply-ready', call=2)
            emit('http-result', method='POST', path=path, status=403)
            emit('race-apply-result', call=2, result={'denied': True})
        emit('race-held', label=late)
        if s:
            remote(True)
        emit('race-released', label='first-apply')
        emit('http-result', method='POST', path=path, status=201)
        emit('race-apply-result', call=1, result={'receipt': expected_receipt(r), 'created': True})
        emit('effect-acknowledged', source='created')
        emit('reconcile-finish', label='first')
        receipt = expected_receipt(r)
        state = {'requests': {key: {}}, 'effects': {key: {'count': 1, 'payload': r['payload'], 'receipt': receipt}},
                 'effectIntents': {key: {'identity': {k: v for k, v in receipt.items() if k != 'count'},
                                         'status': 'committed', 'receipt': receipt}}}
        emit('race-first-acknowledged', state=copy.deepcopy(state))
        if s:
            remote(False)
        else:
            emit('host-authority-withdrawn')
        emit('race-released', label=late)
        emit('effect-disposition-superseded', status='denied', by='committed')
        emit('reconcile-finish', label='second')
        emit('race-receipt-preserved', state=copy.deepcopy(state))
        emit('cancel-mark-held')
        for name in ('acknowledged', 'preserved'):
            (directory / f'race{s}-{name}.json').write_text(json.dumps(state), encoding='utf-8')
    return admitted, events


class ReceiptRecoveryAuditTests(unittest.TestCase):
    def test_exact_inventory_joins_equal_keys_to_scope_and_retries(self):
        ids = inventory()
        _, admitted, by_key = validate_inventory(ids)
        self.assertEqual(len(by_key), 8)
        self.assertEqual(admitted[0]['key'], admitted[4]['key'])
        self.assertNotEqual(expected_receipt(admitted[0]), expected_receipt(admitted[4]))
        for field, value in (('scope', 'service1'), ('version', True), ('submissionId', True), ('payload', 'changed')):
            wrong = copy.deepcopy(ids); wrong['requests'][0][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate_inventory(wrong)
        wrong = copy.deepcopy(ids); wrong['retries'][0]['submissionId'] += 1
        with self.assertRaises(AssertionError):
            validate_inventory(wrong)

    def test_stale_refusal_must_precede_actual_create_in_sql(self):
        admitted = validate_inventory(inventory())[1]
        rows = attempts(admitted)
        validate_attempts(admitted, rows)
        denial = next(i for i, r in enumerate(rows) if r[4] == 403)
        wrong = copy.deepcopy(rows)
        wrong[denial][4], wrong[denial + 1][4] = 201, 403
        with self.assertRaises(AssertionError):
            validate_attempts(admitted, wrong)
        for change in ('foreign-scope', 'repost-negative', 'extra-attempt'):
            wrong = copy.deepcopy(rows)
            if change == 'foreign-scope':
                wrong[0][2] = 'service1'
            elif change == 'repost-negative':
                negative = next(r for r in wrong if r[3].endswith('negative')); negative[1:] = ['POST', *negative[2:4], 201]
            else:
                wrong.append([18, 'POST', rows[0][2], rows[0][3], 200])
            with self.subTest(change=change), self.assertRaises(AssertionError):
                validate_attempts(admitted, wrong)

    def test_aborted_tool_decision_can_have_completed_native_tasks(self):
        r, endpoint, enters = chain(decision='aborted')
        self.assertEqual(validate_final_chain(r, endpoint, enters, expected_api='fixture-api',
                                              native_aborted=False, decision='aborted'), (20, 21))
        wrong = copy.deepcopy(endpoint); wrong['tasks'][1]['state']['outcome']['status'] = 'aborted'
        with self.assertRaises(AssertionError):
            validate_final_chain(r, wrong, enters, expected_api='fixture-api', native_aborted=False, decision='aborted')

    def test_recovered_native_preabort_has_distinct_terminal_outcome(self):
        r, endpoint, enters = chain(native_aborted=True, decision=None)
        validate_final_chain(r, endpoint, enters, expected_api='fixture-api', native_aborted=True, decision=None)
        for field, value in (('api', 'other-api'), ('provider', 'other-provider')):
            wrong = copy.deepcopy(endpoint); wrong['entries'][1]['model'][0][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate_final_chain(r, wrong, enters, expected_api='fixture-api', native_aborted=True, decision=None)

    def test_final_chain_rejects_detached_tool_and_changed_result(self):
        r, endpoint, enters = chain(decision='denied')
        validate_final_chain(r, endpoint, enters, expected_api='fixture-api', native_aborted=False, decision='denied')
        for change in ('owner', 'call', 'result', 'submission', 'duplicate-row'):
            wrong = copy.deepcopy(endpoint)
            if change == 'owner':
                wrong['entries'][1]['byTaskId'] = 99
            elif change == 'call':
                wrong['entries'][1]['model'][0]['content'][0]['arguments']['payload'] = 'changed'
            elif change == 'result':
                wrong['entries'][2]['model'][0]['content'][0]['text'] = 'commit'
            elif change == 'submission':
                wrong['submissions'][0]['requestId'] = 'other'
            else:
                wrong['entries'].append(copy.deepcopy(wrong['entries'][0]))
            with self.subTest(change=change), self.assertRaises(AssertionError):
                validate_final_chain(r, wrong, enters, expected_api='fixture-api', native_aborted=False, decision='denied')

    def test_real_transport_and_saved_receipt_happen_before_stale_callback(self):
        with tempfile.TemporaryDirectory() as temporary:
            d = Path(temporary); admitted, events = race_evidence(d)
            validate_races(d, admitted, events)
            for change in ('missing-transport', 'wrong-refusal', 'receipt-count', 'ack-after-late'):
                wrong = copy.deepcopy(events)
                if change == 'missing-transport':
                    wrong.remove(next(e for e in wrong if e['type'] == 'http-result' and e['status'] == 403))
                elif change == 'wrong-refusal':
                    next(e for e in wrong if e['type'] == 'race-apply-result' and e['call'] == 2)['result'] = {'denied': False}
                elif change == 'receipt-count':
                    next(e for e in wrong if e['type'] == 'race-apply-result' and e['call'] == 1)['result']['receipt']['count'] = 2
                else:
                    index = next(i for i, e in enumerate(wrong) if e['type'] == 'race-first-acknowledged')
                    event = wrong.pop(index)
                    after = next(i for i, e in enumerate(wrong) if e['type'] == 'effect-disposition-superseded')
                    wrong.insert(after + 1, event)
                with self.subTest(change=change), self.assertRaises(AssertionError):
                    validate_races(d, admitted, wrong)

    def test_saved_acknowledgement_cannot_hide_receipt_downgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            d = Path(temporary); admitted, events = race_evidence(d)
            validate_races(d, admitted, events)
            path = d / 'race0-preserved.json'; state = json.loads(path.read_bytes())
            key = next(iter(state['effectIntents']))
            state['effectIntents'][key]['status'] = 'denied'
            path.write_text(json.dumps(state), encoding='utf-8')
            event = next(e for e in events if e['type'] == 'race-receipt-preserved' and e['service'] == 0)
            event['state'] = state
            with self.assertRaises(AssertionError):
                validate_races(d, admitted, events)


if __name__ == '__main__':
    unittest.main()
