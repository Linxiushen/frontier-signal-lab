"""Compose immutable saved-outcome reviews; no ML/native/model execution."""
from pathlib import Path
from datetime import datetime, timezone
import copy
import hashlib
import json

ROOT = Path.cwd()
HERE = Path(__file__).resolve().parent
RAW = ROOT / 'reports/runs/20261102T065705Z/native-training-cost-scopes-v4'
FIX = ROOT / 'fixtures/native-training-cost-scopes-v4-reviewed'
read = lambda p: json.loads(p.read_bytes())
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
main_path = HERE / 'h1-independent-outcome-review.json'
supp_path = HERE / 'h1-independent-evaluator-supplement-v2.json'
main, supp = read(main_path), read(supp_path)
assert main['checks_total'] == main['checks_passed'] == 164
assert supp['checks_total'] == supp['checks_passed'] == 12
assert main['execution_accepted'] is supp['execution_accepted'] is False
assert supp['main_review_sha256'] == sha(main_path)
raw_report = read(RAW / 'report.json')
evaluation = read(RAW / 'evaluation.json')
assert raw_report['passed'] is False and 'comparisons' not in raw_report
assert raw_report['evaluator']['error'] == "KeyError: 'censuses'"
evidence = {p.relative_to(ROOT).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in [RAW / 'report.json', RAW / 'evaluation.json', RAW / 'evaluation-release.json', FIX / 'protocol.json', FIX / 'implementation.json']}
table = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'kind': 'post_outcome_saved_data_supplement', 'original_frozen_acceptance': False, 'original_error': raw_report['evaluator']['error'], 'original_report_comparisons_absent': True, 'evidence': evidence, 'initial_nll': evaluation['initial']['mean_nll'], 'initial_and_endpoint_score_scope': 'Original reused LookingGlass64blocks/4096targets. Procedural seal only; no new holdout or model execution in this calculation.', 'paired_results': main['post_outcome_paired_supplement'], 'joint_screens_passed_count': main['joint_screens_passed_count'], 'joint_screens_failed_count': main['joint_screens_failed_count'], 'all12endpoint_nll_above_initial': all(e['evaluation']['mean_nll'] > evaluation['initial']['mean_nll'] for e in evaluation['endpoints']), 'model_native_scientific_executions_in_supplement': 0, 'cannot_rescue_original_acceptance': True}
table_path = HERE / 'h1-post-outcome-paired-supplement.json'
with table_path.open('x', encoding='utf-8', newline='\n') as h:
    json.dump(table, h, ensure_ascii=False, indent=2); h.write('\n')
result = copy.deepcopy(main)
result['completed_at'] = datetime.now(timezone.utc).isoformat()
result['status'] = 'passed_saved_negative_outcome_with_post_outcome_supplement'
result['checks'] += supp['checks']
result['checks_total'] = result['checks_passed'] = 176
result['composition'] = {'main_review': main_path.relative_to(ROOT).as_posix(), 'main_sha256': sha(main_path), 'evaluator_supplement': supp_path.relative_to(ROOT).as_posix(), 'supplement_sha256': sha(supp_path), 'initial_reviewer_prefix_guard_diagnostic': (HERE / 'h1-independent-evaluator-supplement.json').relative_to(ROOT).as_posix(), 'initial_diagnostic_sha256': sha(HERE / 'h1-independent-evaluator-supplement.json'), 'diagnostic_correction': supp['previous_diagnostic_reason'], 'all_original_receipts_unchanged': True}
result['evidence_hashes'] = evidence
result['post_outcome_table_path'] = table_path.relative_to(ROOT).as_posix()
result['post_outcome_table_sha256'] = sha(table_path)
result['evaluator_ready_full_original_prefix_provider_checks_supplemental'] = True
result['scope'] = 'Independent full byte-identical saved-copy, native training receipts and supplementary saved evaluator metadata review. Original frozen acceptance stays FAILED on censuses KeyError. Twelve completed loops and sealed evaluations permit clearly post-outcome saved-data comparisons only; all six fail, all12endpointNLL worse than initial. No model/native/science rerun or holdout data read.'
out = HERE / 'h1-independent-outcome-accepted-review.json'
with out.open('x', encoding='utf-8', newline='\n') as h:
    json.dump(result, h, ensure_ascii=False, indent=2); h.write('\n')
print(json.dumps({'status': result['status'], 'checks': 176, 'passed': 176, 'receipt': out.relative_to(ROOT).as_posix(), 'sha256': sha(out), 'table': table_path.relative_to(ROOT).as_posix(), 'table_sha256': sha(table_path)}))
