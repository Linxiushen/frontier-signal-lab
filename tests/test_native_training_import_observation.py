"""Portable controls for the actual caller's no-model import boundary."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts import observe_native_training_import as observation


class ImportObservationTests(unittest.TestCase):
    def test_completed_import_cannot_return_to_model_loading(self):
        self.exercise(completes=True)

    def test_failed_import_keeps_failure_and_cancels_dump(self):
        self.exercise(completes=False)

    def exercise(self, *, completes):
        with tempfile.TemporaryDirectory() as tmp:
            progress = SimpleNamespace(directory=Path(tmp), nonce='a' * 64,
                identity={'creation_filetime': 123},
                guard=SimpleNamespace(receipt=lambda: {'test_only': True}))
            importer = Mock(return_value=(object(), object()))
            if not completes:
                importer.side_effect = LookupError('original import failure')
            with patch.object(observation.faulthandler, 'dump_traceback_later') as arm, \
                 patch.object(observation.faulthandler, 'cancel_dump_traceback_later') as cancel, \
                 patch.object(observation.study, 'prepare', side_effect=AssertionError('No model load')) as prepare:
                error = observation.ImportBoundaryStopped if completes else LookupError
                with self.assertRaises(error):
                    observation.observe_import(progress, importer)
                importer.assert_called_once_with(progress)
                arm.assert_called_once()
                self.assertEqual(arm.call_args.args, (15,))
                self.assertFalse(arm.call_args.kwargs['repeat'])
                self.assertFalse(arm.call_args.kwargs['exit'])
                self.assertTrue(arm.call_args.kwargs['file'].closed)
                cancel.assert_called_once_with()
                prepare.assert_not_called()
            before = json.loads((Path(tmp) / 'import-stack-armed.json').read_bytes())
            after = json.loads((Path(tmp) / 'import-stack-disarmed.json').read_bytes())
            self.assertEqual(after['import_outcome'], 'completed' if completes else 'raised')
            self.assertTrue(before['before_model_load'] and after['before_model_load'])
            self.assertLessEqual(before['armed_perf_counter'], after['disarmed_perf_counter'])
            self.assertEqual((Path(tmp) / 'import-stack.txt').read_bytes(), b'')

    def test_old_freeze_refused_without_any_native_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            protocol = directory / 'protocol.json'
            freeze = directory / 'freeze.json'
            protocol.write_text('{}', encoding='utf8')
            freeze.write_text('{}', encoding='utf8')
            with patch.object(observation.study, 'run', side_effect=AssertionError('No native run')) as run:
                with self.assertRaisesRegex(ValueError, 'Separate frozen'):
                    observation.parent(protocol, freeze, directory / 'out', directory / 'plan.json')
                run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
