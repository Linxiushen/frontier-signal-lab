"""Stage-labelled current memory during one pinned two-update dense AdamW worker.

Imports are stdlib only. The reviewed root freeze owns the sole actual study.
Historical integrations and their scientific negatives remain unchanged.
"""
from __future__ import annotations
import argparse
import datetime as dt
import math
import json
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
EXPERIMENT_ID = "windows-pinned-pythia-phase-current-memory-v1"
SOURCE_PATHS = ("experiments/training_phase_memory.py", "tests/test_training_phase_memory.py")
REVIEW_TOOL_PATHS = ("scripts/audit_training_phase_memory.py", "tests/test_training_phase_memory_auditor.py")
DEPENDENCY_PATHS = tuple(dict.fromkeys((*prior.DEPENDENCY_PATHS,
    "experiments/training_observer_v3.py", "fixtures/training-observer-v3/protocol.json", "fixtures/training-observer-v3/implementation.json",
    "experiments/observer_duty_probe.py", "tests/test_observer_duty_probe.py", "fixtures/observer-duty/protocol.json", "fixtures/observer-duty/implementation.json",
    "scripts/audit_observer_duty.py", "tests/test_observer_duty_auditor.py", "experiments/observer_duty_v2.py", "tests/test_observer_duty_v2.py",
    "fixtures/observer-duty-v2/protocol.json", "fixtures/observer-duty-v2/implementation.json", "scripts/audit_observer_duty_v2.py", "tests/test_observer_duty_v2_auditor.py",
    "experiments/observer_query_treatment.py", "tests/test_observer_query_treatment.py", "fixtures/observer-query-treatment/protocol.json", "fixtures/observer-query-treatment/implementation.json",
    "scripts/audit_observer_query_treatment.py", "tests/test_observer_query_treatment_auditor.py")))
CONFIG = {"seed":503,"optimizer_steps":2,"intraop_threads":1,"interop_threads":1,"train_blocks":128,"batch_size":2,"sequence_input_tokens":64,
    "sampler_interval_seconds":0.02,"maximum_recorded_sample_gap_seconds":0.5,"maximum_active_observations":800,"maximum_active_polls":800,
    "case_timeout_seconds":60.0,"total_timeout_seconds":60.0,"cleanup_timeout_seconds":4.0,"import_timeout_seconds":20.0,"load_timeout_seconds":25.0,
    "training_timeout_seconds":15.0,"barrier_timeout_seconds":5.0,"memory_bracket_tolerance_bytes":4194304}
KINDS = ("zero_grad", "forward_loss", "backward", "optimizer_step")
OPERATIONS = tuple({"id":f"step{step}_{kind}","phase_index":(step-1)*4+i,"step":step,"kind":kind} for step in (1,2) for i,kind in enumerate(KINDS))
OP_IDS = tuple(row["id"] for row in OPERATIONS)
STAGES = ("preimport","postimport","pretrain",*OP_IDS,"postvalidation")
PHASES = {"preimport":"preimport","postimport":"postimport","pretrain":"postload",**{name:"train" for name in OP_IDS},"postvalidation":"complete"}
BOUNDARIES = {name:f"B{i}" for i,name in enumerate(("pretrain",*OP_IDS))}
CATEGORIES = ("trainable_parameters","model_buffers","non_none_parameter_gradients","optimizer_exp_avg","optimizer_exp_avg_sq","optimizer_step_scalar","live_loss_tensor")
CONTROL_PURPOSE = "pinned two-update stage-labelled current memory v1"
CONTROL_PLAN = [("create-native.json","create-native","before_native",0)]
for _i,_label in enumerate(STAGES,1):
    CONTROL_PLAN.extend([(_label+"-parent-done.json","parent-sampled",_label,_i),(_label+"-continue.json","continue",_label,_i)])
CONTROL_PLAN.append(("finish.json","finish","postvalidation",12))
CONTROL_PLAN = tuple(CONTROL_PLAN)
END_BARRIER = {"control_filename":"postvalidation-continue.json","filename":"postvalidation-continue-accepted.json",
    "controller_control_index":24,"worker_next_control_index":25,"timeout_seconds":5.0,
    "worker_identity_fields":["pid","creation_filetime"],
    "acknowledgment_fields":["nonce","role","pid","creation_filetime","filename","control_envelope","accepted_perf_counter","next_control_index"],
    "success_receipt_fields":["control_filename","filename","requested_perf_counter","started_perf_counter","deadline_perf_counter","worker_identity","accepted_receipt","completed_perf_counter","wall_seconds","passed"],
    "order":"request <= acknowledgment <= wait completion <= both retained live checks <= finish emission; acknowledgment may precede wait start",
    "deadline":"min(wait start + original five-second barrier budget, original case deadline, original suite deadline); never renewed"}
LIMITS = ["One instrumented worker, one load, two dense updates; no compression/holdout/quality/GPU result",
    "Eight operation intervals and held boundaries are stage-labelled whole-process current samples, not isolated tensor or backward/full peaks",
    "Holds prolong graph/loss lifetimes; current brackets precede rich primitive inventory; metadata and allocator history perturb later readings",
    "Zero selected phase samples produce null maxima/unknown coverage; time gaps do not bound missed-peak bytes",
    "Tensor logical bytes and per-snapshot unique storage backing differ from native process current readings",
    "B4/B8 follow separately timed scalar/deletion housekeeping; not immediate optimizer-return memory",
    "No off baseline, total monitoring-cost estimate, hard cap, production reliability or native network isolation",
    "Historical v1 ordering rejection, six scientific failures and invalid historical RSS remain; H3/H4 unexecuted"]

def finite(v): return type(v) in (int,float) and math.isfinite(v)


def deadline(seconds,case_end,suite_end): return min(time.perf_counter()+seconds,case_end,suite_end)


def schedule(): return cost.batch_schedule(128,2,2,503)

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
    if filename=="pretrain-continue.json":report["training_deadline_perf_counter"]=min(now+15,report["case_deadline_perf_counter"],report["suite_deadline_perf_counter"])
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
        filename=filename,control_envelope=value,creation_filetime=state["creation_filetime"],accepted_perf_counter=now,next_control_index=next_index+1))



