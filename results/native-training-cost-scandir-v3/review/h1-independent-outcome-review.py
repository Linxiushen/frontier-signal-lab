"""Review saved negative outcome on a byte-identical copy; stdlib only."""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

ROOT = Path.cwd()
RUN = ROOT / 'reports/runs/20261102T045820Z'
ORIGINAL = RUN / 'native-training-cost-scandir-v3'
COPY = RUN / 'h1-independent-saved-copy'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_bytes())
now = lambda: dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z')
started = now()
def inventory(root):
    paths = sorted(p for p in root.rglob('*') if p.is_file())
    assert not any(p.is_symlink() for p in root.rglob('*'))
    return {p.relative_to(root).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in paths}

original_before = inventory(ORIGINAL)
assert not COPY.exists()
shutil.copytree(ORIGINAL, COPY, copy_function=shutil.copy2)
checks = []
def check(name, condition, evidence=None):
    checks.append({'name': name, 'passed': bool(condition), 'evidence': evidence})

check('complete_copy_equal_before_review', inventory(COPY) == original_before)
protocol_path = ROOT / 'fixtures/native-training-cost-scandir-v3/protocol.json'
freeze_path = ROOT / 'fixtures/native-training-cost-scandir-v3/implementation.json'
protocol, freeze = read(protocol_path), read(freeze_path)
report = read(COPY / 'report.json')
reserved, complete = (read(RUN / name) for name in ('h1-suite-reserved.json', 'h1-suite-completed.json'))
check('frozen_protocol_and_sources_unchanged', sha(protocol_path) == freeze['protocol_sha256'] == report['protocol_sha256'] and all(sha(ROOT / p) == h for p, h in freeze['source_sha256'].items()))
check('frozen_corrected_entrypoint_unchanged', all(sha(ROOT / p) == h for p, h in freeze['additional_source_sha256'].items()))
check('freeze_chain_exact', sha(freeze_path) == report['freeze_sha256'] == reserved['freeze_sha256'] == complete['freeze_sha256'])
check('one_slot_one_original_cli_zero_retries', complete['scientific_slots_reserved'] == reserved['scientific_slots_reserved'] == report['scientific_suites'] == 1 and complete['original_CLI_invocations'] == reserved['original_CLI_invocations'] == 1 and complete['retries'] == reserved['retries'] == report['retries'] == 0)
check('wrapper_failed_without_outer_timeout', complete['exit_code'] == 1 and complete['outer_timeout'] is False)
check('wrapper_stdout_stderr_hashes', sha(RUN / 'h1-execution.stdout.log') == complete['stdout_sha256'] and sha(RUN / 'h1-execution.stderr.log') == complete['stderr_sha256'])
check('exact_original_job_prefix_stops_after_first_failed_case', [c['job'] for c in report['cases']] == protocol['jobs'][:2] and [c['passed'] for c in report['cases']] == [True, False] and report['passed'] is False)
check('no_evaluation_release_quality_or_paired_comparison', all(not (COPY / p).exists() for p in ('evaluation-release.json', 'evaluation.json')) and 'evaluator' not in report and 'comparisons' not in report)
check('no_other_job_directories', sorted(p.name for p in COPY.iterdir() if p.is_dir()) == sorted(c['id'] for c in report['cases']))
case_summaries = []
for case in report['cases']:
    folder = COPY / case['id']
    check(case['id'] + '_case_and_job_exact', read(COPY / (case['id'] + '-case.json')) == case and read(folder / 'job.json') == case['job'])
    check(case['id'] + '_no_pending_partial_atomic_files', not list(folder.glob('*.pending')))
    identity = case['worker_identity']['self_receipt']
    os_image = case['worker_identity']['os_image']
    check(case['id'] + '_retained_actual_image_identity', (os_image['pid'], os_image['creation_filetime']) == (identity['pid'], identity['creation_filetime']) and os_image['sha256'] == freeze['executables_sha256']['base_python'] and os_image['queried_from_retained_handle'] and os_image['matches_frozen_path_and_hash'] and case['launcher']['pid'] != identity['pid'])
    check(case['id'] + '_stages_raw_receipts_exact', all(read(folder / (label + '-ready.json')) == value for label, value in case['stages'].items()))
    check(case['id'] + '_memory_brackets_raw_self_receipts_exact', all(read(folder / (label + '-' + suffix + '.json')) == case['memory_brackets'][label][key] for label in case['memory_brackets'] for key, suffix in [('self_before', 'before'), ('self_after', 'after')]))
    check(case['id'] + '_import_receipts_exact_and_complete', [read(folder / ('import-progress-' + str(i).zfill(2) + '.json')) for i in range(7)] == case['import_progress'] and [r['seq'] for r in case['import_progress']] == list(range(7)) and case['import_progress'][-1]['step'] == 'versions-verified')
    imported = case['stages']['postimport']
    import_seconds = imported['import_completed_perf_counter'] - imported['import_started_perf_counter']
    check(case['id'] + '_observed_import_within_original20s', 0 < import_seconds < protocol['budgets']['import_seconds'], import_seconds)
    check(case['id'] + '_no_preimport_torch_or_transformers', case['stages']['preimport']['torch_imported'] is False and case['stages']['preimport']['transformers_imported'] is False)
    cleanup = case.get('cleanup', case.get('failure_cleanup'))
    check(case['id'] + '_retained_cleanup_all_exited_zero_job_count', cleanup['all_retained_handles_exited'] is True and cleanup['job_active_count'] == 0 and len(cleanup['exit_codes']) == 5)
    raw = (folder / 'trace.jsonl').read_bytes()
    ledger = [json.loads(line) for line in raw.splitlines()]
    check(case['id'] + '_ledger_exact_saved_records_bytes_sequence', ledger == case['ledger']['records'] and len(raw) == case['ledger']['committed_bytes'] and len(ledger) == case['ledger']['committed_rows'] and [row['seq'] for row in ledger] == list(range(len(ledger))))
    check(case['id'] + '_bounded_nonpoisoned_ledger', len(raw) <= protocol['ledger_limits']['max_total_bytes'] and len(ledger) <= protocol['ledger_limits']['max_rows'] and case['ledger']['failure'] is None and case['ledger']['poisoned'] is False)
    check(case['id'] + '_every_ledger_sample_actual_identity_and_clock', all((row['pid'], row['creation_filetime']) == (identity['pid'], identity['creation_filetime']) and row['query_started_perf_counter'] <= row['member_verified_perf_counter'] <= row['reading']['perf_counter'] <= row['query_completed_perf_counter'] <= row['emitted_perf_counter'] for row in ledger if row['kind'] == 'sample'))
    info = case['stages']['pretrain']['model']
    case_summaries.append({'id': case['id'], 'passed': case['passed'], 'observed_import_seconds': import_seconds,
                           'complete_case_wall_seconds': case['wall_seconds'], 'initial_parameter_sha256': info['initial_parameter_sha256'],
                           'job_active_count_after_cleanup': cleanup['job_active_count'], 'ledger_rows': len(ledger),
                           'ledger_bytes': len(raw)})
    if case['passed']:
        loop = case['loop_after']['loop']
        valid = case['stages']['postvalidation']['validation']
        check('dense_raw_loop_receipts_exact', read(folder / 'before-loop.json') == case['loop_before'] and read(folder / 'after-loop.json') == case['loop_after'])
        check('dense64steps8192targets_original_optimizer_finite', loop['steps_completed'] == protocol['config']['token_steps'] == 64 and loop['training_target_positions'] == 8192 and valid['final_validity']['optimizer_counters'] == [64] * 76 and valid['final_validity']['final_parameter_gradient_moments_finite'] is True and info['optimizer'] == protocol['config']['optimizer'])
        check('dense_checkpoint_byte_hash_and_no_training_holdout', (folder / 'endpoint.pt').stat().st_size == valid['checkpoint_bytes'] and sha(folder / 'endpoint.pt') == valid['checkpoint_sha256'] and valid['no_holdout_evaluation'] is True and info['holdout_opened'] is False)
        check('dense_changed_parameter_hash_and_normal_process_exit', valid['final_parameter_sha256'] != info['initial_parameter_sha256'] and case['healthy_completion']['optimizer_steps'] == 64 and all(row['exit_code'] == 0 for row in cleanup['exit_codes']))
        expected = case['samples'][:3] + [x['sample'] for x in case['active_window']['observations']] + case['samples'][3:]
        check('dense_ledger_exact_observer_samples_and_healthy_close', ledger[0]['kind'] == 'bound' and ledger[-1]['kind'] == 'closed' and ledger[-1]['cleanup'] == cleanup and [row['reading'] for row in ledger[1:-1]] == expected)
        a, b = loop['loop_perf_counter_start'], loop['loop_perf_counter_end']
        selected = [r for r in case['active_window']['observations'] if a <= r['query_started_perf_counter'] <= r['sample']['perf_counter'] <= r['query_completed_perf_counter'] <= b]
        stamps = [a] + [r['sample']['perf_counter'] for r in selected] + [b]
        max_gap = max(y - x for x, y in zip(stamps, stamps[1:]))
        m = case['measurement']
        check('dense_sample_count_and_gap_retained_thresholds', len(selected) == m['native_samples_in_loop'] >= protocol['budgets']['min_in_loop_samples'] and max_gap == m['maximum_sample_gap_seconds'] <= protocol['budgets']['max_sample_gap_seconds'])
        mem = case['memory_brackets']['postloop']
        peak = mem['parent']['memory']['peak_resident_bytes']
        check('dense_retained_postloop_peak_bracket_precedes_validation', mem['self_before']['memory']['peak_resident_bytes'] <= peak <= mem['self_after']['memory']['peak_resident_bytes'] and peak == m['actual_process_peak_resident_through_postloop_bytes'] and b <= mem['self_before']['perf_counter'] <= valid['started_perf_counter'])
        check('dense_sampled_resource_and_query_metrics_exact', max(r['sample']['memory']['private_bytes'] for r in selected) == m['sampled_current_private_max_bytes'] and max(r['sample']['memory']['resident_bytes'] for r in selected) == m['sampled_current_resident_max_bytes'] and math.fsum(r['query_completed_perf_counter'] - r['query_started_perf_counter'] for r in selected) == m['parent_query_wall_seconds'])
        timings = loop['step_timings']
        walls = sorted(t['wall_seconds'] for t in timings)
        check('dense_latency64steps_quantiles_exact', [t['index'] for t in timings] == list(range(64)) and all(loop['step_summary'][label] == walls[math.ceil(64 * q) - 1] for label, q in [('p50_step_seconds', .5), ('p95_step_seconds', .95), ('p99_step_seconds', .99)]))
        case_summaries[-1].update(steps_completed=64, training_target_positions=8192, training_loop_seconds=loop['training_loop_wall_seconds'],
                                  memory=m, step_summary=loop['step_summary'], checkpoint_sha256=valid['checkpoint_sha256'])
    else:
        failure = read(folder / 'worker-failure.json')
        check('bank_raw_worker_failure_and_phase_exact', failure == case['worker_failure_receipt'] and failure['phase'] == 'train' and failure['error'] == 'ValueError: too many values to unpack (expected 2)' and failure['pid'] == identity['pid'])
        check('bank_no_completed_loop_endpoint_or_normal_completion', all(not (folder / name).exists() for name in ('after-loop.json', 'postloop-ready.json', 'postvalidation-ready.json', 'endpoint.pt', 'worker-completed.json')) and 'loop_after' not in case and 'measurement' not in case and 'healthy_completion' not in case)
        check('bank_failed_prefix_not_healthy_closed', ledger[0]['kind'] == 'bound' and ledger[-1]['kind'] == 'sample' and len(ledger) == 5 and list(case['stages']) == ['preimport', 'postimport', 'pretrain'])
        case_summaries[-1].update(worker_failure_error=failure['error'], observed_completed_bank_updates=None,
                                  limitation='No completed bank loop/checkpoint; actual update count is not independently measured by a completed loop receipt.')

