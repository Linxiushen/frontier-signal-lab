"""Independent synthetic duty receipts and mutations; no producer/OS/ML calls."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from scripts import audit_observer_duty as auditor

def provider_receipt(phase,tick,budget=1):
    """Wholly synthetic saved metadata; no hook, socket or provider import."""
    source={'package_relative_path':auditor.PROVIDER_RELATIVE_PATH,'sha256':auditor.PROVIDER_SOURCE_SHA256,
        'normalized_path_sha256':'8'*64}
    events=[]
    if phase not in ('preimport','injected_import'):
        events=[{'event_index':0,'event':'socket.bind','perf_counter':tick+1.5,'phase':'import',
            'decision':'allowed_local_capability_probe','socket_family_code':23,'socket_type_code':1,'socket_protocol':0,
            'endpoint':{'shape':'tuple2','host_kind':'exact_ipv6_loopback','port_kind':'ephemeral_zero','address_logged':False},
            'frames':[{**source,'function':function,'line':line} for function,line in [('_has_ipv6',127),('<module>',137)]],
            'frame_scope':'contiguous_initial_urllib3_frames','frame_boundary':'outside_selected_package',
            'frames_scanned_count':3,'saved_frame_count':2,'frames_truncated':False,'source_hashes_complete':True,
            'diagnostic_errors':[]}]
    return {'installed':True,'python_audit_only':True,'native_network_sandbox':False,'external_providers_permitted':False,
        'synthetic_probe_denials':1,'unexpected_denied_events':[],'denied_audit_events':list(auditor.PROVIDER_EVENTS),
        'policy_id':auditor.PROVIDER_POLICY_ID,'phase':phase,'provider_source':source,'allowed_local_probe_budget':budget,
        'allowed_local_probe_count':len(events),'diagnostic_event_limit':4,'diagnostic_overflow_count':0,
        'observed_event_count':len(events),'diagnostic_events':events}



class ProviderReplayTests(unittest.TestCase):
    def replay(self,value,phase='postimport',budget=1):
        return auditor.replay_provider(value,{'provider_source_sha256':auditor.PROVIDER_SOURCE_SHA256,
            'provider_source_path_sha256':'8'*64},phase,budget,100,120,(101.2,101.8))
    def rejects(self,mutate,part):
        value=provider_receipt('postimport',100);mutate(value)
        try:checks=self.replay(value)
        except (KeyError,TypeError,ValueError,AttributeError,IndexError):return
        self.assertTrue(any(not c['passed'] and part in c['check'] for c in checks),checks)
    def test_exact_synthetic_guard_and_all_saved_phases(self):
        for phase in ('preimport','postimport','postload','train','postupdate','complete'):
            checks=self.replay(provider_receipt(phase,100),phase)
            self.assertTrue(all(c['passed'] for c in checks),checks)
    def test_no_socket_endpoint_or_phase_variation_is_accepted(self):
        for key,value in [('event','socket.connect'),('event_index',True),('phase','train'),
            ('decision','denied'),('socket_family_code',2),('socket_type_code',True),('socket_protocol',6)]:
            with self.subTest(key=key):self.rejects(lambda v:v['diagnostic_events'][0].update({key:value}),'one_exact_import_phase')
        for key,value in [('shape','tuple4'),('host_kind','other'),('port_kind','nonzero_integer'),('address_logged',True)]:
            with self.subTest(key=key):self.rejects(lambda v:v['diagnostic_events'][0]['endpoint'].update({key:value}),'exact_loopback')
    def test_source_frames_are_exact_bounded_and_private_paths_not_claimed(self):
        for key,value in [('frame_scope','whole_stack'),('frame_boundary','stack_end'),('frames_scanned_count',4),
            ('saved_frame_count',True),('frames_truncated',True),('source_hashes_complete',False),('diagnostic_errors',['bad'])]:
            with self.subTest(key=key):self.rejects(lambda v:v['diagnostic_events'][0].update({key:value}),'complete_two_frame_prefix')
        for index in (0,1):
            for key,value in [('sha256','0'*64),('normalized_path_sha256','0'*64),('function','wrong'),('line',128),('package_relative_path','urllib3/other.py')]:
                with self.subTest(index=index,key=key):self.rejects(lambda v:v['diagnostic_events'][0]['frames'][index].update({key:value}),'exact_pinned_caller')
    def test_denial_overflow_counter_and_unknown_fields_cannot_be_laundered(self):
        for key,value in [('synthetic_probe_denials',True),('observed_event_count',0),('allowed_local_probe_budget',2),
            ('allowed_local_probe_count',0),('diagnostic_event_limit',5),('diagnostic_overflow_count',1)]:
            with self.subTest(key=key):self.rejects(lambda v:v.update({key:value}),'exact_one_synthetic_probe')
        for key,value in [('unexpected_denied_events',['socket.bind']),('external_providers_permitted',True),('native_network_sandbox',True),('arbitrary_path','private')]:
            with self.subTest(key=key):self.rejects(lambda v:v.update({key:value}),'closed_policy')
        self.rejects(lambda v:v['diagnostic_events'].clear(),'no_unrecorded_dropped')
        self.rejects(lambda v:v['diagnostic_events'].append(copy.deepcopy(v['diagnostic_events'][0])),'no_unrecorded_dropped')
    def test_event_is_contained_in_real_import_clock(self):
        self.rejects(lambda v:v['diagnostic_events'][0].update(perf_counter=100),'inside_actual_ML_import_interval')
        self.rejects(lambda v:v['diagnostic_events'][0].update(perf_counter=0),'inside_case_and_before_snapshot')


MIB=1048576
LEGACY_STAGES=('preimport','postimport','postload','postupdate','allocated')
LEGACY_CASES=tuple((name,'healthy',0) for name,enabled in auditor.CASES)
LEGACY_CONTROL_PLAN=[('create-native.json','create-native','before_native',0)]
for _index,_stage in enumerate(LEGACY_STAGES,1):
    LEGACY_CONTROL_PLAN.extend([(_stage+'-parent-done.json','parent-sampled',_stage,_index),(_stage+'-continue.json','continue',_stage,_index)])
LEGACY_CONTROL_PLAN.append(('finish.json','finish','allocated',5))
def legacy_fixture():
    sources=dict(auditor.SOURCE_HASHES or {p:'a'*64 for p in auditor.SOURCE_PATHS})
    dependencies=dict(auditor.DEPENDENCY_HASHES or {p:'b'*64 for p in auditor.DEPENDENCY_PATHS})
    pin=auditor.PROTOCOL_SHA256 or '1'*64
    protocol={'schema_version':1,'experiment_id':auditor.EXPERIMENT,'predeclared_at':'2026-10-16T00:00:00+00:00',
        'source_paths':list(auditor.SOURCE_PATHS),'frozen_dependency_paths':list(auditor.DEPENDENCY_PATHS),
        'review_tool_paths':list(auditor.REVIEW_PATHS),'config':dict(auditor.CONFIG),'cases_in_order':[{'id':i,'mode':m,'manual_allocation_bytes':n} for i,m,n in LEGACY_CASES],
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
    for index,(case_id,mode,allocation) in enumerate(LEGACY_CASES):
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
            labels=('preimport',) if mode=='import_fail' else LEGACY_STAGES
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
    upgrade_legacy_fixture(report,protocol,freeze)
    return report,protocol,freeze,sources,dependencies


def upgrade_legacy_fixture(report, protocol, freeze):
    """Synthetic held OS and independent sender/receiver custody, never native calls."""
    executables = {'launcher':'c'*64, 'base_python':'f'*64, 'native':'e'*64, 'conhost':'7'*64}
    protocol['control_plan']=[{'filename':name,'command':command,'decision_label':label,'decision_index':index}
        for name,command,label,index in LEGACY_CONTROL_PLAN]
    protocol['provider_custody']={'denied_python_audit_events':list(auditor.PROVIDER_EVENTS),
        'external_providers_permitted':False,'native_network_sandbox':False,'synthetic_probe_denials':1,
        'unexpected_denied_events_allowed':0,'policy_id':auditor.PROVIDER_POLICY_ID,
        'provider_config':dict(auditor.PROVIDER_CONFIG),'provider_source_relative_path':auditor.PROVIDER_RELATIVE_PATH,
        'provider_source_sha256':auditor.PROVIDER_SOURCE_SHA256,'frame_scope':'contiguous_initial_urllib3_frames'}
    paths = {role:str(index)*64 for index,role in enumerate(executables, 1)}
    freeze.update(executables_sha256=executables, executable_path_sha256=paths,
        provider_source_sha256=auditor.PROVIDER_SOURCE_SHA256,provider_source_path_sha256='8'*64)
    report.update(executables_sha256=copy.deepcopy(executables),executable_path_sha256=copy.deepcopy(paths),
        provider_source_sha256=auditor.PROVIDER_SOURCE_SHA256,provider_source_path_sha256='8'*64,
        provider_policy_id=auditor.PROVIDER_POLICY_ID)
    for case in report['cases']:
        tick, mode = case['started_perf_counter'], case['mode']
        case.update(executables_sha256=copy.deepcopy(executables),executable_path_sha256=copy.deepcopy(paths),
            case_deadline_perf_counter=min(tick+60,280.0),suite_deadline_perf_counter=280.0,
            provider_source_sha256=auditor.PROVIDER_SOURCE_SHA256,provider_source_path_sha256='8'*64,
            cleanup_exact_retained_identity_set=True,control_custody_verified=True,censuses=[],role_decisions=[],
            controller_controls=[],worker_controls=[])
        if mode == 'prehandshake_fail':
            continue
        case['provider_custody_verified']=True
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
                'admitted':True,'requested_control':'training-v3','permitted_control':'training-v3',
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
            stage.update(provider_guard=provider_receipt(label,tick,0 if mode=='import_fail' else 1),
                stage_ready_perf_counter=case['memory_brackets'][label]['self_before']['perf_counter']-.02)
        if mode=='import_fail':
            case['import_failure_receipt'].update(missing_module='training_observer_v3_missing_dependency_'+case['nonce'],
                import_started_perf_counter=tick+1.2,failure_perf_counter=tick+1.3,provider_guard=provider_receipt('injected_import',tick,0))
        else:
            case['stages']['postimport'].update(import_started_perf_counter=tick+1.2,import_completed_perf_counter=tick+1.8)
            if mode=='healthy':case['healthy_completion']['provider_guard']=provider_receipt('complete',tick)
            else:
                for key in ('busy_ready','busy_first_operation'):case[key]['provider_guard']=provider_receipt('busy',tick)
        count={'healthy':12,'timeout':11,'private_cap':11,'import_fail':3}[mode]
        for index,(name,command,label,di) in enumerate(LEGACY_CONTROL_PLAN[:count]):
            if label=='before_native':emitted=tick+.35
            else:
                before=case['memory_brackets'][label]['self_before']['perf_counter']
                emitted=before+(.092 if command=='parent-sampled' else .16 if command=='continue' else .18)
                if label=='postupdate' and mode=='healthy' and command=='continue':emitted=tick+5.2
            value={'nonce':case['nonce'],'role':'controller','pid':999998,'command':command,'purpose':auditor.CONTROL_PURPOSE,
                'training_v3_authorized':True,'role_policy_admitted':True,'role_decision_index':di,'role_decision_label':label,
                'control_index':index,'emitted_perf_counter':emitted}
            case['controller_controls'].append({'filename':name,**value})
            case['worker_controls'].append({'nonce':case['nonce'],'role':'worker','pid':wid,'filename':name,
                'control_envelope':copy.deepcopy(value),'accepted_perf_counter':emitted+.001,'next_control_index':index+1})
        case['cleanup']['exit_codes'].extend([{**ref(pid),'exit_code':0 if mode=='healthy' else 0xE003} for pid in (launch_aux,native_aux)])



def fixture():
    report,protocol,freeze,sources,deps=legacy_fixture()
    protocol['config']=dict(auditor.CONFIG)
    protocol['cases_in_order']=[{'id':name,'sampling_enabled':enabled} for name,enabled in auditor.CASES]
    protocol['control_plan']=[{'filename':f,'command':c,'decision_label':l,'decision_index':i} for f,c,l,i in auditor.CONTROL_PLAN]
    protocol.update(control_purpose=auditor.CONTROL_PURPOSE,role_requested_control='observer-duty',stages=list(auditor.STAGES),provider_stage_phases=dict(auditor.PHASES))
    protocol['model']={'id':auditor.MODEL_ID,'revision':auditor.MODEL_REVISION,'assets':copy.deepcopy(auditor.ASSETS),'planned_model_loads':4,'planned_optimizer_updates':64}
    protocol['training']={'seed':503,'steps':16,'schedule':auditor.schedule(),'schedule_sha256':auditor.sha(auditor.canonical(auditor.schedule()).encode()),
        'train_sha256':auditor.TRAIN_SHA256,'optimizer':dict(auditor.OPTIMIZER),'optimizer_state_entries_before_loop':0,
        'dense_only':True,'holdout_opened':False,'checkpoint_written':False}
    protocol['provider_custody']={'policy_id':auditor.PROVIDER_POLICY_ID,'provider_config':dict(auditor.PROVIDER_CONFIG),
        'provider_source_relative_path':auditor.PROVIDER_RELATIVE_PATH,'provider_source_sha256':auditor.PROVIDER_SOURCE_SHA256,
        'frame_scope':'contiguous_initial_urllib3_frames','native_network_sandbox':False,'external_providers_permitted':False}
    report.update(planned_model_loads=4,planned_optimizer_updates=64)
    rename={'postload':'pretrain','postupdate':'postloop','allocated':'postvalidation'}
    for case,(_,enabled) in zip(report['cases'],auditor.CASES):
        tick=case['started_perf_counter'];case['sampling_enabled']=enabled
        case['case_deadline_perf_counter']=tick+60;case['suite_deadline_perf_counter']=340.0
        case['stages']={rename.get(label,label):value for label,value in case['stages'].items()}
        case['memory_brackets']={rename.get(label,label):value for label,value in case['memory_brackets'].items()}
        for label,stage in case['stages'].items():
            stage['stage']=label;stage['provider_guard']=provider_receipt(auditor.PHASES[label],tick)
        for row in case['censuses']:row['label']=rename.get(row['label'],row['label'])
        for row in case['role_decisions']:
            row['label']=rename.get(row['label'],row['label']);row['requested_control']=row['permitted_control']='observer-duty'
        for rows in (case['controller_controls'],case['worker_controls']):
            for row in rows:
                for old,new in rename.items():row['filename']=row['filename'].replace(old,new)
                target=row['control_envelope'] if 'control_envelope' in row else row
                target.pop('training_v3_authorized',None);target['observer_duty_authorized']=True
                target['role_decision_label']=rename.get(target['role_decision_label'],target['role_decision_label'])
        model=case['stages']['pretrain']['model']
        model.update(optimizer_state_entries=0,optimizer_type='AdamW',optimizer=dict(auditor.OPTIMIZER),batch_shapes=[[2,65]]*16,
            model_load_started_perf_counter=tick+2.3,model_load_completed_perf_counter=tick+2.7)
        op=case['stages']['postloop'].pop('operation');loop=op['loop']
        loop.update(steps_completed=16,training_target_positions=2048,training_targets_per_second=2048/.6,
            preupdate_batch_losses_recorded_after_updates=[4.0+i*.01 for i in range(16)],time_control=None)
        def msg(**kw):return {'nonce':case['nonce'],'role':'worker','pid':case['worker_identity']['self_receipt']['pid'],**kw}
        case['loop_before']=msg(before_loop_perf_counter=tick+3.18,provider_guard=provider_receipt('train',tick))
        case['loop_after']=msg(after_loop_perf_counter=tick+3.82,loop=loop,provider_guard=provider_receipt('postupdate',tick))
        case['stages']['postvalidation']['validation']={'started_perf_counter':tick+5.3,'completed_perf_counter':tick+5.7,
            'final_validity':{'optimizer_counters':[16]*76,'final_parameter_gradient_moments_finite':True},
            'final_parameter_sha256':'3'*64,'no_holdout_evaluation':True,'no_checkpoint_written':True}
        case['stages']['postvalidation'].pop('manual_allocation_bytes',None)
        for field in ('held_parent_overhead_windows','parent_overhead_boundary','allocation_check','healthy_memory_limit_disabled','manual_allocation_bytes','mode'):
            case.pop(field,None)
        case['samples']=[case['memory_brackets'][label]['parent'] for label in auditor.STAGES]
        case['parent_query_costs']=[q for q in case['parent_query_costs'] if q['kind']!='Toolhelp_process_tree_snapshot' and
            (q['kind']!='actual_interpreter_memory_and_cpu_query' or any(q['started_perf_counter']<=v['perf_counter']<=q['completed_perf_counter'] for v in case['samples']))]
        for q in case['parent_query_costs']:
            if q['kind']=='actual_interpreter_memory_and_cpu_query':q['kind']='boundary_worker_memory_and_cpu'
        rows=[]
        if enabled:
            for index in range(24):
                clock=tick+3.205+index*.022
                sample=copy.deepcopy(case['samples'][2]);sample.update(perf_counter=clock+.001,native_cpu_seconds=1+index*.01)
                rows.append({'index':index,'query_started_perf_counter':clock,'query_completed_perf_counter':clock+.002,'sample':sample,
                    'snapshot_started_perf_counter':clock+.0025,'snapshot_completed_perf_counter':clock+.004,'snapshot_process_count':100})
        case['active_window']={'started_perf_counter':tick+3.15,'completed_perf_counter':tick+3.84,'wall_seconds':.69,
            'parent_native_cpu_start_seconds':1.0,'parent_native_cpu_end_seconds':1.1,'parent_native_cpu_delta_seconds':.1,
            'poll_count':24,'observations':rows}
        case['active_observation_indices']=list(range(24)) if enabled else []
        if enabled:
            stamps=[r['sample']['perf_counter'] for r in rows];start,end=tick+3.2,tick+3.8
            gap=max(b-a for a,b in zip([start]+stamps,stamps+[end]));qw=sum(r['query_completed_perf_counter']-r['query_started_perf_counter'] for r in rows);sw=sum(r['snapshot_completed_perf_counter']-r['snapshot_started_perf_counter'] for r in rows)
            case['training_memory']={'sampled_current_resident_max_bytes':max(r['sample']['memory']['resident_bytes'] for r in rows),
                'sampled_current_private_max_bytes':max(r['sample']['memory']['private_bytes'] for r in rows),
                'boundary':'lower bounds on process current readings during full dense loop, not backward/full peak or memory saving'}
            case['active_sampling']={'selected_count':24,'maximum_gap_including_boundaries_seconds':gap,'realized_samples_per_second':24/(end-start),
                'memory_cpu_query_wall_seconds':qw,'snapshot_wall_seconds':sw,'combined_query_wall_fraction':(qw+sw)/(end-start)}
        else:case['training_memory']=case['active_sampling']=None
        case['healthy_completion']['optimizer_steps']=16
        for row in case['prefinish_live_members']:row['verified_perf_counter']=tick+6.175
    report['paired_summary']={'valid':True,'all_four_trajectories_matched':True,'pairs':[
        {'off_case':'pair1_off','on_case':'pair1_on','exact_trajectory_matched':True,'on_off_wall_ratio':1.0},
        {'off_case':'pair2_off','on_case':'pair2_on','exact_trajectory_matched':True,'on_off_wall_ratio':1.0}],
        'geometric_mean_on_off_wall_ratio':1.0}
    return report,protocol,freeze,sources,deps


class DutyAuditorTests(unittest.TestCase):
    def run_audit(self,data,**kwargs):
        report,protocol,freeze,sources,deps=data
        return auditor.audit(report,protocol,freeze,protocol_sha256=auditor.PROTOCOL_SHA256 or '1'*64,freeze_sha256='d'*64,
            actual_source_sha256=sources,actual_dependency_sha256=deps,actual_review_tools_sha256=freeze['review_tools_sha256'],**kwargs)
    def rejects(self,mutate,label):
        data=fixture();mutate(data);result=self.run_audit(data)
        self.assertFalse(result['passed'],label);self.assertTrue(any(label in s for s in result['failures']),result['failures'])
    def test_complete_synthetic_ABBA_study(self):
        result=self.run_audit(fixture());self.assertTrue(result['passed'],result['failures'])
        self.assertGreater(result['check_count'],4000)

    def test_protocol_contract_mutations(self):
        changes=[('config','seed',504,'fixed_numeric'),('model','revision','bad','declared_model'),
            ('training','optimizer_state_entries_before_loop',1,'declared_fixed_dense'),
            ('provider_custody','native_network_sandbox',True,'declared_provider')]
        for section,key,value,label in changes:
            with self.subTest(section=section,key=key):self.rejects(lambda d:d[1][section].__setitem__(key,value),label)
        self.rejects(lambda d:d[1]['cases_in_order'].reverse(),'fixed_ABBA')
        self.rejects(lambda d:d[1].__setitem__('role_requested_control','training-v3'),'declared_control_stage')
        self.rejects(lambda d:d[1]['control_plan'].pop(),'fixed_control_plan')
        self.rejects(lambda d:d[1]['frozen_dependency_paths'].pop(),'exact_frozen_file_inventories')

    def test_frozen_hash_and_execution_chronology_mutations(self):
        for field,key,label in [('new_source_files_sha256',auditor.SOURCE_PATHS[0],'actual_sources'),
            ('frozen_dependency_files_sha256',auditor.DEPENDENCY_PATHS[0],'actual_dependencies'),
            ('review_tools_sha256',auditor.REVIEW_PATHS[0],'actual_review_tools')]:
            with self.subTest(field=field):self.rejects(lambda d:d[2][field].__setitem__(key,'0'*64),label)
        self.rejects(lambda d:d[0].__setitem__('implementation_sha256','0'*64),'implementation_hash_chain')
        self.rejects(lambda d:d[0].__setitem__('started_at','2026-10-15T00:00:00+00:00'),'predeclare_freeze_execution')
        self.rejects(lambda d:d[0].__setitem__('no_fallback',False),'Windows_only_no_fallback')
        self.rejects(lambda d:d[0].__setitem__('passed',False),'reported_failure_never_upgraded')

    def test_ABBA_fresh_workers_and_failure_custody(self):
        self.rejects(lambda d:d[0]['cases'][0].__setitem__('sampling_enabled',True),'exact_case_spec')
        self.rejects(lambda d:d[0]['cases'][1].__setitem__('nonce',d[0]['cases'][0]['nonce']),'four_fresh_nonces')
        self.rejects(lambda d:d[0]['cases'][0].__setitem__('worker_failure_receipt',{'error':'retained'}),'no_hidden_failure')
        self.rejects(lambda d:d[0]['cases'][0].__setitem__('outcome','timeout'),'no_hidden_failure')
        self.rejects(lambda d:d[0]['cases'][0].__setitem__('case_deadline_perf_counter',999),'nonrenewable_case_suite_deadlines')

    def test_training_fresh_state_shapes_fixed_steps_and_finiteness(self):
        for key,value,label in [('optimizer_state_entries',1,'fresh_AdamW'),('parameter_tensors',75,'fresh_AdamW'),
            ('batch_shapes',[[2,65]]*15,'fresh_AdamW'),('dtype','torch.float16','fixed_offline'),
            ('trust_remote_code',True,'fixed_offline'),('schedule',[[0,1]]*16,'pinned_model_data')]:
            with self.subTest(key=key):self.rejects(lambda d:d[0]['cases'][0]['stages']['pretrain']['model'].__setitem__(key,value),label)
        for key,value,label in [('steps_completed',15,'exact_sixteen'),('steps_completed',True,'exact_sixteen'),
            ('training_target_positions',256,'exact_sixteen'),('training_loop_cpu_seconds',-1,'exact_sixteen'),
            ('preupdate_batch_losses_recorded_after_updates',[1.0]*15,'finite_sixteen'),
            ('preupdate_batch_losses_recorded_after_updates',[float('nan')]*16,'finite_sixteen'),
            ('training_targets_per_second',0,'target_throughput')]:
            with self.subTest(key=key,value=value):self.rejects(lambda d:d[0]['cases'][0]['loop_after']['loop'].__setitem__(key,value),label)
        self.rejects(lambda d:d[0]['cases'][0]['stages']['postvalidation']['validation']['final_validity']['optimizer_counters'].__setitem__(2,15),'all_76_optimizer')

    def test_full_four_trajectory_parity_never_uses_tolerance(self):
        def initial(d):d[0]['cases'][1]['stages']['pretrain']['model']['initial_parameter_sha256']='4'*64
        def final(d):d[0]['cases'][1]['stages']['postvalidation']['validation']['final_parameter_sha256']='4'*64
        def loss(d):d[0]['cases'][2]['loop_after']['loop']['preupdate_batch_losses_recorded_after_updates'][7]+=1e-12
        for mutation in (initial,final,loss):
            with self.subTest(mutation=mutation.__name__):self.rejects(mutation,'all_four_initial_schedule_final_hashes_and_entire_loss_trajectories_exactly_equal')

    def test_loop_signal_identity_and_actual_clock_separation(self):
        for field in ('loop_before','loop_after'):
            for key,value in [('nonce','0'*64),('role','controller'),('pid',999)]:
                with self.subTest(field=field,key=key):self.rejects(lambda d:d[0]['cases'][0][field].__setitem__(key,value),field+':nonce_role_PID')
        self.rejects(lambda d:d[0]['cases'][0]['loop_before'].__setitem__('before_loop_perf_counter',999),'exact_before_full_loop_after')
        self.rejects(lambda d:d[0]['cases'][0]['stages']['postvalidation']['validation'].__setitem__('started_perf_counter',105.0),'final_validation_and_digest_outside')
        self.rejects(lambda d:d[0]['cases'][0]['loop_after']['loop'].__setitem__('training_loop_wall_seconds',1.0),'loop_wall_recomputed')

    def test_OFF_unknown_is_null_and_cannot_contain_active_queries(self):
        self.rejects(lambda d:d[0]['cases'][0].__setitem__('training_memory',0),'OFF_no_active_queries_and_unknown_memory_is_null')
        self.rejects(lambda d:d[0]['cases'][0].__setitem__('active_sampling',{}),'OFF_no_active_queries_and_unknown_memory_is_null')
        def observation(d):
            c=d[0]['cases'][0];r=copy.deepcopy(d[0]['cases'][1]['active_window']['observations'][0]);r['index']=0
            c['active_window']['observations']=[r]
        self.rejects(observation,'OFF_no_active_queries_and_unknown_memory_is_null')

    def test_ON_current_maxima_do_not_accept_lifetime_peaks_or_zero(self):
        self.rejects(lambda d:d[0]['cases'][1]['training_memory'].__setitem__('sampled_current_resident_max_bytes',0),'ON_current_sample_maxima')
        self.rejects(lambda d:d[0]['cases'][1]['training_memory'].__setitem__('peak_resident_bytes',999),'ON_current_sample_maxima')
        self.rejects(lambda d:d[0]['cases'][1]['training_memory'].__setitem__('boundary','full backward peak'),'ON_current_sample_maxima')
        data=fixture()
        for row in data[0]['cases'][1]['active_window']['observations']:row['sample']['memory']['peak_resident_bytes']*=10
        result=self.run_audit(data);self.assertTrue(result['passed'],result['failures'])

    def test_active_selection_requires_both_full_query_and_snapshot_inside_loop(self):
        def crossing(d):
            c=d[0]['cases'][1];start=c['loop_after']['loop']['loop_perf_counter_start']
            r=c['active_window']['observations'][0];r['query_started_perf_counter']=start-.001
        self.rejects(crossing,'exact_whole_query_and_snapshot_inside_actual_loop_selection')
        self.rejects(lambda d:d[0]['cases'][1]['active_observation_indices'].pop(),'exact_whole_query_and_snapshot_inside_actual_loop_selection')
        self.rejects(lambda d:d[0]['cases'][1]['active_window']['observations'][0]['sample'].__setitem__('perf_counter',999),'bounded_sample_clock')
        self.rejects(lambda d:d[0]['cases'][1]['active_window']['observations'][0]['sample'].__setitem__('creation_filetime',999),'actual_retained_worker_identity')
        self.rejects(lambda d:d[0]['cases'][1]['active_window']['observations'][0].__setitem__('snapshot_process_count',True),'global_Toolhelp_count_not_role_admission')

    def test_active_query_sampling_stats_and_bounds_are_recomputed(self):
        for key in ('selected_count','maximum_gap_including_boundaries_seconds','realized_samples_per_second',
            'memory_cpu_query_wall_seconds','snapshot_wall_seconds','combined_query_wall_fraction'):
            with self.subTest(key=key):
                self.rejects(lambda d:d[0]['cases'][1]['active_sampling'].__setitem__(key,999),'active:')
        self.rejects(lambda d:d[0]['cases'][1]['active_window'].__setitem__('poll_count',801),'bounded_common_poll_count')
        self.rejects(lambda d:d[0]['cases'][1]['active_window']['observations'][1]['sample'].__setitem__('native_cpu_seconds',0),'worker_native_CPU_monotonic')
        def few(d):
            c=d[0]['cases'][1];c['active_window']['observations']=c['active_window']['observations'][:19];c['active_window']['poll_count']=19
        self.rejects(few,'ON_twenty_samples_and_boundary_gap_gate')

    def test_wider_parent_CPU_is_never_exact_loop_CPU_or_exclusive_query_cost(self):
        self.rejects(lambda d:d[0]['cases'][1]['active_window'].__setitem__('parent_native_cpu_delta_seconds',0),'wider_parent_CPU_delta_recomputed_not_loop_only_CPU')
        self.rejects(lambda d:d[0]['cases'][1]['active_window'].__setitem__('parent_native_cpu_start_seconds',2),'wider_parent_CPU_nonnegative')
        self.rejects(lambda d:d[0]['cases'][1]['active_window'].__setitem__('started_perf_counter',999),'wider_release_completion_window')

    def test_paired_ratios_members_and_geomean_are_recomputed(self):
        self.rejects(lambda d:d[0]['paired_summary']['pairs'][0].__setitem__('off_case','pair2_off'),'exact_members')
        self.rejects(lambda d:d[0]['paired_summary']['pairs'][0].__setitem__('on_off_wall_ratio',.1),'ON_OFF_actual_loop_wall_ratio')
        self.rejects(lambda d:d[0]['paired_summary'].__setitem__('geometric_mean_on_off_wall_ratio',.1),'geometric_mean_recomputed')
        self.rejects(lambda d:d[0]['paired_summary'].__setitem__('all_four_trajectories_matched',False),'valid_interpretation')

    def test_unfavorable_slowdown_has_no_pass_threshold(self):
        data=fixture()
        for index in (0,3):
            loop=data[0]['cases'][index]['loop_after']['loop'];loop['loop_perf_counter_end']-=.3
            loop['training_loop_wall_seconds']=loop['loop_perf_counter_end']-loop['loop_perf_counter_start']
            loop['training_targets_per_second']=2048/loop['training_loop_wall_seconds']
        ratios=[]
        for row,(off,on) in zip(data[0]['paired_summary']['pairs'],[(0,1),(3,2)]):
            ratio=data[0]['cases'][on]['loop_after']['loop']['training_loop_wall_seconds']/data[0]['cases'][off]['loop_after']['loop']['training_loop_wall_seconds']
            row['on_off_wall_ratio']=ratio;ratios.append(ratio)
        data[0]['paired_summary']['geometric_mean_on_off_wall_ratio']=(ratios[0]*ratios[1])**.5
        result=self.run_audit(data);self.assertTrue(result['passed'],result['failures']);self.assertGreater(ratios[0],1.9)

    def test_exact_roles_liveness_images_control_and_cleanup(self):
        self.rejects(lambda d:d[0]['cases'][0]['censuses'][0]['processes'][0].__setitem__('alive',False),'held_same_live_job')
        self.rejects(lambda d:d[0]['cases'][0]['censuses'][1]['processes'][0]['image'].__setitem__('sha256','0'*64),'independent_exact_image_role')
        self.rejects(lambda d:d[0]['cases'][0]['role_decisions'][0].__setitem__('admitted',False),'positive_policy_decision')
        self.rejects(lambda d:d[0]['cases'][0]['controller_controls'][6].__setitem__('observer_duty_authorized',False),'exact_current_authority')
        self.rejects(lambda d:d[0]['cases'][0]['worker_controls'][6]['control_envelope'].__setitem__('control_index',0),'exact_saved_worker_copy')
        self.rejects(lambda d:d[0]['cases'][0]['prefinish_live_members'][0].__setitem__('alive',False),'prefinish_liveness')
        self.rejects(lambda d:d[0]['cases'][0]['cleanup']['exit_codes'].pop(),'exact_five_retained_exit')
        self.rejects(lambda d:d[0]['cases'][0]['cleanup'].__setitem__('job_active_count',1),'exact_five_retained_exit')
        self.rejects(lambda d:d[0]['cases'][0]['native_descendant']['os_image'].__setitem__('sha256','0'*64),'native_OS_image')

    def test_raw_files_are_all_required_and_failure_cannot_be_ignored(self):
        data=fixture();raw={c['id']:copy.deepcopy(auditor.raw_payloads(c)) for c in data[0]['cases']}
        result=self.run_audit(data,actual_raw_files=raw);self.assertTrue(result['passed'],result['failures'])
        for name in ('before-loop.json','pretrain-ready.json','finish-accepted.json'):
            changed=copy.deepcopy(raw);changed['pair1_off'].pop(name)
            result=self.run_audit(data,actual_raw_files=changed);self.assertFalse(result['passed'])
        changed=copy.deepcopy(raw);changed['pair1_off']['worker-failure.json']={'error':'hidden'}
        result=self.run_audit(data,actual_raw_files=changed);self.assertFalse(result['passed'])
        changed=copy.deepcopy(raw);changed['pair1_off']['before-loop.json']['pid']=123
        result=self.run_audit(data,actual_raw_files=changed);self.assertFalse(result['passed'])

    def test_bounded_saved_JSON_rejects_duplicates_nonfinite_and_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'receipt.json'
            for payload in (b'{"v":1,"v":2}',b'{"v":NaN}',b'{"v":Infinity}',b''):
                with self.subTest(payload=payload):
                    path.write_bytes(payload)
                    with self.assertRaises(ValueError):auditor.bounded(path)
            path.write_bytes(b'{"v":1}')
            with self.assertRaises(ValueError):auditor.bounded(path,maximum_bytes=6)
            self.assertEqual(auditor.bounded(path)[1],{'v':1})

    def test_file_entrypoint_reads_raw_files_and_actual_pinned_bytes(self):
        data=fixture();report,protocol,freeze,sources,deps=data
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for group in (auditor.SOURCE_PATHS,auditor.DEPENDENCY_PATHS,auditor.REVIEW_PATHS):
                for name in group:
                    path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(('synthetic:'+name).encode())
            sources={p:auditor.sha((root/p).read_bytes()) for p in auditor.SOURCE_PATHS}
            deps={p:auditor.sha((root/p).read_bytes()) for p in auditor.DEPENDENCY_PATHS}
            reviews={p:auditor.sha((root/p).read_bytes()) for p in auditor.REVIEW_PATHS}
            freeze.update(new_source_files_sha256=sources,frozen_dependency_files_sha256=deps,review_tools_sha256=reviews)
            report.update(source_sha256=sources,frozen_dependencies_sha256=deps,review_tools_sha256=reviews)
            def save(path,value):path.write_text(json.dumps(value,allow_nan=False),encoding='utf-8')
            protocol_path=root/'protocol.json';freeze_path=root/'freeze.json';report_path=root/'report.json'
            save(protocol_path,protocol);pin=auditor.sha(protocol_path.read_bytes());freeze['protocol_sha256']=report['protocol_sha256']=pin
            save(freeze_path,freeze);report['implementation_sha256']=auditor.sha(freeze_path.read_bytes());save(report_path,report)
            for case in report['cases']:
                folder=root/case['id'];folder.mkdir()
                for name,value in auditor.raw_payloads(case).items():save(folder/name,value)
            with mock.patch.multiple(auditor,PROTOCOL_SHA256=pin,SOURCE_HASHES=sources,DEPENDENCY_HASHES=deps):
                result=auditor.audit_files(report_path,protocol_path,freeze_path,root=root)
                self.assertTrue(result['passed'],result['failures'])
                save(root/'pair1_off'/'worker-failure.json',{'hidden':True})
                result=auditor.audit_files(report_path,protocol_path,freeze_path,root=root);self.assertFalse(result['passed'])
                (root/'pair1_off'/'worker-failure.json').unlink()
                (root/auditor.SOURCE_PATHS[0]).write_bytes(b'changed')
                result=auditor.audit_files(report_path,protocol_path,freeze_path,root=root);self.assertFalse(result['passed'])
                with self.assertRaises(ValueError):auditor.audit_files(report_path,protocol_path,freeze_path,root=root,python_path=root/'any')
