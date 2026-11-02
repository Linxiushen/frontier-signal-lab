from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess,sys,time
ROOT=Path.cwd();OUT=ROOT/'reports/runs/20261102T170820Z/validation'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
old=json.loads((OUT/'portable-full.receipt.json').read_bytes());paths=old['source_before_sha256']
before={n:sha(ROOT/n) for n in paths};started=datetime.now(timezone.utc).isoformat();start=time.monotonic()
argv=[sys.executable,'-X','utf8','-B','scripts/run_portable_tests.py','-v'];name='portable-with-dependencies'
with (OUT/(name+'.stdout')).open('xb') as out,(OUT/(name+'.stderr')).open('xb') as err:p=subprocess.run(argv,cwd=ROOT,stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW,timeout=180)
record={'started_at':started,'completed_at':datetime.now(timezone.utc).isoformat(),'argv':argv,'returncode':p.returncode,'elapsed_seconds':time.monotonic()-start,'source_before_sha256':before,'source_after_sha256':{n:sha(ROOT/n) for n in paths},'stdout_sha256':sha(OUT/(name+'.stdout')),'stderr_sha256':sha(OUT/(name+'.stderr')),'scope':'Complete existing unit/saved archive suite with installed NumPy; Torch absent. No optional native/model/scientific suite rerun.','prior_environment_failure':'portable-full used -S and all11module import errors were missing installed NumPy; original failed receipt preserved.'}
assert record['source_before_sha256']==record['source_after_sha256']
with (OUT/(name+'.receipt.json')).open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False,indent=2)
print(json.dumps({'name':name,'returncode':p.returncode,'elapsed_seconds':record['elapsed_seconds']}))
raise SystemExit(p.returncode)
