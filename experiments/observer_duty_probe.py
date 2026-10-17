"""Counterbalanced observer duty during fixed dense CPU training.

Imports are stdlib only. The reviewed root freeze owns the sole actual study.
Historical integrations and their scientific negatives remain unchanged.
"""
from __future__ import annotations
import argparse
import datetime as dt
import math
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import training_observer_v3 as prior
from experiments import process_observer as obs
from experiments import process_observer_probe as base
from experiments import workload_observer_probe as work
from experiments import dual_identity_census as dual
from experiments import role_policy_probe as role
from experiments import activation_cost_probe as cost

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path(__file__).resolve()
EXPERIMENT_ID = "windows-pinned-pythia-observer-duty-v1"
SOURCE_PATHS = ("experiments/observer_duty_probe.py", "tests/test_observer_duty_probe.py")
REVIEW_TOOL_PATHS = ("scripts/audit_observer_duty.py", "tests/test_observer_duty_auditor.py")
DEPENDENCY_PATHS = tuple(dict.fromkeys((*prior.DEPENDENCY_PATHS, "experiments/training_observer_v3.py",
    "fixtures/training-observer-v3/protocol.json", "fixtures/training-observer-v3/implementation.json")))
CONFIG = {"seed":503,"optimizer_steps":16,"intraop_threads":1,"interop_threads":1,
    "train_blocks":128,"batch_size":2,"sequence_input_tokens":64,
    "sampler_interval_seconds":0.02,"maximum_recorded_sample_gap_seconds":0.5,
    "minimum_active_samples":20,"maximum_active_observations":800,"maximum_active_polls":800,
    "case_timeout_seconds":60.0,"total_timeout_seconds":240.0,"cleanup_timeout_seconds":4.0,
    "import_timeout_seconds":20.0,"load_timeout_seconds":25.0,"training_timeout_seconds":15.0,
    "barrier_timeout_seconds":5.0,"memory_bracket_tolerance_bytes":4194304}
CASES = (("pair1_off",False),("pair1_on",True),("pair2_on",True),("pair2_off",False))
STAGES = ("preimport","postimport","pretrain","postloop","postvalidation")
PHASES = dict(zip(STAGES,("preimport","postimport","postload","postupdate","complete")))
CONTROL_PURPOSE = "pinned observer duty v1; fixed dense measurement controls"
CONTROL_PLAN = [("create-native.json","create-native","before_native",0)]
for _i,_label in enumerate(STAGES,1):
    CONTROL_PLAN.extend([(_label+"-parent-done.json","parent-sampled",_label,_i),
        (_label+"-continue.json","continue",_label,_i)])
CONTROL_PLAN.append(("finish.json","finish","postvalidation",5))
CONTROL_PLAN = tuple(CONTROL_PLAN)


def finite(v): return type(v) in (int,float) and math.isfinite(v)
def deadline(seconds,case_end,suite_end): return min(time.perf_counter()+seconds,case_end,suite_end)
def schedule(): return cost.batch_schedule(128,16,2,503)


def control(directory,filename,nonce,command,report):
    index=len(report.setdefault("controller_controls",[]));decision=report["role_decisions"][-1]
    now=time.perf_counter()
    if (index>=len(CONTROL_PLAN) or (filename,command,decision["label"],decision["decision_index"])!=CONTROL_PLAN[index]
        or decision.get("admitted") is not True or not finite(decision.get("completed_perf_counter"))
        or decision["completed_perf_counter"]>now
        or now>min(report["case_deadline_perf_counter"],report["suite_deadline_perf_counter"])):
        raise obs.ObserverError("observer duty control lacks exact current role admission/order")
    value=base.envelope(nonce,"controller",command=command,purpose=CONTROL_PURPOSE,
        observer_duty_authorized=True,role_policy_admitted=True,role_decision_index=decision["decision_index"],
        role_decision_label=decision["label"],control_index=index,emitted_perf_counter=now)
    obs.write_new(directory/filename,value)
    report["controller_controls"].append({"filename":filename,**value})


def require_control(directory,filename,nonce,command,label,index,state,case_end,suite_end):
    value=work.wait_receipt(directory,filename,deadline(5,case_end,suite_end),nonce,"controller")
    now=time.perf_counter();next_index=state["next_index"]
    if (next_index>=len(CONTROL_PLAN) or (filename,command,label,index)!=CONTROL_PLAN[next_index]
        or value.get("purpose")!=CONTROL_PURPOSE or value.get("observer_duty_authorized") is not True
        or value.get("role_policy_admitted") is not True or value.get("command")!=command
        or type(value.get("control_index")) is not int or value["control_index"]!=next_index
        or type(value.get("role_decision_index")) is not int or value["role_decision_index"]!=index
        or value.get("role_decision_label")!=label or not finite(value.get("emitted_perf_counter"))
        or not state["last_emitted"]<=value["emitted_perf_counter"]<=now<=min(case_end,suite_end)):
        raise obs.ObserverError("observer duty worker rejected control custody")
    state.update(next_index=next_index+1,last_emitted=value["emitted_perf_counter"])
    obs.write_new(directory/filename.replace(".json","-accepted.json"),base.envelope(nonce,"worker",
        filename=filename,control_envelope=value,accepted_perf_counter=now,next_control_index=next_index+1))


