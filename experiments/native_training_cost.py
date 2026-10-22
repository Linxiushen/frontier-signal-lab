"""Matched CPU training on the accepted retained-interpreter/ledger caller.

Import is stdlib-only. Execution requires a separate, pre-execution freeze.
The original cost data, seeds, optimizer and budgets are deliberately retained.
Evaluation is procedurally sealed, not new or secret test data.
"""
from contextlib import nullcontext
import argparse
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments import training_ledger_v2 as ledger_caller
from experiments import training_import_progress as progress
from experiments.trace_ledger import BoundedJSONLLedger

duty,obs,prior,base,work,dual,cost=(ledger_caller.duty,ledger_caller.obs,
    ledger_caller.prior,ledger_caller.base,ledger_caller.work,ledger_caller.dual,ledger_caller.cost)
ROOT=ledger_caller.ROOT
SCRIPT=Path(__file__).resolve()
TrainingTrace=ledger_caller.TrainingTrace
deadline,control,inventory=duty.deadline,duty.control,duty.inventory
read_held=ledger_caller.read_held
await_postvalidation_continue=duty.await_postvalidation_continue
verify_controls=duty.verify_controls
CONFIG=cost.preset_config()
LIMITS={"max_rows":4096,"max_row_bytes":8192,"max_total_bytes":4194304}
ID="native-matched-training-cost-v1"


def jobs():
    return [{"id":f"{j['arm']}-{j['seed']}-{i}",**j} for i,j in enumerate(cost.job_order())]


def publish_json(path,value):
    pending=path.with_suffix(path.suffix+'.pending')
    obs.write_new(pending,value)
    if path.exists():raise FileExistsError(path)
    os.replace(pending,path)


def require_job(value):
    if value not in jobs() or set(value)!={"id","arm","seed","method"}:
        raise ValueError("Unknown or altered fixed training job")
    return value


def quantile(values,q):
    if not values or not 0<q<=1 or any(not math.isfinite(x) or x<0 for x in values):
        raise ValueError("Finite nonnegative latency sample required")
    return sorted(values)[math.ceil(len(values)*q)-1]


def summarize_steps(rows):
    if not rows or [r['index'] for r in rows]!=list(range(len(rows))):
        raise ValueError("Contiguous complete optimizer steps required")
    fields=['data_seconds','zero_grad_seconds','forward_seconds','backward_seconds','optimizer_seconds','loss_record_seconds','wall_seconds']
    for r in rows:
        if any(not math.isfinite(r[k]) or r[k]<0 for k in fields):
            raise ValueError("Invalid step phase duration")
        if not math.isclose(sum(r[k] for k in fields[:-1]),r['wall_seconds'],rel_tol=0,abs_tol=1e-9):
            raise ValueError("Incomplete step phase accounting")
    return {"count":len(rows),"phase_totals_seconds":{k:math.fsum(r[k] for r in rows) for k in fields},
        "p50_step_seconds":quantile([r['wall_seconds'] for r in rows],.5),
        "p95_step_seconds":quantile([r['wall_seconds'] for r in rows],.95),
        "p99_step_seconds":quantile([r['wall_seconds'] for r in rows],.99),
        "first_step_seconds":rows[0]['wall_seconds'],
        "remaining_steps_mean_seconds":math.fsum(r['wall_seconds'] for r in rows[1:])/max(1,len(rows)-1),
        "scope":"eager CPU; phase clocks and loss recording included; no compiler or communication"}


