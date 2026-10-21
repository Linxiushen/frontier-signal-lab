"""Independent saved-byte audit of actual training-ledger integration v2.

Only stdlib parsing/replay; no producer or ML import and no workload execution.
Healthy caller checks are copied from the immutable duty-v2 saved-byte auditor.
No ABBA/overhead or scientific cost/quality acceptance is inferred from one arm.
"""
import argparse
import hashlib
import json
from pathlib import Path
from scripts.audit_observer_duty_v2 import (Replay,canonical,stamp,reading,replay_roles,
    replay_controls,replay_training,replay_active,replay_postvalidation_ack_barrier,
    raw_payloads,close,finite,fingerprint,STAGES,CONFIG,NATIVE_ARGUMENTS)
from scripts import audit_observer_duty_v2 as legacy

ROOT=Path(__file__).resolve().parents[1]
LIMITS={"max_rows":900,"max_row_bytes":8192,"max_total_bytes":4194304}
sha=lambda b:hashlib.sha256(b).hexdigest()


def replay_partial_roles(case, freeze, lower, upper):
    """Reconstruct the exact primary/console policy from raw retained rows."""
    replay = Replay()
    check = replay.check
    executables, paths = freeze['executables_sha256'], freeze['executable_path_sha256']
    launcher = replay.identity(case['launcher'], 'role:launcher')
    worker = replay.identity(case['worker_identity']['self_receipt'], 'role:worker')
    native = replay.identity(case['native_descendant']['os_identity'], 'role:native')
    labels = ['before_native', *STAGES[:2]]
    rows, decisions = case['censuses'], case['role_decisions']
    check(len(rows) == len(decisions) == len(labels) and
          [row['label'] for row in rows] == [row['label'] for row in decisions] == labels,
          'role:fixed_complete_stage_inventory')
    retained, parents, image_pins, pins = {}, {}, {}, {}
    previous = lower
    for index, (row, decision, label) in enumerate(zip(rows, decisions, labels)):
        tag = 'role:' + label
        start, census_end = replay.span(row, previous, upper, 5, tag + ':census')
        decision_start, decision_end = replay.span(decision, start, upper, 5, tag + ':decision')
        check(start == decision_start and census_end <= decision_end,
              tag + ':decision_covers_raw_census_and_hold')
        previous = decision_end
        check(row['training_permitted'] is False and row['census_complete'] is True and
              row['errors'] == [] and row['truncated'] is False and row['query_budget_exceeded'] is False and
              row['all_known_present'] is True, tag + ':complete_no_error_inventory')
        nodes = row['processes']
        refs = [replay.identity(node, tag) for node in nodes]
        by_pid = {node['pid']: node for node in nodes}
        check(len(nodes) == len(by_pid) == len(set(refs)) == (3 if index == 0 else 5) and
              all(type(pid) is int for pid in row['observed_pids']) and
              row['observed_pids'] == sorted(by_pid) and type(row['snapshot_observed_count']) is int and
              row['snapshot_observed_count'] == len(nodes), tag + ':exact_three_or_five_unique_observed')
        check(all(type(row[key]) is int and row[key] == len(nodes) for key in ('job_count_before', 'job_count_after')) and
              row['job_count_matches_before'] is True and row['job_count_matches_after'] is True,
              tag + ':two_raw_job_counts')
        primary = {launcher: 'launcher', worker: 'base_python'}
        if index:
            primary[native] = 'native'
        check(set(primary) <= set(refs) and (native[0] in by_pid) == bool(index), tag + ':exact_primary_registration')
        for node, ref in zip(nodes, refs):
            check(node['job_member'] is True and node['alive'] is True and not node.get('error'), tag + ':held_same_live_job')
            check(ref[0] not in retained or retained[ref[0]] == ref[1], tag + ':no_PID_reuse')
            retained[ref[0]] = ref[1]
            check(ref not in parents or parents[ref] == node['parent_pid'], tag + ':stable_parent')
            parents[ref] = node['parent_pid']
            value = replay.image(node, primary.get(ref), executables, paths, tag)
            check(ref not in image_pins or image_pins[ref] == value, tag + ':stable_OS_image_path')
            image_pins[ref] = value
            check(node['approved_known'] is (ref in primary) and node['policy_role'] == primary.get(ref, 'unapproved'),
                  tag + ':raw_primary_roles_are_exact_identities')
        check(parents[worker] == launcher[0] and (not index or parents[native] == worker[0]), tag + ':primary_direct_parent_graph')
        expected_primary = []
        for ref, role in primary.items():
            parent = None if role == 'launcher' else launcher if role == 'base_python' else worker
            expected_primary.append({'pid': ref[0], 'creation_filetime': ref[1], 'role': role,
                'parent_ref': None if parent is None else {'pid': parent[0], 'creation_filetime': parent[1]},
                'frozen_image_sha256': executables[role], 'frozen_path_sha256': paths[role]})
            if parent:
                check(parent[1] <= ref[1], tag + ':primary_creation_order')
        aux = []
        aux_refs = set()
        for owner_role, owner in [('launcher', launcher)] + ([('native', native)] if index else []):
            matches = [node for node in nodes if node['parent_pid'] == owner[0] and
                       node['image']['sha256'] == executables['conhost'] and
                       node['image']['normalized_path_sha256'] == paths['conhost'] and
                       'conhost' in node['image']['exact_path_matches']]
            check(len(matches) == 1, tag + ':one_exact_console_for_' + owner_role)
            if len(matches) != 1:
                continue
            node = matches[0]
            ref = replay.identity(node, tag + ':console')
            replay.image(node, 'conhost', executables, paths, tag + ':console')
            check(owner[1] <= ref[1] and ref not in primary, tag + ':console_owner_creation')
            pin = {'owner_ref': {'pid': owner[0], 'creation_filetime': owner[1]},
                'auxiliary_ref': {'pid': ref[0], 'creation_filetime': ref[1]},
                'frozen_image_sha256': executables['conhost'], 'frozen_path_sha256': paths['conhost']}
            check(owner_role not in pins or pins[owner_role] == pin, tag + ':console_identity_pinned')
            pins[owner_role] = pin
            aux_refs.add(ref)
            aux.append({'pid': ref[0], 'creation_filetime': ref[1], 'role': 'console_auxiliary',
                'parent_ref': pin['owner_ref'], 'owner_role': owner_role,
                'frozen_image_sha256': executables['conhost'], 'frozen_path_sha256': paths['conhost']})
        admitted = set(primary) | aux_refs
        check(set(refs) == admitted, tag + ':no_unregistered_same_image_identity')
        check(row['unapproved_pids'] == sorted(ref[0] for ref in aux_refs) and
              all(type(pid) is int for pid in row['unapproved_pids']), tag + ':raw_unapproved_is_console_only')
        check(type(decision['census_index']) is int and type(decision['decision_index']) is int and
              decision['census_index'] == decision['decision_index'] == index and
              decision['training_permitted'] is False and decision['admitted'] is True,
              tag + ':positive_policy_decision_identity')
        check(decision['primary_roles'] == expected_primary and decision['auxiliary_roles'] == aux and
              decision['admitted_pids'] == sorted(ref[0] for ref in admitted) and
              all(type(pid) is int for pid in decision['admitted_pids']) and decision['rejected_pids'] == [] and
              decision['rejections'] == [] and decision['errors'] == [] and decision['pinned_auxiliaries'] == pins,
              tag + ':independently_reconstructed_roles_and_admission')
        live = decision['held_liveness']
        live_refs = [replay.identity(value, tag + ':held') for value in live]
        check(len(live) == len(set(live_refs)) == len(nodes) and set(live_refs) == set(refs) and
              all(type(decision[key]) is int and decision[key] == len(nodes) for key in ('job_count_before', 'job_count_after')),
              tag + ':complete_post_census_held_liveness')
        held_previous = census_end
        for value in live:
            instant = value['verified_perf_counter']
            check(value['alive'] is True and value['job_member'] is True and finite(instant) and
                  held_previous <= instant <= decision_end, tag + ':post_census_liveness_clock')
            held_previous = instant
        if label in STAGES:
            check(case['memory_brackets'][label]['parent']['perf_counter'] <= start and
                  decision_end <= case['memory_brackets'][label]['self_after']['perf_counter'],
                  tag + ':role_census_inside_memory_bracket')
    return retained, replay.checks



