"""Guarded stdlib mocks and primitive synthetic metadata; no native/ML workload."""
import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from experiments import training_phase_memory as p
NONCE="a"*64
REAL_AWAIT=p.await_postvalidation_continue

class Tensor:
    counter=100
    def __init__(self,n=1,shape=None,dtype="torch.float32",width=4,value=1):
        Tensor.counter+=1;self.address=Tensor.counter;self.n=n;self.shape=([n] if shape is None else shape);self.dtype=dtype;self.width=width
        self.device="cpu";self.requires_grad=False;self.is_leaf=True;self.grad=None;self.value=value
    def numel(self):return self.n
    def element_size(self):return self.width
    def storage_offset(self):return 0
    def untyped_storage(self):return SimpleNamespace(nbytes=lambda:self.n*self.width,data_ptr=lambda:self.address)
    def item(self):return self.value

def fake_model():
    params=[(f"layer{i}.weight",Tensor(14067712-75 if i==0 else 1)) for i in range(76)]
    return SimpleNamespace(named_parameters=lambda:iter(params),parameters=lambda:(v for _,v in params),named_buffers=lambda:iter(())),params

def synthetic_inventory(index):
    model,named=fake_model();optimizer=SimpleNamespace(state={})
    if index in (3,4,7,8):
        for _,v in named:v.grad=Tensor(v.n)
    if index>=4:
        for _,v in named:optimizer.state[v]={"exp_avg":Tensor(v.n),"exp_avg_sq":Tensor(v.n),"step":Tensor(1,shape=[],value=2 if index==8 else 1)}
    loss=Tensor(1,shape=[]) if index in (2,3,6,7) else None
    return p.tensor_inventory(model,optimizer,loss,"B"+str(index))

def observation(index,start,end,stamp=None):
    return {"index":index,"query_started_perf_counter":start,"query_completed_perf_counter":end,
        "snapshot_started_perf_counter":None,"snapshot_completed_perf_counter":None,"snapshot_process_count":None,
        "sample":{"pid":2000,"creation_filetime":20,"perf_counter":(start+end)/2 if stamp is None else stamp,
        "native_cpu_seconds":0,"memory":{"resident_bytes":100+index,"private_bytes":200+index,"peak_resident_bytes":999999999}}}

class ContractTests(unittest.TestCase):
    def test_only_one_load_two_steps_eight_ops_twelve_holds_twenty_six_controls(self):
        self.assertEqual(p.schedule(),[[116,73],[14,52]])
        self.assertEqual((p.CONFIG["optimizer_steps"],len(p.OPERATIONS),len(p.BOUNDARIES),len(p.STAGES),len(p.CONTROL_PLAN)),(2,8,9,12,26))
        self.assertEqual(p.END_BARRIER["controller_control_index"],24);self.assertEqual(p.END_BARRIER["worker_next_control_index"],25)
    def test_imports_are_stdlib_without_torch(self):
        self.assertNotIn("torch",sys.modules);self.assertNotIn("transformers",sys.modules)
    def test_protocol_matches_new_finite_contract(self):
        x=json.loads((p.ROOT/"fixtures/training-phase-memory/protocol.json").read_text())
        for key,value in (("config",p.CONFIG),("operations",list(p.OPERATIONS)),("stages",list(p.STAGES)),("boundaries",p.BOUNDARIES),("categories",list(p.CATEGORIES)),("end_barrier",p.END_BARRIER)):
            self.assertEqual(x[key],value)
        self.assertEqual(x["training"]["schedule"],p.schedule());self.assertEqual(x["model"]["planned_model_loads"],1);self.assertEqual(x["model"]["planned_optimizer_updates"],2)
    def test_deadlines_are_minimum_original_bounds(self):
        with mock.patch.object(p.time,"perf_counter",return_value=10):
            self.assertEqual(p.deadline(5,12,20),12);self.assertEqual(p.deadline(5,20,11),11)
    def test_worker_source_has_only_one_loop_with_exact_operation_calls(self):
        source=p.SCRIPT.read_text();tree=ast.parse(source)
        worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="worker")
        calls=[ast.unparse(n.func) for n in ast.walk(worker) if isinstance(n,ast.Call)]
        for call in ("prepare","optimizer.zero_grad","cost.forward_loss","loss.backward","optimizer.step"):
            self.assertEqual(calls.count(call),1,call)
        self.assertNotIn("cost.training_loop",calls);self.assertNotIn("gc.collect",calls)
        self.assertEqual(source.count('training_end=min(state["last_emitted"]+15'),1)

    def test_fresh_prepare_uses_pinned_loader_seed_and_exactly_two_batches(self):
        class Tokens:
            def __getitem__(self,indices):return SimpleNamespace(shape=[2,65])
        parameters=[SimpleNamespace(numel=lambda:14067712)]+[SimpleNamespace(numel=lambda:0) for _ in range(75)]
        model=SimpleNamespace(parameters=lambda:parameters);optimizer=SimpleNamespace(state={})
        torch=SimpleNamespace(long="long",tensor=mock.Mock(return_value=Tokens()),get_num_threads=lambda:1,
            get_num_interop_threads=lambda:1,are_deterministic_algorithms_enabled=lambda:True)
        with mock.patch.object(p.cost,"verify_model_assets"),mock.patch.object(p.cost,"validate_fixture",return_value=({"train_sha256":"c"*64},None,None)), \
                mock.patch.object(p.cost,"load_blocks",return_value=[[1]*65]*128), \
                mock.patch.object(p.cost,"load_model",return_value=model) as load, \
                mock.patch.object(p.cost,"optimizer_for",return_value=optimizer), \
                mock.patch.object(p.cost,"parameter_hash",return_value="a"*64):
            actual_model,actual_optimizer,batches,info=p.prepare(torch,"model","fixture")
        load.assert_called_once_with("model",503)
        self.assertIs(actual_model,model);self.assertIs(actual_optimizer,optimizer);self.assertEqual(len(batches),2)
        self.assertEqual(info["schedule"],p.schedule());self.assertEqual(info["optimizer_state_entries"],0)
        self.assertEqual(info["optimizer_type"],"AdamW");self.assertEqual(info["batch_shapes"],[[2,65]]*2)