def held_stage(backend,directory,label,nonce,state,guard,case_end,suite_end,**details):
    guard.set_phase(PHASES[label]);index=STAGES.index(label)+1
    obs.write_new(directory/(label+"-ready.json"),base.envelope(nonce,"worker",stage=label,
        stage_ready_perf_counter=time.perf_counter(),provider_guard=guard.receipt(),
        native_thread_count=work.native_thread_count(backend,os.getpid()),**details))
    obs.write_new(directory/(label+"-before.json"),base.envelope(nonce,"worker",**backend.self_reading()))
    require_control(directory,label+"-parent-done.json",nonce,"parent-sampled",label,index,state,case_end,suite_end)
    obs.write_new(directory/(label+"-after.json"),base.envelope(nonce,"worker",**backend.self_reading()))
    require_control(directory,label+"-continue.json",nonce,"continue",label,index,state,case_end,suite_end)


def prepare(torch,model_dir,fixture):
    cost.verify_model_assets(model_dir);manifest,_,_=cost.validate_fixture(fixture,verify_holdout=False)
    blocks=cost.load_blocks(Path(fixture)/"train.json","train",128)
    started=time.perf_counter();model=cost.load_model(model_dir,503);loaded=time.perf_counter()
    optimizer=cost.optimizer_for(model);tokens=torch.tensor(blocks,dtype=torch.long)
    batches=[tokens[indices] for indices in schedule()]
    initial=cost.parameter_hash(model)
    info={"model_id":cost.MODEL_ID,"model_revision":cost.MODEL_REVISION,"seed":503,
        "train_sha256":manifest["train_sha256"],"schedule":schedule(),"schedule_sha256":cost.digest(schedule()),
        "initial_parameter_sha256":initial,"optimizer_state_entries":len(optimizer.state),"optimizer_type":"AdamW",
        "parameter_tensors":len(list(model.parameters())),"trainable_parameter_count":sum(v.numel() for v in model.parameters()),
        "batch_shapes":[list(v.shape) for v in batches],"intraop_threads":torch.get_num_threads(),
        "interop_threads":torch.get_num_interop_threads(),"deterministic_algorithms":torch.are_deterministic_algorithms_enabled(),
        "model_load_started_perf_counter":started,"model_load_completed_perf_counter":loaded,
        "loader_local_files_only":True,"trust_remote_code":False,"device":"cpu","dtype":"torch.float32",
        "optimizer":cost.preset_config()["optimizer"],"holdout_opened":False,"offline_environment":dict(prior.OFFLINE_ENV)}
    return model,optimizer,batches,info


def dense_loop(model,optimizer,batches):
    config=cost.preset_config();config.update(token_steps=16,max_token_loop_seconds=15.0)
    return cost.training_loop(model,optimizer,batches,"token","dense",[],config=config)


def worker(directory,nonce,native,provider_source,model_dir,fixture,case_end,suite_end):
    backend=obs.WindowsBackend();child=None
    state={"next_index":0,"last_emitted":0.0}
    guard=prior.LocalProviderGuard(provider_source,True);guard.install()
    try:
        dual.publish_identity(backend,directory,"worker-ready.json",nonce,"worker")
        require_control(directory,"create-native.json",nonce,"create-native","before_native",0,state,case_end,suite_end)
        started=time.perf_counter()
        child=subprocess.Popen([str(native),*work.NATIVE_ARGUMENTS],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,close_fds=True,creationflags=0x08000000,shell=False)
        obs.write_new(directory/"native-ready.json",base.envelope(nonce,"worker",native_pid=child.pid,
            launch_started_perf_counter=started,launch_completed_perf_counter=time.perf_counter(),
            command_arguments=list(work.NATIVE_ARGUMENTS),close_fds=True,stdin_anonymous_pipe=True,
            shell=False,creationflags=0x08000000,stdout_devnull=True,stderr_devnull=True))
        held_stage(backend,directory,"preimport",nonce,state,guard,case_end,suite_end,
            torch_imported="torch" in sys.modules,transformers_imported="transformers" in sys.modules)
        guard.set_phase("import");started=time.perf_counter();torch,transformers=prior.import_packages();ended=time.perf_counter()
        held_stage(backend,directory,"postimport",nonce,state,guard,case_end,suite_end,
            import_started_perf_counter=started,import_completed_perf_counter=ended,
            torch_version=str(torch.__version__),transformers_version=str(transformers.__version__))
        guard.set_phase("load");model,optimizer,batches,info=prepare(torch,model_dir,fixture)
        held_stage(backend,directory,"pretrain",nonce,state,guard,case_end,suite_end,model=info)
        guard.set_phase("train")
        obs.write_new(directory/"before-loop.json",base.envelope(nonce,"worker",
            before_loop_perf_counter=time.perf_counter(),provider_guard=guard.receipt()))
        loop=dense_loop(model,optimizer,batches)
        guard.set_phase("postupdate")
        obs.write_new(directory/"after-loop.json",base.envelope(nonce,"worker",
            after_loop_perf_counter=time.perf_counter(),loop=loop,provider_guard=guard.receipt()))
        held_stage(backend,directory,"postloop",nonce,state,guard,case_end,suite_end)
        validation_started=time.perf_counter()
        validity=cost.final_validity(model,optimizer,16);final=cost.parameter_hash(model)
        held_stage(backend,directory,"postvalidation",nonce,state,guard,case_end,suite_end,
            validation={"started_perf_counter":validation_started,"completed_perf_counter":time.perf_counter(),
                "final_validity":validity,"final_parameter_sha256":final,
                "no_holdout_evaluation":True,"no_checkpoint_written":True})
        require_control(directory,"finish.json",nonce,"finish","postvalidation",5,state,case_end,suite_end)
        child.stdin.write(b"done\r\n");child.stdin.flush();child.stdin.close()
        budget=deadline(5,case_end,suite_end)-time.perf_counter()
        if budget<=0 or child.wait(timeout=budget)!=0:raise obs.ObserverError("native normal completion failed")
        obs.write_new(directory/"worker-completed.json",base.envelope(nonce,"worker",model_loads=1,optimizer_steps=16,
            native_exit_code=0,native_released_nonempty_line=True,provider_guard=guard.receipt()))
    except BaseException as error:
        obs.write_new(directory/"worker-failure.json",base.envelope(nonce,"worker",provider_guard=guard.receipt(),
            phase=guard.phase,failure_perf_counter=time.perf_counter(),
            error=base.public_error(error,directory,native,provider_source,model_dir,fixture,sys.executable)))
        raise
    finally:
        if child is not None and child.stdin is not None and not child.stdin.closed:child.stdin.close()


