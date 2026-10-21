"""Actual duty-v2 worker with separately frozen bounded import progress."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments import observer_duty_v2 as duty
from experiments import training_import_progress as progress
prior,obs,base,work,dual,cost=(duty.prior,duty.obs,duty.base,duty.work,duty.dual,duty.cost)
require_control,held_stage,prepare,dense_loop,deadline=(duty.require_control,duty.held_stage,duty.prepare,duty.dense_loop,duty.deadline)

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
        guard.set_phase("import");started=time.perf_counter();torch,transformers=progress.import_packages(progress.ImportProgress(directory,nonce,backend.self_reading(),guard));ended=time.perf_counter()
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

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--worker",action="store_true",required=True)
    for name in ("directory","native","provider-source","model-dir","fixture"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--nonce",required=True)
    for name in ("case-end","suite-end"):p.add_argument("--"+name,type=float,required=True)
    a=p.parse_args();obs.validate_nonce(a.nonce)
    worker(a.directory,a.nonce,a.native,a.provider_source,a.model_dir,a.fixture,a.case_end,a.suite_end)