class InventoryTests(unittest.TestCase):
    def test_all_nine_declared_lifecycles(self):
        for index in range(9):
            with self.subTest(index=index):p.validate_inventory(synthetic_inventory(index),index)
    def test_first_state_creation_second_state_counter(self):
        a,b,c=synthetic_inventory(3),synthetic_inventory(4),synthetic_inventory(8)
        self.assertEqual(a["optimizer_state_entries"],0);self.assertEqual(b["optimizer_state_entries"],76)
        self.assertEqual(b["optimizer_step_values"],[1]*76);self.assertEqual(c["optimizer_step_values"],[2]*76)
        self.assertEqual(b["categories"]["optimizer_exp_avg"]["logical_bytes"],56270848)
    def test_inventory_is_only_JSON_primitives(self):
        x=synthetic_inventory(4);self.assertEqual(json.loads(json.dumps(x)),x)
        self.assertNotIn("data_ptr",json.dumps(x))
    def test_cross_category_alias_is_deduplicated_once_per_snapshot(self):
        model,named=fake_model();named[0][1].grad=Tensor(named[0][1].n);named[0][1].grad.address=named[0][1].address
        x=p.tensor_inventory(model,SimpleNamespace(state={}),None,"alias")
        self.assertEqual(x["all_categories_unique_backing_bytes"],56270848)
        self.assertEqual(x["categories"]["non_none_parameter_gradients"]["logical_bytes"],named[0][1].n*4)
    def test_new_snapshot_never_unions_previous_addresses(self):
        self.assertEqual(synthetic_inventory(0)["all_categories_unique_backing_bytes"],synthetic_inventory(0)["all_categories_unique_backing_bytes"])
    def test_missing_state_lookup_does_not_create_entries(self):
        class FailMissing(dict):
            def __missing__(self,key):raise AssertionError("unexpected optimizer state insertion")
        model,_=fake_model();state=FailMissing();p.tensor_inventory(model,SimpleNamespace(state=state),None,"B0")
        self.assertEqual(state,{})
    def test_inventory_rejects_missing_moment_state_keys(self):
        model,named=fake_model();state={named[0][1]:{"step":Tensor(1,shape=[])}}
        with self.assertRaises(p.obs.ObserverError):p.tensor_inventory(model,SimpleNamespace(state=state),None,"B4")
    def test_semantic_mutations_do_not_get_accepted(self):
        changes=[("optimizer_state_entries",0),("optimizer_step_values",[2]*76),("live_loss_tensor",True),("all_categories_unique_backing_bytes",0),("tensor_count",0)]
        for field,value in changes:
            x=synthetic_inventory(4);x[field]=value
            with self.subTest(field=field),self.assertRaises(p.obs.ObserverError):p.validate_inventory(x,4)
    def test_wrong_moment_shape_and_scalar_dtype_reject(self):
        for category in ("optimizer_exp_avg","optimizer_step_scalar"):
            x=synthetic_inventory(4);row=next(r for r in x["tensors"] if r["category"]==category);row["dtype"]="torch.float64"
            with self.subTest(category=category),self.assertRaises(p.obs.ObserverError):p.validate_inventory(x,4)
    def test_metadata_limits_are_finite(self):
        model,named=fake_model();model.named_buffers=lambda:((str(i),Tensor(1)) for i in range(257))
        with self.assertRaises(p.obs.ObserverError):p.tensor_inventory(model,SimpleNamespace(state={}),None,"B0")