def query_interval(function, **envelope):
    q0=time.perf_counter(); sample=function(); q1=time.perf_counter()
    return {**envelope,"query_started_perf_counter":q0,"query_completed_perf_counter":q1,"sample":sample}


def tensor_inventory(model,optimizer,loss,boundary):
    """Only primitive metadata; backing identities exist within this call only."""
    start=time.perf_counter();rows=[];groups=[];keys={}
    def add(name,category,tensor):
        if tensor is None:return
        shape=list(tensor.shape)
        if len(rows)>=1024 or len(shape)>8 or len(name)>256:raise obs.ObserverError("bounded tensor metadata exceeded")
        storage=tensor.untyped_storage(); nbytes=int(storage.nbytes()); device=str(tensor.device)
        key=(device,int(storage.data_ptr())); sid=keys.get(key)
        if sid is None:
            sid=len(groups);keys[key]=sid;groups.append({"id":sid,"device":device,"backing_nbytes":nbytes,"members":[]})
        if groups[sid]["backing_nbytes"]!=nbytes:raise obs.ObserverError("aliased backing capacity mismatch")
        groups[sid]["members"].append(name)
        numel=int(tensor.numel());width=int(tensor.element_size())
        rows.append({"name":name,"category":category,"shape":shape,"dtype":str(tensor.dtype),"device":device,"numel":numel,
            "element_size_bytes":width,"logical_bytes":numel*width,"storage_offset_elements":int(tensor.storage_offset()),
            "storage_id":sid,"backing_nbytes":nbytes,"requires_grad":bool(tensor.requires_grad),"is_leaf":bool(tensor.is_leaf)})
    names=list(model.named_parameters())
    if len(names)!=76 or len(optimizer.state)>76:raise obs.ObserverError("pinned parameter/state inventory count differs")
    counters=[]
    for name,p in names:
        add("parameters."+name,"trainable_parameters",p);add("gradients."+name,"non_none_parameter_gradients",p.grad)
        state=optimizer.state.get(p,{})
        if state:
            if set(state)!={"step","exp_avg","exp_avg_sq"}:raise obs.ObserverError("unexpected AdamW state keys")
            for field,category in (("exp_avg","optimizer_exp_avg"),("exp_avg_sq","optimizer_exp_avg_sq"),("step","optimizer_step_scalar")):
                add("optimizer."+name+"."+field,category,state[field])
            value=state["step"].item()
            if not finite(value) or value!=int(value):raise obs.ObserverError("optimizer counter is not integral")
            counters.append(int(value))
    buffers=list(model.named_buffers())
    if len(buffers)>256:raise obs.ObserverError("buffer inventory bound exceeded")
    for name,tensor in buffers:add("buffers."+name,"model_buffers",tensor)
    add("loss","live_loss_tensor",loss)
    categories={}
    for category in CATEGORIES:
        selected=[r for r in rows if r["category"]==category]
        ids={r["storage_id"] for r in selected}
        categories[category]={"tensor_count":len(selected),"logical_bytes":sum(r["logical_bytes"] for r in selected),"unique_backing_bytes":sum(groups[i]["backing_nbytes"] for i in ids)}
    end=time.perf_counter()
    return {"boundary_id":boundary,"snapshot_started_perf_counter":start,"snapshot_completed_perf_counter":end,"wall_seconds":end-start,
        "tensors":rows,"storage_groups":groups,"categories":categories,"all_categories_unique_backing_bytes":sum(g["backing_nbytes"] for g in groups),
        "optimizer_state_entries":len(optimizer.state),"optimizer_step_values":counters,"live_loss_tensor":loss is not None,"tensor_count":len(rows),
        "method":"primitive metadata, snapshot-local backing union; activation saves/temporary buffers/input and batch backing/Python/native arenas excluded; not process current or peak"}


def held_stage(backend,directory,label,nonce,state,guard,case_end,suite_end,model=None,optimizer=None,loss=None,**details):
    guard.set_phase(PHASES[label]);index=STAGES.index(label)+1
    env=base.envelope(nonce,"worker",creation_filetime=state["creation_filetime"])
    obs.write_new(directory/(label+"-ready.json"),{**env,"stage":label,"stage_ready_perf_counter":time.perf_counter(),
        "provider_guard":guard.receipt(),"native_thread_count":work.native_thread_count(backend,os.getpid()),**details})
    obs.write_new(directory/(label+"-before.json"),query_interval(backend.self_reading,**env))
    require_control(directory,label+"-parent-done.json",nonce,"parent-sampled",label,index,state,case_end,suite_end)
    obs.write_new(directory/(label+"-after.json"),query_interval(backend.self_reading,**env))
    if label in BOUNDARIES:
        inv=tensor_inventory(model,optimizer,loss,BOUNDARIES[label]);obs.write_new(directory/(label+"-inventory.json"),{**env,**inv})
    require_control(directory,label+"-continue.json",nonce,"continue",label,index,state,case_end,suite_end)


def prepare(torch,model_dir,fixture):
    cost.verify_model_assets(model_dir);manifest,_,_=cost.validate_fixture(fixture,verify_holdout=False)
    blocks=cost.load_blocks(Path(fixture)/"train.json","train",128)
    started=time.perf_counter();model=cost.load_model(model_dir,503);loaded=time.perf_counter()
    optimizer=cost.optimizer_for(model);tokens=torch.tensor(blocks,dtype=torch.long);batches=[tokens[indices] for indices in schedule()]
    initial=cost.parameter_hash(model)
    info={"model_id":cost.MODEL_ID,"model_revision":cost.MODEL_REVISION,"seed":503,"train_sha256":manifest["train_sha256"],
        "schedule":schedule(),"schedule_sha256":cost.digest(schedule()),"initial_parameter_sha256":initial,"optimizer_state_entries":len(optimizer.state),
        "optimizer_type":"AdamW","parameter_tensors":len(list(model.parameters())),"trainable_parameter_count":sum(v.numel() for v in model.parameters()),
        "batch_shapes":[list(v.shape) for v in batches],"intraop_threads":torch.get_num_threads(),"interop_threads":torch.get_num_interop_threads(),
        "deterministic_algorithms":torch.are_deterministic_algorithms_enabled(),"model_load_started_perf_counter":started,"model_load_completed_perf_counter":loaded,
        "loader_local_files_only":True,"trust_remote_code":False,"device":"cpu","dtype":"torch.float32","optimizer":cost.preset_config()["optimizer"],
        "holdout_opened":False,"offline_environment":dict(prior.OFFLINE_ENV)}
    return model,optimizer,batches,info


