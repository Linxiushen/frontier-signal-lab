"""Regress the scoped test-only compatibility shim; never launch a process."""
import importlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_portable_tests as runner


class PortableRunnerTests(unittest.TestCase):
    def target(self):
        module = importlib.import_module('test_pi_generation_freeze')
        return module.FreezeTests('test_process_start_failure_preserved_and_not_retried')

    def test_missing_platform_constant_reaches_mock_and_is_restored(self):
        target = self.target()
        with patch.dict(subprocess.__dict__):
            subprocess.__dict__.pop('CREATE_NO_WINDOW', None)
            suite = unittest.TestSuite([target])
            runner.prepare_suite(suite, platform='linux')
            result = unittest.TestResult(); suite.run(result)
            self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
            self.assertEqual(result.testsRun, 1)
            self.assertNotIn('CREATE_NO_WINDOW', subprocess.__dict__)

    def test_unwrapped_missing_constant_reproduces_CI_failure(self):
        target = self.target()
        with patch.dict(subprocess.__dict__):
            subprocess.__dict__.pop('CREATE_NO_WINDOW', None)
            result = unittest.TestResult(); target.run(result)
            self.assertEqual(len(result.failures), 1)
            self.assertIn('CREATE_NO_WINDOW', result.failures[0][1])
            self.assertIn('synthetic process failure', result.failures[0][1])
            self.assertFalse(result.errors)
            self.assertNotIn('CREATE_NO_WINDOW', subprocess.__dict__)

    def test_existing_constant_restored_after_target(self):
        target = self.target()
        with patch.object(subprocess, 'CREATE_NO_WINDOW', 12345, create=True):
            suite = runner.prepare_suite(unittest.TestSuite([target]), platform='linux')
            result = unittest.TestResult(); suite.run(result)
            self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
            self.assertEqual(subprocess.CREATE_NO_WINDOW, 12345)

    def test_missing_or_duplicate_exact_target_refused(self):
        with self.assertRaises(ValueError): runner.prepare_suite(unittest.TestSuite())
        with self.assertRaises(ValueError):
            runner.prepare_suite(unittest.TestSuite([self.target(), self.target()]))

    def test_changed_frozen_test_refused(self):
        with tempfile.TemporaryDirectory(prefix='portable-runner-') as temp:
            root = Path(temp)
            source = root / runner.TARGET_PATH; source.parent.mkdir(); source.write_bytes(b'changed')
            fixture = root / 'fixtures/pi-generation'; fixture.mkdir(parents=True)
            (fixture / 'implementation.json').write_text(json.dumps({'source_sha256': {runner.TARGET_PATH: '0' * 64}}))
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                runner.prepare_suite(unittest.TestSuite([self.target()]), root=root, platform='linux')

    def test_other_case_unwrapped_and_native_launcher_untouched(self):
        ordinary = unittest.FunctionTestCase(lambda: None)
        original = ordinary.runTest
        launcher = subprocess.Popen
        suite = runner.prepare_suite(unittest.TestSuite([self.target(), ordinary]), platform='linux')
        self.assertIs(subprocess.Popen, launcher)
        self.assertEqual(ordinary.runTest, original)
        self.assertEqual(suite.countTestCases(), 2)

    def test_windows_case_is_not_wrapped(self):
        target = self.target(); original = getattr(target, target._testMethodName)
        runner.prepare_suite(unittest.TestSuite([target]), platform='win32')
        self.assertEqual(getattr(target, target._testMethodName), original)


if __name__ == '__main__':
    unittest.main()
