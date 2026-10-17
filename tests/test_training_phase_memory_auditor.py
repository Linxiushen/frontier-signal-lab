"""Synthetic saved receipts and adversarial mutations; no producer/native/ML calls."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from scripts import audit_training_phase_memory as auditor
from tests import test_observer_query_treatment_auditor as historical_synthetic


def provider(phase):
    return historical_synthetic.provider_receipt(phase,102)


def make_inventory(index,start,env):
    rows=[];groups=[]
    def add(name,category,numel,dtype='torch.float32',requires=False,shape=None):
        sid=len(groups);shape=[numel] if shape is None else shape
        row={'name':name,'category':category,'shape':shape,'dtype':dtype,'device':'cpu','numel':numel,'element_size_bytes':4,'logical_bytes':numel*4,'storage_offset_elements':0,'storage_id':sid,'backing_nbytes':numel*4,'requires_grad':requires,'is_leaf':not category=='live_loss_tensor'}
        rows.append(row);groups.append({'id':sid,'device':'cpu','backing_nbytes':numel*4,'members':[name]})
    for i in range(76):
        n=auditor.PARAM_NUMEL-75 if i==0 else 1;name='p'+str(i)
        add('parameters.'+name,'trainable_parameters',n,requires=True)
        if index in (3,4,7,8):add('gradients.'+name,'non_none_parameter_gradients',n)
        if index>=4:
            for field in ('exp_avg','exp_avg_sq'):add('optimizer.'+name+'.'+field,'optimizer_'+field,n)
            add('optimizer.'+name+'.step','optimizer_step_scalar',1,shape=[])
    # Two buffer aliases exercise cross-category-independent within-snapshot union.
    add('buffers.cache_a','model_buffers',1)
    duplicate=copy.deepcopy(rows[-1]);duplicate['name']='buffers.cache_b';rows.append(duplicate);groups[-1]['members'].append(duplicate['name'])
    live=index in (2,3,6,7)
    if live:add('loss','live_loss_tensor',1,requires=True,shape=[])
    categories={}
    for cat in auditor.CATEGORIES:
        selected=[t for t in rows if t['category']==cat];ids={t['storage_id'] for t in selected}
        categories[cat]={'tensor_count':len(selected),'logical_bytes':sum(t['logical_bytes'] for t in selected),'unique_backing_bytes':sum(groups[s]['backing_nbytes'] for s in ids)}
    return {**env,'boundary_id':'B'+str(index),'snapshot_started_perf_counter':start,'snapshot_completed_perf_counter':start+.02,'wall_seconds':.02,'tensors':rows,'storage_groups':groups,'categories':categories,'all_categories_unique_backing_bytes':sum(g['backing_nbytes'] for g in groups),'optimizer_state_entries':76 if index>=4 else 0,'optimizer_step_values':[2 if index==8 else 1]*76 if index>=4 else [],'live_loss_tensor':live,'tensor_count':len(rows),'method':auditor.INVENTORY_METHOD}


def summarize(op,window):
    a,b=op['operator_started_perf_counter'],op['operator_completed_perf_counter'];selected=[]
    for row in window['observations']:
        if a<=row['query_started_perf_counter']<=row['sample']['perf_counter']<=row['query_completed_perf_counter']<=b:selected.append(row)
    points=[a]+[v['sample']['perf_counter'] for v in selected]+[b];gap=max(y-x for x,y in zip(points,points[1:]));wall=sum(v['query_completed_perf_counter']-v['query_started_perf_counter'] for v in selected)
    count=len(selected);coverage=count>0 and gap<=.5
    return {'id':op['id'],'raw_count':len(window['observations']),'selected_count':count,'selected_indices':[v['index'] for v in selected],'excluded_count':len(window['observations'])-count,'maximum_gap_including_boundaries_seconds':gap,'realized_samples_per_second':count/(b-a) if count else None,'query_wall_seconds':wall,'query_wall_fraction':wall/(b-a) if count else None,'sampled_current_resident_max_bytes':max((v['sample']['memory']['resident_bytes'] for v in selected),default=None),'sampled_current_private_max_bytes':max((v['sample']['memory']['private_bytes'] for v in selected),default=None),'coverage_status':'unobserved' if not count else 'finite_sampled_lower_bound' if coverage else 'inadequate_gap','coverage_gate_passed':coverage,'missed_peak_bytes_upper_bound':None}


def fixture():
    old_report,_,old_freeze,_,_=historical_synthetic.fixture();base=old_report['cases'][0]
    protocol=json.loads((auditor.ROOT/'fixtures/training-phase-memory/protocol.json').read_bytes())
    protocol['predeclared_at']='2026-10-16T00:00:00+00:00'
    sources=dict(auditor.SOURCE_HASHES or {p:'a'*64 for p in auditor.SOURCE_PATHS})
    deps=dict(auditor.DEPENDENCY_HASHES or {p:'b'*64 for p in auditor.DEPENDENCY_PATHS})
    pin=auditor.PROTOCOL_SHA256 or '1'*64
    freeze={'schema_version':1,'frozen_at':'2026-10-16T00:00:01+00:00','protocol_sha256':pin,'new_source_files_sha256':dict(sources),'frozen_dependency_files_sha256':dict(deps),'review_tools_sha256':{p:'9'*64 for p in auditor.REVIEW_PATHS},'executables_sha256':old_freeze['executables_sha256'],'executable_path_sha256':old_freeze['executable_path_sha256'],'provider_source_sha256':auditor.PROVIDER_SOURCE_SHA256,'provider_source_path_sha256':'8'*64}
    report={'schema_version':1,'experiment_id':auditor.EXPERIMENT,'started_at':'2026-10-16T00:00:02+00:00','completed_at':'2026-10-16T00:00:19+00:00','started_perf_counter':100.,'completed_perf_counter':117.,'wall_seconds':17.,'passed':True,'os_name':'nt','no_fallback':True,'protocol_sha256':pin,'implementation_sha256':'d'*64,'protocol_predeclared_at':protocol['predeclared_at'],'implementation_frozen_at':freeze['frozen_at'],'source_sha256':dict(sources),'frozen_dependencies_sha256':dict(deps),'review_tools_sha256':dict(freeze['review_tools_sha256']),'planned_model_loads':1,'planned_optimizer_updates':2}
    for key in ('executables_sha256','executable_path_sha256','provider_source_sha256','provider_source_path_sha256'):report[key]=copy.deepcopy(freeze[key])
    keep=('launcher','worker_identity','native_descendant','cleanup','provider_custody_verified')
    case={k:copy.deepcopy(base[k]) for k in keep};case.update(id='phase_memory',sampling_enabled=True,query_treatment='memory_only',nonce=base['nonce'],passed=True,outcome='normal_completion',started_at='2026-10-16T00:00:04+00:00',completed_at='2026-10-16T00:00:18+00:00',started_perf_counter=102.,completed_perf_counter=116.,wall_seconds=14.,case_deadline_perf_counter=160.,suite_deadline_perf_counter=160.,stages={},memory_brackets={},inventories={},samples=[],parent_query_costs=[],censuses=[],role_decisions=[],controller_controls=[],worker_controls=[],operation_receipts=[],housekeeping_receipts=[],active_windows={},phase_measurements=[])
    for key in ('executables_sha256','executable_path_sha256','provider_source_sha256','provider_source_path_sha256'):case[key]=copy.deepcopy(freeze[key])
    identity={k:case['worker_identity']['self_receipt'][k] for k in ('pid','creation_filetime')};env={'nonce':case['nonce'],'role':'worker',**identity}
    def reading(clock):
        return {**identity,'perf_counter':clock,'memory':{'resident_bytes':104857600,'private_bytes':83886080,'peak_resident_bytes':209715200},'native_cpu_seconds':clock*.5}
    def query_cost(kind,a,b):
        return {'kind':kind,'started_perf_counter':a,'completed_perf_counter':b,'wall_seconds':b-a,'started_process_cpu_seconds':0.,'completed_process_cpu_seconds':0.,'parent_process_cpu_seconds':0.}
    def role_census(label,index,a):
        row=copy.deepcopy(base['censuses'][0 if index==0 else 1]);decision=copy.deepcopy(base['role_decisions'][0 if index==0 else 1]);b=a+.02;end=a+.04
        row.update(label=label,started_perf_counter=a,completed_perf_counter=b,wall_seconds=b-a)
        decision.update(label=label,census_index=index,decision_index=index,started_perf_counter=a,completed_perf_counter=end,wall_seconds=end-a)
        for j,v in enumerate(decision['held_liveness']):v['verified_perf_counter']=b+.001*(j+1)
        case['censuses'].append(row);case['role_decisions'].append(decision);case['parent_query_costs'].append(query_cost('held_role_census_and_liveness',a-.001,end+.001))
    role_census('before_native',0,102.25)
    for j,label in enumerate(auditor.STAGES):
        clock=103.+j
        stage={**env,'stage':label,'stage_ready_perf_counter':clock,'provider_guard':provider(auditor.PHASES[label]),'native_thread_count':7}
        if label=='preimport':stage.update(torch_imported=False,transformers_imported=False)
        if label=='postimport':stage.update(import_started_perf_counter=103.45,import_completed_perf_counter=103.8,torch_version='2.9.1+cpu',transformers_version='4.57.3')
        case['stages'][label]=stage
        before={**env,'query_started_perf_counter':clock+.01,'query_completed_perf_counter':clock+.02,'sample':reading(clock+.015)}
        parent={'query_started_perf_counter':clock+.05,'query_completed_perf_counter':clock+.06,'sample':reading(clock+.055)}
        after={**env,'query_started_perf_counter':clock+.20,'query_completed_perf_counter':clock+.21,'sample':reading(clock+.205)}
        case['memory_brackets'][label]={'self_before':before,'parent':parent,'self_after':after,'comparison':dict(same_identity=True,ordered_monotonic_bracket=True,resident_within_tolerance=True,private_within_tolerance=True,passed=True),'full_interval_ordered':True}
        case['samples'].append(parent['sample']);case['parent_query_costs'].append(query_cost('boundary_worker_memory_and_cpu',clock+.049,clock+.061));role_census(label,j+1,clock+.12)
        if label in auditor.BOUNDARIES:
            index=int(auditor.BOUNDARIES[label][1:]);case['inventories']['B'+str(index)]=make_inventory(index,clock+.25,env)
    case['parent_query_costs'].sort(key=lambda v:v['started_perf_counter'])
    for i,(filename,command,label,di) in enumerate(auditor.CONTROL_PLAN):
        if i==0:clock=102.35
        else:
            base_clock=case['stages'][label]['stage_ready_perf_counter'];clock=base_clock+(.18 if command=='parent-sampled' else .43 if command=='finish' else .4)
        sent={'filename':filename,'nonce':case['nonce'],'role':'controller','pid':999998,'command':command,'purpose':auditor.CONTROL_PURPOSE,'observer_duty_authorized':True,'role_policy_admitted':True,'role_decision_index':di,'role_decision_label':label,'control_index':i,'emitted_perf_counter':clock}
        case['controller_controls'].append(sent);case['worker_controls'].append({**env,'filename':filename,'control_envelope':{k:v for k,v in sent.items() if k!='filename'},'accepted_perf_counter':clock+.001,'next_control_index':i+1})
    case['training_deadline_perf_counter']=min(case['controller_controls'][6]['emitted_perf_counter']+15,160.)
    for i,id in enumerate(auditor.OP_IDS):
        a=105.5+i;b=a+(.0005 if i%4==0 else .2)
        op={**env,'id':id,'phase_index':i,'step':i//4+1,'kind':auditor.OPERATORS[i%4],'operator_started_perf_counter':a,'operator_completed_perf_counter':b,'wall_seconds':b-a,'worker_process_cpu_start_seconds':i*.25,'worker_process_cpu_end_seconds':i*.25+.1,'cpu_seconds':.1,'live_loss_after_operator':i%4!=0,'provider_guard':provider('train')};case['operation_receipts'].append(op)
        if i%4==3:case['housekeeping_receipts'].append({**env,'id':id,'started_perf_counter':b+.01,'completed_perf_counter':b+.02,'wall_seconds':.01,'loss_live_before':True,'loss_live_after':False,'recorded_loss':4.-i*.01})
        q=a-.08 if i%4==0 else a+.05
        sample=reading(q+.001)
        row={'index':0,'query_started_perf_counter':q,'query_completed_perf_counter':q+.002,'sample':sample,'snapshot_started_perf_counter':None,'snapshot_completed_perf_counter':None,'snapshot_process_count':None}
        wide0=case['controller_controls'][6+2*i]['emitted_perf_counter']-.001;wide1=b+.03
        window={'started_perf_counter':wide0,'completed_perf_counter':wide1,'wall_seconds':wide1-wide0,'parent_native_cpu_start_seconds':0.,'parent_native_cpu_end_seconds':0.,'parent_native_cpu_delta_seconds':0.,'poll_count':1,'observations':[row]}
        case['active_windows'][id]=window;case['phase_measurements'].append(summarize(op,window))
    case['all_phases_have_finite_sampled_coverage']=False
    case['training_span']={'started_perf_counter':105.5,'completed_perf_counter':113.,'wall_seconds':7.5,'operator_wall_sum_seconds':sum(v['wall_seconds'] for v in case['operation_receipts']),'housekeeping_wall_sum_seconds':sum(v['wall_seconds'] for v in case['housekeeping_receipts'])}
    info=copy.deepcopy(base['stages']['pretrain']['model']);info.update(schedule=auditor.schedule(),schedule_sha256=auditor.sha(auditor.canonical(auditor.schedule()).encode()),batch_shapes=[[2,65]]*2)
    info.update(model_load_started_perf_counter=104.5,model_load_completed_perf_counter=104.8)
    case['stages']['pretrain']['model_info']=info
    case['stages']['postvalidation']['validation']={'started_perf_counter':113.5,'completed_perf_counter':113.8,'final_validity':{'optimizer_counters':[2]*76,'final_parameter_gradient_moments_finite':True},'final_parameter_sha256':'3'*64,'no_holdout_evaluation':True,'no_checkpoint_written':True}
    case['postvalidation_continue_ack_barrier']={'control_filename':'postvalidation-continue.json','filename':'postvalidation-continue-accepted.json','requested_perf_counter':114.4,'started_perf_counter':114.4005,'completed_perf_counter':114.41,'wall_seconds':114.41-114.4005,'deadline_perf_counter':119.4005,'worker_identity':identity,'accepted_receipt':copy.deepcopy(case['worker_controls'][24]),'passed':True}
    case['prefinish_live_members']=copy.deepcopy(base['prefinish_live_members'])
    for v in case['prefinish_live_members']:v['verified_perf_counter']=114.42
    case['healthy_completion']={**env,'model_loads':1,'optimizer_steps':2,'native_exit_code':0,'native_released_nonempty_line':True,'provider_guard':provider('complete')}
    case['cleanup'].update(started_perf_counter=115.,completed_perf_counter=115.1,wall_seconds=.1,timeout_seconds=4.)
    report['cases']=[case]
    return report,protocol,freeze,sources,deps


class PhaseMemoryAuditorTests(unittest.TestCase):
    def run_audit(self,values=None,**kwargs):
        report,protocol,freeze,sources,deps=values or fixture()
        with mock.patch.multiple(auditor,PROTOCOL_SHA256=report['protocol_sha256'],SOURCE_HASHES=sources,DEPENDENCY_HASHES=deps):
            return auditor.audit(report,protocol,freeze,protocol_sha256=report['protocol_sha256'],freeze_sha256=report['implementation_sha256'],actual_source_sha256=sources,actual_dependency_sha256=deps,actual_review_tools_sha256=freeze['review_tools_sha256'],**kwargs)
    def reject(self,mutate,part=None):
        values=fixture();mutate(values[0]['cases'][0]);result=self.run_audit(values)
        self.assertFalse(result['passed'],result)
        if part:self.assertTrue(any(part in s for s in result['failures']),result['failures'])
    def test_complete_synthetic_two_update_study_and_exact_raw_count(self):
        values=fixture();case=values[0]['cases'][0]
        self.assertEqual(len(auditor.raw_payloads(case)),110)
        result=self.run_audit(values,actual_raw_files={'phase_memory':auditor.raw_payloads(case)},actual_historical_evidence_sha256=dict(auditor.HISTORICAL_FILE_SHA256))
        self.assertTrue(result['passed'],result['failures'])
        self.assertGreater(result['check_count'],10000)
    def test_file_entrypoint_replays_synthetic_raw_custody_and_actual_hash_bindings(self):
        from contextlib import redirect_stdout
        import io
        values=fixture();report,protocol,freeze,_,_=values
        sources={p:auditor.sha((auditor.ROOT/p).read_bytes()) for p in auditor.SOURCE_PATHS}
        deps={p:auditor.sha((auditor.ROOT/p).read_bytes()) for p in auditor.DEPENDENCY_PATHS}
        reviews={p:auditor.sha((auditor.ROOT/p).read_bytes()) for p in auditor.REVIEW_PATHS}
        raw_protocol=(json.dumps(protocol,ensure_ascii=False,allow_nan=False)+'\n').encode()
        pin=auditor.sha(raw_protocol)
        freeze.update(protocol_sha256=pin,new_source_files_sha256=sources,frozen_dependency_files_sha256=deps,review_tools_sha256=reviews)
        raw_freeze=(json.dumps(freeze,ensure_ascii=False,allow_nan=False)+'\n').encode()
        report.update(protocol_sha256=pin,implementation_sha256=auditor.sha(raw_freeze),source_sha256=sources,frozen_dependencies_sha256=deps,review_tools_sha256=reviews)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);receipt_dir=root/'phase_memory';receipt_dir.mkdir()
            for name,row in auditor.raw_payloads(report['cases'][0]).items():(receipt_dir/name).write_text(json.dumps(row,allow_nan=False),encoding='utf-8')
            rp,pp,fp,op=[root/n for n in ('report.json','protocol.json','freeze.json','audit.json')]
            rp.write_text(json.dumps(report,allow_nan=False),encoding='utf-8');pp.write_bytes(raw_protocol);fp.write_bytes(raw_freeze)
            with mock.patch.multiple(auditor,PROTOCOL_SHA256=pin,SOURCE_HASHES=sources,DEPENDENCY_HASHES=deps),redirect_stdout(io.StringIO()):
                code=auditor.main(['--report',str(rp),'--protocol',str(pp),'--freeze',str(fp),'--output',str(op)])
            result=json.loads(op.read_bytes())
            self.assertEqual(code,0,result['failures']);self.assertTrue(result['passed'],result['failures'])
            self.assertEqual(result['report_file_sha256'],auditor.sha(rp.read_bytes()))
            self.assertIn('local_executable_files',result['unperformed_optional_file_checks'])
    def test_inadequate_sample_gap_is_honest_lower_bound_with_engineering_acceptance(self):
        values=fixture();c=values[0]['cases'][0];op=c['operation_receipts'][1];window=c['active_windows'][op['id']]
        op.update(operator_started_perf_counter=106.4015,operator_completed_perf_counter=106.99,wall_seconds=106.99-106.4015)
        row=window['observations'][0];row.update(query_started_perf_counter=106.402,query_completed_perf_counter=106.404);row['sample']['perf_counter']=106.403
        window.update(completed_perf_counter=106.995,wall_seconds=106.995-window['started_perf_counter'])
        c['phase_measurements'][1]=summarize(op,window);c['training_span']['operator_wall_sum_seconds']=sum(v['wall_seconds'] for v in c['operation_receipts'])
        self.assertEqual(c['phase_measurements'][1]['coverage_status'],'inadequate_gap')
        result=self.run_audit(values);self.assertTrue(result['passed'],result['failures'])
    def test_summary_indices_exclusion_schema_and_coverage_are_recomputed(self):
        for field,value in [('selected_indices',[]),('excluded_count',1),('coverage_gate_passed',False),('missed_peak_bytes_upper_bound',0)]:
            with self.subTest(field=field):self.reject(lambda c:c['phase_measurements'][1].update({field:value}),'active:')
        self.reject(lambda c:c['phase_measurements'][1].pop('selected_indices'),'invalid_or_incomplete')
        self.reject(lambda c:c.update(all_phases_have_finite_sampled_coverage=True),'all_phase_coverage')
    def test_snapshot_local_ids_and_category_integer_arithmetic_are_required(self):
        self.reject(lambda c:c['inventories']['B0']['tensors'][0].update(storage_id='0'),'invalid_or_incomplete')
        self.reject(lambda c:c['inventories']['B0']['categories']['live_loss_tensor'].update(tensor_count=False),'recomputed_category')
        self.reject(lambda c:c['inventories']['B0']['storage_groups'][0].update(id=True),'groups_exact_local_storage_partition')
    def test_omitted_declared_deadline_or_wrong_ready_creation_is_rejected(self):
        self.reject(lambda c:c.pop('training_deadline_perf_counter'),'invalid_or_incomplete')
        self.reject(lambda c:c['stages']['pretrain'].update(creation_filetime=9),'ready_before_queries')
    def test_unsampled_short_zero_grad_retains_null_unknown_and_engineering_passes(self):
        values=fixture();case=values[0]['cases'][0]
        self.assertEqual(case['phase_measurements'][0]['selected_count'],0)
        self.assertIsNone(case['phase_measurements'][0]['sampled_current_private_max_bytes'])
        self.assertTrue(self.run_audit(values)['passed'])
    def test_zero_fabrication_or_held_endpoint_cannot_fill_unsampled_phase(self):
        for key in ('sampled_current_resident_max_bytes','sampled_current_private_max_bytes','realized_samples_per_second','query_wall_fraction'):
            with self.subTest(key=key):self.reject(lambda c:c['phase_measurements'][0].update({key:0}),'active:')
    def test_complete_query_crossing_phase_boundary_is_excluded(self):
        values=fixture();c=values[0]['cases'][0];id=auditor.OP_IDS[1];op=c['operation_receipts'][1];row=c['active_windows'][id]['observations'][0]
        row['query_started_perf_counter']=op['operator_started_perf_counter']-.001
        c['phase_measurements'][1]=summarize(op,c['active_windows'][id])
        self.assertEqual(c['phase_measurements'][1]['selected_count'],0)
        self.assertTrue(self.run_audit(values)['passed'])
        c['phase_measurements'][1]['selected_count']=1
        self.assertFalse(self.run_audit(values)['passed'])
    def test_snapshot_nulls_and_actual_worker_identity_are_not_optional(self):
        for field,value in [('snapshot_process_count',0),('snapshot_started_perf_counter',0),('snapshot_completed_perf_counter',0)]:
            with self.subTest(field=field):self.reject(lambda c:c['active_windows'][auditor.OP_IDS[1]]['observations'][0].update({field:value}),'Toolhelp_unperformed')
        self.reject(lambda c:c['active_windows'][auditor.OP_IDS[1]]['observations'][0]['sample'].update(pid=1234),'actual_retained_worker')
    def test_sample_maximum_uses_current_not_lifetime_peak(self):
        self.reject(lambda c:c['phase_measurements'][1].update(sampled_current_resident_max_bytes=209715200),'current_lower_bound')
    def test_reversed_or_overlapping_full_query_brackets_reject_point_order_escape(self):
        self.reject(lambda c:c['memory_brackets']['pretrain']['self_before'].update(query_completed_perf_counter=105.051),'full_query_order')
        self.reject(lambda c:c['memory_brackets']['pretrain']['parent'].update(query_completed_perf_counter=105.201),'full_query_order')
    def test_memory_tolerance_failures_are_not_recalibrated(self):
        self.reject(lambda c:c['memory_brackets']['pretrain']['parent']['sample']['memory'].update(private_bytes=999999999),'current_values_and_tolerance')
    def test_phase_order_count_clock_and_housekeeping_custody(self):
        self.reject(lambda c:c['operation_receipts'].pop(),'eight_operators')
        self.reject(lambda c:c['operation_receipts'][1].update(operator_started_perf_counter=104.),'operation_only')
        self.reject(lambda c:c['housekeeping_receipts'][0].update(started_perf_counter=108.6),'housekeeping_before_hold')
        self.reject(lambda c:c['housekeeping_receipts'][0].update(loss_live_after=True),'housekeeping_before_hold')
    def test_late_inventory_cannot_be_before_or_during_memory_query(self):
        self.reject(lambda c:c['inventories']['B0'].update(snapshot_started_perf_counter=105.2),'inventory_after_native_current')
    def test_inventory_gradient_state_and_loss_lifetimes_are_falsifiable(self):
        self.reject(lambda c:c['inventories']['B0'].update(optimizer_state_entries=76),'first_optimizer_creates')
        self.reject(lambda c:c['inventories']['B4']['optimizer_step_values'].__setitem__(0,2),'native_step_counters')
        self.reject(lambda c:c['inventories']['B8']['optimizer_step_values'].__setitem__(0,1),'native_step_counters')
        self.reject(lambda c:c['inventories']['B2'].update(live_loss_tensor=False),'loss_binding_lifetime')
    def test_unique_backing_union_handles_aliases_and_does_not_equal_logical_bytes(self):
        values=fixture();inv=values[0]['cases'][0]['inventories']['B0'];cat=inv['categories']['model_buffers']
        self.assertEqual(cat,{'tensor_count':2,'logical_bytes':8,'unique_backing_bytes':4})
        self.assertTrue(self.run_audit(values)['passed'])
        self.reject(lambda c:c['inventories']['B0'].update(all_categories_unique_backing_bytes=c['inventories']['B0']['all_categories_unique_backing_bytes']+4),'unique_backing_union')
    def test_conflicting_alias_capacity_or_unregistered_storage_fails(self):
        self.reject(lambda c:c['inventories']['B0']['tensors'][-1].update(backing_nbytes=8),'alias_backing_capacity')
        self.reject(lambda c:c['inventories']['B0']['storage_groups'].pop(),'groups_exact_local_storage_partition')
    def test_boolean_count_shape_name_and_source_fields_cannot_launder_metadata(self):
        self.reject(lambda c:c['inventories']['B0']['tensors'][0].update(numel=True),'numel_and_element_size')
        self.reject(lambda c:c['inventories']['B0']['tensors'][0].update(name='x'*257),'bounded_name')
        self.reject(lambda c:c['phase_measurements'][1].update(selected_count=True),'counts_recomputed')
    def test_wrong_actual_creation_and_ack_replay_block_finish(self):
        self.reject(lambda c:c['worker_controls'][24].update(creation_filetime=999),'authenticated_worker_copy')
        self.reject(lambda c:c['postvalidation_continue_ack_barrier'].update(completed_perf_counter=114.425,wall_seconds=114.425-114.4005),'both_live_and_finish')
        self.reject(lambda c:c['postvalidation_continue_ack_barrier'].update(deadline_perf_counter=130),'nonrenewable_deadline')
    def test_cleanups_and_failure_receipts_are_never_upgraded(self):
        self.reject(lambda c:c['cleanup']['exit_codes'][0].update(exit_code=37),'five_retained_exit0')
        self.reject(lambda c:c['cleanup'].update(job_active_count=1),'five_retained_exit0')
        self.reject(lambda c:c.update(worker_failure_receipt={'error':'saved failure'}),'no_hidden_failure')
    def test_provider_changes_and_extra_same_image_roles_remain_rejected(self):
        self.reject(lambda c:c['operation_receipts'][2]['provider_guard'].update(allowed_local_probe_count=0),'provider:')
        self.reject(lambda c:c['censuses'][3]['processes'][0].update(parent_pid=999),'role:')
    def test_zero_native_CPU_and_no_physical_state_delta_have_no_favorable_gate(self):
        self.assertTrue(self.run_audit()['passed'])
    def test_validation_cannot_leak_into_training_operations(self):
        self.reject(lambda c:c['stages']['postvalidation']['validation'].update(started_perf_counter=110),'final_checks_after')
    def test_raw_files_extra_missing_or_mutated_reject(self):
        for kind in ('extra','missing','mutated'):
            values=fixture();raw=auditor.raw_payloads(values[0]['cases'][0])
            if kind=='extra':raw['extra.json']={}
            elif kind=='missing':raw.pop('step1_backward-operation.json')
            else:raw['step1_backward-operation.json']=dict(raw['step1_backward-operation.json'],wall_seconds=999)
            self.assertFalse(self.run_audit(values,actual_raw_files={'phase_memory':raw})['passed'])
    def test_root_freeze_protocol_source_and_history_mutations_reject(self):
        values=fixture();values[1]['config']['optimizer_steps']=3
        self.assertFalse(self.run_audit(values)['passed'])
        values=fixture();values[2]['new_source_files_sha256'][auditor.SOURCE_PATHS[0]]='0'*64
        self.assertFalse(self.run_audit(values)['passed'])
        values=fixture();values[1]['history']['observer_duty_v1_acceptance_passed']=True
        self.assertFalse(self.run_audit(values)['passed'])
    def test_bounded_JSON_rejects_duplicate_nonfinite_empty_and_oversize(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'receipt.json'
            for raw in (b'',b'{"x":1,"x":2}',b'{"x":NaN}',b'x'*20):
                p.write_bytes(raw)
                with self.assertRaises(ValueError):auditor.bounded(p,16)
    def test_auditor_source_never_imports_producer_ML_or_network_or_launches_process(self):
        import ast
        source=Path(auditor.__file__).read_text(encoding='utf-8');tree=ast.parse(source)
        imports=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):imports.extend(a.name for a in node.names)
            elif isinstance(node,ast.ImportFrom):imports.append(node.module or '')
        self.assertFalse(any(n.startswith(('torch','transformers','experiments','socket','subprocess','ctypes')) for n in imports),imports)


if __name__=='__main__':unittest.main()