def worker(directory,nonce,native,provider_source,model_dir,fixture,case_end,suite_end):
    backend=obs.WindowsBackend();child=None
    state={"next_index":0,"last_emitted":0.0,"creation_filetime":backend.creation(backend.k.GetCurrentProcess())}
    guard=prior.LocalProviderGuard(provider_source,True);guard.install()
    try:
        dual.publish_identity(backend,directory,"worker-ready.json",nonce,"worker")
        require_control(directory,"create-native.json",nonce,"create-native","before_native",0,state,case_end,suite_end)
        started=time.perf_counter()
        child=subprocess.Popen([str(native),*work.NATIVE_ARGUMENTS],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,creationflags=0x08000000,shell=False)
        obs.write_new(directory/"native-ready.json",base.envelope(nonce,"worker",creation_filetime=state["creation_filetime"],native_pid=child.pid,
            launch_started_perf_counter=started,launch_completed_perf_counter=time.perf_counter(),command_arguments=list(work.NATIVE_ARGUMENTS),
            close_fds=True,stdin_anonymous_pipe=True,shell=False,creationflags=0x08000000,stdout_devnull=True,stderr_devnull=True))
        held_stage(backend,directory,"preimport",nonce,state,guard,case_end,suite_end,torch_imported="torch" in sys.modules,transformers_imported="transformers" in sys.modules)
        guard.set_phase("import");started=time.perf_counter();torch,transformers=prior.import_packages();ended=time.perf_counter()
        held_stage(backend,directory,"postimport",nonce,state,guard,case_end,suite_end,import_started_perf_counter=started,import_completed_perf_counter=ended,
            torch_version=str(torch.__version__),transformers_version=str(transformers.__version__))
        guard.set_phase("load");model,optimizer,batches,info=prepare(torch,model_dir,fixture)
        held_stage(backend,directory,"pretrain",nonce,state,guard,case_end,suite_end,model=model,optimizer=optimizer,model_info=info)
        training_end=min(state["last_emitted"]+15,case_end,suite_end);loss=None
        for spec in OPERATIONS:
            if time.perf_counter()>=training_end:raise obs.ObserverError("nonrenewable training envelope exhausted")
            guard.set_phase("train");kind=spec["kind"];t0=time.perf_counter();c0=time.process_time()
            if kind=="zero_grad":optimizer.zero_grad(set_to_none=True)
            elif kind=="forward_loss":loss=cost.forward_loss(model,batches[spec["step"]-1],codec=None)
            elif kind=="backward":loss.backward()
            elif kind=="optimizer_step":optimizer.step()
            else:raise obs.ObserverError("undeclared operation")
            c1=time.process_time();t1=time.perf_counter()
            env=base.envelope(nonce,"worker",creation_filetime=state["creation_filetime"])
            op={**env,**spec,"operator_started_perf_counter":t0,"operator_completed_perf_counter":t1,"wall_seconds":t1-t0,
                "worker_process_cpu_start_seconds":c0,"worker_process_cpu_end_seconds":c1,"cpu_seconds":c1-c0,"live_loss_after_operator":loss is not None,"provider_guard":guard.receipt()}
            obs.write_new(directory/(spec["id"]+"-operation.json"),op)
            if kind=="optimizer_step":
                h0=time.perf_counter();value=float(loss.detach())
                if not finite(value):raise obs.ObserverError("nonfinite observed loss")
                del loss;loss=None;h1=time.perf_counter()
                obs.write_new(directory/(spec["id"]+"-housekeeping.json"),{**env,"id":spec["id"],"started_perf_counter":h0,"completed_perf_counter":h1,
                    "wall_seconds":h1-h0,"loss_live_before":True,"loss_live_after":False,"recorded_loss":value})
            if time.perf_counter()>=training_end:raise obs.ObserverError("operation exceeded original training deadline")
            held_stage(backend,directory,spec["id"],nonce,state,guard,case_end,min(suite_end,training_end),model=model,optimizer=optimizer,loss=loss)
        validation_started=time.perf_counter();validity=cost.final_validity(model,optimizer,2);final=cost.parameter_hash(model)
        held_stage(backend,directory,"postvalidation",nonce,state,guard,case_end,suite_end,validation={"started_perf_counter":validation_started,"completed_perf_counter":time.perf_counter(),
            "final_validity":validity,"final_parameter_sha256":final,"no_holdout_evaluation":True,"no_checkpoint_written":True})
        require_control(directory,"finish.json",nonce,"finish","postvalidation",12,state,case_end,suite_end)
        child.stdin.write(b"done\r\n");child.stdin.flush();child.stdin.close()
        budget=deadline(5,case_end,suite_end)-time.perf_counter()
        if budget<=0 or child.wait(timeout=budget)!=0:raise obs.ObserverError("native normal completion failed")
        obs.write_new(directory/"worker-completed.json",base.envelope(nonce,"worker",creation_filetime=state["creation_filetime"],model_loads=1,optimizer_steps=2,
            native_exit_code=0,native_released_nonempty_line=True,provider_guard=guard.receipt()))
    except BaseException as error:
        obs.write_new(directory/"worker-failure.json",base.envelope(nonce,"worker",creation_filetime=state["creation_filetime"],provider_guard=guard.receipt(),phase=guard.phase,
            failure_perf_counter=time.perf_counter(),error=base.public_error(error,directory,native,provider_source,model_dir,fixture,sys.executable)))
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



def validate_query(row,actual):
    q0,q1=row["query_started_perf_counter"],row["query_completed_perf_counter"];sample=row["sample"]
    if "pid" in row and (row["pid"]!=actual.pid or row.get("creation_filetime")!=actual.creation_filetime):raise obs.ObserverError("query envelope identity mismatch")
    if (not finite(q0) or not finite(q1) or not q0<=sample["perf_counter"]<=q1
        or sample.get("pid")!=actual.pid or sample.get("creation_filetime")!=actual.creation_filetime):raise obs.ObserverError("complete query interval/identity mismatch")
    for field in ("resident_bytes","private_bytes"):
        if type(sample["memory"].get(field)) is not int or sample["memory"][field]<0:raise obs.ObserverError("native memory is not nonnegative bytes")


