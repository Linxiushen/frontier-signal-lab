"""One small stdlib process-identity diagnostic; no model or training."""
from pathlib import Path
import sys, subprocess, json, datetime as dt
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from experiments.activation_cost_probe import memory_info

child_code = '''import sys,os,json
from experiments.activation_cost_probe import memory_info
allocation=bytearray(16*1024*1024)
print(json.dumps({"interpreter_pid":os.getpid(),"self_memory":memory_info(),"allocation_bytes":len(allocation)}),flush=True)
sys.stdin.readline()
'''
p=subprocess.Popen([sys.executable,'-c',child_code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
try:
    child=json.loads(p.stdout.readline())
    result={'schema_version':1,'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'mode':'stdlib engineering identity reproduction, no ML imports/model/training/heldout reads','popen_pid':p.pid,**child,'popen_pid_memory':memory_info(p.pid),'interpreter_pid_memory':memory_info(child['interpreter_pid']),'same_pid':p.pid==child['interpreter_pid'],'limitation':'Same launch path reproduction only. Original training receipts did not record PIDs; this cannot authenticate historical PID/descendant relationships. No original measurement is replaced.'}
finally:
    p.communicate('\n',timeout=10)
result['returncode']=p.returncode
out=Path(__file__).with_name('launcher-identity-check.json')
with out.open('x',encoding='utf-8',newline='\n') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps(result))
