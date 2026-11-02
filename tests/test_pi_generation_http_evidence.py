"""Fault controls for saved SQL/identity/trace evidence; no native or HTTP run."""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from experiments.pi_generation_http_audit import (
    validate_recovery_evidence, validate_task_coverage, validate_trace_evidence,
    verify_copied_endpoint, expected_receipt, validate_scoped_authority, validate_preabort_evidence,
    validate_effect_controls,
)
from scripts.check_pi_generation_http import validate_workload


def save(directory, name, value):
    (directory / name).write_text(json.dumps(value), encoding='utf-8')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def copied_native(directory):
    stem = 'service0-stage0'
    expected = {'state': {'capacity': 2, 'active': {}}, 'document_sequences': [7],
                'tasks': [], 'entries': [], 'submissions': [], 'conversations': []}
    with closing(sqlite3.connect(directory / f'{stem}.sqlite')) as db, db:
        db.execute('CREATE TABLE documents(id TEXT,kind TEXT)')
        db.execute('CREATE TABLE document_revisions(document_id TEXT,seq INTEGER,content TEXT)')
        db.execute('INSERT INTO documents VALUES(?,?)', ('document', json.dumps('frontier.generation-admission-service')))
        db.execute('INSERT INTO document_revisions VALUES(?,?,?)', ('document', 7, json.dumps(expected['state'])))
        for table in ('tasks', 'entries', 'submissions', 'conversations'):
            db.execute(f'CREATE TABLE {table}(id TEXT,record TEXT)')
    save(directory, f'{stem}-endpoint.json', expected)
    save(directory, f'{stem}-copy-comparison.json', {'service': 0, 'stage': 0, 'equal': True,
         'source_endpoint_sha256': digest(expected), 'copy_endpoint_sha256': digest(expected)})
    return stem, expected