def read_held(job,launcher,actual,native,directory,label,nonce,report,case_end,suite_end,timeout=5):
    ready=work.wait_receipt(directory,label+"-ready.json",deadline(timeout,case_end,suite_end),nonce)
    if (ready["pid"]!=actual.pid or ready.get("creation_filetime")!=actual.creation_filetime or ready.get("stage")!=label
        or type(ready.get("native_thread_count")) is not int or ready["native_thread_count"]<1 or not prior.validate_provider(ready.get("provider_guard"),PHASES[label],1)):
        raise obs.ObserverError("held phase identity/thread/provider differs")
    report.setdefault("stages",{})[label]=ready
    before=work.wait_receipt(directory,label+"-before.json",deadline(5,case_end,suite_end),nonce)
    parent=prior.timed_call("boundary_worker_memory_and_cpu",lambda:query_interval(lambda:work.parent_sample(job,actual,report["samples"])),report["parent_query_costs"])
    inventory(job,launcher,actual,native,report,label);control(directory,label+"-parent-done.json",nonce,"parent-sampled",report)
    after=work.wait_receipt(directory,label+"-after.json",deadline(5,case_end,suite_end),nonce)
    for row in (before,parent,after):validate_query(row,actual)
    ordered=ready["stage_ready_perf_counter"]<=before["query_started_perf_counter"]<=before["query_completed_perf_counter"]<=parent["query_started_perf_counter"]<=parent["query_completed_perf_counter"]<=after["query_started_perf_counter"]<=after["query_completed_perf_counter"]
    comparison=obs.compare_memory_bracket(before["sample"],parent["sample"],after["sample"],CONFIG["memory_bracket_tolerance_bytes"])
    report.setdefault("memory_brackets",{})[label]={"self_before":before,"parent":parent,"self_after":after,"comparison":comparison,"full_interval_ordered":ordered}
    if not ordered or not comparison["passed"]:raise obs.ObserverError("held full-interval memory bracket failed")
    if label in BOUNDARIES:
        inv=work.wait_receipt(directory,label+"-inventory.json",deadline(5,case_end,suite_end),nonce)
        if inv.get("pid")!=actual.pid or inv.get("creation_filetime")!=actual.creation_filetime or inv.get("boundary_id")!=BOUNDARIES[label] or not after["query_completed_perf_counter"]<=inv["snapshot_started_perf_counter"]<=inv["snapshot_completed_perf_counter"]:
            raise obs.ObserverError("logical inventory identity/order differs")
        report.setdefault("inventories",{})[BOUNDARIES[label]]=inv


def observe_operation(job,actual,directory,nonce,report,spec,case_end,suite_end,training_end):
    parent=obs.ProcessRef(job.backend,job.backend.k.GetCurrentProcess());t0=time.perf_counter();cpu0=work.native_process_cpu(job.backend,parent)
    window={"started_perf_counter":t0,"parent_native_cpu_start_seconds":cpu0,"poll_count":0,"observations":[]}
    report.setdefault("active_windows",{})[spec["id"]]=window
    predecessor="pretrain" if spec["phase_index"]==0 else OP_IDS[spec["phase_index"]-1]
    control(directory,predecessor+"-continue.json",nonce,"continue",report)
    until=min(report["training_deadline_perf_counter"],case_end,suite_end);next_due=time.perf_counter();filename=spec["id"]+"-operation.json"
    while not (directory/filename).exists():
        now=time.perf_counter()
        if now>=until:raise obs.ObserverError("original stage-training envelope exhausted")
        if (directory/"worker-failure.json").exists():raise obs.ObserverError("worker failed during phase")
        window["poll_count"]+=1
        if window["poll_count"]>800 or len(window["observations"])>=800:raise obs.ObserverError("finite phase poll/query bound exceeded")
        row=query_interval(lambda:work.parent_sample(job,actual,[]));validate_query(row,actual)
        window["observations"].append({"index":len(window["observations"]),**row,"snapshot_started_perf_counter":None,"snapshot_completed_perf_counter":None,"snapshot_process_count":None})
        next_due+=0.02;now=time.perf_counter()
        if next_due<=now:next_due=now+0.02
        time.sleep(min(max(0,next_due-now),max(0,until-now)))
    window["parent_native_cpu_end_seconds"]=work.native_process_cpu(job.backend,parent);window["completed_perf_counter"]=time.perf_counter()
    window["parent_native_cpu_delta_seconds"]=window["parent_native_cpu_end_seconds"]-cpu0;window["wall_seconds"]=window["completed_perf_counter"]-t0
    value=obs.validate_message(obs.read_small(directory/filename),nonce,"worker")
    if value["pid"]!=actual.pid or value.get("creation_filetime")!=actual.creation_filetime:raise obs.ObserverError("operation identity mismatch")
    report.setdefault("operation_receipts",[]).append(value)
    if spec["kind"]=="optimizer_step":
        value=work.wait_receipt(directory,spec["id"]+"-housekeeping.json",deadline(5,case_end,until),nonce)
        report.setdefault("housekeeping_receipts",[]).append(value)


