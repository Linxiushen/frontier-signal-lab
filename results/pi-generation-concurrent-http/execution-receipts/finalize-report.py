from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,shutil
ROOT=Path.cwd();RUN=ROOT/'reports/runs/20261102T170820Z';RESULT=ROOT/'results/pi-generation-concurrent-http'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
load=lambda p:json.loads(p.read_bytes())
stamp=lambda:datetime.now(timezone.utc).isoformat()
report=RESULT/'report.json';md=RESULT/'report.md'
(RUN/'report-before-validation.json').write_bytes(report.read_bytes());(RUN/'report-before-validation.md').write_bytes(md.read_bytes())
target=RESULT/'execution-receipts/validation';target.mkdir()
for p in sorted((RUN/'validation').iterdir()):
 assert p.is_file();q=target/p.name;q.write_bytes(p.read_bytes());assert sha(q)==sha(p)
for p in [RUN/'validate-publication.py',RUN/'validate-portable-with-dependencies.py']:(target/p.name).write_bytes(p.read_bytes())
assert load(RUN/'validation/saved-observer-tests.receipt.json')['returncode']==0
assert load(RUN/'validation/portable-full.receipt.json')['returncode']==1
assert load(RUN/'validation/portable-with-dependencies.receipt.json')['returncode']==0
assert 'Ran 1175 tests' in (RUN/'validation/portable-with-dependencies.stderr').read_text()
record={'recorded_at':stamp(),'saved_archive_regressions':{'methods':6,'passed':6,'skipped':0},'initial_full_suite':{'methods':1098,'errors':11,'skipped':41,'status':'failed_environment_invocation','cause':'-S disabled installed NumPy; all11errors are NumPy module-import failures; no source or dependency change'},'complete_supported_suite':{'methods':1175,'passed':1094,'skipped':81,'errors':0,'failures':0,'status':'passed_with_optional_Torch_skips'},'source_windows_exact':True,'frozen_execution_acceptance_unchanged':False,'new_scientific_or_native_invocations':0,'receipt_files':{p.relative_to(RESULT).as_posix():sha(p) for p in sorted(target.iterdir())}}
# This field is an assertion about the acceptance value, which remains false.
record['frozen_execution_acceptance_unchanged']=True
r=load(report);assert r['execution_accepted'] is False;r['post_outcome_validation']=record
report.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
with md.open('a',encoding='utf-8',newline='\n') as f:f.write('\nPost-outcome archive regressions: 6/6 pass. The first full-suite invocation used `-S`, hiding installed NumPy, and retains 11 import errors across 1,098 discovered methods (41 skips). With the normal installed dependency path, the complete suite reports 1,175 methods: 1,094 pass and 81 optional Torch skips. No code or dependency change separates these invocations; original frozen native acceptance remains failed. Exact outputs and source-before/after windows are under execution-receipts/validation.\n')
with (RUN/'validation/public-copy-and-report-finalization.json').open('x',encoding='utf-8') as f:json.dump({'recorded_at':stamp(),'report_sha256':sha(report),'report_md_sha256':sha(md),'validation':record},f,ensure_ascii=False,indent=2)
print(json.dumps({'report_sha256':sha(report),'report_md_sha256':sha(md),'full_methods':1175,'passed':1094,'skipped':81}))
