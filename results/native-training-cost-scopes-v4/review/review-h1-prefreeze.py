"""Independent saved-source/config/byte review. No project or ML imports."""
from pathlib import Path
from datetime import datetime, timezone
import ast
import ctypes
import hashlib
import json
import os
import shutil
import sys

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
RUN = ROOT / 'reports/runs/20261102T065705Z'
FIX = ROOT / 'fixtures/native-training-cost-scopes-v4-reviewed'
OLD = ROOT / 'fixtures/native-training-cost-scopes-v4'
PRIOR = ROOT / 'fixtures/native-training-cost-scandir-v3'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text(encoding='utf-8-sig'))
now = lambda: datetime.now(timezone.utc).isoformat()
started = now()
checks = []
def check(name, passed, evidence=None):
    checks.append({'name': name, 'passed': bool(passed), 'evidence': evidence})

def inventory(root, base=False):
    root = Path(root).resolve(strict=True)
    stack = [root / 'Lib', root / 'DLLs'] if base else [root]
    files = [p for p in root.iterdir() if p.is_file()] if base else []
    while stack:
        directory = stack.pop()
        if not directory.exists():
            continue
        with os.scandir(directory) as entries:
            for entry in entries:
                if base and directory == root / 'Lib' and entry.name == 'site-packages':
                    continue
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & 1024:
                    raise ValueError('Reparse point: ' + entry.path)
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files.append(Path(entry.path))
                else:
                    raise ValueError('Nonregular file: ' + entry.path)
    return sorted([{'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size,
                    'sha256': sha(p)} for p in files], key=lambda r: r['path'])

paths_to_pin = [FIX / 'protocol.json', FIX / 'implementation.json', OLD / 'protocol.json',
               OLD / 'implementation.json', RUN / 'h1-execution-plan.json',
               RUN / 'h1-qualified-prefreeze-review.json', RUN / 'h1-runtime-preflight.json',
               RUN / 'h1-base-standard-library-manifest.json', RUN / 'h1-current-python-authentication.json',
               RUN / 'h1-current-python-identity.json', HERE / 'h1-independent-base-signatures.json']
initial = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths_to_pin}
p, f, op, of = [read(d / name) for d, name in [(FIX, 'protocol.json'), (FIX, 'implementation.json'),
                                             (OLD, 'protocol.json'), (OLD, 'implementation.json')]]
pp, pf = read(PRIOR / 'protocol.json'), read(PRIOR / 'implementation.json')
plan = read(RUN / 'h1-execution-plan.json')
review = read(RUN / 'h1-qualified-prefreeze-review.json')
base = read(RUN / 'h1-base-standard-library-manifest.json')
auth = read(RUN / 'h1-current-python-authentication.json')
identity = read(RUN / 'h1-current-python-identity.json')
signatures = read(HERE / 'h1-independent-base-signatures.json')
runtime_manifest_path = ROOT / 'reports/runs/20261031T080306Z/h1-static/runtime-manifest.json'
runtime_manifest = read(runtime_manifest_path)
output = ROOT / f['output_directory']
parse = lambda s: datetime.fromisoformat(s.replace('Z', '+00:00'))
check('no_science_output_or_suite_reservation_before_review', not output.exists() and not (RUN / 'h1-suite-reserved.json').exists())
check('corrected_protocol_entrypoint_hash_matches_real_v4', p['entrypoint'] == 'scripts/run_native_training_cost_scopes_v4.py' and sha(ROOT / p['entrypoint']) == f['entrypoint_sha256'])
check('protocol_pin', sha(FIX / 'protocol.json') == f['protocol_sha256'])
check('preregistration_before_freeze_before_review', parse(p['predeclared_at']) <= parse(f['frozen_at']) < parse(started))
check('unexecuted_candidate_retained_exact', sha(OLD / 'protocol.json') == 'ace5fb9b7b06fb71201cab8bbf706a9cacc4566fb36241bd043dec0519740156' and sha(OLD / 'implementation.json') == f['unexecuted_candidate_freeze_sha256'] == 'dff81fd9d5450d027239096827366323a6fe95005cb2c8a6da1d59b1e3aa388e')
pdiff = [k for k in set(p) | set(op) if p.get(k) != op.get(k)]
check('candidate_protocol_changes_only_entrypoint_time', set(pdiff) == {'predeclared_at', 'entrypoint'}, pdiff)
fdiff = [k for k in set(f) | set(of) if f.get(k) != of.get(k)]
check('candidate_freeze_changes_only_provenance_time_protocol', set(fdiff) == {'frozen_at', 'protocol_sha256', 'unexecuted_candidate_freeze_sha256', 'preexecution_wording_correction'}, fdiff)
check('one_suite_zero_retries', f['suites_permitted'] == 1 and f['retries'] == 0)
for key in ['jobs', 'config', 'ledger_limits', 'budgets', 'joint_screens', 'evaluation', 'memory_endpoint', 'observer_cost']:
    check('original_v3_' + key + '_exact', p[key] == pp[key])
