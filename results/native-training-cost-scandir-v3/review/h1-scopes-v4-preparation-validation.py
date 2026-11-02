import ast
import copy
import datetime as dt
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path.cwd()
RUN = ROOT / 'reports/runs/20261102T045820Z'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
now = lambda: dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
freeze_path = ROOT / 'fixtures/native-training-cost-scandir-v3/implementation.json'
freeze = json.loads(freeze_path.read_bytes())
old_source = ROOT / 'experiments/native_training_cost.py'
new_source = ROOT / 'experiments/native_training_cost_scopes_v4.py'
old_launcher = ROOT / 'scripts/run_native_training_cost.py'
new_launcher = ROOT / 'scripts/run_native_training_cost_scopes_v4.py'
new_test = ROOT / 'tests/test_native_training_cost_scopes_v4.py'
original_hashes = {p: sha(ROOT / p) for p in freeze['source_sha256']}
assert original_hashes == freeze['source_sha256']
assert all(sha(ROOT / p) == h for p, h in freeze['additional_source_sha256'].items())
old_tree, new_tree = (ast.parse(path.read_bytes()) for path in (old_source, new_source))
old_loop = next(node for node in old_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'training_loop')
new_loop = next(node for node in new_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'training_loop')
assert ast.unparse(new_loop.body[2]).startswith('groups = ')
assert ast.unparse(new_loop.body[3]) == 'modules = [pair for group in groups for pair in group]'
new_loop.body[2:4] = [copy.deepcopy(old_loop.body[2])]
old_sources = next(node for node in old_tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SOURCES' for t in node.targets))
new_sources = next(node for node in new_tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SOURCES' for t in node.targets))
new_sources.value = copy.deepcopy(old_sources.value)
assert ast.dump(new_tree) == ast.dump(old_tree), 'Unexpected caller change beyond flattening and versioned source pins'
old_launch_tree, new_launch_tree = (ast.parse(path.read_bytes()) for path in (old_launcher, new_launcher))
new_launch_tree.body[0] = copy.deepcopy(old_launch_tree.body[0])
old_import = next(n for n in old_launch_tree.body if isinstance(n, ast.ImportFrom) and n.module == 'experiments')
new_import = next(n for n in new_launch_tree.body if isinstance(n, ast.ImportFrom) and n.module == 'experiments')
new_import.names = copy.deepcopy(old_import.names)
assert ast.dump(old_launch_tree) == ast.dump(new_launch_tree), 'Unexpected versioned launcher behavior change'
diff = ''.join(difflib.unified_diff(old_source.read_text(encoding='utf-8').splitlines(keepends=True),
                                  new_source.read_text(encoding='utf-8').splitlines(keepends=True),
                                  fromfile='experiments/native_training_cost.py', tofile='experiments/native_training_cost_scopes_v4.py'))
(RUN / 'h1-scopes-v4-caller.diff').write_text(diff, encoding='utf-8', newline='\n')
args = [sys.executable, '-X', 'utf8', '-B', '-S', '-m', 'unittest',
        'tests.test_native_training_cost_scopes_v4', 'tests.test_native_training_cost',
        'tests.test_native_training_cost_launcher', 'tests.test_native_training_cost_entrypoint_boundary']
started = now()
completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
(RUN / 'h1-scopes-v4-pure-tests.stdout.log').write_bytes(completed.stdout)
(RUN / 'h1-scopes-v4-pure-tests.stderr.log').write_bytes(completed.stderr)
unchanged = original_hashes == {p: sha(ROOT / p) for p in freeze['source_sha256']} and all(sha(ROOT / p) == h for p, h in freeze['additional_source_sha256'].items())
receipt = {'started_at': started, 'completed_at': now(), 'command': args, 'exit_code': completed.returncode,
           'stdout_sha256': sha(RUN / 'h1-scopes-v4-pure-tests.stdout.log'), 'stderr_sha256': sha(RUN / 'h1-scopes-v4-pure-tests.stderr.log'),
           'original49_and3_extra_sources_unchanged': unchanged, 'original_freeze_sha256': sha(freeze_path),
           'versioned_source_sha256': {str(p.relative_to(ROOT)): sha(p) for p in (new_source, new_test, new_launcher)},
           'versioned_caller_ast_otherwise_exact': True, 'versioned_launcher_ast_otherwise_exact': True,
           'new_freeze_or_runtime_launch': False, 'native_jobs': 0, 'model_loads': 0, 'ml_imports': 0,
           'scope': 'Pure boundary controls only. Old caller fails before batch access; versioned caller reaches first-getitem sentinel after all19actual preserve_scopes wrappers and restores original forwards. Existing9cost/launcher controls included. No full training or startup validation.',
           'exit_condition': 'Preservation group calling contract fixed. Return to original12matched jobs only in a future separately frozen suite; do not widen deadlines, expand observer diagnostics or rerun this heartbeat scientific suite.'}
assert unchanged
path = RUN / 'h1-scopes-v4-preparation-validation.json'
path.write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode())
print(json.dumps({'exit_code': completed.returncode, 'receipt': str(path.relative_to(ROOT)), 'sha256': sha(path), 'stderr': completed.stderr.decode('utf-8', 'replace')}, indent=2))
raise SystemExit(completed.returncode)