def inventory(job,launcher,actual,native,report,label):
    known={launcher.pid:(launcher.creation_filetime,"launcher"),actual.pid:(actual.creation_filetime,"base_python")}
    if native is not None:known[native.pid]=(native.creation_filetime,"native")
    _,decision=prior.timed_call("held_role_census_and_liveness",lambda:role.policy_stage(job,launcher,known,
        report["_paths"],report["executables_sha256"],report,label,"observer-duty",report.get("pinned_auxiliaries",{}),
        report["case_deadline_perf_counter"],report["suite_deadline_perf_counter"]),report["parent_query_costs"])
    if decision.get("admitted") is not True:raise obs.ObserverError("exact frozen role policy rejected duty boundary")
    report["pinned_auxiliaries"]=decision["pinned_auxiliaries"]


def read_held(job,launcher,actual,native,directory,label,nonce,report,case_end,suite_end,timeout=5):
    ready=work.wait_receipt(directory,label+"-ready.json",deadline(timeout,case_end,suite_end),nonce)
    if (ready["pid"]!=actual.pid or ready.get("stage")!=label or type(ready.get("native_thread_count")) is not int
        or ready["native_thread_count"]<1 or not prior.validate_provider(ready.get("provider_guard"),PHASES[label],1)):
        raise obs.ObserverError("held duty identity/thread/provider receipt differs")
    report.setdefault("stages",{})[label]=ready
    before=work.wait_receipt(directory,label+"-before.json",deadline(5,case_end,suite_end),nonce)
    parent=prior.timed_call("boundary_worker_memory_and_cpu",lambda:work.parent_sample(job,actual,report["samples"]),report["parent_query_costs"])
    inventory(job,launcher,actual,native,report,label)
    control(directory,label+"-parent-done.json",nonce,"parent-sampled",report)
    after=work.wait_receipt(directory,label+"-after.json",deadline(5,case_end,suite_end),nonce)
    comparison=obs.compare_memory_bracket(before,parent,after,CONFIG["memory_bracket_tolerance_bytes"])
    report.setdefault("memory_brackets",{})[label]={"self_before":before,"parent":parent,"self_after":after,"comparison":comparison}
    if not comparison["passed"]:raise obs.ObserverError("held duty memory bracket mismatch")


def observe_training(job,actual,directory,nonce,report,case_end,suite_end):
    parent=obs.ProcessRef(job.backend,job.backend.k.GetCurrentProcess())
    start=time.perf_counter();cpu0=work.native_process_cpu(job.backend,parent)
    window={"started_perf_counter":start,"parent_native_cpu_start_seconds":cpu0,"poll_count":0,"observations":[]}
    report["active_window"]=window
    control(directory,"pretrain-continue.json",nonce,"continue",report)
    until=deadline(15,case_end,suite_end);next_due=time.perf_counter()
    while True:
        now=time.perf_counter()
        if now>=until:raise obs.ObserverError("active duty training deadline exhausted")
        if (directory/"worker-failure.json").exists():raise obs.ObserverError("worker failed during duty measurement")
        if (directory/"after-loop.json").exists():break
        window["poll_count"]+=1
        if window["poll_count"]>800:raise obs.ObserverError("active duty polling bound exhausted")
        if report["sampling_enabled"]:
            rows=window["observations"]
            if len(rows)>=800:raise obs.ObserverError("active duty observation bound exhausted")
            q0=time.perf_counter();sample=work.parent_sample(job,actual,[]);q1=time.perf_counter()
            s0=time.perf_counter();parents=job.backend.snapshot();s1=time.perf_counter()
            rows.append({"index":len(rows),"query_started_perf_counter":q0,"query_completed_perf_counter":q1,
                "sample":sample,"snapshot_started_perf_counter":s0,"snapshot_completed_perf_counter":s1,
                "snapshot_process_count":len(parents)})
        next_due+=0.02
        now=time.perf_counter()
        if next_due<=now:next_due=now+0.02
        time.sleep(min(max(0,next_due-now),max(0,until-now)))
    window["parent_native_cpu_end_seconds"]=work.native_process_cpu(job.backend,parent)
    window["completed_perf_counter"]=time.perf_counter()
    window["parent_native_cpu_delta_seconds"]=window["parent_native_cpu_end_seconds"]-cpu0
    window["wall_seconds"]=window["completed_perf_counter"]-start
    for key,filename in (("loop_before","before-loop.json"),("loop_after","after-loop.json")):
        value=obs.validate_message(obs.read_small(directory/filename),nonce,"worker")
        if value["pid"]!=actual.pid:raise obs.ObserverError("loop signal worker identity differs")
        report[key]=value