check('twelve_jobs_original_seeds', len(p['jobs']) == 12 and {j['seed'] for j in p['jobs']} == {503, 701, 907})
check('original_fixed_import_case_suite_resource_gates', p['budgets']['import_seconds'] == 20 and p['budgets']['case_seconds'] == 180 and p['budgets']['suite_seconds'] == 1200 and p['budgets']['minimum_free_disk_bytes'] == 5 * 1024**3 and p['budgets']['minimum_free_memory_bytes'] == 8 * 1024**3)
check('original49core3extra_sources_retained', all(f['source_sha256'][k] == v for k, v in pf['source_sha256'].items()) and f['additional_source_sha256'] == pf['additional_source_sha256'])
check('52core3extra_pins', len(f['source_sha256']) == 52 and len(f['additional_source_sha256']) == 3)
for group, pins in [('core', f['source_sha256']), ('extra', f['additional_source_sha256']), ('accepted', read(ROOT / 'fixtures/training-ledger-v3/implementation.json')['source_sha256'])]:
    check(group + '_current_source_bytes', all(sha(ROOT / n) == h for n, h in pins.items()), len(pins))
source = (ROOT / 'experiments/native_training_cost_scopes_v4.py').read_text(encoding='utf-8')
prior_source = (ROOT / 'experiments/native_training_cost.py').read_text(encoding='utf-8')
normalized = source.replace("groups=cost.preservation_modules(model) if job['method']!='dense' else ()\n    modules=[pair for group in groups for pair in group]", "modules=cost.preservation_modules(model) if job['method']!='dense' else []").replace(",\n    'experiments/native_training_cost_scopes_v4.py','tests/test_native_training_cost_scopes_v4.py',\n    'scripts/run_native_training_cost_scopes_v4.py'", '')
check('caller_AST_only_flattening_and_source_pin_additions', ast.dump(ast.parse(normalized)) == ast.dump(ast.parse(prior_source)))
check('source_launches_its_own_v4_worker', 'SCRIPT=Path(__file__)' in source and 'str(SCRIPT)' in source)
check('model_asset_maps_unchanged_without_load', f['model_assets'] == pf['model_assets'])
check('model_assets_current_bytes_without_load', all((Path(plan['model_dir']) / n).stat().st_size == r['bytes'] and sha(Path(plan['model_dir']) / n) == r['sha256'] for n, r in f['model_assets'].items()))
executables = {k: Path(v).resolve() for k, v in plan['explicit_local_executable_paths'].items()}
for key, path in executables.items():
    check('executable_' + key + '_bytes_and_path', sha(path) == f['executables_sha256'][key] and hashlib.sha256(os.path.normcase(os.path.realpath(path)).encode()).hexdigest() == f['executable_path_sha256'][key])