def healthy(case,freeze,raw,start,end,started,completed):
    replay=Replay();check=replay.check
    spec=("healthy",True);prefix="healthy:"
    actual_raw_files={case["id"]:raw}
    suite_a,suite_b=start,end
    suite_utc=(started,completed)
    previous=start;last_utc=started;worker_refs=set();trajectories=[];loop_walls={}
    check(case['id']==spec[0] and type(case['sampling_enabled']) is bool and case['sampling_enabled'] is spec[1],prefix+'exact_case_spec')
    check(case['passed'] is True and case['outcome']=='normal_completion' and not any(case.get(k) for k in ('error','cleanup_error','job_close_error','process_handle_close_error',
        'worker_failure_receipt','worker_failure_custody_error','failure_cleanup','case_wall_budget_exceeded')),prefix+'no_hidden_failure')
    if actual_raw_files is not None:
        check(canonical(actual_raw_files[case['id']])==canonical(raw_payloads(case)),prefix+'exact_raw_identity_controls_stages_loop_completion_files')
    start,end=replay.span(case,suite_a,suite_b,60,prefix+'case')
    check(previous<=start,prefix+'ordered_nonoverlapping_cases');previous=end
    a,b=stamp(case['started_at']),stamp(case['completed_at'])
    check(last_utc<=a<=b<=suite_utc[1],prefix+'UTC_order');last_utc=b
    check(abs((b-a).total_seconds()-(end-start))<=0.25,prefix+'UTC_perf_wall_agrees')
    check(case['case_deadline_perf_counter']==min(start+60,suite_a+240) and case['suite_deadline_perf_counter']==suite_a+240 and
        end<=case['case_deadline_perf_counter'],prefix+'nonrenewable_case_suite_deadlines')
    check(case['executables_sha256']==freeze['executables_sha256'] and case['executable_path_sha256']==freeze['executable_path_sha256'] and
        case['provider_source_sha256']==freeze['provider_source_sha256'] and case['provider_source_path_sha256']==freeze['provider_source_path_sha256'],
        prefix+'case_exact_executable_and_provider_freeze')
    lid=replay.identity(case['launcher'],prefix+'launcher');worker=case['worker_identity'];ready=worker['self_receipt']
    wid=replay.identity(ready,prefix+'worker');replay.message(ready,case['nonce'],'worker',wid[0],prefix+'worker_ready')
    check(wid not in worker_refs,prefix+'fresh_worker_creation_identity');worker_refs.add(wid)
    reading(replay,ready,wid,start,end,prefix+'ready')
    check(case['launcher']['assigned_while_suspended'] is True and case['launcher']['job_handle_inherited'] is False,prefix+'suspended_noninherited_Job')
    check(worker['launcher_differs_from_interpreter'] is (wid[0]!=lid[0]) and
        worker['self_executable_expected_role']=='launcher' and worker['retained_os_image_expected_role']=='base_python' and
        ready['self_executable']=={'source':'sys.executable','basename':'python.exe','sha256':freeze['executables_sha256']['launcher'],
        'normalized_path_sha256':freeze['executable_path_sha256']['launcher']},prefix+'distinct_launcher_self_and_retained_OS_worker_roles')
    chain=worker['verified_ancestry'];refs=[replay.identity(v,prefix+'ancestor') for v in chain]
    check(len(refs)==2 and refs==[wid,lid] and ready['parent_pid']==chain[0]['parent_pid'] and
        chain[0]['parent_pid']==lid[0] and lid[1]<=wid[1] and all(v['job_member'] is True for v in chain),prefix+'exact_held_ancestry')
    for value,identity,role_name in [(worker['os_image'],wid,'base_python'),(case['launcher']['os_image'],lid,'launcher')]:
        check(replay.identity(value,prefix+'OS_image')==identity and value['basename'].lower()=='python.exe' and
            value['sha256']==freeze['executables_sha256'][role_name] and value['queried_from_retained_handle'] is True and
            value['matches_frozen_path_and_hash'] is True and start<=value['verified_perf_counter']<=
            case['memory_brackets']['preimport']['self_before']['perf_counter'],prefix+'retained_OS_image_hash_path_before_import')
    native=case['native_descendant'];nid=replay.identity(native['os_identity'],prefix+'native');launch=native['launch_receipt']
    replay.message(launch,case['nonce'],'worker',wid[0],prefix+'native_launch')
    check(type(launch['native_pid']) is int and launch['native_pid']==nid[0] and native['os_identity']['parent_pid']==wid[0] and
        native['job_member'] is True and native['no_native_self_report'] is True and wid[1]<=nid[1],prefix+'native_exact_direct_parent_Job_identity')
    check(native['os_image']=={'basename':'cmd.exe','sha256':freeze['executables_sha256']['native'],'matches_frozen':True},
        prefix+'native_OS_image_exact_frozen_bytes')
    check(launch['command_arguments']==NATIVE_ARGUMENTS and launch['close_fds'] is True and launch['stdin_anonymous_pipe'] is True and
        launch['shell'] is False and type(launch['creationflags']) is int and launch['creationflags']==0x08000000 and
        launch['stdout_devnull'] is True and launch['stderr_devnull'] is True,prefix+'fixed_hidden_native_pipe_launch')
    check(list(case['stages'])==list(STAGES) and set(case['memory_brackets'])==set(STAGES),prefix+'complete_five_held_stages')
    prior=start
    for label in STAGES:
        stage=case['stages'][label];replay.message(stage,case['nonce'],'worker',wid[0],prefix+label)
        check(stage['stage']==label and type(stage['native_thread_count']) is int and stage['native_thread_count']>=1,prefix+label+':raw_native_thread_count')
        bracket=case['memory_brackets'][label];before,parent,after=[bracket[k] for k in ('self_before','parent','self_after')]
        for key,value in [('self_before',before),('parent',parent),('self_after',after)]:
            reading(replay,value,wid,start,end,prefix+label+':'+key,key=='parent')
            if key!='parent':replay.message(value,case['nonce'],'worker',wid[0],prefix+label+':'+key)
        ordered=prior<=before['perf_counter']<=parent['perf_counter']<=after['perf_counter'];prior=after['perf_counter']
        expected={'same_identity':True,'ordered_monotonic_bracket':ordered}
        for metric in ('resident','private'):
            values=[v['memory'][metric+'_bytes'] for v in (before,parent,after)]
            expected[metric+'_within_tolerance']=min(values[0],values[2])-4194304<=values[1]<=max(values[0],values[2])+4194304
        expected['passed']=all(expected.values())
        check(ordered and expected['passed'] and bracket['comparison']==expected and parent in case['samples'] and
            after['perf_counter']-before['perf_counter']<=5,prefix+label+':independent_synchronized_memory_bracket')
    check(case['stages']['preimport']['torch_imported'] is False and case['stages']['preimport']['transformers_imported'] is False and
        case['stages']['postimport']['torch_version']=='2.9.1+cpu' and case['stages']['postimport']['transformers_version']=='4.57.3',
        prefix+'authorized_actual_ML_import_versions')
    retained,checks=replay_roles(case,freeze,start,end);replay.checks.extend({'check':prefix+c['check'],'passed':c['passed']} for c in checks)
    queries=case['parent_query_costs'];samples=case['samples']
    check(len(queries)==11 and len(samples)==5 and
        [q['kind'] for q in queries].count('boundary_worker_memory_and_cpu')==5 and
        [q['kind'] for q in queries].count('held_role_census_and_liveness')==6,prefix+'exact_held_boundary_query_inventory')
    previous_query=start
    for q in queries:
        qa,qb=replay.span(q,previous_query,end,5,prefix+'boundary_query');previous_query=qb
        close(replay,q['parent_process_cpu_seconds'],q['completed_process_cpu_seconds']-q['started_process_cpu_seconds'],
            prefix+'boundary_query_CPU_recomputed')
        check(all(finite(q[k]) and q[k]>=0 for k in ('started_process_cpu_seconds','completed_process_cpu_seconds','parent_process_cpu_seconds')),
            prefix+'boundary_query_CPU_nonnegative')
    memory_queries=[q for q in queries if q['kind']=='boundary_worker_memory_and_cpu']
    for sample,q in zip(samples,memory_queries):
        reading(replay,sample,wid,q['started_perf_counter'],q['completed_perf_counter'],prefix+'held_parent_query_sample',True)
    census_queries=[q for q in queries if q['kind']=='held_role_census_and_liveness']
    for q,c,d in zip(census_queries,case['censuses'],case['role_decisions']):
        check(q['started_perf_counter']<=c['started_perf_counter']<=c['completed_perf_counter']<=
            d['completed_perf_counter']<=q['completed_perf_counter'],prefix+'every_census_inside_timed_boundary_query')
    for fn in (replay_controls,replay_training):
        checks=fn(case,freeze,start,end) if fn is replay_controls else fn(case,start,end)
        replay.checks.extend({'check':prefix+c['check'],'passed':c['passed']} for c in checks)
    for field in ('loop_before','loop_after'):
        replay.message(case[field],case['nonce'],'worker',wid[0],prefix+field)
    checks=replay_active(case,wid,start,end);replay.checks.extend({'check':prefix+c['check'],'passed':c['passed']} for c in checks)
    checks=replay_postvalidation_ack_barrier(case,wid,start,end)
    replay.checks.extend({'check':prefix+c['check'],'passed':c['passed']} for c in checks)
    for field in ('cleanup_exact_retained_identity_set','provider_custody_verified','control_custody_verified'):
        check(case[field] is True,prefix+'producer_'+field)
    completed=case['healthy_completion'];replay.message(completed,case['nonce'],'worker',wid[0],prefix+'completion')
    check(type(completed['model_loads']) is int and completed['model_loads']==1 and type(completed['optimizer_steps']) is int and
        completed['optimizer_steps']==16 and type(completed['native_exit_code']) is int and completed['native_exit_code']==0 and
        completed['native_released_nonempty_line'] is True,prefix+'precise_one_load_sixteen_updates_native_normal_completion')
    clean=case['cleanup'];ca,cb=replay.span(clean,start,end,4,prefix+'cleanup')
    check(finite(clean['timeout_seconds']) and 0<=cb-ca<=clean['timeout_seconds']<=4,prefix+'cleanup_four_second_bound')
    live=case['prefinish_live_members'];live_refs=[replay.identity(v,prefix+'prefinish_live') for v in live]
    check(len(live)==len(set(live_refs))==2 and set(live_refs)=={wid,nid} and all(v['alive'] is True and v['job_member'] is True and
        case['worker_controls'][10]['accepted_perf_counter']<=v['verified_perf_counter']<=
        case['controller_controls'][11]['emitted_perf_counter']<=ca for v in live),prefix+'exact_worker_native_prefinish_liveness')
    exits=clean['exit_codes'];exitrefs=[replay.identity(v,prefix+'exit') for v in exits]
    check(len(exitrefs)==len(set(exitrefs))==5 and set(exitrefs)==set(retained.items()) and
        all(type(v['exit_code']) is int and v['exit_code']==0 for v in exits) and clean['all_retained_handles_exited'] is True and
        type(clean['job_active_count']) is int and clean['job_active_count']==0,prefix+'exact_five_retained_exit_zero_and_empty_Job')
    check(ca>=case['memory_brackets']['postvalidation']['self_after']['perf_counter'] and ca>=case['active_window']['completed_perf_counter'],prefix+'cleanup_after_all_recorded_work')
    model=case['stages']['pretrain']['model'];valid=case['stages']['postvalidation']['validation'];loop=case['loop_after']['loop']
    trajectories.append((model['initial_parameter_sha256'],model['schedule_sha256'],valid['final_parameter_sha256'],
        canonical(loop['preupdate_batch_losses_recorded_after_updates'])))
    loop_walls[case['id']]=loop['training_loop_wall_seconds']
    return replay.checks