def measurement_summary(case):
    loop=case["loop_after"]["loop"];start,end=loop["loop_perf_counter_start"],loop["loop_perf_counter_end"]
    if (not finite(start) or not finite(end) or not 0<end-start<=15
        or not math.isclose(loop.get("training_loop_wall_seconds",-1),end-start,rel_tol=0,abs_tol=1e-12)
        or loop.get("steps_completed")!=16 or type(loop.get("steps_completed")) is not int
        or loop.get("training_target_positions")!=2048 or len(loop.get("preupdate_batch_losses_recorded_after_updates",[]))!=16
        or not finite(loop.get("training_loop_cpu_seconds")) or loop["training_loop_cpu_seconds"]<0
        or not all(finite(v) for v in loop["preupdate_batch_losses_recorded_after_updates"])):
        raise obs.ObserverError("fixed sixteen-update loop receipt differs")
    before,after=case["loop_before"],case["loop_after"];window=case["active_window"]
    if not window["started_perf_counter"]<=before["before_loop_perf_counter"]<=start<=end<=after["after_loop_perf_counter"]<=window["completed_perf_counter"]:
        raise obs.ObserverError("before/full-loop/after signals outside active window")
    rows=window["observations"]
    identity=case["worker_identity"]["self_receipt"]
    previous=window["started_perf_counter"]
    if (type(window.get("poll_count")) is not int or not 0<=window["poll_count"]<=800
        or len(rows)>800 or not finite(window.get("parent_native_cpu_delta_seconds"))
        or window["parent_native_cpu_delta_seconds"]<0):
        raise obs.ObserverError("active polling/query/CPU bounds differ")
    for index,row in enumerate(rows):
        sample=row["sample"]
        stamps=[row[k] for k in ("query_started_perf_counter","query_completed_perf_counter","snapshot_started_perf_counter","snapshot_completed_perf_counter")]
        if (row.get("index")!=index or type(row.get("index")) is not int or not all(finite(v) for v in stamps)
            or not previous<=stamps[0]<=sample["perf_counter"]<=stamps[1]<=stamps[2]<=stamps[3]<=window["completed_perf_counter"]
            or sample["pid"]!=identity["pid"] or sample["creation_filetime"]!=identity["creation_filetime"]
            or any(type(sample["memory"].get(k)) is not int or sample["memory"][k]<0 for k in ("resident_bytes","private_bytes"))
            or type(row.get("snapshot_process_count")) is not int or row["snapshot_process_count"]<1):
            raise obs.ObserverError("active observation identity/clock/current reading differs")
        previous=stamps[3]
    selected=[r for r in rows if start<=r["query_started_perf_counter"]<=r["query_completed_perf_counter"]
        <=r["snapshot_started_perf_counter"]<=r["snapshot_completed_perf_counter"]<=end]
    case["active_observation_indices"]=[r["index"] for r in selected]
    if not case["sampling_enabled"]:
        if rows:raise obs.ObserverError("OFF case contains active queries")
        case["training_memory"]=None;case["active_sampling"]=None
        return
    stamps=[r["sample"]["perf_counter"] for r in selected]
    gap=max(b-a for a,b in zip([start]+stamps,[*stamps,end]))
    if len(selected)<20 or gap>0.5:raise obs.ObserverError("ON actual-loop sample coverage below frozen gate")
    case["training_memory"]={"sampled_current_resident_max_bytes":max(r["sample"]["memory"]["resident_bytes"] for r in selected),
        "sampled_current_private_max_bytes":max(r["sample"]["memory"]["private_bytes"] for r in selected),
        "boundary":"lower bounds on process current readings during full dense loop, not backward/full peak or memory saving"}
    querywall=sum(r["query_completed_perf_counter"]-r["query_started_perf_counter"] for r in selected)
    snapshotwall=sum(r["snapshot_completed_perf_counter"]-r["snapshot_started_perf_counter"] for r in selected)
    case["active_sampling"]={"selected_count":len(selected),"maximum_gap_including_boundaries_seconds":gap,
        "realized_samples_per_second":len(selected)/(end-start),"memory_cpu_query_wall_seconds":querywall,
        "snapshot_wall_seconds":snapshotwall,"combined_query_wall_fraction":(querywall+snapshotwall)/(end-start)}


