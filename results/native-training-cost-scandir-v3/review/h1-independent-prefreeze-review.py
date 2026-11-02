"""Independent stdlib-only inspection; no producer imports or execution."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
RUN = ROOT / 'reports/runs/20261102T045820Z'
FIX = ROOT / 'fixtures/native-training-cost-scandir-v3'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text(encoding='utf-8-sig'))
now = lambda: dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
started = now()
checks = []
def check(name, value, evidence=None):
    checks.append({'name': name, 'passed': bool(value), 'evidence': evidence})

def inventory(root, *, base=False):
    root = Path(root).resolve(strict=True)
    pending = [root / 'Lib', root / 'DLLs'] if base else [root]
    files = [p for p in root.iterdir() if p.is_file()] if base else []
    while pending:
        directory = pending.pop()
        if not directory.exists():
            continue
        with os.scandir(directory) as entries:
            for entry in entries:
                if base and directory == root / 'Lib' and entry.name == 'site-packages':
                    continue
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & 1024:
                    raise ValueError('Linked/reparse file encountered: ' + entry.path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    files.append(Path(entry.path))
                else:
                    raise ValueError('Nonregular file encountered: ' + entry.path)
    return sorted([{'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size,
                    'sha256': sha(p)} for p in files], key=lambda row: row['path'])

initial_paths = [FIX / 'protocol.json', FIX / 'implementation.json', RUN / 'h1-execution-plan.json',
                 RUN / 'h1-runtime-preflight.json', RUN / 'h1-prefreeze-review.json',
                 RUN / 'h1-base-standard-library-manifest.json',
                 RUN / 'h1-current-python-authentication.json', RUN / 'h1-current-python-identity.json',
                 RUN / 'h1-independent-base-signatures.json', RUN / 'h1-retained-prefreeze-rejection.json']
initial_hashes = {str(p.relative_to(ROOT)): sha(p) for p in initial_paths}
protocol = read(FIX / 'protocol.json')
freeze = read(FIX / 'implementation.json')
plan = read(RUN / 'h1-execution-plan.json')
preflight = read(RUN / 'h1-runtime-preflight.json')
owner_review = read(RUN / 'h1-prefreeze-review.json')
old_protocol = read(ROOT / 'fixtures/native-training-cost-v2/protocol.json')
old_freeze = read(ROOT / 'fixtures/native-training-cost-v2/implementation.json')
accepted = read(ROOT / 'fixtures/training-ledger-v3/implementation.json')
auth = read(RUN / 'h1-current-python-authentication.json')
identity = read(RUN / 'h1-current-python-identity.json')
signatures = read(RUN / 'h1-independent-base-signatures.json')
base_manifest = read(RUN / 'h1-base-standard-library-manifest.json')
runtime_manifest_path = ROOT / 'reports/runs/20261031T080306Z/h1-static/runtime-manifest.json'
runtime_manifest = read(runtime_manifest_path)
output = ROOT / freeze['output_directory']
check('no_scientific_output_exists_before_review', not output.exists(), str(output.relative_to(ROOT)))
check('no_scientific_modules_imported', not any(x in sys.modules for x in ('torch', 'transformers', 'numpy')))
check('protocol_hash_pinned', sha(FIX / 'protocol.json') == freeze['protocol_sha256'])
check('one_suite_no_retry', freeze['suites_permitted'] == 1 and freeze['retries'] == 0)
parse = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
check('preregistration_before_freeze_before_review', parse(protocol['predeclared_at']) <= parse(freeze['frozen_at']) < parse(started))
allowed_protocol_changes = {'predeclared_at', 'execution_revision', 'previous_attempt', 'unchanged_workload'}
check('all_other_old_protocol_fields_exact', all(protocol[k] == v for k, v in old_protocol.items() if k not in allowed_protocol_changes))
check('twelve_original_matched_jobs_config_limits_screens', all(protocol[k] == old_protocol[k] for k in ('jobs', 'config', 'ledger_limits', 'budgets', 'joint_screens', 'evaluation', 'memory_endpoint', 'observer_cost')) and len(protocol['jobs']) == 12)
check('20second_import_budget_retained', protocol['budgets']['import_seconds'] == 20)
check('source49_map_exact', freeze['source_sha256'] == old_freeze['source_sha256'] and len(freeze['source_sha256']) == 49)
check('additional3_map_exact', freeze['additional_source_sha256'] == old_freeze['additional_source_sha256'] and len(freeze['additional_source_sha256']) == 3)
for group, values in [('core', freeze['source_sha256']), ('extra', freeze['additional_source_sha256']), ('accepted_caller', accepted['source_sha256'])]:
    check(group + '_current_bytes', all(sha(ROOT / p) == h for p, h in values.items()), len(values))
check('accepted_caller_freeze_retained', sha(ROOT / 'fixtures/training-ledger-v3/implementation.json') == freeze['preserved_actual_caller_v3_freeze_sha256'])
check('original_model_asset_map_exact', freeze['model_assets'] == old_freeze['model_assets'])
model = Path(plan['model_dir'])
check('current_model_asset_bytes_exact_without_load', all((model / p).stat().st_size == v['bytes'] and sha(model / p) == v['sha256'] for p, v in freeze['model_assets'].items()))
paths = {k: Path(v).resolve() for k, v in plan['explicit_local_executable_paths'].items()}
for k, p in paths.items():
    check('executable_' + k + '_sha256', sha(p) == freeze['executables_sha256'][k])
    check('executable_' + k + '_path_sha256', hashlib.sha256(os.path.normcase(os.path.realpath(p)).encode()).hexdigest() == freeze['executable_path_sha256'][k])
check('only_base_executable_bytes_differ_from_old', all(freeze['executables_sha256'][k] == v for k, v in old_freeze['executables_sha256'].items() if k != 'base_python') and freeze['executables_sha256']['base_python'] != old_freeze['executables_sha256']['base_python'])
check('provider_bytes_frozen_original', sha(plan['provider_source']) == freeze['provider_source_sha256'] == old_freeze['provider_source_sha256'])
check('provider_path_pinned', hashlib.sha256(os.path.normcase(os.path.realpath(plan['provider_source'])).encode()).hexdigest() == freeze['provider_source_path_sha256'])
check('configured_bundle_and_identity', auth['configured_bundle_version'] == '26.1026.10807' and Path(auth['configured_python_path']).resolve() == paths['base_python'] and Path(identity['executable']).resolve() == paths['base_python'] and identity['version'] == freeze['python_version'])
check('independently_reverified_three_valid_openai_signatures', len(signatures) == 3 and all(s['status'] == 'Valid' and 'OpenAI OpCo' in s['signer_subject'] and s['signer_thumbprint'] == '45E8B6511C6E88838E0038B13037A8B1146858A9' and sha(s['path']) == s['sha256'] for s in signatures))
for p, h in freeze['python_runtime_files'].items():
    check('python_runtime_' + p + '_current_pin', sha(paths['base_python'].parent / p) == h)
check('both_python_dlls_explicitly_changed', set(freeze['python_runtime_files']) == set(old_freeze['python_runtime_files']) and all(h != old_freeze['python_runtime_files'][p] for p, h in freeze['python_runtime_files'].items()))
check('current_base_auth_and_manifest_links', sha(RUN / 'h1-current-python-authentication.json') == freeze['current_base_authentication_sha256'] == base_manifest['authentication_sha256'] and sha(RUN / 'h1-current-python-identity.json') == base_manifest['identity_sha256'] and sha(RUN / 'h1-base-standard-library-manifest.json') == freeze['current_base_standard_library_manifest_sha256'])
actual_base = inventory(paths['base_python'].parent, base=True)
check('fresh_full_base_manifest_equal', actual_base == base_manifest['files'])
check('base1028files46054193bytes', len(actual_base) == 1028 and sum(row['bytes'] for row in actual_base) == 46054193)
runtime = paths['launcher'].parent.parent
actual_runtime = inventory(runtime)
check('fresh_full_prepared_runtime_manifest_equal', actual_runtime == runtime_manifest['files'])
check('prepared26720files757706940bytes', len(actual_runtime) == 26720 and sum(row['bytes'] for row in actual_runtime) == 757706940)
check('runtime_manifest_links', sha(runtime_manifest_path) == freeze['runtime_manifest_sha256'] == protocol['dependency_change']['full_manifest_sha256'] == preflight['manifest_sha256'])
old_rt = {row['path']: row for row in runtime_manifest['original_files']}
new_rt = {row['path']: row for row in runtime_manifest['files']}
changed_rt = [p for p in set(old_rt) | set(new_rt) if old_rt.get(p) != new_rt.get(p)]
check('copied_venv_internal_change_only_scandir', changed_rt == ['Lib/site-packages/transformers/utils/import_utils.py'], changed_rt)
package_root = runtime / 'Lib/site-packages'
check('selected_ml_runtime_bytes_pinned_without_import', all((package_root / p).stat().st_size == v['bytes'] and sha(package_root / p) == v['sha256'] for p, v in freeze['selected_runtime_files'].items()))
check('external_base_change_and_causal_limit_explicit', 'additional explicit environment change' in protocol['current_base_environment']['difference_from_prior'] and 'No attribution' in protocol['current_base_environment']['inference_limit'])
check('no_stale_only_scandir_overall_workload_claim', 'Only separately prepared runtime scanner enumeration' not in protocol['unchanged_workload'])
check('preflight_hash_and_resources', sha(RUN / 'h1-runtime-preflight.json') == freeze['runtime_preflight_sha256'] == owner_review['runtime_preflight_sha256'] and preflight['free_memory_bytes'] >= protocol['budgets']['minimum_free_memory_bytes'] and preflight['free_disk_bytes'] >= protocol['budgets']['minimum_free_disk_bytes'])
check('fresh_preflight_and_current_free_disk', (parse(started) - parse(preflight['completed_at'])).total_seconds() < 900 and shutil.disk_usage(ROOT).free >= protocol['budgets']['minimum_free_disk_bytes'])
check('owner_review_exact_final_artifact_hashes', owner_review['freeze_sha256'] == sha(FIX / 'implementation.json') and owner_review['protocol_sha256'] == sha(FIX / 'protocol.json') and owner_review['plan_sha256'] == sha(RUN / 'h1-execution-plan.json'))
check('prior_prefreeze_rejection_retained', read(RUN / 'h1-retained-prefreeze-rejection.json')['expected_executable_sha256'] == old_freeze['executables_sha256']['base_python'] and preflight['prior_prefreeze_rejected_before_freeze_or_native'] is True)
check('output_still_absent_at_end', not output.exists())
check('reviewed_artifacts_unchanged_while_reading', initial_hashes == {str(p.relative_to(ROOT)): sha(p) for p in initial_paths})
failed = [row for row in checks if not row['passed']]
receipt = {'started_at': started, 'completed_at': now(), 'status': 'passed' if not failed else 'blocked',
           'checks_total': len(checks), 'checks_passed': len(checks) - len(failed), 'findings': failed, 'checks': checks,
           'reviewed_artifacts_sha256': initial_hashes,
           'independent_inventory': {'base_files': len(actual_base), 'base_bytes': sum(row['bytes'] for row in actual_base),
                                     'target_files': len(actual_runtime), 'target_bytes': sum(row['bytes'] for row in actual_runtime)},
           'execution_scope': {'scientific_suites': 0, 'native_test_or_job_launches': 0, 'model_loads': 0, 'ml_imports': 0,
                               'holdout_data_opens': 0, 'tracked_or_shared_ledger_edits': 0},
           'review_limit': 'Static source/config review, fresh full byte inventories and independently rechecked Authenticode signatures; no package import, startup deadline proof, native training or quality/performance result. Current matched arms share additional authenticated base environment change; no scandir causal attribution.'}
path = RUN / 'h1-independent-prefreeze-review.json'
path.write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode())
print(json.dumps({'status': receipt['status'], 'checks_total': len(checks), 'checks_passed': receipt['checks_passed'], 'findings': failed,
                  'receipt': str(path.relative_to(ROOT)), 'sha256': sha(path)}, ensure_ascii=False, indent=2))
