"""Reproduce only the original saved-byte audit failure; never rerun native work."""
from pathlib import Path
from datetime import datetime, timezone
from contextlib import redirect_stdout
import hashlib
import json
import sys
import traceback

ROOT = Path(__file__).resolve().parents[4]
RUN = ROOT / 'reports/runs/20261102T170820Z'
OUT = Path(__file__).resolve().parent
RAW = RUN / 'h2-native-concurrent-http'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
before = {p.relative_to(RAW).as_posix(): sha(p) for p in RAW.rglob('*') if p.is_file()}
freeze_path = ROOT / 'fixtures/pi-generation-concurrent-http/implementation.json'
freeze = json.loads(freeze_path.read_bytes())
assert all(sha(ROOT / name) == expected for name, expected in freeze['source_sha256'].items())
execution = json.loads((RAW / 'execution.json').read_bytes())
assert execution['status'] == 'failed' and execution['error'] == "KeyError('service')"
started = datetime.now(timezone.utc).isoformat()
sys.path.insert(0, str(ROOT))
from experiments.pi_generation_concurrent_http_audit import audit
stdout_path = OUT / 'original-audit-failure.stdout'
with stdout_path.open('x', encoding='utf-8', newline='\n') as stream, redirect_stdout(stream):
    try:
        audit(RAW)
    except KeyError as error:
        assert error.args == ('service',)
        traceback.print_exc(file=stream)
        error_text = repr(error)
    else:
        raise AssertionError('Original failed auditor unexpectedly returned; do not promote acceptance')
after = {p.relative_to(RAW).as_posix(): sha(p) for p in RAW.rglob('*') if p.is_file()}
assert before == after
assert all(sha(ROOT / name) == expected for name, expected in freeze['source_sha256'].items())
result = {'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
          'status': 'original_saved_audit_failure_reproduced', 'error': error_text,
          'original_execution_accepted': False, 'original_execution_status': execution['status'],
          'original_execution_sha256': sha(RAW / 'execution.json'), 'freeze_sha256': sha(freeze_path),
          'stdout_sha256': sha(stdout_path), 'raw_files': len(before),
          'raw_before_after_sha256_exact': True, 'frozen_sources_unchanged': True,
          'native_HTTP_model_or_scientific_reexecution': 0, 'project_tests': 0,
          'scope': 'Only the original immutable saved-byte audit was called once. It raises on a heterogeneous event lacking service because admission filtering indexes service before checking type. No frozen code patch, acceptance rescue, native execution or retry.'}
path = OUT / 'original-audit-failure.receipt.json'
with path.open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'receipt': path.relative_to(ROOT).as_posix(), 'sha256': sha(path),
                  'stdout_sha256': sha(stdout_path), 'error': error_text, 'raw_files': len(before)}))
