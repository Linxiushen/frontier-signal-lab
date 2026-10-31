"""Independent saved v2 outcome audit. No native runtime execution or assertion adaptation."""
from collections import Counter
from datetime import datetime,timezone
import json,hashlib,math,shutil,sqlite3,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];RUN=Path(__file__).resolve().parent
RAW=RUN/'h2-generation-v2-native';OUT=RUN/'h2-generation-v2-preflight';COPY=ROOT/'local-state/audits/20261031T220050Z-radar-generation-v2'
sys.path.insert(0,str(ROOT))
from scripts.check_pi_generation_v2 import validate_freeze
from experiments.pi_generation_v2_audit import audit,read_endpoint
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
load=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
now=lambda:datetime.now(timezone.utc).isoformat()
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def inventory(root):
 rows=[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(root.rglob('*')) if p.is_file()]
 return {'files':rows,'bytes':sum(r['bytes'] for r in rows)}
original=inventory(RAW);save(OUT/'raw-manifest-radar.json',original)
report={'status':'auditing','started_at':now(),'native_executions':0,'native_retries':0,'audit_source_modified':False,'raw_file_count':len(original['files']),'raw_bytes':original['bytes'],'sqlite_scope':str(COPY),'endpoints':[],'execution_accepted':False}
try:
 execution=load(RAW/'execution.json');assert execution['status'] in ('passed','failed')
 report['frozen_execution_status']=execution['status']
 assert not COPY.exists();shutil.copytree(RAW,COPY)
 assert inventory(COPY)==original
 freeze_path=ROOT/'fixtures/pi-generation-v2/implementation.json';frozen=load(freeze_path)
 protocol,manifest=validate_freeze(ROOT,frozen)
 assert execution['freeze_sha256']==sha(freeze_path)
 assert execution['scientific_suites']==1 and execution['retries']==execution['model_loads']==0
 assert sha(Path(frozen['node']))==frozen['node_sha256']
 runtime=ROOT/frozen['runtime_directory']
 actual={p.relative_to(runtime).as_posix() for p in (runtime/'node_modules').rglob('*') if p.is_file()}|{'package.json','package-lock.json'}
 assert actual=={r['path'] for r in manifest['files']}
 for row in manifest['files']:assert sha(runtime/row['path'])==row['sha256'] and (runtime/row['path']).stat().st_size==row['bytes']
 report['verified_source_counts']={'v2':len(frozen['source_sha256']),'preserved_previous':len(frozen['preserved_previous_source_sha256']),'runtime_files':len(manifest['files'])}
 report['freeze_sha256']=sha(freeze_path)
 assert execution['status']=='passed',execution.get('error')
 acceptance=audit(COPY);assert acceptance==execution['acceptance'];report['unmodified_frozen_audit']=acceptance
 processes=execution['processes'];assert len(processes)==len({p['pid'] for p in processes})==3
 assert [p['forced_termination'] for p in processes]==[True,True,False]
 assert [p['stage'] for p in processes]==[0,1,2]
 assert all(p['returncode']!=0 for p in processes[:2]) and processes[2]['returncode']==0
 assert math.isfinite(execution['elapsed_seconds']) and 0<=execution['elapsed_seconds']<protocol['suite_wall_seconds']
 assert original['bytes']<protocol['output_bytes_ceiling']
 for p in processes:
  assert math.isfinite(p['elapsed_seconds']) and 0<=p['elapsed_seconds']<protocol['process_wall_seconds']
  assert p['memory_samples'] and all(0<=s['PrivateUsage']<protocol['polled_process_private_bytes_ceiling'] for s in p['memory_samples'])
  assert p['ready']['pid']==p['pid'] and p['ready']['stage']==p['stage']
 report['processes']=[{'stage':p['stage'],'pid':p['pid'],'returncode':p['returncode'],'forced_termination':p['forced_termination'],'elapsed_seconds':p['elapsed_seconds'],'samples':len(p['memory_samples']),'maximum_polled_private_bytes':max(s['PrivateUsage'] for s in p['memory_samples']),'maximum_observed_os_peak_working_set_bytes':max(s['PeakWorkingSetSize'] for s in p['memory_samples']),'stderr_bytes':(COPY/f"stage{p['stage']}.stderr.txt").stat().st_size} for p in processes]
 identities=load(COPY/'identities.json');requests=identities['requests']
 events=[json.loads(line) for stage in range(3) for line in (COPY/f'stage{stage}.jsonl').read_text(encoding='utf8').splitlines()]
 apis={(e['service'],e['stage']):e['api'] for e in events if e['type']=='provider-identity'}
 assert len(apis)==6 and len({apis[0,s] for s in range(3)})==3 and {apis[1,s] for s in range(3)}=={'frontier-faux-v2'}
 kinds=Counter();outcomes=Counter();messages=[]
 for service in range(2):
  for stage in range(3):
   path=COPY/f'service{service}-stage{stage}.sqlite'
   with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
    endpoint=read_endpoint(db)
   assert endpoint==load(COPY/f'service{service}-stage{stage}-endpoint.json')
   assert endpoint['state']==load(COPY/f'stage{stage}-snapshot.json')['states'][service]
   report['endpoints'].append({'service':service,'stage':stage,'backup_sha256':sha(path),'full_endpoint_matches':True,'integrity_check':'ok','tasks':len(endpoint['tasks']),'submissions':len(endpoint['submissions']),'effects':len(endpoint['state']['effects'])})
   if stage!=2:continue
   tasks={t['id']:t for t in endpoint['tasks']}
   for t in tasks.values():assert t['state']['status']=='terminal';kinds[t['kind']]+=1;outcomes[t['state']['outcome']['status']]+=1
   for request in [r for r in requests if r['service']==service and r['status']=='admit']:
    enters=[e for e in events if e['type']=='tool-enter' and e['service']==service and e['key']==request['key']]
    task=tasks[enters[0]['taskId']];assistant=next(e for e in endpoint['entries'] if e['id']==task['input']['assistant']);actual=assistant['model'][0]['api']
    assert actual==apis[service,request['stage']]
    messages.append({'service':service,'request_stage':request['stage'],'key':request['key'],'intent':request['intent'],'assistant_id':assistant['id'],'tool_id':task['id'],'api':actual,'tool_execution_count':len(enters)})
 assert kinds=={'pi.generation':14,'pi.tool':14} and outcomes=={'completed':20,'aborted':8}
 assert len(messages)==14 and sum(r['tool_execution_count']==2 for r in messages)==4
 sinks=[load(COPY/f'stage{s}-sink.json') for s in range(3)]
 report['identity_bindings']=messages
 report['actual_faux_api_by_service_stage']={f'{s}:{g}':a for (s,g),a in apis.items()}
 report['native_counts']={'task_kinds':dict(kinds),'terminal_outcomes':dict(outcomes),'event_counts':dict(Counter(e['type'] for e in events))}
 report['metrics']={'suite_wall_seconds':execution['elapsed_seconds'],'descriptive_effects_per_suite_second':10/execution['elapsed_seconds'],'terminal_latency_ms':acceptance['terminal_latency_ms'],'observation_callback_ms':sum(s['callback_ms'] for s in sinks),'observation_flush_ms':sum(s['flush_ms'] for s in sinks),'jsonl_bytes':sum(s['bytes'] for s in sinks),'raw_bytes':original['bytes'],'sqlite_bytes':sum(r['bytes'] for r in original['files'] if r['path'].endswith('.sqlite')),'cost_scope':'Descriptive single suite includes gates/restarts/captures; no baseline, speedup or production throughput inference.'}
 report.update(status='passed',execution_accepted=True,scope='SingleWindows host,2SQLiteSessions,actualGenerationTask/officialFaux/ToolTask,2controlledreopens;notrealmodel,HTTP,tenantauth,externalexactlyonce,arbitrarycrash,productionorcomparisonproof')
except BaseException:
 report.update(status='independent_audit_failed',error=traceback.format_exc())
finally:
 report['original_raw_unchanged']=inventory(RAW)==original
 if not report['original_raw_unchanged']:report.update(status='original_raw_changed',execution_accepted=False)
 report['raw_manifest_sha256']=sha(OUT/'raw-manifest-radar.json');report['completed_at']=now()
 save(OUT/'independent-outcome-review-radar.json',report)
 print(json.dumps({'status':report['status'],'accepted':report['execution_accepted'],'original_raw_unchanged':report['original_raw_unchanged'],'receipt_sha256':sha(OUT/'independent-outcome-review-radar.json'),'error':report.get('error'),'metrics':report.get('metrics')}))
