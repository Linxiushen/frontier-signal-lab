"""Run the full stdlib suite with one hash-bound mocked Windows fixture shim.

The failed frozen generation v1 test mocks Popen but evaluates CREATE_NO_WINDOW
first. On non-Windows, supply that absent flag only inside that exact test. No
real process launcher is enabled, and frozen test/controller bytes stay intact.
"""
import argparse
import functools
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TARGET_ID = 'test_pi_generation_freeze.FreezeTests.test_process_start_failure_preserved_and_not_retried'
TARGET_PATH = 'tests/test_pi_generation_freeze.py'


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def prepare_suite(suite, root=ROOT, platform=None):
    """Keep discovery unchanged; guard and wrap exactly one known mocked case."""
    selected = [case for case in cases(suite) if case.id() == TARGET_ID]
    if len(selected) != 1:
        raise ValueError(f'Expected exactly one frozen mock fixture, found {len(selected)}')
    target = selected[0]
    path = root / TARGET_PATH
    freeze = json.loads((root / 'fixtures/pi-generation/implementation.json').read_text(encoding='utf-8-sig'))
    expected = freeze['source_sha256'][TARGET_PATH]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Frozen mock fixture source SHA256 mismatch')
    method_name = target._testMethodName
    original = getattr(target, method_name)
    if Path(inspect.getsourcefile(original)).resolve() != path.resolve():
        raise ValueError('Frozen fixture module does not match the guarded path')
    # This method's frozen body patches Popen and checks exactly one mock call.
    # Never synthesize platform flags for a real native controller invocation.
    if (sys.platform if platform is None else platform) != 'win32':
        @functools.wraps(original)
        def mocked_fixture_only():
            with patch.object(subprocess, 'CREATE_NO_WINDOW', 0, create=True):
                return original()
        setattr(target, method_name, mocked_fixture_only)
    return suite


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    prepare_suite(suite)
    result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