class QueryTests(unittest.TestCase):
    def setUp(self):self.actual=SimpleNamespace(pid=2000,creation_filetime=20)
    def test_complete_query_interval_identity_validates(self):p.validate_query(observation(0,1,1.1),self.actual)
    def test_wrong_pid_creation_overlap_or_noninteger_bytes_reject(self):
        for field in ("pid","creation_filetime","clock","bytes"):
            x=observation(0,1,1.1)
            if field in ("pid","creation_filetime"):x["sample"][field]+=1
            if field=="clock":x["sample"]["perf_counter"]=1.2
            if field=="bytes":x["sample"]["memory"]["private_bytes"]=True
            with self.subTest(field=field),self.assertRaises(p.obs.ObserverError):p.validate_query(x,self.actual)
    def test_only_wholly_contained_queries_select(self):
        rows=[observation(0,.9,1.1),observation(1,1.2,1.21),observation(2,1.99,2.01)]
        x=p.phase_summary(p.OPERATIONS[0],{"operator_started_perf_counter":1,"operator_completed_perf_counter":2},{"observations":rows})
        self.assertEqual(x["selected_indices"],[1]);self.assertEqual(x["excluded_count"],2);self.assertEqual(x["sampled_current_resident_max_bytes"],101)
    def test_zero_samples_remain_unknown_null_not_zero(self):
        x=p.phase_summary(p.OPERATIONS[0],{"operator_started_perf_counter":1,"operator_completed_perf_counter":1.0001},{"observations":[]})
        for field in ("sampled_current_resident_max_bytes","sampled_current_private_max_bytes","realized_samples_per_second","query_wall_fraction","missed_peak_bytes_upper_bound"):self.assertIsNone(x[field])
        self.assertEqual(x["coverage_status"],"unobserved");self.assertFalse(x["coverage_gate_passed"])
    def test_large_gap_with_one_query_stays_inadequate(self):
        x=p.phase_summary(p.OPERATIONS[0],{"operator_started_perf_counter":1,"operator_completed_perf_counter":3},{"observations":[observation(0,1.1,1.11)]})
        self.assertEqual(x["coverage_status"],"inadequate_gap");self.assertFalse(x["coverage_gate_passed"])
    def test_current_sample_max_does_not_use_lifetime_highwater(self):
        x=p.phase_summary(p.OPERATIONS[0],{"operator_started_perf_counter":1,"operator_completed_perf_counter":1.2},{"observations":[observation(0,1.1,1.11)]})
        self.assertEqual(x["sampled_current_resident_max_bytes"],100);self.assertTrue(x["coverage_gate_passed"])
    def test_query_wrapper_bounds_full_read(self):
        sample={"perf_counter":2}
        with mock.patch.object(p.time,"perf_counter",side_effect=[1,3]):x=p.query_interval(lambda:sample)
        self.assertEqual(x,{"query_started_perf_counter":1,"query_completed_perf_counter":3,"sample":sample})


