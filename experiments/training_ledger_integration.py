"""Bounded ledger in the actual pinned CPU pretrained training caller.

The original duty-v2 worker/provider/acknowledgment policy stays immutable.
The parent explicitly injects a retained-interpreter trace into its held and
active query paths. No global patching and no launcher-memory substitution.
One exclusive, initially empty, local binary sink is supported. Flush is not
fsync; arbitrary blocking sinks and continuous isolation are outside scope.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments import observer_duty_v2 as duty
from experiments.trace_ledger import BoundedJSONLLedger, LedgerIOError

prior,obs,base,work,dual,role,cost=(duty.prior,duty.obs,duty.base,duty.work,duty.dual,duty.role,duty.cost)
ROOT=duty.ROOT
SCRIPT=duty.SCRIPT
CONFIG,PHASES=duty.CONFIG,duty.PHASES
deadline,control,inventory=duty.deadline,duty.control,duty.inventory
await_postvalidation_continue=duty.await_postvalidation_continue
validate_case,verify_controls=duty.validate_case,duty.verify_controls
LIMITS={"max_rows":900,"max_row_bytes":8192,"max_total_bytes":4194304}
MAX_PRIVATE_BYTES=1073741824
CASES=("healthy","partial_pretrain")
ID="actual-pretrained-training-ledger-v1"


class TrainingTrace:
    """Caller-owned Job/ref; serialize native query and publication together."""
    def __init__(self,job,actual,ledger):
        self.job,self.actual,self.ledger=job,actual,ledger
        self.lock=threading.RLock()
        self.failed=False
        self.retired=False
        self.bound=False

    def _append(self,kind,**fields):
        try:
            return self.ledger.append(kind,emitted_perf_counter=time.perf_counter(),
                native_thread_id=threading.get_native_id(),**fields)
        except BaseException:
            self.failed=True
            raise

    def start(self,launcher):
        with self.lock:
            self.check()
            if self.bound:raise obs.ObserverError("One retained training interpreter per trace")
            row=self._append("bound",pid=self.actual.pid,creation_filetime=self.actual.creation_filetime,
                launcher_pid=launcher.pid,launcher_creation_filetime=launcher.creation_filetime)
            self.bound=True
            return row

    def check(self):
        if self.failed or self.retired:
            raise obs.ObserverError("Training trace failed/retired; no query or release allowed")

    def sample(self,request_id):
        with self.lock:
            self.check()
            if not self.bound:raise obs.ObserverError("Retained training interpreter not bound")
            if not isinstance(request_id,str) or not 1<=len(request_id)<=128:
                raise ValueError("request_id must contain 1..128 characters")
            try:
                started=time.perf_counter()
                self.job.member(self.actual)
                member=time.perf_counter()
                reading=self.actual.reading()
                if (reading.get("pid"),reading.get("creation_filetime"))!=(self.actual.pid,self.actual.creation_filetime):
                    raise obs.ObserverError("Native reading differs from retained training identity")
                if reading["memory"]["private_bytes"]>MAX_PRIVATE_BYTES:
                    raise obs.ObserverError("Sampled actual-interpreter private-byte budget exceeded")
                reading["native_cpu_seconds"]=work.native_process_cpu(self.job.backend,self.actual)
                completed=time.perf_counter()
                self._append("sample",request_id=request_id,pid=self.actual.pid,
                    creation_filetime=self.actual.creation_filetime,query_started_perf_counter=started,
                    member_verified_perf_counter=member,query_completed_perf_counter=completed,reading=reading)
                return reading
            except BaseException:
                self.failed=True
                raise

    def close_record(self,cleanup):
        # Native cleanup and closes belong to run_case and are never gated on I/O.
        with self.lock:
            self.check()
            self._append("closed",cleanup=cleanup)
            self.retired=True


class PartialPretrainSink:
    """Frozen fault injection at the actual held pretrain query, before release."""
    def __init__(self,sink):
        self.sink=sink
        self.injected=False
    def write(self,data):
        row=json.loads(data)
        if row["kind"]=="sample" and row["request_id"]=="held:pretrain":
            self.injected=True
            self.sink.write(data[:5]);self.sink.flush()
            raise OSError("predeclared partial pretrain write")
        return self.sink.write(data)
    def flush(self):
        return self.sink.flush()


def held_sample(trace,samples,label):
    sample=trace.sample("held:"+label)
    samples.append(sample)
    return sample


def fault_contract(directory,report,trace,error):
    snap=trace.ledger.snapshot()
    if (type(error) is not LedgerIOError or not trace.failed or not snap["poisoned"]
        or snap["committed_rows"]!=3 or snap["failure"]["seq"]!=3
        or [r["kind"] for r in snap["records"]]!=["bound","sample","sample"]
        or [r.get("request_id") for r in snap["records"][1:]]!=["held:preimport","held:postimport"]
        or list(report["stages"])!=["preimport","postimport","pretrain"]
        or len(report["controller_controls"])!=5
        or any((directory/name).exists() for name in ("pretrain-parent-done.json","pretrain-continue.json",
            "before-loop.json","after-loop.json","postloop-ready.json","worker-completed.json"))):
        raise obs.ObserverError("fault must poison actual pretrain query before any release/update")
    model=report["stages"]["pretrain"]["model"]
    if model["optimizer_state_entries"]!=0 or model["holdout_opened"] is not False or model["schedule"]!=duty.schedule():
        raise obs.ObserverError("fault model is not fresh held pretrained caller")
    exits=report["failure_cleanup"]["exit_codes"]
    if any(r["exit_code"]!=0xE003 for r in exits if r["pid"] in (report["launcher"]["pid"],trace.actual.pid)):
        raise obs.ObserverError("fault must retain exact Python Job termination exit")
    # Even an attempted later query must refuse before touching native handles.
    try:
        trace.sample("forbidden-after-poison")
    except obs.ObserverError:
        report["post_poison_query_refused"]=True
    else:
        raise obs.ObserverError("poison permitted a later query")
    report["expected_fault"]={"type":"LedgerIOError","stage":"pretrain","before_training_release":True}


def read_held(job,launcher,actual,native,directory,label,nonce,report,case_end,suite_end,timeout=5,*,trace):
    ready=work.wait_receipt(directory,label+"-ready.json",deadline(timeout,case_end,suite_end),nonce)
    if (ready["pid"]!=actual.pid or ready.get("stage")!=label or type(ready.get("native_thread_count")) is not int
        or ready["native_thread_count"]<1 or not prior.validate_provider(ready.get("provider_guard"),PHASES[label],1)):
        raise obs.ObserverError("held duty identity/thread/provider receipt differs")
    report.setdefault("stages",{})[label]=ready
    before=work.wait_receipt(directory,label+"-before.json",deadline(5,case_end,suite_end),nonce)
    parent=prior.timed_call("boundary_worker_memory_and_cpu",lambda:held_sample(trace,report["samples"],label),report["parent_query_costs"])
    inventory(job,launcher,actual,native,report,label)
    control(directory,label+"-parent-done.json",nonce,"parent-sampled",report)
    after=work.wait_receipt(directory,label+"-after.json",deadline(5,case_end,suite_end),nonce)
    comparison=obs.compare_memory_bracket(before,parent,after,CONFIG["memory_bracket_tolerance_bytes"])
    report.setdefault("memory_brackets",{})[label]={"self_before":before,"parent":parent,"self_after":after,"comparison":comparison}
    if not comparison["passed"]:raise obs.ObserverError("held duty memory bracket mismatch")


def observe_training(job,actual,directory,nonce,report,case_end,suite_end,*,trace):
    parent=obs.ProcessRef(job.backend,job.backend.k.GetCurrentProcess())
    start=time.perf_counter();cpu0=work.native_process_cpu(job.backend,parent)
    window={"started_perf_counter":start,"parent_native_cpu_start_seconds":cpu0,"poll_count":0,"observations":[]}
    report["active_window"]=window
    trace.check()
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
            q0=time.perf_counter();sample=trace.sample("active:"+str(len(rows)));q1=time.perf_counter()
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


def run_case(spec,paths,provider_source,model_dir,fixture,freeze,output,suite_end):
    case_id=spec;enabled=True;directory=output/case_id;directory.mkdir()
    start=time.perf_counter();case_end=min(start+60,suite_end);nonce=secrets.token_hex(32)
    report={"id":case_id,"sampling_enabled":enabled,"nonce":nonce,"started_at":base.utc_now(),"started_perf_counter":start,"passed":False,
        "case_deadline_perf_counter":case_end,"suite_deadline_perf_counter":suite_end,"censuses":[],"role_decisions":[],
        "samples":[],"parent_query_costs":[],"executables_sha256":freeze["executables_sha256"],
        "executable_path_sha256":freeze["executable_path_sha256"],"provider_source_sha256":freeze["provider_source_sha256"],
        "provider_source_path_sha256":freeze["provider_source_path_sha256"],"_paths":paths}
    job=actual=trace=None
    sink=(directory/"trace.jsonl").open("xb")
    writer=PartialPretrainSink(sink) if case_id=="partial_pretrain" else sink
    ledger=BoundedJSONLLedger(writer,**LIMITS)
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
        trace=TrainingTrace(job,actual,ledger);trace.start(launcher)
        inventory(job,launcher,actual,None,report,"before_native");control(directory,"create-native.json",nonce,"create-native",report)
        native_ready=work.wait_receipt(directory,"native-ready.json",deadline(5,case_end,suite_end),nonce)
        native,report["native_descendant"]=work.verify_native_child(job,actual,native_ready,paths["native"],freeze["executables_sha256"]["native"])
        for label,seconds in (("preimport",5),("postimport",20),("pretrain",25)):
            read_held(job,launcher,actual,native,directory,label,nonce,report,case_end,suite_end,seconds,trace=trace)
            if label!="pretrain":control(directory,label+"-continue.json",nonce,"continue",report)
        observe_training(job,actual,directory,nonce,report,case_end,suite_end,trace=trace)
        for label in ("postloop","postvalidation"):
            read_held(job,launcher,actual,native,directory,label,nonce,report,case_end,suite_end,trace=trace)
            control(directory,label+"-continue.json",nonce,"continue",report)
        await_postvalidation_continue(directory,nonce,report,actual,case_end,suite_end)
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
        if case_id=="partial_pretrain" and trace is not None:
            try:
                fault_contract(directory,report,trace,error)
                if report.get("cleanup_error"):raise obs.ObserverError("fault cleanup failed")
                report["cleanup"]=report["failure_cleanup"]
                prior.verify_cleanup(report,"partial_pretrain")
                report["outcome"]="expected_pretrain_trace_failure"
                report["passed"]=True
            except BaseException as fault_error:
                report["fault_contract_error"]=base.public_error(fault_error)

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
    if report["passed"] and case_id=="healthy":
        try:trace.close_record(report["cleanup"])
        except BaseException as error:
            report["close_trace_error"]=base.public_error(error);report["passed"]=False
    report["ledger"]=ledger.snapshot()
    report["fault_injected"]=isinstance(writer,PartialPretrainSink) and writer.injected
    sink.close()
    report.pop("_paths",None);report["completed_at"]=base.utc_now();report["completed_perf_counter"]=time.perf_counter();report["wall_seconds"]=report["completed_perf_counter"]-start
    if report["completed_perf_counter"]>case_end:report["passed"]=False;report["case_wall_budget_exceeded"]=True
    return report


SOURCES=tuple(dict.fromkeys((*duty.DEPENDENCY_PATHS,*duty.SOURCE_PATHS,*duty.REVIEW_TOOL_PATHS,
    "fixtures/observer-duty-v2/protocol.json","fixtures/observer-duty-v2/implementation.json",
    "experiments/trace_ledger.py","experiments/training_ledger_integration.py",
    "scripts/audit_training_ledger.py","tests/test_training_ledger.py","results/observer-duty-v2/report.json")))


def run(protocol_path,freeze_path,output,plan):
    protocol,freeze=obs.read_small(protocol_path),obs.read_small(freeze_path)
    paths={k:Path(v).resolve() for k,v in plan["explicit_local_executable_paths"].items()}
    provider,model,fixture=(Path(plan[k]).resolve() for k in ("provider_source","model_dir","fixture"))
    assert protocol["id"]==ID and protocol["cases"]==list(CASES) and protocol["limits"]==LIMITS
    assert protocol["training_config"]==CONFIG and protocol["worker_control_plan"]==[list(v) for v in duty.CONTROL_PLAN]
    assert protocol["sampled_private_byte_stop"]==MAX_PRIVATE_BYTES
    assert freeze["source_sha256"]=={p:obs.sha256_file(ROOT/p) for p in SOURCES}
    assert freeze["protocol_sha256"]==obs.sha256_file(protocol_path)
    assert freeze["output_directory"]==output.relative_to(ROOT).as_posix()
    assert freeze["actual_suites_permitted"]==1 and freeze["retries"]==0
    assert freeze["model_loads_ceiling"]==2 and freeze["optimizer_updates_ceiling"]==16
    assert freeze["executables_sha256"]=={k:obs.sha256_file(p) for k,p in paths.items()}
    assert freeze["executable_path_sha256"]=={k:dual.path_hash(p) for k,p in paths.items()}
    assert freeze["python_runtime_files"]=={k:obs.sha256_file(paths["base_python"].parent/k) for k in freeze["python_runtime_files"]}
    site_packages=provider.parent.parent.parent
    assert all(obs.sha256_file(site_packages/p)==v["sha256"] for p,v in freeze["selected_runtime_files"].items())
    assert freeze["provider_source_sha256"]==prior.PROVIDER_SOURCE_SHA256==prior.source_digest(provider)
    assert freeze["provider_source_path_sha256"]==dual.path_hash(provider)
    assert Path(provider).parts[-3:]==("urllib3","util","connection.py")
    assert fixture==(ROOT/"fixtures/activation-cost").resolve()
    cost.verify_model_assets(model);cost.validate_fixture(fixture,verify_holdout=False)
    system32=Path(os.environ["SystemRoot"])/"System32"
    assert paths["native"]==(system32/"cmd.exe").resolve() and paths["conhost"]==(system32/"conhost.exe").resolve()
    assert datetime.fromisoformat(protocol["predeclared_at"])<=datetime.fromisoformat(freeze["frozen_at"])<datetime.now(timezone.utc)
    assert os.name=="nt"
    output.mkdir(exist_ok=False)
    start=time.perf_counter();end=start+240
    report={"id":ID,"started_at":base.utc_now(),"started_perf_counter":start,
        "protocol_sha256":obs.sha256_file(protocol_path),"freeze_sha256":obs.sha256_file(freeze_path),
        "cases":[],"scientific_experiments":1,"model_loads_ceiling":2,"optimizer_updates_ceiling":16}
    for spec in CASES:
        report["cases"].append(run_case(spec,paths,provider,model,fixture,freeze,output,end))
        if not report["cases"][-1]["passed"]:break
    report["passed"]=len(report["cases"])==2 and all(c["passed"] for c in report["cases"]) and time.perf_counter()<=end
    report["completed_at"]=base.utc_now();report["completed_perf_counter"]=time.perf_counter()
    obs.write_new(output/"report.json",report)
    print(json.dumps({"passed":report["passed"],"cases":[(c["id"],c["passed"])for c in report["cases"]]}))
    return report["passed"]


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("protocol","freeze","output","plan"):
        parser.add_argument("--"+name,type=Path,required=True)
    a=parser.parse_args()
    raise SystemExit(0 if run(a.protocol.resolve(),a.freeze.resolve(),a.output.resolve(),obs.read_small(a.plan)) else 1)
