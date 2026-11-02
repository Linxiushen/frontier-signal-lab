"""Independent v5 preparation review; stdlib, mocked tests and saved records."""
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
import ast
import copy
import hashlib
import json
import subprocess
import sys
import time

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
RUN = ROOT / 'reports/runs/20261102T065705Z'
PREP = RUN / 'evaluator-v5-preparation'
read = lambda p: json.loads(p.read_bytes())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
now = lambda: datetime.now(timezone.utc).isoformat()
started = now()
checks = []
def ck(name, passed, evidence=None):
    checks.append({'name': name, 'passed': bool(passed), 'evidence': evidence})
receipt = read(PREP / 'receipt.json')
pins = read(ROOT / 'fixtures/native-training-cost-scopes-v4-reviewed/implementation.json')
all_old = {**pins['source_sha256'], **pins['additional_source_sha256']}
initial = {p: sha(ROOT / p) for p in [*all_old, *receipt['sources']]}
ck('receipt_source3_current_bytes_exact', all(sha(ROOT / p) == r['sha256'] and (ROOT / p).stat().st_size == r['bytes'] for p, r in receipt['sources'].items()))
ck('old55frozen_sources_exact', len(all_old) == 55 and all(sha(ROOT / p) == h for p, h in all_old.items()))
for item in receipt['differential_controls']:
    ck(item['caller'] + '_differential_logs_exact', sha(PREP / (item['caller'] + '-positive-fixture.stdout.log')) == item['stdout_sha256'] and sha(PREP / (item['caller'] + '-positive-fixture.stderr.log')) == item['stderr_sha256'])
    ck(item['caller'] + '_differential_expected_exit', item['exit_code'] == item['expected_exit_code'])
ck('prior22focused_test_logs_exact', sha(PREP / 'focused.stdout.log') == receipt['focused_tests']['stdout_sha256'] and sha(PREP / 'focused.stderr.log') == receipt['focused_tests']['stderr_sha256'] and receipt['focused_tests']['exit_code'] == 0)
prior_tree = ast.parse((ROOT / 'experiments/native_training_cost_scopes_v4.py').read_text(encoding='utf-8'))
new_tree = ast.parse((ROOT / 'experiments/native_training_cost_evaluator_v5.py').read_text(encoding='utf-8'))
byname = lambda tree, name: next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
source_assignment = lambda n: isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SOURCES' for t in n.targets)
old_sources = next(n for n in prior_tree.body if source_assignment(n))
new_tree.body = [n for n in new_tree.body if not isinstance(n, ast.FunctionDef) or n.name != 'verify_evaluator_cleanup']
new_tree.body = [copy.deepcopy(old_sources) if source_assignment(n) else n for n in new_tree.body]
class NormalizeCleanup(ast.NodeTransformer):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == 'verify_evaluator_cleanup':
            return ast.Call(func=ast.Attribute(value=ast.Name(id='prior', ctx=ast.Load()), attr='verify_cleanup', ctx=ast.Load()), args=[ast.Name(id='r', ctx=ast.Load()), ast.Constant(value='healthy')], keywords=[])
        return self.generic_visit(node)
new_tree = NormalizeCleanup().visit(new_tree)
ck('caller_AST_only_new_validator_cleanup_call_and_sources', ast.dump(new_tree) == ast.dump(prior_tree))
old_launcher = ast.parse((ROOT / 'scripts/run_native_training_cost_scopes_v4.py').read_text(encoding='utf-8'))
new_launcher = ast.parse((ROOT / 'scripts/run_native_training_cost_evaluator_v5.py').read_text(encoding='utf-8'))
new_launcher.body[0] = copy.deepcopy(old_launcher.body[0])
for n in new_launcher.body:
    if isinstance(n, ast.ImportFrom) and n.module == 'experiments':
        n.names = [ast.alias(name='native_training_cost_scopes_v4', asname='study')]
