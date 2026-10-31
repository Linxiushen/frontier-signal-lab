"""No Pi runtime execution: exercise atomic-save observation races."""
from pathlib import Path
import tempfile
import unittest

from scripts.run_pi_durable_recovery_v2 import observed_output_bytes


class OutputObservationTests(unittest.TestCase):
    def test_counts_files_and_ignores_subdirectories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'one').write_bytes(b'abc')
            (root / 'two').write_bytes(b'de')
            (root / 'directory').mkdir()
            self.assertEqual(observed_output_bytes(root), 5)

    def test_atomic_rename_between_listing_and_stat_is_tolerated(self):
        class RenamedPath:
            def is_file(self):
                return True

            def stat(self):
                raise FileNotFoundError('worker renamed its temporary file')

        class Output:
            def iterdir(self):
                return iter([RenamedPath()])

        self.assertEqual(observed_output_bytes(Output()), 0)

    def test_unexpected_access_failure_is_not_hidden(self):
        class DeniedPath:
            def is_file(self):
                raise PermissionError('cannot establish output bytes')

        class Output:
            def iterdir(self):
                return iter([DeniedPath()])

        with self.assertRaises(PermissionError):
            observed_output_bytes(Output())