def training_loop(model,optimizer,tokens,schedule,job):
    torch=cost.require_torch();require_job(job)
    modules=cost.preservation_modules(model) if job['method']!='dense' else []
    codec=cost.CostCodec(list(model.parameters())) if modules else None
    limit=CONFIG['token_steps'] if job['arm']=='token' else CONFIG['max_time_steps']
    losses=[];rows=[];start=time.perf_counter();cpu=time.process_time()
    with cost.preserve_scopes(modules) if codec is not None else nullcontext():
        for i in range(limit):
            a=time.perf_counter();batch=tokens[schedule[i]];b=time.perf_counter()
            optimizer.zero_grad(set_to_none=True);c=time.perf_counter()
            loss=cost.forward_loss(model,batch,codec);d=time.perf_counter()
            loss.backward();e=time.perf_counter();optimizer.step();f=time.perf_counter()
            value=float(loss.detach());losses.append(value)
            if not math.isfinite(value):raise ValueError('Nonfinite training loss')
            # Do not keep the previous graph/batch alive during the next step.
            del loss,batch
            g=time.perf_counter()
            rows.append(dict(index=i,data_seconds=b-a,zero_grad_seconds=c-b,forward_seconds=d-c,
                backward_seconds=e-d,optimizer_seconds=f-e,loss_record_seconds=g-f,wall_seconds=g-a))
            elapsed=time.perf_counter()-start
            hard=CONFIG['max_time_loop_seconds'] if job['arm']=='time' else CONFIG['max_token_loop_seconds']
            if elapsed>hard:raise TimeoutError('Original training loop hard budget exceeded')
            if job['arm']=='time' and elapsed>=CONFIG['time_budget_seconds']:break
    end=time.perf_counter();wall=end-start;steps=len(rows)
    return {"steps_completed":steps,"training_target_positions":steps*128,
        "training_loop_wall_seconds":wall,"training_loop_cpu_seconds":time.process_time()-cpu,
        "loop_perf_counter_start":start,"loop_perf_counter_end":end,
        "training_targets_per_second":steps*128/wall,"preupdate_batch_losses_recorded_after_updates":losses,
        "time_control":cost.classify_time(wall,steps,CONFIG) if job['arm']=='time' else None,
        "step_timings":rows,"step_summary":summarize_steps(rows),
        "cost_boundary":"data indexing, hook setup/restore, pack/retrieve, forward/backward, AdamW, scalar/phase trace and deletion inside total loop; load, native observer and checkpoint separately recorded"}


def prepare(model_dir,fixture,job):
    require_job(job);cost.verify_model_assets(model_dir)
    manifest,_,_=cost.validate_fixture(fixture,verify_holdout=False)
    started=time.perf_counter();blocks=cost.load_blocks(fixture/'train.json','train',128)
    schedule=cost.batch_schedule(128,4096,2,job['seed'])
    model=cost.load_model(model_dir,job['seed']);loaded=time.perf_counter()
    torch=cost.require_torch();optimizer=cost.optimizer_for(model)
    tokens=torch.tensor(blocks,dtype=torch.long)
    initial=cost.parameter_hash(model)
    info={"model_id":cost.MODEL_ID,"model_revision":cost.MODEL_REVISION,"seed":job['seed'],
        "train_sha256":manifest['train_sha256'],"schedule_sha256":cost.digest(schedule),
        "initial_parameter_sha256":initial,"optimizer_state_entries":len(optimizer.state),
        "optimizer_type":"AdamW","parameter_tensors":len(list(model.parameters())),
        "trainable_parameter_count":sum(p.numel() for p in model.parameters()),
        "intraop_threads":torch.get_num_threads(),"interop_threads":torch.get_num_interop_threads(),
        "deterministic_algorithms":torch.are_deterministic_algorithms_enabled(),
        "model_load_started_perf_counter":started,"model_load_completed_perf_counter":loaded,
        "loader_local_files_only":True,"trust_remote_code":False,"device":"cpu","dtype":"torch.float32",
        "optimizer":CONFIG['optimizer'],"holdout_opened":False,"offline_environment":dict(prior.OFFLINE_ENV),
        "job":job,"data_tensor_shape":list(tokens.shape),"schedule_batches":len(schedule),
        "prepare_completed_perf_counter":time.perf_counter()}
    return model,optimizer,tokens,schedule,info