check('identical_initial_dense_bank_parameter_hash', case_summaries[0]['initial_parameter_sha256'] == case_summaries[1]['initial_parameter_sha256'])
check('original_output_unchanged_through_independent_review', inventory(ORIGINAL) == original_before)
check('independent_copy_unchanged_through_review', inventory(COPY) == original_before)
check('no_ml_imports_in_reviewer', not any(x in sys.modules for x in ('torch', 'transformers', 'numpy')))
failed = [c for c in checks if not c['passed']]
result = {'started_at': started, 'completed_at': now(), 'status': 'passed_saved_negative_outcome' if not failed else 'blocked',
          'checks_total': len(checks), 'checks_passed': len(checks) - len(failed), 'findings': failed, 'checks': checks,
          'execution_accepted': False, 'scientific_joint_screens_computed': False,
          'actual_original_scientific_suites': 1, 'reviewer_scientific_suites': 0, 'reviewer_native_jobs': 0,
          'reviewer_ml_imports': 0, 'reviewer_model_loads': 0, 'reviewer_holdout_opens': 0,
          'outer_cli_seconds': complete['outer_CLI_wall_seconds'], 'runner_suite_seconds': report['wall_seconds'],
          'cases': case_summaries, 'saved_files': len(original_before), 'saved_bytes': sum(x['bytes'] for x in original_before.values()),
          'original_saved_manifest': original_before, 'copy': str(COPY.relative_to(ROOT)),
          'scope': 'Independent stdlib-only inspection of original saved bytes and a complete byte-identical copy. Original acceptance unchanged: first dense case passed, second bank case failed, remaining10 not launched and no evaluator. No matched cost/quality success or failure screen can be computed.',
          'static_failure_explanation': 'Frozen caller passes the (norms, attentions) pair of lists directly to preserve_scopes, which expects a flat iterable of(name,module)pairs; 13-item first list is consistent with the saved unpack error. No traceback was retained; this is a source-supported explanation, not a new dynamic localization.',
          'limits': ['Current authenticated base Python/DLL/stdlib is an additional environment change; no scandir-only startup attribution.',
                     'Dense peak is retained actual-interpreter OS lifetime working-set high-water through postloop, not private/GPU/isolated activation peak.',
                     'Current private/resident maxima are sampled lower bounds; no causal observer-overhead estimate.',
                     'No complete bank pair, all seeds, time arm or holdout evaluation. No new model quality, GPU, distributed, production or learned residual-bank result.']}
path = RUN / 'h1-independent-outcome-review.json'
path.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
print(json.dumps({'status': result['status'], 'checks_total': len(checks), 'checks_passed': result['checks_passed'], 'findings': failed,
                  'saved_files': result['saved_files'], 'saved_bytes': result['saved_bytes'], 'receipt': str(path.relative_to(ROOT)), 'sha256': sha(path)}, indent=2))
