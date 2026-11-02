"""Saved-copy H1 outcome audit only; never executes a native job or model."""
from pathlib import Path
from datetime import datetime, timezone
import copy
import hashlib
import json
import math
import shutil
import sys

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
RUN = ROOT / 'reports/runs/20261102T065705Z'
ORIGINAL = RUN / 'native-training-cost-scopes-v4'
COPY = HERE / 'h1-independent-saved-copy'
FIX = ROOT / 'fixtures/native-training-cost-scopes-v4-reviewed'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_bytes())
now = lambda: datetime.now(timezone.utc).isoformat()
started = now()
checks = []
def check(name, passed, evidence=None):
    checks.append({'name': name, 'passed': bool(passed), 'evidence': evidence})
def inventory(folder):
    paths = sorted(p for p in folder.rglob('*') if p.is_file())
    assert not any(p.is_symlink() for p in folder.rglob('*'))
    return {p.relative_to(folder).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in paths}

complete, reserved = [read(RUN / n) for n in ['h1-suite-completed.json', 'h1-suite-reserved.json']]
protocol, freeze = [read(FIX / n) for n in ['protocol.json', 'implementation.json']]
original_before = inventory(ORIGINAL)
assert not COPY.exists()
shutil.copytree(ORIGINAL, COPY, copy_function=shutil.copy2)
check('full_saved_copy_byte_identical_before_review', inventory(COPY) == original_before)
sys.path.insert(0, str(ROOT))
from scripts.audit_native_training_cost import audit
from experiments import native_training_cost as study
canonical = audit(COPY, checkpoints=True)
report = read(COPY / 'report.json')
check('canonical_saved_receipt_audit_passed', canonical['receipt_integrity_passed'])
check('no_ML_imports_by_saved_auditor', not {'torch', 'transformers', 'numpy'} & set(sys.modules))
check('one_suite_one_CLI_no_retry', complete['scientific_slots_reserved'] == reserved['scientific_slots_reserved'] == report['scientific_suites'] == 1 and complete['original_CLI_invocations'] == reserved['original_CLI_invocations'] == 1 and complete['retries'] == reserved['retries'] == report['retries'] == 0)
check('review_wrapper_protocol_freeze_hash_chain', sha(FIX / 'protocol.json') == freeze['protocol_sha256'] == report['protocol_sha256'] and sha(FIX / 'implementation.json') == report['freeze_sha256'] == reserved['freeze_sha256'] == complete['freeze_sha256'] and sha(ROOT / reserved['independent_review_path']) == reserved['independent_review_sha256'] and sha(RUN / 'execute-h1-once.py') == reserved['execution_wrapper_sha256'])
check('all55frozen_source_pins_current_exact', len(freeze['source_sha256']) == 52 and len(freeze['additional_source_sha256']) == 3 and all(sha(ROOT / p) == h for p, h in {**freeze['source_sha256'], **freeze['additional_source_sha256']}.items()))
check('wrapper_stdout_stderr_exact', sha(RUN / 'h1-execution.stdout.log') == complete['stdout_sha256'] and sha(RUN / 'h1-execution.stderr.log') == complete['stderr_sha256'])
check('wrapper_outcome_consistent_with_execution', complete['outer_timeout'] is False and complete['exit_code'] == (0 if report['passed'] else 1))
check('all_actual_jobs_exact_original_ordered_prefix', [c['job'] for c in report['cases']] == protocol['jobs'][:len(report['cases'])])
case_rows = []
retained_exit_codes = []
for case in report['cases']:
    folder = COPY / case['id']
    actual = case.get('worker_identity', {}).get('self_receipt')
    cleanup = case.get('cleanup', case.get('failure_cleanup', {}))
    check(case['id'] + '_cleanup_empty_all_retained_exited', cleanup.get('job_active_count') == 0 and cleanup.get('all_retained_handles_exited') is True)
    retained_exit_codes.extend(cleanup.get('exit_codes', []))
    if not case['passed']:
        check(case['id'] + '_failure_stops_prefix', case is report['cases'][-1] and report['passed'] is False)
        continue
    os_image = case['worker_identity']['os_image']
    check(case['id'] + '_actual_interpreter_identity', (actual['pid'], actual['creation_filetime']) == (os_image['pid'], os_image['creation_filetime']) and actual['pid'] != case['launcher']['pid'] and os_image['sha256'] == freeze['executables_sha256']['base_python'] and os_image['queried_from_retained_handle'] and os_image['matches_frozen_path_and_hash'])
    raw_imports = [read(folder / ('import-progress-' + str(i).zfill(2) + '.json')) for i in range(7)]
    check(case['id'] + '_import_markers_complete_exact', raw_imports == case['import_progress'] and [r['seq'] for r in raw_imports] == list(range(7)) and raw_imports[-1]['step'] == 'versions-verified')
    stage = case['stages']['postimport']
    imports = stage['import_completed_perf_counter'] - stage['import_started_perf_counter']
    check(case['id'] + '_import_original20s', 0 < imports < protocol['budgets']['import_seconds'], imports)
    loop = case['loop_after']['loop']
    info = case['stages']['pretrain']['model']
    valid = case['stages']['postvalidation']['validation']
    check(case['id'] + '_original_optimizer_finite_all_counters', info['optimizer'] == protocol['config']['optimizer'] and valid['final_validity']['optimizer_counters'] == [loop['steps_completed']] * 76 and valid['final_validity']['final_parameter_gradient_moments_finite'] is True)
    check(case['id'] + '_checkpoint_full_bytes_hash_and_training_no_holdout', (folder / 'endpoint.pt').stat().st_size == valid['checkpoint_bytes'] and sha(folder / 'endpoint.pt') == valid['checkpoint_sha256'] and valid['no_holdout_evaluation'] and info['holdout_opened'] is False)
    check(case['id'] + '_target_count_and_arm_budget', loop['training_target_positions'] == loop['steps_completed'] * 128 and ((case['job']['arm'] == 'token' and loop['steps_completed'] == 64) or (case['job']['arm'] == 'time' and 60 <= loop['training_loop_wall_seconds'] <= 61)))
    timings = loop['step_timings']; walls = sorted(t['wall_seconds'] for t in timings)
    check(case['id'] + '_observed_latency_quantiles_recomputed', [t['index'] for t in timings] == list(range(loop['steps_completed'])) and all(loop['step_summary'][label] == walls[math.ceil(len(walls) * q) - 1] for label, q in [('p50_step_seconds', .5), ('p95_step_seconds', .95), ('p99_step_seconds', .99)]))
    a, b = loop['loop_perf_counter_start'], loop['loop_perf_counter_end']
    selected = [r for r in case['active_window']['observations'] if a <= r['query_started_perf_counter'] <= r['sample']['perf_counter'] <= r['query_completed_perf_counter'] <= b]
    stamps = [a] + [r['sample']['perf_counter'] for r in selected] + [b]
    m = case['measurement']; bracket = case['memory_brackets']['postloop']; peak = bracket['parent']['memory']['peak_resident_bytes']
    check(case['id'] + '_native_sample_count_gap_and_resource_recomputed', len(selected) == m['native_samples_in_loop'] >= 20 and max(y - x for x, y in zip(stamps, stamps[1:])) == m['maximum_sample_gap_seconds'] <= .5 and max(r['sample']['memory']['private_bytes'] for r in selected) == m['sampled_current_private_max_bytes'] and max(r['sample']['memory']['resident_bytes'] for r in selected) == m['sampled_current_resident_max_bytes'] and math.fsum(r['query_completed_perf_counter'] - r['query_started_perf_counter'] for r in selected) == m['parent_query_wall_seconds'])
    check(case['id'] + '_actual_process_lifetime_peak_bracket_before_validation', bracket['self_before']['memory']['peak_resident_bytes'] <= peak <= bracket['self_after']['memory']['peak_resident_bytes'] and peak == m['actual_process_peak_resident_through_postloop_bytes'] and b <= bracket['self_before']['perf_counter'] <= valid['started_perf_counter'])
    check(case['id'] + '_healthy_exit_codes_exactly5zero', len(cleanup['exit_codes']) == 5 and all(r['exit_code'] == 0 for r in cleanup['exit_codes']))
    case_rows.append({'id': case['id'], 'job': case['job'], 'imports_seconds': imports, 'steps': loop['steps_completed'], 'targets': loop['training_target_positions'], 'loop_seconds': loop['training_loop_wall_seconds'], 'complete_case_wall_seconds': case['wall_seconds'], 'peak_scope': 'Actual interpreter OS lifetime working-set high-water through postloop', 'memory': m, 'latencies': loop['step_summary'], 'initial_parameter_sha256': info['initial_parameter_sha256'], 'checkpoint_sha256': valid['checkpoint_sha256']})

