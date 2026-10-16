"""Public receipt-auditor CLI portability checks, using only the standard library."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import audit_activation_history as auditor


class AuditorCliTests(unittest.TestCase):
    def test_help_runs_without_site_packages(self):
        child = subprocess.run([sys.executable, "-S", str(Path(auditor.__file__).resolve()), "--help"],
            capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertIn("--result", child.stdout)
        self.assertIn("--output", child.stdout)

    def test_default_result_is_repository_relative_from_another_directory(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with patch.object(auditor, "audit", return_value={"ok": True}) as audit:
                    result = auditor.main(["--output", "receipt.json"])
                self.assertEqual(result, {"ok": True})
                self.assertEqual(audit.call_args.args[0], auditor.ROOT / "results/activation-history")
                self.assertEqual(audit.call_args.args[1], Path("receipt.json"))
            finally:
                os.chdir(previous)

    def test_explicit_unicode_paths_are_passed_without_shell_parsing(self):
        with patch.object(auditor, "audit", return_value={}) as audit:
            auditor.main(["--result", "研究 结果", "--output", "审计 记录.json"])
        self.assertEqual(audit.call_args.args, (Path("研究 结果"), Path("审计 记录.json")))

    def test_missing_output_is_an_argument_error(self):
        with contextlib.redirect_stderr(io.StringIO()), patch.object(auditor, "audit") as audit:
            with self.assertRaises(SystemExit) as error:
                auditor.main([])
        self.assertEqual(error.exception.code, 2)
        audit.assert_not_called()

    def test_existing_output_refused_before_any_input_read(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                output = Path("审计 记录.json")
                output.write_text("keep original", encoding="utf-8")
                with patch.object(auditor, "read") as read:
                    with self.assertRaises(FileExistsError) as error:
                        auditor.audit("missing-result", output)
                self.assertIn(str(output.resolve()), str(error.exception))
                read.assert_not_called()
                self.assertEqual(output.read_text(encoding="utf-8"), "keep original")
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