def ledger_checks(case,raw):
    snap=case["ledger"]
    records=snap["records"]
    encoded=[(json.dumps(r,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)+"\n").encode() for r in records]
    prefix=b"".join(encoded)
    assert len(records)==snap["committed_rows"]<=LIMITS["max_rows"]
    assert all(r["seq"]==i for i,r in enumerate(records))
    assert all(len(v)<=LIMITS["max_row_bytes"] for v in encoded)
    assert len(prefix)==snap["committed_bytes"]<=LIMITS["max_total_bytes"]
    fault=case["id"]=="partial_pretrain"
    assert raw==(prefix+b'{"cre' if fault else prefix)
    assert snap["poisoned"] is fault and case["fault_injected"] is fault
    worker=case["worker_identity"]["self_receipt"]
    first=records[0]
    assert first["kind"]=="bound" and first["pid"]==worker["pid"] and first["creation_filetime"]==worker["creation_filetime"]
    assert first["launcher_pid"]==case["launcher"]["pid"]!=worker["pid"]
    rows=[r for r in records if r["kind"]=="sample"]
    expected=[("held:"+label,case["memory_brackets"][label]["parent"]) for label in (STAGES[:2] if fault else STAGES)]
    if not fault:
        expected+= [("active:"+str(r["index"]),r["sample"]) for r in case["active_window"]["observations"]]
    assert len(rows)==len(expected) and len(set(r["request_id"] for r in rows))==len(rows)
    assert {r["request_id"]:r["reading"] for r in rows}==dict(expected)
    previous=case["started_perf_counter"]
    for r in records:
        assert previous<=r["emitted_perf_counter"]<=case["completed_perf_counter"]
        assert type(r["native_thread_id"]) is int and r["native_thread_id"]>0
        previous=r["emitted_perf_counter"]
    for r in rows:
        assert r["pid"]==worker["pid"] and r["creation_filetime"]==worker["creation_filetime"]
        assert r["query_started_perf_counter"]<=r["member_verified_perf_counter"]<=r["reading"]["perf_counter"]<=r["query_completed_perf_counter"]<=r["emitted_perf_counter"]
        assert r["reading"]["pid"]==worker["pid"] and r["reading"]["creation_filetime"]==worker["creation_filetime"]
        assert r["reading"]["memory"]["private_bytes"]<=1073741824
    if fault:
        assert len(records)==3 and snap["failure"]["seq"]==3 and snap["failure"]["stage"]=="write"
        assert snap["failure"]["error_type"]=="OSError" and snap["failure"]["sink_may_have_uncommitted_bytes"] is True
    else:
        assert records[-1]["kind"]=="closed" and records[-1]["cleanup"]==case["cleanup"] and snap["failure"] is None
        assert len(records)==len(rows)+2
    return {"rows":len(records),"samples":len(rows),"bytes":len(prefix),"uncertain_tail_bytes":5 if fault else 0}