independent_pairs = []
paired_supplement = None
full_training_and_saved_evaluation = len(report['cases']) == 12 and all(c['passed'] for c in report['cases']) and (COPY / 'evaluation.json').is_file()
if full_training_and_saved_evaluation:
    evaluation, release = read(COPY / 'evaluation.json'), read(COPY / 'evaluation-release.json')
    study.validate_release(release, COPY)
    paired_supplement = study.paired_results(report['cases'], evaluation)
    check('12complete_cases12sealed_endpoints', len(report['cases']) == len(release['endpoints']) == len(evaluation['endpoints']) == 12 and all(c['passed'] for c in report['cases']))
    check('all12training_initial_parameter_hashes_match', len({c['stages']['pretrain']['model']['initial_parameter_sha256'] for c in report['cases']}) == 1)
    check('evaluation_after_all_training_sealed', datetime.fromisoformat(release['training_sealed_at']) <= datetime.fromisoformat(evaluation['started_at']) and evaluation['release_sha256'] == sha(COPY / 'evaluation-release.json'))
    check('initial_plus12evaluation64blocks4096targets', all(len(e['block_mean_nll']) == 64 and e['scored_target_positions'] == 4096 for e in [evaluation['initial']] + [row['evaluation'] for row in evaluation['endpoints']]))
    check('all12evaluation_release_checkpoint_and_parameter_identities_exact', [e['job'] for e in evaluation['endpoints']] == protocol['jobs'] and all(e['job'] == rel['job'] == c['job'] and e['checkpoint_sha256'] == rel['checkpoint_sha256'] == c['stages']['postvalidation']['validation']['checkpoint_sha256'] and e['initial_parameter_sha256'] == rel['initial_parameter_sha256'] == c['stages']['pretrain']['model']['initial_parameter_sha256'] == evaluation['initial_parameter_sha256'] and e['final_parameter_sha256'] == rel['final_parameter_sha256'] == c['stages']['postvalidation']['validation']['final_parameter_sha256'] for e, rel, c in zip(evaluation['endpoints'], release['endpoints'], report['cases'])))
    check('13evaluation_score_means_recomputed', all(math.isclose(e['mean_nll'], sum(e['block_mean_nll']) / 64, rel_tol=0, abs_tol=1e-12) and all(math.isfinite(x) for x in e['block_mean_nll']) for e in [evaluation['initial']] + [row['evaluation'] for row in evaluation['endpoints']]))
    check('evaluator_provider_guard_saved_valid_one_local_probe', study.prior.validate_provider(evaluation['provider_guard'], 'load', 1))
    imports = [read(COPY / ('import-progress-' + str(i).zfill(2) + '.json')) for i in range(7)]
    check('evaluator_seven_saved_import_markers_exact_identity', [r['step'] for r in imports] == list(study.progress.STEPS) and all(r['nonce'] == report['evaluator']['nonce'] and r['pid'] == evaluation['pid'] for r in imports))
    for arm in ['token', 'time']:
        for seed in [503, 701, 907]:
            dense, bank = [next(c for c in report['cases'] if c['job']['arm'] == arm and c['job']['seed'] == seed and c['job']['method'] == method) for method in ['dense', 'model_except_norm_attention_saved_int8']]
            dn, bn = [next(e['evaluation']['mean_nll'] for e in evaluation['endpoints'] if e['job'] == c['job']) for c in [dense, bank]]
            cond = {'bank_nll_no_worse_than_dense': bn <= dn, 'bank_nll_below_initial': bn < evaluation['initial']['mean_nll']}
            if arm == 'token':
                cond.update(bank_observed_complete_case_faster=bank['wall_seconds'] < dense['wall_seconds'], bank_process_lifetime_working_set_peak_lower=bank['measurement']['actual_process_peak_resident_through_postloop_bytes'] < dense['measurement']['actual_process_peak_resident_through_postloop_bytes'])
            else:
                cond.update(bank_more_targets=bank['loop_after']['loop']['training_target_positions'] > dense['loop_after']['loop']['training_target_positions'])
            expected = next(r for r in paired_supplement['comparisons'] if r['arm'] == arm and r['seed'] == seed)
            check(arm + '_' + str(seed) + '_independent_joint_screen_conditions', cond == expected['conditions'] and all(cond.values()) == expected['joint_screen_passed'])
            independent_pairs.append({'arm': arm, 'seed': seed, 'dense_nll': dn, 'bank_nll': bn, 'conditions': cond, 'joint_screen_passed': all(cond.values())})
    check('all_six_joint_screens_boolean_independently_recomputed', all(p['joint_screen_passed'] for p in independent_pairs) == paired_supplement['all_six_joint_screens_passed'])
    evaluator = report['evaluator']; cleanup = evaluator['cleanup']; retained_exit_codes.extend(cleanup['exit_codes'])
    check('evaluator_retained_empty_job_exactly2zeroexits', cleanup['job_active_count'] == 0 and cleanup['all_retained_handles_exited'] and len(cleanup['exit_codes']) == 2 and all(x['exit_code'] == 0 for x in cleanup['exit_codes']))
    check('evaluator_actual_interpreter_identity_and_saved_pid', evaluator['identity']['self_receipt']['pid'] == evaluation['pid'] == evaluator['identity']['os_image']['pid'] and evaluator['identity']['os_image']['sha256'] == freeze['executables_sha256']['base_python'])
    ancestry = {(r['pid'], r['creation_filetime']) for r in evaluator['identity']['verified_ancestry']}
    check('evaluator_cleanup_exact_2authenticated_ancestry_identities', {(r['pid'], r['creation_filetime']) for r in cleanup['exit_codes']} == ancestry and evaluator['failure_cleanup']['exit_codes'] == cleanup['exit_codes'] and evaluator['failure_cleanup']['all_retained_handles_exited'] and evaluator['failure_cleanup']['job_active_count'] == 0)
    try:
        study.prior.verify_cleanup(copy.deepcopy(evaluator), 'healthy')
        saved_validator_error = None
    except KeyError as error:
        saved_validator_error = "KeyError: " + str(error)
    check('original_cleanup_validator_rejects_saved_evaluator_missing_censuses', saved_validator_error == evaluator.get('error') == "KeyError: 'censuses'" and 'censuses' not in evaluator and evaluator['passed'] is False)
    check('frozen_failure_and_no_report_comparisons_preserved', report['passed'] is False and 'comparisons' not in report)