def phase_summary(spec,operation,window):
    start,end=operation["operator_started_perf_counter"],operation["operator_completed_perf_counter"]
    if not finite(start) or not finite(end) or not 0<=end-start<=15:raise obs.ObserverError("invalid operation interval")
    rows=window["observations"];selected=[r for r in rows if start<=r["query_started_perf_counter"]<=r["sample"]["perf_counter"]<=r["query_completed_perf_counter"]<=end]
    points=[start]+[r["sample"]["perf_counter"] for r in selected]+[end]
    gap=max(b-a for a,b in zip(points,points[1:]));wall=sum(r["query_completed_perf_counter"]-r["query_started_perf_counter"] for r in selected)
    covered=bool(selected) and gap<=0.5
    return {"id":spec["id"],"selected_count":len(selected),"raw_count":len(rows),"selected_indices":[r["index"] for r in selected],"excluded_count":len(rows)-len(selected),"maximum_gap_including_boundaries_seconds":gap,
        "realized_samples_per_second":len(selected)/(end-start) if selected and end>start else None,"query_wall_seconds":wall,
        "query_wall_fraction":wall/(end-start) if selected and end>start else None,
        "sampled_current_resident_max_bytes":max((r["sample"]["memory"]["resident_bytes"] for r in selected),default=None),
        "sampled_current_private_max_bytes":max((r["sample"]["memory"]["private_bytes"] for r in selected),default=None),
        "coverage_status":"finite_sampled_lower_bound" if covered else ("unobserved" if not selected else "inadequate_gap"),"coverage_gate_passed":covered,"missed_peak_bytes_upper_bound":None}


def validate_inventory(inv,index):
    rows=inv["tensors"];groups=inv["storage_groups"];categories=inv["categories"]
    if inv["boundary_id"]!="B"+str(index) or inv["tensor_count"]!=len(rows) or len(rows)>1024 or len({r["name"] for r in rows})!=len(rows):raise obs.ObserverError("inventory shape/count differs")
    for r in rows:
        if r["category"] not in CATEGORIES or r["logical_bytes"]!=r["numel"]*r["element_size_bytes"] or r["numel"]!=math.prod(r["shape"]) or r["backing_nbytes"]!=groups[r["storage_id"]]["backing_nbytes"]:raise obs.ObserverError("logical/backing inventory arithmetic differs")
    for category in CATEGORIES:
        selected=[r for r in rows if r["category"]==category];ids={r["storage_id"] for r in selected}
        if categories[category]!={"tensor_count":len(selected),"logical_bytes":sum(r["logical_bytes"] for r in selected),"unique_backing_bytes":sum(groups[i]["backing_nbytes"] for i in ids)}:raise obs.ObserverError("inventory category sum differs")
    if inv["all_categories_unique_backing_bytes"]!=sum(g["backing_nbytes"] for g in groups):raise obs.ObserverError("inventory union differs")
    gradients=76 if index in (3,4,7,8) else 0;entries=76 if index>=4 else 0;live=index in (2,3,6,7)
    if not (categories["trainable_parameters"]["tensor_count"]==76 and categories["trainable_parameters"]["logical_bytes"]==56270848
        and categories["non_none_parameter_gradients"]["tensor_count"]==gradients and categories["non_none_parameter_gradients"]["logical_bytes"]==(56270848 if gradients else 0)
        and inv["optimizer_state_entries"]==entries and inv["live_loss_tensor"] is live):raise obs.ObserverError("phase logical lifecycle differs")
    for category in ("optimizer_exp_avg","optimizer_exp_avg_sq","optimizer_step_scalar"):
        if categories[category]["tensor_count"]!=entries:raise obs.ObserverError("AdamW state tensor count differs")
    if inv["optimizer_step_values"]!=([2 if index==8 else 1]*76 if entries else []):raise obs.ObserverError("AdamW state step sequence differs")
    if categories["live_loss_tensor"]["tensor_count"]!=int(live):raise obs.ObserverError("loss lifetime metadata differs")
    params={r["name"][11:]:r for r in rows if r["category"]=="trainable_parameters"}
    for r in rows:
        if r["category"] in ("non_none_parameter_gradients","optimizer_exp_avg","optimizer_exp_avg_sq"):
            name=r["name"][10:] if r["category"]=="non_none_parameter_gradients" else r["name"][10:].rsplit(".",1)[0]
            p=params.get(name)
            if not p or any(r[k]!=p[k] for k in ("shape","dtype","device","numel","element_size_bytes")):raise obs.ObserverError("gradient/moment parameter metadata mismatch")
        if r["category"]=="optimizer_step_scalar" and (r["shape"]!=[] or r["dtype"]!="torch.float32" or r["device"]!="cpu"):raise obs.ObserverError("AdamW scalar counter layout differs")

def await_postvalidation_continue(directory,nonce,report,actual,case_end,suite_end):
    """One authenticated wait; no live check or finish is authorized on failure."""
    start=time.perf_counter();until=min(start+5.0,case_end,suite_end)
    barrier={"control_filename":END_BARRIER["control_filename"],"filename":END_BARRIER["filename"],
        "requested_perf_counter":None,"started_perf_counter":start,"deadline_perf_counter":until,
        "worker_identity":{"pid":actual.pid,"creation_filetime":actual.creation_filetime},"passed":False}
    report["postvalidation_continue_ack_barrier"]=barrier
    try:
        rows=report.get("controller_controls",[])
        if (len(rows)!=25 or rows[24].get("filename")!=END_BARRIER["control_filename"]
            or (rows[24].get("command"),rows[24].get("role_decision_label"),rows[24].get("role_decision_index"))!=("continue","postvalidation",12)
            or type(rows[24].get("control_index")) is not int or rows[24]["control_index"]!=24
            or rows[24].get("purpose")!=CONTROL_PURPOSE or rows[24].get("observer_duty_authorized") is not True
            or rows[24].get("role_policy_admitted") is not True
            or not finite(rows[24].get("emitted_perf_counter")) or not rows[24]["emitted_perf_counter"]<=start<until
            or case_end!=report["case_deadline_perf_counter"] or suite_end!=report["suite_deadline_perf_counter"]):
            raise obs.ObserverError("final continue wait lacks exact bounded request")
        envelope={k:v for k,v in rows[24].items() if k!="filename"}
        obs.validate_message(envelope,nonce,"controller")
        if envelope["pid"]!=os.getpid():raise obs.ObserverError("final continue controller PID differs")
        identity=report["worker_identity"]["self_receipt"]
        if any(identity[k]!=v for k,v in barrier["worker_identity"].items()):
            raise obs.ObserverError("final continue retained worker identity differs")
        barrier["requested_perf_counter"]=envelope["emitted_perf_counter"]
        value=work.wait_receipt(directory,END_BARRIER["filename"],until,nonce,"worker")
        ended=time.perf_counter()
        barrier["accepted_receipt"]=value
        obs.validate_message(value,nonce,"worker")
        if (set(value)!=set(END_BARRIER["acknowledgment_fields"]) or value["pid"]!=actual.pid
            or value.get("creation_filetime")!=actual.creation_filetime
            or value.get("filename")!=END_BARRIER["control_filename"] or value.get("control_envelope")!=envelope
            or type(value.get("next_control_index")) is not int or value["next_control_index"]!=25
            or not finite(value.get("accepted_perf_counter"))
            or not envelope["emitted_perf_counter"]<=value["accepted_perf_counter"]<=ended<=until
            or not start<=ended):
            raise obs.ObserverError("final continue acknowledgment identity/envelope/time differs")
        barrier.update(accepted_receipt=value,completed_perf_counter=ended,wall_seconds=ended-start,passed=True)
    except BaseException as error:
        ended=time.perf_counter()
        barrier.update(completed_perf_counter=ended,wall_seconds=ended-start,error=base.public_error(error,directory))
        raise


