import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from experiments.pi_generation_audit import read_endpoint, validate_effect, validate_native_chain, validate_state
from scripts.run_pi_generation import execute


def native_chain(intent='commit', settled=True):
    request = {'key': '9:req', 'requestId': 'req', 'conversation': 9, 'payload': 'p', 'version': 1,
               'submissionId': 10, 'intent': intent, 'stage': 0, 'status': 'admit'}
    args = {'key': '9:req', 'payload': 'p', 'version': 1}
    call_id = 'call-' + hashlib.sha256(b'9:req').hexdigest()[:24]
    submission = {'id': 10, 'type': 'input', 'requestId': 'req', 'conversationId': 9, 'entry': 11,
                  'status': 'unanswered' if intent in ('pre-abort', 'post-abort') else 'done'}
    if submission['status'] == 'unanswered': submission['reason'] = 'aborted'
    else: submission['answer'] = 13
    request['terminal'] = copy.deepcopy(submission)
    outcome = {'status': 'aborted' if intent in ('pre-abort', 'post-abort') else 'completed'}
    generation = {'id': 12, 'kind': 'pi.generation', 'version': 1, 'input': {}, 'conversationId': 9,
                  'background': False, 'state': {'status': 'terminal', 'outcome': outcome}}
    tool = {'id': 14, 'kind': 'pi.tool', 'version': 2, 'input': {'kind': 'model', 'assistant': 13, 'callId': call_id},
            'owner': 12, 'conversationId': 9, 'background': False, 'state': {'status': 'terminal', 'outcome': outcome}}
    user = {'id': 11, 'kind': 'pi.user', 'conversationId': 9, 'model': [{'role': 'user', 'content': json.dumps(args)}]}
    assistant = {'id': 13, 'kind': 'pi.assistant', 'conversationId': 9, 'byTaskId': 12,
                 'model': [{'role': 'assistant', 'api': 'faux', 'provider': 'faux', 'model': 'faux-1', 'stopReason': 'toolUse', 'content': [{'type': 'toolCall', 'id': call_id, 'name': 'frontier_effect', 'arguments': args}]}]}
    result = {'id': 15, 'kind': 'pi.tool-result', 'conversationId': 9, 'byTaskId': 14,
              'model': [{'role': 'toolResult', 'toolCallId': call_id, 'toolName': 'frontier_effect',
                         'isError': intent in ('pre-abort', 'post-abort', 'deny'),
                         'content': [{'type': 'text', 'text': 'denied' if intent == 'deny' else 'existing' if intent == 'recover' else 'commit'}]}]}
    if not settled:
        submission = {k: v for k, v in submission.items() if k not in ('reason', 'answer')}
        submission['status'] = 'placed'
        tool['state'] = {'status': 'running', 'checkpoint': {'phase': 'execute', 'arguments': args, 'replay': 'safe'}}
        generation['state'] = {'status': 'waiting', 'checkpoint': {'phase': 'tools', 'assistant': 13, 'tools': [14], 'pending': []}, 'on': [14], 'policy': 'allSettled'}
    endpoint = {'tasks': [generation, tool], 'entries': [user, assistant] + ([result] if settled else []), 'submissions': [submission]}
    enters = [{'taskId': 14, 'conversation': 9, 'callId': call_id}]
    return request, endpoint, enters


