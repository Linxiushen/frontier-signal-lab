from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess,sys,time
ROOT=Path.cwd();RUN=ROOT/'reports/runs/20261102T045820Z'
read=lambda p:json.loads(Path(p).read_bytes())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
now=lambda:datetime.now(timezone.utc).isoformat()
def save(path,obj):
    with path.open('x',encoding='utf-8',newline='\n')as stream:json.dump(obj,stream,ensure_ascii=False,indent=2);stream.write('\n')
freeze_path=ROOT/'fixtures/native-training-cost-scandir-v3/implementation.json'
protocol_path=freeze_path.with_name('protocol.json')
assert sha(freeze_path)=='ca4901255697ae98cb011c4107353355863bac3976c1e5a91b92393864034b62'
assert sha(protocol_path)=='084cdfef187df0f2723d2e298fb4ac125d511e53e7631ba29115352d3b72076c'
assert sha(RUN/'h1-independent-prefreeze-review.json')=='2622791f9fbba58703ca2d28142c1d33e01d41a96d7b03545b3e3019c621cb81'
freeze=read(freeze_path);review=read(RUN/'h1-prefreeze-review.json')
for p,h in {**freeze['source_sha256'],**freeze['additional_source_sha256']}.items():assert sha(ROOT/p)==h,p
assert sha(RUN/'h1-execution-plan.json')==review['plan_sha256']
assert not (ROOT/freeze['output_directory']).exists()
base_manifest=read(RUN/'h1-base-standard-library-manifest.json')
assert sha(RUN/'h1-base-standard-library-manifest.json')==freeze['current_base_standard_library_manifest_sha256']
assert all(sha(Path(base_manifest['base_prefix'])/r['path'])==r['sha256'] for r in base_manifest['files'])
command=[sys.executable,'-X','utf8','-B','-S','scripts/run_native_training_cost.py',
    '--protocol',str(protocol_path.relative_to(ROOT)),'--freeze',str(freeze_path.relative_to(ROOT)),
    '--output',freeze['output_directory'],'--plan',str((RUN/'h1-execution-plan.json').relative_to(ROOT))]
reserved={'started_at':now(),'scientific_slots_reserved':1,'original_CLI_invocations':1,'retries':0,
    'command':command,'freeze_sha256':sha(freeze_path),'independent_review_sha256':sha(RUN/'h1-independent-prefreeze-review.json'),
    'outer_timing_scope':'Monotonic CLI subprocess lifetime including its in-process asset/executable/resource preflight and all native stages. Excludes this wrapper saved-byte verification, preparation, independent review and post-outcome audit.',
    'environment_overrides':{'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'},
    'limits':'One current composite environment; no unchanged-suite retries, scanner-only attribution, GPU/production or fresh generalization claim.'}
save(RUN/'h1-suite-reserved.json',reserved)
started=time.perf_counter();status={}
with (RUN/'h1-execution.stdout.log').open('xb')as stdout,(RUN/'h1-execution.stderr.log').open('xb')as stderr:
    try:
        child=subprocess.run(command,cwd=ROOT,stdout=stdout,stderr=stderr,
            env=dict(os.environ,**reserved['environment_overrides']),timeout=1250)
        status={'exit_code':child.returncode,'outer_timeout':False}
    except subprocess.TimeoutExpired:
        status={'exit_code':None,'outer_timeout':True,'timeout_seconds':1250}
completed={**reserved,**status,'completed_at':now(),'outer_CLI_wall_seconds':time.perf_counter()-started,
    'stdout_sha256':sha(RUN/'h1-execution.stdout.log'),'stderr_sha256':sha(RUN/'h1-execution.stderr.log')}
save(RUN/'h1-suite-completed.json',completed)
print(json.dumps(completed))
print((RUN/'h1-execution.stdout.log').read_text(encoding='utf-8')[-2500:])
print((RUN/'h1-execution.stderr.log').read_text(encoding='utf-8')[-2500:])
