"""One-shot root-owned freeze/reservation/CLI launch. Never retries native work."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
import sys
import time
ROOT = Path.cwd(); RUN = ROOT / 'reports/runs/20261102T170820Z'
sys.path.insert(0, str(ROOT))
from scripts.check_pi_generation_concurrent_http import MANDATORY_SOURCES, validate_freeze, python_runtime_modules
import platform, sqlite3
stamp = lambda: datetime.now(timezone.utc).isoformat()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
load = lambda p: json.loads(p.read_bytes())
def save_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
assert not (RUN / 'scientific-reservation.json').exists()
assert not (RUN / 'h2-native-CLI.receipt.json').exists()
assert not (RUN / 'h2-native-concurrent-http').exists()
for name in ('node-pure-fixed', 'python-pure', 'worker-syntax'):
    receipt = load(RUN / ('h2-concurrent/' + name + '.receipt.json'))
    assert receipt['returncode'] == 0
    for stream in ('stdout', 'stderr'):
        assert sha(RUN / ('h2-concurrent/' + name + '.' + stream)) == receipt[stream + '_sha256']
assert shutil.disk_usage(ROOT).free >= 1073741824
assert subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip() == 'cead3e56b4670ea09126c0383301f25eb34be5c7'
sources = {name: sha(ROOT / name) for name in sorted(MANDATORY_SOURCES)}
reviews = [RUN / 'h2-concurrent/radar-preexecution-review.json',
           RUN / 'h2-concurrent/maintenance-preexecution-review.json']
for path in reviews:
    review = load(path)
    assert review['status'] == 'passed_for_separate_freeze'
    assert not review.get('findings', []) and not review.get('blockers', [])
    assert review.get('observed_all_source_sha256', review['source_sha256']) == sources
    assert all(sources[name] == digest for name, digest in review['source_sha256'].items())
assert set().union(*(set(load(path)['source_sha256']) for path in reviews)) == set(sources)
fixture = ROOT / 'fixtures/pi-generation-concurrent-http'; assert not fixture.exists(); fixture.mkdir()
receipts = []
for path in reviews:
    target = fixture / path.name
    target.write_bytes(path.read_bytes())
    receipts.append({'path': target.relative_to(ROOT).as_posix(), 'sha256': sha(target)})
aggregate = {'status': 'passed_for_separate_freeze', 'recorded_at': stamp(), 'source_sha256': sources,
             'reviewer_receipts': receipts, 'scientific_experiments_executed_by_reviewers': 0}
save_new(fixture / 'pre-execution-review.json', aggregate)
prior_path = ROOT / 'fixtures/pi-generation-http/implementation.json'; prior = load(prior_path)
freeze = {k: prior[k] for k in ('node', 'node_sha256', 'runtime_directory', 'runtime_manifest_path', 'runtime_manifest_sha256')}
freeze.update(frozen_at=stamp(), source_sha256=sources,
              python=sys.executable, python_sha256=sha(Path(sys.executable)), python_version=platform.python_version(),
              sqlite_version=sqlite3.sqlite_version, python_runtime_modules=python_runtime_modules(),
              protocol_path='experiments/pi_generation_concurrent_http_protocol.json', protocol_sha256=sources['experiments/pi_generation_concurrent_http_protocol.json'],
              preserved_previous_source_sha256={**prior['preserved_previous_source_sha256'], **prior['source_sha256']},
              previous_freeze_path=prior_path.relative_to(ROOT).as_posix(), previous_freeze_sha256=sha(prior_path),
              pre_execution_review_path='fixtures/pi-generation-concurrent-http/pre-execution-review.json',
              pre_execution_review_sha256=sha(fixture / 'pre-execution-review.json'),
              output_directory='reports/runs/20261102T170820Z/h2-native-concurrent-http')
validate_freeze(ROOT, freeze)
save_new(fixture / 'implementation.json', freeze)
save_new(RUN / 'scientific-reservation.json', {'reserved_at': stamp(), 'hypothesis': 'H2', 'scientific_suites': 1,
    'retries': 0, 'freeze_sha256': sha(fixture / 'implementation.json'), 'launcher_sha256': sha(Path(__file__)),
    'output_directory': freeze['output_directory'], 'free_disk_bytes': shutil.disk_usage(ROOT).free})
argv = [sys.executable, '-X', 'utf8', '-B', 'scripts/run_pi_generation_concurrent_http.py',
        '--freeze', 'fixtures/pi-generation-concurrent-http/implementation.json']
start = time.monotonic(); started = stamp()
with (RUN / 'h2-native-CLI.stdout.log').open('xb') as stdout, (RUN / 'h2-native-CLI.stderr.log').open('xb') as stderr:
    process = subprocess.run(argv, cwd=ROOT, stdout=stdout, stderr=stderr,
                             creationflags=subprocess.CREATE_NO_WINDOW, timeout=400)
receipt = {'started_at': started, 'completed_at': stamp(), 'argv': argv, 'exit_code': process.returncode,
           'full_CLI_wall_seconds': time.monotonic() - start, 'CLI_invocations': 1, 'retries': 0,
           'includes': 'Python process creation/startup/imports, source/runtime authentication, suite/workers/restarts/copies/audit/exit',
           'excludes': 'Protocol preparation, independent reviews, prior pure regressions and later publication/checks',
           'stdout_sha256': sha(RUN / 'h2-native-CLI.stdout.log'), 'stderr_sha256': sha(RUN / 'h2-native-CLI.stderr.log')}
save_new(RUN / 'h2-native-CLI.receipt.json', receipt)
print(json.dumps(receipt))