def worker(directory,nonce,native,provider_source,model_dir,fixture,case_end,suite_end):
    job=require_job(obs.read_small(directory/'job.json'))
    backend=obs.WindowsBackend();child=None;state={"next_index":0,"last_emitted":0.0}
    guard=prior.LocalProviderGuard(provider_source,True);guard.install()
    # Procedural access boundary: training refuses any attempt to open holdout.
    sys.addaudithook(refuse_holdout)
    try:
        dual.publish_identity(backend,directory,'worker-ready.json',nonce,'worker')
        duty.require_control(directory,'create-native.json',nonce,'create-native','before_native',0,state,case_end,suite_end)
        started=time.perf_counter()
        child=subprocess.Popen([str(native),*work.NATIVE_ARGUMENTS],stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,creationflags=0x08000000,shell=False)
        obs.write_new(directory/'native-ready.json',base.envelope(nonce,'worker',native_pid=child.pid,
            launch_started_perf_counter=started,launch_completed_perf_counter=time.perf_counter(),
            command_arguments=list(work.NATIVE_ARGUMENTS),close_fds=True,stdin_anonymous_pipe=True,
            shell=False,creationflags=0x08000000,stdout_devnull=True,stderr_devnull=True))
        duty.held_stage(backend,directory,'preimport',nonce,state,guard,case_end,suite_end,
            torch_imported='torch'in sys.modules,transformers_imported='transformers'in sys.modules)
        guard.set_phase('import');started=time.perf_counter()
        torch,transformers=progress.import_packages(progress.ImportProgress(directory,nonce,backend.self_reading(),guard))
        duty.held_stage(backend,directory,'postimport',nonce,state,guard,case_end,suite_end,
            import_started_perf_counter=started,import_completed_perf_counter=time.perf_counter(),
            torch_version=str(torch.__version__),transformers_version=str(transformers.__version__))
        guard.set_phase('load');model,optimizer,tokens,schedule,info=prepare(model_dir,fixture,job)
        duty.held_stage(backend,directory,'pretrain',nonce,state,guard,case_end,suite_end,model=info)
        guard.set_phase('train')
        obs.write_new(directory/'before-loop.json',base.envelope(nonce,'worker',
            before_loop_perf_counter=time.perf_counter(),provider_guard=guard.receipt()))
        loop=training_loop(model,optimizer,tokens,schedule,job);steps=loop['steps_completed']
        guard.set_phase('postupdate')
        publish_json(directory/'after-loop.json',base.envelope(nonce,'worker',
            after_loop_perf_counter=time.perf_counter(),loop=loop,provider_guard=guard.receipt()))
        duty.held_stage(backend,directory,'postloop',nonce,state,guard,case_end,suite_end)
        started=time.perf_counter();validity=cost.final_validity(model,optimizer,steps)
        final=cost.parameter_hash(model);checkpoint=directory/'endpoint.pt';save0=time.perf_counter()
        torch.save(model.state_dict(),checkpoint);saved=time.perf_counter()
        checkpoint_hash=cost.file_hash(checkpoint)
        duty.held_stage(backend,directory,'postvalidation',nonce,state,guard,case_end,suite_end,
            validation={"started_perf_counter":started,"completed_perf_counter":time.perf_counter(),
                "final_validity":validity,"final_parameter_sha256":final,"no_holdout_evaluation":True,
                "checkpoint_sha256":checkpoint_hash,"checkpoint_bytes":checkpoint.stat().st_size,
                "checkpoint_save_seconds":saved-save0,"checkpoint_filename":"endpoint.pt"})
        duty.require_control(directory,'finish.json',nonce,'finish','postvalidation',5,state,case_end,suite_end)
        child.stdin.write(b'done\r\n');child.stdin.flush();child.stdin.close()
        budget=deadline(5,case_end,suite_end)-time.perf_counter()
        if budget<=0 or child.wait(timeout=budget)!=0:raise obs.ObserverError('Native normal completion failed')
        obs.write_new(directory/'worker-completed.json',base.envelope(nonce,'worker',model_loads=1,
            optimizer_steps=steps,native_exit_code=0,native_released_nonempty_line=True,provider_guard=guard.receipt()))
    except BaseException as error:
        obs.write_new(directory/'worker-failure.json',base.envelope(nonce,'worker',provider_guard=guard.receipt(),
            phase=guard.phase,failure_perf_counter=time.perf_counter(),
            error=base.public_error(error,directory,native,provider_source,model_dir,fixture,sys.executable)))
        raise
    finally:
        if child is not None and child.stdin is not None and not child.stdin.closed:child.stdin.close()


def observe_training(job,actual,directory,nonce,report,case_end,suite_end,*,trace):
    parent=obs.ProcessRef(job.backend,job.backend.k.GetCurrentProcess())
    start=time.perf_counter();cpu0=work.native_process_cpu(job.backend,parent)
    window={"started_perf_counter":start,"parent_native_cpu_start_seconds":cpu0,"poll_count":0,"observations":[]}
    report['active_window']=window;trace.check()
    control(directory,'pretrain-continue.json',nonce,'continue',report)
    hard=CONFIG['max_time_loop_seconds'] if report['job']['arm']=='time' else CONFIG['max_token_loop_seconds']
    until=deadline(hard+5,case_end,suite_end);next_due=time.perf_counter()
    while True:
        now=time.perf_counter()
        if now>=until:raise obs.ObserverError('Active training deadline exhausted')
        if (directory/'worker-failure.json').exists():raise obs.ObserverError('Worker failed during matched cost')
        if (directory/'after-loop.json').exists():break
        window['poll_count']+=1
        if window['poll_count']>4000:raise obs.ObserverError('Active polling bound exhausted')
        rows=window['observations'];q0=time.perf_counter()
        sample=trace.sample('active:'+str(len(rows)));q1=time.perf_counter()
        # The selected memory+CPU query is retained; no global Toolhelp in the loop.
        rows.append(dict(index=len(rows),query_started_perf_counter=q0,query_completed_perf_counter=q1,sample=sample))
        next_due+=.02;now=time.perf_counter()
        if next_due<=now:next_due=now+.02
        time.sleep(min(max(0,next_due-now),max(0,until-now)))
    window['parent_native_cpu_end_seconds']=work.native_process_cpu(job.backend,parent)
    window['completed_perf_counter']=time.perf_counter()
    window['parent_native_cpu_delta_seconds']=window['parent_native_cpu_end_seconds']-cpu0
    window['wall_seconds']=window['completed_perf_counter']-start
    for key,filename in [('loop_before','before-loop.json'),('loop_after','after-loop.json')]:
        value=obs.validate_message(obs.read_small(directory/filename),nonce,'worker')
        if value['pid']!=actual.pid:raise obs.ObserverError('Loop signal actual identity differs')
        report[key]=value