def validate_end_barrier(report,actual):
    """Recheck saved raw acknowledgment and clocks before producer success."""
    barrier=report.get("postvalidation_continue_ack_barrier",{})
    if set(barrier)!=set(END_BARRIER["success_receipt_fields"]) or barrier.get("passed") is not True:
        raise obs.ObserverError("final continue acknowledgment barrier missing or failed")
    request=report["controller_controls"][24];finish=report["controller_controls"][25]
    envelope={k:v for k,v in request.items() if k!="filename"}
    accepted=barrier["accepted_receipt"]
    obs.validate_message(accepted,report["nonce"],"worker")
    clocks=[barrier[k] for k in ("requested_perf_counter","started_perf_counter","deadline_perf_counter","completed_perf_counter","wall_seconds")]
    identity={"pid":actual.pid,"creation_filetime":actual.creation_filetime}
    self_identity=report["worker_identity"]["self_receipt"]
    if (barrier["control_filename"]!=END_BARRIER["control_filename"] or barrier["filename"]!=END_BARRIER["filename"]
        or barrier["worker_identity"]!=identity or any(self_identity[k]!=v for k,v in identity.items())
        or accepted!=report["worker_controls"][24] or accepted.get("control_envelope")!=envelope
        or accepted["pid"]!=actual.pid or accepted.get("creation_filetime")!=actual.creation_filetime or set(accepted)!=set(END_BARRIER["acknowledgment_fields"])
        or accepted.get("filename")!=END_BARRIER["control_filename"]
        or type(accepted.get("next_control_index")) is not int or accepted["next_control_index"]!=25
        or not all(finite(v) for v in clocks) or not finite(accepted.get("accepted_perf_counter"))
        or barrier["requested_perf_counter"]!=request["emitted_perf_counter"]
        or barrier["deadline_perf_counter"]!=min(barrier["started_perf_counter"]+5.0,report["case_deadline_perf_counter"],report["suite_deadline_perf_counter"])
        or not barrier["requested_perf_counter"]<=barrier["started_perf_counter"]<=barrier["completed_perf_counter"]<=barrier["deadline_perf_counter"]
        or not barrier["requested_perf_counter"]<=accepted["accepted_perf_counter"]<=barrier["completed_perf_counter"]
        or barrier["wall_seconds"]!=barrier["completed_perf_counter"]-barrier["started_perf_counter"]):
        raise obs.ObserverError("saved final continue acknowledgment custody differs")
    members=report.get("prefinish_live_members",[])
    native_id=report["native_descendant"]["os_identity"]
    if (len(members)!=2 or {(m.get("pid"),m.get("creation_filetime")) for m in members}
            !={(actual.pid,actual.creation_filetime),(native_id["pid"],native_id["creation_filetime"])}
        or finish.get("filename")!="finish.json" or finish.get("command")!="finish"
        or not finite(finish.get("emitted_perf_counter"))
        or any(m.get("alive") is not True or m.get("job_member") is not True or not finite(m.get("verified_perf_counter"))
            or not barrier["completed_perf_counter"]<=m["verified_perf_counter"]<=finish["emitted_perf_counter"] for m in members)
        or not finish["emitted_perf_counter"]<=min(report["case_deadline_perf_counter"],report["suite_deadline_perf_counter"])):
        raise obs.ObserverError("final continue acknowledgment/live/finish order differs")



def verify_controls(directory,report,actual):
    rows=report["controller_controls"]
    if len(rows)!=26:raise obs.ObserverError("fixed phase control count differs")
    report["worker_controls"]=[]
    for index,row in enumerate(rows):
        accepted=obs.validate_message(obs.read_small(directory/row["filename"].replace(".json","-accepted.json")),report["nonce"],"worker")
        envelope={k:v for k,v in row.items() if k!="filename"}
        if (accepted["pid"]!=actual.pid or accepted.get("creation_filetime")!=actual.creation_filetime or accepted.get("filename")!=row["filename"]
            or accepted.get("control_envelope")!=envelope or accepted.get("next_control_index")!=index+1
            or not row["emitted_perf_counter"]<=accepted.get("accepted_perf_counter",-1)<=report["case_deadline_perf_counter"]):raise obs.ObserverError("saved phase control acceptance differs")
        report["worker_controls"].append({"filename":row["filename"],**accepted})
    for label in STAGES:
        index=STAGES.index(label)+1;before=report["memory_brackets"][label]["self_before"];after=report["memory_brackets"][label]["self_after"]
        done=report["controller_controls"][index*2-1];accepted=report["worker_controls"][index*2-1];release=report["controller_controls"][index*2]
        if not before["query_completed_perf_counter"]<=done["emitted_perf_counter"]<=accepted["accepted_perf_counter"]<=after["query_started_perf_counter"]<=after["query_completed_perf_counter"]<=release["emitted_perf_counter"]:raise obs.ObserverError("held bracket control interval order differs")
        if label in BOUNDARIES and not after["query_completed_perf_counter"]<=report["inventories"][BOUNDARIES[label]]["snapshot_started_perf_counter"]<=report["inventories"][BOUNDARIES[label]]["snapshot_completed_perf_counter"]<=release["emitted_perf_counter"]:raise obs.ObserverError("held inventory release order differs")
    actions=[(0,report["native_descendant"]["launch_receipt"]["launch_started_perf_counter"]),(2,report["stages"]["postimport"]["import_started_perf_counter"]),(4,report["stages"]["pretrain"]["model_info"]["model_load_started_perf_counter"])]
    actions.extend((6+i*2,op["operator_started_perf_counter"]) for i,op in enumerate(report["operation_receipts"]))
    actions.append((22,report["stages"]["postvalidation"]["validation"]["started_perf_counter"]))
    if any(not report["worker_controls"][i]["accepted_perf_counter"]<=clock for i,clock in actions):raise obs.ObserverError("work preceded exact release acknowledgment")
    validate_end_barrier(report,actual)