class GenerationSavedBoundaryTests(unittest.TestCase):
    def test_exact_native_chain_and_held_checkpoint(self):
        for intent in ('commit', 'recover', 'deny', 'pre-abort', 'post-abort'):
            self.assertEqual(validate_native_chain(*native_chain(intent)), (12, 14))
        self.assertEqual(validate_native_chain(*native_chain('recover', False), settled=False), (12, 14))

    def test_native_chain_rejects_wrong_submission_model_and_task_identity(self):
        mutations = [
            lambda r, e, t: e['submissions'][0].update(requestId='other'),
            lambda r, e, t: e['submissions'][0].update(conversationId=8),
            lambda r, e, t: e['entries'][0]['model'][0].update(content='{"key":"other"}'),
            lambda r, e, t: e['entries'][1].update(byTaskId=14),
            lambda r, e, t: e['entries'][1]['model'][0].update(provider='different'),
            lambda r, e, t: e['entries'][1]['model'][0]['content'][0]['arguments'].update(payload='changed'),
            lambda r, e, t: e['tasks'][1].update(owner=14),
            lambda r, e, t: e['tasks'][1]['input'].update(callId='different'),
            lambda r, e, t: e['tasks'][0].update(input={'unexpected': True}),
            lambda r, e, t: e['entries'][2]['model'][0].update(toolCallId='different'),
            lambda r, e, t: e['entries'][2]['model'][0].update(isError=True),
            lambda r, e, t: e['tasks'].append(copy.deepcopy(e['tasks'][0])),
            lambda r, e, t: t.append({'taskId': 99, 'conversation': 9, 'callId': t[0]['callId']}),
        ]
        for mutate in mutations:
            args = native_chain(); mutate(*args)
            with self.assertRaises((AssertionError, KeyError)): validate_native_chain(*args)

    def test_held_native_chain_rejects_wrong_replay_arguments_and_join(self):
        mutations = [
            lambda e: e['tasks'][1]['state']['checkpoint'].update(replay='unsafe'),
            lambda e: e['tasks'][1]['state']['checkpoint']['arguments'].update(version=2),
            lambda e: e['tasks'][0]['state']['checkpoint'].update(tools=[99]),
            lambda e: e['tasks'][0]['state'].update(on=[99]),
            lambda e: e['tasks'][0]['state'].update(policy='failFast'),
            lambda e: e['submissions'][0].update(status='queued'),
        ]
        for mutate in mutations:
            args = native_chain('recover', False); mutate(args[1])
            with self.assertRaises(AssertionError): validate_native_chain(*args, settled=False)

    def test_saved_host_state_rejects_authority_identity_and_extra_effect(self):
        r, _, _ = native_chain(); state = {'capacity': 2, 'authority': {'9': {'version': 1, 'allowed': True}, '8': {'version': 99, 'allowed': False}},
            'requests': {r['key']: {'fingerprint': hashlib.sha256(b'p').hexdigest(), 'conversation': 9, 'payload': 'p', 'version': 1, 'submissionId': 10, 'terminal': r['terminal']}},
            'effects': {r['key']: {'count': 1, 'payload': 'p'}}, 'active': {}}
        validate_state(state, [r], [9, 8], 0, set())
        mutations = [lambda s: s['authority']['8'].update(allowed=True),
                     lambda s: s['requests'][r['key']].update(fingerprint='bad'),
                     lambda s: s['requests'][r['key']].update(conversation=8),
                     lambda s: s['effects'].update(unowned={'count': 1, 'payload': 'p'}),
                     lambda s: s['active'].update(unowned=True)]
        for mutate in mutations:
            changed = copy.deepcopy(state); mutate(changed)
            with self.assertRaises(AssertionError): validate_state(changed, [r], [9, 8], 0, set())

    def database(self, kind):
        db = sqlite3.connect(':memory:')
        db.executescript('CREATE TABLE documents(id INTEGER,kind TEXT);'
                         'CREATE TABLE document_revisions(document_id INTEGER,seq INTEGER,content TEXT);')
        for table in ('tasks', 'entries', 'submissions', 'conversations'):
            db.execute('CREATE TABLE ' + table + '(id INTEGER,record TEXT)')
        db.execute('INSERT INTO documents VALUES(1,?)', (kind,))
        db.execute('INSERT INTO document_revisions VALUES(1,1,?)', (json.dumps({'v': 'old'}),))
        db.execute('INSERT INTO document_revisions VALUES(1,2,?)', (json.dumps({'v': 'new'}),))
        return db

    def test_native_encoded_kind_reads_latest_revision(self):
        with self.database(json.dumps('frontier.generation-service')) as db:
            value = read_endpoint(db)
            self.assertEqual(value['state'], {'v': 'new'})
            self.assertEqual(value['document_sequences'], [1, 2])

    def test_unencoded_or_other_kind_cannot_be_accepted(self):
        for kind in ('frontier.generation-service', json.dumps('frontier.service')):
            with self.database(kind) as db, self.assertRaises(AssertionError): read_endpoint(db)

    def test_effect_outcomes_reject_duplicate_and_wrong_payload(self):
        for intent in ('recover', 'commit', 'post-abort'):
            request = {'intent': intent, 'key': 'k', 'payload': 'p'}
            validate_effect(request, {'count': 1, 'payload': 'p'})
            for effect in (None, {'count': 2, 'payload': 'p'}, {'count': 1, 'payload': 'q'}):
                with self.assertRaises(AssertionError): validate_effect(request, effect)
        for intent in ('pre-abort', 'deny', 'overload'):
            request = {'intent': intent, 'key': 'k', 'payload': 'p'}
            validate_effect(request, None)
            with self.assertRaises(AssertionError): validate_effect(request, {'count': 1, 'payload': 'p'})

    def test_old_or_unrelated_freeze_refused_before_native_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            freeze = Path(directory) / 'freeze.json'; freeze.write_text('{"source_sha256":{}}')
            with patch('scripts.run_pi_generation.subprocess.Popen', side_effect=AssertionError('must not launch')) as child:
                with self.assertRaisesRegex(AssertionError, 'new own exact source freeze'): execute(freeze)
                child.assert_not_called()