def fault_checks(case,healthy_case,directory,freeze):
    assert case["passed"] is True and case["outcome"]=="expected_pretrain_trace_failure"
    assert case["post_poison_query_refused"] is True
    assert case["expected_fault"]=={"type":"LedgerIOError","stage":"pretrain","before_training_release":True}
    assert not any(case.get(k) for k in ("cleanup_error","fault_contract_error","job_close_error","process_handle_close_error","worker_failure_receipt","worker_failure_custody_error","case_wall_budget_exceeded"))
    assert list(case["stages"])==list(STAGES[:3]) and set(case["memory_brackets"])==set(STAGES[:2])
    assert [r["label"] for r in case["censuses"]]==["before_native","preimport","postimport"]
    assert len(case["controller_controls"])==5
    assert case["stages"]["pretrain"]["model"]==healthy_case["stages"]["pretrain"]["model"] or all(
        case["stages"]["pretrain"]["model"][k]==healthy_case["stages"]["pretrain"]["model"][k] for k in
        ("model_id","model_revision","seed","train_sha256","schedule","schedule_sha256","initial_parameter_sha256","optimizer_state_entries","optimizer","holdout_opened"))
    wid=case["worker_identity"]["self_receipt"]
    for label in STAGES[:3]:
        ready=json.loads((directory/(label+"-ready.json")).read_bytes())
        assert ready==case["stages"][label] and ready["nonce"]==case["nonce"] and ready["pid"]==wid["pid"]
        checks=legacy.replay_provider(ready["provider_guard"],freeze,legacy.PHASES[label],1,case["started_perf_counter"],case["completed_perf_counter"])
        assert all(r["passed"] for r in checks),checks
    for row in case["controller_controls"]:
        accepted=json.loads((directory/row["filename"].replace(".json","-accepted.json")).read_bytes())
        assert accepted["pid"]==wid["pid"] and accepted["nonce"]==case["nonce"]
        assert accepted["control_envelope"]=={k:v for k,v in row.items() if k!="filename"}
        assert row["emitted_perf_counter"]<=accepted["accepted_perf_counter"]<=case["completed_perf_counter"]
    for name in ("pretrain-parent-done.json","pretrain-continue.json","before-loop.json","after-loop.json","postloop-ready.json","worker-completed.json","worker-failure.json"):
        assert not (directory/name).exists(),name
    assert case["stages"]["pretrain"]["provider_guard"]["diagnostic_events"]==case["stages"]["postimport"]["provider_guard"]["diagnostic_events"]
    retained_map,checks=replay_partial_roles(case,freeze,case["started_perf_counter"],case["completed_perf_counter"])
    assert all(c["passed"] for c in checks),[c for c in checks if not c["passed"]]
    retained=set(retained_map.items())
    exits=case["cleanup"]["exit_codes"]
    assert len(exits)==len(retained)==5 and {(p["pid"],p["creation_filetime"]) for p in exits}==retained
    assert case["cleanup"]["all_retained_handles_exited"] is True and case["cleanup"]["job_active_count"]==0
    assert all(p["exit_code"]==0xE003 for p in exits if p["pid"] in (case["launcher"]["pid"],wid["pid"]))
    return True


