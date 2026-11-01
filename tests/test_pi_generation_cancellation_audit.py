"""Saved historical native graph and adverse mutations; no new native suite."""
import copy
import json
from pathlib import Path
import unittest

from experiments.pi_generation_cancellation_audit import validate_cardinality, validate_effects, validate_host


class CancellationAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = Path(__file__).resolve().parents[1] / 'results/pi-generation-admission/raw'
        cls.requests = json.loads((raw / 'identities.json').read_bytes())['requests']
        cls.events = [json.loads(line) for g in range(3) for line in
                      (raw / f'stage{g}.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        cls.endpoint = json.loads((raw / 'service0-stage2-endpoint.json').read_bytes())

    def case(self, old_intent, new_intent):
        r = copy.deepcopy(next(r for r in self.requests if r['service'] == 0 and r['intent'] == old_intent))
        r['intent'] = new_intent
        r['expected_api'] = next(e['api'] for e in self.events if e['type'] == 'provider-request' and e['key'] == r['key'])
        return r, copy.deepcopy(self.events), copy.deepcopy(self.endpoint)

    def test_prior_native_pre_and_post_cancel_graph_scope(self):
        for old, new in (('pre-abort', 'pre-cancel'), ('post-abort', 'post-cancel')):
            r, events, endpoint = self.case(old, new)
            self.assertEqual(len(validate_effects(r, events, endpoint)), 2)
            validate_host(r, endpoint['state']['requests'][r['key']], True)

    def test_effect_task_identity_false_positive_is_refused(self):
        r, events, endpoint = self.case('post-abort', 'post-cancel')
        next(e for e in events if e['type'] == 'tool-effect' and e['key'] == r['key'])['taskId'] = 0
        with self.assertRaises(AssertionError): validate_effects(r, events, endpoint)

    def test_cancelled_replay_and_late_effect_are_refused(self):
        r, events, endpoint = self.case('post-abort', 'post-cancel')
        effect = next(e for e in events if e['type'] == 'tool-effect' and e['key'] == r['key'])
        for mutation in ({**effect, 'stage': 2}, {**effect, 'decision': 'existing'}):
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                validate_effects(r, events + [mutation], endpoint)
        enters = next(e for e in events if e['type'] == 'tool-enter' and e['key'] == r['key'])
        with self.assertRaises(AssertionError): validate_effects(r, events + [{**enters, 'stage': 2}], endpoint)

    def test_lost_cancel_mark_or_changed_identity_is_refused(self):
        r, _, endpoint = self.case('pre-abort', 'pre-cancel')
        host = endpoint['state']['requests'][r['key']]
        for key, value in (('cancelled', False), ('version', 999), ('requestId', 'other'),
                           ('submissionId', 0), ('terminal', {'status': 'done'})):
            changed = {**host, key: value}
            with self.subTest(key=key), self.assertRaises(AssertionError): validate_host(r, changed, True)

    def test_pending_cancel_has_no_native_or_effect(self):
        r, events, _ = self.case('pre-abort', 'pending-cancel')
        del r['submissionId']; r['terminal'] = {'status': 'cancelled-before-submit'}
        endpoint = {'state': {'effects': {}}, 'submissions': []}
        self.assertEqual(validate_effects(r, [], endpoint), [])
        with self.assertRaises(AssertionError): validate_effects(r, events, endpoint)
        endpoint['submissions'].append({'requestId': r['requestId'], 'conversationId': r['conversation']})
        with self.assertRaises(AssertionError): validate_effects(r, [], endpoint)

    def test_changed_api_and_false_success_are_refused(self):
        r, events, endpoint = self.case('pre-abort', 'pre-cancel')
        with self.assertRaises(AssertionError): validate_effects({**r, 'expected_api': 'wrong'}, events, endpoint)
        n = next(n for n in endpoint['submissions'] if n['id'] == r['submissionId'])
        n['status'] = 'done'; r['terminal'] = copy.deepcopy(n)
        with self.assertRaises(AssertionError): validate_effects(r, events, endpoint)

    def test_orphan_assistant_and_duplicate_native_records_are_refused(self):
        validate_cardinality(self.endpoint, 10, 16, 4)
        for mutation in ('extra-assistant', 'missing-result', 'duplicate-task', 'unknown-kind', 'wrong-outcome'):
            endpoint = copy.deepcopy(self.endpoint)
            if mutation == 'extra-assistant':
                extra = copy.deepcopy(next(e for e in endpoint['entries'] if e['kind'] == 'pi.assistant'))
                extra['id'] = -999; endpoint['entries'].append(extra)
            elif mutation == 'missing-result':
                endpoint['entries'].remove(next(e for e in endpoint['entries'] if e['kind'] == 'pi.tool-result'))
            elif mutation == 'duplicate-task': endpoint['tasks'].append(copy.deepcopy(endpoint['tasks'][0]))
            elif mutation == 'unknown-kind': endpoint['entries'].append({'id': -999, 'kind': 'unexpected'})
            else: endpoint['tasks'][0]['state']['outcome']['status'] = 'unsupported'
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                validate_cardinality(endpoint, 10, 16, 4)


if __name__ == '__main__':
    unittest.main()