def validate_case(report):
    job=require_job(report['job']);model=report['stages']['pretrain']['model']
    loop=report['loop_after']['loop'];v=report['stages']['postvalidation']['validation']
    n=loop['steps_completed'];a,b=loop['loop_perf_counter_start'],loop['loop_perf_counter_end']
    if type(n)is not int or not 1<=n<=4096 or (job['arm']=='token' and n!=64):raise ValueError('Step budget differs')
    if job['arm']=='time' and (loop['time_control']!=cost.classify_time(b-a,n,CONFIG) or not loop['time_control']['valid']):raise ValueError('Time budget differs')
    if (model['job']!=job or model['seed']!=job['seed'] or model['optimizer']!=CONFIG['optimizer']
        or model['model_id']!=cost.MODEL_ID or model['model_revision']!=cost.MODEL_REVISION
        or model['train_sha256']!='8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681'
        or model['schedule_sha256']!=cost.digest(cost.batch_schedule(128,4096,2,job['seed']))
        or model['optimizer_state_entries']!=0 or model['parameter_tensors']!=76
        or model['trainable_parameter_count']!=14067712 or model['holdout_opened']is not False
        or model['data_tensor_shape']!=[128,65] or model['schedule_batches']!=4096
        or model['offline_environment']!=dict(prior.OFFLINE_ENV)
        or model['intraop_threads']!=1 or model['interop_threads']!=1
        or model['device']!='cpu' or model['dtype']!='torch.float32'
        or model['deterministic_algorithms']is not True or model['loader_local_files_only']is not True or model['trust_remote_code']is not False
        or v['final_validity']['optimizer_counters']!=[n]*76
        or v['final_validity']['final_parameter_gradient_moments_finite']is not True
        or v['no_holdout_evaluation']is not True or not prior.is_hash(v['checkpoint_sha256'])
        or not prior.is_hash(v['final_parameter_sha256']) or v['final_parameter_sha256']==model['initial_parameter_sha256']):
        raise ValueError('Model/data/optimizer or checkpoint contract differs')
    if loop['training_target_positions']!=n*128 or len(loop['preupdate_batch_losses_recorded_after_updates'])!=n or not all(math.isfinite(x)for x in loop['preupdate_batch_losses_recorded_after_updates']):raise ValueError('Loss/denominator differs')
    if loop['step_summary']!=summarize_steps(loop['step_timings']) or len(loop['step_timings'])!=n:raise ValueError('Latency accounting differs')
    if not math.isclose(loop['training_loop_wall_seconds'],b-a,rel_tol=0,abs_tol=1e-12):raise ValueError('Loop clock differs')
    window=report['active_window'];before=report['loop_before'];after=report['loop_after']
    if not window['started_perf_counter']<=before['before_loop_perf_counter']<=a<b<=after['after_loop_perf_counter']<=window['completed_perf_counter']:raise ValueError('Loop observer boundary differs')
    selected=[r for r in window['observations'] if a<=r['query_started_perf_counter']<=r['sample']['perf_counter']<=r['query_completed_perf_counter']<=b]
    identity=report['worker_identity']['self_receipt']
    if len(selected)<20:raise ValueError('Insufficient actual-loop samples')
    stamps=[a]+[r['sample']['perf_counter']for r in selected]+[b]
    if max(y-x for x,y in zip(stamps,stamps[1:]))>.5:raise ValueError('Native sampling gap exceeded')
    for i,r in enumerate(window['observations']):
        if r['index']!=i or any(r['sample'][k]!=identity[k]for k in ['pid','creation_filetime']):raise ValueError('Observer identity/order differs')
    source={"package_relative_path":prior.PROVIDER_SOURCE_RELATIVE_PATH,"sha256":prior.PROVIDER_SOURCE_SHA256,
        "normalized_path_sha256":report['provider_source_path_sha256']}
    receipts=[(duty.PHASES[label],report['stages'][label]['provider_guard'])for label in duty.STAGES]
    receipts += [('train',before['provider_guard']),('postupdate',after['provider_guard']),('complete',report['healthy_completion']['provider_guard'])]
    cumulative=None
    for phase,value in receipts:
        if not prior.validate_provider(value,phase,1) or value['provider_source']!=source:raise ValueError('Provider policy differs')
        if phase!='preimport':
            if cumulative is None:cumulative=value['diagnostic_events']
            elif cumulative!=value['diagnostic_events']:raise ValueError('Provider identity changed')
    imported=report['stages']['postimport'];pre=report['stages']['preimport']
    if pre['torch_imported']or pre['transformers_imported']or imported['torch_version']!=prior.CONFIG['torch_version']or imported['transformers_version']!=prior.CONFIG['transformers_version']:raise ValueError('Import contract differs')
    if not imported['import_started_perf_counter']<=cumulative[0]['perf_counter']<=imported['import_completed_perf_counter']:raise ValueError('Provider event outside import')
    if not b<=report['memory_brackets']['postloop']['self_before']['perf_counter']<=v['started_perf_counter']<=v['completed_perf_counter']:raise ValueError('Memory endpoint contaminated by checkpoint validation')
    peak=report['memory_brackets']['postloop']['parent']['memory']['peak_resident_bytes']
    readings=[r['sample']for r in selected]
    report['measurement']={"actual_process_peak_resident_through_postloop_bytes":peak,
        "sampled_current_private_max_bytes":max(r['memory']['private_bytes']for r in readings),
        "sampled_current_resident_max_bytes":max(r['memory']['resident_bytes']for r in readings),
        "native_samples_in_loop":len(selected),"maximum_sample_gap_seconds":max(y-x for x,y in zip(stamps,stamps[1:])),
        "parent_query_wall_seconds":math.fsum(r['query_completed_perf_counter']-r['query_started_perf_counter']for r in selected),
        "parent_native_cpu_seconds":window['parent_native_cpu_delta_seconds'],
        "peak_scope":"retained actual interpreter OS lifetime working-set high-water through postloop; includes import/load/training/observation, excludes later checkpoint. Not private/GPU/isolated activation peak; current private maxima are sampled lower bounds.",
        "observer_scope":"same memory+CPU ledger query at20ms target in both arms; query wall/parentCPU descriptive, total causal observer overhead unestimated; no Toolhelp in active window"}


