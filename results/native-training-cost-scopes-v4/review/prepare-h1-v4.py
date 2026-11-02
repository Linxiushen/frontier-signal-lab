from pathlib import Path
from datetime import datetime,timezone
import copy,hashlib,json,shutil,sys

ROOT=Path.cwd();RUN=ROOT/'reports/runs/20261102T065705Z';PREV=ROOT/'reports/runs/20261102T045820Z'
sys.path.insert(0,str(ROOT))
from experiments import native_training_cost_scopes_v4 as study
from scripts.prepare_transformers_scandir_runtime import inventory
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))
now=lambda:datetime.now(timezone.utc).isoformat()
def save(path,obj):
 with path.open('x',encoding='utf-8',newline='\n') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')

assert read(RUN/'h1-focused-prefreeze.receipt.json')['exit_code']==0
assert not {'torch','transformers','numpy'}&set(sys.modules)
old=read(ROOT/'fixtures/native-training-cost-scandir-v3/implementation.json')
prior_protocol=read(ROOT/'fixtures/native-training-cost-scandir-v3/protocol.json')
assert all(sha(ROOT/p)==v for p,v in {**old['source_sha256'],**old['additional_source_sha256']}.items())
accepted=read(ROOT/'fixtures/training-ledger-v3/implementation.json')
assert all(sha(ROOT/p)==v for p,v in accepted['source_sha256'].items())
assert len(study.SOURCES)==52
new_sources={p:sha(ROOT/p) for p in study.SOURCES}
assert set(new_sources)-set(old['source_sha256'])=={'experiments/native_training_cost_scopes_v4.py','scripts/run_native_training_cost_scopes_v4.py','tests/test_native_training_cost_scopes_v4.py'}
assert all(new_sources[p]==v for p,v in old['source_sha256'].items())
runtime=ROOT/'local-state/activation-scandir-20261031T080306Z'
manifest_path=ROOT/'reports/runs/20261031T080306Z/h1-static/runtime-manifest.json'
manifest=read(manifest_path);started=now();actual=inventory(runtime)
assert actual==manifest['files'] and len(actual)==26720 and sum(x['bytes'] for x in actual)==757706940
plan=read(PREV/'h1-execution-plan.json');paths={k:Path(v).resolve() for k,v in plan['explicit_local_executable_paths'].items()}
assert {k:sha(p) for k,p in paths.items()}==old['executables_sha256']
assert {k:sha(paths['base_python'].parent/k) for k in old['python_runtime_files']}==old['python_runtime_files']
base=read(RUN/'h1-base-standard-library-manifest.json');prior_base=read(PREV/'h1-base-standard-library-manifest.json')
assert base['version']==sys.version
assert all(sha(paths['base_python'].parent/r['path'])==r['sha256'] for r in base['files'])
prior_by={x['path']:x for x in prior_base['files']};current_by={x['path']:x for x in base['files']}
assert all(current_by[k]==v for k,v in prior_by.items())
delta=[current_by[k] for k in sorted(current_by.keys()-prior_by.keys())]
assert [x['path'] for x in delta]==['Lib/encodings/__pycache__/ascii.cpython-312.pyc','Lib/encodings/__pycache__/utf_16_le.cpython-312.pyc']
assert base['file_count']==1030 and base['bytes']==46059001
provider=Path(plan['provider_source']);model=Path(plan['model_dir']);fixture=Path(plan['fixture'])
assert sha(provider)==old['provider_source_sha256']==study.prior.PROVIDER_SOURCE_SHA256
assert all(sha(runtime/'Lib/site-packages'/p)==v['sha256'] for p,v in old['selected_runtime_files'].items())
study.cost.verify_model_assets(model);study.cost.validate_fixture(fixture,verify_holdout=False)
memory=study.cost.free_memory_bytes();disk=shutil.disk_usage(ROOT).free
assert memory>=study.CONFIG['min_free_memory_bytes'] and disk>=study.CONFIG['min_free_disk_bytes']
assert not {'torch','transformers','numpy'}&set(sys.modules)
save(RUN/'h1-runtime-preflight.json',{'started_at':started,'completed_at':now(),'status':'passed',
 'runtime':str(runtime),'manifest':manifest_path.relative_to(ROOT).as_posix(),'manifest_sha256':sha(manifest_path),
 'files_freshly_rehashed':len(actual),'bytes_freshly_rehashed':757706940,'exact_inventory_equal':True,
 'free_memory_bytes':memory,'free_disk_bytes':disk,'required_free_disk_bytes':5368709120,'required_free_memory_bytes':8589934592,
 'prior_core49_sources_unchanged':True,'prior_additional3_sources_unchanged':True,'accepted_ledger50_sources_unchanged':True,
 'new_source_files':3,'current_caller_source_files':52,'base_original1028files_unchanged':True,
 'current_base_file_count':1030,'current_base_bytes':46059001,'base_added_files':delta,'cause_of_added_cache_files':'not investigated or attributed',
 'base_manifest_sha256':sha(RUN/'h1-base-standard-library-manifest.json'),'authentication_sha256':sha(RUN/'h1-current-python-authentication.json'),
 'models_imported_or_loaded':0,'scope':'Fresh full prepared runtime/base inventories, source/modelasset/provider/executable/resource authentication. No Torch/Transformers import or model/native execution.'})