class WorkerTests(unittest.TestCase):
    def run_worker(self,fail_forward=False):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);directory=Path(temporary.name)
        backend=mock.Mock();backend.creation.return_value=20
        guard=mock.Mock();guard.receipt.return_value={"phase":"synthetic"};guard.phase="train"
        optimizer=mock.Mock();loss=SimpleNamespace(backward=mock.Mock(),detach=lambda:4.0)
        native=mock.Mock();native.pid=3000;native.stdin.closed=False;native.wait.return_value=0
        labels=[]
        def held(backend,directory,label,nonce,state,guard,*args,**kwargs):
            labels.append(label);state["last_emitted"]=10.0
        with mock.patch.object(p.obs,"WindowsBackend",return_value=backend),mock.patch.object(p.prior,"LocalProviderGuard",return_value=guard), \
             mock.patch.object(p.dual,"publish_identity"),mock.patch.object(p,"require_control"),mock.patch.object(p.subprocess,"Popen",return_value=native), \
             mock.patch.object(p,"held_stage",side_effect=held),mock.patch.object(p.prior,"import_packages",return_value=(SimpleNamespace(__version__="torch"),SimpleNamespace(__version__="transformers"))), \
             mock.patch.object(p,"prepare",return_value=(object(),optimizer,[object(),object()],{})) as load, \
             mock.patch.object(p.cost,"forward_loss",side_effect=p.obs.ObserverError("synthetic forward failure") if fail_forward else None,return_value=loss) as forward, \
             mock.patch.object(p.cost,"final_validity",return_value={}) as validity,mock.patch.object(p.cost,"parameter_hash",return_value="b"*64), \
             mock.patch.object(p.time,"perf_counter",return_value=10.0):
            if fail_forward:
                with self.assertRaisesRegex(p.obs.ObserverError,"synthetic forward failure"):p.worker(directory,NONCE,Path("cmd"),Path("provider"),Path("model"),Path("fixture"),60,60)
            else:p.worker(directory,NONCE,Path("cmd"),Path("provider"),Path("model"),Path("fixture"),60,60)
        return directory,labels,optimizer,load,forward,validity,loss,native
    def test_mock_worker_performs_exactly_two_dense_updates_and_no_extra_training(self):
        directory,labels,optimizer,load,forward,validity,loss,native=self.run_worker()
        self.assertEqual(labels,list(p.STAGES));load.assert_called_once();self.assertEqual(forward.call_count,2)
        self.assertEqual(optimizer.zero_grad.call_count,2);self.assertEqual(loss.backward.call_count,2);self.assertEqual(optimizer.step.call_count,2)
        self.assertEqual(len(list(directory.glob('*-operation.json'))),8);self.assertEqual(len(list(directory.glob('*-housekeeping.json'))),2)
        self.assertEqual(json.loads((directory/'worker-completed.json').read_text())["optimizer_steps"],2)
        validity.assert_called_once();native.stdin.write.assert_called_once_with(b'done\r\n')
    def test_failure_stops_before_optimizer_or_final_validation_and_preserves_failure(self):
        directory,labels,optimizer,load,forward,validity,loss,native=self.run_worker(fail_forward=True)
        self.assertTrue((directory/'worker-failure.json').exists());optimizer.step.assert_not_called();validity.assert_not_called()
        self.assertNotIn('postvalidation',labels);native.stdin.write.assert_not_called()

class ControlTests(unittest.TestCase):
    def test_worker_acceptance_includes_bound_creation_and_rejects_wrong_index(self):
        env=p.base.envelope(NONCE,'controller',command='create-native',purpose=p.CONTROL_PURPOSE,observer_duty_authorized=True,role_policy_admitted=True,
            role_decision_index=0,role_decision_label='before_native',control_index=0,emitted_perf_counter=1.0)
        state={'next_index':0,'last_emitted':0.,'creation_filetime':20}
        with mock.patch.object(p.work,'wait_receipt',return_value=env),mock.patch.object(p.time,'perf_counter',return_value=2.),mock.patch.object(p.obs,'write_new') as write:
            p.require_control(Path('unused'),'create-native.json',NONCE,'create-native','before_native',0,state,60,60)
        self.assertEqual(write.call_args.args[1]['creation_filetime'],20);self.assertEqual(state['next_index'],1)
        with mock.patch.object(p.work,'wait_receipt',return_value=env),mock.patch.object(p.time,'perf_counter',return_value=2.),mock.patch.object(p.obs,'write_new') as write,self.assertRaises(p.obs.ObserverError):
            p.require_control(Path('unused'),'create-native.json',NONCE,'create-native','before_native',0,state,60,60)
        write.assert_not_called()
    def test_active_sampler_source_is_memory_only_no_snapshot_no_repeated_training_budget(self):
        tree=ast.parse(p.SCRIPT.read_text());f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='observe_operation')
        calls=[ast.unparse(n.func) for n in ast.walk(f) if isinstance(n,ast.Call)]
        self.assertNotIn('job.backend.snapshot',calls);self.assertNotIn('p.cost.training_loop',calls)
        self.assertIn('report["training_deadline_perf_counter"]',ast.get_source_segment(p.SCRIPT.read_text(),f))