def validate_case(report):
    model=report["stages"]["pretrain"]["model"];v=report["stages"]["postvalidation"]["validation"]
    if (model.get("model_id")!=cost.MODEL_ID or model.get("model_revision")!=cost.MODEL_REVISION
        or model.get("seed")!=503 or model.get("schedule")!=schedule() or model.get("schedule_sha256")!=cost.digest(schedule())
        or model.get("optimizer_state_entries")!=0 or type(model.get("optimizer_state_entries")) is not int
        or model.get("optimizer_type")!="AdamW" or model.get("parameter_tensors")!=76 or model.get("trainable_parameter_count")!=14067712
        or model.get("train_sha256")!="8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681"
        or model.get("batch_shapes")!=[[2,65]]*16 or model.get("intraop_threads")!=1 or model.get("interop_threads")!=1
        or any(type(model.get(k)) is not int for k in ("seed","intraop_threads","interop_threads","parameter_tensors","trainable_parameter_count"))
        or model.get("deterministic_algorithms") is not True or model.get("optimizer")!=cost.preset_config()["optimizer"]
        or model.get("loader_local_files_only") is not True or model.get("trust_remote_code") is not False
        or model.get("device")!="cpu" or model.get("dtype")!="torch.float32" or model.get("holdout_opened") is not False
        or model.get("offline_environment")!=dict(prior.OFFLINE_ENV) or not prior.is_hash(model.get("initial_parameter_sha256"))
        or v.get("final_validity",{}).get("optimizer_counters")!=[16]*76
        or any(type(n) is not int for n in v.get("final_validity",{}).get("optimizer_counters",[]))
        or v.get("final_validity",{}).get("final_parameter_gradient_moments_finite") is not True
        or not prior.is_hash(v.get("final_parameter_sha256")) or v["final_parameter_sha256"]==model["initial_parameter_sha256"]
        or v.get("no_holdout_evaluation") is not True or v.get("no_checkpoint_written") is not True):
        raise obs.ObserverError("duty model/fresh optimizer/final sixteen-step contract differs")
    postloop=report["memory_brackets"]["postloop"]["self_after"]["perf_counter"]
    if not report["loop_after"]["after_loop_perf_counter"]<=postloop<=v["started_perf_counter"]<=v["completed_perf_counter"]:
        raise obs.ObserverError("postvalidation overlaps isolated training memory boundary")
    source={"package_relative_path":prior.PROVIDER_SOURCE_RELATIVE_PATH,"sha256":prior.PROVIDER_SOURCE_SHA256,
        "normalized_path_sha256":report["provider_source_path_sha256"]}
    cumulative=None
    receipts=[(PHASES[label],report["stages"][label]["provider_guard"]) for label in STAGES]
    receipts.extend([("train",report["loop_before"]["provider_guard"]),("postupdate",report["loop_after"]["provider_guard"]),
        ("complete",report["healthy_completion"]["provider_guard"])])
    for phase,value in receipts:
        if not prior.validate_provider(value,phase,1) or value["provider_source"]!=source:raise obs.ObserverError("provider source/policy changed")
        if phase!="preimport":
            if cumulative is None:cumulative=value["diagnostic_events"]
            elif cumulative!=value["diagnostic_events"]:raise obs.ObserverError("provider cumulative identity changed")
    imported=report["stages"]["postimport"]
    if not imported["import_started_perf_counter"]<=cumulative[0]["perf_counter"]<=imported["import_completed_perf_counter"]:
        raise obs.ObserverError("capability probe outside import interval")
    pre=report["stages"]["preimport"]
    if pre.get("torch_imported") is not False or pre.get("transformers_imported") is not False:raise obs.ObserverError("ML imported before admission")
    if imported.get("torch_version")!=prior.CONFIG["torch_version"] or imported.get("transformers_version")!=prior.CONFIG["transformers_version"]:raise obs.ObserverError("ML version differs")
    measurement_summary(report);report["provider_custody_verified"]=True


def verify_controls(directory,report,actual):
    rows=report["controller_controls"]
    if len(rows)!=12:raise obs.ObserverError("fixed duty control count differs")
    report["worker_controls"]=[]
    for index,row in enumerate(rows):
        accepted=obs.validate_message(obs.read_small(directory/row["filename"].replace(".json","-accepted.json")),report["nonce"],"worker")
        envelope={k:v for k,v in row.items() if k!="filename"}
        if (accepted["pid"]!=actual.pid or accepted.get("filename")!=row["filename"]
            or accepted.get("control_envelope")!=envelope or accepted.get("next_control_index")!=index+1
            or not row["emitted_perf_counter"]<=accepted.get("accepted_perf_counter",-1)<=report["case_deadline_perf_counter"]):
            raise obs.ObserverError("saved duty control acceptance differs")
        report["worker_controls"].append({"filename":row["filename"],**accepted})
    actions=((0,report["native_descendant"]["launch_receipt"]["launch_started_perf_counter"]),
        (2,report["stages"]["postimport"]["import_started_perf_counter"]),
        (4,report["stages"]["pretrain"]["model"]["model_load_started_perf_counter"]),
        (6,report["loop_before"]["before_loop_perf_counter"]),
        (8,report["stages"]["postvalidation"]["validation"]["started_perf_counter"]))
    for index,stamp in actions:
        if report["worker_controls"][index]["accepted_perf_counter"]>stamp:raise obs.ObserverError("action precedes exact duty authorization")
    report["control_custody_verified"]=True


