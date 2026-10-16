"""Post-hoc consistency audit of one pinned FAILED training acceptance report.

This is not preregistered acceptance. It preserves the frozen success auditor
and its rejection, checks the negative receipts, and performs no OS/ML work.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if not __package__: sys.path.insert(0,str(ROOT))
from scripts import audit_training_observer as success

REPORT_SHA256='29213227dbc96d700d73bef4a82eea272b28506d977f5f3d90a3c482c2d397ab'
PROTOCOL_SHA256='b3ac0d419eeb2965bc6a5472ae3e0e800eaf6c6c20b3c515c366daaf0d740715'
FREEZE_SHA256='c7a6d3be59947a45547043ecb70a2610f4d79b4b72282a5c2aeaa25dc3d7251a'
SUCCESS_AUDITOR_SHA256='0f0b5b0fc2e0de283262bbd46d20908981159a4f5d2edf237e9f6782c4415a22'
SUCCESS_TEST_SHA256='13ed205cfdc0466563536a707721d2a0ac7f7172f781f12867b6eff49132ade6'
EXPECTED_ERROR='ObserverError: stage process snapshot has missing or unexpected descendants'
EXPECTED_ACCEPTANCE_FAILURES=[
    'reported_acceptance_pass_not_laundered',
    'healthy_dense2:no_hidden_failure','healthy_dense2:exact_stage_inventory',"healthy_dense2:invalid_or_incomplete_receipt:'postimport'",
    'dense2_busy_deadline:no_hidden_failure','dense2_busy_deadline:exact_stage_inventory',"dense2_busy_deadline:invalid_or_incomplete_receipt:'postimport'",
    'dense2_private_cap64:no_hidden_failure','dense2_private_cap64:exact_stage_inventory',"dense2_private_cap64:invalid_or_incomplete_receipt:'postimport'",
    'injected_import_failure38:no_hidden_failure','injected_import_failure38:snapshot_descendants_exact',
    'injected_import_failure38:snapshot_retained_members',"injected_import_failure38:invalid_or_incomplete_receipt:'cleanup'"]


def sha(b): return hashlib.sha256(b).hexdigest()
def finite(v): return type(v) in (int,float) and math.isfinite(v)
def positive(v): return type(v) is int and v>0
def stamp(v):
    t=dt.datetime.fromisoformat(v.replace('Z','+00:00'))
    if t.tzinfo is None: raise ValueError('naive timestamp')
    return t


def audit(report,acceptance,protocol,freeze,*,report_sha256,protocol_sha256,freeze_sha256,
          success_auditor_sha256,actual_source_sha256,actual_dependency_sha256,success_test_sha256):
    """Field checks are separate from the exact historical report byte pin."""
    checks=[]; case_summaries=[]
    def check(value,label): checks.append({'check':label,'passed':bool(value)}); return bool(value)
    def close(a,b,label): check(finite(a) and finite(b) and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8),label)
    def identity(row,label):
        pair=row['pid'],row['creation_filetime']; check(all(positive(x) for x in pair),label+':positive_pid_creation'); return pair
    def message(row,nonce,pid,label):
        check(row.get('nonce')==nonce and row.get('role')=='worker' and type(row.get('pid')) is int and row['pid']==pid,label+':nonce_role_actual_pid')
    def interval(row,start,end,label):
        a,b=row['started_perf_counter'],row['completed_perf_counter']
        check(all(finite(x) for x in (a,b)) and start<=a<=b<=end,label+':contained_clock')
        close(row['wall_seconds'],b-a,label+':wall_recomputed'); return a,b
    def reading(row,pair,start,end,label,cpu=False):
        check(identity(row,label)==pair,label+':same_identity')
        check(finite(row['perf_counter']) and start<=row['perf_counter']<=end,label+':contained_clock')
        m=row['memory']; check(all(type(m[k]) is int and m[k]>=0 for k in ('resident_bytes','private_bytes','peak_resident_bytes'))
            and m['peak_resident_bytes']>=m['resident_bytes'] and m.get('backend')=='Windows GetProcessMemoryInfo',label+':memory_backend_and_values')
        if cpu: check(finite(row['native_cpu_seconds']) and row['native_cpu_seconds']>=0,label+':native_CPU')
    def cleanup(case,row,retained,start,end,anchor,exit_code,prefix):
        a,b=interval(row,start,end,prefix+'cleanup')
        check(anchor<=a and finite(row['timeout_seconds']) and 0<=b-a<=row['timeout_seconds']<=4,prefix+'cleanup_after_receipts_within_4s')
        check(row.get('all_retained_handles_exited') is True and type(row.get('job_active_count')) is int and row['job_active_count']==0,prefix+'all_exited_job_zero')
        exits=row['exit_codes']; pairs=[identity(x,prefix+'exit') for x in exits]
        check(len(pairs)==len(set(pairs)) and set(pairs)==set(retained),prefix+'every_retained_identity_has_exact_exit')
        check(all(type(x.get('exit_code')) is int and x['exit_code']==exit_code for x in exits),prefix+'exact_exit_codes')
        return exits
    def forbidden_training_fields(value):
        names={'operation','loop','optimizer_counters','model_loads','optimizer_steps','healthy_completion',
            'busy_ready','busy_first_operation','held_parent_overhead_windows','allocation_check','import_failure_receipt'}
        if isinstance(value,dict):
            return any(k in names or forbidden_training_fields(v) for k,v in value.items())
        if isinstance(value,list): return any(forbidden_training_fields(v) for v in value)
        return False

    cases=[]; suite_a=suite_b=None; suite_utc_a=suite_utc_b=None
    try:
        check(report_sha256==REPORT_SHA256,'exact_original_failed_report_bytes')
        check(protocol_sha256==PROTOCOL_SHA256==report.get('protocol_sha256')==freeze.get('protocol_sha256'),'exact_protocol_hash_chain')
        check(freeze_sha256==FREEZE_SHA256==report.get('implementation_sha256'),'exact_implementation_freeze_hash')
        check(success_auditor_sha256==SUCCESS_AUDITOR_SHA256 and success_test_sha256==SUCCESS_TEST_SHA256,'frozen_success_auditor_and_tests_unchanged')
        check(freeze.get('review_tools_sha256')=={'scripts/audit_training_observer.py':SUCCESS_AUDITOR_SHA256,
            'tests/test_training_observer_auditor.py':SUCCESS_TEST_SHA256},'implementation_pins_original_review_tools')
        check(actual_source_sha256==success.SOURCE_HASHES==freeze.get('new_source_files_sha256')==report.get('source_sha256'),'frozen_source_hash_chain')
        check(actual_dependency_sha256==success.DEPENDENCY_HASHES==freeze.get('frozen_dependency_files_sha256')==report.get('frozen_dependencies_sha256'),'frozen_dependency_hash_chain')
        check(report.get('schema_version')==1 and report.get('experiment_id')==protocol.get('experiment_id')==success.EXPERIMENT,'report_identity')
        check(report.get('passed') is False and not report.get('error') and report.get('no_fallback') is True
            and report.get('os_name')=='nt' and not report.get('final_wall_budget_exceeded'),'original_experiment_stays_failed')
        check(acceptance.get('passed') is False and acceptance.get('receipt_consistency_passed') is False
            and acceptance.get('failures')==EXPECTED_ACCEPTANCE_FAILURES and acceptance.get('check_count')==461
            and acceptance.get('checks_passed')==447,'frozen_success_auditor_preserves_exact_rejection')
        check(acceptance.get('report_file_sha256')==report_sha256 and acceptance.get('protocol_file_sha256')==protocol_sha256
            and acceptance.get('implementation_freeze_file_sha256')==freeze_sha256,'success_audit_uses_same_saved_bytes')
        check(acceptance.get('unperformed_optional_file_checks')==['launcher_executable_file','actual_base_interpreter_file',
            'native_executable_file','local_model_asset_files'],'no_optional_local_remeasurement_claim')
        suite_a,suite_b=interval(report,0,float('inf'),'suite'); check(0<=suite_b-suite_a<=180,'original_suite_180s_bound')
        suite_utc_a,suite_utc_b=stamp(report['started_at']),stamp(report['completed_at'])
        check(stamp(protocol['predeclared_at'])<=stamp(freeze['frozen_at'])<=suite_utc_a<=suite_utc_b,'original_protocol_freeze_run_chronology')
        check(abs((suite_utc_b-suite_utc_a).total_seconds()-(suite_b-suite_a))<=0.25,'suite_UTC_monotonic_consistency')
        cases=report['cases']; check(len(cases)==5 and [c.get('id') for c in cases]==[s[0] for s in success.CASES],'five_original_cases_in_order')
        check([c.get('passed') for c in cases]==[False,False,False,True,False]
            and all(type(c.get('passed')) is bool for c in cases),'four_failures_one_exit37_success')
        nonces=[c['nonce'] for c in cases]; check(all(success.fingerprint(n) for n in nonces) and len(set(nonces))==5,'unique_original_nonces')
    except (KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError) as error:
        check(False,'incomplete_original_report:'+str(error)); cases=report.get('cases',[]) if isinstance(report,dict) else []
        if not isinstance(cases,list): cases=[]

    previous=suite_a; previous_utc=suite_utc_a; total_exits=0; total_unknown=0; authenticated=0; preimport_only=0
    for case,spec in zip(cases,success.CASES):
        name,mode,allocation=spec; prefix=name+':'
        try:
            check((case['id'],case['mode'],case['manual_allocation_bytes'])==spec and type(case['manual_allocation_bytes']) is int,prefix+'original_case_spec')
            start,end=interval(case,suite_a,suite_b,prefix+'case'); check(previous<=start and 0<=end-start<=60,prefix+'case_order_and_60s_bound'); previous=end
            ua,ub=stamp(case['started_at']),stamp(case['completed_at']); check(previous_utc<=ua<=ub<=suite_utc_b
                and abs((ub-ua).total_seconds()-(end-start))<=0.25,prefix+'UTC_monotonic_order'); previous_utc=ub
            check(not any(case.get(k) for k in ('cleanup_error','job_close_error','process_handle_close_error','final_wall_budget_exceeded')),prefix+'no_hidden_cleanup_error')
            check(not forbidden_training_fields(case),prefix+'no_import_failure_model_or_training_receipts')
            nonce=case['nonce']; launcher=case['launcher']; lid=identity(launcher,prefix+'launcher')
            check(launcher.get('assigned_while_suspended') is True and launcher.get('job_handle_inherited') is False,prefix+'launcher_job_custody')
            if mode=='prehandshake_fail':
                check(case.get('passed') is True and case.get('outcome')=='expected_prehandshake_exit37' and not case.get('error'),prefix+'only_expected_exit37_passes')
                check(case.get('prehandshake_control')=={'exit_code':37,'handshake_absent':True,'actual_interpreter_identity_unavailable':True},prefix+'precise_absent_identity_exit37_control')
                check(not any(case.get(k) for k in ('worker_identity','native_descendant','stages','memory_brackets','stage_process_inventories',
                    'failure_cleanup','samples','parent_query_costs')),prefix+'no_substituted_interpreter_or_work')
                exits=cleanup(case,case['cleanup'],[lid],start,end,start,37,prefix); total_exits+=len(exits)
                case_summaries.append({'id':name,'acceptance_passed':True,'observed_stage':'prehandshake_exit37','authenticated_worker':False,
                    'retained_exit_receipts':len(exits),'job_active_count':0,'model_load_receipts':0,'optimizer_update_receipts':0}); continue

            check(case.get('passed') is False and case.get('outcome') is None and case.get('error')==EXPECTED_ERROR
                and 'cleanup' not in case,prefix+'exact_preimport_discovery_failure_preserved')
            check(set(case['stages'])==set(case['memory_brackets'])=={'preimport'},prefix+'only_preimport_stage_reached')
            worker=case['worker_identity']; ready=worker['self_receipt']; wid=identity(ready,prefix+'worker')
            message(ready,nonce,wid[0],prefix+'worker'); reading(ready,wid,start,end,prefix+'ready')
            check(wid[0]!=lid[0] and worker.get('launcher_differs_from_interpreter') is True and ready['parent_pid']==lid[0],prefix+'actual_interpreter_separate_from_launcher')
            check(ready.get('runtime_executable_basename','').lower()=='python.exe'
                and ready.get('runtime_executable_sha256')==freeze['python_executable_sha256'],prefix+'self_launcher_image_claim_kept_separate')
            chain=worker['verified_ancestry']; check(len(chain)==2 and [identity(x,prefix+'ancestor') for x in chain]==[wid,lid]
                and chain[0]['parent_pid']==lid[0] and lid[1]<=wid[1] and all(x.get('job_member') is True for x in chain),prefix+'authenticated_actual_ancestry')
            image_clocks=[]
            for owner,pair,expected in [(worker,wid,freeze['base_python_executable_sha256']),(launcher,lid,freeze['python_executable_sha256'])]:
                image=owner['os_image']; check(identity(image,prefix+'OS_image')==pair and image.get('basename','').lower()=='python.exe'
                    and image.get('sha256')==expected and image.get('queried_from_retained_handle') is True
                    and image.get('matches_frozen_path_and_hash') is True,prefix+'retained_OS_image_hash_path_identity')
                image_clocks.append(image['verified_perf_counter'])
            check(all(finite(t) for t in image_clocks) and ready['perf_counter']<=image_clocks[0]<=image_clocks[1]<=end,prefix+'OS_image_queries_after_authentication')
            native=case['native_descendant']; nid=identity(native['os_identity'],prefix+'native'); launch=native['launch_receipt']
            message(launch,nonce,wid[0],prefix+'native_launch')
            check(nid[0] not in {lid[0],wid[0]} and nid[1]>=wid[1] and native['os_identity']['parent_pid']==wid[0]
                and launch.get('native_pid')==nid[0] and native.get('job_member') is True and native.get('no_native_self_report') is True,prefix+'native_direct_child_identity')
            check(native['os_image'].get('basename','').lower()=='cmd.exe' and native['os_image'].get('sha256')==freeze['native_executable_sha256']
                and native['os_image'].get('matches_frozen') is True,prefix+'native_image_hash')
            check(launch.get('command_arguments')==success.NATIVE_ARGUMENTS and launch.get('shell') is False
                and type(launch.get('creationflags')) is int and launch['creationflags']==0x08000000
                and all(launch.get(k) is True for k in ('close_fds','stdin_anonymous_pipe','stdout_devnull','stderr_devnull')),prefix+'native_control_command')
            stage=case['stages']['preimport']; message(stage,nonce,wid[0],prefix+'preimport')
            check(stage.get('stage')=='preimport' and type(stage.get('native_thread_count')) is int and stage['native_thread_count']>=1
                and stage.get('torch_imported') is False and stage.get('transformers_imported') is False,prefix+'authenticated_no_ML_at_preimport')
            bracket=case['memory_brackets']['preimport']; before,parent,after=[bracket[k] for k in ('self_before','parent','self_after')]
            for label,row in [('before',before),('parent',parent),('after',after)]:
                reading(row,wid,start,end,prefix+label,cpu=label=='parent')
                if label!='parent': message(row,nonce,wid[0],prefix+label)
            check(image_clocks[-1]<=before['perf_counter']<=parent['perf_counter']<=after['perf_counter'],prefix+'preimport_memory_bracket_clock')
            expected={'same_identity':all((r['pid'],r['creation_filetime'])==wid for r in (before,parent,after)),
                'ordered_monotonic_bracket':before['perf_counter']<=parent['perf_counter']<=after['perf_counter']}
            for metric in ('resident','private'):
                a,b,c=[r['memory'][metric+'_bytes'] for r in (before,parent,after)]
                expected[metric+'_within_tolerance']=min(a,c)-4194304<=b<=max(a,c)+4194304
            expected['passed']=all(expected.values()); check(expected['passed'] and bracket['comparison']==expected,prefix+'memory_comparison_independently_recomputed')
            samples=case['samples']; check(bool(samples) and parent in samples,prefix+'actual_parent_sample_retained')
            for i,row in enumerate(samples):
                reading(row,wid,start,end,prefix+'sample',cpu=True)
                if i: check(samples[i-1]['perf_counter']<=row['perf_counter'] and samples[i-1]['native_cpu_seconds']<=row['native_cpu_seconds'],prefix+'sample_clock_CPU_order')
            queries=case['parent_query_costs']; memory_queries=[]; scans=[]; last=start; last_cpu=0
            for row in queries:
                a,b=interval(row,start,end,prefix+'query'); check(last<=a,prefix+'query_monotonic_order'); last=b
                c0,c1=row['started_process_cpu_seconds'],row['completed_process_cpu_seconds']
                check(all(finite(v) for v in (c0,c1)) and last_cpu<=c0<=c1,prefix+'parent_CPU_clock'); last_cpu=c1
                close(row['parent_process_cpu_seconds'],c1-c0,prefix+'parent_CPU_cost_recomputed')
                if row['kind']=='actual_interpreter_memory_and_cpu_query': memory_queries.append(row)
                elif row['kind']=='Toolhelp_process_tree_snapshot': scans.append(row)
                else: check(False,prefix+'unknown_query_kind')
            check(len(memory_queries)==len(samples) and len(scans)==1,prefix+'all_sample_and_single_discovery_query_costs')
            for row,sample in zip(memory_queries,samples): check(row['started_perf_counter']<=sample['perf_counter']<=row['completed_perf_counter'],prefix+'sample_inside_query_cost_clock')

            inventories=case['stage_process_inventories']; check(len(inventories)==1 and inventories[0].get('label')=='preimport',prefix+'single_failed_preimport_discovery')
            inv=inventories[0]; t=inv['perf_counter']; check(finite(t) and after['perf_counter']<=scans[0]['started_perf_counter']<=scans[0]['completed_perf_counter']<=t<=end,prefix+'discovery_after_held_bracket')
            nodes=inv['processes']; pairs=[identity(x,prefix+'observed') for x in nodes]; pids=[p for p,c in pairs]
            known={lid[0],wid[0],nid[0]}; observed=set(pids); unknown=observed-known
            check(len(nodes)==len(set(pids))==5 and inv['observed_pids']==sorted(observed)
                and inv['expected_live_pids']==sorted(known) and known<=observed,prefix+'three_known_five_observed_retained_members')
            check(len(unknown)==2 and inv['unknown_descendants']==sorted(unknown),prefix+'exact_two_unknown_descendants_preserved')
            check(all(x.get('job_member') is True and x.get('alive') is True for x in nodes),prefix+'all_five_observed_live_same_job')
            by_pid={x['pid']:x for x in nodes}; check((by_pid[lid[0]]['pid'],by_pid[lid[0]]['creation_filetime'])==lid
                and (by_pid[wid[0]]['pid'],by_pid[wid[0]]['creation_filetime'])==wid
                and (by_pid[nid[0]]['pid'],by_pid[nid[0]]['creation_filetime'])==nid
                and by_pid[wid[0]]['parent_pid']==lid[0] and by_pid[nid[0]]['parent_pid']==wid[0],prefix+'known_inventory_identity_parent_links')
            for pid in unknown:
                visited=set(); current=pid
                for _ in range(16):
                    if current==lid[0]: break
                    if current in visited or current not in by_pid: raise ValueError('unknown descendant lacks bounded launcher ancestry')
                    visited.add(current); node=by_pid[current]; parent_pid=node['parent_pid']
                    if parent_pid not in by_pid: raise ValueError('unknown descendant parent absent')
                    check(by_pid[parent_pid]['creation_filetime']<=node['creation_filetime'],prefix+'unknown_parent_creation_order')
                    current=parent_pid
                check(current==lid[0],prefix+'unknown_bounded_launcher_ancestry')
            anchor=max([t,after['perf_counter'],*image_clocks]+[r['perf_counter'] for r in samples]+[r['completed_perf_counter'] for r in queries])
            exits=cleanup(case,case['failure_cleanup'],pairs,start,end,anchor,57347,prefix)
            by_exit={x['pid']:x for x in exits}
            check(all((by_exit[pid]['pid'],by_exit[pid]['creation_filetime'])==(by_pid[pid]['pid'],by_pid[pid]['creation_filetime']) for pid in unknown),prefix+'unknown_identities_retained_through_exit')
            authenticated+=1; preimport_only+=1; total_exits+=len(exits); total_unknown+=len(unknown)
            case_summaries.append({'id':name,'acceptance_passed':False,'observed_stage':'preimport_discovery_failed',
                'authenticated_worker':True,'preimport_torch_imported':stage['torch_imported'],'preimport_transformers_imported':stage['transformers_imported'],
                'unknown_descendants':[{k:by_pid[pid][k] for k in ('pid','creation_filetime','parent_pid')} for pid in sorted(unknown)],
                'retained_exit_receipts':len(exits),'unknown_exit_receipts':[by_exit[pid] for pid in sorted(unknown)],
                'job_active_count':0,'model_load_receipts':0,'optimizer_update_receipts':0,'expected_import_failure38_reached':False})
        except (KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError) as error:
            check(False,prefix+'incomplete_negative_receipt:'+str(error))
    check(authenticated==preimport_only==4 and total_unknown==8 and total_exits==21,'four_authenticated_preimport_failures_eight_unknowns_21_exits')
    failures=[x['check'] for x in checks if not x['passed']]
    return {'schema_version':1,'audit_kind':'post_hoc_failure_receipt_consistency','preregistered':False,
        'failure_receipt_consistency_passed':not failures,'experiment_acceptance_passed':False,
        'original_report_declared_passed':report.get('passed') if isinstance(report,dict) else None,
        'frozen_success_auditor_acceptance_passed':acceptance.get('passed') if isinstance(acceptance,dict) else None,
        'frozen_success_auditor_failures':acceptance.get('failures') if isinstance(acceptance,dict) else None,
        'check_count':len(checks),'checks_passed':sum(x['passed'] for x in checks),'failures':failures,'checks':checks,
        'report_file_sha256':report_sha256,'protocol_file_sha256':protocol_sha256,'implementation_freeze_file_sha256':freeze_sha256,
        'frozen_success_auditor_sha256':success_auditor_sha256,'case_summaries':case_summaries,
        'observed_authenticated_preimport_failures':authenticated,'observed_unknown_descendants':total_unknown,'observed_retained_exit_receipts':total_exits,
        'model_load_receipts':sum('postload' in c.get('stages',{}) for c in cases),
        'training_update_receipts':sum('postupdate' in c.get('stages',{}) for c in cases),
        'scope':'Post-hoc saved negative-receipt/hash consistency only, not preregistered acceptance, fresh OS measurement, ML execution or historical correction. Frozen success auditor still rejects. Four authenticated workers report Torch/Transformers absent at preimport; discovery failed before import release, so no load/update/timeout/cap/overhead or injected38 validation is established. Eight unknown descendants retain recorded identities and exit receipts; their executable images and purpose are unverified. Job0/handle exits are saved receipts, not a fresh liveness query or exclusive kill-cause proof. No quality/compression/cost benefit or prior scientific/RSS upgrade.'}


def audit_files(report_path,root=ROOT):
    root=Path(root); protocol_path=root/'fixtures/training-observer/protocol.json'; freeze_path=root/'fixtures/training-observer/implementation.json'
    raw,report=success.bounded(report_path,16*1048576); pr,protocol=success.bounded(protocol_path); fr,freeze=success.bounded(freeze_path)
    # Call the frozen original without executable/model arguments. It must keep
    # rejecting the original report; this module never changes its result.
    acceptance=success.audit_files(report_path,protocol_path,freeze_path,root=root)
    return audit(report,acceptance,protocol,freeze,report_sha256=sha(raw),protocol_sha256=sha(pr),freeze_sha256=sha(fr),
        success_auditor_sha256=sha((root/'scripts/audit_training_observer.py').read_bytes()),
        success_test_sha256=sha((root/'tests/test_training_observer_auditor.py').read_bytes()),
        actual_source_sha256={p:sha((root/p).read_bytes()) for p in success.SOURCE_PATHS},
        actual_dependency_sha256={p:sha((root/p).read_bytes()) for p in success.DEPENDENCY_PATHS})


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--report',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv); result=audit_files(args.report)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n')
    print(json.dumps({k:result[k] for k in ('failure_receipt_consistency_passed','experiment_acceptance_passed','check_count','checks_passed','failures')}))
    return 0 if result['failure_receipt_consistency_passed'] else 1


if __name__=='__main__': raise SystemExit(main())