else:
    check('incomplete_execution_has_no_claimed_screens', 'comparisons' not in report)
check('original_output_unchanged_through_review', inventory(ORIGINAL) == original_before)
check('independent_saved_copy_unchanged_through_review', inventory(COPY) == original_before)
check('reviewer_no_ML_imports', not {'torch', 'transformers', 'numpy'} & set(sys.modules))
failed = [c for c in checks if not c['passed']]
result = {'started_at': started, 'completed_at': now(), 'status': 'passed_saved_negative_outcome_with_post_outcome_supplement' if not failed else 'blocked', 'checks_total': len(checks), 'checks_passed': len(checks) - len(failed), 'findings': failed, 'checks': checks, 'canonical_saved_auditor': canonical, 'execution_accepted': report['passed'], 'scientific_joint_screens_computed': False, 'post_outcome_supplement_computed': bool(independent_pairs), 'joint_screens_passed_count': sum(p['joint_screen_passed'] for p in independent_pairs), 'joint_screens_failed_count': sum(not p['joint_screen_passed'] for p in independent_pairs), 'all_six_joint_screens_passed': all(p['joint_screen_passed'] for p in independent_pairs) if independent_pairs else None, 'post_outcome_paired_supplement': paired_supplement, 'independent_comparisons': independent_pairs, 'case_summaries': case_rows, 'completed_training_updates': sum(r['steps'] for r in case_rows), 'actual_initial_model_loads_observed': len(case_rows) + (1 if full_training_and_saved_evaluation else 0), 'completed_training_loops': len(case_rows), 'saved_evaluation_endpoint_records': 12 if full_training_and_saved_evaluation else 0, 'retained_exit_codes_count': len(retained_exit_codes), 'empty_jobs': len(case_rows) + (1 if full_training_and_saved_evaluation else 0), 'raw_files': len(original_before), 'raw_bytes': sum(r['bytes'] for r in original_before.values()), 'raw_manifest': original_before, 'copy': COPY.relative_to(ROOT).as_posix(), 'outer_CLI_wall_seconds': complete['outer_CLI_wall_seconds'], 'runner_suite_seconds': report['wall_seconds'], 'scientific_suites_in_original': 1, 'reviewer_native_jobs': 0, 'reviewer_ML_imports': 0, 'reviewer_model_loads': 0, 'reviewer_scientific_suites': 0, 'reviewer_holdout_data_reads': 0, 'limits': ['Original frozen acceptance remains FAILED: evaluator cleanup controller raises KeyError censuses after evaluation bytes exist. Saved-data pair calculations are explicitly a post-outcome supplement and do not rescue frozen acceptance.', 'Local single-machine CPU/fixed order, three seeds only; no GPU/distributed/production inference.', 'Existing saved-activation INT8 treatment excluding norm/attention; not learned residual-bank architecture.', 'Reused public LookingGlass blocks give procedural sealing, not fresh generalization.', 'Actual interpreter OS lifetime working-set high-water includes imports/load/holds; sampled private/resident maxima are lower bounds, not GPU/isolated activation peaks.', 'Query cost measured with observation enabled in both arms; no causal total observer overhead or performance claim.', 'Historical failures and invalid parent RSS remain unchanged; receipt validation is distinct from scientific joint-screen outcome.']}
path = HERE / 'h1-independent-outcome-review.json'
with path.open('x', encoding='utf-8', newline='\n') as h:
    json.dump(result, h, ensure_ascii=False, indent=2); h.write('\n')
print(json.dumps({'status': result['status'], 'checks': result['checks_total'], 'passed': result['checks_passed'], 'findings': failed, 'execution_accepted': result['execution_accepted'], 'joint_screens_passed_count': result['joint_screens_passed_count'], 'joint_screens_failed_count': result['joint_screens_failed_count'], 'raw_files': result['raw_files'], 'raw_bytes': result['raw_bytes'], 'receipt': path.relative_to(ROOT).as_posix(), 'sha256': sha(path)}))