# run_case and the suite/evaluator entrypoints are below. Their process/role/
# provider/control lifetimes derive directly from the accepted ledger caller.


def run_case(spec,paths,provider_source,model_dir,fixture,freeze,output,suite_end):
    spec=require_job(spec);case_id=spec['id'];enabled=True;directory=output/case_id;directory.mkdir();obs.write_new(directory/'job.json',spec)
    start=time.perf_counter();case_end=min(start+180,suite_end);nonce=secrets.token_hex(32)
    report={"id":case_id,"sampling_enabled":enabled,"nonce":nonce,"started_at":base.utc_now(),"started_perf_counter":start,"passed":False,
        "case_deadline_perf_counter":case_end,"suite_deadline_perf_counter":suite_end,"censuses":[],"role_decisions":[],
        "samples":[],"parent_query_costs":[],"executables_sha256":freeze["executables_sha256"],
        "executable_path_sha256":freeze["executable_path_sha256"],"provider_source_sha256":freeze["provider_source_sha256"],
        "provider_source_path_sha256":freeze["provider_source_path_sha256"],"_paths":paths,"job":spec}
    job=actual=trace=None
    sink=(directory/"trace.jsonl").open("xb")
    writer=sink
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
        if done["pid"]!=actual.pid or done.get("native_exit_code")!=0 or done.get("native_released_nonempty_line") is not True or done.get("model_loads")!=1 or done.get("optimizer_steps")!=report["loop_after"]["loop"]["steps_completed"]:raise obs.ObserverError("normal duty completion differs")
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
    try:
        report["import_progress"]=progress.read_prefix(directory,nonce,
            report["worker_identity"]["self_receipt"],start,time.perf_counter(),complete=report["passed"])
    except BaseException as error:
        report["import_progress_error"]=base.public_error(error);report["passed"]=False
    if report["passed"]:
        try:trace.close_record(report["cleanup"])
        except BaseException as error:
            report["close_trace_error"]=base.public_error(error);report["passed"]=False
    report["ledger"]=ledger.snapshot()
    sink.close()
    report.pop("_paths",None);report["completed_at"]=base.utc_now();report["completed_perf_counter"]=time.perf_counter();report["wall_seconds"]=report["completed_perf_counter"]-start
    if report["completed_perf_counter"]>case_end:report["passed"]=False;report["case_wall_budget_exceeded"]=True
    return report