def run_case(spec,paths,provider_source,model_dir,fixture,freeze,output,suite_end):
    case_id,enabled=spec;directory=output/case_id;directory.mkdir()
    start=time.perf_counter();case_end=min(start+60,suite_end);nonce=secrets.token_hex(32)
    report={"id":case_id,"sampling_enabled":enabled,"nonce":nonce,"started_at":base.utc_now(),"started_perf_counter":start,"passed":False,
        "case_deadline_perf_counter":case_end,"suite_deadline_perf_counter":suite_end,"censuses":[],"role_decisions":[],
        "samples":[],"parent_query_costs":[],"executables_sha256":freeze["executables_sha256"],
        "executable_path_sha256":freeze["executable_path_sha256"],"provider_source_sha256":freeze["provider_source_sha256"],
        "provider_source_path_sha256":freeze["provider_source_path_sha256"],"_paths":paths}
    job=actual=None
    try:
        if start>=suite_end:raise obs.ObserverError("suite deadline before duty launch")
        job=obs.WindowsJob()
        args=[str(paths["launcher"]),"-S",str(SCRIPT),"--worker","--directory",str(directory),"--nonce",nonce,
            "--native",str(paths["native"]),"--provider-source",str(provider_source),"--model-dir",str(model_dir),
            "--fixture",str(fixture),"--case-end",str(case_end),"--suite-end",str(suite_end)]
        launcher=job.start_suspended(args,cwd=ROOT)
        report["launcher"]={"pid":launcher.pid,"creation_filetime":launcher.creation_filetime,"assigned_while_suspended":True,"job_handle_inherited":False}
        ready=work.wait_receipt(directory,"worker-ready.json",deadline(5,case_end,suite_end),nonce)
        actual,ancestry=job.authenticate(ready,nonce,"worker",launcher)
        if actual.pid==launcher.pid:raise obs.ObserverError("venv launcher equals actual interpreter")
        report["worker_identity"]={"self_receipt":ready,"verified_ancestry":ancestry,"launcher_differs_from_interpreter":True,
            "os_image":prior.os_image(job.backend,actual,paths["base_python"],freeze["executables_sha256"]["base_python"]),
            **dual.verify_self_executable(ready,"worker",paths,freeze["executables_sha256"])}
        report["launcher"]["os_image"]=prior.os_image(job.backend,launcher,paths["launcher"],freeze["executables_sha256"]["launcher"])
        inventory(job,launcher,actual,None,report,"before_native");control(directory,"create-native.json",nonce,"create-native",report)
        native_ready=work.wait_receipt(directory,"native-ready.json",deadline(5,case_end,suite_end),nonce)
        native,report["native_descendant"]=work.verify_native_child(job,actual,native_ready,paths["native"],freeze["executables_sha256"]["native"])
        for label,seconds in (("preimport",5),("postimport",20),("pretrain",25)):
            read_held(job,launcher,actual,native,directory,label,nonce,report,case_end,suite_end,seconds)
            if label!="pretrain":control(directory,label+"-continue.json",nonce,"continue",report)
        observe_training(job,actual,directory,nonce,report,case_end,suite_end)
        for label in ("postloop","postvalidation"):
            read_held(job,launcher,actual,native,directory,label,nonce,report,case_end,suite_end)
            control(directory,label+"-continue.json",nonce,"continue",report)
        report["prefinish_live_members"]=work.live_member_receipts(job,actual,native)
        control(directory,"finish.json",nonce,"finish",report)
        done=work.wait_receipt(directory,"worker-completed.json",deadline(5,case_end,suite_end),nonce)
        report["healthy_completion"]=done
        if done["pid"]!=actual.pid or done.get("native_exit_code")!=0 or done.get("native_released_nonempty_line") is not True or done.get("model_loads")!=1 or done.get("optimizer_steps")!=16:raise obs.ObserverError("normal duty completion differs")
        report["cleanup"]=work.cleanup(job,case_end,suite_end);prior.verify_cleanup(report,"healthy")
        if (directory/"worker-failure.json").exists():raise obs.ObserverError("hidden worker failure rejects duty case")
        validate_case(report);verify_controls(directory,report,actual)
        report["outcome"]="normal_completion"
        report["passed"]=time.perf_counter()<=case_end
    except BaseException as error:
        report["error"]=base.public_error(error,directory,output,*paths.values(),provider_source,model_dir,fixture)
        if job is not None:
            try:job.terminate();report["failure_cleanup"]=work.cleanup(job,case_end,suite_end)
            except BaseException as cleanup_error:report["cleanup_error"]=base.public_error(cleanup_error)
    finally:
        failure_path=directory/"worker-failure.json"
        if failure_path.exists():
            report["passed"]=False
            try:
                failure=obs.validate_message(obs.read_small(failure_path),nonce,"worker")
                if actual is not None and failure["pid"]!=actual.pid:raise obs.ObserverError("failure actual PID differs")
                report["worker_failure_receipt"]=failure
            except BaseException as error:report["worker_failure_custody_error"]=base.public_error(error,directory)
        if job is not None:
            for key,action in (("job_close_error",job.close),("process_handle_close_error",job.close_refs)):
                try:action()
                except BaseException as error:report[key]=base.public_error(error);report["passed"]=False
    report.pop("_paths",None);report["completed_at"]=base.utc_now();report["completed_perf_counter"]=time.perf_counter();report["wall_seconds"]=report["completed_perf_counter"]-start
    if report["completed_perf_counter"]>case_end:report["passed"]=False;report["case_wall_budget_exceeded"]=True
    return report