def audit_progress(case,directory,freeze):
    steps=("site-start","site-complete","torch-start","torch-complete",
        "transformers-start","transformers-complete","versions-verified")
    paths=sorted(directory.glob("import-progress-*.json"))
    assert len(paths)==len(steps)==7 and not list(directory.glob("import-progress-*.pending"))
    rows=[];previous=case["stages"]["preimport"]["stage_ready_perf_counter"]
    upper=case["stages"]["postimport"]["import_completed_perf_counter"]
    wid=case["worker_identity"]["self_receipt"]
    empty=dict(case["stages"]["preimport"]["provider_guard"]);empty["phase"]="import"
    final_events=case["stages"]["postimport"]["provider_guard"]["diagnostic_events"]
    previous_count=0
    for i,path in enumerate(paths):
        assert path.name==f"import-progress-{i:02d}.json" and path.stat().st_size<=8192
        row=json.loads(path.read_bytes());rows.append(row)
        assert set(row)=={"nonce","role","pid","creation_filetime","seq","step","emitted_perf_counter","provider_guard"}
        assert row["seq"]==i and type(row["seq"])is int and row["step"]==steps[i]
        assert row["pid"]==wid["pid"] and row["creation_filetime"]==wid["creation_filetime"]
        assert row["nonce"]==case["nonce"] and row["role"]=="worker"
        stamp=row["emitted_perf_counter"]
        assert finite(stamp) and previous<=stamp<=upper;previous=stamp
        guard=row["provider_guard"];count=guard["allowed_local_probe_count"]
        assert type(count)is int and previous_count<=count<=1;previous_count=count
        if count==0:
            assert guard==empty
            assert all(e["perf_counter"]>stamp for e in final_events)
        else:
            checks=legacy.replay_provider(guard,freeze,"import",1,case["started_perf_counter"],stamp)
            assert all(c["passed"]for c in checks),[c for c in checks if not c["passed"]]
        assert guard["diagnostic_events"]==final_events[:count]
    assert previous_count==1 and case["import_progress"]==rows and not case.get("import_progress_error")
    return {"rows":len(rows),"bytes":sum(p.stat().st_size for p in paths),
        "scope":"actual interpreter import markers only; not native stack attribution or measured import speedup"}


