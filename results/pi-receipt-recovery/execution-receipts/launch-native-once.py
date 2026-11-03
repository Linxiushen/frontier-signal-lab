from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

root = Path.cwd()
run = Path(__file__).resolve().parent
now = lambda: datetime.now(timezone.utc).isoformat()
freeze = root / 'fixtures/pi-receipt-recovery/implementation.json'
frozen = json.loads(freeze.read_bytes())
assert not (root / frozen['output_directory']).exists()
argv = [frozen['python'], '-B', '-X', 'utf8', str(root / 'scripts/run_pi_receipt_recovery.py'), '--freeze', str(freeze)]
intent = {'started_at': now(), 'argv': argv, 'freeze_sha256': hashlib.sha256(freeze.read_bytes()).hexdigest(),
          'attempt': 1, 'native_retry_allowed': False, 'scientific_suite_budget': 1}
with (run / 'native-launch-attempt.json').open('x', encoding='utf8') as stream:
    json.dump(intent, stream, indent=2)
begun = time.monotonic()
with (run / 'native-launch.stdout').open('xb') as stdout, (run / 'native-launch.stderr').open('xb') as stderr:
    process = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=140,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
receipt = {'completed_at': now(), 'returncode': process.returncode, 'full_CLI_elapsed_seconds': time.monotonic() - begun,
           'attempts': 1, 'retries': 0, 'scientific_experiments': 1, 'model_loads': 0,
           'stdout_sha256': hashlib.sha256((run / 'native-launch.stdout').read_bytes()).hexdigest(),
           'stderr_sha256': hashlib.sha256((run / 'native-launch.stderr').read_bytes()).hexdigest()}
with (run / 'native-launch-result.json').open('x', encoding='utf8') as stream:
    json.dump(receipt, stream, indent=2)
print(json.dumps(receipt))
print((run / 'native-launch.stdout').read_text())
print((run / 'native-launch.stderr').read_text())
raise SystemExit(process.returncode)
