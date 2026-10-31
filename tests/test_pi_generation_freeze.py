"""Synthetic freeze/refusal tests; no Node, native runtime, database or model execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import check_pi_generation as checker
from scripts import run_pi_generation as controller


class FreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pi-generation-freeze-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / 'fixtures/pi-generation'
        self.fixture.mkdir(parents=True)
        self.raw = self.root / 'results/pi-generation/raw'
        self.raw.mkdir(parents=True)
        self.protocol = json.loads((checker.ROOT / 'experiments/pi_generation_protocol.json').read_text(encoding='utf-8-sig'))
        self.protocol['predeclared_at'] = '2026-01-01T00:00:00+00:00'
        for name in checker.MANDATORY_SOURCES:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic source\n', encoding='utf8')
        self.write('experiments/pi_generation_protocol.json', self.protocol)
        sources = {name: checker.digest(self.root / name) for name in checker.MANDATORY_SOURCES}
        runtime_names = ['package.json', 'package-lock.json', *[
            f'node_modules/@earendil-works/{name}/dist/index.js' for name in ('pi-durable', 'pi-ai', 'chord')]]
        runtime_rows = []
        for name in runtime_names:
            path = self.root / 'local-state/runtime' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
            runtime_rows.append({'path': name, 'bytes': 7, 'sha256': checker.digest(path)})
        self.write('fixtures/pi-generation/runtime.json', {'files': runtime_rows})
        self.write('fixtures/pi-generation/reviewer.json', {'status': 'passed', 'source_sha256': {
            'scripts/check_pi_generation.py': sources['scripts/check_pi_generation.py']}})
        self.write('fixtures/pi-generation/pre-review.json', {'status': 'passed_for_separate_freeze',
            'source_sha256': sources, 'reviewer_receipts': [{'path': 'fixtures/pi-generation/reviewer.json',
                'sha256': checker.digest(self.fixture / 'reviewer.json')}]})
        node = self.root / 'fake-node.exe'; node.write_bytes(b'not executable')
        self.freeze = {'source_sha256': sources, 'preserved_previous_source_sha256': {
            k: sources[k] for k in ('experiments/pi_durable_service_v2.mjs', 'scripts/run_pi_durable_recovery_v3.py')},
            'protocol_path': 'experiments/pi_generation_protocol.json',
            'protocol_sha256': checker.digest(self.root / 'experiments/pi_generation_protocol.json'),
            'runtime_directory': 'local-state/runtime', 'output_directory': 'reports/never-run',
            'node': str(node), 'node_sha256': checker.digest(node),
            'runtime_manifest_path': 'fixtures/pi-generation/runtime.json',
            'runtime_manifest_sha256': checker.digest(self.fixture / 'runtime.json'),
            'pre_execution_review_path': 'fixtures/pi-generation/pre-review.json',
            'pre_execution_review_sha256': checker.digest(self.fixture / 'pre-review.json'),
            'frozen_at': '2026-01-01T00:00:01+00:00'}
        self.write('fixtures/pi-generation/implementation.json', self.freeze)
        self.execution = {'freeze_sha256': checker.digest(self.fixture / 'implementation.json'),
            'scientific_suites': 1, 'retries': 0, 'model_loads': 0, 'status': 'failed',
            'error': 'synthetic failure, preserved', 'limits': self.protocol['limits'], 'elapsed_seconds': 1}
        self.write_outcome()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf8')

    def write_outcome(self):
        self.write('results/pi-generation/raw/execution.json', self.execution)
        path = self.raw / 'execution.json'
        self.row = {'path': 'execution.json', 'bytes': path.stat().st_size, 'sha256': checker.digest(path)}
        self.write('results/pi-generation/raw-manifest.json', {'files': [self.row]})
        self.write('results/pi-generation/report.json', {'execution_status': self.execution['status'],
            'execution_accepted': False, 'raw_files': 1, 'raw_bytes': self.row['bytes']})

    def test_failed_outcome_portable_without_runtime(self):
        import shutil
        shutil.rmtree(self.root / 'local-state')
        self.assertFalse(checker.check(self.root)['execution_accepted'])

    def test_missing_source_and_preserved_change_refused(self):
        broken = copy.deepcopy(self.freeze)
        del broken['source_sha256']['scripts/pi_generation_worker.mjs']
        with self.assertRaises(AssertionError): checker.validate_freeze(self.root, broken)
        (self.root / 'experiments/pi_durable_service_v2.mjs').write_text('changed')
        with self.assertRaises(AssertionError): checker.validate_freeze(self.root, self.freeze)

    def test_protocol_constants_refused(self):
        for key in checker.PROTOCOL_CONSTANTS:
            changed = copy.deepcopy(self.protocol); changed[key] = -1
            self.write('experiments/pi_generation_protocol.json', changed)
            broken = copy.deepcopy(self.freeze)
            broken['protocol_sha256'] = checker.digest(self.root / broken['protocol_path'])
            broken['source_sha256'][broken['protocol_path']] = broken['protocol_sha256']
            with self.subTest(key=key), self.assertRaises(AssertionError): checker.validate_freeze(self.root, broken)

    def test_duplicate_and_noncanonical_manifest_refused(self):
        for name in ('../escape', '/absolute', 'a//b', 'a/./b', 'a\\b', 'C:/escape'):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                checker.inventory({'files': [{**self.row, 'path': name}]})
        with self.assertRaises(AssertionError): checker.inventory({'files': [self.row, self.row]})
        for field, value in (('bytes', -1), ('bytes', True), ('sha256', 'wrong')):
            with self.assertRaises(AssertionError): checker.inventory({'files': [{**self.row, field: value}]})

    def test_raw_duplicate_or_extra_file_refused(self):
        self.write('results/pi-generation/raw-manifest.json', {'files': [self.row, self.row]})
        with self.assertRaises(AssertionError): checker.check(self.root)
        self.write_outcome(); (self.raw / 'extra').write_bytes(b'new')
        with self.assertRaises(AssertionError): checker.check(self.root)

    def test_unfinished_or_unknown_status_refused(self):
        for status in ('running', 'unknown'):
            self.execution['status'] = status; self.write_outcome()
            with self.subTest(status=status), self.assertRaises(AssertionError): checker.check(self.root)

    def test_stale_review_or_subset_hash_refused(self):
        self.write('fixtures/pi-generation/reviewer.json', {'status': 'passed',
            'source_sha256': {'scripts/check_pi_generation.py': '0' * 64}})
        with self.assertRaises(AssertionError): checker.validate_freeze(self.root, self.freeze)
        review = checker.load(self.fixture / 'pre-review.json')
        review['reviewer_receipts'][0]['sha256'] = checker.digest(self.fixture / 'reviewer.json')
        self.write('fixtures/pi-generation/pre-review.json', review)
        self.freeze['pre_execution_review_sha256'] = checker.digest(self.fixture / 'pre-review.json')
        with self.assertRaises(AssertionError): checker.validate_freeze(self.root, self.freeze)

    def test_process_start_failure_preserved_and_not_retried(self):
        (self.root / 'reports').mkdir()
        with patch.object(controller, 'ROOT', self.root), patch.object(controller, '__file__', str(self.root / 'scripts/run_pi_generation.py')):
            with patch.object(controller.subprocess, 'Popen', side_effect=OSError('synthetic process failure')) as spawn:
                self.assertEqual(controller.execute(self.fixture / 'implementation.json'), 1)
                saved = checker.load(self.root / 'reports/never-run/execution.json')
                self.assertEqual(saved['status'], 'failed')
                self.assertIn('synthetic process failure', saved['error'])
                self.assertEqual(len(saved['processes']), 1)
                with self.assertRaises(AssertionError): controller.execute(self.fixture / 'implementation.json')
                self.assertEqual(spawn.call_count, 1)

    def test_accepted_bounds_require_memory_and_finite_times(self):
        self.execution.update(status='passed', acceptance={'synthetic': True}, processes=[
            {'stage': stage, 'pid': stage + 100, 'forced_termination': stage < 2,
             'returncode': -1 if stage < 2 else 0, 'elapsed_seconds': 1,
             'ready': {'pid': stage + 100, 'stage': stage},
             'memory_samples': [{'PrivateUsage': 100}]} for stage in range(3)])
        def accepted_fixture():
            self.write_outcome()
            report = checker.load(self.root / 'results/pi-generation/report.json')
            report.update(execution_accepted=True, acceptance={'synthetic': True})
            self.write('results/pi-generation/report.json', report)
        accepted_fixture()
        with patch.object(checker, 'audit', return_value={'synthetic': True}):
            self.assertTrue(checker.check(self.root)['execution_accepted'])
            for field, value in (('memory_samples', []), ('elapsed_seconds', float('nan')),
                                 ('elapsed_seconds', 20)):
                previous = self.execution['processes'][0][field]
                self.execution['processes'][0][field] = value; accepted_fixture()
                with self.subTest(field=field, value=value), self.assertRaises(AssertionError):
                    checker.check(self.root)
                self.execution['processes'][0][field] = previous
            self.execution['processes'][0]['memory_samples'][0]['PrivateUsage'] = 268435456
            accepted_fixture()
            with self.assertRaises(AssertionError): checker.check(self.root)

    def test_preserved_only_path_is_checked(self):
        old = self.root / 'experiments/old.py'; old.write_bytes(b'old')
        self.freeze['preserved_previous_source_sha256']['experiments/old.py'] = checker.digest(old)
        checker.validate_freeze(self.root, self.freeze)
        old.write_bytes(b'changed')
        with self.assertRaises(AssertionError): checker.validate_freeze(self.root, self.freeze)

    def test_capture_deadline_refuses_before_sqlite(self):
        with patch.object(controller.time, 'monotonic', return_value=10), patch.object(controller.sqlite3, 'connect') as connect:
            with self.assertRaises(AssertionError): controller.capture(self.root, 0, 9)
            connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
