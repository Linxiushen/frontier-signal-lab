"""Verify otherwise unreached evaluator saved-metadata checks only."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sys

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
RUN = ROOT / 'reports/runs/20261102T065705Z'
ORIGINAL = RUN / 'native-training-cost-scopes-v4'
COPY = HERE / 'h1-independent-saved-copy'
read = lambda p: json.loads(p.read_bytes())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
sys.path.insert(0, str(ROOT))
from experiments import native_training_cost as study

review = read(HERE / 'h1-independent-outcome-review.json')
report = read(COPY / 'report.json')
evaluator = report['evaluator']
evaluation = read(COPY / 'evaluation.json')
ready = read(COPY / 'evaluator-ready.json')
checks = []
def ck(name, passed, evidence=None):
    checks.append({'name': name, 'passed': bool(passed), 'evidence': evidence})
ck('prior164checks_passed_with_original_frozen_rejection', review['checks_total'] == review['checks_passed'] == 164 and review['execution_accepted'] is False)
ck('saved_evaluator_ready_exact_self_receipt', ready == evaluator['identity']['self_receipt'])
ck('ready_nonce_role_pid_creation_exact_authenticated_actual', ready['nonce'] == evaluator['nonce'] and ready['role'] == 'worker' and ready['pid'] == evaluator['identity']['os_image']['pid'] == evaluation['pid'] and ready['creation_filetime'] == evaluator['identity']['os_image']['creation_filetime'])
rows = study.progress.read_prefix(COPY, evaluator['nonce'], ready, ready['perf_counter'], evaluator['cleanup']['started_perf_counter'], complete=True)
ck('full_original_prefix_rules_accept7saved_records', len(rows) == 7 and [row['step'] for row in rows] == list(study.progress.STEPS))
ck('import_receipts_valid_guard_phase_and_monotone_probe_counts', all(study.prior.validate_provider(row['provider_guard'], 'import', 1) for row in rows) and [row['provider_guard']['allowed_local_probe_count'] for row in rows] == sorted(row['provider_guard']['allowed_local_probe_count'] for row in rows))
ck('final_saved_evaluation_provider_guard_valid', study.prior.validate_provider(evaluation['provider_guard'], 'load', 1))
ck('exact2authenticated_evaluator_retained_handles_exit0', len(evaluator['cleanup']['exit_codes']) == 2 and {(row['pid'], row['creation_filetime']) for row in evaluator['cleanup']['exit_codes']} == {(row['pid'], row['creation_filetime']) for row in evaluator['identity']['verified_ancestry']} and all(row['exit_code'] == 0 for row in evaluator['cleanup']['exit_codes']))
ck('both_cleanup_receipts_keep_same2identities_and_empty_job', evaluator['cleanup']['exit_codes'] == evaluator['failure_cleanup']['exit_codes'] and all(evaluator[k]['all_retained_handles_exited'] and evaluator[k]['job_active_count'] == 0 for k in ['cleanup', 'failure_cleanup']))
ck('all12observed_endpoint_NLL_above_initial', all(row['evaluation']['mean_nll'] > evaluation['initial']['mean_nll'] for row in evaluation['endpoints']), {'initial_nll': evaluation['initial']['mean_nll'], 'endpoint_nll': [{'job': row['job'], 'mean_nll': row['evaluation']['mean_nll']} for row in evaluation['endpoints']]})
selected = ['report.json', 'evaluation.json', 'evaluation-release.json', 'evaluator-ready.json'] + [f'import-progress-{i:02d}.json' for i in range(7)]
ck('all_reviewed_evaluator_original_copy_bytes_still_match_full_manifest', all(sha(ORIGINAL / p) == sha(COPY / p) == review['raw_manifest'][p]['sha256'] and (ORIGINAL / p).stat().st_size == (COPY / p).stat().st_size == review['raw_manifest'][p]['bytes'] for p in selected))
ck('original_rejection_no_retroactive_comparisons', report['passed'] is False and evaluator['passed'] is False and evaluator['error'] == "KeyError: 'censuses'" and 'comparisons' not in report)
ck('reviewer_no_ML_imports', not {'torch', 'transformers', 'numpy'} & set(sys.modules))
result = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'status': 'passed_saved_evaluator_supplement' if all(c['passed'] for c in checks) else 'blocked', 'checks_total': len(checks), 'checks_passed': sum(c['passed'] for c in checks), 'findings': [c for c in checks if not c['passed']], 'checks': checks, 'main_review': (HERE / 'h1-independent-outcome-review.json').relative_to(ROOT).as_posix(), 'main_review_sha256': sha(HERE / 'h1-independent-outcome-review.json'), 'execution_accepted': False, 'post_outcome_supplement_only': True, 'frozen_controller_did_not_reach_these_validations': True, 'scientific_suites_in_reviewer': 0, 'model_loads_in_reviewer': 0, 'native_jobs_in_reviewer': 0, 'holdout_data_reads': 0, 'scope': 'Actual original saved-data prefix validator and provider validation only, using seven exact evaluator import receipts and authenticated two-handle identity/cleanup. Does not add censuses, mutate records, run a model, rescue frozen acceptance, or label supplementary calculations as preregistered success.'}
path = HERE / 'h1-independent-evaluator-supplement.json'
with path.open('x', encoding='utf-8', newline='\n') as h:
    json.dump(result, h, ensure_ascii=False, indent=2); h.write('\n')
print(json.dumps({'status': result['status'], 'checks': result['checks_total'], 'passed': result['checks_passed'], 'findings': result['findings'], 'receipt': path.relative_to(ROOT).as_posix(), 'sha256': sha(path)}))