def validate_case(report):
    model=report["stages"]["pretrain"]["model_info"];v=report["stages"]["postvalidation"]["validation"]
    if (model.get("model_id")!=cost.MODEL_ID or model.get("model_revision")!=cost.MODEL_REVISION or model.get("seed")!=503 or model.get("schedule")!=schedule()
        or model.get("schedule_sha256")!=cost.digest(schedule()) or model.get("optimizer_state_entries")!=0 or model.get("optimizer_type")!="AdamW"
        or model.get("parameter_tensors")!=76 or model.get("trainable_parameter_count")!=14067712
        or model.get("train_sha256")!="8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681"
        or model.get("batch_shapes")!=[[2,65]]*2 or model.get("intraop_threads")!=1 or model.get("interop_threads")!=1 or model.get("deterministic_algorithms") is not True
        or model.get("optimizer")!=cost.preset_config()["optimizer"] or model.get("loader_local_files_only") is not True or model.get("trust_remote_code") is not False
        or model.get("device")!="cpu" or model.get("dtype")!="torch.float32" or model.get("holdout_opened") is not False or model.get("offline_environment")!=dict(prior.OFFLINE_ENV)
        or not prior.is_hash(model.get("initial_parameter_sha256")) or v.get("final_validity",{}).get("optimizer_counters")!=[2]*76
        or v.get("final_validity",{}).get("final_parameter_gradient_moments_finite") is not True or not prior.is_hash(v.get("final_parameter_sha256"))
        or v["final_parameter_sha256"]==model["initial_parameter_sha256"] or v.get("no_holdout_evaluation") is not True or v.get("no_checkpoint_written") is not True):raise obs.ObserverError("phase model/fresh optimizer/two-update validation differs")
    ops=report["operation_receipts"];house=report["housekeeping_receipts"]
    if len(ops)!=8 or len(house)!=2 or set(report["inventories"])!={"B"+str(i) for i in range(9)}:raise obs.ObserverError("phase receipt count differs")
    source={"package_relative_path":prior.PROVIDER_SOURCE_RELATIVE_PATH,"sha256":prior.PROVIDER_SOURCE_SHA256,"normalized_path_sha256":report["provider_source_path_sha256"]}
    cumulative=None
    receipts=[(PHASES[label],report["stages"][label]["provider_guard"]) for label in STAGES]+[("train",op["provider_guard"]) for op in ops]+[("complete",report["healthy_completion"]["provider_guard"])]
    for phase,value in receipts:
        if not prior.validate_provider(value,phase,1) or value["provider_source"]!=source:raise obs.ObserverError("provider source/policy changed")
        if phase!="preimport":
            if cumulative is None:cumulative=value["diagnostic_events"]
            elif cumulative!=value["diagnostic_events"]:raise obs.ObserverError("provider cumulative identity changed")
    imported=report["stages"]["postimport"];pre=report["stages"]["preimport"]
    if (pre.get("torch_imported") is not False or pre.get("transformers_imported") is not False or imported.get("torch_version")!=prior.CONFIG["torch_version"]
        or imported.get("transformers_version")!=prior.CONFIG["transformers_version"] or not imported["import_started_perf_counter"]<=cumulative[0]["perf_counter"]<=imported["import_completed_perf_counter"]):raise obs.ObserverError("import/provider chronology differs")
    for i,(spec,op) in enumerate(zip(OPERATIONS,ops)):
        if any(op.get(k)!=value for k,value in spec.items()) or op.get("pid")!=report["worker_identity"]["self_receipt"]["pid"] or op.get("creation_filetime")!=report["worker_identity"]["self_receipt"]["creation_filetime"]:raise obs.ObserverError("operation exact specification/identity differs")
        t0,t1=op["operator_started_perf_counter"],op["operator_completed_perf_counter"]
        if (not all(finite(op.get(k)) for k in ("operator_started_perf_counter","operator_completed_perf_counter","wall_seconds","worker_process_cpu_start_seconds","worker_process_cpu_end_seconds","cpu_seconds"))
            or not t0<=t1<=report["training_deadline_perf_counter"] or op["wall_seconds"]!=t1-t0 or op["cpu_seconds"]!=op["worker_process_cpu_end_seconds"]-op["worker_process_cpu_start_seconds"] or op["cpu_seconds"]<0
            or op.get("live_loss_after_operator") is not (spec["kind"]!="zero_grad")):raise obs.ObserverError("operation clock/loss binding differs")
        output=report["stages"][spec["id"]]["stage_ready_perf_counter"]
        if not t1<=output:raise obs.ObserverError("phase hold preceded operation end")
        if spec["kind"]=="optimizer_step":
            h=house[spec["step"]-1]
            if (h.get("id")!=spec["id"] or h.get("pid")!=op["pid"] or h.get("creation_filetime")!=op["creation_filetime"] or h.get("loss_live_before") is not True or h.get("loss_live_after") is not False
                or not finite(h.get("recorded_loss")) or not t1<=h["started_perf_counter"]<=h["completed_perf_counter"]<=output or h["wall_seconds"]!=h["completed_perf_counter"]-h["started_perf_counter"]):raise obs.ObserverError("separate optimizer housekeeping differs")
        validate_inventory(report["inventories"]["B"+str(i+1)],i+1)
    validate_inventory(report["inventories"]["B0"],0)
    if not report["memory_brackets"][OP_IDS[-1]]["self_after"]["query_completed_perf_counter"]<=v["started_perf_counter"]<=v["completed_perf_counter"]:raise obs.ObserverError("final validation precedes last training bracket")
    report["phase_measurements"]=[phase_summary(spec,op,report["active_windows"][spec["id"]]) for spec,op in zip(OPERATIONS,ops)]
    report["all_phases_have_finite_sampled_coverage"]=all(r["coverage_gate_passed"] for r in report["phase_measurements"])
    a,b=ops[0]["operator_started_perf_counter"],report["stages"][OP_IDS[-1]]["stage_ready_perf_counter"]
    report["training_span"]={"started_perf_counter":a,"completed_perf_counter":b,"wall_seconds":b-a,"operator_wall_sum_seconds":sum(r["wall_seconds"] for r in ops),"housekeeping_wall_sum_seconds":sum(r["wall_seconds"] for r in house)}
    report["provider_custody_verified"]=True