folder=ROOT/'fixtures/native-training-cost-scopes-v4';folder.mkdir(exist_ok=False)
output=RUN/'native-training-cost-scopes-v4'
protocol=copy.deepcopy(prior_protocol)
protocol.update(predeclared_at=now(),execution_revision=4,previous_attempt='results/native-training-cost-scandir-v3/failure.json',
 actual_caller='Same accepted training_ledger_v2 identity/provider/role/control/cleanup caller with separate native_training_cost_scopes_v4: flatten existing13norm/6attention groups into ordered19named pairs before actual preserve_scopes. New path-normalizing pinned launcher; no global monkeypatch.',
 integration_change={'source':'experiments/native_training_cost_scopes_v4.py','prior_caller_sha256':old['source_sha256']['experiments/native_training_cost.py'],
  'new_caller_sha256':new_sources['experiments/native_training_cost_scopes_v4.py'],'behavior':'Only preservation-group flattening plus source pins differs from priorcaller. Dense path unchanged. Source-supported prior failure explanation, not captured traceback.',
  'preparation':'15fresh pure/mocked controls pass incl realcontext oldfailure/new19wrappers restoration, parser normalization and scanner controls. Exact parent canonical1129methods1048pass81skip preserved; no source changes since.'},
 unchanged_workload='Original12jobs, seeds503/701/907, LR1e-4, data,64step/60secondarms, quality thresholds,20simport/180scase/1200ssuite and5GiBdisk/8GiBmemory gates and memory endpoints exactly retained. Only separately versioned caller/entrypoint/sourcepins, authenticatedcurrentbaseinventory/provenance and single-use freeze/output differ from v3. No observer expansion, deadline widening or v3 retry.',
 preflight='No preflight ML import/model/native execution. Fresh full26720file prepared runtime; current1030file base with original1028unchanged plus two disclosed encodings caches. Same binaries/DLLs/configuredbundle as v3, not equivalent to oldOct22environment. Both arms share composite environment; no scandir-only attribution.')
protocol['current_base_environment'].update(standard_library_manifest_sha256=sha(RUN/'h1-base-standard-library-manifest.json'),
 file_count=1030,total_bytes=46059001,delta_since_v3=delta,
 authentication='Fresh Valid OpenAI OpCo Authenticode on configured base executable and both DLLs; same binary hashes as v3. Full1030file base inventory freshly authenticated; original1028unchanged, two added encoding cache files explicitly retained.',
 difference_from_v3='Two added .pyc cache files listed with exact bytes/hashes; no original base-file changes. Their creation cause is unverified. Prepared runtime26720files unchanged.',
 inference_limit='Same current composite environment for both arms. No attribution of startup improvement to scandir alone, oldbinary equivalence or cross-environment causal performance claim.')
assert protocol['jobs']==study.jobs()==prior_protocol['jobs'] and protocol['config']==study.CONFIG==prior_protocol['config'] and protocol['ledger_limits']==study.LIMITS==prior_protocol['ledger_limits']
save(folder/'protocol.json',protocol)
freeze=copy.deepcopy(old)
for k in ['unexecuted_candidate_freeze_sha256','preexecution_wording_correction']:freeze.pop(k,None)
freeze.update(frozen_at=now(),protocol_sha256=sha(folder/'protocol.json'),source_sha256=new_sources,
 output_directory=output.relative_to(ROOT).as_posix(),entrypoint_sha256=sha(ROOT/'scripts/run_native_training_cost_scopes_v4.py'),
 previous_failed_freeze_sha256=sha(ROOT/'fixtures/native-training-cost-scandir-v3/implementation.json'),
 current_base_standard_library_manifest_sha256=sha(RUN/'h1-base-standard-library-manifest.json'),current_base_authentication_sha256=sha(RUN/'h1-current-python-authentication.json'),
 runtime_preflight_sha256=sha(RUN/'h1-runtime-preflight.json'),
 review='Prior49core+3additional and accepted50source pins unchanged; separate3newsourcepaths for flattened caller/parser/contextregression.15fresh focused controls pass; exact parentcanonical1129methods1048pass81skip. Same original12workloads/resources/thresholds, one separately frozen suite/no retries, no preflight ML/native/model run.')
save(folder/'implementation.json',freeze);save(RUN/'h1-execution-plan.json',plan)
save(RUN/'h1-prefreeze-review.json',{'recorded_at':now(),'status':'passed','protocol_sha256':sha(folder/'protocol.json'),'freeze_sha256':sha(folder/'implementation.json'),
 'plan_sha256':sha(RUN/'h1-execution-plan.json'),'runtime_preflight_sha256':sha(RUN/'h1-runtime-preflight.json'),
 'original_jobs_config_ledger_limits_exact':True,'original_source_pins_preserved':True,'caller_sources':52,'additional_sources':3,
 'native_suites_executed':0,'model_loads':0,'suites_permitted':1,'retries':0,'independent_review_required_before_invocation':True})
print(json.dumps({'status':'frozen_not_executed','protocol_sha256':sha(folder/'protocol.json'),'freeze_sha256':sha(folder/'implementation.json'),'resources':{'free_memory':memory,'free_disk':disk},'scientific_suites_executed':0}))