def trace_fixture(directory):
    execution = {'processes': [], 'servers': []}
    events = []
    for stage in range(3):
        pid = 100 + stage
        ready = {'stage': stage, 'pid': pid, 'pending': (4, 2, 0)[stage], 'closed': stage == 2, 'elapsed_ms': 1}
        execution['processes'].append({'stage': stage, 'pid': pid, 'ready': ready})
        execution['servers'].append({'stage': stage, 'pid': 200 + stage})
        save(directory, f'stage{stage}-ready.json', ready)
        save(directory, f'stage{stage}-snapshot.json', {'stage': stage, 'pid': pid})
        event = {'type': 'ready', 'stage': stage, 'pid': pid}
        events.append(event)
        raw = (json.dumps(event) + '\n').encode()
        (directory / f'stage{stage}.jsonl').write_bytes(raw)
        save(directory, f'stage{stage}-sink.json', {'events': 1, 'bytes': len(raw), 'callback_ms': 0, 'flush_ms': 0})
        server_ready = {'stage': stage, 'pid': 200 + stage, 'base': f'http://127.0.0.1:{10000+stage}/', 'started_at': 'fixed'}
        save(directory, f'effect-server{stage}-ready.json', server_ready)
        rows = [{'type': 'server-ready', **server_ready, 'epoch_ms': 0, 'monotonic_ns': 0},
                {'type': 'server-closed', 'stage': stage, 'pid': 200 + stage, 'epoch_ms': 1, 'monotonic_ns': 1}]
        (directory / f'effect-server{stage}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows), encoding='utf-8')
    return execution, events


def stopped_chains(directory):
    """Independent numeric-ID stopped DB records, before recovery abort marks."""
    admitted, events, apis = [], [], {}
    endpoints = {}
    for service in range(2):
        for index, (stage, intent, conversation) in enumerate(((0, 'remote-deny', 2),
                (0, 'pre-cancel', 8), (1, 'post-cancel', 2))):
            request_id = f'db{service}-{intent}'
            key = f'{conversation}:{request_id}'
            r = {'stage': stage, 'service': service, 'conversation': conversation, 'requestId': request_id,
                 'key': key, 'payload': 'payload-' + request_id, 'version': stage + 1,
                 'submissionId': 3 + index * 6, 'intent': intent}
            admitted.append(r)
            generation, tool, user, assistant = (5 + index * 6, 7 + index * 6, 4 + index * 6, 6 + index * 6)
            call = 'call-' + hashlib.sha256(key.encode()).hexdigest()[:24]
            args = {k: r[k] for k in ('key', 'payload', 'version')}
            api = apis[service, stage] = f'fixture-{service}-{stage}'
            endpoint = endpoints.setdefault((service, stage), {'state': {'effectIntents': {}},
                'tasks': [], 'entries': [], 'submissions': []})
            endpoint['state']['effectIntents'][key] = {'identity': {
                **args, 'conversation': conversation, 'scope': f'service{service}',
                'fingerprint': hashlib.sha256(r['payload'].encode()).hexdigest()}}
            endpoint['submissions'].append({'id': r['submissionId'], 'type': 'input', 'status': 'placed',
                'requestId': request_id, 'conversationId': conversation, 'entry': user})
            endpoint['entries'].extend([
                {'id': user, 'kind': 'pi.user', 'conversationId': conversation,
                 'model': [{'role': 'user', 'content': json.dumps(args)}]},
                {'id': assistant, 'kind': 'pi.assistant', 'conversationId': conversation, 'byTaskId': generation,
                 'model': [{'role': 'assistant', 'api': api, 'provider': 'faux', 'model': 'faux-1',
                            'stopReason': 'toolUse', 'content': [{'type': 'toolCall', 'id': call,
                                'name': 'frontier_effect', 'arguments': args}]}]},
            ])
            endpoint['tasks'].extend([
                {'id': generation, 'kind': 'pi.generation', 'version': 1, 'conversationId': conversation,
                 'background': False, 'input': {}, 'state': {'status': 'waiting', 'on': [tool],
                    'policy': 'allSettled', 'checkpoint': {'phase': 'tools', 'assistant': assistant,
                        'tools': [tool], 'pending': []}}},
                {'id': tool, 'kind': 'pi.tool', 'version': 2, 'conversationId': conversation,
                 'background': False, 'owner': generation, 'input': {'kind': 'model', 'assistant': assistant,
                    'callId': call}, 'state': {'status': 'running', 'checkpoint': {'phase': 'execute',
                        'arguments': args, 'replay': 'safe'}}},
            ])
            events.extend([
                {'type': 'tool-enter', 'stage': stage, 'service': service, 'key': key,
                 'taskId': tool, 'conversation': conversation, 'callId': call},
                {'type': 'recovery-native-preabort', 'stage': stage + 1, 'service': service, 'key': key,
                 'submissionId': r['submissionId'], 'conversation': conversation,
                 'generationTaskId': generation, 'toolTaskId': tool, 'scheduling': 'paused'},
            ])
    for (service, stage), endpoint in endpoints.items():
        save(directory, f'service{service}-stage{stage}-endpoint.json', endpoint)
    return admitted, events, apis


class SavedHttpEvidenceTests(unittest.TestCase):
    def test_conflict_control_uses_changed_payload_with_its_own_valid_fingerprint(self):
        admitted = [{'service': service, 'key': f'2:s1-db{service}-post-cancel-0', 'conversation': 2,
                     'payload': f'payload-db{service}', 'version': 2, 'intent': 'post-cancel'}
                    for service in range(2)]
        events = []
        for request in admitted:
            common = {'stage': 2, 'service': request['service'], 'key': request['key']}
            payload = 'changed-' + request['payload']
            events.extend([
                {'type': 'duplicate-effect-control', **common, 'status': 200,
                 'receipt': expected_receipt(request)},
                {'type': 'changed-effect-control', **common, 'status': 409, 'payload': payload,
                 'fingerprint': hashlib.sha256(payload.encode()).hexdigest()},
            ])
        validate_effect_controls(admitted, events)
        for field, value in (('payload', admitted[0]['payload']), ('fingerprint', '0' * 64),
                             ('service', 1), ('stage', 1), ('status', 400)):
            changed = copy.deepcopy(events)
            next(e for e in changed if e['type'] == 'changed-effect-control')[field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate_effect_controls(admitted, changed)
        changed = copy.deepcopy(events)
        changed[0]['receipt']['scope'] = 'service1'
        with self.assertRaises(AssertionError):
            validate_effect_controls(admitted, changed)

    def test_paused_preabort_binds_each_original_native_chain_stage_service_and_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            d = Path(temporary); admitted, events, apis = stopped_chains(d)
            validate_preabort_evidence(d, admitted, events, apis)
            for field, value in (('toolTaskId', 999), ('generationTaskId', 999), ('conversation', 999),
                                 ('submissionId', 999), ('stage', 2), ('service', 1), ('scheduling', 'running')):
                changed = copy.deepcopy(events)
                next(e for e in changed if e['type'] == 'recovery-native-preabort')[field] = value
                with self.subTest(field=field), self.assertRaises(AssertionError):
                    validate_preabort_evidence(d, admitted, changed, apis)
            endpoint = json.loads((d / 'service0-stage0-endpoint.json').read_bytes())
            key = admitted[0]['key']
            endpoint['state']['effectIntents'][key]['identity']['scope'] = 'service1'
            save(d, 'service0-stage0-endpoint.json', endpoint)
            with self.assertRaisesRegex(AssertionError, 'scoped remote identity'):
                validate_preabort_evidence(d, admitted, events, apis)

    def test_reused_native_conversation_ids_require_distinct_remote_scopes(self):
        conversations = [[2, 8], [2, 8]]
        rows = [['service0', 2, 1, 0], ['service0', 8, 1, 1],
                ['service1', 2, 1, 0], ['service1', 8, 1, 1]]
        validate_scoped_authority(rows, conversations, 0)
        for changed in (rows[:2], [*rows[:2], *rows[:2]]):
            with self.assertRaisesRegex(AssertionError, 'isolate'):
                validate_scoped_authority(changed, conversations, 0)
        request = {'service': 0, 'key': '2:db0-r', 'conversation': 2, 'payload': 'value', 'version': 1}
        own = expected_receipt(request)
        foreign = expected_receipt({**request, 'service': 1})
        self.assertEqual(own['conversation'], 2)
        self.assertEqual(own['scope'], 'service0')
        self.assertNotEqual(own, foreign)

    def test_every_predeclared_workload_count_is_exact_and_integer(self):
        root = Path(__file__).resolve().parents[1]
        workload = json.loads((root / 'experiments/pi_generation_http_protocol.json').read_bytes())['workload']
        validate_workload(workload)
        for changed in ({**workload, 'effect_POST_attempts': 15}, {**workload, 'final_active': False},
                        {**workload, 'unregistered_arrival': 1}):
            with self.assertRaises(AssertionError):
                validate_workload(changed)

    def test_full_native_sql_endpoint_reread_and_changed_sql_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            d = Path(temporary); stem, expected = copied_native(d)
            before = {p.name for p in d.iterdir()}
            self.assertEqual(verify_copied_endpoint(d, 0, 0), expected)
            self.assertEqual({p.name for p in d.iterdir()}, before)
            with closing(sqlite3.connect(d / f'{stem}.sqlite')) as db, db:
                db.execute('UPDATE document_revisions SET content=?', ('{"active":{"foreign":true}}',))
            with self.assertRaisesRegex(AssertionError, 'differs'):
                verify_copied_endpoint(d, 0, 0)

    def test_json_encoded_kind_and_derived_copy_digests_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            d = Path(temporary); stem, _ = copied_native(d)
            comparison = json.loads((d / f'{stem}-copy-comparison.json').read_bytes())
            comparison['source_endpoint_sha256'] = '0' * 64
            save(d, f'{stem}-copy-comparison.json', comparison)
            with self.assertRaises(AssertionError):
                verify_copied_endpoint(d, 0, 0)
            with closing(sqlite3.connect(d / f'{stem}.sqlite')) as db, db:
                db.execute('UPDATE documents SET kind=?', ('frontier.generation-admission-service',))
            with self.assertRaises(AssertionError):
                verify_copied_endpoint(d, 0, 0)

    def test_separate_effect_sql_cannot_be_replaced_by_plausible_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            d = Path(temporary); stem = 'effects-stage2'
            expected = {'authority': [['service0', 2, 1, 1]], 'effects': [], 'attempts': [[1, 'GET', '2:r', 404]]}
            with closing(sqlite3.connect(d / f'{stem}.sqlite')) as db, db:
                db.execute('CREATE TABLE authority(scope TEXT,conversation INTEGER,version INTEGER,allowed INTEGER)')
                db.execute('CREATE TABLE effects(key TEXT,identity TEXT,count INTEGER)')
                db.execute('CREATE TABLE attempts(seq INTEGER,method TEXT,key TEXT,status INTEGER)')
                db.execute('INSERT INTO authority VALUES(?,?,?,?)', ('service0', 2, 1, 1))
                db.execute('INSERT INTO attempts VALUES(?,?,?,?)', (1, 'GET', '2:r', 404))
            save(d, f'{stem}-endpoint.json', expected)
            save(d, f'{stem}-copy-comparison.json', {'equal': True, 'source_endpoint_sha256': digest(expected),
                 'copy_endpoint_sha256': digest(expected)})
            self.assertEqual(verify_copied_endpoint(d, 2), expected)
            with closing(sqlite3.connect(d / f'{stem}.sqlite')) as db, db:
                db.execute('UPDATE attempts SET status=200')
            with self.assertRaisesRegex(AssertionError, 'differs'):
                verify_copied_endpoint(d, 2)

    def test_event_pid_stage_and_sink_bytes_bind_the_controller_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            d = Path(temporary); execution, events = trace_fixture(d)
            validate_trace_evidence(d, events, execution)
            foreign = copy.deepcopy(events); foreign[1]['pid'] += 10
            with self.assertRaises(AssertionError):
                validate_trace_evidence(d, foreign, execution)
            foreign = copy.deepcopy(events); foreign[1]['stage'] = 7
            with self.assertRaises(AssertionError):
                validate_trace_evidence(d, foreign, execution)
            sink = json.loads((d / 'stage0-sink.json').read_bytes()); sink['bytes'] += 1
            save(d, 'stage0-sink.json', sink)
            with self.assertRaises(AssertionError):
                validate_trace_evidence(d, events, execution)

    def test_exact_recovery_ids_and_prior_stopped_state_cannot_be_swapped(self):
        with tempfile.TemporaryDirectory() as temporary:
            d = Path(temporary); admitted = []
            for service in range(2):
                for index, (stage, intent) in enumerate(((0, 'remote-deny'), (0, 'pre-cancel'), (1, 'post-cancel'))):
                    key = f'{service}:{intent}'
                    admitted.append({'stage': stage, 'service': service, 'key': key, 'submissionId': 100 + service * 10 + index, 'intent': intent})
            recovered = [{'stage': r['stage'] + 1, **{k: r[k] for k in ('service', 'key', 'submissionId')}} for r in admitted]
            events = []
            for r in recovered:
                state = {'marker': f"{r['service']}:{r['stage']-1}"}
                save(d, f"service{r['service']}-stage{r['stage']-1}-endpoint.json", {'state': state})
                events.append({'type': 'recovery-before-resume', **{k: r[k] for k in ('stage', 'service', 'key')}, 'state': state})
            ids = {'recovered': recovered}
            validate_recovery_evidence(d, ids, admitted, events)
            changed = copy.deepcopy(ids)
            changed['recovered'][0]['submissionId'], changed['recovered'][1]['submissionId'] = changed['recovered'][1]['submissionId'], changed['recovered'][0]['submissionId']
            with self.assertRaises(AssertionError):
                validate_recovery_evidence(d, changed, admitted, events)
            changed = copy.deepcopy(events); changed[0]['state']['marker'] = 'foreign'
            with self.assertRaises(AssertionError):
                validate_recovery_evidence(d, ids, admitted, changed)

    def test_every_generation_and_tool_must_have_one_distinct_original_chain(self):
        tasks = [{'id': i} for i in range(12)]; chain = [t['id'] for t in tasks]
        validate_task_coverage(chain, tasks)
        for changed in ([*chain[:-1], chain[0]], [*chain[:-1], 99]):
            with self.assertRaises(AssertionError):
                validate_task_coverage(changed, tasks)


if __name__ == '__main__':
    unittest.main()