def refuse_holdout(event,args):
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        if os.fsdecode(args[0]).replace('\\','/').rsplit('/',1)[-1]=='holdout.json':
            raise PermissionError('Training cannot unseal heldout data')


def validate_release(release,output):
    if set(release)!={'id','all_training_completed','endpoints','training_sealed_at','protocol_sha256'} or release['id']!=ID or release['all_training_completed']is not True:
        raise ValueError('Incomplete training release')
    endpoints=release['endpoints']
    if [e['job']for e in endpoints]!=jobs():raise ValueError('Missing/duplicate/reordered training endpoint')
    for e in endpoints:
        if set(e)!={'job','checkpoint_sha256','initial_parameter_sha256','final_parameter_sha256'} or any(not prior.is_hash(e[k])for k in e if k!='job'):
            raise ValueError('Invalid endpoint hash schema')
        checkpoint=output/e['job']['id']/'endpoint.pt'
        if cost.file_hash(checkpoint)!=e['checkpoint_sha256']:raise ValueError('Checkpoint changed before evaluation release')
    return endpoints


def evaluate(model_dir,fixture,output,nonce,provider_source):
    backend=obs.WindowsBackend();dual.publish_identity(backend,output,'evaluator-ready.json',nonce,'worker')
    # No provider calls; same single local import capability allowance.
    guard=prior.LocalProviderGuard(provider_source,True);guard.install();guard.set_phase('import')
    torch,_=progress.import_packages(progress.ImportProgress(output,nonce,backend.self_reading(),guard))
    release=obs.read_small(output/'evaluation-release.json');endpoints=validate_release(release,output)
    guard.set_phase('load');started=base.utc_now()
    model=cost.load_model(model_dir,503);initial_hash=cost.parameter_hash(model)
    manifest,_,_=cost.validate_fixture(fixture,verify_holdout=True)
    blocks=cost.load_blocks(fixture/'holdout.json','holdout',64)
    train=cost.load_blocks(fixture/'train.json','train',128)
    if set(map(tuple,blocks))&set(map(tuple,train)):raise ValueError('Train/heldout overlap')
    initial=cost.evaluate_model(model,blocks);rows=[]
    for e in endpoints:
        checkpoint=output/e['job']['id']/'endpoint.pt'
        if cost.file_hash(checkpoint)!=e['checkpoint_sha256']:raise ValueError('Checkpoint changed during evaluation')
        state=torch.load(checkpoint,map_location='cpu',weights_only=True);model.load_state_dict(state,strict=True);del state
        if cost.parameter_hash(model)!=e['final_parameter_sha256']or initial_hash!=e['initial_parameter_sha256']:
            raise ValueError('Initial/final model differs in evaluator')
        rows.append({**e,'evaluation':cost.evaluate_model(model,blocks)})
    publish_json(output/'evaluation.json',{'id':ID,'started_at':started,'completed_at':base.utc_now(),
        'initial_parameter_sha256':initial_hash,'holdout_sha256':manifest['holdout_sha256'],
        'release_sha256':cost.file_hash(output/'evaluation-release.json'),'initial':initial,'endpoints':rows,
        'provider_guard':guard.receipt(),'pid':os.getpid(),
        'scope':'one evaluation per endpoint after all training; original publicly visible previously evaluated book blocks, procedural seal only. Not fresh generalization data.'})


