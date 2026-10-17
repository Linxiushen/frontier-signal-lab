"""Independent synthetic receipts/mutations; no producer, OS or ML execution."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import audit_training_observer_v2 as auditor

MIB=1024*1024


def fixture():
    sources=dict(auditor.SOURCE_HASHES or {p:'a'*64 for p in auditor.SOURCE_PATHS})
    dependencies=dict(auditor.DEPENDENCY_HASHES or {p:'b'*64 for p in auditor.DEPENDENCY_PATHS})
    pin=auditor.PROTOCOL_SHA256 or '1'*64
    protocol={'schema_version':1,'experiment_id':auditor.EXPERIMENT,'predeclared_at':'2026-10-16T00:00:00+00:00',
        'source_paths':list(auditor.SOURCE_PATHS),'frozen_dependency_paths':list(auditor.DEPENDENCY_PATHS),
        'review_tool_paths':list(auditor.REVIEW_PATHS),'config':dict(auditor.CONFIG),'cases_in_order':[{'id':i,'mode':m,'manual_allocation_bytes':n} for i,m,n in auditor.CASES],
        'model':{'id':auditor.MODEL_ID,'revision':auditor.MODEL_REVISION,'assets':copy.deepcopy(auditor.ASSETS),
            'planned_model_loads':3,'planned_optimizer_updates':6,'dense_only':True,'no_download_install_or_GPU':True},
        'training':{'train_sha256':auditor.TRAIN_SHA256,'schedule':auditor.schedule(),
            'schedule_sha256':auditor.sha(auditor.canonical(auditor.schedule()).encode()),'seed':503,'steps':2,
            'batch_shape':[2,65],'input_tokens_per_batch':128,'optimizer':copy.deepcopy(auditor.OPTIMIZER),
            'method':'dense','arm':'token','holdout_opened':False,'checkpoint_written':False}}
    freeze={'schema_version':1,'frozen_at':'2026-10-16T00:00:01+00:00','protocol_sha256':pin,
        'new_source_files_sha256':sources,'frozen_dependency_files_sha256':dependencies,
        'review_tools_sha256':{p:'9'*64 for p in auditor.REVIEW_PATHS},'python_executable_sha256':'c'*64,'base_python_executable_sha256':'f'*64,'native_executable_sha256':'e'*64}
    report={'schema_version':1,'experiment_id':auditor.EXPERIMENT,'protocol_sha256':pin,'implementation_sha256':'d'*64,
        'review_tools_sha256':dict(freeze['review_tools_sha256']),'source_sha256':dict(sources),'frozen_dependencies_sha256':dict(dependencies),'launch_executable_sha256':'c'*64,
        'actual_worker_expected_os_image_sha256':'f'*64,'native_executable_sha256':'e'*64,
        'model_id':auditor.MODEL_ID,'model_revision':auditor.MODEL_REVISION,'model_assets':copy.deepcopy(auditor.ASSETS),
        'protocol_predeclared_at':protocol['predeclared_at'],'implementation_frozen_at':freeze['frozen_at'],
        'started_at':'2026-10-16T00:00:02+00:00','completed_at':'2026-10-16T00:01:42+00:00',
        'started_perf_counter':100.0,'completed_perf_counter':200.0,'wall_seconds':100.0,
        'passed':True,'os_name':'nt','no_fallback':True,'planned_model_loads':3,'planned_optimizer_updates':6,'cases':[]}
    for index,(case_id,mode,allocation) in enumerate(auditor.CASES):
        tick=102.0+index*18; offset=index*1000; nonce=f'{index+1:064x}'
        lid,wid,nid=(offset+1,10+offset),(offset+2,20+offset),(offset+3,30+offset)
        def msg(**kwargs): return {'nonce':nonce,'role':'worker','pid':wid[0],**kwargs}
        def reading(clock,increase=0,cpu=False):
            row={'pid':wid[0],'creation_filetime':wid[1],'perf_counter':clock,
                'memory':{'resident_bytes':100*MIB+increase,'private_bytes':80*MIB+increase,'peak_resident_bytes':100*MIB+increase}}
            if cpu: row['native_cpu_seconds']=(clock-tick)*0.5+1
            return row
        def image(pair,digest): return {'pid':pair[0],'creation_filetime':pair[1],'basename':'python.exe',
            'sha256':digest,'queried_from_retained_handle':True,'matches_frozen_path_and_hash':True,'verified_perf_counter':tick+0.2}
        start_utc=dt.datetime(2026,10,16,0,0,4,tzinfo=dt.timezone.utc)+dt.timedelta(seconds=index*18)
        case={'id':case_id,'mode':mode,'manual_allocation_bytes':allocation,'nonce':nonce,'passed':True,
            'started_at':start_utc.isoformat(),'completed_at':(start_utc+dt.timedelta(seconds=12)).isoformat(),
            'started_perf_counter':tick,'completed_perf_counter':tick+12,'wall_seconds':12.0,
            'launcher':{'pid':lid[0],'creation_filetime':lid[1],'assigned_while_suspended':True,'job_handle_inherited':False},
            'samples':[],'parent_query_costs':[]}
        retained=[lid]
        if mode=='prehandshake_fail':
            case.update(prehandshake_control={'exit_code':37,'handshake_absent':True,'actual_interpreter_identity_unavailable':True},
                outcome='expected_prehandshake_exit37')
        else:
            retained+=[wid,nid]; case['launcher']['os_image']=image(lid,'c'*64)
            case['worker_identity']={'self_receipt':msg(**reading(tick+0.1),parent_pid=lid[0],
                runtime_executable_basename='python.exe',runtime_executable_sha256='c'*64),
                'launcher_differs_from_interpreter':True,'os_image':image(wid,'f'*64),
                'verified_ancestry':[{'pid':wid[0],'creation_filetime':wid[1],'parent_pid':lid[0],'job_member':True},
                    {'pid':lid[0],'creation_filetime':lid[1],'parent_pid':999999,'job_member':True}]}
            case['native_descendant']={'launch_receipt':msg(native_pid=nid[0],command_arguments=list(auditor.NATIVE_ARGUMENTS),
                close_fds=True,stdin_anonymous_pipe=True,shell=False,creationflags=0x08000000,stdout_devnull=True,stderr_devnull=True),
                'os_identity':{'pid':nid[0],'creation_filetime':nid[1],'parent_pid':wid[0]},
                'os_image':{'basename':'cmd.exe','sha256':'e'*64,'matches_frozen':True},'job_member':True,'no_native_self_report':True}
            def query(kind,a,b):
                return {'kind':kind,'started_perf_counter':a,'completed_perf_counter':b,'wall_seconds':b-a,
                    'started_process_cpu_seconds':a*0.01,'completed_process_cpu_seconds':b*0.01,
                    'parent_process_cpu_seconds':(b-a)*0.01}
            def sample(clock,increase=0):
                row=reading(clock,increase,cpu=True); case['samples'].append(row)
                case['parent_query_costs'].append(query('actual_interpreter_memory_and_cpu_query',clock-0.001,clock+0.001)); return row
            def inventory(label,clock):
                case['parent_query_costs'].append(query('Toolhelp_process_tree_snapshot',clock-0.02,clock-0.01))
                nodes=[{'pid':p,'creation_filetime':c,'parent_pid':999999 if p==lid[0] else lid[0] if p==wid[0] else wid[0],
                    'job_member':True,'alive':True} for p,c in retained]
                case['stage_process_inventories'].append({'label':label,'perf_counter':clock,'processes':nodes,
                    'expected_live_pids':sorted(p for p,c in retained),'observed_pids':sorted(p for p,c in retained),'unknown_descendants':[]})
            case.update(stages={},memory_brackets={},stage_process_inventories=[])
            labels=('preimport',) if mode=='import_fail' else auditor.STAGES
            for j,label in enumerate(labels):
                clock=tick+j+1 if label!='allocated' else tick+(6 if mode=='healthy' else 5)
                inc=allocation if label=='allocated' else 0
                parent=sample(clock+0.05,inc)
                case['memory_brackets'][label]={'self_before':msg(**reading(clock,inc)),'parent':parent,
                    'self_after':msg(**reading(clock+0.1,inc)),
                    'comparison':dict(same_identity=True,ordered_monotonic_bracket=True,resident_within_tolerance=True,private_within_tolerance=True,passed=True)}
                case['stages'][label]=msg(stage=label,native_thread_count=4)
                inventory(label,clock+0.15)
            case['stages']['preimport'].update(torch_imported=False,transformers_imported=False)
            if mode=='import_fail':
                case.update(import_failure_receipt=msg(stage='import',exception_type='ModuleNotFoundError',
                    missing_module='training_observer_missing_dependency_'+nonce,torch_imported=False,transformers_imported=False,
                    model_loads=0,optimizer_steps=0,expected_exit_code=38),expected_worker_exit_code=38,
                    outcome='expected_injected_import_failure38')
            else:
                case['stages']['postimport'].update(torch_version='2.9.1+cpu',transformers_version='4.57.3')
                sched=auditor.schedule()
                case['stages']['postload']['model']={'model_id':auditor.MODEL_ID,'model_revision':auditor.MODEL_REVISION,
                    'train_sha256':auditor.TRAIN_SHA256,'schedule':sched,'schedule_sha256':auditor.sha(auditor.canonical(sched).encode()),
                    'seed':503,'trainable_parameter_count':14067712,'parameter_tensors':76,'initial_parameter_sha256':'2'*64,
                    'batch_shapes':[[2,65],[2,65]],'device':'cpu','dtype':'torch.float32','intraop_threads':1,'interop_threads':1,
                    'deterministic_algorithms':True,'loader_local_files_only':True,'trust_remote_code':False,'attention':'eager',
                    'holdout_opened':False,'offline_environment':dict(auditor.OFFLINE_ENV),
                    'preparation_timing':{'started_perf_counter':tick+2.2,'completed_perf_counter':tick+2.8,'wall_seconds':0.6},
                    'model_load_timing':{'started_perf_counter':tick+2.3,'completed_perf_counter':tick+2.7,'wall_seconds':0.4}}
                case['stages']['postupdate']['operation']={'method':'dense','arm':'token','optimizer':copy.deepcopy(auditor.OPTIMIZER),
                    'loop':{'steps_completed':2,'training_target_positions':256,'training_loop_wall_seconds':0.6,
                        'training_loop_cpu_seconds':0.5,'loop_perf_counter_start':tick+3.2,'loop_perf_counter_end':tick+3.8,
                        'training_targets_per_second':256/0.6,'preupdate_batch_losses_recorded_after_updates':[4.0,3.9]},
                    'final_validity':{'final_parameter_gradient_moments_finite':True,'optimizer_counters':[2]*76},
                    'final_parameter_sha256':'3'*64,'no_checkpoint_written':True,'no_holdout_evaluation':True}
                case['stages']['allocated']['manual_allocation_bytes']=allocation
                case['allocation_check']={'explicit_allocation_bytes':allocation,'parent_deltas_bytes':{'resident_bytes':allocation,'private_bytes':allocation},
                    'minimum_required_increase_bytes':58720256 if allocation else 0,'passed':True}
                if mode=='healthy':
                    # Insert held-window queries in chronological order, then set
                    # their indices from the complete independent synthetic list.
                    sample(tick+4.75)
                    case['parent_query_costs'].append(query('Toolhelp_process_tree_snapshot',tick+4.78,tick+4.79))
                    case['parent_query_costs'].sort(key=lambda r:r['started_perf_counter']); case['samples'].sort(key=lambda r:r['perf_counter'])
                    windows=[]
                    for enabled,a,b in [(False,tick+4.2,tick+4.6),(True,tick+4.7,tick+5.1)]:
                        qi=sum(q['completed_perf_counter']<a for q in case['parent_query_costs']); qj=sum(q['completed_perf_counter']<=b for q in case['parent_query_costs'])
                        si=sum(s['perf_counter']<a for s in case['samples']); sj=sum(s['perf_counter']<=b for s in case['samples'])
                        windows.append({'sampling_enabled':enabled,'started_perf_counter':a,'completed_perf_counter':b,'wall_seconds':b-a,
                            'parent_native_cpu_start_seconds':1.0,'parent_native_cpu_end_seconds':1.0 if not enabled else 1.01,
                            'parent_native_cpu_delta_seconds':0.0 if not enabled else 0.01,
                            'query_cost_index_start':qi,'query_cost_index_end':qj,'sample_index_start':si,'sample_index_end':sj})
                    case.update(held_parent_overhead_windows=windows,healthy_memory_limit_disabled=True,
                        healthy_completion=msg(native_exit_code=0,native_released_nonempty_line=True,model_loads=1,optimizer_steps=2),outcome='normal_completion',
                        prefinish_live_members=[{'pid':p,'creation_filetime':c,'alive':True,'job_member':True,'verified_perf_counter':tick+6.2} for p,c in [wid,nid]])
                else:
                    a=tick+5.3; b=a+(1.6 if mode=='timeout' else 0.2)
                    count=16 if mode=='timeout' else 2
                    selected=[sample(a+i*0.1,allocation) for i in range(count+1)]; selected[-1]['perf_counter']=b
                    case.update(busy_ready=msg(perf_counter=a,extra_backward_calls=0,extra_optimizer_steps=0,model_forward_no_grad=True),
                        busy_first_operation=msg(completed_perf_counter=a+0.01,model_forward_iterations_completed=1,
                            extra_backward_calls=0,extra_optimizer_steps=0,model_forward_no_grad=True),
                        busy_sampling={'started_perf_counter':a,'completed_perf_counter':b,'wall_seconds':b-a,'samples_count':len(selected),
                            'maximum_gap_including_boundaries_seconds':0.1,'native_cpu_delta_seconds':selected[-1]['native_cpu_seconds']-selected[0]['native_cpu_seconds'],'gap_gate_passed':True},
                        termination_request_started_perf_counter=b+0.1,termination_request_returned_perf_counter=b+0.11,
                        pretermination_live_members=[{'pid':p,'creation_filetime':c,'alive':True,'job_member':True,'verified_perf_counter':b+0.08} for p,c in [wid,nid]])
                    inventory('pretermination',b+0.05)
                    if mode=='timeout': case.update(busy_deadline_perf_counter=a+1.5,outcome='timeout')
                    else: case.update(actual_interpreter_private_limit_bytes=128*MIB,first_over_limit_sample=case['memory_brackets']['allocated']['parent'],
                        allocation_ready_to_termination_seconds=b+0.11-(tick+5),outcome='memory_private_limit')
        case['cleanup']={'all_retained_handles_exited':True,'job_active_count':0,
            'exit_codes':[{'pid':p,'creation_filetime':c,'exit_code':0 if mode=='healthy' else 37 if mode=='prehandshake_fail'
                else 38 if mode=='import_fail' and p!=nid[0] else 0xE003} for p,c in retained],
            'started_perf_counter':tick+10,'completed_perf_counter':tick+10.1,'wall_seconds':0.1,'timeout_seconds':4.0}
        report['cases'].append(case)
    upgrade_fixture(report,protocol,freeze)
    return report,protocol,freeze,sources,dependencies


def upgrade_fixture(report, protocol, freeze):
    """Synthetic held OS and independent sender/receiver custody, never native calls."""
    executables = {'launcher':'c'*64, 'base_python':'f'*64, 'native':'e'*64, 'conhost':'7'*64}
    protocol['control_plan']=[{'filename':name,'command':command,'decision_label':label,'decision_index':index}
        for name,command,label,index in auditor.CONTROL_PLAN]
    protocol['provider_custody']={'denied_python_audit_events':list(auditor.PROVIDER_EVENTS),
        'external_providers_permitted':False,'native_network_sandbox':False,'synthetic_probe_denials':1,
        'unexpected_denied_events_allowed':0}
    paths = {role:str(index)*64 for index,role in enumerate(executables, 1)}
    freeze.update(executables_sha256=executables, executable_path_sha256=paths)
    report.update(executables_sha256=copy.deepcopy(executables),executable_path_sha256=copy.deepcopy(paths))
    for case in report['cases']:
        tick, mode = case['started_perf_counter'], case['mode']
        case.update(executables_sha256=copy.deepcopy(executables),executable_path_sha256=copy.deepcopy(paths),
            case_deadline_perf_counter=min(tick+60,280.0),suite_deadline_perf_counter=280.0,
            cleanup_exact_retained_identity_set=True,control_custody_verified=True,censuses=[],role_decisions=[],
            controller_controls=[],worker_controls=[])
        if mode == 'prehandshake_fail':
            continue
        lid=case['launcher']['pid']; wid=case['worker_identity']['self_receipt']['pid']
        nid=case['native_descendant']['os_identity']['pid']; launch_aux=lid+3; native_aux=lid+4
        refs={r['pid']:r['creation_filetime'] for r in case['cleanup']['exit_codes']}
        refs.update({launch_aux:refs[lid]+31,native_aux:refs[nid]+31})
        def ref(pid): return {'pid':pid,'creation_filetime':refs[pid]}
        worker=case['worker_identity']; ready=worker['self_receipt']
        ready.pop('runtime_executable_basename');ready.pop('runtime_executable_sha256')
        ready['self_executable']={'source':'sys.executable','basename':'python.exe','sha256':executables['launcher'],'normalized_path_sha256':paths['launcher']}
        worker.update(self_executable_expected_role='launcher',retained_os_image_expected_role='base_python')
        launch=case['native_descendant']['launch_receipt']
        launch.update(launch_started_perf_counter=tick+.4,launch_completed_perf_counter=tick+.5)
        legacy=case.pop('stage_process_inventories')
        labels=['before_native']+ [r['label'] for r in legacy]
        query_times=[];pins={}
        for index,label in enumerate(labels):
            before=index==0; pids=[lid,wid,launch_aux] if before else [lid,wid,nid,launch_aux,native_aux]
            if before: start=tick+.25;end=tick+.28;done=tick+.29
            elif label=='pretermination':
                start=case['busy_sampling']['completed_perf_counter']+.02;end=start+.02;done=start+.03
            else:
                clock=case['memory_brackets'][label]['parent']['perf_counter']-.05
                start=clock+.06;end=clock+.08;done=clock+.09
            primary=[(lid,'launcher',None),(wid,'base_python',lid)]+([] if before else [(nid,'native',wid)])
            nodes=[]
            roles={pid:role for pid,role,_ in primary}
            for pid in sorted(pids):
                role=roles.get(pid);image_role=role or 'conhost'
                parent=999999 if pid==lid else lid if pid in (wid,launch_aux) else wid if pid==nid else nid
                nodes.append({**ref(pid),'parent_pid':parent,'job_member':True,'alive':True,'approved_known':role is not None,
                    'policy_role':role or 'unapproved','image':{'basename':'cmd.exe' if role=='native' else 'conhost.exe' if role is None else 'python.exe',
                    'sha256':executables[image_role],'normalized_path_sha256':paths[image_role],
                    'exact_path_matches':[image_role],'path_classification':'exact_executable',
                    'queried_from_retained_handle':True,'retained_identity_stable':True}})
            row={'label':label,'training_permitted':False,'processes':nodes,'observed_pids':sorted(pids),
                'started_perf_counter':start,'completed_perf_counter':end,'wall_seconds':end-start,
                'snapshot_observed_count':len(pids),'job_count_before':len(pids),'job_count_after':len(pids),
                'job_count_matches_before':True,'job_count_matches_after':True,'all_known_present':True,
                'census_complete':True,'errors':[],'truncated':False,'query_budget_exceeded':False,
                'unapproved_pids':sorted([launch_aux]+([] if before else [native_aux]))}
            pp=[{**ref(pid),'role':role,'parent_ref':None if parent is None else ref(parent),
                'frozen_image_sha256':executables[role],'frozen_path_sha256':paths[role]} for pid,role,parent in primary]
            aa=[]
            for owner_role,owner,child in [('launcher',lid,launch_aux)]+([] if before else [('native',nid,native_aux)]):
                pins[owner_role]={'owner_ref':ref(owner),'auxiliary_ref':ref(child),'frozen_image_sha256':executables['conhost'],'frozen_path_sha256':paths['conhost']}
                aa.append({**ref(child),'role':'console_auxiliary','parent_ref':ref(owner),'owner_role':owner_role,
                    'frozen_image_sha256':executables['conhost'],'frozen_path_sha256':paths['conhost']})
            decision={'label':label,'census_index':index,'decision_index':index,'training_permitted':False,
                'admitted':True,'requested_control':'training-v2','permitted_control':'training-v2',
                'primary_roles':pp,'auxiliary_roles':aa,'admitted_pids':sorted(pids),'rejected_pids':[],
                'rejections':[],'errors':[],'pinned_auxiliaries':copy.deepcopy(pins),
                'started_perf_counter':start,'completed_perf_counter':done,'wall_seconds':done-start,
                'job_count_before':len(pids),'job_count_after':len(pids),
                'held_liveness':[{**ref(pid),'job_member':True,'alive':True,'verified_perf_counter':end+.001*(n+1)} for n,pid in enumerate(sorted(pids))]}
            case['censuses'].append(row);case['role_decisions'].append(decision)
            q0,q1=start-.001,done+.001
            query_times.append({'kind':'held_role_census_and_liveness','started_perf_counter':q0,'completed_perf_counter':q1,
                'wall_seconds':q1-q0,'started_process_cpu_seconds':q0*.01,'completed_process_cpu_seconds':q1*.01,'parent_process_cpu_seconds':(q1-q0)*.01})
        # Only the held-overhead snapshot is a plain raw Toolhelp query now.
        case['parent_query_costs']=[q for q in case['parent_query_costs'] if q['kind']!='Toolhelp_process_tree_snapshot' or tick+4.7<=q['started_perf_counter']<=tick+5.1 and mode=='healthy']
        case['parent_query_costs'].extend(query_times);case['parent_query_costs'].sort(key=lambda q:q['started_perf_counter'])
        for window in case.get('held_parent_overhead_windows',[]):
            a,b=window['started_perf_counter'],window['completed_perf_counter']
            window['query_cost_index_start']=sum(q['completed_perf_counter']<a for q in case['parent_query_costs'])
            window['query_cost_index_end']=sum(q['completed_perf_counter']<=b for q in case['parent_query_costs'])
        for label,stage in case['stages'].items():
            stage.update(provider_guard=auditor.provider_expected(),stage_ready_perf_counter=case['memory_brackets'][label]['self_before']['perf_counter']-.02)
        if mode=='import_fail':
            case['import_failure_receipt'].update(missing_module='training_observer_v2_missing_dependency_'+case['nonce'],
                import_started_perf_counter=tick+1.2,failure_perf_counter=tick+1.3,provider_guard=auditor.provider_expected())
        else:
            case['stages']['postimport'].update(import_started_perf_counter=tick+1.2,import_completed_perf_counter=tick+1.8)
            if mode=='healthy':case['healthy_completion']['provider_guard']=auditor.provider_expected()
            else:
                for key in ('busy_ready','busy_first_operation'):case[key]['provider_guard']=auditor.provider_expected()
        count={'healthy':12,'timeout':11,'private_cap':11,'import_fail':3}[mode]
        for index,(name,command,label,di) in enumerate(auditor.CONTROL_PLAN[:count]):
            if label=='before_native':emitted=tick+.35
            else:
                before=case['memory_brackets'][label]['self_before']['perf_counter']
                emitted=before+(.092 if command=='parent-sampled' else .16 if command=='continue' else .18)
                if label=='postupdate' and mode=='healthy' and command=='continue':emitted=tick+5.2
            value={'nonce':case['nonce'],'role':'controller','pid':999998,'command':command,'purpose':auditor.CONTROL_PURPOSE,
                'training_v2_authorized':True,'role_policy_admitted':True,'role_decision_index':di,'role_decision_label':label,
                'control_index':index,'emitted_perf_counter':emitted}
            case['controller_controls'].append({'filename':name,**value})
            case['worker_controls'].append({'nonce':case['nonce'],'role':'worker','pid':wid,'filename':name,
                'control_envelope':copy.deepcopy(value),'accepted_perf_counter':emitted+.001,'next_control_index':index+1})
        case['cleanup']['exit_codes'].extend([{**ref(pid),'exit_code':0 if mode=='healthy' else 0xE003} for pid in (launch_aux,native_aux)])


class TrainingAuditorTests(unittest.TestCase):
    def run_audit(self,data,optional=True):
        report,protocol,freeze,sources,deps=data
        return auditor.audit(report,protocol,freeze,protocol_sha256=auditor.PROTOCOL_SHA256 or '1'*64,freeze_sha256='d'*64,
            actual_source_sha256=sources,actual_dependency_sha256=deps,
            actual_review_tools_sha256=freeze['review_tools_sha256'],launch_sha256='c'*64 if optional else None,
            base_python_sha256='f'*64 if optional else None,native_sha256='e'*64 if optional else None,conhost_sha256='7'*64 if optional else None,
            actual_model_assets=copy.deepcopy(auditor.ASSETS) if optional else None)
    def rejects(self,mutation,label):
        data=fixture(); mutation(data); result=self.run_audit(data)
        self.assertFalse(result['passed'],label)
        self.assertTrue(any(label in x for x in result['failures']),result['failures'])
    def test_complete_synthetic_receipts(self):
        result=self.run_audit(fixture()); self.assertTrue(result['passed'],result['failures'])
        self.assertEqual(result['unperformed_optional_file_checks'],['raw_controller_and_worker_receipt_files'])
    def test_optional_file_hashes_are_explicit(self):
        result=self.run_audit(fixture(),False); self.assertTrue(result['passed'],result['failures'])
        self.assertEqual(len(result['unperformed_optional_file_checks']),6)
    def test_protocol_and_file_hash_mutations(self):
        for mutate,label in [
            (lambda d:d[1]['config'].update(seed=True),'fixed_numeric_protocol'),
            (lambda d:d[1]['cases_in_order'].reverse(),'declared_case_order'),
            (lambda d:d[2].update(protocol_sha256='0'*64),'protocol_hash_chain'),
            (lambda d:d[3].update({auditor.SOURCE_PATHS[0]:'0'*64}),'actual_source_file_hashes'),
            (lambda d:d[4].update({auditor.DEPENDENCY_PATHS[0]:'0'*64}),'actual_dependency_file_hashes'),
            (lambda d:d[0]['model_assets']['model.safetensors'].update(sha256='0'*64),'pinned_model_assets_metadata')]:
            with self.subTest(label=label): self.rejects(mutate,label)
    def test_identity_OS_image_and_native_mutations(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][0]['worker_identity']['self_receipt'].update(nonce='0'*64),'nonce_role_actual_pid'),
            (lambda d:d[0]['cases'][0]['worker_identity']['os_image'].update(sha256='c'*64),'OS_image_hash_path'),
            (lambda d:d[0]['cases'][0]['worker_identity']['os_image'].update(queried_from_retained_handle=False),'OS_image_hash_path'),
            (lambda d:d[0]['cases'][0]['launcher']['os_image'].update(creation_filetime=999),'retained_identity'),
            (lambda d:d[0]['cases'][0]['worker_identity']['verified_ancestry'][0].update(parent_pid=999),'parent_creation_order'),
            (lambda d:d[0]['cases'][0]['native_descendant']['os_identity'].update(parent_pid=999),'native_direct_descendant_identity'),
            (lambda d:d[0]['cases'][0]['native_descendant']['launch_receipt'].update(shell=True),'native_command_flags')]:
            with self.subTest(label=label): self.rejects(mutate,label)
    def test_real_training_contract_mutations(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][0]['stages']['preimport'].update(torch_imported=True),'no_ML_before_release'),
            (lambda d:d[0]['cases'][0]['stages']['postload']['model'].update(schedule=[[0,1],[2,3]]),'pinned_model_training_schedule'),
            (lambda d:d[0]['cases'][0]['stages']['postload']['model'].update(trust_remote_code=True),'offline_deterministic_loader'),
            (lambda d:d[0]['cases'][0]['stages']['postload']['model']['model_load_timing'].update(started_perf_counter=0),'load_nested_in_preparation'),
            (lambda d:d[0]['cases'][0]['stages']['postupdate']['operation']['optimizer'].update(fused=True),'fixed_dense_AdamW'),
            (lambda d:d[0]['cases'][0]['stages']['postupdate']['operation']['loop'].update(steps_completed=3),'exact_two_updates'),
            (lambda d:d[0]['cases'][0]['stages']['postupdate']['operation']['loop'].update(preupdate_batch_losses_recorded_after_updates=[1,float('nan')]),'finite_loss'),
            (lambda d:d[0]['cases'][0]['stages']['postupdate']['operation']['final_validity']['optimizer_counters'].__setitem__(1,1),'moment_counters'),
            (lambda d:d[0]['cases'][0]['stages']['postupdate']['operation'].update(final_parameter_sha256='2'*64),'parameter_change')]:
            with self.subTest(label=label): self.rejects(mutate,label)
    def test_memory_bracket_and_allocation_mutations(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][0]['memory_brackets']['preimport']['parent'].update(creation_filetime=999),'actual_interpreter_identity'),
            (lambda d:d[0]['cases'][0]['memory_brackets']['postload']['comparison'].update(passed=False),'independent_memory_bracket'),
            (lambda d:d[0]['cases'][0]['allocation_check']['parent_deltas_bytes'].update(private_bytes=0),'independent_allocation_delta'),
            (lambda d:d[0]['cases'][0]['stages']['allocated'].update(manual_allocation_bytes=0),'allocated_stage_bytes')]:
            with self.subTest(label=label): self.rejects(mutate,label)
    def test_query_and_snapshot_mutations(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][0]['parent_query_costs'].pop(1),'every_parent_sample_has_cost_record'),
            (lambda d:d[0]['cases'][0]['parent_query_costs'][0].update(parent_process_cpu_seconds=100),'query_CPU_recomputed'),
            (lambda d:d[0]['cases'][0]['censuses'][0]['observed_pids'].append(999),'exact_three_or_five_unique_observed'),
            (lambda d:d[0]['cases'][0]['censuses'][0]['processes'][1].update(alive=False),'held_same_live_job'),
            (lambda d:d[0]['cases'][0]['censuses'][0]['processes'][1].update(parent_pid=999),'primary_direct_parent_graph')]:
            with self.subTest(label=label): self.rejects(mutate,label)
    def test_held_overhead_window_mutations(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][0]['held_parent_overhead_windows'].reverse(),'fixed_off_on_overhead_windows'),
            (lambda d:d[0]['cases'][0]['held_parent_overhead_windows'][1].update(sample_index_end=0),'overhead_slice_indices'),
            (lambda d:d[0]['cases'][0]['held_parent_overhead_windows'][0].update(parent_native_cpu_delta_seconds=1),'overhead_CPU_recomputed'),
            (lambda d:d[0]['cases'][0]['held_parent_overhead_windows'][0].update(parent_native_cpu_start_seconds=1000,parent_native_cpu_end_seconds=1000),'overhead_native_CPU_clock'),
            (lambda d:d[0]['cases'][0].update(healthy_memory_limit_disabled=False),'healthy_no_false_termination')]:
            with self.subTest(label=label): self.rejects(mutate,label)
    def test_busy_deadline_cap_and_no_extra_update_mutations(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][1].update(busy_deadline_perf_counter=0),'fixed_1point5s_deadline'),
            (lambda d:d[0]['cases'][1]['busy_first_operation'].update(extra_optimizer_steps=1),'no_extra_updates'),
            (lambda d:d[0]['cases'][1]['busy_sampling'].update(native_cpu_delta_seconds=0),'busy_CPU_delta_recomputed'),
            (lambda d:d[0]['cases'][1]['pretermination_live_members'][0].update(alive=False),'both_live_before_termination'),
            (lambda d:d[0]['cases'][2].update(actual_interpreter_private_limit_bytes=0),'postupdate_sampled_private_limit'),
            (lambda d:d[0]['cases'][2].update(allocation_ready_to_termination_seconds=0),'cap_response_recomputed')]:
            with self.subTest(label=label): self.rejects(mutate,label)
    def test_precise_failure_controls_and_cleanup_mutations(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][3]['prehandshake_control'].update(exit_code=1),'exact_prehandshake_control'),
            (lambda d:d[0]['cases'][3]['cleanup']['exit_codes'][0].update(exit_code=38),'precise_exit37'),
            (lambda d:d[0]['cases'][4]['import_failure_receipt'].update(missing_module='anything'),'precise_import_failure38'),
            (lambda d:d[0]['cases'][4]['import_failure_receipt'].update(transformers_imported=True),'precise_import_failure38'),
            (lambda d:d[0]['cases'][4]['cleanup']['exit_codes'][1].update(exit_code=1),'precise_actual_and_launcher_exit38'),
            (lambda d:d[0]['cases'][0]['cleanup'].update(job_active_count=1),'job_zero'),
            (lambda d:d[0]['cases'][0]['cleanup']['exit_codes'].pop(),'all_retained_exit_identities'),
            (lambda d:d[0]['cases'][0]['cleanup'].update(started_perf_counter=0),'within_case_clock')]:
            with self.subTest(label=label): self.rejects(mutate,label)
    def test_failed_report_is_never_upgraded(self):
        self.rejects(lambda d:d[0].update(passed=False),'reported_acceptance_pass_not_laundered')
        self.rejects(lambda d:d[0]['cases'][0].update(error='retained actual failure',passed=False),'no_hidden_failure')
    def test_shifted_cleanup_and_snapshot_intervals_rejected(self):
        def early_healthy(d):
            c=d[0]['cases'][0]; tick=c['started_perf_counter']
            c['cleanup'].update(started_perf_counter=tick+6.16,completed_perf_counter=tick+6.26,wall_seconds=0.1)
        def early_import(d):
            c=d[0]['cases'][4]; tick=c['started_perf_counter']
            c['cleanup'].update(started_perf_counter=tick+1.11,completed_perf_counter=tick+1.21,wall_seconds=0.1)
        self.rejects(early_healthy,'cleanup_after_all_known_live')
        self.rejects(early_import,'precise_import_failure_after_authorization')
        self.rejects(lambda d:d[0]['cases'][0]['censuses'][1].update(started_perf_counter=d[0]['cases'][0]['started_perf_counter']+3),
            'bounded_clock_span')
        def early_images(d):
            c=d[0]['cases'][0]; c['worker_identity']['os_image']['verified_perf_counter']=c['started_perf_counter']+0.001
            c['launcher']['os_image']['verified_perf_counter']=c['started_perf_counter']+0.002
        self.rejects(early_images,'image_query_clock')
    def test_partial_receipts_fail_without_crash(self):
        for report in ({},{'cases':[{}]},{'cases':None}):
            data=list(fixture()); data[0]=report
            self.assertFalse(self.run_audit(data)['passed'])
    def test_duplicate_nonfinite_and_oversize_JSON_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'receipt.json'
            for raw in [b'{"a":1,"a":2}',b'{"x":NaN}',b' '*1048577,b'']:
                path.write_bytes(raw)
                with self.assertRaises(ValueError): auditor.bounded(path)

    def test_four_executable_files_paths_and_review_custody(self):
        for mutate,label in [
            (lambda d:d[0]['executables_sha256'].update(conhost='0'*64),'four_exact_file_and_opaque_path_freeze'),
            (lambda d:d[0]['cases'][0]['executable_path_sha256'].update(base_python='0'*64),'case_exact_executable_freeze'),
            (lambda d:d[2]['review_tools_sha256'].update({auditor.REVIEW_PATHS[0]:'0'*64}),'actual_review_tool_file_hashes'),
            (lambda d:d[0]['cases'][0]['worker_identity']['self_receipt']['self_executable'].update(sha256='f'*64),'separate_self_launcher_OS_base_role')]:
            with self.subTest(label=label):self.rejects(mutate,label)

    def test_raw_roles_cannot_promote_same_image_or_unregistered_owner(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][0]['censuses'][1]['processes'].append(copy.deepcopy(d[0]['cases'][0]['censuses'][1]['processes'][1])),'exact_three_or_five_unique_observed'),
            (lambda d:d[0]['cases'][0]['censuses'][1]['processes'][-1].update(parent_pid=d[0]['cases'][0]['worker_identity']['self_receipt']['pid']),'one_exact_console_for_native'),
            (lambda d:d[0]['cases'][0]['role_decisions'][1]['auxiliary_roles'][0]['parent_ref'].update(creation_filetime=999),'independently_reconstructed_roles'),
            (lambda d:d[0]['cases'][0]['role_decisions'][1]['pinned_auxiliaries']['launcher']['auxiliary_ref'].update(creation_filetime=999),'independently_reconstructed_roles')]:
            with self.subTest(label=label):self.rejects(mutate,label)

    def test_raw_console_image_file_path_and_pin_are_independent(self):
        for field,value,label in [
            ('sha256','0'*64,'one_exact_console_for_launcher'),
            ('normalized_path_sha256','0'*64,'one_exact_console_for_launcher'),
            ('basename','cmd.exe','independent_exact_image_role'),
            ('retained_identity_stable',False,'retained_OS_image_complete'),
            ('exact_path_matches',[],'one_exact_console_for_launcher')]:
            self.rejects(lambda d:d[0]['cases'][0]['censuses'][0]['processes'][-1]['image'].update({field:value}),label)

    def test_census_liveness_counts_and_resource_deadlines(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][0]['censuses'][1].update(truncated=True),'complete_no_error_inventory'),
            (lambda d:d[0]['cases'][0]['censuses'][1].update(job_count_after=9),'two_raw_job_counts'),
            (lambda d:d[0]['cases'][0]['role_decisions'][1]['held_liveness'].pop(),'complete_post_census_held_liveness'),
            (lambda d:d[0]['cases'][0]['role_decisions'][1]['held_liveness'][0].update(alive=False),'post_census_liveness_clock'),
            (lambda d:d[0]['cases'][0]['role_decisions'][1]['held_liveness'][0].update(verified_perf_counter=0),'post_census_liveness_clock'),
            (lambda d:d[0]['cases'][0].update(case_deadline_perf_counter=999),'nonrenewable_case_suite_deadlines')]:
            with self.subTest(label=label):self.rejects(mutate,label)

    def test_controls_require_exact_current_decision_and_worker_identity(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][0]['controller_controls'].pop(),'exact_mode_control_count'),
            (lambda d:d[0]['cases'][0]['controller_controls'][1].update(role_decision_index=0),'fixed_envelope_authority'),
            (lambda d:d[0]['cases'][0]['controller_controls'][1].update(training_v2_authorized=False),'fixed_envelope_authority'),
            (lambda d:d[0]['cases'][0]['worker_controls'][0].update(pid=999),'nonce_role_PID'),
            (lambda d:d[0]['cases'][0]['worker_controls'][0]['control_envelope'].update(purpose='other'),'exact_worker_custody_of_emitted_payload'),
            (lambda d:d[0]['cases'][0]['role_decisions'][0].update(permitted_control='finish'),'exact_current_role_decision')]:
            with self.subTest(label=label):self.rejects(mutate,label)

    def test_controls_have_independent_emit_accept_action_clock_chain(self):
        for mutate,label in [
            (lambda d:d[0]['cases'][0]['controller_controls'][0].update(emitted_perf_counter=0),'monotonic_decision_emit_accept_chain'),
            (lambda d:d[0]['cases'][0]['worker_controls'][0].update(accepted_perf_counter=0),'monotonic_decision_emit_accept_chain'),
            (lambda d:d[0]['cases'][0]['worker_controls'][1].update(accepted_perf_counter=d[0]['cases'][0]['started_perf_counter']+1.2),'held_bracket_release_chronology'),
            (lambda d:d[0]['cases'][0]['native_descendant']['launch_receipt'].update(launch_started_perf_counter=0),'native_launch_after_accepted_permission'),
            (lambda d:d[0]['cases'][0]['stages']['postimport'].update(import_started_perf_counter=0),'import_after_authorized_release'),
            (lambda d:d[0]['cases'][0]['stages']['preimport'].update(stage_ready_perf_counter=float('nan')),'ready_before_bracket')]:
            with self.subTest(label=label):self.rejects(mutate,label)

    def test_provider_audit_probe_never_becomes_native_sandbox_proof(self):
        for field,value in [('installed',False),('native_network_sandbox',True),('external_providers_permitted',True),
                            ('synthetic_probe_denials',True),('unexpected_denied_events',['socket.connect']),
                            ('denied_audit_events',[])]:
            self.rejects(lambda d:d[0]['cases'][0]['stages']['preimport']['provider_guard'].update({field:value}),'local_Python_only_guard')

    def test_busy_cleanup_requires_all_consoles_and_held_python_exit_code(self):
        self.rejects(lambda d:d[0]['cases'][1]['cleanup']['exit_codes'].pop(),'all_retained_exit_identities')
        self.rejects(lambda d:d[0]['cases'][1]['cleanup']['exit_codes'][0].update(exit_code=0),'precise_busy_held_Python_termination_codes')
        data=list(fixture())
        for case in data[0]['cases'][1:3]:
            for row in case['cleanup']['exit_codes']:
                if row['pid'] not in {case['launcher']['pid'],case['worker_identity']['self_receipt']['pid']}:
                    row['exit_code']=123
        self.assertTrue(self.run_audit(data)['passed'])

    def test_saved_raw_controls_are_required_by_file_entrypoint(self):
        report,protocol,freeze,_,_=fixture()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in (*auditor.SOURCE_PATHS,*auditor.DEPENDENCY_PATHS,*auditor.REVIEW_PATHS):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
            for names,freeze_key,report_key in [
                (auditor.SOURCE_PATHS,'new_source_files_sha256','source_sha256'),
                (auditor.DEPENDENCY_PATHS,'frozen_dependency_files_sha256','frozen_dependencies_sha256'),
                (auditor.REVIEW_PATHS,'review_tools_sha256','review_tools_sha256')]:
                freeze[freeze_key]={name:auditor.sha((root/name).read_bytes()) for name in names}
                report[report_key]=dict(freeze[freeze_key])
            pp,fp,rp=[root/name for name in ('protocol.json','freeze.json','report.json')]
            pp.write_text(json.dumps(protocol),encoding='utf-8')
            freeze['protocol_sha256']=report['protocol_sha256']=auditor.sha(pp.read_bytes())
            fp.write_text(json.dumps(freeze),encoding='utf-8');report['implementation_sha256']=auditor.sha(fp.read_bytes())
            rp.write_text(json.dumps(report),encoding='utf-8')
            for case in report['cases']:
                folder=root/case['id'];folder.mkdir()
                for row,ack in zip(case['controller_controls'],case['worker_controls']):
                    (folder/row['filename']).write_text(json.dumps({k:v for k,v in row.items() if k!='filename'}),encoding='utf-8')
                    (folder/row['filename'].replace('.json','-accepted.json')).write_text(json.dumps(ack),encoding='utf-8')
            def run():
                with mock.patch.object(auditor,'PROTOCOL_SHA256',None), mock.patch.object(auditor,'SOURCE_HASHES',None), mock.patch.object(auditor,'DEPENDENCY_HASHES',None):
                    return auditor.audit_files(rp,pp,fp,root=root)
            self.assertTrue(run()['passed'],run()['failures'])
            target=root/report['cases'][0]['id']/'create-native.json'
            old=target.read_text(encoding='utf-8');value=json.loads(old);value['purpose']='different raw file'
            target.write_text(json.dumps(value),encoding='utf-8')
            self.assertFalse(run()['passed'])
            target.write_text(old,encoding='utf-8')
            extra=root/report['cases'][1]['id']/'finish.json';extra.write_text(old,encoding='utf-8')
            self.assertFalse(run()['passed'])
            extra.unlink();target.unlink()
            self.assertFalse(run()['passed'])


if __name__=='__main__': unittest.main()