def paired_summary(cases):
    if (len(cases)!=4 or [(c.get("id"),c.get("sampling_enabled")) for c in cases]!=list(CASES)
        or not all(c.get("passed") is True for c in cases)):
        return {"valid":False,"pairs":[],"geometric_mean_on_off_wall_ratio":None,"reason":"one or more fixed cases failed; no rescue"}
    def trajectory(c):
        model=c["stages"]["pretrain"]["model"]
        return (model["initial_parameter_sha256"],model["schedule_sha256"],model["optimizer_state_entries"],
            model["intraop_threads"],model["interop_threads"],model["offline_environment"],
            c["stages"]["postvalidation"]["validation"]["final_parameter_sha256"],
            c["loop_after"]["loop"]["preupdate_batch_losses_recorded_after_updates"])
    all_matched=all(trajectory(c)==trajectory(cases[0]) for c in cases)
    pairs=[]
    for off_index,on_index in ((0,1),(3,2)):
        off,on=cases[off_index],cases[on_index]
        ratio=on["loop_after"]["loop"]["training_loop_wall_seconds"]/off["loop_after"]["loop"]["training_loop_wall_seconds"]
        pairs.append({"off_case":off["id"],"on_case":on["id"],"exact_trajectory_matched":trajectory(off)==trajectory(on),
            "on_off_wall_ratio":ratio if all_matched else None})
    return {"valid":all_matched,"all_four_trajectories_matched":all_matched,"pairs":pairs,
        "geometric_mean_on_off_wall_ratio":math.sqrt(pairs[0]["on_off_wall_ratio"]*pairs[1]["on_off_wall_ratio"]) if all_matched else None,
        "boundary":"two counterbalanced pairs, descriptive conditional fixed intervention; no population inference or general causal/production claim"}


def validate_freeze(protocol_path,freeze_path,paths,provider_source,model_dir,fixture):
    protocol,freeze=obs.read_small(protocol_path),obs.read_small(freeze_path)
    if (protocol.get("experiment_id")!=EXPERIMENT_ID or protocol.get("config")!=CONFIG
        or protocol.get("cases_in_order")!=[{"id":name,"sampling_enabled":enabled} for name,enabled in CASES]
        or protocol.get("control_plan")!=[{"filename":f,"command":c,"decision_label":l,"decision_index":i} for f,c,l,i in CONTROL_PLAN]
        or protocol.get("source_paths")!=list(SOURCE_PATHS) or protocol.get("frozen_dependency_paths")!=list(DEPENDENCY_PATHS)
        or protocol.get("review_tool_paths")!=list(REVIEW_TOOL_PATHS) or freeze.get("protocol_sha256")!=obs.sha256_file(protocol_path)):
        raise obs.ObserverError("new duty protocol/config/order/inventory not frozen")
    provider=protocol.get("provider_custody",{})
    if (provider.get("policy_id")!=prior.PROVIDER_POLICY_ID or provider.get("provider_config")!=prior.PROVIDER_CONFIG
        or provider.get("provider_source_relative_path")!=prior.PROVIDER_SOURCE_RELATIVE_PATH
        or provider.get("provider_source_sha256")!=prior.PROVIDER_SOURCE_SHA256 or provider.get("frame_scope")!=prior.PROVIDER_FRAME_SCOPE
        or provider.get("native_network_sandbox") is not False or provider.get("external_providers_permitted") is not False
        or protocol.get("model",{}).get("planned_model_loads")!=4 or protocol.get("model",{}).get("planned_optimizer_updates")!=64
        or protocol.get("training",{}).get("schedule")!=schedule()):
        raise obs.ObserverError("duty declared provider/training bounds differ")
    for field,names in (("new_source_files_sha256",SOURCE_PATHS),("frozen_dependency_files_sha256",DEPENDENCY_PATHS),("review_tools_sha256",REVIEW_TOOL_PATHS)):
        if set(freeze.get(field,{}))!=set(names) or any(freeze[field][name]!=obs.sha256_file(ROOT/name) for name in names):raise obs.ObserverError("duty implementation source/review/dependency differs")
    if (freeze.get("executables_sha256")!={key:obs.sha256_file(path) for key,path in paths.items()}
        or freeze.get("executable_path_sha256")!={key:dual.path_hash(path) for key,path in paths.items()}
        or freeze.get("provider_source_sha256")!=prior.PROVIDER_SOURCE_SHA256
        or freeze.get("provider_source_path_sha256")!=dual.path_hash(provider_source)
        or prior.source_digest(provider_source)!=prior.PROVIDER_SOURCE_SHA256
        or Path(provider_source).resolve().parts[-3:]!=("urllib3","util","connection.py")):
        raise obs.ObserverError("duty executable/provider file or opaque path pin differs")
    system32=Path(os.environ["SystemRoot"])/"System32"
    if dual.canonical_path(paths["native"])!=dual.canonical_path(system32/"cmd.exe") or dual.canonical_path(paths["conhost"])!=dual.canonical_path(system32/"conhost.exe"):raise obs.ObserverError("duty exact native System32 images differ")
    declared,frozen=(dt.datetime.fromisoformat(value) for value in (protocol["predeclared_at"],freeze["frozen_at"]))
    if declared.tzinfo is None or frozen.tzinfo is None or not declared<=frozen<=dt.datetime.now(dt.timezone.utc):raise obs.ObserverError("duty freeze chronology invalid")
    if Path(fixture).resolve()!=(ROOT/"fixtures/activation-cost").resolve():raise obs.ObserverError("duty train fixture must be exact frozen path")
    cost.verify_model_assets(model_dir);cost.validate_fixture(fixture,verify_holdout=False)
    return protocol,freeze