def run_evaluator(paths,provider,model,fixture,freeze,output,suite_end):
    job=obs.WindowsJob();nonce=secrets.token_hex(32);end=min(time.perf_counter()+300,suite_end)
    r={'nonce':nonce,'started_at':base.utc_now()}
    try:
        command=[str(paths['launcher']),'-S',str(SCRIPT),'--evaluate','--directory',str(output),'--nonce',nonce,
            '--provider-source',str(provider),'--model-dir',str(model),'--fixture',str(fixture)]
        launcher=job.start_suspended(command,cwd=ROOT)
        ready=work.wait_receipt(output,'evaluator-ready.json',min(time.perf_counter()+5,end),nonce)
        actual,chain=job.authenticate(ready,nonce,'worker',launcher)
        if actual.pid==launcher.pid:raise ValueError('Evaluator launcher substituted for actual interpreter')
        r['identity']={'self_receipt':ready,'verified_ancestry':chain,
            'os_image':prior.os_image(job.backend,actual,paths['base_python'],freeze['executables_sha256']['base_python']),
            **dual.verify_self_executable(ready,'worker',paths,freeze['executables_sha256'])}
        while not (output/'evaluation.json').exists():
            if time.perf_counter()>=end or not actual.alive():raise TimeoutError('Evaluator failed or timed out; no retry')
            if actual.reading()['memory']['private_bytes']>1073741824:raise ValueError('Evaluator sampled private cap exceeded')
            time.sleep(.02)
        r['cleanup']=work.cleanup(job,end,suite_end);prior.verify_cleanup(r,'healthy')
        result=obs.read_small(output/'evaluation.json')
        if result['pid']!=actual.pid or not prior.validate_provider(result['provider_guard'],'load',1):raise ValueError('Evaluator identity/provider differs')
        progress.read_prefix(output,nonce,ready,r['identity']['self_receipt']['perf_counter'] if 'perf_counter'in ready else 0,time.perf_counter(),complete=True)
        r['passed']=True
    except BaseException as e:
        r.update(passed=False,error=base.public_error(e,output,provider,model,fixture))
        job.terminate();r['failure_cleanup']=work.cleanup(job,end,suite_end)
    finally:
        job.close();job.close_refs()
    r['completed_at']=base.utc_now();return r


def paired_results(cases,evaluation):
    if len(cases)!=12 or [c['job']for c in cases]!=jobs()or not all(c['passed']for c in cases):raise ValueError('Every fixed training case required')
    if [e['job']for e in evaluation['endpoints']]!=jobs():raise ValueError('Evaluation endpoint set differs')
    rows=[]
    for arm in ['token','time']:
        for seed in CONFIG['seeds']:
            pair=[next(c for c in cases if c['job']['arm']==arm and c['job']['seed']==seed and c['job']['method']==m)for m in CONFIG['methods']]
            scores=[next(e['evaluation']['mean_nll']for e in evaluation['endpoints']if e['job']==c['job'])for c in pair]
            dense,bank=pair;d,b=(c['loop_after']['loop']for c in pair)
            dp,bp=(c['measurement']['actual_process_peak_resident_through_postloop_bytes']for c in pair)
            cond={'bank_nll_no_worse_than_dense':scores[1]<=scores[0],'bank_nll_below_initial':scores[1]<evaluation['initial']['mean_nll']}
            if arm=='token':cond.update(bank_observed_complete_case_faster=bank['wall_seconds']<dense['wall_seconds'],bank_process_lifetime_working_set_peak_lower=bp<dp)
            else:cond.update(bank_more_targets=b['training_target_positions']>d['training_target_positions'])
            rows.append({'arm':arm,'seed':seed,'dense_nll':scores[0],'bank_nll':scores[1],
                'dense_steps':d['steps_completed'],'bank_steps':b['steps_completed'],
                'bank_to_dense_loop_wall_ratio':b['training_loop_wall_seconds']/d['training_loop_wall_seconds'],
                'bank_to_dense_complete_case_wall_ratio':bank['wall_seconds']/dense['wall_seconds'],
                'bank_minus_dense_actual_process_peak_resident_bytes':bp-dp,
                'dense_end_to_end_targets_per_second':d['training_target_positions']/dense['wall_seconds'],
                'bank_end_to_end_targets_per_second':b['training_target_positions']/bank['wall_seconds'],
                'conditions':cond,'joint_screen_passed':all(cond.values())})
    return {'comparisons':rows,'all_six_joint_screens_passed':all(r['joint_screen_passed']for r in rows),
        'scope':'observed local CPU workloads/fixed order, three seeds, reused procedural heldout; no causal observer-cost, significance, GPU/multinode/production or general quality claim'}


SOURCES=tuple(dict.fromkeys((*ledger_caller.SOURCES,'experiments/native_training_cost.py',
    'tests/test_native_training_cost.py','scripts/audit_native_training_cost.py')))


