"""Stdlib mocks/synthetic receipts only; no ML, process, native or socket work."""
import ast
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from experiments import observer_duty_v2 as p

NONCE="a"*64
REAL_AWAIT=p.await_postvalidation_continue


def loop():
    return {"steps_completed":16,"training_target_positions":2048,"training_loop_wall_seconds":1.0,
        "training_loop_cpu_seconds":0.875,"loop_perf_counter_start":1.0,"loop_perf_counter_end":2.0,
        "training_targets_per_second":2048.0,"preupdate_batch_losses_recorded_after_updates":[4.0+i/100 for i in range(16)],
        "time_control":None,"cost_boundary":"fixed helper"}


def observation(index,stamp):
    return {"index":index,"query_started_perf_counter":stamp,"query_completed_perf_counter":stamp+.001,
        "snapshot_started_perf_counter":stamp+.002,"snapshot_completed_perf_counter":stamp+.003,
        "snapshot_process_count":100,"sample":{"pid":2000,"creation_filetime":20,"perf_counter":stamp+.0005,
            "native_cpu_seconds":0.5,"memory":{"resident_bytes":100+index,"private_bytes":200+index,
                "peak_resident_bytes":999999999}}}


def measured(enabled=True):
    return {"sampling_enabled":enabled,"loop_before":{"before_loop_perf_counter":.9},
        "loop_after":{"after_loop_perf_counter":2.1,"loop":loop()},
        "worker_identity":{"self_receipt":{"pid":2000,"creation_filetime":20}},
        "active_window":{"started_perf_counter":.5,"completed_perf_counter":2.5,"poll_count":50,
            "parent_native_cpu_delta_seconds":.125,
            "observations":[observation(i,1.01+i*.02) for i in range(40)] if enabled else []}}


def pair_case(spec):
    value=measured(spec[1]);value.update(id=spec[0],passed=True)
    value["stages"]={"pretrain":{"model":{"initial_parameter_sha256":"a"*64,"schedule_sha256":p.cost.digest(p.schedule()),
        "optimizer_state_entries":0,"intraop_threads":1,"interop_threads":1,"offline_environment":dict(p.prior.OFFLINE_ENV)}},
        "postvalidation":{"validation":{"final_parameter_sha256":"b"*64}}}
    return value


class ContractTests(unittest.TestCase):
    def test_only_end_barrier_functions_change_historical_dense_sampler_and_worker_AST(self):
        def functions(path):
            return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text()).body
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        old=functions(p.ROOT/"experiments/observer_duty_probe.py")
        new=functions(p.SCRIPT)
        changed={name for name in old if old[name]!=new[name]}
        self.assertEqual(changed,{"verify_controls","run_case","validate_freeze"})
        self.assertEqual(set(new)-set(old),{"await_postvalidation_continue","validate_end_barrier"})
        old_protocol=p.obs.read_small(p.ROOT/"fixtures/observer-duty/protocol.json")
        new_protocol=p.obs.read_small(p.ROOT/"fixtures/observer-duty-v2/protocol.json")
        for key in ("config","cases_in_order","control_plan","stages","provider_stage_phases","model","training",
                "provider_custody","pairing","measurement_boundary","active_treatment","active_filter","parent_CPU","identity_cleanup"):
            self.assertEqual(new_protocol[key],old_protocol[key],key)
        self.assertEqual(new_protocol["end_barrier"],p.END_BARRIER)

    def test_new_protocol_exact_inventory_order_and_predeclared_counts(self):
        value=p.obs.read_small(p.ROOT/"fixtures/observer-duty-v2/protocol.json")
        self.assertEqual(value["config"],p.CONFIG);self.assertEqual(value["source_paths"],list(p.SOURCE_PATHS))
        self.assertEqual(value["frozen_dependency_paths"],list(p.DEPENDENCY_PATHS))
        self.assertEqual(value["review_tool_paths"],list(p.REVIEW_TOOL_PATHS))
        self.assertEqual(value["cases_in_order"],[{"id":i,"sampling_enabled":e} for i,e in p.CASES])
        self.assertEqual(value["training"]["schedule"],p.schedule())
        self.assertEqual((value["model"]["planned_model_loads"],value["model"]["planned_optimizer_updates"]),(4,64))
        self.assertEqual(len(p.CONTROL_PLAN),12)

    def test_dense_loop_calls_unchanged_historical_helper_only(self):
        result=loop()
        with mock.patch.object(p.cost,"training_loop",return_value=result) as call:
            self.assertIs(p.dense_loop("model","optimizer",["batch"]*16),result)
        args,kwargs=call.call_args
        self.assertEqual(args,("model","optimizer",["batch"]*16,"token","dense",[]))
        self.assertEqual(kwargs["config"]["token_steps"],16)
        self.assertEqual(kwargs["config"]["max_token_loop_seconds"],15.0)
        self.assertEqual(kwargs["config"]["optimizer"],p.cost.preset_config()["optimizer"])

    def test_deadline_never_renews_case_or_suite(self):
        with mock.patch.object(p.time,"perf_counter",return_value=10):
            self.assertEqual(p.deadline(5,12,20),12);self.assertEqual(p.deadline(5,20,11),11)

    def test_fresh_prepare_uses_pinned_loader_same_seed_and_full_schedule(self):
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
        self.assertIs(actual_model,model);self.assertIs(actual_optimizer,optimizer);self.assertEqual(len(batches),16)
        self.assertEqual(info["schedule"],p.schedule());self.assertEqual(info["optimizer_state_entries"],0)
        self.assertEqual(info["optimizer_type"],"AdamW");self.assertEqual(info["batch_shapes"],[[2,65]]*16)