ck('launcher_AST_only_docstring_and_module_binding', ast.dump(old_launcher) == ast.dump(new_launcher))
sys.path.insert(0, str(ROOT))
from experiments import native_training_cost_evaluator_v5 as current
from experiments import native_training_cost_scopes_v4 as prior
new3 = tuple(receipt['sources'])
ck('58unique_source_pins_exact_old55plus3', len(current.SOURCES) == len(set(current.SOURCES)) == 58 and set(current.SOURCES) == set(all_old) | set(new3) and tuple(current.SOURCES[:52]) == prior.SOURCES)
ck('all_jobs_config_limits_training_evaluation_release_unchanged', current.CONFIG == prior.CONFIG and current.jobs() == prior.jobs() and current.LIMITS == prior.LIMITS and all(ast.dump(byname(ast.parse((ROOT / 'experiments/native_training_cost_evaluator_v5.py').read_text(encoding='utf-8')), name)) == ast.dump(byname(prior_tree, name)) for name in ['training_loop', 'prepare', 'worker', 'run_case', 'validate_release', 'evaluate', 'paired_results', 'run']))
saved = read(RUN / 'native-training-cost-scopes-v4/report.json')['evaluator']
chain = saved['identity']['verified_ancestry']
actual_row = next(r for r in chain if r['pid'] == saved['identity']['self_receipt']['pid'])
launcher_row = next(r for r in chain if r['pid'] != actual_row['pid'])
launcher_ref, actual_ref = [SimpleNamespace(pid=r['pid'], creation_filetime=r['creation_filetime']) for r in [launcher_row, actual_row]]
saved_before = json.dumps(saved, sort_keys=True)
accepted = copy.deepcopy(saved)
current.verify_evaluator_cleanup(accepted, launcher_ref, actual_ref)
ck('new_validator_accepts_exact_actual_saved2handle_cleanup', accepted['cleanup_exact_retained_identity_set'] is True and len(accepted['cleanup']['exit_codes']) == 2 and saved_before == json.dumps(saved, sort_keys=True))
ck('saved_acceptance_flag_and_failure_remain_unchanged', accepted['passed'] is False and accepted['error'] == "KeyError: 'censuses'" and saved['passed'] is False and 'censuses' not in accepted)
reverse = copy.deepcopy(saved); reverse['cleanup']['exit_codes'].reverse()
current.verify_evaluator_cleanup(reverse, launcher_ref, actual_ref)
ck('validator_accepts_reordered_exact_identity_set', reverse['cleanup_exact_retained_identity_set'] is True)
mutations = [
    ('bool_creation', lambda r: r['cleanup']['exit_codes'][0].update(creation_filetime=True)),
    ('float_exit', lambda r: r['cleanup']['exit_codes'][0].update(exit_code=0.0)),
    ('extra_row_field', lambda r: r['cleanup']['exit_codes'][0].update(untrusted=True)),
    ('string_exit', lambda r: r['cleanup']['exit_codes'][0].update(exit_code='0')),
    ('wrong_identity', lambda r: r['cleanup']['exit_codes'][0].update(creation_filetime=1)),
]
for label, mutate in mutations:
    record = copy.deepcopy(saved); mutate(record)
    try:
        current.verify_evaluator_cleanup(record, launcher_ref, actual_ref)
        rejected = False
    except current.obs.ObserverError:
        rejected = True
    ck('saved_record_negative_' + label, rejected and 'cleanup_exact_retained_identity_set' not in record)
command = [sys.executable, '-X', 'utf8', '-B', '-S', '-m', 'unittest', 'tests.test_native_training_cost_evaluator_v5', '-v']
wall = time.perf_counter(); process = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=60)
stdout, stderr = HERE / 'h1-v5-independent-tests.stdout.log', HERE / 'h1-v5-independent-tests.stderr.log'
for p, data in [(stdout, process.stdout), (stderr, process.stderr)]:
    with p.open('xb') as h: h.write(data)
ck('independent10mocked_unit_methods_passed', process.returncode == 0 and b'Ran 10 tests' in process.stderr and process.stderr.rstrip().endswith(b'OK'))
ck('all58reviewed_source_bytes_still_exact', initial == {p: sha(ROOT / p) for p in initial})
ck('reviewer_no_ML_imports', not {'numpy', 'torch', 'transformers'} & set(sys.modules))
failed = [c for c in checks if not c['passed']]
result = {'started_at': started, 'completed_at': now(), 'status': 'passed_preparation_only' if not failed else 'blocked', 'checks_total': len(checks), 'checks_passed': len(checks) - len(failed), 'findings': failed, 'checks': checks, 'new_sources': receipt['sources'], 'preparation_receipt': (PREP / 'receipt.json').relative_to(ROOT).as_posix(), 'preparation_receipt_sha256': sha(PREP / 'receipt.json'), 'old55pins_exact': True, 'source_pin_count': len(current.SOURCES), 'test': {'command': command, 'exit_code': process.returncode, 'wall_seconds': time.perf_counter() - wall, 'stdout_sha256': sha(stdout), 'stderr_sha256': sha(stderr), 'methods': 10, 'scope': 'Real Python evaluator controller/parser/validators with process/provider I/O replaced by fixtures. Five further saved-record malformed-schema controls, one exact real saved evaluator record and reorderedidentitypositive. No native WindowsJob/model process.'}, 'scientific_suites': 0, 'native_jobs': 0, 'model_loads': 0, 'ML_imports': 0, 'shared_or_tracked_writes': False, 'old_v4_frozen_acceptance': False, 'new_freeze': False, 'limits': 'Static AST/source/hash review and mocked/saved-metadata tests only. Exact2retainedrole validator rejects aliasing, malformed/bool identities, incomplete/extra/missing/duplicate exits, nonzero exits and active Jobs. Prior result identity/provider/fullimportprefix gates remain unchanged. No new native/model/scientific acceptance, retry, or v4 outcome rescue.'}
out = HERE / 'h1-v5-independent-preparation-review.json'
with out.open('x', encoding='utf-8', newline='\n') as h:
    json.dump(result, h, ensure_ascii=False, indent=2); h.write('\n')
print(json.dumps({'status': result['status'], 'checks': result['checks_total'], 'passed': result['checks_passed'], 'findings': failed, 'receipt': out.relative_to(ROOT).as_posix(), 'sha256': sha(out)}))
