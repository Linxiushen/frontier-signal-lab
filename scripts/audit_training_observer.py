"""Independent stdlib audit of pinned training/Windows observer receipts.

Reads saved JSON and hashes files only. Never imports experiment modules or ML,
launches a child, queries the OS, reruns training or changes a failed report.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import random
import re

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = 'windows-pinned-pythia-training-observer-integration-v1'
# Root-approved stable sources; the implementation file is written after review.
PROTOCOL_SHA256 = 'b3ac0d419eeb2965bc6a5472ae3e0e800eaf6c6c20b3c515c366daaf0d740715'
SOURCE_HASHES = {
    'experiments/training_observer_probe.py':'39fca84fc9c2eef2abf7f967f70b7d5752faccddf6f5456c9965ed3f9a06d728',
    'tests/test_training_observer.py':'26c18d7f1f2d9952b320a068d91e0aef42685595d2d0ef26bc90a7fbab2111eb'}
DEPENDENCY_HASHES = {
    'experiments/activation_cost_probe.py':'0f3f0062269ad2b2531e9a6ef2f94dbc65b5af46a89bad75ec9d7be5f1d661ce',
    'scripts/capture_real_activation.py':'32ac2555ce2f2593efc5f08188ba7b7703c33efb510fa78d680ace22fdab1b87',
    'experiments/process_observer.py':'3f247512aee1e50940d57e81a0290d658bad56cae098d45b2f92bb69deece175',
    'experiments/process_observer_probe.py':'cfbc7de447cdf7b1dbae98e34c9e642c7d7cc8d93343c961f6aec8f78ea31740',
    'experiments/workload_observer_probe.py':'cdb14b85a40f866676e3181eca513041d6c6fa5bc679429654b4b72b9e63eba3',
    'fixtures/process-observer/protocol.json':'e4b77a96ab8aa1a2857b3156f485226791c877b923f847798eaad97e1f4b58a0',
    'fixtures/process-observer/implementation.json':'535c3e78a9abf53fd89452876796c1df8c39a5a8d2b21963f173f148fc03e954',
    'fixtures/workload-observer/protocol.json':'659146a5f05ed88b23886fefc3a389268883b88c5ad8b3a869712c1d27dbb463',
    'fixtures/workload-observer/implementation.json':'db207618c0f5226dc5f2e509fdbf99cb32ae9d24af4066f1bd3a23fba47e293c',
    'fixtures/activation-cost/train.json':'8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681',
    'fixtures/activation-cost/manifest.json':'0d08ba2574148924da713a40a66e49f3a7adc4d280a6d8f2e0d5135aae5148eb',
    'fixtures/activation-cost/protocol.json':'8908ca5362a51a1b0e2a9d27657b0b8e64ac5632fc695b30407331be5c1c87ed',
    'fixtures/activation-cost/implementation.json':'e28fe5df090bcc86dae9e0151e3765f130d40a28499df5b0714be32f4b826de5'}
SOURCE_PATHS = ('experiments/training_observer_probe.py', 'tests/test_training_observer.py')
DEPENDENCY_PATHS = ('experiments/activation_cost_probe.py', 'scripts/capture_real_activation.py',
    'experiments/process_observer.py', 'experiments/process_observer_probe.py',
    'experiments/workload_observer_probe.py', 'fixtures/process-observer/protocol.json',
    'fixtures/process-observer/implementation.json', 'fixtures/workload-observer/protocol.json',
    'fixtures/workload-observer/implementation.json', 'fixtures/activation-cost/train.json',
    'fixtures/activation-cost/manifest.json', 'fixtures/activation-cost/protocol.json',
    'fixtures/activation-cost/implementation.json')
CONFIG = {'torch_version':'2.9.1+cpu','transformers_version':'4.57.3','seed':503,
    'optimizer_steps':2,'intraop_threads':1,'interop_threads':1,'train_blocks':128,'batch_size':2,
    'sequence_input_tokens':64,'trainable_parameter_count':14067712,'parameter_tensors':76,
    'manual_allocation_bytes':67108864,'private_cap_increment_bytes':50331648,
    'minimum_allocation_delta_bytes':58720256,'memory_bracket_tolerance_bytes':4194304,
    'sampler_interval_seconds':0.02,'maximum_recorded_sample_gap_seconds':0.5,
    'handshake_timeout_seconds':5.0,'import_timeout_seconds':20.0,'load_timeout_seconds':25.0,
    'training_timeout_seconds':15.0,'barrier_timeout_seconds':5.0,'overhead_window_seconds':0.4,
    'busy_timeout_seconds':1.5,'busy_minimum_cpu_seconds':0.25,'busy_backstop_seconds':10.0,
    'cap_ready_to_termination_maximum_seconds':1.0,'cleanup_timeout_seconds':4.0,
    'case_timeout_seconds':60.0,'total_timeout_seconds':180.0,
    'prehandshake_expected_exit_code':37,'import_failure_expected_exit_code':38}
CASES = (('healthy_dense2','healthy',67108864),('dense2_busy_deadline','timeout',0),
    ('dense2_private_cap64','private_cap',67108864),('prehandshake_exit37','prehandshake_fail',0),
    ('injected_import_failure38','import_fail',0))
STAGES = ('preimport','postimport','postload','postupdate','allocated')
NATIVE_ARGUMENTS = ['/d','/q','/c','set /p workload_observer_gate=']
MODEL_ID = 'EleutherAI/pythia-14m'
MODEL_REVISION = 'cf967c0a9a04383db6f7b1108d86b2962634b4ac'
TRAIN_SHA256 = '8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681'
ASSETS = {
    'README.md': {'bytes':10560,'sha256':'d1f2cf1d5181daedeaa70208ddd5cc5251867bde9acf6db7bb45a2265e25e163'},
    'config.json': {'bytes':698,'sha256':'f97f966a66c444890ed461fff2a51eefb15d74303df05b948124719f199b0b17'},
    'generation_config.json': {'bytes':111,'sha256':'494cbba887cc299273f0c54d7612596918e74c7881a27cbd95e4e7e2464ea090'},
    'model.safetensors': {'bytes':28143920,'sha256':'116a02532db461f91386a5b20f942ff2c8d4de7341e21b55caafc3d7b25f49a1'},
    'special_tokens_map.json': {'bytes':441,'sha256':'10b8c8852c1e1f70b54d9aff61728408c28971c0e97a6c5a7b2debbd1d3e9c0c'},
    'tokenizer.json': {'bytes':2114042,'sha256':'870f4e2baa6b683221fa52004d5d6f40ab8c9d31961617304b78c910c2c3caf2'},
    'tokenizer_config.json': {'bytes':4834,'sha256':'eee017c5bd133137f45907bd0a6e781e2ccd1a533734b7ed2a2f2f4446659809'}}
OFFLINE_ENV = {'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_DATASETS_OFFLINE':'1',
    'HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false','OMP_NUM_THREADS':'1',
    'MKL_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}
OPTIMIZER = {'learning_rate':0.0001,'betas':[0.9,0.999],'epsilon':1e-8,
    'weight_decay':0.01,'foreach':False,'fused':False}


def sha(data): return hashlib.sha256(data).hexdigest()
def finite(v): return type(v) in (int,float) and math.isfinite(v)
def integer(v, minimum=0): return type(v) is int and v >= minimum
def fingerprint(v): return isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) is not None
def canonical(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def stamp(v):
    d = dt.datetime.fromisoformat(v.replace('Z','+00:00'))
    if d.tzinfo is None: raise ValueError('timestamp lacks timezone')
    return d
def schedule():
    order = list(range(128)); random.Random(503).shuffle(order)
    return [order[:2],order[2:4]]


def audit(report, protocol, freeze, *, protocol_sha256, freeze_sha256,
          actual_source_sha256, actual_dependency_sha256, launch_sha256=None,
          base_python_sha256=None, native_sha256=None, actual_model_assets=None):
    checks = []
    def check(ok,label):
        checks.append({'check':label,'passed':bool(ok)}); return bool(ok)
    def close(a,b,label):
        return check(finite(a) and finite(b) and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8),label)
    def ident(row,label):
        value = row['pid'],row['creation_filetime']
        check(all(integer(v,1) for v in value),label+':positive_pid_creation')
        return value
    def msg(row,nonce,pid,label):
        check(row.get('nonce')==nonce and row.get('role')=='worker'
            and type(row.get('pid')) is int and row['pid']==pid,label+':nonce_role_actual_pid')
    def interval(row,start,end,label):
        a,b = row['started_perf_counter'],row['completed_perf_counter']
        check(all(finite(v) for v in (a,b)) and start<=a<=b<=end,label+':within_case_clock')
        close(row['wall_seconds'],b-a,label+':wall_recomputed')
        return a,b
    def reading(row,expected,start,end,label,cpu=False):
        check(ident(row,label)==expected,label+':actual_interpreter_identity')
        check(finite(row['perf_counter']) and start<=row['perf_counter']<=end,label+':within_case_clock')
        m=row['memory']
        check(all(integer(m[k]) for k in ['resident_bytes','private_bytes','peak_resident_bytes'])
            and m['peak_resident_bytes']>=m['resident_bytes'],label+':current_memory_and_lifetime_peak')
        if cpu: check(finite(row['native_cpu_seconds']) and row['native_cpu_seconds']>=0,label+':native_cpu')
    def image(row,expected,hash_value,start,end,label):
        check(ident(row,label)==expected,label+':retained_identity')
        check(row.get('basename','').lower()=='python.exe' and row.get('sha256')==hash_value
            and row.get('queried_from_retained_handle') is True
            and row.get('matches_frozen_path_and_hash') is True,label+':OS_image_hash_path')
        check(finite(row['verified_perf_counter']) and start<=row['verified_perf_counter']<=end,
            label+':image_query_clock')
    def cleanup(case,retained,mode,start,end,prefix):
        row=case['cleanup']; a,b=interval(row,start,end,prefix+'cleanup')
        check(row.get('all_retained_handles_exited') is True and type(row.get('job_active_count')) is int
            and row['job_active_count']==0,prefix+'all_handles_exited_and_job_zero')
        exits=row['exit_codes']; pairs=[ident(x,prefix+'exit') for x in exits]
        check(len(pairs)==len(set(pairs)) and set(pairs)==set(retained.items()),prefix+'all_retained_exit_identities')
        check(all(integer(x['exit_code']) and x['exit_code']<=0xFFFFFFFF for x in exits),prefix+'exit_codes_uint32')
        check(finite(row['timeout_seconds']) and 0<=b-a<=row['timeout_seconds']<=4.0,prefix+'cleanup_4s_bound')
        codes={x['pid']:x['exit_code'] for x in exits}
        if mode=='healthy': check(all(v==0 for v in codes.values()),prefix+'healthy_zero_exits')
        if mode=='prehandshake_fail': check(len(exits)==1 and exits[0]['exit_code']==37,prefix+'precise_exit37')
        if mode=='import_fail':
            worker=case['worker_identity']['self_receipt']['pid']; launcher=case['launcher']['pid']
            check(codes.get(worker)==codes.get(launcher)==38,prefix+'precise_actual_and_launcher_exit38')
        if mode in ('timeout','private_cap'):
            check(case['termination_request_returned_perf_counter']<=a,prefix+'cleanup_after_termination')
        return a,b

    cases=[]; suite_start=suite_end=None; suite_a=suite_b=None
    try:
        check(all(type(d.get('schema_version')) is int and d['schema_version']==1 for d in (report,protocol,freeze)),'schema')
        check(report['experiment_id']==protocol['experiment_id']==EXPERIMENT,'experiment_identity')
        check(canonical(protocol['config'])==canonical(CONFIG),'fixed_numeric_protocol')
        check(tuple(protocol['source_paths'])==SOURCE_PATHS and tuple(protocol['frozen_dependency_paths'])==DEPENDENCY_PATHS,'declared_file_inventory')
        check([(c['id'],c['mode'],c['manual_allocation_bytes']) for c in protocol['cases_in_order']]==list(CASES),'declared_case_order')
        check(fingerprint(protocol_sha256) and protocol_sha256==freeze['protocol_sha256']==report.get('protocol_sha256'),'protocol_hash_chain')
        if PROTOCOL_SHA256 is not None: check(protocol_sha256==PROTOCOL_SHA256,'root_frozen_protocol_pin')
        check(fingerprint(freeze_sha256) and freeze_sha256==report.get('implementation_sha256'),'implementation_freeze_hash')
        sources=freeze['new_source_files_sha256']; dependencies=freeze['frozen_dependency_files_sha256']
        check(set(sources)==set(SOURCE_PATHS) and all(fingerprint(x) for x in sources.values())
            and sources==actual_source_sha256==report.get('source_sha256'),'actual_source_file_hashes')
        check(set(dependencies)==set(DEPENDENCY_PATHS) and all(fingerprint(x) for x in dependencies.values())
            and dependencies==actual_dependency_sha256==report.get('frozen_dependencies_sha256'),'actual_dependency_file_hashes')
        if SOURCE_HASHES is not None: check(sources==SOURCE_HASHES,'root_frozen_source_pins')
        if DEPENDENCY_HASHES is not None: check(dependencies==DEPENDENCY_HASHES,'historical_dependency_pins')
        for key,field,measured,label in [('python_executable_sha256','launch_executable_sha256',launch_sha256,'launcher'),
            ('base_python_executable_sha256','actual_worker_expected_os_image_sha256',base_python_sha256,'base_interpreter'),
            ('native_executable_sha256','native_executable_sha256',native_sha256,'native')]:
            check(fingerprint(freeze[key]) and freeze[key]==report.get(field),'frozen_'+label+'_hash')
            if measured is not None: check(fingerprint(measured) and measured==freeze[key],'actual_'+label+'_file_hash')
        pm=protocol['model']; pt=protocol['training']; sched=schedule()
        check(pm.get('id')==MODEL_ID and pm.get('revision')==MODEL_REVISION and pm.get('assets')==ASSETS
            and pm.get('planned_model_loads')==3 and pm.get('planned_optimizer_updates')==6
            and pm.get('dense_only') is True and pm.get('no_download_install_or_GPU') is True,'protocol_model_assets_and_limits')
        check(pt.get('train_sha256')==TRAIN_SHA256 and pt.get('schedule')==sched and pt.get('schedule_sha256')==sha(canonical(sched).encode())
            and pt.get('seed')==503 and pt.get('steps')==2 and pt.get('batch_shape')==[2,65]
            and pt.get('input_tokens_per_batch')==128 and pt.get('optimizer')==OPTIMIZER
            and pt.get('method')=='dense' and pt.get('arm')=='token' and pt.get('holdout_opened') is False
            and pt.get('checkpoint_written') is False,'protocol_training_contract')
        check(report.get('model_id')==MODEL_ID and report.get('model_revision')==MODEL_REVISION
            and report.get('model_assets')==ASSETS,'pinned_model_assets_metadata')
        if actual_model_assets is not None: check(actual_model_assets==ASSETS,'actual_model_asset_bytes_and_hashes')
        declared,frozen=stamp(protocol['predeclared_at']),stamp(freeze['frozen_at'])
        suite_start,suite_end=stamp(report['started_at']),stamp(report['completed_at'])
        check(declared<=frozen<=suite_start<=suite_end,'predeclare_freeze_run_chronology')
        check(report.get('protocol_predeclared_at')==protocol['predeclared_at']
            and report.get('implementation_frozen_at')==freeze['frozen_at'],'reported_freeze_timestamps')
        check(report.get('os_name')=='nt' and report.get('no_fallback') is True,'windows_no_fallback')
        check(report.get('passed') is True and not report.get('error') and report.get('final_wall_budget_exceeded') is not True,'reported_acceptance_pass_not_laundered')
        check(type(report.get('planned_model_loads')) is int and report['planned_model_loads']==3
            and type(report.get('planned_optimizer_updates')) is int and report['planned_optimizer_updates']==6,'fixed_3loads_6updates')
        suite_a,suite_b=interval(report,0,float('inf'),'suite')
        check(0<=report['wall_seconds']<=180.0,'suite_180s_bound')
        check(abs((suite_end-suite_start).total_seconds()-report['wall_seconds'])<=0.25,'suite_utc_wall_agrees')
        cases=report['cases']
        check(len(cases)==5 and [c.get('id') for c in cases]==[s[0] for s in CASES],'all_five_cases_in_order')
        nonces=[c.get('nonce') for c in cases]
        check(all(fingerprint(n) for n in nonces) and len(set(nonces))==len(nonces)==5,'five_unique_256bit_nonces')
    except (KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError) as error:
        check(False,'invalid_suite_receipt:'+str(error)); cases=report.get('cases',[]) if isinstance(report,dict) else []
        if not isinstance(cases,list): cases=[]

    previous_end=suite_a; previous_utc=suite_start; seen_worker_identities=set()
    for case,spec in zip(cases,CASES):
        case_id,mode,allocation=spec; prefix=case_id+':'
        try:
            check((case['id'],case['mode'],case['manual_allocation_bytes'])==spec
                and type(case['manual_allocation_bytes']) is int,prefix+'fixed_case_spec')
            check(case.get('passed') is True and not any(case.get(k) for k in ('error','cleanup_error','job_close_error',
                'process_handle_close_error','failure_cleanup','final_wall_budget_exceeded')),prefix+'no_hidden_failure')
            start,end=interval(case,suite_a,suite_b,prefix+'case')
            check(0<=end-start<=60 and previous_end<=start,prefix+'ordered_case_60s_bound'); previous_end=end
            begin_utc,end_utc=stamp(case['started_at']),stamp(case['completed_at'])
            check(previous_utc<=begin_utc<=end_utc<=suite_end,prefix+'case_utc_order'); previous_utc=end_utc
            check(abs((end_utc-begin_utc).total_seconds()-(end-start))<=0.25,prefix+'case_utc_wall_agrees')
            nonce=case['nonce']; launcher=case['launcher']; lid=ident(launcher,prefix+'launcher')
            check(launcher.get('assigned_while_suspended') is True and launcher.get('job_handle_inherited') is False,prefix+'suspended_job_assignment')
            retained={lid[0]:lid[1]}
            if mode=='prehandshake_fail':
                check(case.get('prehandshake_control')=={'exit_code':37,'handshake_absent':True,
                    'actual_interpreter_identity_unavailable':True},prefix+'exact_prehandshake_control')
                check(not any(case.get(k) for k in ('worker_identity','native_descendant','stages','memory_brackets',
                    'samples','parent_query_costs','stage_process_inventories','import_failure_receipt')),prefix+'no_substituted_worker_or_training')
                check(case.get('outcome')=='expected_prehandshake_exit37',prefix+'outcome')
                cleanup(case,retained,mode,start,end,prefix); continue

            worker=case['worker_identity']; ready=worker['self_receipt']; wid=ident(ready,prefix+'worker')
            msg(ready,nonce,wid[0],prefix+'worker'); reading(ready,wid,start,end,prefix+'worker_ready')
            check(wid not in seen_worker_identities,prefix+'fresh_worker_identity'); seen_worker_identities.add(wid)
            check(worker.get('launcher_differs_from_interpreter') is (lid[0]!=wid[0]),prefix+'launcher_actual_distinction')
            check(ready.get('runtime_executable_basename','').lower()=='python.exe'
                and fingerprint(ready.get('runtime_executable_sha256')),prefix+'runtime_self_image_is_separate_receipt')
            chain=worker['verified_ancestry']; pairs=[ident(x,prefix+'ancestor') for x in chain]
            check(1<=len(chain)<=16 and pairs[0]==wid and pairs[-1]==lid
                and len({p[0] for p in pairs})==len(pairs),prefix+'acyclic_ancestry_endpoints')
            check(ready['parent_pid']==chain[0]['parent_pid'] and all(x.get('job_member') is True for x in chain),prefix+'parent_and_job_membership')
            for i,node in enumerate(chain):
                pid,creation=pairs[i]; check(pid not in retained or retained[pid]==creation,prefix+'retained_creation_consistency'); retained[pid]=creation
                if i+1<len(chain): check(node['parent_pid']==chain[i+1]['pid'] and chain[i+1]['creation_filetime']<=creation,prefix+'parent_creation_order')
            image(worker['os_image'],wid,freeze['base_python_executable_sha256'],ready['perf_counter'],end,prefix+'actual_OS_image')
            image(launcher['os_image'],lid,freeze['python_executable_sha256'],worker['os_image']['verified_perf_counter'],end,prefix+'launcher_OS_image')
            native=case['native_descendant']; nid=ident(native['os_identity'],prefix+'native'); launch=native['launch_receipt']
            msg(launch,nonce,wid[0],prefix+'native_launch')
            check(nid[0] not in retained and native['os_identity']['parent_pid']==wid[0] and nid[1]>=wid[1]
                and launch['native_pid']==nid[0],prefix+'native_direct_descendant_identity'); retained[nid[0]]=nid[1]
            check(native.get('job_member') is True and native.get('no_native_self_report') is True,prefix+'native_OS_identity_job')
            ni=native['os_image']; check(ni.get('basename','').lower()=='cmd.exe' and ni.get('sha256')==freeze['native_executable_sha256']
                and ni.get('matches_frozen') is True,prefix+'native_image_hash')
            check(launch.get('command_arguments')==NATIVE_ARGUMENTS and all(launch.get(k) is True for k in
                ('close_fds','stdin_anonymous_pipe','stdout_devnull','stderr_devnull')) and launch.get('shell') is False
                and type(launch.get('creationflags')) is int and launch['creationflags']==0x08000000,prefix+'native_command_flags')

            samples=case['samples']; queries=case['parent_query_costs']; mem_queries=[]
            check(isinstance(samples,list) and bool(samples),prefix+'parent_samples_present')
            for i,row in enumerate(samples):
                reading(row,wid,start,end,prefix+'sample',cpu=True)
                check(row['perf_counter']>=ready['perf_counter'],prefix+'sample_after_worker_identity')
                if i: check(samples[i-1]['perf_counter']<=row['perf_counter'] and samples[i-1]['native_cpu_seconds']<=row['native_cpu_seconds'],prefix+'sample_clock_cpu_order')
            last_query_end=start; last_cpu_end=0
            for row in queries:
                a,b=interval(row,start,end,prefix+'query_cost')
                check(last_query_end<=a and row.get('kind') in ('actual_interpreter_memory_and_cpu_query','Toolhelp_process_tree_snapshot'),prefix+'query_order_and_kind'); last_query_end=b
                cpu0,cpu1=row['started_process_cpu_seconds'],row['completed_process_cpu_seconds']
                check(all(finite(v) for v in (cpu0,cpu1)) and last_cpu_end<=cpu0<=cpu1,prefix+'query_CPU_clock_order'); last_cpu_end=cpu1
                close(row['parent_process_cpu_seconds'],cpu1-cpu0,prefix+'query_CPU_recomputed')
                check(0<=cpu1-cpu0<=b-a+0.05,prefix+'query_CPU_bounded_by_wall')
                if row['kind']=='actual_interpreter_memory_and_cpu_query': mem_queries.append(row)
            check(len(mem_queries)==len(samples),prefix+'every_parent_sample_has_cost_record')
            for row,s in zip(mem_queries,samples): check(row['started_perf_counter']<=s['perf_counter']<=row['completed_perf_counter'],prefix+'sample_inside_cost_clock')

            labels=('preimport',) if mode=='import_fail' else STAGES
            stages=case['stages']; brackets=case['memory_brackets']
            check(set(stages)==set(labels) and set(brackets)==set(labels),prefix+'exact_stage_inventory')
            last=ready['perf_counter']
            for label in labels:
                stage=stages[label]; msg(stage,nonce,wid[0],prefix+label)
                check(stage.get('stage')==label and integer(stage.get('native_thread_count'),1),prefix+label+':stage_and_native_threads')
                br=brackets[label]; before,parent,after=[br[k] for k in ('self_before','parent','self_after')]
                for name,row in (('before',before),('parent',parent),('after',after)):
                    reading(row,wid,start,end,prefix+label+':'+name,cpu=name=='parent')
                    if name!='parent': msg(row,nonce,wid[0],prefix+label+':'+name)
                ordered=last<=before['perf_counter']<=parent['perf_counter']<=after['perf_counter']; last=after['perf_counter']
                expected={'same_identity':all((v['pid'],v['creation_filetime'])==wid for v in (before,parent,after)),
                    'ordered_monotonic_bracket':before['perf_counter']<=parent['perf_counter']<=after['perf_counter']}
                for metric in ('resident','private'):
                    a,b,c=[x['memory'][metric+'_bytes'] for x in (before,parent,after)]
                    expected[metric+'_within_tolerance']=min(a,c)-4194304<=b<=max(a,c)+4194304
                expected['passed']=all(expected.values())
                check(ordered and expected['passed'] and br['comparison']==expected,prefix+label+':independent_memory_bracket')
                check(parent in samples,prefix+label+':bracket_parent_in_samples')
                check(0<=after['perf_counter']-before['perf_counter']<=5,prefix+label+':bracket_5s_bound')
            check(stages['preimport'].get('torch_imported') is False and stages['preimport'].get('transformers_imported') is False,prefix+'no_ML_before_release')
            check(worker['os_image']['verified_perf_counter']<=brackets['preimport']['self_before']['perf_counter']
                and launcher['os_image']['verified_perf_counter']<=brackets['preimport']['self_before']['perf_counter'],prefix+'OS_images_before_import')

            inventories=case['stage_process_inventories']; expected_labels=list(labels)+(['pretermination'] if mode in ('timeout','private_cap') else [])
            check([r.get('label') for r in inventories]==expected_labels,prefix+'stage_snapshot_inventory')
            previous_snapshot=start
            for row in inventories:
                t=row['perf_counter']; expected_pids=sorted({lid[0],wid[0],nid[0]})
                check(finite(t) and previous_snapshot<=t<=end,prefix+'inventory_clock_order'); previous_snapshot=t
                check(row['expected_live_pids']==row['observed_pids']==expected_pids and row['unknown_descendants']==[],prefix+'snapshot_descendants_exact')
                nodes=row['processes']; ids=[ident(x,prefix+'snapshot') for x in nodes]
                check(len(ids)==len(set(ids)) and set(ids)==set(retained.items()) and all(x.get('job_member') is True and x.get('alive') is True for x in nodes),prefix+'snapshot_retained_members')
                by_pid={x['pid']:x for x in nodes}
                check(by_pid[wid[0]]['parent_pid']==ready['parent_pid'] and by_pid[nid[0]]['parent_pid']==wid[0],prefix+'snapshot_parent_links')
                if row['label'] in labels: check(brackets[row['label']]['self_after']['perf_counter']<=t,prefix+'snapshot_after_bracket')
                lower=brackets[row['label']]['self_after']['perf_counter'] if row['label'] in labels else case['busy_sampling']['completed_perf_counter']
                check(any(x['kind']=='Toolhelp_process_tree_snapshot' and lower<=x['started_perf_counter']<=x['completed_perf_counter']<=t
                    for x in queries),prefix+'inventory_has_timed_snapshot_query')
                if row['label'] in labels:
                    label_index=labels.index(row['label'])
                    if label_index+1<len(labels):
                        upper=brackets[labels[label_index+1]]['self_before']['perf_counter']
                    elif mode=='healthy': upper=min(x['verified_perf_counter'] for x in case['prefinish_live_members'])
                    elif mode in ('timeout','private_cap'): upper=case['busy_ready']['perf_counter']
                    else: upper=case['cleanup']['started_perf_counter']
                    if row['label']=='postupdate' and mode=='healthy': upper=case['held_parent_overhead_windows'][0]['started_perf_counter']
                    check(t<=upper,prefix+'snapshot_before_next_stage_or_release')

            # Cross-record anchors catch a shifted whole cleanup interval even
            # when its own duration and enclosing case bounds remain valid.
            live_rows=case.get('prefinish_live_members',[])+case.get('pretermination_live_members',[])
            anchor=max([ready['perf_counter']]+[x['perf_counter'] for x in inventories]
                +[x['perf_counter'] for x in samples]+[x['completed_perf_counter'] for x in queries]
                +[x['verified_perf_counter'] for x in live_rows])
            check(anchor<=case['cleanup']['started_perf_counter'],prefix+'cleanup_after_all_known_live_and_work_receipts')

            if mode=='import_fail':
                failure=case['import_failure_receipt']; msg(failure,nonce,wid[0],prefix+'import_failure')
                check(failure.get('stage')=='import' and failure.get('exception_type')=='ModuleNotFoundError'
                    and failure.get('missing_module')=='training_observer_missing_dependency_'+nonce
                    and failure.get('torch_imported') is False and failure.get('transformers_imported') is False
                    and type(failure.get('model_loads')) is int and failure['model_loads']==0
                    and type(failure.get('optimizer_steps')) is int and failure['optimizer_steps']==0
                    and type(failure.get('expected_exit_code')) is int and failure['expected_exit_code']==case.get('expected_worker_exit_code')==38,prefix+'precise_import_failure38_no_training')
                check(case.get('outcome')=='expected_injected_import_failure38' and not any(case.get(k) for k in
                    ('allocation_check','healthy_completion','busy_ready','held_parent_overhead_windows')),prefix+'import_failure_outcome')
                clean_a,_=cleanup(case,retained,mode,start,end,prefix)
                check(last<=clean_a and samples[-1]['perf_counter']<=clean_a,prefix+'cleanup_after_preimport'); continue

            check(stages['postimport'].get('torch_version')=='2.9.1+cpu' and stages['postimport'].get('transformers_version')=='4.57.3',prefix+'ML_versions')
            model=stages['postload']['model']; sched=schedule()
            check(model.get('model_id')==MODEL_ID and model.get('model_revision')==MODEL_REVISION
                and model.get('train_sha256')==TRAIN_SHA256 and model.get('schedule')==sched
                and model.get('schedule_sha256')==sha(canonical(sched).encode()),prefix+'pinned_model_training_schedule')
            check(all(type(model.get(k)) is int and model[k]==v for k,v in [('seed',503),('trainable_parameter_count',14067712),
                ('parameter_tensors',76),('intraop_threads',1),('interop_threads',1)]) and model.get('batch_shapes')==[[2,65],[2,65]]
                and model.get('device')=='cpu' and model.get('dtype')=='torch.float32',prefix+'fixed_model_shape_threads')
            check(all(model.get(k) is True for k in ('deterministic_algorithms','loader_local_files_only'))
                and model.get('trust_remote_code') is False and model.get('attention')=='eager' and model.get('holdout_opened') is False
                and model.get('offline_environment')==OFFLINE_ENV and fingerprint(model.get('initial_parameter_sha256')),prefix+'offline_deterministic_loader')
            prepare_a,prepare_b=interval(model['preparation_timing'],start,end,prefix+'model_preparation')
            load_a,load_b=interval(model['model_load_timing'],start,end,prefix+'actual_pretrained_load')
            check(brackets['postimport']['self_after']['perf_counter']<=prepare_a<=load_a<=load_b<=prepare_b<=brackets['postload']['self_before']['perf_counter']
                and 0<=prepare_b-prepare_a<=25 and 0<=load_b-load_a<=25,prefix+'load_nested_in_preparation_25s_bound')
            operation=stages['postupdate']['operation']; loop=operation['loop']; valid=operation['final_validity']
            check(operation.get('method')=='dense' and operation.get('arm')=='token' and operation.get('optimizer')==OPTIMIZER,prefix+'fixed_dense_AdamW')
            check(type(loop.get('steps_completed')) is int and loop['steps_completed']==2 and type(loop.get('training_target_positions')) is int
                and loop['training_target_positions']==256,prefix+'exact_two_updates_256_targets')
            losses=loop['preupdate_batch_losses_recorded_after_updates']
            check(isinstance(losses,list) and len(losses)==2 and all(finite(x) for x in losses),prefix+'two_finite_loss_diagnostics')
            op_a,op_b=loop['loop_perf_counter_start'],loop['loop_perf_counter_end']
            check(all(finite(v) for v in (op_a,op_b)) and brackets['postload']['self_after']['perf_counter']<=op_a<=op_b<=brackets['postupdate']['self_before']['perf_counter'],prefix+'training_inside_load_update_brackets')
            close(loop['training_loop_wall_seconds'],op_b-op_a,prefix+'training_wall_recomputed')
            check(0<op_b-op_a<=15 and finite(loop['training_loop_cpu_seconds']) and 0<=loop['training_loop_cpu_seconds']<=op_b-op_a+0.1,prefix+'training_time_CPU_bound')
            close(loop['training_targets_per_second'],256/(op_b-op_a),prefix+'training_throughput_recomputed')
            counters=valid['optimizer_counters']; check(valid.get('final_parameter_gradient_moments_finite') is True and len(counters)==76
                and all(type(v) is int and v==2 for v in counters),prefix+'76_finite_parameter_gradient_moment_counters')
            check(fingerprint(operation.get('final_parameter_sha256')) and operation['final_parameter_sha256']!=model['initial_parameter_sha256']
                and operation.get('no_checkpoint_written') is True and operation.get('no_holdout_evaluation') is True,prefix+'parameter_change_without_checkpoint_holdout')
            check(type(stages['allocated'].get('manual_allocation_bytes')) is int and stages['allocated']['manual_allocation_bytes']==allocation,prefix+'allocated_stage_bytes')
            baseline,allocated=brackets['postupdate'],brackets['allocated']
            deltas={m:allocated['parent']['memory'][m]-baseline['parent']['memory'][m] for m in ('resident_bytes','private_bytes')}
            minimum=58720256 if allocation else 0
            expected={'explicit_allocation_bytes':allocation,'parent_deltas_bytes':deltas,'minimum_required_increase_bytes':minimum,
                'passed':allocation==0 or all(v>=minimum for v in deltas.values())}
            check(expected['passed'] and case['allocation_check']==expected,prefix+'independent_allocation_delta')

            if mode=='healthy':
                windows=case['held_parent_overhead_windows']; check(len(windows)==2 and [x.get('sampling_enabled') for x in windows]==[False,True]
                    and all(type(x.get('sampling_enabled')) is bool for x in windows),prefix+'fixed_off_on_overhead_windows')
                last_end=baseline['self_after']['perf_counter']; last_native_cpu=0
                for w in windows:
                    a,b=interval(w,start,end,prefix+'overhead'); check(last_end<=a<=b<=allocated['self_before']['perf_counter'] and 0.4-1e-8<=b-a<=0.9,prefix+'held_0point4s_overhead_clock'); last_end=b
                    c0,c1=w['parent_native_cpu_start_seconds'],w['parent_native_cpu_end_seconds']; check(all(finite(v) for v in (c0,c1)) and last_native_cpu<=c0<=c1
                        and 0<=c1-c0<=b-a+0.05,prefix+'overhead_native_CPU_clock'); last_native_cpu=c1
                    close(w['parent_native_cpu_delta_seconds'],c1-c0,prefix+'overhead_CPU_recomputed')
                    qi,qj=w['query_cost_index_start'],w['query_cost_index_end']; si,sj=w['sample_index_start'],w['sample_index_end']
                    check(all(type(v) is int for v in (qi,qj,si,sj)) and 0<=qi<=qj<=len(queries) and 0<=si<=sj<=len(samples),prefix+'overhead_slice_indices')
                    selected=queries[qi:qj]; ss=samples[si:sj]
                    check(all(a<=x['started_perf_counter']<=x['completed_perf_counter']<=b for x in selected)
                        and all(a<=x['perf_counter']<=b for x in ss),prefix+'overhead_slices_inside_hold')
                    actual_q=[x for x in queries if a<=x['started_perf_counter'] and x['completed_perf_counter']<=b]
                    actual_s=[x for x in samples if a<=x['perf_counter']<=b]
                    check(selected==actual_q and ss==actual_s,prefix+'overhead_complete_slices')
                    if w['sampling_enabled']:
                        check(bool(ss) and len(selected)==2*len(ss)
                            and [x['kind'] for x in selected]==['actual_interpreter_memory_and_cpu_query','Toolhelp_process_tree_snapshot']*len(ss),prefix+'enabled_query_sampling_counts')
                    else: check(qi==qj and si==sj,prefix+'disabled_window_has_no_queries')
                check(windows[0]['query_cost_index_end']==windows[1]['query_cost_index_start']
                    and windows[0]['sample_index_end']==windows[1]['sample_index_start'],prefix+'adjacent_overhead_slices')
                done=case['healthy_completion']; msg(done,nonce,wid[0],prefix+'healthy_completion')
                check(type(done.get('native_exit_code')) is int and done['native_exit_code']==0 and done.get('native_released_nonempty_line') is True
                    and type(done.get('model_loads')) is int and done['model_loads']==1 and type(done.get('optimizer_steps')) is int and done['optimizer_steps']==2,prefix+'precise_healthy_completion')
                check(case.get('healthy_memory_limit_disabled') is True and case.get('outcome')=='normal_completion'
                    and not any(k.startswith('termination_request_') for k in case),prefix+'healthy_no_false_termination')
                live=case['prefinish_live_members']; live_ids=[ident(x,prefix+'prefinish') for x in live]
                check(live_ids==[wid,nid] and all(x.get('alive') is True and x.get('job_member') is True
                    and last<=x['verified_perf_counter']<=end for x in live),prefix+'healthy_live_before_release')
            else:
                check(not case.get('held_parent_overhead_windows'),prefix+'no_unplanned_busy_overhead')
                busy,first,summary=case['busy_ready'],case['busy_first_operation'],case['busy_sampling']
                for name,row in [('busy',busy),('first_forward',first)]:
                    msg(row,nonce,wid[0],prefix+name)
                    check(all(type(row.get(k)) is int and row[k]==0 for k in ('extra_backward_calls','extra_optimizer_steps'))
                        and row.get('model_forward_no_grad') is True,prefix+name+':no_extra_updates')
                check(type(first.get('model_forward_iterations_completed')) is int and first['model_forward_iterations_completed']==1,prefix+'one_busy_forward_completed')
                a,b=interval(summary,start,end,prefix+'busy')
                check(last<=a==busy['perf_counter']<=first['completed_perf_counter']<=b,prefix+'busy_after_allocation')
                selected=[s for s in samples if a<=s['perf_counter']<=b]; points=[a]+[s['perf_counter'] for s in selected]+[b]
                gap=max(y-x for x,y in zip(points,points[1:])); cpu=selected[-1]['native_cpu_seconds']-selected[0]['native_cpu_seconds'] if len(selected)>=2 else 0
                check(type(summary['samples_count']) is int and summary['samples_count']==len(selected) and bool(selected),prefix+'busy_samples_recomputed')
                close(summary['maximum_gap_including_boundaries_seconds'],gap,prefix+'busy_boundary_gap_recomputed')
                close(summary['native_cpu_delta_seconds'],cpu,prefix+'busy_CPU_delta_recomputed')
                check(summary.get('gap_gate_passed') is True and gap<=0.5,prefix+'busy_gap_gate')
                req,ret=case['termination_request_started_perf_counter'],case['termination_request_returned_perf_counter']
                check(all(finite(x) for x in (req,ret)) and b<=req<=ret<=end,prefix+'termination_clock')
                live=case['pretermination_live_members']; live_ids=[ident(x,prefix+'pretermination') for x in live]
                check(live_ids==[wid,nid] and all(x.get('alive') is True and x.get('job_member') is True
                    and finite(x['verified_perf_counter']) and b<=x['verified_perf_counter']<=req for x in live),prefix+'both_live_before_termination')
                check(inventories[-1]['perf_counter']<=req and inventories[-1]['perf_counter']>=b,prefix+'pretermination_snapshot_before_request')
                if mode=='timeout':
                    close(case['busy_deadline_perf_counter'],a+1.5,prefix+'fixed_1point5s_deadline')
                    check(b-a>=1.5 and req>=a+1.5 and cpu>=0.25 and case.get('outcome')=='timeout',prefix+'deadline_and_busy_CPU_gate')
                else:
                    limit=baseline['parent']['memory']['private_bytes']+50331648
                    check(type(case['actual_interpreter_private_limit_bytes']) is int and case['actual_interpreter_private_limit_bytes']==limit,prefix+'postupdate_sampled_private_limit')
                    crossed=[s for s in samples if s['perf_counter']>=allocated['self_before']['perf_counter'] and s['memory']['private_bytes']>limit]
                    check(bool(crossed) and case['first_over_limit_sample']==crossed[0] and samples[-1]['memory']['private_bytes']>limit,prefix+'first_and_latest_sampled_crossing')
                    close(case['allocation_ready_to_termination_seconds'],ret-allocated['self_before']['perf_counter'],prefix+'cap_response_recomputed')
                    check(0<=ret-allocated['self_before']['perf_counter']<=1.0 and case.get('outcome')=='memory_private_limit',prefix+'cap_response_1s_bound')
            clean_a,_=cleanup(case,retained,mode,start,end,prefix)
            check(last<=clean_a and samples[-1]['perf_counter']<=clean_a,prefix+'cleanup_after_recorded_work')
        except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,ZeroDivisionError) as error:
            check(False,prefix+'invalid_or_incomplete_receipt:'+str(error))
    failures=[x['check'] for x in checks if not x['passed']]
    omitted=[label for value,label in [(launch_sha256,'launcher_executable_file'),(base_python_sha256,'actual_base_interpreter_file'),
        (native_sha256,'native_executable_file'),(actual_model_assets,'local_model_asset_files')] if value is None]
    return {'schema_version':1,'passed':not failures,'receipt_consistency_passed':not failures,
        'check_count':len(checks),'checks_passed':sum(x['passed'] for x in checks),'failures':failures,'checks':checks,
        'unperformed_optional_file_checks':omitted,'root_freeze_pins_set':PROTOCOL_SHA256 is not None and SOURCE_HASHES is not None and DEPENDENCY_HASHES is not None,
        'scope':'Offline stdlib receipt/hash/algebra consistency only; no OS remeasurement, experiment/ML import or process execution. Optional local executable/model bytes are unverified unless supplied. Two-update semantics also rely on the frozen historical helper; counters are not independent per-call tracing. Snapshot inventories cannot prove continuous child absence, provider behavior or exact concurrent kernel threads. Memory brackets are current readings and peaks are process-lifetime values; cap is sampled with overshoot, not an import/training hard ceiling. Held off/on windows are descriptive, ordered, and do not estimate causal training slowdown. Cannot authenticate coherently rewritten evidence, establish quality/compression/cost gains or revise historic scientific negatives.'}


def bounded(path,maximum_bytes=1048576):
    raw=Path(path).read_bytes()
    if not 0<len(raw)<=maximum_bytes: raise ValueError('empty JSON or receipt exceeds fixed byte bound')
    def reject(v): raise ValueError('nonfinite JSON number:'+v)
    def pairs(values):
        result={}
        for key,value in values:
            if key in result: raise ValueError('duplicate JSON key:'+key)
            result[key]=value
        return result
    return raw,json.loads(raw,parse_constant=reject,object_pairs_hook=pairs)


def audit_files(report_path,protocol_path,freeze_path,python_path=None,base_python_path=None,native_path=None,model_dir=None,root=ROOT):
    # Fixed before real acceptance: full180s sampling can exceed1MiB. Protocol
    # and implementation metadata retain the smaller1MiB bound.
    raw,report=bounded(report_path,16*1048576); pr,protocol=bounded(protocol_path); fr,freeze=bounded(freeze_path)
    model_assets=None if model_dir is None else {name:{'bytes':(Path(model_dir)/name).stat().st_size,
        'sha256':sha((Path(model_dir)/name).read_bytes())} for name in ASSETS}
    result=audit(report,protocol,freeze,protocol_sha256=sha(pr),freeze_sha256=sha(fr),
        actual_source_sha256={p:sha((Path(root)/p).read_bytes()) for p in SOURCE_PATHS},
        actual_dependency_sha256={p:sha((Path(root)/p).read_bytes()) for p in DEPENDENCY_PATHS},
        launch_sha256=None if python_path is None else sha(Path(python_path).read_bytes()),
        base_python_sha256=None if base_python_path is None else sha(Path(base_python_path).read_bytes()),
        native_sha256=None if native_path is None else sha(Path(native_path).read_bytes()),actual_model_assets=model_assets)
    result.update(report_file_sha256=sha(raw),protocol_file_sha256=sha(pr),implementation_freeze_file_sha256=sha(fr))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('report','protocol','freeze','output'): parser.add_argument('--'+key,type=Path,required=True)
    for key in ('python','base-python','native','model-dir'): parser.add_argument('--'+key,type=Path)
    args=parser.parse_args(argv)
    result=audit_files(args.report,args.protocol,args.freeze,args.python,args.base_python,args.native,args.model_dir)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n')
    print(json.dumps({k:result[k] for k in ('passed','check_count','checks_passed','failures')}))
    return 0 if result['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