def run_case(paths,provider_source,model_dir,fixture,freeze,output,suite_end):
    case_id="phase_memory";directory=output/case_id;directory.mkdir()
    start=time.perf_counter();case_end=min(start+60,suite_end);nonce=secrets.token_hex(32)
    report={"id":case_id,"sampling_enabled":True,"query_treatment":"memory_only","nonce":nonce,"started_at":base.utc_now(),"started_perf_counter":start,"passed":False,
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
        for spec in OPERATIONS:
            observe_operation(job,actual,directory,nonce,report,spec,case_end,suite_end,report.get("training_deadline_perf_counter",case_end))
            read_held(job,launcher,actual,native,directory,spec["id"],nonce,report,case_end,min(suite_end,report["training_deadline_perf_counter"]))
        control(directory,OP_IDS[-1]+"-continue.json",nonce,"continue",report)
        read_held(job,launcher,actual,native,directory,"postvalidation",nonce,report,case_end,suite_end)
        control(directory,"postvalidation-continue.json",nonce,"continue",report)
        await_postvalidation_continue(directory,nonce,report,actual,case_end,suite_end)
        report["prefinish_live_members"]=work.live_member_receipts(job,actual,native)
        control(directory,"finish.json",nonce,"finish",report)
        done=work.wait_receipt(directory,"worker-completed.json",deadline(5,case_end,suite_end),nonce)
        report["healthy_completion"]=done
        if done["pid"]!=actual.pid or done.get("creation_filetime")!=actual.creation_filetime or done.get("native_exit_code")!=0 or done.get("native_released_nonempty_line") is not True or done.get("model_loads")!=1 or done.get("optimizer_steps")!=2:raise obs.ObserverError("normal duty completion differs")
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


def validate_freeze(protocol_path,freeze_path,paths,provider_source,model_dir,fixture):
    protocol,freeze=obs.read_small(protocol_path),obs.read_small(freeze_path)
    if (protocol.get("experiment_id")!=EXPERIMENT_ID or protocol.get("config")!=CONFIG
        or protocol.get("cases_in_order")!=[{"id":"phase_memory","sampling_enabled":True,"query_treatment":"memory_only"}]
        or protocol.get("control_plan")!=[{"filename":f,"command":c,"decision_label":l,"decision_index":i} for f,c,l,i in CONTROL_PLAN]
        or protocol.get("source_paths")!=list(SOURCE_PATHS) or protocol.get("frozen_dependency_paths")!=list(DEPENDENCY_PATHS)
        or protocol.get("review_tool_paths")!=list(REVIEW_TOOL_PATHS) or freeze.get("protocol_sha256")!=obs.sha256_file(protocol_path)
        or protocol.get("end_barrier")!=END_BARRIER or protocol.get("control_purpose")!=CONTROL_PURPOSE
        or protocol.get("operations")!=list(OPERATIONS) or protocol.get("stages")!=list(STAGES) or protocol.get("boundaries")!=BOUNDARIES or protocol.get("categories")!=list(CATEGORIES)):
        raise obs.ObserverError("new duty protocol/config/order/inventory not frozen")
    provider=protocol.get("provider_custody",{})
    if (provider.get("policy_id")!=prior.PROVIDER_POLICY_ID or provider.get("provider_config")!=prior.PROVIDER_CONFIG
        or provider.get("provider_source_relative_path")!=prior.PROVIDER_SOURCE_RELATIVE_PATH
        or provider.get("provider_source_sha256")!=prior.PROVIDER_SOURCE_SHA256 or provider.get("frame_scope")!=prior.PROVIDER_FRAME_SCOPE
        or provider.get("native_network_sandbox") is not False or provider.get("external_providers_permitted") is not False
        or protocol.get("model",{}).get("planned_model_loads")!=1 or protocol.get("model",{}).get("planned_optimizer_updates")!=2
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
    start=time.perf_counter();suite_end=start+60
    report={"schema_version":1,"experiment_id":EXPERIMENT_ID,"started_at":base.utc_now(),"started_perf_counter":start,"passed":False,"cases":[],
        "planned_model_loads":1,"planned_optimizer_updates":2,"platform":platform.platform(),"os_name":os.name,"no_fallback":True,"boundaries":LIMITS}
    try:
        protocol,freeze=validate_freeze(protocol_path,freeze_path,paths,provider_source,model_dir,fixture)
        report.update(protocol_sha256=obs.sha256_file(protocol_path),implementation_sha256=obs.sha256_file(freeze_path),source_sha256=freeze["new_source_files_sha256"],
            frozen_dependencies_sha256=freeze["frozen_dependency_files_sha256"],review_tools_sha256=freeze["review_tools_sha256"],executables_sha256=freeze["executables_sha256"],
            executable_path_sha256=freeze["executable_path_sha256"],provider_source_sha256=freeze["provider_source_sha256"],provider_source_path_sha256=freeze["provider_source_path_sha256"],
            protocol_predeclared_at=protocol["predeclared_at"],implementation_frozen_at=freeze["frozen_at"])
        if os.name!="nt":raise obs.UnsupportedPlatform("Windows only; no uncontained fallback")
        case=run_case(paths,provider_source,model_dir,fixture,freeze,output,suite_end);report["cases"].append(case)
        report["passed"]=case["passed"] and time.perf_counter()<=suite_end
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
    print("stage-labelled current memory: "+("valid" if result["passed"] else "FAILED"));return 0 if result["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
