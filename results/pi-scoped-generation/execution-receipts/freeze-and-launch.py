"""Single separately reviewed native experiment launch; never retry an outcome."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
RUN = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from scripts.check_pi_scoped_generation import MANDATORY_SOURCES, PREVIOUS, RUNTIME_FIELDS, OUTPUT, validate_freeze

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
now = lambda: datetime.now(timezone.utc).isoformat()
load = lambda p: json.loads(p.read_bytes())

def save(path, value):
    with path.open('x', encoding='utf8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == '729eeb2341ce63a8f2812fbe97cd760723086213'
assert not (ROOT / OUTPUT).exists()
fixture = ROOT / 'fixtures/pi-scoped-generation'
assert not fixture.exists()
sources = {name: sha(ROOT / name) for name in sorted(MANDATORY_SOURCES)}
review_names = ['maintenance-prefreeze-review.json', 'radar-prefreeze-review.json']
reviews = [load(RUN / name) for name in review_names]
assert all(r['status'] == 'passed_for_separate_freeze' and r['source_sha256'] == sources and not r['findings'] for r in reviews)
assert len({r['reviewer'] for r in reviews}) == 2
root_review = {'status': 'passed_for_separate_freeze', 'reviewer': 'root', 'reviewed_at': now(), 'source_sha256': sources,
    'authored_sources': ['scripts/pi_scoped_generation_worker.mjs', 'experiments/pi_scoped_generation_protocol.json'],
    'findings': [], 'cross_review': 'Read full independent auditor/tests/controller/checker and original native chain/dispatcher helpers. Independent peer reviews cover root-authored worker/protocol; their authored scopes are disclosed. Preserve previous failed suite. No outcome yet.',
    'pre_execution_corrections': ['Release qualified original positive tool gates during recovery', 'One observed terminal epoch shared by identity and trace', 'Isolated Python exact-directory runpy bootstrap validated through help only'],
    'scientific_suites_before_freeze': 0}
save(RUN / 'root-prefreeze-review.json', root_review)
fixture.mkdir()
for name in review_names + ['root-prefreeze-review.json']:
    shutil.copyfile(RUN / name, fixture / name)
for stem in ['auditor-portable-test-1', 'auditor-portable-test-2', 'isolated-server-help-discovered-failure', 'isolated-server-help-fixed']:
    for suffix in ['json', 'stdout', 'stderr']:
        shutil.copyfile(RUN / f'{stem}.{suffix}', fixture / f'{stem}.{suffix}')
aggregate = {'status': 'passed_for_separate_freeze', 'recorded_at': now(), 'source_sha256': sources,
    'reviewer_receipts': [{'path': (fixture / n).relative_to(ROOT).as_posix(), 'sha256': sha(fixture / n)} for n in review_names + ['root-prefreeze-review.json']],
    'scientific_experiments_executed_by_reviewers': 0}
save(fixture / 'pre-execution-review.json', aggregate)
previous = load(ROOT / PREVIOUS)
freeze = {k: previous[k] for k in RUNTIME_FIELDS}
freeze.update(frozen_at=now(), source_sha256=sources,
    preserved_previous_source_sha256={**previous['preserved_previous_source_sha256'], **previous['source_sha256']},
    previous_freeze_path=PREVIOUS, previous_freeze_sha256=sha(ROOT / PREVIOUS),
    protocol_path='experiments/pi_scoped_generation_protocol.json', protocol_sha256=sources['experiments/pi_scoped_generation_protocol.json'],
    pre_execution_review_path='fixtures/pi-scoped-generation/pre-execution-review.json',
    pre_execution_review_sha256=sha(fixture / 'pre-execution-review.json'), output_directory=OUTPUT)
save(fixture / 'implementation.json', freeze)
validate_freeze(ROOT, freeze)
assert shutil.disk_usage(ROOT / 'local-state').free >= 1073741824
command = [sys.executable, '-X', 'utf8', '-B', '-S', str(ROOT / 'scripts/run_pi_scoped_generation.py'), '--freeze', str(fixture / 'implementation.json')]
intent = {'recorded_at': now(), 'argv': command, 'freeze_sha256': sha(fixture / 'implementation.json'),
    'launcher_sha256': sha(Path(__file__)), 'attempt': 1, 'retries': 0,
    'native_suites': 1, 'H2_scientific_suites': 1, 'model_loads': 0,
    'free_disk_bytes': shutil.disk_usage(ROOT / 'local-state').free}
save(RUN / 'launch-intent.json', intent)
start = time.monotonic()
result = subprocess.run(command, cwd=ROOT, capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
(RUN / 'native.stdout').write_bytes(result.stdout)
(RUN / 'native.stderr').write_bytes(result.stderr)
receipt = {**intent, 'completed_at': now(), 'returncode': result.returncode,
    'full_cli_elapsed_seconds': time.monotonic() - start,
    'stdout_sha256': sha(RUN / 'native.stdout'), 'stderr_sha256': sha(RUN / 'native.stderr')}
save(RUN / 'launch-receipt.json', receipt)
print(json.dumps(receipt, ensure_ascii=False))
print(result.stdout.decode('utf8', 'replace'))
if result.returncode:
    print(result.stderr.decode('utf8', 'replace'))
raise SystemExit(result.returncode)
