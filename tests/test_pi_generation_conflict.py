"""Pure preparation regressions; no native runtime, model, provider or SQLite."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from experiments.pi_generation_conflict_audit import validate_host, validate_event_stage
from scripts.check_pi_generation_conflict import CONSTANTS, MANDATORY_SOURCES, WORKLOAD, digest, validate_freeze


class HostDispositionTests(unittest.TestCase):
    def test_wrong_terminal_stage_is_rejected(self):
        for intent, origin, terminal in [('pre-abort', 0, 1), ('busy-deny', 0, 1), ('busy-cancel', 0, 1),
                                         ('type-collision', 1, 1), ('content-collision', 1, 1), ('post-abort', 1, 2), ('commit', 2, 2)]:
            r = {'intent': intent, 'stage': origin}
            validate_event_stage('terminal', {'stage': terminal}, r)
            for wrong in set(range(3)) - {terminal}:
                with self.subTest(intent=intent, wrong=wrong), self.assertRaises(AssertionError):
                    validate_event_stage('terminal', {'stage': wrong}, r)

    def test_original_reservation_including_conflict_identity_is_exact(self):
        r = {'conversation': 'c', 'requestId': 'r', 'payload': 'original', 'version': 2,
             'intent': 'content-collision', 'terminal': {'status': 'native-conflict', 'nativeSubmissionId': 'foreign', 'nativeType': 'input'}}
        host = {k: r[k] for k in ('conversation', 'requestId', 'payload', 'version', 'terminal')}
        host.update(cancelled=True, fingerprint=hashlib.sha256(b'original').hexdigest())
        validate_host(r, host)
        for field, value in [('payload', 'foreign'), ('version', 3), ('requestId', 'other'),
                             ('cancelled', False), ('fingerprint', '0' * 64), ('submissionId', 'foreign')]:
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate_host(r, {**host, field: value})
        for terminal in ({'status': 'done'}, {**r['terminal'], 'nativeSubmissionId': 'other'}, {**r['terminal'], 'nativeType': 'write'}):
            with self.subTest(terminal=terminal), self.assertRaises(AssertionError):
                validate_host(r, {**host, 'terminal': terminal})


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='frontier-conflict-pure-')
        self.addCleanup(self.temp.cleanup); self.root = Path(self.temp.name)
        self.protocol = {**CONSTANTS, 'predeclared_at': '2026-11-02T11:00:00+00:00',
                         'workload': {**WORKLOAD, 'provider_api_identity_contract': {'service0': 'default-dynamic', 'service1': 'frontier-faux-conflict'}}}
        for name in MANDATORY_SOURCES:
            self.write(name, self.protocol if name.endswith('protocol.json') else 'pure synthetic bytes, never executed')
        preserved = {'old-helper.py': self.write('old-helper.py', 'preserved')}
        manifest = {'files': [{'path': 'package.json', 'bytes': 0, 'sha256': hashlib.sha256(b'').hexdigest()}]}
        prior = {'preserved_previous_source_sha256': preserved, 'source_sha256': {}, 'node': 'synthetic-node',
                 'node_sha256': '1' * 64, 'runtime_directory': 'runtime', 'runtime_manifest_path': 'fixture/runtime.json',
                 'runtime_manifest_sha256': self.write('fixture/runtime.json', manifest)}
        self.freeze = {**prior, 'source_sha256': {name: digest(self.root / name) for name in MANDATORY_SOURCES},
                       'previous_freeze_path': 'fixtures/pi-generation-cancellation/implementation.json',
                       'previous_freeze_sha256': self.write('fixtures/pi-generation-cancellation/implementation.json', prior),
                       'frozen_at': '2026-11-02T11:01:00+00:00', 'protocol_path': 'experiments/pi_generation_conflict_protocol.json',
                       'protocol_sha256': digest(self.root / 'experiments/pi_generation_conflict_protocol.json'),
                       'output_directory': 'outcome', 'pre_execution_review_path': 'fixture/review.json'}
        child = {'status': 'passed_for_separate_freeze', 'source_sha256': self.freeze['source_sha256']}
        review = {**child, 'reviewer_receipts': [{'path': 'fixture/child.json', 'sha256': self.write('fixture/child.json', child)}]}
        self.freeze['pre_execution_review_sha256'] = self.write('fixture/review.json', review)

    def write(self, name, value):
        p = self.root / name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')
        return digest(p)

    def test_complete_exact_preparation_validates_without_runtime(self):
        protocol, _ = validate_freeze(self.root, self.freeze)
        self.assertEqual(protocol['workload']['expected_faux_provider_calls'], 10)

    def test_missing_or_changed_source_and_preserved_source_rejected(self):
        for key in ('source_sha256', 'preserved_previous_source_sha256'):
            f = copy.deepcopy(self.freeze); f[key].pop(next(iter(f[key])))
            with self.subTest(key=key), self.assertRaises(AssertionError): validate_freeze(self.root, f)
        p = self.root / 'old-helper.py'; p.write_text('changed', encoding='utf-8')
        with self.assertRaises(AssertionError): validate_freeze(self.root, self.freeze)

    def test_runtime_swap_time_and_path_escape_rejected(self):
        for change in ({'node': 'different'}, {'runtime_directory': 'other'}, {'frozen_at': '2026-11-02T10:59:00+00:00'},
                       {'frozen_at': '2026-11-02T11:01:00'}, {'output_directory': '../outside'}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                validate_freeze(self.root, {**self.freeze, **change})

    def test_unapproved_or_empty_child_review_rejected(self):
        review = json.loads((self.root / 'fixture/review.json').read_bytes())
        for changed in ({**review, 'status': 'pending'}, {**review, 'reviewer_receipts': []}):
            f = {**self.freeze, 'pre_execution_review_sha256': self.write('fixture/review.json', changed)}
            with self.subTest(changed=changed), self.assertRaises(AssertionError): validate_freeze(self.root, f)


if __name__ == '__main__':
    unittest.main()