def barrier_fixture():
    actual=SimpleNamespace(pid=2000,creation_filetime=20)
    rows=[]
    for i,(filename,command,label,index) in enumerate(p.CONTROL_PLAN):
        envelope=p.base.envelope(NONCE,"controller",command=command,purpose=p.CONTROL_PURPOSE,
            observer_duty_authorized=True,role_policy_admitted=True,role_decision_index=index,
            role_decision_label=label,control_index=i,emitted_perf_counter=5.0 if i<25 else 13.0)
        rows.append({"filename":filename,**envelope})
    ack=p.base.envelope(NONCE,"worker",filename="postvalidation-continue.json",creation_filetime=20,
        control_envelope={k:v for k,v in rows[24].items() if k!="filename"},
        accepted_perf_counter=11.0,next_control_index=25)
    ack["pid"]=actual.pid
    report={"nonce":NONCE,"case_deadline_perf_counter":100.0,"suite_deadline_perf_counter":200.0,
        "worker_identity":{"self_receipt":{"pid":2000,"creation_filetime":20}},
        "native_descendant":{"os_identity":{"pid":3000,"creation_filetime":30}},
        "controller_controls":rows[:25]}
    return actual,report,ack,rows[25]


class EndBarrierTests(unittest.TestCase):
    def success(self,accepted=11.0,start=10.0,end=12.0,case_end=100.0,suite_end=200.0):
        actual,report,ack,finish=barrier_fixture();ack["accepted_perf_counter"]=accepted
        report.update(case_deadline_perf_counter=case_end,suite_deadline_perf_counter=suite_end)
        with mock.patch.object(p.time,"perf_counter",side_effect=[start,end]), \
                mock.patch.object(p.work,"wait_receipt",return_value=ack) as call:
            REAL_AWAIT(Path("synthetic-unused"),NONCE,report,actual,case_end,suite_end)
        return actual,report,ack,finish,call

    def complete(self):
        actual,report,ack,finish,_=self.success()
        report["controller_controls"].append(finish)
        report["worker_controls"]=[{} for _ in range(24)]+[ack,{}]
        report["prefinish_live_members"]=[{"pid":2000,"creation_filetime":20,"alive":True,"job_member":True,"verified_perf_counter":12.2},
            {"pid":3000,"creation_filetime":30,"alive":True,"job_member":True,"verified_perf_counter":12.3}]
        return actual,report

    def test_authenticated_delayed_ack_saves_exact_original_receipt_and_deadline(self):
        actual,report,ack,_,call=self.success()
        barrier=report["postvalidation_continue_ack_barrier"]
        self.assertTrue(barrier["passed"]);self.assertIs(barrier["accepted_receipt"],ack)
        self.assertEqual(barrier["worker_identity"],{"pid":2000,"creation_filetime":20})
        self.assertEqual((barrier["requested_perf_counter"],barrier["started_perf_counter"],barrier["completed_perf_counter"],barrier["wall_seconds"]),(5,10,12,2))
        self.assertEqual(set(barrier),set(p.END_BARRIER["success_receipt_fields"]))
        call.assert_called_once_with(Path("synthetic-unused"),"postvalidation-continue-accepted.json",15.0,NONCE,"worker")

    def test_ack_may_arrive_before_wait_start_and_at_deadline(self):
        self.assertTrue(self.success(accepted=9.0)[1]["postvalidation_continue_ack_barrier"]["passed"])
        self.assertTrue(self.success(accepted=11.0,end=15.0)[1]["postvalidation_continue_ack_barrier"]["passed"])

    def test_wait_deadline_is_minimum_original_case_suite_and_five_seconds(self):
        for case_end,suite_end,expected in ((13.0,200.0,13.0),(100.0,14.0,14.0),(100.0,200.0,15.0)):
            with self.subTest(case_end=case_end,suite_end=suite_end):
                *_,call=self.success(case_end=case_end,suite_end=suite_end)
                self.assertEqual(call.call_args.args[2],expected)

    def test_missing_ack_timeout_is_single_wait_failed_receipt_and_no_deadline_renewal(self):
        actual,report,_,_=barrier_fixture()
        with mock.patch.object(p.time,"perf_counter",side_effect=[10.0,15.0]), \
                mock.patch.object(p.work,"wait_receipt",side_effect=p.obs.ObserverError("message deadline exceeded")) as call, \
                self.assertRaisesRegex(p.obs.ObserverError,"deadline"):
            REAL_AWAIT(Path("unused"),NONCE,report,actual,100,200)
        call.assert_called_once();barrier=report["postvalidation_continue_ack_barrier"]
        self.assertFalse(barrier["passed"]);self.assertEqual(barrier["deadline_perf_counter"],15.0)
        self.assertEqual(barrier["wall_seconds"],5.0);self.assertIn("error",barrier)

    def test_premature_future_wrong_identity_or_envelope_ack_never_authorizes(self):
        changes=[("nonce","b"*64),("role","controller"),("pid",2001),("creation_filetime",21),("pid",True),
            ("filename","postloop-continue.json"),("next_control_index",12),("next_control_index",True),
            ("accepted_perf_counter",4.99),("accepted_perf_counter",12.01),("accepted_perf_counter",float("nan")),
            ("accepted_perf_counter",True),("control_envelope",{}),("extra",False)]
        for field,value in changes:
            actual,report,ack,_=barrier_fixture();ack[field]=value
            with self.subTest(field=field,value=value),mock.patch.object(p.time,"perf_counter",return_value=12.0), \
                    mock.patch.object(p.work,"wait_receipt",return_value=ack),self.assertRaises(p.obs.ObserverError):
                REAL_AWAIT(Path("unused"),NONCE,report,actual,100,200)
            self.assertFalse(report["postvalidation_continue_ack_barrier"]["passed"])
            self.assertIs(report["postvalidation_continue_ack_barrier"]["accepted_receipt"],ack)

    def test_no_budget_wrong_request_or_retained_identity_rejects_before_wait(self):
        for change in ("case_deadline","request_future","request_count","controller_pid","worker_creation","control_index"):
            actual,report,_,_=barrier_fixture()
            if change=="case_deadline":report["case_deadline_perf_counter"]=10.0
            if change=="request_future":report["controller_controls"][24]["emitted_perf_counter"]=11.0
            if change=="request_count":report["controller_controls"].pop()
            if change=="controller_pid":report["controller_controls"][24]["pid"]+=1
            if change=="worker_creation":report["worker_identity"]["self_receipt"]["creation_filetime"]+=1
            if change=="control_index":report["controller_controls"][24]["control_index"]=True
            with self.subTest(change=change),mock.patch.object(p.time,"perf_counter",return_value=10.0), \
                    mock.patch.object(p.work,"wait_receipt") as call,self.assertRaises(p.obs.ObserverError):
                REAL_AWAIT(Path("unused"),NONCE,report,actual,report["case_deadline_perf_counter"],200)
            call.assert_not_called();self.assertFalse(report["postvalidation_continue_ack_barrier"]["passed"])

    def test_success_source_rechecks_exact_raw_ack_live_identities_and_order(self):
        actual,report=self.complete();p.validate_end_barrier(report,actual)
        for change in ("missing","extra","future","premature","raw_mismatch","wrong_creation","live_early","finish_early","deadline_renewed","native_creation","nonmember"):
            _,report=self.complete();barrier=report["postvalidation_continue_ack_barrier"]
            if change=="missing":report.pop("postvalidation_continue_ack_barrier")
            if change=="extra":barrier["error"]="ignored failure"
            if change=="future":barrier["accepted_receipt"]["accepted_perf_counter"]=12.1
            if change=="premature":barrier["accepted_receipt"]["accepted_perf_counter"]=4.0
            if change=="raw_mismatch":report["worker_controls"][24]=copy.deepcopy(barrier["accepted_receipt"]);report["worker_controls"][24]["next_control_index"]=12
            if change=="wrong_creation":barrier["worker_identity"]["creation_filetime"]=21
            if change=="live_early":report["prefinish_live_members"][0]["verified_perf_counter"]=11.9
            if change=="finish_early":report["controller_controls"][25]["emitted_perf_counter"]=12.1
            if change=="deadline_renewed":barrier["deadline_perf_counter"]=16.0
            if change=="native_creation":report["prefinish_live_members"][1]["creation_filetime"]=31
            if change=="nonmember":report["prefinish_live_members"][0]["job_member"]=False
            with self.subTest(change=change),self.assertRaises(p.obs.ObserverError):p.validate_end_barrier(report,actual)



if __name__=="__main__":unittest.main()