def audit_files(output,protocol_path,freeze_path,root=ROOT):
    report=json.loads((output/"report.json").read_bytes());protocol=json.loads(protocol_path.read_bytes());freeze=json.loads(freeze_path.read_bytes())
    assert report["passed"] is True and report["id"]==protocol["id"]=="actual-pretrained-training-ledger-v2"
    assert report["protocol_sha256"]==freeze["protocol_sha256"]==sha(protocol_path.read_bytes())
    assert report["freeze_sha256"]==sha(freeze_path.read_bytes())
    assert freeze["source_sha256"]=={p:sha((root/p).read_bytes()) for p in freeze["source_sha256"]}
    assert protocol["limits"]==LIMITS and protocol["training_config"]==CONFIG
    assert protocol["sampled_private_byte_stop"]==1073741824
    assert protocol["cases"]==[c["id"] for c in report["cases"]]==["healthy","partial_pretrain"]
    started,completed=stamp(report["started_at"]),stamp(report["completed_at"])
    assert stamp(protocol["predeclared_at"])<=stamp(freeze["frozen_at"])<=started<=completed
    start,end=report["started_perf_counter"],report["completed_perf_counter"]
    assert end-start<=240
    h,f=report["cases"]
    assert h["completed_perf_counter"]<=f["started_perf_counter"]
    checks=healthy(h,freeze,{p.name:json.loads(p.read_bytes()) for p in (output/"healthy").glob("*.json")},start,end,started,completed)
    assert all(c["passed"] for c in checks),[c for c in checks if not c["passed"]]
    assert fault_checks(f,h,output/"partial_pretrain",freeze)
    progress_summaries={c["id"]:audit_progress(c,output/c["id"],freeze) for c in (h,f)}
    summaries={c["id"]:ledger_checks(c,(output/c["id"]/"trace.jsonl").read_bytes()) for c in (h,f)}
    return {"passed":True,"healthy_saved_checks":len(checks),"ledger":summaries,"import_progress":progress_summaries,
        "model_loads":2,"optimizer_updates":16,"scientific_experiments":1,
        "boundary":"one healthy CPU trajectory and a stopped pretrain fault; no matched cost/quality/GPU/production evidence"}


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("output","protocol","freeze"):p.add_argument("--"+name,type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(audit_files(a.output,a.protocol,a.freeze),indent=2))
