from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess,sys,time
ROOT=Path.cwd();RUN=ROOT/'reports/runs/20261102T170820Z';OUT=RUN/'validation';OUT.mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
stamp=lambda:datetime.now(timezone.utc).isoformat()
freeze=json.loads((ROOT/'fixtures/pi-generation-concurrent-http/implementation.json').read_bytes())
paths=sorted(set(freeze['source_sha256'])|set(freeze['preserved_previous_source_sha256'])|{'experiments/pi_generation_concurrent_http_saved_observation.py','tests/test_pi_generation_concurrent_http_saved_observation.py','.gitattributes','.github/workflows/ci.yml'})
for name,args in [('saved-observer-tests',['-m','unittest','discover','-s','tests','-p','test_pi_generation_concurrent_http_saved_observation.py','-v']),('portable-full',['scripts/run_portable_tests.py','-v'])]:
 before={n:sha(ROOT/n) for n in paths};started=stamp();start=time.monotonic()
 argv=[sys.executable,'-X','utf8','-B','-S',*args]
 with (OUT/(name+'.stdout')).open('xb') as out,(OUT/(name+'.stderr')).open('xb') as err:
  p=subprocess.run(argv,cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW,timeout=180)
 record={'started_at':started,'completed_at':stamp(),'argv':argv,'returncode':p.returncode,'elapsed_seconds':time.monotonic()-start,'source_before_sha256':before,'source_after_sha256':{n:sha(ROOT/n) for n in paths},'stdout_sha256':sha(OUT/(name+'.stdout')),'stderr_sha256':sha(OUT/(name+'.stderr')),'scope':'Pure/unit and saved-archive checks; no optional native suite, model, HTTP server or scientific rerun'}
 assert record['source_before_sha256']==record['source_after_sha256']
 with (OUT/(name+'.receipt.json')).open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False,indent=2)
 print(json.dumps({'name':name,'returncode':p.returncode,'elapsed_seconds':record['elapsed_seconds']}),flush=True)
 if p.returncode:raise SystemExit(p.returncode)