class MeasurementTests(unittest.TestCase):
    def run_observer(self,enabled,timeout=False):
        class Clock:
            value=0.0
            def now(self):return self.value
        clock=Clock();directory=self.directory
        def release(*args):
            p.obs.write_new(directory/"before-loop.json",{"nonce":NONCE,"role":"worker","pid":2000,"before_loop_perf_counter":.001})
        def sleep(seconds):
            clock.value+=16 if timeout else seconds
            if clock.value>=.14 and not timeout and not (directory/"after-loop.json").exists():
                p.obs.write_new(directory/"after-loop.json",{"nonce":NONCE,"role":"worker","pid":2000,
                    "after_loop_perf_counter":.13,"loop":loop()})
        backend=SimpleNamespace(k=SimpleNamespace(GetCurrentProcess=lambda:1),snapshot=mock.Mock(return_value={1:0,2:1}))
        job=SimpleNamespace(backend=backend)
        report={"sampling_enabled":enabled}
        def sample(*args):
            return {"pid":2000,"creation_filetime":20,"perf_counter":clock.value,
                "native_cpu_seconds":clock.value,"memory":{"resident_bytes":100,"private_bytes":200}}
        with mock.patch.object(p.obs,"ProcessRef",return_value=object()), \
                mock.patch.object(p.work,"native_process_cpu",side_effect=[1.0,1.125]), \
                mock.patch.object(p.work,"parent_sample",side_effect=sample) as sampling, \
                mock.patch.object(p,"control",side_effect=release) as control, \
                mock.patch.object(p.time,"perf_counter",side_effect=clock.now),mock.patch.object(p.time,"sleep",side_effect=sleep):
            if timeout:
                with self.assertRaisesRegex(p.obs.ObserverError,"deadline"):
                    p.observe_training(job,SimpleNamespace(pid=2000),directory,NONCE,report,60,240)
            else:p.observe_training(job,SimpleNamespace(pid=2000),directory,NONCE,report,60,240)
        return report,sampling.call_count,backend.snapshot.call_count,control

    def test_controller_off_polls_without_any_native_sampling_or_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.directory=Path(tmp);report,samples,snapshots,control=self.run_observer(False)
        self.assertEqual((samples,snapshots),(0,0))
        self.assertGreater(report["active_window"]["poll_count"],0)
        self.assertEqual(report["active_window"]["observations"],[])
        self.assertEqual(report["active_window"]["parent_native_cpu_delta_seconds"],.125)
        self.assertEqual(control.call_args.args[1],"pretrain-continue.json")

    def test_controller_on_queries_actual_worker_and_saves_bounded_raw_intervals(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.directory=Path(tmp);report,samples,snapshots,_=self.run_observer(True)
        self.assertGreater(samples,0);self.assertEqual(samples,snapshots)
        self.assertEqual(samples,len(report["active_window"]["observations"]))
        self.assertEqual(report["active_window"]["observations"][0]["snapshot_process_count"],2)

    def test_controller_deadline_fails_once_without_rescue_or_busy_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.directory=Path(tmp);report,samples,snapshots,_=self.run_observer(False,True)
        self.assertEqual((samples,snapshots),(0,0));self.assertNotIn("loop_after",report)

    def test_on_summary_uses_current_samples_and_excludes_boundary_queries(self):
        case=measured()
        rows=case["active_window"]["observations"]
        rows.insert(0,observation(0,.7));rows.append(observation(41,2.2))
        for i,r in enumerate(rows):r["index"]=i
        p.measurement_summary(case)
        self.assertEqual(case["active_observation_indices"],list(range(1,41)))
        self.assertEqual(case["training_memory"]["sampled_current_resident_max_bytes"],139)
        self.assertEqual(case["training_memory"]["sampled_current_private_max_bytes"],239)
        self.assertEqual(case["active_sampling"]["selected_count"],40)
        self.assertGreater(case["active_sampling"]["combined_query_wall_fraction"],0)
        self.assertNotIn("peak_resident_bytes",case["training_memory"])

    def test_off_is_null_and_never_infers_zero_memory(self):
        case=measured(False);p.measurement_summary(case)
        self.assertIsNone(case["training_memory"]);self.assertIsNone(case["active_sampling"])
        self.assertEqual(case["active_observation_indices"],[])
        case=measured(False);case["active_window"]["observations"]=[observation(0,1.2)]
        with self.assertRaisesRegex(p.obs.ObserverError,"OFF"):p.measurement_summary(case)

    def test_wrong_steps_loss_clock_or_window_rejects(self):
        for key,value in (("steps_completed",True),("steps_completed",15),("training_target_positions",128),
                ("training_loop_wall_seconds",.9),("preupdate_batch_losses_recorded_after_updates",[float("nan")]*16)):
            case=measured();case["loop_after"]["loop"][key]=value
            with self.subTest(key=key),self.assertRaises(p.obs.ObserverError):p.measurement_summary(case)
        case=measured();case["loop_after"]["after_loop_perf_counter"]=1.9
        with self.assertRaises(p.obs.ObserverError):p.measurement_summary(case)

    def test_coverage_is_fixed_no_threshold_rescue(self):
        for rows in ([observation(i,1.1+i*.01) for i in range(19)],
                [observation(i,1.01+i*.004) for i in range(20)]):
            case=measured();case["active_window"]["observations"]=rows
            with self.assertRaisesRegex(p.obs.ObserverError,"coverage"):p.measurement_summary(case)

    def test_observation_rejects_wrong_pid_creation_clock_or_noninteger_memory(self):
        for key,value in (("pid",2001),("creation_filetime",21),("perf_counter",float("nan"))):
            case=measured();case["active_window"]["observations"][0]["sample"][key]=value
            with self.subTest(key=key),self.assertRaises(p.obs.ObserverError):p.measurement_summary(case)
        for key,value in (("resident_bytes",True),("private_bytes",-1)):
            case=measured();case["active_window"]["observations"][0]["sample"]["memory"][key]=value
            with self.subTest(key=key),self.assertRaises(p.obs.ObserverError):p.measurement_summary(case)

    def test_pair_ratios_are_descriptive_with_exact_all_four_fidelity_gate(self):
        cases=[pair_case(spec) for spec in p.CASES]
        cases[1]["loop_after"]["loop"]["training_loop_wall_seconds"]=1.2
        cases[2]["loop_after"]["loop"]["training_loop_wall_seconds"]=1.1
        result=p.paired_summary(cases)
        self.assertTrue(result["valid"]);self.assertEqual(result["pairs"][0]["on_off_wall_ratio"],1.2)
        self.assertAlmostEqual(result["geometric_mean_on_off_wall_ratio"],(1.2*1.1)**.5)
        for change in ("initial","final","loss","schedule","optimizer","environment"):
            bad=copy.deepcopy(cases);model=bad[3]["stages"]["pretrain"]["model"]
            if change=="initial":model["initial_parameter_sha256"]="c"*64
            elif change=="final":bad[3]["stages"]["postvalidation"]["validation"]["final_parameter_sha256"]="c"*64
            elif change=="loss":bad[3]["loop_after"]["loop"]["preupdate_batch_losses_recorded_after_updates"][0]+=1e-10
            elif change=="schedule":model["schedule_sha256"]="c"*64
            elif change=="optimizer":model["optimizer_state_entries"]=1
            else:model["offline_environment"]={}
            result=p.paired_summary(bad)
            with self.subTest(change=change):
                self.assertFalse(result["valid"]);self.assertIsNone(result["geometric_mean_on_off_wall_ratio"])
                self.assertTrue(all(r["on_off_wall_ratio"] is None for r in result["pairs"]))
        cases[0]["passed"]=False;self.assertFalse(p.paired_summary(cases)["valid"])
        self.assertFalse(p.paired_summary(list(reversed(cases)))["valid"])


class ControlWorkerTests(unittest.TestCase):
    def report(self):
        return {"role_decisions":[{"label":"before_native","decision_index":0,"admitted":True,"completed_perf_counter":9}],
            "case_deadline_perf_counter":100,"suite_deadline_perf_counter":200}

    def test_emit_accept_authentication_sequence_and_monotonic_time(self):
        with tempfile.TemporaryDirectory() as tmp,mock.patch.object(p.time,"perf_counter",return_value=10):
            directory=Path(tmp);report=self.report();p.control(directory,"create-native.json",NONCE,"create-native",report)
            envelope=p.obs.read_small(directory/"create-native.json")
            state={"next_index":0,"last_emitted":0}
            with mock.patch.object(p.work,"wait_receipt",return_value=envelope):
                p.require_control(directory,"create-native.json",NONCE,"create-native","before_native",0,state,100,200)
            self.assertEqual(state["next_index"],1)
            accepted=p.obs.read_small(directory/"create-native-accepted.json")
            self.assertEqual(accepted["control_envelope"],envelope)
            for field,value in (("observer_duty_authorized",False),("control_index",1),("role_decision_label","other"),
                    ("emitted_perf_counter",11),("purpose","old-suite")):
                bad=copy.deepcopy(envelope);bad[field]=value
                with mock.patch.object(p.work,"wait_receipt",return_value=bad),self.subTest(field=field),self.assertRaises(p.obs.ObserverError):
                    p.require_control(directory,"create-native.json",NONCE,"create-native","before_native",0,
                        {"next_index":0,"last_emitted":0},100,200)

    def test_rejected_or_future_role_and_nonplan_control_never_emit(self):
        for changed in ("rejected","future","wrongplan"):
            report=self.report()
            if changed=="rejected":report["role_decisions"][0]["admitted"]=False
            elif changed=="future":report["role_decisions"][0]["completed_perf_counter"]=11
            with tempfile.TemporaryDirectory() as tmp,mock.patch.object(p.time,"perf_counter",return_value=10), \
                    self.subTest(changed=changed),self.assertRaises(p.obs.ObserverError):
                p.control(Path(tmp),"finish.json" if changed=="wrongplan" else "create-native.json",NONCE,
                    "finish" if changed=="wrongplan" else "create-native",report)

    def worker_context(self,events,denial=False):
        backend=mock.Mock();child=mock.Mock();child.wait.return_value=0;child.stdin.closed=False
        guard=SimpleNamespace(phase="preimport",install=mock.Mock(),receipt=lambda:{"bounded":"synthetic"})
        def phase(value):guard.phase=value
        guard.set_phase=phase
        torch,transformers=SimpleNamespace(__version__="2.9.1+cpu"),SimpleNamespace(__version__="4.57.3")
        def held(*args,**kwargs):events.append(args[2]);guard.set_phase(p.PHASES[args[2]])
        def train(*args):
            events.append("loop")
            if denial:raise PermissionError("synthetic denied event")
            return loop()
        patches=[mock.patch.object(p.obs,"WindowsBackend",return_value=backend),
            mock.patch.object(p.prior,"LocalProviderGuard",return_value=guard),mock.patch.object(p.dual,"publish_identity"),
            mock.patch.object(p,"require_control"),mock.patch.object(p.subprocess,"Popen",return_value=child),
            mock.patch.object(p,"held_stage",side_effect=held),
            mock.patch.object(p.prior,"import_packages",return_value=(torch,transformers)),
            mock.patch.object(p,"prepare",return_value=("model","optimizer",["batch"]*16,{})),
            mock.patch.object(p,"dense_loop",side_effect=train),
            mock.patch.object(p.cost,"final_validity",side_effect=lambda *a:events.append("validation") or {"ok":True}),
            mock.patch.object(p.cost,"parameter_hash",side_effect=lambda *a:events.append("hash") or "b"*64),
            mock.patch.object(p.obs,"write_new",side_effect=lambda path,value:events.append((path.name,value))),
            mock.patch.object(p.time,"perf_counter",return_value=10)]
        for patch in patches:patch.start();self.addCleanup(patch.stop)
        return child,guard

    def test_worker_emits_loop_end_and_holds_memory_before_validation_or_hash(self):
        events=[];child,guard=self.worker_context(events)
        p.worker(Path("unused"),NONCE,Path("cmd.exe"),Path("provider"),Path("model"),Path("fixture"),100,200)
        names=[item[0] if isinstance(item,tuple) else item for item in events]
        order=["pretrain","before-loop.json","loop","after-loop.json","postloop","validation","hash","postvalidation"]
        self.assertEqual(sorted(order,key=names.index),order)
        end=next(v for n,v in (e for e in events if isinstance(e,tuple)) if n=="after-loop.json")
        self.assertEqual(end["loop"],loop());child.stdin.write.assert_called_once_with(b"done\r\n")
        guard.install.assert_called_once()

    def test_worker_failure_retains_guard_phase_and_never_postvalidates(self):
        events=[];self.worker_context(events,True)
        with self.assertRaises(PermissionError):
            p.worker(Path("unused"),NONCE,Path("cmd.exe"),Path("provider"),Path("model"),Path("fixture"),100,200)
        failure=next(v for n,v in (e for e in events if isinstance(e,tuple)) if n=="worker-failure.json")
        self.assertEqual(failure["phase"],"train");self.assertEqual(failure["failure_perf_counter"],10)
        self.assertEqual(failure["provider_guard"],{"bounded":"synthetic"});self.assertNotIn("validation",events)


class FreezeTests(unittest.TestCase):
    def test_freeze_requires_exact_new_source_review_dependencies_provider_and_case_order(self):
        protocol=p.obs.read_small(p.ROOT/"fixtures/observer-duty-v2/protocol.json")
        protocol["predeclared_at"]="2026-01-01T00:00:00+00:00"
        system=Path(p.os.environ.get("SystemRoot","mock-system"))/"System32"
        paths={"launcher":Path("launcher/python.exe"),"base_python":Path("base/python.exe"),
            "native":system/"cmd.exe","conhost":system/"conhost.exe"}
        provider=Path("mock-site/urllib3/util/connection.py")
        freeze={"protocol_sha256":"a"*64,"frozen_at":"2026-01-01T00:00:01+00:00",
            "new_source_files_sha256":{n:"a"*64 for n in p.SOURCE_PATHS},
            "frozen_dependency_files_sha256":{n:"a"*64 for n in p.DEPENDENCY_PATHS},
            "review_tools_sha256":{n:"a"*64 for n in p.REVIEW_TOOL_PATHS},
            "executables_sha256":{n:"a"*64 for n in paths},
            "executable_path_sha256":{n:p.dual.path_hash(v) for n,v in paths.items()},
            "provider_source_sha256":p.prior.PROVIDER_SOURCE_SHA256,
            "provider_source_path_sha256":p.dual.path_hash(provider)}
        def check():return p.validate_freeze("protocol","freeze",paths,provider,"model",p.ROOT/"fixtures/activation-cost")
        with mock.patch.dict(p.os.environ,{"SystemRoot":str(system.parent)}), \
                mock.patch.object(p.obs,"read_small",side_effect=lambda v:protocol if v=="protocol" else freeze), \
                mock.patch.object(p.obs,"sha256_file",return_value="a"*64), \
                mock.patch.object(p.prior,"source_digest",return_value=p.prior.PROVIDER_SOURCE_SHA256), \
                mock.patch.object(p.cost,"verify_model_assets"),mock.patch.object(p.cost,"validate_fixture"):
            check()
            for field in ("new_source_files_sha256","frozen_dependency_files_sha256","review_tools_sha256",
                    "executables_sha256","executable_path_sha256"):
                saved=freeze[field];freeze[field]={}
                with self.subTest(field=field),self.assertRaises(p.obs.ObserverError):check()
                freeze[field]=saved
            for field in ("provider_source_sha256","provider_source_path_sha256"):
                saved=freeze[field];freeze[field]="b"*64
                with self.subTest(field=field),self.assertRaises(p.obs.ObserverError):check()
                freeze[field]=saved
            saved=protocol["end_barrier"];protocol["end_barrier"]={}
            with self.assertRaises(p.obs.ObserverError):check()
            protocol["end_barrier"]=saved
            protocol["cases_in_order"].reverse()
            with self.assertRaises(p.obs.ObserverError):check()


def barrier_fixture():
    actual=SimpleNamespace(pid=2000,creation_filetime=20)
    rows=[]
    for i,(filename,command,label,index) in enumerate(p.CONTROL_PLAN):
        envelope=p.base.envelope(NONCE,"controller",command=command,purpose=p.CONTROL_PURPOSE,
            observer_duty_authorized=True,role_policy_admitted=True,role_decision_index=index,
            role_decision_label=label,control_index=i,emitted_perf_counter=5.0 if i<11 else 13.0)
        rows.append({"filename":filename,**envelope})
    ack=p.base.envelope(NONCE,"worker",filename="postvalidation-continue.json",
        control_envelope={k:v for k,v in rows[10].items() if k!="filename"},
        accepted_perf_counter=11.0,next_control_index=11)
    ack["pid"]=actual.pid
    report={"nonce":NONCE,"case_deadline_perf_counter":100.0,"suite_deadline_perf_counter":200.0,
        "worker_identity":{"self_receipt":{"pid":2000,"creation_filetime":20}},
        "native_descendant":{"os_identity":{"pid":3000,"creation_filetime":30}},
        "controller_controls":rows[:11]}
    return actual,report,ack,rows[11]


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
        report["worker_controls"]=[{} for _ in range(10)]+[ack,{}]
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
        changes=[("nonce","b"*64),("role","controller"),("pid",2001),("pid",True),
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
            if change=="request_future":report["controller_controls"][10]["emitted_perf_counter"]=11.0
            if change=="request_count":report["controller_controls"].pop()
            if change=="controller_pid":report["controller_controls"][10]["pid"]+=1
            if change=="worker_creation":report["worker_identity"]["self_receipt"]["creation_filetime"]+=1
            if change=="control_index":report["controller_controls"][10]["control_index"]=True
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
            if change=="raw_mismatch":report["worker_controls"][10]=copy.deepcopy(barrier["accepted_receipt"]);report["worker_controls"][10]["next_control_index"]=12
            if change=="wrong_creation":barrier["worker_identity"]["creation_filetime"]=21
            if change=="live_early":report["prefinish_live_members"][0]["verified_perf_counter"]=11.9
            if change=="finish_early":report["controller_controls"][11]["emitted_perf_counter"]=12.1
            if change=="deadline_renewed":barrier["deadline_perf_counter"]=16.0
            if change=="native_creation":report["prefinish_live_members"][1]["creation_filetime"]=31
            if change=="nonmember":report["prefinish_live_members"][0]["job_member"]=False
            with self.subTest(change=change),self.assertRaises(p.obs.ObserverError):p.validate_end_barrier(report,actual)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.output=Path(self.tmp.name)
        self.paths={name:Path(name+".exe") for name in ("launcher","base_python","native","conhost")}
        self.freeze={"executables_sha256":{n:"a"*64 for n in self.paths},"executable_path_sha256":{n:"b"*64 for n in self.paths},
            "provider_source_sha256":p.prior.PROVIDER_SOURCE_SHA256,"provider_source_path_sha256":"f"*64}
        self.launcher=SimpleNamespace(pid=1000,creation_filetime=10)
        self.actual=SimpleNamespace(pid=2000,creation_filetime=20)
        self.native=SimpleNamespace(pid=3000,creation_filetime=30)
        self.job=mock.Mock();self.job.start_suspended.return_value=self.launcher
        self.job.authenticate.return_value=(self.actual,[])
        self.fail_load=False;self.hidden=False
        def inventory(job,launcher,actual,native,report,label):
            count=3 if native is None else 5
            report["censuses"].append({"label":label,"processes":[{"pid":1000*i,"creation_filetime":10*i} for i in range(1,count+1)]})
        def held(job,launcher,actual,native,directory,label,nonce,report,*args):
            if label=="pretrain" and self.fail_load:raise p.obs.ObserverError("synthetic load failure")
            report.setdefault("stages",{})[label]={}
            report.setdefault("memory_brackets",{})[label]={}
            inventory(job,launcher,actual,native,report,label)
        def cleanup(*args):
            if self.hidden:
                path=self.output/"pair1_off"/"worker-failure.json"
                if not path.exists():p.obs.write_new(path,{"nonce":NONCE,"role":"worker","pid":2000,"error":"hidden"})
            return {"all_retained_handles_exited":True,"job_active_count":0,
                "exit_codes":[{"pid":i*1000,"creation_filetime":i*10,"exit_code":0} for i in range(1,6)]}
        def message(directory,name,*args):
            if name=="worker-completed.json":
                return {"pid":2000,"native_exit_code":0,"native_released_nonempty_line":True,"model_loads":1,"optimizer_steps":16}
            return {"pid":2000,"creation_filetime":20}
        patches=[mock.patch.object(p.obs,"WindowsJob",return_value=self.job),
            mock.patch.object(p.prior,"os_image",return_value={}),mock.patch.object(p.dual,"verify_self_executable",return_value={}),
            mock.patch.object(p,"inventory",side_effect=inventory),mock.patch.object(p,"read_held",side_effect=held),
            mock.patch.object(p.work,"wait_receipt",side_effect=message),
            mock.patch.object(p.work,"verify_native_child",return_value=(self.native,{})),
            mock.patch.object(p,"control") ,mock.patch.object(p,"observe_training"),
            mock.patch.object(p,"validate_case"),mock.patch.object(p,"verify_controls"),
            mock.patch.object(p,"await_postvalidation_continue"),
            mock.patch.object(p.work,"live_member_receipts",return_value=[]),
            mock.patch.object(p.work,"cleanup",side_effect=cleanup),mock.patch.object(p.secrets,"token_hex",return_value=NONCE),
            mock.patch.object(p.time,"perf_counter",return_value=10)]
        for patch in patches:patch.start();self.addCleanup(patch.stop)

    def run_case(self):
        return p.run_case(p.CASES[0],self.paths,Path("provider"),Path("model"),Path("fixture"),self.freeze,self.output,250)

    def test_mock_controller_reuses_retained_worker_job_native_and_exact_cleanup(self):
        result=self.run_case()
        self.assertTrue(result["passed"],result.get("error"));self.assertNotIn("_paths",result)
        self.assertTrue(result["cleanup_exact_retained_identity_set"])
        args=self.job.start_suspended.call_args.args[0]
        self.assertIn("--provider-source",args);self.assertIn("-S",args)
        self.job.close.assert_called_once();self.job.close_refs.assert_called_once()
        self.job.terminate.assert_not_called()

    def test_mock_controller_load_failure_stops_measurement_and_preserves_cleanup(self):
        self.fail_load=True;result=self.run_case()
        self.assertFalse(result["passed"]);self.assertIn("load failure",result["error"])
        self.assertTrue(result["failure_cleanup"]["all_retained_handles_exited"])
        p.observe_training.assert_not_called();self.job.terminate.assert_called_once()

    def test_controller_delayed_ack_must_complete_before_live_checks_and_finish(self):
        clock=SimpleNamespace(value=10.0);events=[];saved={}
        p.time.perf_counter.side_effect=lambda:clock.value
        def emit(directory,filename,nonce,command,report):
            rows=report.setdefault("controller_controls",[])
            while p.CONTROL_PLAN[len(rows)][:2]!=(filename,command):
                missing=p.CONTROL_PLAN[len(rows)];self.assertEqual(missing[1],"parent-sampled")
                rows.append({"filename":missing[0],**p.base.envelope(nonce,"controller",command=missing[1],
                    purpose=p.CONTROL_PURPOSE,observer_duty_authorized=True,role_policy_admitted=True,
                    role_decision_label=missing[2],role_decision_index=missing[3],control_index=len(rows),emitted_perf_counter=clock.value)})
            index=len(rows)
            planned=p.CONTROL_PLAN[index]
            self.assertEqual((filename,command),planned[:2])
            if filename=="finish.json":self.assertEqual(events[-1],"live-after-ack")
            report["controller_controls"].append({"filename":filename,**p.base.envelope(nonce,"controller",
                command=command,purpose=p.CONTROL_PURPOSE,observer_duty_authorized=True,role_policy_admitted=True,
                role_decision_label=planned[2],role_decision_index=planned[3],control_index=index,
                emitted_perf_counter=clock.value)})
            saved["report"]=report;events.append(filename)
        def wait(directory,filename,until,nonce,*args):
            if filename=="postvalidation-continue-accepted.json":
                self.assertEqual(events[-1],"postvalidation-continue.json")
                p.work.live_member_receipts.assert_not_called()
                clock.value=10.2
                ack=p.base.envelope(nonce,"worker",filename="postvalidation-continue.json",
                    control_envelope={k:v for k,v in saved["report"]["controller_controls"][10].items() if k!="filename"},
                    accepted_perf_counter=10.1,next_control_index=11)
                ack["pid"]=2000;events.append("ack-consumed");return ack
            if filename=="worker-completed.json":
                return {"pid":2000,"native_exit_code":0,"native_released_nonempty_line":True,"model_loads":1,"optimizer_steps":16}
            return {"pid":2000,"creation_filetime":20}
        def live(*args):
            self.assertEqual(events[-1],"ack-consumed")
            self.assertTrue(saved["report"]["postvalidation_continue_ack_barrier"]["passed"])
            clock.value=10.3;events.append("live-after-ack");return []
        p.control.side_effect=emit;p.work.wait_receipt.side_effect=wait
        p.observe_training.side_effect=lambda j,a,d,n,r,*args:p.control(d,"pretrain-continue.json",n,"continue",r)
        p.await_postvalidation_continue.side_effect=REAL_AWAIT;p.work.live_member_receipts.side_effect=live
        result=self.run_case();self.assertTrue(result["passed"],result.get("error"))
        self.assertEqual(events[-4:],["postvalidation-continue.json","ack-consumed","live-after-ack","finish.json"])
        barrier=result["postvalidation_continue_ack_barrier"]
        self.assertEqual((barrier["started_perf_counter"],barrier["completed_perf_counter"]),(10,10.2))

    def test_controller_ack_failure_prevents_live_and_finish_then_cleans_up(self):
        p.await_postvalidation_continue.side_effect=p.obs.ObserverError("synthetic missing final acknowledgment")
        result=self.run_case();self.assertFalse(result["passed"])
        self.assertIn("missing final acknowledgment",result["error"])
        p.work.live_member_receipts.assert_not_called()
        self.assertTrue(all(c.args[1]!="finish.json" for c in p.control.call_args_list))
        self.job.terminate.assert_called_once();self.assertTrue(result["failure_cleanup"]["all_retained_handles_exited"])

    def test_controller_real_ack_wait_timeout_wrong_pid_and_future_ack_cannot_reach_live_or_finish(self):
        for mode in ("timeout","wrong_pid","future"):
            with tempfile.TemporaryDirectory() as tmp,self.subTest(mode=mode):
                self.output=Path(tmp);saved={};seen_final_wait=[];p.control.reset_mock();p.work.live_member_receipts.reset_mock()
                self.job.terminate.reset_mock()
                def emit(directory,filename,nonce,command,report):
                    rows=report.setdefault("controller_controls",[])
                    while p.CONTROL_PLAN[len(rows)][:2]!=(filename,command):
                        missing=p.CONTROL_PLAN[len(rows)];self.assertEqual(missing[1],"parent-sampled")
                        rows.append({"filename":missing[0],**p.base.envelope(nonce,"controller",command=missing[1],
                            purpose=p.CONTROL_PURPOSE,observer_duty_authorized=True,role_policy_admitted=True,
                            role_decision_label=missing[2],role_decision_index=missing[3],control_index=len(rows),emitted_perf_counter=10.0)})
                    index=len(rows);spec=p.CONTROL_PLAN[index]
                    rows.append({"filename":filename,**p.base.envelope(nonce,"controller",command=command,
                        purpose=p.CONTROL_PURPOSE,observer_duty_authorized=True,role_policy_admitted=True,
                        role_decision_label=spec[2],role_decision_index=spec[3],control_index=index,emitted_perf_counter=10.0)})
                    saved["report"]=report
                def wait(directory,filename,until,nonce,*args):
                    if filename=="postvalidation-continue-accepted.json":
                        seen_final_wait.append(filename)
                        if mode=="timeout":raise p.obs.ObserverError("synthetic acknowledgment deadline exceeded")
                        value=p.base.envelope(nonce,"worker",filename="postvalidation-continue.json",
                            control_envelope={k:v for k,v in saved["report"]["controller_controls"][10].items() if k!="filename"},
                            accepted_perf_counter=10.1 if mode=="future" else 10.0,next_control_index=11)
                        value["pid"]=2001 if mode=="wrong_pid" else 2000;return value
                    return {"pid":2000,"creation_filetime":20}
                p.control.side_effect=emit;p.work.wait_receipt.side_effect=wait
                p.observe_training.side_effect=lambda j,a,d,n,r,*args:p.control(d,"pretrain-continue.json",n,"continue",r)
                p.await_postvalidation_continue.side_effect=REAL_AWAIT
                result=self.run_case();self.assertFalse(result["passed"])
                self.assertEqual(seen_final_wait,["postvalidation-continue-accepted.json"])
                self.assertFalse(result["postvalidation_continue_ack_barrier"]["passed"])
                p.work.live_member_receipts.assert_not_called()
                self.assertTrue(all(c.args[1]!="finish.json" for c in p.control.call_args_list))
                self.job.terminate.assert_called_once();self.assertTrue(result["failure_cleanup"]["all_retained_handles_exited"])

    def test_hidden_worker_failure_cannot_pass_and_exact_raw_receipt_is_copied(self):
        self.hidden=True;result=self.run_case()
        self.assertFalse(result["passed"]);self.assertEqual(result["worker_failure_receipt"]["pid"],2000)
        self.assertIn("hidden worker failure",result["error"])

    def test_handle_close_error_rejects_an_otherwise_normal_case(self):
        self.job.close.side_effect=RuntimeError("synthetic close failure")
        result=self.run_case();self.assertFalse(result["passed"]);self.assertIn("job_close_error",result)