def run(protocol_path,freeze_path,output,plan):
    protocol=json.loads(protocol_path.read_bytes());freeze=json.loads(freeze_path.read_bytes())
    if (protocol['id']!=ID or protocol['jobs']!=jobs()or protocol['config']!=CONFIG or protocol['ledger_limits']!=LIMITS
        or freeze['source_sha256']!={p:cost.file_hash(ROOT/p)for p in SOURCES}
        or freeze['protocol_sha256']!=cost.file_hash(protocol_path)or freeze['output_directory']!=output.relative_to(ROOT).as_posix()
        or freeze['suites_permitted']!=1 or freeze['retries']!=0
        or not datetime.fromisoformat(protocol['predeclared_at'])<=datetime.fromisoformat(freeze['frozen_at'])<datetime.now(timezone.utc)):
        raise ValueError('Frozen execution contract differs')
    paths={k:Path(v).resolve()for k,v in plan['explicit_local_executable_paths'].items()}
    model,fixture,provider=(Path(plan[k]).resolve()for k in ['model_dir','fixture','provider_source'])
    if {k:cost.file_hash(p)for k,p in paths.items()}!=freeze['executables_sha256']or {k:dual.path_hash(p)for k,p in paths.items()}!=freeze['executable_path_sha256']:raise ValueError('Executable pin differs')
    if cost.file_hash(provider)!=freeze['provider_source_sha256'] or freeze['provider_source_sha256']!=prior.PROVIDER_SOURCE_SHA256 or dual.path_hash(provider)!=freeze['provider_source_path_sha256']:raise ValueError('Provider pin differs')
    if any(cost.file_hash(paths['base_python'].parent/k)!=v for k,v in freeze['python_runtime_files'].items()):raise ValueError('Python runtime pin differs')
    if any(cost.file_hash(provider.parent.parent.parent/p)!=v['sha256']for p,v in freeze['selected_runtime_files'].items()):raise ValueError('ML runtime pin differs')
    cost.verify_model_assets(model);cost.validate_fixture(fixture,verify_holdout=False)
    if fixture!=ROOT/'fixtures/activation-cost' or os.name!='nt':raise ValueError('Unsupported fixture/platform')
    if cost.free_memory_bytes()<CONFIG['min_free_memory_bytes']:raise ValueError('Insufficient free memory')
    import shutil
    if shutil.disk_usage(output.parent).free<CONFIG['min_free_disk_bytes']:raise ValueError('Insufficient free disk')
    output.mkdir(exist_ok=False);start=time.perf_counter();end=start+1200
    report={'id':ID,'started_at':base.utc_now(),'started_perf_counter':start,
        'protocol_sha256':cost.file_hash(protocol_path),'freeze_sha256':cost.file_hash(freeze_path),'cases':[],
        'scientific_suites':1,'retries':0,'passed':False}
    for spec in jobs():
        case=run_case(spec,paths,provider,model,fixture,freeze,output,end)
        report['cases'].append(case);obs.write_new(output/(spec['id']+'-case.json'),case)
        if not case['passed']or cost.output_bytes(output)>CONFIG['max_output_bytes']:break
    if len(report['cases'])==12 and all(c['passed']for c in report['cases']):
        release={'id':ID,'all_training_completed':True,'training_sealed_at':base.utc_now(),
            'protocol_sha256':report['protocol_sha256'],'endpoints':[]}
        for c in report['cases']:
            v=c['stages']['postvalidation']['validation'];m=c['stages']['pretrain']['model']
            release['endpoints'].append({'job':c['job'],'checkpoint_sha256':v['checkpoint_sha256'],
                'initial_parameter_sha256':m['initial_parameter_sha256'],'final_parameter_sha256':v['final_parameter_sha256']})
        validate_release(release,output);obs.write_new(output/'evaluation-release.json',release)
        report['evaluator']=run_evaluator(paths,provider,model,fixture,freeze,output,end)
        if report['evaluator']['passed']:
            report['comparisons']=paired_results(report['cases'],obs.read_small(output/'evaluation.json'))
            report['passed']=True
    report.update(completed_at=base.utc_now(),completed_perf_counter=time.perf_counter())
    report['wall_seconds']=report['completed_perf_counter']-start
    if report['completed_perf_counter']>end:report['passed']=False
    obs.write_new(output/'report.json',report)
    print(json.dumps({'passed':report['passed'],'cases':len(report['cases']),'last_error':report['cases'][-1].get('error'),
        'scientific_screen':report.get('comparisons',{}).get('all_six_joint_screens_passed')}))
    return report['passed']


if __name__=='__main__':
    p=argparse.ArgumentParser()
    mode=p.add_mutually_exclusive_group(required=True)
    for name in ['worker','evaluate','run']:mode.add_argument('--'+name,action='store_true')
    for name in ['directory','native','provider-source','model-dir','fixture','protocol','freeze','output','plan']:p.add_argument('--'+name,type=Path)
    p.add_argument('--nonce')
    for name in ['case-end','suite-end']:p.add_argument('--'+name,type=float)
    a=p.parse_args()
    if a.worker:worker(a.directory,a.nonce,a.native,a.provider_source,a.model_dir,a.fixture,a.case_end,a.suite_end)
    elif a.evaluate:evaluate(a.model_dir,a.fixture,a.directory,a.nonce,a.provider_source)
    else:raise SystemExit(0 if run(a.protocol,a.freeze,a.output,json.loads(a.plan.read_bytes()))else 1)
