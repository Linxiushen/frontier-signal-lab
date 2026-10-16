"""Independent synthetic receipts/mutations; no producer, OS or ML execution."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from scripts import audit_training_observer as auditor

MIB=1024*1024


def fixture():
    sources=dict(auditor.SOURCE_HASHES or {p:'a'*64 for p in auditor.SOURCE_PATHS})
    dependencies=dict(auditor.DEPENDENCY_HASHES or {p:'b'*64 for p in auditor.DEPENDENCY_PATHS})
    pin=auditor.PROTOCOL_SHA256 or '1'*64
    protocol={'schema_version':1,'experiment_id':auditor.EXPERIMENT,'predeclared_at':'2026-10-16T00:00:00+00:00',
        'source_paths':list(auditor.SOURCE_PATHS),'frozen_dependency_paths':list(auditor.DEPENDENCY_PATHS),
        'config':dict(auditor.CONFIG),'cases_in_order':[{'id':i,'mode':m,'manual_allocation_bytes':n} for i,m,n in auditor.CASES],
        'model':{'id':auditor.MODEL_ID,'revision':auditor.MODEL_REVISION,'assets':copy.deepcopy(auditor.ASSETS),
            'planned_model_loads':3,'planned_optimizer_updates':6,'dense_only':True,'no_download_install_or_GPU':True},
        'training':{'train_sha256':auditor.TRAIN_SHA256,'schedule':auditor.schedule(),
            'schedule_sha256':auditor.sha(auditor.canonical(auditor.schedule()).encode()),'seed':503,'steps':2,
            'batch_shape':[2,65],'input_tokens_per_batch':128,'optimizer':copy.deepcopy(auditor.OPTIMIZER),
            'method':'dense','arm':'token','holdout_opened':False,'checkpoint_written':False}}
    freeze={'schema_version':1,'frozen_at':'2026-10-16T00:00:01+00:00','protocol_sha256':pin,
        'new_source_files_sha256':sources,'frozen_dependency_files_sha256':dependencies,
        'python_executable_sha256':'c'*64,'base_python_executable_sha256':'f'*64,'native_executable_sha256':'e'*64}
    report={'schema_version':1,'experiment_id':auditor.EXPERIMENT,'protocol_sha256':pin,'implementation_sha256':'d'*64,
        'source_sha256':dict(sources),'frozen_dependencies_sha256':dict(dependencies),'launch_executable_sha256':'c'*64,
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
    return report,protocol,freeze,sources,dependencies


class TrainingAuditorTests(unittest.TestCase):
    def run_audit(self,data,optional=True):
        report,protocol,freeze,sources,deps=data
        return auditor.audit(report,protocol,freeze,protocol_sha256=auditor.PROTOCOL_SHA256 or '1'*64,freeze_sha256='d'*64,
            actual_source_sha256=sources,actual_dependency_sha256=deps,launch_sha256='c'*64 if optional else None,
            base_python_sha256='f'*64 if optional else None,native_sha256='e'*64 if optional else None,
            actual_model_assets=copy.deepcopy(auditor.ASSETS) if optional else None)
    def rejects(self,mutation,label):
        data=fixture(); mutation(data); result=self.run_audit(data)
        self.assertFalse(result['passed'],label)
        self.assertTrue(any(label in x for x in result['failures']),result['failures'])
    def test_complete_synthetic_receipts(self):
        result=self.run_audit(fixture()); self.assertTrue(result['passed'],result['failures'])
        self.assertEqual(result['unperformed_optional_file_checks'],[])
    def test_optional_file_hashes_are_explicit(self):
        result=self.run_audit(fixture(),False); self.assertTrue(result['passed'],result['failures'])
        self.assertEqual(len(result['unperformed_optional_file_checks']),4)
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
            (lambda d:d[0]['cases'][0]['parent_query_costs'].pop(0),'every_parent_sample_has_cost_record'),
            (lambda d:d[0]['cases'][0]['parent_query_costs'][0].update(parent_process_cpu_seconds=100),'query_CPU_recomputed'),
            (lambda d:d[0]['cases'][0]['stage_process_inventories'][0]['unknown_descendants'].append(999),'snapshot_descendants_exact'),
            (lambda d:d[0]['cases'][0]['stage_process_inventories'][0]['processes'][1].update(alive=False),'snapshot_retained_members'),
            (lambda d:d[0]['cases'][0]['stage_process_inventories'][0]['processes'][2].update(parent_pid=999),'snapshot_parent_links')]:
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
        self.rejects(early_import,'cleanup_after_all_known_live')
        self.rejects(lambda d:d[0]['cases'][0]['stage_process_inventories'][0].update(perf_counter=d[0]['cases'][0]['started_perf_counter']+3),
            'snapshot_before_next_stage_or_release')
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


if __name__=='__main__': unittest.main()