check('same_binaries_as_v3', f['executables_sha256'] == pf['executables_sha256'] and f['python_runtime_files'] == pf['python_runtime_files'])
check('fresh_valid_independent_openai_signatures', len(signatures) == 3 and all(s['status'] == 'Valid' and 'OpenAI OpCo' in s['signer_subject'] and s['signer_thumbprint'] == '45E8B6511C6E88838E0038B13037A8B1146858A9' and sha(s['path']) == s['sha256'] for s in signatures))
check('configured_bundle_identity', auth['configured_bundle_version'] == '26.1026.10807' and Path(auth['configured_python_path']).resolve() == executables['base_python'] == Path(identity['executable']).resolve() and identity['version'] == f['python_version'])
check('current_base_manifest_auth_identity_links', sha(RUN / 'h1-base-standard-library-manifest.json') == f['current_base_standard_library_manifest_sha256'] and sha(RUN / 'h1-current-python-authentication.json') == f['current_base_authentication_sha256'] == base['authentication_sha256'] and sha(RUN / 'h1-current-python-identity.json') == base['identity_sha256'])
actual_base = inventory(executables['base_python'].parent, base=True)
check('fresh_full_base_inventory1030files46059001bytes', actual_base == base['files'] and len(actual_base) == 1030 and sum(r['bytes'] for r in actual_base) == 46059001)
prior_base = read(ROOT / 'reports/runs/20261102T045820Z/h1-base-standard-library-manifest.json')
by = {r['path']: r for r in actual_base}
check('prior1028base_files_exact', len(prior_base['files']) == 1028 and all(by.get(r['path']) == r for r in prior_base['files']))
added = [r for r in actual_base if r['path'] not in {x['path'] for x in prior_base['files']}]
check('only_two_disclosed_base_caches_added', added == p['current_base_environment']['delta_since_v3'], added)
runtime = executables['launcher'].parent.parent
actual_runtime = inventory(runtime)
check('fresh_full_runtime26720files757706940bytes', actual_runtime == runtime_manifest['files'] and len(actual_runtime) == 26720 and sum(r['bytes'] for r in actual_runtime) == 757706940)
check('runtime_manifest_hash_links', sha(runtime_manifest_path) == f['runtime_manifest_sha256'] == p['dependency_change']['full_manifest_sha256'])
check('selected_runtime_bytes_without_import', all((runtime / 'Lib/site-packages' / n).stat().st_size == r['bytes'] and sha(runtime / 'Lib/site-packages' / n) == r['sha256'] for n, r in f['selected_runtime_files'].items()))
check('provider_exact_bytes_and_path', sha(plan['provider_source']) == f['provider_source_sha256'] == pf['provider_source_sha256'] and hashlib.sha256(os.path.normcase(os.path.realpath(plan['provider_source'])).encode()).hexdigest() == f['provider_source_path_sha256'])
class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), *[(n, ctypes.c_ulonglong) for n in ['total_phys', 'avail_phys', 'total_page', 'avail_page', 'total_virtual', 'avail_virtual', 'avail_extended']]]
memory = MemoryStatus(); memory.length = ctypes.sizeof(memory)
if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
    raise OSError('GlobalMemoryStatusEx failed')
resources = {'observed_at': now(), 'free_memory_bytes': memory.avail_phys, 'free_disk_bytes': shutil.disk_usage(ROOT).free}
check('fresh_current_original_resources', resources['free_memory_bytes'] >= p['budgets']['minimum_free_memory_bytes'] and resources['free_disk_bytes'] >= p['budgets']['minimum_free_disk_bytes'], resources)
check('owner_review_qualified_hashes', review['status'] == 'passed' and review['freeze_sha256'] == sha(FIX / 'implementation.json') and review['protocol_sha256'] == sha(FIX / 'protocol.json') and review['plan_sha256'] == sha(RUN / 'h1-execution-plan.json'))
check('old_prefreeze_remains_authenticated_historical_only', sha(RUN / 'h1-runtime-preflight.json') == f['runtime_preflight_sha256'] == review['runtime_preflight_sha256'])
check('explicit_composite_environment_limit', 'No attribution' in p['current_base_environment']['inference_limit'] and 'not equivalent' in p['preflight'])
check('no_scientific_imports_in_reviewer', not {'torch', 'transformers', 'numpy'} & set(sys.modules))
check('output_still_absent', not output.exists())
check('all_reviewed_artifacts_unchanged', initial == {x.relative_to(ROOT).as_posix(): sha(x) for x in paths_to_pin})
failed = [c for c in checks if not c['passed']]
result = {'started_at': started, 'completed_at': now(), 'status': 'passed' if not failed else 'blocked', 'checks_total': len(checks), 'checks_passed': len(checks) - len(failed), 'findings': failed, 'checks': checks, 'reviewed_artifacts_sha256': initial, 'protocol_path': (FIX / 'protocol.json').relative_to(ROOT).as_posix(), 'freeze_path': (FIX / 'implementation.json').relative_to(ROOT).as_posix(), 'resources': resources, 'inventory': {'base_files': len(actual_base), 'base_bytes': sum(r['bytes'] for r in actual_base), 'runtime_files': len(actual_runtime), 'runtime_bytes': sum(r['bytes'] for r in actual_runtime)}, 'scope': 'Independent source/AST/config/full runtime and base byte inventory; Authenticode and read-only Windows memory statistics. No project/ML imports, native suite, model load, holdout read, scientific execution or shared/tracked writes. Original07:01preflight remains historical; fresh resources and full inventories in this review supplement it. Maintenance classification still required separately before invocation.', 'scientific_suites': 0, 'native_suite_launches': 0, 'model_loads': 0, 'ML_imports': 0, 'holdout_data_reads': 0}
receipt = HERE / 'h1-independent-qualified-prefreeze-review.json'
with receipt.open('x', encoding='utf-8', newline='\n') as h:
    json.dump(result, h, ensure_ascii=False, indent=2); h.write('\n')
print(json.dumps({'status': result['status'], 'checks_total': result['checks_total'], 'checks_passed': result['checks_passed'], 'findings': failed, 'receipt': receipt.relative_to(ROOT).as_posix(), 'sha256': sha(receipt)}))
