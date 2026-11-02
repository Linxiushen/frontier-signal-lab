from pathlib import Path
import datetime as dt,hashlib,json,subprocess,sys,time
root=Path.cwd();out=root/'reports/runs/20261102T065705Z/independent-final-review';helper=root/'results/native-training-cost-scopes-v4/replay_saved.py';expected='d04e72532cde90239ad2367e437ce1d95d01bfa7621608f2a093410cee6ca1bb';sha=lambda b:hashlib.sha256(b).hexdigest()
assert sha(helper.read_bytes())==expected
stdout=out/'public-metadata-replay.stdout.log';stderr=out/'public-metadata-replay.stderr.log';receipt=out/'public-metadata-replay.receipt.json';assert not any(p.exists()for p in [stdout,stderr,receipt]);start=dt.datetime.now(dt.timezone.utc).isoformat();timer=time.perf_counter();args=[sys.executable,'-X','utf8','-B','-S',str(helper)]
with stdout.open('xb')as so,stderr.open('xb')as se:
 try:r=subprocess.run(args,cwd=root,stdout=so,stderr=se,timeout=180);code=r.returncode;timedout=False
 except subprocess.TimeoutExpired:code=None;timedout=True
elapsed=time.perf_counter()-timer;end=dt.datetime.now(dt.timezone.utc).isoformat();parsed=None
if code==0:parsed=json.loads(stdout.read_bytes())
record={'started_at':start,'completed_at':end,'command':args,'cwd':str(root),'helper_sha256':expected,'exit_code':code,'timeout':timedout,'wall_seconds':elapsed,'stdout_sha256':sha(stdout.read_bytes()),'stderr_sha256':sha(stderr.read_bytes()),'result':parsed,'scope':'Independent execution of saved-byte public metadata replay only; no original producer/model/native/scientific suite or checkpoints/holdout evaluation executed. Temporary reconstruction deleted by helper.','scientific_suites':0,'native_jobs':0,'model_loads':0,'tracked_shared_writes':0}
receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(record,ensure_ascii=False,indent=2));assert code==0 and not timedout and parsed['receipt_integrity_passed']is True and parsed['execution_accepted']is False and parsed['post_outcome_joint_screens_passed']is False and parsed['published_metadata_files_verified']==659 and parsed['independent_quality_evaluation_performed']is False
