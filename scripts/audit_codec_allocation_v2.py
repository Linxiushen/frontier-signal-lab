"""Audit saved codec receipts without importing Torch or starting workloads.

Receipt consistency and execution acceptance are separate results. A faithfully
recorded failed measurement can pass the receipt audit. This is not an
independent allocator implementation or a runtime reproduction.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.codec_allocation_events import reduce_events, boundary_summary
from experiments import training_observer_v3 as provider

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('saved JSON exceeds 64 MiB audit budget')
    return json.loads(path.read_bytes())


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def audit_v2_evidence(result_dir, case, protocol, freeze, check):
    """Recompute saved pre-release gates, including honestly rejected stages.

    The immutable provider validator is reused. Identity/file and diagnostic
    consistency are checked separately from admission: a correctly recorded
    rejected PID, budget or thread count does not become an accepted stage.
    """
    label, nonce = case['id'], case['nonce']
    directory = result_dir / label
    prefix = label + ':v2:'
    check(prefix+'case_schema', case['schema_version'] == 2)
    stages = protocol['stages']
    raw, accepted, diagnostics = (case['received_stage_receipts'], case['stages'], case['gate_diagnostics'])
    check(prefix+'raw_bounded_prefix', list(raw) == stages[:len(raw)] and len(raw) <= len(stages))
    check(prefix+'accepted_bounded_prefix', list(accepted) == stages[:len(accepted)] and len(accepted) <= len(raw))
    check(prefix+'diagnostic_coverage', set(diagnostics) == set(raw))
    identity = case.get('worker_identity')
    launcher = case.get('launcher')
    if identity is None:
        check(prefix+'no_unauthenticated_stage', not raw and not accepted and case['passed'] is False)
    else:
        ready = identity['self_receipt']
        pid = ready['pid']
        check(prefix+'identity_file', read(directory/'worker-ready.json') == ready)
        check(prefix+'identity_nonce_role', ready['nonce'] == nonce and ready['role'] == 'worker')
        ancestry = identity['verified_ancestry']
        keys = {(r['pid'], r['creation_filetime']) for r in ancestry}
        expected = {(pid, ready['creation_filetime']), (launcher['pid'], launcher['creation_filetime'])}
        check(prefix+'authenticated_ancestry', len(ancestry) == len(keys) == 2 and keys == expected
              and all(r['job_member'] is True for r in ancestry) and pid != launcher['pid'])
        check(prefix+'executable_custody', case['executables_sha256'] == freeze['executables_sha256']
              and case['executable_path_sha256'] == freeze['executable_path_sha256']
              and ready['self_executable']['sha256'] == freeze['executables_sha256']['launcher']
              and ready['self_executable']['normalized_path_sha256'] == freeze['executable_path_sha256']['launcher'])
        for owner, role in ((launcher, 'launcher'), (identity, 'base_python')):
            image = owner['os_image']
            check(prefix+'retained_image:'+role, image['sha256'] == freeze['executables_sha256'][role]
                  and image['queried_from_retained_handle'] is True
                  and image['matches_frozen_path_and_hash'] is True
                  and (image['pid'], image['creation_filetime']) in expected)
        for index, (stage, value) in enumerate(raw.items()):
            saved = diagnostics[stage]
            checked = saved['checked_perf_counter']
            stamp = value.get('stage_ready_perf_counter')
            previous = None if index == 0 else case['worker_controls'][index-1]['accepted_perf_counter']
            phase = {'preimport':'preimport', 'postimport':'postimport', 'postload':'postload',
                     'poststudy':'postupdate', 'complete':'complete'}[stage]
            predicates = {
                'pid_matches': value.get('pid') == pid,
                'stage_matches': value.get('stage') == stage,
                'stage_clock_finite': finite(stamp),
                'stage_clock_in_original_budget': finite(stamp) and case['started_perf_counter'] <= stamp <= checked
                    < min(case['case_deadline_perf_counter'], case['suite_deadline_perf_counter']),
                'stage_after_previous_acceptance': previous is None or (finite(stamp) and stamp >= previous),
                'native_threads_bounded': type(value.get('native_thread_count')) is int
                    and 1 <= value['native_thread_count'] <= protocol['config']['maximum_native_threads'],
                'provider_policy_budget_one': provider.validate_provider(value.get('provider_guard', {}), phase, expected_budget=1),
                'preimport_no_ML': stage != 'preimport' or
                    (value.get('torch_imported') is False and value.get('transformers_imported') is False),
            }
            check(prefix+'raw_file:'+stage, read(directory/(stage+'-ready.json')) == value)
            check(prefix+'raw_nonce_role:'+stage, value['nonce'] == nonce and value['role'] == 'worker')
            check(prefix+'diagnostic_clock:'+stage, finite(checked) and checked <= case['completed_perf_counter'])
            check(prefix+'diagnostics_recomputed:'+stage, saved == {
                'checked_perf_counter': checked, 'expected_provider_phase': phase,
                'expected_provider_budget': 1, 'predicates': predicates})
            admitted = all(predicates.values())
            check(prefix+'admission_consistent:'+stage,
                  (stage in accepted and accepted[stage] == value) if admitted else
                  (stage not in accepted and case['passed'] is False and index == len(raw)-1
                   and 'codec held identity/provider/thread gate failed: '+stage in case.get('error', '')))
            if stage == 'poststudy':
                check(prefix+'raw_poststudy_custody', sha(directory/'operation.json') == value.get('operation_sha256'))
            if stage == 'postload' and case['passed']:
                model = value['model']
                check(prefix+'pinned_model_preparation',
                      model.get('model_id') == 'EleutherAI/pythia-14m'
                      and model.get('model_revision') == 'cf967c0a9a04383db6f7b1108d86b2962634b4ac'
                      and model.get('train_sha256') == protocol['training']['train_sha256']
                      and model.get('batch_indices') == [116, 73] and model.get('batch_shape') == [2, 65]
                      and provider.is_hash(model.get('batch_sha256'))
                      and provider.is_hash(model.get('initial_parameter_sha256'))
                      and model.get('parameter_tensors') == 76 and model.get('parameter_elements') == 14067712
                      and model.get('optimizer_created') is False and model.get('holdout_opened') is False
                      and model.get('seed') == 503 and model.get('intraop_threads') == model.get('interop_threads') == 1
                      and model.get('deterministic_algorithms') is True)
        for index, ack in enumerate(case['worker_controls']):
            control = case['controller_controls'][index]
            check(prefix+'ack_identity_deadline:'+str(index), ack['role'] == 'worker' and ack['pid'] == pid
                  and ack['filename'] == control['filename'] and finite(ack['accepted_perf_counter'])
                  and ack['accepted_perf_counter'] < min(case['case_deadline_perf_counter'], case['suite_deadline_perf_counter']))
    if 'worker_failure' in case:
        check(prefix+'worker_failure_file', read(directory/'worker-failure.json') == case['worker_failure'])
        check(prefix+'worker_failure_means_rejection', case['passed'] is False)
    if case['passed']:
        done = case['completion']
        check(prefix+'completion_contract', done['nonce'] == nonce and done['role'] == 'worker'
              and done['pid'] == identity['self_receipt']['pid'] and done.get('spec') == case['spec']
              and done.get('model_loads') == done.get('forward_calls') == done.get('backward_calls') == 1
              and done.get('optimizer_updates') == 0
              and provider.validate_provider(done.get('provider_guard', {}), 'complete', expected_budget=1))
    cleanup = case.get('failure_cleanup', case.get('cleanup'))
    if cleanup is not None:
        retained = set()
        if launcher:
            retained.add((launcher['pid'], launcher['creation_filetime']))
        if identity:
            retained.update((r['pid'], r['creation_filetime']) for r in identity['verified_ancestry'])
        for census in case.get('censuses', []):
            retained.update((r['pid'], r['creation_filetime']) for r in census['processes'])
        exits = cleanup['exit_codes']
        check(prefix+'cleanup_exact_retained', bool(retained) and len(exits) == len(retained)
              and {(r['pid'],r['creation_filetime']) for r in exits} == retained)
        check(prefix+'cleanup_empty_and_exited', cleanup['all_retained_handles_exited'] is True
              and cleanup['job_active_count'] == 0 and all(type(r['exit_code']) is int and r['exit_code'] != 259 for r in exits))
        check(prefix+'cleanup_timing', case['started_perf_counter'] <= cleanup['started_perf_counter']
              <= cleanup['completed_perf_counter'] <= case['completed_perf_counter']
              and abs(cleanup['wall_seconds']-(cleanup['completed_perf_counter']-cleanup['started_perf_counter'])) < 1e-8
              and 0 <= cleanup['wall_seconds'] <= cleanup['timeout_seconds'] == protocol['config']['cleanup_timeout_seconds'])
    else:
        check(prefix+'cleanup_absent_only_before_job', not launcher and not identity and case['passed'] is False)


def _audit(result_dir, protocol_path, freeze_path):
    result_dir = Path(result_dir)
    protocol, freeze, report = read(protocol_path), read(freeze_path), read(result_dir/'report.json')
    checks = {}
    def check(name, value):
        checks[name] = bool(value)
    check('protocol_hash', sha(protocol_path)==freeze['protocol_sha256']==report['protocol_sha256'])
    check('freeze_hash', sha(freeze_path)==report['implementation_sha256'])
    check('suite_payload_hash', hashlib.sha256(canonical({k:v for k,v in report.items() if k!='result_sha256'})).hexdigest()==report['result_sha256'])
    check('id_and_schema', report['schema_version']==protocol['schema_version']==2 and report['experiment_id']==protocol['experiment_id'])
    check('one_attempt', report['suite_launches']==1 and report['retries']==0)
    check('freeze_before_execution', dt.datetime.fromisoformat(protocol['predeclared_at']) <= dt.datetime.fromisoformat(freeze['frozen_at']) <= dt.datetime.fromisoformat(report['started_at']) <= dt.datetime.fromisoformat(report['completed_at']))
    for field in ('new_source_files_sha256', 'frozen_dependency_files_sha256', 'review_tool_files_sha256'):
        for name, expected in freeze.get(field, {}).items():
            check('frozen_file:'+name, sha(ROOT/name)==expected)
    specs = protocol['cases_in_order']
    cases = report['cases']
    check('bounded_prefix_order', len(cases)<=len(specs) and [c['spec'] for c in cases]==specs[:len(cases)])
    check('no_case_after_failure', all(case['passed'] is True for case in cases[:-1]))
    operations = {'dense': [], 'int8': []}
    traces = []
    for case in cases:
        label = case['id']
        directory = result_dir/label
        if directory.resolve().parent != result_dir.resolve():
            raise ValueError('case directory escapes the saved result root')
        check(label+':separate_result', read(result_dir/(label+'-result.json'))==case)
        check(label+':case_id', label==case['spec']['id'])
        audit_v2_evidence(result_dir, case, protocol, freeze, check)
        for stage, receipt in case.get('stages', {}).items():
            check(label+':stage:'+stage, read(directory/(stage+'-ready.json'))==receipt and receipt['nonce']==case['nonce'] and receipt['pid']==case['worker_identity']['self_receipt']['pid'])
        for control in case.get('controller_controls', []):
            filename = control['filename']
            check(label+':control:'+filename, read(directory/filename)=={k:v for k,v in control.items() if k!='filename'})
        for ack in case.get('worker_controls', []):
            filename = ack['filename'].replace('.json','-accepted.json')
            check(label+':ack:'+filename, read(directory/filename)=={k:v for k,v in ack.items() if k!='parent_wait'} and ack['nonce']==case['nonce'])
        if case['passed']:
            controls, acks = case['controller_controls'], case['worker_controls']
            check(label+':control_counts', len(controls)==len(acks)==6 and set(case['stages'])==set(protocol['stages']))
            for index, ack in enumerate(acks):
                expected_control={k:v for k,v in controls[index].items() if k!='filename'}
                check(label+':ack_order:'+str(index), ack['control_envelope']==expected_control and ack['next_control_index']==index+1 and controls[index]['control_index']==index and controls[index]['emitted_perf_counter']<=ack['accepted_perf_counter']<=ack['parent_wait']['completed_perf_counter'] and ack['parent_wait']['started_perf_counter']<=ack['parent_wait']['completed_perf_counter'])
            live=case['prefinish_live_members']
            check(label+':end_ack_before_live_before_finish', len(live)==2 and {r['pid'] for r in live}=={case['launcher']['pid'],case['worker_identity']['self_receipt']['pid']} and all(r['alive'] is True and r['job_member'] is True and acks[4]['parent_wait']['completed_perf_counter']<=r['verified_perf_counter']<=controls[-1]['emitted_perf_counter'] for r in live))
            check(label+':completion_file', read(directory/'worker-completed.json')==case['completion'])
        cleanup = case.get('cleanup', case.get('failure_cleanup', {}))
        exits = cleanup.get('exit_codes', [])
        if case['passed']:
            identities={(r['pid'],r['creation_filetime']) for r in case['censuses'][-1]['processes']}
            check(label+':retained_cleanup', bool(exits) and cleanup.get('all_retained_handles_exited') is True and cleanup.get('job_active_count')==0 and all(row['exit_code']==0 for row in exits) and len(exits)==len(identities) and {(r['pid'],r['creation_filetime']) for r in exits}==identities and case.get('cleanup_exact_retained_identity_set') is True)
        operation = case.get('operation')
        if operation is None:
            check(label+':failure_recorded', case['passed'] is False and bool(case.get('error') or case.get('worker_failure')))
            continue
        check(label+':operation_file', read(directory/'operation.json')==operation)
        if 'poststudy' in case['stages']:
            check(label+':operation_custody', sha(directory/'operation.json')==case['stages']['poststudy']['operation_sha256'])
        check(label+':fixed_work', operation['spec']==case['spec'] and operation['forward_calls']==operation['backward_calls']==1 and operation['optimizer_updates']==0 and operation['holdout_opened'] is False and operation['checkpoint_written'] is False)
        if case['passed']:
            numbers=('loss','forward_loss_wall_seconds','backward_wall_seconds','forward_plus_backward_wall_seconds')
            check(label+':accepted_operation_values', operation['parameters_unchanged'] is True and operation['final_parameter_sha256']==case['stages']['postload']['model']['initial_parameter_sha256'] and operation['gradient']['finite'] is True and operation['gradient']['count']==76 and operation['exact_norm_scopes']==13 and operation['exact_attention_scopes']==6 and all(type(operation[n]) in (int,float) and math.isfinite(operation[n]) for n in numbers) and all(0<=operation[n]<=protocol['config']['study_timeout_seconds'] for n in numbers[1:]) and len(operation['gradient']['sha256'])==64)
            check(label+':accepted_observer_contract', operation['observer_enabled'] is case['spec']['observer_enabled'] and (operation['measurement_valid'] is True if case['spec']['observer_enabled'] else operation['measurement_valid'] is None))
        operations[case['spec']['method']].append(case)
        if case['spec']['observer_enabled']:
            trace_path=directory/'allocation-trace.json'
            trace=read(trace_path)
            check(label+':trace_custody', sha(trace_path)==operation['trace_sha256'])
            check(label+':trace_settings', trace['profile_memory'] is True and trace['record_shapes'] is False and trace['with_stack'] is False)
            reduced=reduce_events(trace['events'],trace['markers'],trace['references'])
            check(label+':reduction_replay', reduced==trace['reduced'])
            marker_map={m['id']:m for m in trace['markers']}
            for boundary in trace['boundaries']:
                owners=[{'storage_id':r['storage_id'],'expired':r['expired']} for r in boundary['rows']]
                computed=boundary_summary(reduced,marker_map[boundary['marker_id']],owners)
                check(label+':boundary:'+boundary['marker_id'], computed==boundary)
            check(label+':measurement_claim_consistent', trace['measurement_valid']==all(trace['measurement_gates'].values()) and trace['measurement_valid']==operation['measurement_valid'] and trace['measurement_gates']==operation['measurement_gates'])
            required=[b for b in reduced['bindings'] if b['required']]
            required_ids={b['storage_id'] for b in required}
            required_owners=[r for b in trace['boundaries'] for r in b['rows'] if r['storage_id'] in required_ids]
            callbacks=trace['callbacks']
            outer=operation['codec_counts']['outer']
            expected_gates={
                'raw_cpu_events_present':bool(trace['events']),
                'event_reduction_valid':reduced['valid'],
                'all_required_observations_uniquely_bound':bool(required) and all(r['status']=='bound' for r in required),
                'required_owner_agreement':bool(required_owners) and all(r['agreement'] is True for r in required_owners),
                'four_owner_boundaries':len(trace['boundaries'])==4,
                'callback_markers_complete':all(r['id'] in marker_map for r in callbacks),
                'all_callback_summaries_valid':len(reduced['callback_summaries'])==len(callbacks) and all(r['valid'] for r in reduced['callback_summaries']),
                'outer33save_calls':outer['pack']==33,
                'outer19eligible_saves':outer['eligible']==19,
                'outer19compressed_or_zero':outer['compressed']==(19 if case['spec']['method']=='int8' else 0),
            }
            check(label+':measurement_gates_recomputed', trace['measurement_gates']==expected_gates)
            if trace['measurement_valid']:
                expected_boundaries=['codec_boundary_'+name for name in protocol['boundaries']]
                callback_ids=[r['id'] for r in callbacks]
                marker_callbacks={m['id'] for m in trace['markers'] if m['kind'] in ('pack','unpack')}
                check(label+':accepted_measurement_has_coverage', reduced['valid'] and bool(required) and all(b['status']=='bound' for b in required) and [b['marker_id'] for b in trace['boundaries']]==expected_boundaries and len(callback_ids)==len(set(callback_ids)) and set(callback_ids)==marker_callbacks and all(r['agreement'] is True for r in required_owners))
            traces.append({'id':label,'events':len(trace['events']),'allocations':len(reduced['allocations']),'unknown_preexisting_frees':len(reduced['unknown_preexisting_frees']),'measurement_valid':trace['measurement_valid']})
        else:
            check(label+':observer_off_is_null', not (directory/'allocation-trace.json').exists() and all(operation.get(k) is None for k in ('trace_sha256','measurement_valid','measurement_gates','profiler_settings','callback_pack_wall_seconds','callback_unpack_wall_seconds')))
    math_controls={method:{'four_matched_operations':len(values)==4,'loss_identical':len({v['operation']['loss'] for v in values})==1,'gradient_bytes_identical':len({v['operation']['gradient']['sha256'] for v in values})==1,'initial_parameter_bytes_identical':len({v['stages']['postload']['model']['initial_parameter_sha256'] for v in values})==1,'batch_bytes_identical':len({v['stages']['postload']['model']['batch_sha256'] for v in values})==1} for method,values in operations.items() if values}
    check('math_controls_recomputed', report.get('math_controls')==math_controls if 'math_controls' in report else bool(report.get('error')))
    expected=len(cases)==8 and all(c['passed'] for c in cases) and set(math_controls)=={'dense','int8'} and all(all(v.values()) for v in math_controls.values())
    check('acceptance_claim_recomputed', report['passed']==expected)
    passed=all(checks.values())
    return {'schema_version':2,'audited_at':dt.datetime.now(dt.timezone.utc).isoformat(),'checks':checks,'passed':passed,'reported_execution_acceptance':report['passed'],'execution_acceptance':expected if passed else None,'completed_case_receipts':len(cases),'traces':traces,'suite_payload_sha256':report['result_sha256'],'limits':'Saved receipt consistency only. Reuses the pure reducer; gradient digests are producer-reported and equality is recomputed, gradient bytes are not independently rehashed. Raw received/accepted stage custody, recomputed named gate predicates, retained failure cleanup, selected controls and measurement gates are checked; this is not a second full Windows/provider-policy auditor or a signature. No Torch/model/process/database/network execution, independent allocator reproduction, OS peak or quality claim.'}


def audit(result_dir, protocol_path, freeze_path):
    reported = None
    try:
        reported = read(Path(result_dir)/'report.json').get('passed')
        return _audit(result_dir, protocol_path, freeze_path)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        return {'schema_version': 2, 'passed': False, 'execution_acceptance': None,
                'reported_execution_acceptance': reported, 'error': str(error)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result',type=Path,required=True)
    parser.add_argument('--protocol',type=Path,default=ROOT/'fixtures/codec-allocation-v2/protocol.json')
    parser.add_argument('--freeze',type=Path,default=ROOT/'fixtures/codec-allocation-v2/implementation.json')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    try:
        result=audit(args.result,args.protocol,args.freeze)
    except (OSError,ValueError,KeyError,TypeError,IndexError) as error:
        result={'passed':False,'error':str(error),'execution_acceptance':None}
    if args.output:
        with args.output.open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
