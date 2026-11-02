from pathlib import Path
import datetime as dt,gzip,hashlib,json,sys
root=Path.cwd();run=root/'reports/runs/20261102T065705Z';dest=root/'results/native-training-cost-scopes-v4';raw=run/'native-training-cost-scopes-v4';out=run/'independent-final-review';now=lambda:dt.datetime.now(dt.timezone.utc).isoformat();start=now();sha=lambda b:hashlib.sha256(b).hexdigest()
def filehash(path):
 h=hashlib.sha256()
 with path.open('rb')as s:
  while b:=s.read(1024*1024):h.update(b)
 return h.hexdigest()
m=json.loads((dest/'raw-manifest.json').read_bytes());expected={r['path']:r for r in m['files']};files={p.relative_to(raw).as_posix():p for p in raw.rglob('*')if p.is_file()};assert set(files)==set(expected);assert not any(p.is_symlink()for p in raw.rglob('*'))
verified=[]
for name,path in sorted(files.items()):
 r=expected[name];assert path.stat().st_size==r['bytes'] and filehash(path)==r['sha256'],name
 if r['published']:
  public=dest/r['public_path'];packed=public.read_bytes();assert len(packed)==r['public_bytes'] and sha(packed)==r['public_sha256'];data=gzip.decompress(packed)if r['encoding']=='gzip'else packed;assert len(data)==r['bytes']and sha(data)==r['sha256']
 else:assert name.endswith('/endpoint.pt')and r['public_path']is None
 verified.append({'path':name,'bytes':r['bytes'],'sha256':r['sha256'],'public_metadata_verified':r['published']})
assert len(verified)==671 and sum(r['bytes']for r in verified)==759604672 and sum(r['published']for r in m['files'])==659 and not list(dest.rglob('*.pt'))
replay=out/'public-metadata-replay.receipt.json';d=json.loads(replay.read_bytes());publichelper=dest/'replay_saved.py';assert filehash(publichelper)==d['helper_sha256']==filehash(run/'replay_saved.py')
static=out/'curation-replay-independent-review.json';staticd=json.loads(static.read_bytes());assert staticd['checks_passed']==staticd['checks_total']==50 and not staticd['findings']
record={'started_at':start,'completed_at':now(),'status':'passed_saved_byte_wrapper_review','checks_scope':'Independent streaming rehash all671originalfiles incl12opaque checkpoint binaries;659public metadata decomp/hash; actual pure-stdlib public replay with timestamped stdout/stderr;50saved metadata/parameter/release/comparison checks. No model reload/evaluation or native execution.','original_files_rehashed':len(verified),'original_bytes_rehashed':sum(r['bytes']for r in verified),'published_metadata_files_verified':659,'public_metadata_stored_bytes':m['published_metadata_stored_bytes'],'omitted_checkpoints_verified_locally':12,'omitted_checkpoint_bytes':m['omitted_checkpoint_bytes'],'no_checkpoint_bytes_published':True,'raw_manifest_sha256':filehash(dest/'raw-manifest.json'),'raw_files_manifest_payload_sha256':sha(json.dumps(verified,sort_keys=True,separators=(',',':')).encode()),'public_helper_sha256':filehash(publichelper),'public_replay_receipt':str(replay.relative_to(root)).replace('\\','/'),'public_replay_receipt_sha256':filehash(replay),'saved_metadata_review':str(static.relative_to(root)).replace('\\','/'),'saved_metadata_review_sha256':filehash(static),'passed_metadata_checks':50,'findings':[],'scientific_suites':0,'native_jobs':0,'model_loads':0,'holdout_data_reads':0,'tracked_shared_writes':0,'execution_acceptance_unchanged':True,'frozen_execution_accepted':False,'post_outcome_all_six_screens':False}
p=out/'final-curation-wrapper-review.json';p.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'receipt':str(p.relative_to(root)).replace('\\','/'),'sha256':filehash(p),'original_files':671,'original_bytes':759604672,'public_metadata_files':659,'omitted_checkpoints':12,'findings':[]},indent=2))