def acceptance(paths,provider_source,model_dir,fixture,protocol_path,freeze_path,output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();suite_end=start+240
    report={"schema_version":1,"experiment_id":EXPERIMENT_ID,"started_at":base.utc_now(),"started_perf_counter":start,
        "passed":False,"cases":[],"planned_model_loads":4,"planned_optimizer_updates":64,"platform":platform.platform(),"os_name":os.name,"no_fallback":True,
        "boundaries":["OFF null memory is unobserved, not zero; ON current maxima are sampled lower bounds",
            "loop excludes loading, parameter hashing, postvalidation and held boundary scans; no isolated backward peak",
            "parent CPU window encloses control release and completion polling, wider than worker loop",
            "active Toolhelp query count is global snapshot metadata, not an admitted active role census",
            "two ABBA pairs are descriptive conditional fixed intervention, not general causal/production evidence",
            "no compression/holdout/GPU, no scientific failure rescue; no hard training cap or native network sandbox"]}
    try:
        protocol,freeze=validate_freeze(protocol_path,freeze_path,paths,provider_source,model_dir,fixture)
        report.update(protocol_sha256=obs.sha256_file(protocol_path),implementation_sha256=obs.sha256_file(freeze_path),
            source_sha256=freeze["new_source_files_sha256"],frozen_dependencies_sha256=freeze["frozen_dependency_files_sha256"],
            review_tools_sha256=freeze["review_tools_sha256"],executables_sha256=freeze["executables_sha256"],
            executable_path_sha256=freeze["executable_path_sha256"],provider_source_sha256=freeze["provider_source_sha256"],
            provider_source_path_sha256=freeze["provider_source_path_sha256"],protocol_predeclared_at=protocol["predeclared_at"],implementation_frozen_at=freeze["frozen_at"])
        if os.name!="nt":raise obs.UnsupportedPlatform("Windows only; no uncontained fallback")
        for spec in CASES:report["cases"].append(run_case(spec,paths,provider_source,model_dir,fixture,freeze,output,suite_end))
        report["paired_summary"]=paired_summary(report["cases"])
        report["passed"]=report["paired_summary"]["valid"] and time.perf_counter()<=suite_end
    except BaseException as error:report["error"]=base.public_error(error,output,*paths.values(),provider_source,model_dir,fixture,protocol_path,freeze_path)
    report["completed_at"]=base.utc_now();report["completed_perf_counter"]=time.perf_counter();report["wall_seconds"]=report["completed_perf_counter"]-start
    if report["completed_perf_counter"]>suite_end:report["passed"]=False
    obs.write_new(output/"report.json",report);return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("python","base-python","native","conhost","provider-source","model-dir","fixture","protocol","freeze","output","directory"):
        parser.add_argument("--"+name,type=Path)
    parser.add_argument("--worker",action="store_true");parser.add_argument("--nonce")
    parser.add_argument("--case-end",type=float);parser.add_argument("--suite-end",type=float)
    a=parser.parse_args(argv)
    if a.worker:
        if any(value is None for value in (a.directory,a.nonce,a.native,a.provider_source,a.model_dir,a.fixture,a.case_end,a.suite_end)):parser.error("worker needs directory/nonce/native/provider-source/model-dir/fixture/deadlines")
        obs.validate_nonce(a.nonce);worker(a.directory,a.nonce,a.native,a.provider_source,a.model_dir,a.fixture,a.case_end,a.suite_end);return 0
    if any(value is None for value in (a.python,a.base_python,a.native,a.conhost,a.provider_source,a.model_dir,a.fixture,a.protocol,a.freeze,a.output)):parser.error("acceptance needs exact paths/protocol/freeze/fresh output")
    paths={"launcher":a.python.resolve(),"base_python":a.base_python.resolve(),"native":a.native.resolve(),"conhost":a.conhost.resolve()}
    result=acceptance(paths,a.provider_source.resolve(),a.model_dir.resolve(),a.fixture.resolve(),a.protocol.resolve(),a.freeze.resolve(),a.output.resolve())
    print("observer duty fixed measurement: "+("valid" if result["passed"] else "FAILED"));return 0 if result["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
