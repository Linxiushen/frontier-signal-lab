"""Portable stdlib audit of saved dual-identity census receipts; launches nothing.

Success is saved receipt/hash consistency, not fresh OS measurement, authenticity
of rewritten evidence, loaded-image integrity, continuous coverage or training approval.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
SOURCE_PATHS=('experiments/dual_identity_census.py','tests/test_dual_identity_census.py')
REVIEW_PATHS=('scripts/audit_dual_identity_census.py','tests/test_dual_identity_census_auditor.py')
DEPENDENCY_PATHS=('experiments/process_observer.py','experiments/process_observer_probe.py','experiments/workload_observer_probe.py','fixtures/process-observer/protocol.json','fixtures/process-observer/implementation.json','fixtures/workload-observer/protocol.json','fixtures/workload-observer/implementation.json')
CONFIG={'case_timeout_seconds':20.0,'suite_timeout_seconds':45.0,'stage_timeout_seconds':5.0,'cleanup_timeout_seconds':4.0,'maximum_descendants':16,'maximum_depth':16,'maximum_json_bytes':1048576}
CASES=(('native_census_graceful',False),('injected_python_rejection',True))
NATIVE_ARGUMENTS=['/d','/q','/c','set /p workload_observer_gate=']
SELF_ROLES={'worker':'launcher','helper':'base_python'}
OS_ROLES={'worker':'base_python','helper':'base_python'}
sha=lambda b:hashlib.sha256(b).hexdigest()
def finite(x): return type(x) in (int,float) and math.isfinite(x)
def fingerprint(x): return isinstance(x,str) and re.fullmatch('[0-9a-f]{64}',x) is not None
def audit(report,protocol,freeze,*,protocol_sha256,freeze_sha256,actual_source_sha256,actual_dependency_sha256,actual_review_tools_sha256,executable_sha256=None):
    checks=[];summaries=[]
    def check(ok,name): checks.append({'check':name,'passed':bool(ok)});return bool(ok)
    def close(a,b,name): check(finite(a) and finite(b) and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8),name)
    def stamp(s):
        v=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
        if v.tzinfo is None: raise ValueError('UTC offset missing')
        return v
    def identity(row,name):
        pair=row['pid'],row['creation_filetime'];check(all(type(x)is int and x>0 for x in pair),name+':PID_creation');return pair
    def message(row,nonce,role,pid,name): check(row.get('nonce')==nonce and row.get('role')==role and row.get('pid')==pid,name+':nonce_role_PID')
    def no_ml(row,name,imports=False):
        check(row.get('training_permitted')is False and type(row.get('model_loads'))is int and row['model_loads']==0 and type(row.get('optimizer_steps'))is int and row['optimizer_steps']==0,name+':training_forbidden_zero_work')
        if imports: check(row.get('torch_imported')is False and row.get('transformers_imported')is False,name+':no_ML_imports')
    def span(row,lo,hi,limit,name):
        a,b=row['started_perf_counter'],row['completed_perf_counter'];check(all(finite(x)for x in (a,b)) and lo<=a<=b<=hi and b-a<=limit,name+':bounded_interval');close(row['wall_seconds'],b-a,name+':wall_recomputed');return a,b
    def ancestry(owner,nonce,role,ancestor,lo,hi,name):
        ready=owner['self_receipt'];pair=identity(ready,name);message(ready,nonce,role,pair[0],name)
        check(finite(ready['perf_counter']) and lo<=ready['perf_counter']<=hi,name+':ready_clock')
        chain=owner['verified_ancestry'];pairs=[identity(x,name+':ancestor')for x in chain]
        check(1<=len(chain)<=16 and len({x[0]for x in pairs})==len(pairs) and pairs[0]==pair and pairs[-1]==ancestor,name+':bounded_ancestry_endpoints')
        check(ready['parent_pid']==chain[0]['parent_pid'] and all(x.get('job_member')is True for x in chain),name+':self_parent_job')
        check(all(c['parent_pid']==p['pid'] and p['creation_filetime']<=c['creation_filetime']for c,p in zip(chain,chain[1:])),name+':parent_creation_order')
        self_image=ready['self_executable'];expected=SELF_ROLES[role]
        check(owner['self_executable_expected_role']==expected and owner['retained_os_image_expected_role']==OS_ROLES[role],name+':declared_independent_roles')
        check(not any(k.startswith('runtime_executable_')for k in ready) and set(self_image)=={'source','basename','sha256','normalized_path_sha256'} and self_image['source']=='sys.executable' and isinstance(self_image['basename'],str) and bool(self_image['basename']) and '/'not in self_image['basename'] and '\\'not in self_image['basename'] and self_image['sha256']==executables[expected] and self_image['normalized_path_sha256']==path_hashes[expected],name+':self_executable_matches_declared_role')
        return pair,chain
    try:
        check(report['schema_version']==protocol['schema_version']==1 and report['experiment_id']==protocol['experiment_id']=='windows-dual-identity-census-v1','schema_experiment')
        check(protocol['config']==CONFIG and tuple(protocol['source_paths'])==SOURCE_PATHS and tuple(protocol['frozen_dependency_paths'])==DEPENDENCY_PATHS and tuple(protocol['review_tool_paths'])==REVIEW_PATHS,'fixed_protocol_sources_config')
        check([(x['id'],x['injected'])for x in protocol['cases_in_order']]==list(CASES) and protocol['training_permitted']is False,'fixed_cases_no_training')
        check(protocol['self_executable_roles']==report['self_executable_roles']==SELF_ROLES and protocol['retained_os_image_roles']==report['retained_os_image_roles']==OS_ROLES,'fixed_independent_identity_role_contracts')
        check(freeze['protocol_sha256']==report['protocol_sha256']==protocol_sha256 and report['implementation_sha256']==freeze_sha256,'protocol_freeze_hash_chain')
        for field,paths,actual,out in [('new_source_files_sha256',SOURCE_PATHS,actual_source_sha256,'source_sha256'),('frozen_dependency_files_sha256',DEPENDENCY_PATHS,actual_dependency_sha256,'dependencies_sha256'),('review_tools_sha256',REVIEW_PATHS,actual_review_tools_sha256,'review_tools_sha256')]:
            values=freeze[field];check(set(values)==set(paths) and all(fingerprint(x)for x in values.values()) and values==actual==report[out],field+':actual_hash_inventory')
        executables=freeze['executables_sha256'];path_hashes=report['executable_path_sha256']
        check(set(executables)==set(path_hashes)=={'launcher','base_python','native'} and all(fingerprint(x)for x in [*executables.values(),*path_hashes.values()]) and report['executables_sha256']==executables and freeze['executable_path_sha256']==path_hashes,'frozen_executable_and_opaque_path_hashes')
        if executable_sha256 is not None: check(executable_sha256==executables,'optional_local_executable_hashes')
        declared,frozen,started,ended=map(stamp,(protocol['predeclared_at'],freeze['frozen_at'],report['started_at'],report['completed_at']))
        check(declared<=frozen<=started<=ended and report['protocol_predeclared_at']==protocol['predeclared_at'] and report['implementation_frozen_at']==freeze['frozen_at'],'declaration_freeze_run_chronology')
        check(report.get('passed')is True and not report.get('error') and report.get('os_name')=='nt' and report.get('no_fallback')is True,'reported_acceptance_Windows_no_fallback')
        no_ml(report,'suite');s0,s1=span(report,0,float('inf'),45,'suite')
        cases=report['cases'];check([(c['id'],c['injected'])for c in cases]==list(CASES) and all(type(c['injected'])is bool for c in cases),'exact_two_cases_in_order')
        nonces=[c[k]for c in cases for k in ('nonce','helper_nonce')];check(len(nonces)==len(set(nonces))==4 and all(fingerprint(x)for x in nonces),'four_distinct_nonces')
    except (KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError) as e:
        check(False,'incomplete_suite:'+str(e));cases=[];s0=s1=0;started=ended=None;executables={};path_hashes={}
    previous=s0;previous_utc=started
    for case,(name,injected) in zip(cases,CASES):
        pre=name+':'
        try:
            check(case.get('passed')is True and not any(case.get(k)for k in ('error','cleanup_error','job_close_error','process_handle_close_error','case_wall_budget_exceeded')) and 'failure_cleanup'not in case,pre+'no_hidden_failure')
            no_ml(case,pre+'case');c0,c1=span(case,previous,s1,20,pre+'case');previous=c1
            u0,u1=stamp(case['started_at']),stamp(case['completed_at']);check(previous_utc<=u0<=u1<=ended,pre+'UTC_order');previous_utc=u1
            launcher=case['launcher'];lid=identity(launcher,pre+'launcher');check(launcher.get('assigned_while_suspended')is True and launcher.get('job_handle_inherited')is False,pre+'suspended_assignment_no_handle_inherit')
            wid,chain=ancestry(case['worker_identity'],case['nonce'],'worker',lid,c0,c1,pre+'worker');check(wid[0]!=lid[0],pre+'launcher_actual_distinct')
            ready=case['worker_identity']['self_receipt']
            state=case['worker_census_state'];message(state,case['nonce'],'worker',wid[0],pre+'state');no_ml(state,pre+'state',True)
            native=case['native_descendant'];nid=identity(native['os_identity'],pre+'native');launch=native['launch_receipt'];message(launch,case['nonce'],'worker',wid[0],pre+'native_launch')
            check(launch['native_pid']==nid[0] and launch['command_arguments']==NATIVE_ARGUMENTS and launch['close_fds']is True and launch['stdin_anonymous_pipe']is True and launch['shell']is False and launch['creationflags']==0x08000000 and launch['stdout_devnull']is True and launch['stderr_devnull']is True,pre+'fixed_native_command')
            check(native['os_identity']['parent_pid']==wid[0] and nid[1]>=wid[1] and native['job_member']is True and native['no_native_self_report']is True and native['os_image']=={'basename':native['os_image']['basename'],'sha256':executables['native'],'matches_frozen':True} and native['os_image']['basename'].lower()=='cmd.exe',pre+'native_parent_OS_image')
            known={lid: 'launcher',wid:'base_python',nid:'native'};retained={};parent_links={};labels=['before_native','after_native']+(['after_helper']if injected else [])
            check([r['label']for r in case['censuses']]==labels,pre+'exact_stage_order');last=ready['perf_counter'];all_unknown=set()
            for row in case['censuses']:
                tag=pre+row['label'];a,b=span(row,last,c1,5,tag);last=b
                check(row.get('training_permitted')is False and row.get('census_complete')is True and not row['errors'] and row['truncated']is False and row['query_budget_exceeded']is False,tag+':complete_no_errors')
                nodes=row['processes'];pairs=[identity(n,tag)for n in nodes];pids=[p[0]for p in pairs];by={n['pid']:n for n in nodes}
                check(2<=len(nodes)<=17 and len(set(pids))==len(nodes) and row['observed_pids']==sorted(pids) and row['snapshot_observed_count']==len(nodes),tag+':bounded_full_observed_set')
                check(type(row['job_count_before'])is int and type(row['job_count_after'])is int and row['job_count_before']==row['job_count_after']==len(nodes) and row['job_count_matches_before']is True and row['job_count_matches_after']is True,tag+':two_job_counts_recomputed')
                expected={p:r for p,r in known.items()if r!='native' or row['label']!='before_native'}
                check(set(expected)<=set(pairs) and row['all_known_present']is True,tag+':all_exact_known_identities')
                check(row['label']!='before_native' or nid[0]not in pids,tag+':native_absent_before_creation')
                unknown=[]
                for n,pair in zip(nodes,pairs):
                    check(n.get('job_member')is True and n.get('alive')is True and not n.get('error'),tag+':live_retained_job')
                    check(pair[0]not in retained or retained[pair[0]]==pair[1],tag+':no_PID_reuse');retained[pair[0]]=pair[1]
                    check(pair not in parent_links or parent_links[pair]==n['parent_pid'],tag+':retained_parent_stable');parent_links[pair]=n['parent_pid'];image=n['image'];matches=image['exact_path_matches'];role=expected.get(pair)
                    check(isinstance(image['basename'],str) and bool(image['basename']) and '/'not in image['basename'] and '\\'not in image['basename'] and fingerprint(image['sha256']) and fingerprint(image['normalized_path_sha256']) and image['queried_from_retained_handle']is True and image['retained_identity_stable']is True,tag+':complete_retained_OS_image')
                    check(isinstance(matches,list) and matches==sorted(set(matches)) and set(matches)<=set(executables) and image['path_classification']in ('exact_executable','system32','other') and (image['path_classification']=='exact_executable')==bool(matches),tag+':path_classification_not_basename')
                    for match in matches: check(image['sha256']==executables[match] and image['normalized_path_sha256']==path_hashes[match],tag+':exact_path_hash_agrees')
                    check(n['approved_known']is bool(role) and n['policy_role']==(role or 'unapproved'),tag+':exact_PID_creation_policy')
                    if role: check(role in matches and image['sha256']==executables[role] and image['normalized_path_sha256']==path_hashes[role],tag+':known_OS_image_matches_freeze')
                    else: unknown.append(pair[0]);all_unknown.add(pair)
                    current=pair[0];visited=set()
                    for _ in range(17):
                        if current==lid[0]: break
                        if current in visited or current not in by or by[current]['parent_pid']not in by: raise ValueError('orphan/cyclic census tree')
                        visited.add(current);child=by[current];parent=by[child['parent_pid']];check(parent['creation_filetime']<=child['creation_filetime'],tag+':parent_creation_order');current=parent['pid']
                    check(current==lid[0] and len(visited)<=16,tag+':bounded_launcher_ancestry')
                check(row['unapproved_pids']==sorted(unknown),tag+':every_extra_stays_unapproved')
            check(case['before_native_unapproved_pids']==case['censuses'][0]['unapproved_pids'],pre+'before_unknowns_retained')
            check(parent_links.get(nid)==wid[0],pre+'native_snapshot_parent_matches_identity')
            for role,owner in [('worker',case['worker_identity'])]+([('helper',case['injected_helper'])]if injected else []):
                images=[n['image']for row in case['censuses']for n in row['processes']if n['policy_role']==SELF_ROLES[role]]
                check(bool(images) and all(image['basename'].lower()==owner['self_receipt']['self_executable']['basename'].lower()for image in images),pre+role+':self_basename_matches_declared_path_role')
            for node in chain: check(retained.get(node['pid'])==node['creation_filetime'] and parent_links[(node['pid'],node['creation_filetime'])]==node['parent_pid'],pre+'authenticated_chain_retained')
            if injected:
                helper=case['injected_helper'];hid,hchain=ancestry(helper,case['helper_nonce'],'helper',wid,case['censuses'][1]['completed_perf_counter'],case['censuses'][2]['started_perf_counter'],pre+'helper')
                hlaunch=helper['launch_receipt'];message(hlaunch,case['nonce'],'worker',wid[0],pre+'helper_launch')
                check(hlaunch['helper_launcher_pid']==hid[0] and hlaunch['base_executable_sha256']==executables['base_python'] and hlaunch['shell']is False and hlaunch['close_fds']is True and hlaunch['creationflags']==0x08000000,pre+'fixed_helper_launch')
                hnode=next(n for n in case['censuses'][-1]['processes']if n['pid']==hid[0]);check(identity(hnode,pre+'helper_node')==hid and hid in all_unknown and hnode['policy_role']=='unapproved' and 'base_python'in hnode['image']['exact_path_matches'],pre+'identified_same_image_helper_rejected')
                check(all(hid[0]not in row['observed_pids']for row in case['censuses'][:2]),pre+'helper_absent_before_creation')
                for node in hchain: check(retained.get(node['pid'])==node['creation_filetime'] and parent_links[(node['pid'],node['creation_filetime'])]==node['parent_pid'],pre+'helper_chain_retained')
                rejection=case['rejection'];check(rejection['helper_pid']==hid[0] and rejection['training_permitted']is False and rejection['ML_release_absent']is True,pre+'no_helper_or_ML_release')
                ta,tb=case['termination_started_perf_counter'],case['termination_returned_perf_counter'];check(finite(ta) and finite(tb) and last<=ta<=tb<=c1,pre+'termination_interval');anchor=tb
                live=case['pretermination_live_members'];required={wid,nid,hid};check(case['outcome']=='identified_helper_rejected_no_training' and 'completion'not in case,pre+'rejection_outcome')
            else:
                done=case['completion'];message(done,case['nonce'],'worker',wid[0],pre+'completion');no_ml(done,pre+'completion',True)
                check(done['native_exit_code']==0 and done['native_released_nonempty_line']is True and case['outcome']=='graceful_census_no_training' and 'rejection'not in case,pre+'graceful_outcome');live=case['prefinish_live_members'];required={wid,nid};anchor=last
            check({identity(x,pre+'live')for x in live}==required and len(live)==len(required),pre+'exact_live_known_controls')
            for row in live: check(row['alive']is True and row['job_member']is True and finite(row['verified_perf_counter']) and last<=row['verified_perf_counter']<=(ta if injected else c1),pre+'live_clock_job')
            anchor=max(anchor,*(x['verified_perf_counter']for x in live));cleanup=case['cleanup'];a,b=span(cleanup,anchor,c1,4,pre+'cleanup')
            check(cleanup['all_retained_handles_exited']is True and cleanup['job_active_count']==0 and finite(cleanup['timeout_seconds']) and 0<cleanup['timeout_seconds']<=4 and b-a<=cleanup['timeout_seconds']+1e-8,pre+'bounded_all_retained_exit_job_zero')
            exits=cleanup['exit_codes'];pairs=[identity(x,pre+'exit')for x in exits];check(len(set(pairs))==len(exits) and set(pairs)==set(retained.items()),pre+'all_observed_identities_have_exact_exit_receipts')
            for row in exits: check(type(row['exit_code'])is int and 0<=row['exit_code']<2**32,pre+'preserved_exit_code')
            codes={(x['pid'],x['creation_filetime']):x['exit_code']for x in exits};check(all(codes[p]==(57347 if injected else 0)for p in ({lid,wid,hid}if injected else {lid,wid,nid})),pre+'controlled_exit_codes')
            summaries.append({'id':name,'unapproved_identities':[{'pid':p,'creation_filetime':c}for p,c in sorted(all_unknown)],'exit_receipts':len(exits),'training_permitted':False})
        except (KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError,StopIteration) as e: check(False,pre+'incomplete_receipt:'+str(e))
    failures=[x['check']for x in checks if not x['passed']]
    return {'schema_version':1,'audit_kind':'saved_dual_identity_census_consistency','passed':not failures,'training_permitted':False,'model_loads':0,'optimizer_steps':0,'check_count':len(checks),'checks_passed':sum(x['passed']for x in checks),'failures':failures,'checks':checks,'case_summaries':summaries,'scope':__doc__}

def bounded(path):
    b=Path(path).read_bytes()
    if len(b)>1048576: raise ValueError('JSON exceeds fixed1MiB bound')
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result: raise ValueError('duplicate JSON key')
            result[k]=v
        return result
    return b,json.loads(b,object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
def audit_files(report_path,protocol_path=None,freeze_path=None,*,root=ROOT,executables=None):
    root=Path(root);p=Path(protocol_path)if protocol_path else root/'fixtures/dual-identity-census/protocol.json';f=Path(freeze_path)if freeze_path else root/'fixtures/dual-identity-census/implementation.json'
    rb,report=bounded(report_path);pb,protocol=bounded(p);fb,freeze=bounded(f)
    result=audit(report,protocol,freeze,protocol_sha256=sha(pb),freeze_sha256=sha(fb),actual_source_sha256={p:sha((root/p).read_bytes())for p in SOURCE_PATHS},actual_dependency_sha256={p:sha((root/p).read_bytes())for p in DEPENDENCY_PATHS},actual_review_tools_sha256={p:sha((root/p).read_bytes())for p in REVIEW_PATHS},executable_sha256={k:sha(Path(v).read_bytes())for k,v in executables.items()}if executables else None)
    result.update(report_sha256=sha(rb),protocol_sha256=sha(pb),implementation_sha256=sha(fb));return result
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--protocol',type=Path);parser.add_argument('--freeze',type=Path)
    for role in ('launcher','base-python','native'): parser.add_argument('--'+role,type=Path)
    args=parser.parse_args(argv);images={'launcher':args.launcher,'base_python':args.base_python,'native':args.native}
    if any(images.values()) and not all(images.values()): parser.error('supply all three optional local executable paths')
    result=audit_files(args.report,args.protocol,args.freeze,executables=images if all(images.values()) else None);args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8',newline='\n')as stream: json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({k:result[k]for k in ('passed','training_permitted','check_count','checks_passed','failures')}));return 0 if result['passed']else 1
if __name__=='__main__': raise SystemExit(main())
