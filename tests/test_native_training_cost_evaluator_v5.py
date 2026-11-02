"""Exercise the real evaluator controller with process I/O replaced by fixtures."""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments import native_training_cost_scopes_v4 as prior
from experiments import native_training_cost_evaluator_v5 as current
from scripts import run_native_training_cost_evaluator_v5 as launcher


def cleanup_fixture():
    return {
        'all_retained_handles_exited': True,
        'job_active_count': 0,
        'exit_codes': [
            {'pid': 101, 'creation_filetime': 1001, 'exit_code': 0},
            {'pid': 202, 'creation_filetime': 2002, 'exit_code': 0},
        ],
    }


def invoke_evaluator(study, *, cleanup=None, result_pid=202, provider_valid=True,
                     progress_error=None):
    """Call the actual controller, without a Windows backend or any ML import."""
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        output = Path(directory)
        (output / 'evaluation.json').write_text(json.dumps({
            'pid': result_pid, 'provider_guard': {'fixture': 'saved-evaluator'},
        }), encoding='utf-8')
        launcher_ref = SimpleNamespace(pid=101, creation_filetime=1001)
        actual = SimpleNamespace(pid=202, creation_filetime=2002)
        ready = {'pid': actual.pid, 'creation_filetime': actual.creation_filetime,
                 'perf_counter': 1.0}
        job = mock.Mock()
        job.start_suspended.return_value = launcher_ref
        job.authenticate.return_value = (actual, [ready])
        stack.enter_context(mock.patch.object(study.obs, 'WindowsJob', return_value=job))
        stack.enter_context(mock.patch.object(study.work, 'wait_receipt', return_value=ready))
        clean = stack.enter_context(mock.patch.object(
            study.work, 'cleanup', return_value=copy.deepcopy(
                cleanup if cleanup is not None else cleanup_fixture())))
        stack.enter_context(mock.patch.object(study.prior, 'os_image', return_value={'verified': True}))
        stack.enter_context(mock.patch.object(study.dual, 'verify_self_executable', return_value={}))
        provider = stack.enter_context(mock.patch.object(
            study.prior, 'validate_provider', return_value=provider_valid))
        prefix = stack.enter_context(mock.patch.object(
            study.progress, 'read_prefix', side_effect=progress_error))
        read = stack.enter_context(mock.patch.object(study.obs, 'read_small', wraps=study.obs.read_small))
        report = study.run_evaluator(
            {'launcher': Path('fixture-launcher.exe'), 'base_python': Path('fixture-python.exe')},
            Path('fixture-provider.py'), Path('fixture-model'), Path('fixture-data'),
            {'executables_sha256': {'base_python': 'a' * 64}}, output,
            study.time.perf_counter() + 600)
        calls = {
            'job': job, 'cleanup': clean, 'provider': provider, 'prefix': prefix, 'read': read,
            'prefix_complete': prefix.call_args.kwargs.get('complete') if prefix.called else None,
        }
    return report, calls


class EvaluatorCleanupBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.loaded_before = set(sys.modules)

    def tearDown(self):
        self.assertFalse({'torch', 'transformers', 'numpy'} & (set(sys.modules) - self.loaded_before))

    def test_unmodified_v4_rejects_two_role_evaluator_before_saved_result_checks(self):
        report, calls = invoke_evaluator(prior)
        self.assertFalse(report['passed'])
        self.assertTrue(report['error'].startswith('KeyError:'), report['error'])
        self.assertIn('censuses', str(report['error']))
        calls['read'].assert_not_called()
        calls['provider'].assert_not_called()
        calls['prefix'].assert_not_called()
        calls['job'].terminate.assert_called_once()

    def test_v5_accepts_exact_two_role_exit0_then_checks_result_provider_and_prefix(self):
        report, calls = invoke_evaluator(current)
        self.assertTrue(report['passed'])
        self.assertTrue(report['cleanup_exact_retained_identity_set'])
        calls['read'].assert_called_once()
        calls['provider'].assert_called_once_with({'fixture': 'saved-evaluator'}, 'load', 1)
        calls['prefix'].assert_called_once()
        self.assertTrue(calls['prefix_complete'])
        calls['job'].terminate.assert_not_called()
        calls['cleanup'].assert_called_once()
        calls['job'].close.assert_called_once()
        calls['job'].close_refs.assert_called_once()
        self.assertNotIn('censuses', report)
        self.assertNotIn('launcher', report)

    def test_v5_rejects_wrong_missing_extra_duplicate_and_unfinished_cleanup(self):
        mutations = {
            'wrong_pid': lambda c: c['exit_codes'][1].update(pid=303),
            'wrong_creation': lambda c: c['exit_codes'][1].update(creation_filetime=2003),
            'missing': lambda c: c['exit_codes'].pop(),
            'extra': lambda c: c['exit_codes'].append({'pid': 303, 'creation_filetime': 3003, 'exit_code': 0}),
            'duplicate': lambda c: c['exit_codes'].__setitem__(1, copy.deepcopy(c['exit_codes'][0])),
            'nonzero_exit': lambda c: c['exit_codes'][1].update(exit_code=38),
            'missing_exit': lambda c: c['exit_codes'][1].pop('exit_code'),
            'unexited_code': lambda c: c['exit_codes'][1].update(exit_code=None),
            'unexited_handle': lambda c: c.update(all_retained_handles_exited=False),
            'active_job': lambda c: c.update(job_active_count=1),
            'unknown_active_job': lambda c: c.update(job_active_count=None),
            'bool_active_job': lambda c: c.update(job_active_count=False),
            'bool_exit': lambda c: c['exit_codes'][1].update(exit_code=False),
            'bool_pid': lambda c: c['exit_codes'][1].update(pid=True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                cleanup = cleanup_fixture()
                mutate(cleanup)
                report, calls = invoke_evaluator(current, cleanup=cleanup)
                self.assertFalse(report['passed'])
                self.assertTrue(report['error'].startswith('ObserverError:'), report['error'])
                self.assertNotIn('cleanup_exact_retained_identity_set', report)
                calls['read'].assert_not_called()
                calls['provider'].assert_not_called()
                calls['prefix'].assert_not_called()
                calls['job'].terminate.assert_called_once()
                calls['job'].close.assert_called_once()
                calls['job'].close_refs.assert_called_once()

    def test_v5_still_rejects_wrong_evaluation_identity_after_cleanup(self):
        report, calls = invoke_evaluator(current, result_pid=303)
        self.assertFalse(report['passed'])
        self.assertIn('Evaluator identity/provider differs', str(report['error']))
        calls['read'].assert_called_once()
        calls['provider'].assert_not_called()
        calls['prefix'].assert_not_called()
        calls['job'].terminate.assert_called_once()

    def test_v5_still_rejects_invalid_provider_after_cleanup(self):
        report, calls = invoke_evaluator(current, provider_valid=False)
        self.assertFalse(report['passed'])
        calls['provider'].assert_called_once()
        calls['prefix'].assert_not_called()
        calls['job'].terminate.assert_called_once()

    def test_v5_still_requires_complete_import_prefix_after_cleanup(self):
        report, calls = invoke_evaluator(current, progress_error=ValueError('Incomplete import prefix'))
        self.assertFalse(report['passed'])
        self.assertIn('Incomplete import prefix', str(report['error']))
        calls['provider'].assert_called_once()
        calls['prefix'].assert_called_once()
        self.assertTrue(calls['prefix_complete'])
        calls['job'].terminate.assert_called_once()

    def test_validator_rejects_aliased_or_untyped_retained_identities(self):
        launcher_ref = SimpleNamespace(pid=101, creation_filetime=1001)
        for actual in [SimpleNamespace(pid=101, creation_filetime=1001),
                       SimpleNamespace(pid=True, creation_filetime=2002),
                       SimpleNamespace(pid=202, creation_filetime=None)]:
            with self.subTest(actual=actual):
                with self.assertRaises(current.obs.ObserverError):
                    current.verify_evaluator_cleanup({'cleanup': cleanup_fixture()}, launcher_ref, actual)


class EvaluatorLauncherAndPinsTest(unittest.TestCase):
    def test_parser_binds_v5_and_normalizes_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            protocol, freeze, output, plan = [folder / name for name in ('protocol.json', 'freeze.json', 'out', 'plan.json')]
            freeze.write_text(json.dumps({'entrypoint_sha256': hashlib.sha256(Path(launcher.__file__).read_bytes()).hexdigest()}), encoding='utf-8')
            plan.write_text('{"control": "saved-only"}', encoding='utf-8')
            with mock.patch.object(current, 'run', return_value=False) as run:
                self.assertFalse(launcher.main(['--protocol', str(protocol), '--freeze', str(freeze),
                                                '--output', str(output), '--plan', str(plan)]))
            self.assertEqual(run.call_args.args,
                             (protocol.resolve(), freeze.resolve(), output.resolve(), {'control': 'saved-only'}))

    def test_prior_or_absent_entrypoint_pin_cannot_authorize_v5(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            freeze = folder / 'freeze.json'
            for pin in [None, prior.cost.file_hash(Path('scripts/run_native_training_cost_scopes_v4.py'))]:
                freeze.write_text(json.dumps({'entrypoint_sha256': pin}), encoding='utf-8')
                with mock.patch.object(current, 'run') as run:
                    with self.assertRaises(ValueError):
                        launcher.main(['--protocol', str(folder / 'protocol.json'), '--freeze', str(freeze),
                                       '--output', str(folder / 'out'), '--plan', str(folder / 'plan.json')])
                    run.assert_not_called()

    def test_source_prefix_preserves_old_pins_and_extends_only_new_preparation(self):
        additional = ('scripts/run_native_training_cost.py', 'tests/test_native_training_cost_launcher.py',
                      'tests/test_native_training_cost_entrypoint_boundary.py')
        new = ('experiments/native_training_cost_evaluator_v5.py', 'tests/test_native_training_cost_evaluator_v5.py',
               'scripts/run_native_training_cost_evaluator_v5.py')
        self.assertEqual(len(prior.SOURCES), 52)
        self.assertEqual(current.SOURCES, (*prior.SOURCES, *additional, *new))
        self.assertEqual(len(set(current.SOURCES)), 58)
        self.assertEqual(current.CONFIG, prior.CONFIG)
        self.assertEqual(current.jobs(), prior.jobs())
        self.assertEqual(current.LIMITS, prior.LIMITS)


if __name__ == '__main__':
    unittest.main()
