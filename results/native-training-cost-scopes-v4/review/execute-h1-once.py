from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess,sys,time
ROOT=Path.cwd();RUN=ROOT/'reports/runs/20261102T065705Z'
read=lambda p:json.loads(Path(p).read_bytes())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
now=lambda:datetime.now(timezone.utc).isoformat()
def save(path,obj):
    with path.open('x',encoding='utf-8',newline='\n')as stream:json.dump(obj,stream,ensure_ascii=False,indent=2);stream.write('\n')
freeze_path=ROOT/'fixtures/native-training-cost-scopes-v4-reviewed/implementation.json'
protocol_path=freeze_path.with_name('protocol.json')
assert sha(freeze_path)=='c5a8d0eaa37275618c321c9f16407afa9ab2d6ae38765a92130b58844e42325d'
assert sha(protocol_path)=='0b598c459ecaa294ee17532d3544d670dc35c218a3f97045838e638530988641'
import argparse
p=argparse.ArgumentParser();p.add_argument('--review',type=Path,required=True);p.add_argument('--review-sha',required=True);args=p.parse_args()
independent=args.review.resolve();assert sha(independent)==args.review_sha
assert read(independent)['status']=='passed'
assert read(independent)['freeze_sha256']==sha(freeze_path)
assert read(independent)['protocol_sha256']==sha(protocol_path)
freeze=read(freeze_path);review=read(RUN/'h1-qualified-prefreeze-review.json')
for p,h in {**freeze['source_sha256'],**freeze['additional_source_sha256']}.items():assert sha(ROOT/p)==h,p
assert sha(RUN/'h1-execution-plan.json')==review['plan_sha256']
assert not (ROOT/freeze['output_directory']).exists()
base_manifest=read(RUN/'h1-base-standard-library-manifest.json')
assert sha(RUN/'h1-base-standard-library-manifest.json')==freeze['current_base_standard_library_manifest_sha256']
assert all(sha(Path(base_manifest['base_prefix'])/r['path'])==r['sha256'] for r in base_manifest['files'])
command=[sys.executable,'-X','utf8','-B','-S','scripts/run_native_training_cost_scopes_v4.py',
    '--protocol',str(protocol_path.relative_to(ROOT)),'--freeze',str(freeze_path.relative_to(ROOT)),
    '--output',freeze['output_directory'],'--plan',str((RUN/'h1-execution-plan.json').relative_to(ROOT))]
reserved={'started_at':now(),'scientific_slots_reserved':1,'original_CLI_invocations':1,'retries':0,
    'command':command,'freeze_sha256':sha(freeze_path),'independent_review_sha256':sha(independent),'independent_review_path':str(independent.relative_to(ROOT)),'execution_wrapper_sha256':sha(__file__),
    'outer_timing_scope':'Monotonic CLI subprocess lifetime including its in-process asset/executable/resource preflight and all native stages. Excludes this wrapper saved-byte verification, preparation, independent review and post-outcome audit.',
    'environment_overrides':{'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'},
    'limits':'One current composite environment; no unchanged-suite retries, scanner-only attribution, GPU/production or fresh generalization claim.'}
save(RUN/'h1-suite-reserved.json',reserved)
started=time.perf_counter();status={}
with (RUN/'h1-execution.stdout.log').open('xb')as stdout,(RUN/'h1-execution.stderr.log').open('xb')as stderr:
    try:
        child=subprocess.run(command,cwd=ROOT,stdout=stdout,stderr=stderr,
            env=dict(os.environ,**reserved['environment_overrides']),timeout=1250,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        status={'exit_code':child.returncode,'outer_timeout':False}
    except subprocess.TimeoutExpired:
        status={'exit_code':None,'outer_timeout':True,'timeout_seconds':1250}
completed={**reserved,**status,'completed_at':now(),'outer_CLI_wall_seconds':time.perf_counter()-started,
    'stdout_sha256':sha(RUN/'h1-execution.stdout.log'),'stderr_sha256':sha(RUN/'h1-execution.stderr.log')}
save(RUN/'h1-suite-completed.json',completed)
print(json.dumps(completed))
print((RUN/'h1-execution.stdout.log').read_text(encoding='utf-8')[-2500:])
print((RUN/'h1-execution.stderr.log').read_text(encoding='utf-8')[-2500:])
