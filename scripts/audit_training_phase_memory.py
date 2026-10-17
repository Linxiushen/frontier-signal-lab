"""Independent stdlib saved-receipt replay for stage-labelled current memory.

No producer, ML, OS measurement, network or workload execution.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re


ROOT=Path(__file__).resolve().parents[1]

NATIVE_ARGUMENTS=['/d','/q','/c','set /p workload_observer_gate=']

EXECUTABLE_ROLES={'launcher','base_python','native','conhost'}

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

class Replay:
    """Independent raw-evidence checker; it does not call the producer policy."""

    def __init__(self):
        self.checks = []

    def check(self, condition, name):
        self.checks.append({"check": name, "passed": bool(condition)})
        return bool(condition)

    def identity(self, row, name):
        pair = row["pid"], row["creation_filetime"]
        self.check(all(type(value) is int and value > 0 for value in pair), name + ":PID_creation")
        return pair

    def span(self, row, lower, upper, maximum, name):
        start, end = row["started_perf_counter"], row["completed_perf_counter"]
        self.check(all(finite(value) for value in (start, end)) and
                   lower <= start <= end <= upper and end - start <= maximum,
                   name + ":bounded_clock_span")
        wall = row["wall_seconds"]
        self.check(finite(wall) and finite(start) and finite(end) and
                   math.isclose(wall, end - start, rel_tol=1e-10, abs_tol=1e-8),
                   name + ":wall_recomputed")
        return start, end

    @staticmethod
    def stamp(value):
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone missing")
        return result

    def message(self, row, nonce, role, pid, name):
        self.check(row.get("nonce") == nonce and row.get("role") == role and
                   type(row.get("pid")) is int and row["pid"] == pid,
                   name + ":nonce_role_PID")

    def image(self, node, role, executables, paths, name):
        value = node["image"]
        basename = value["basename"]
        matches = value["exact_path_matches"]
        self.check(isinstance(basename, str) and bool(basename) and
                   "/" not in basename and "\\" not in basename and
                   fingerprint(value["sha256"]) and fingerprint(value["normalized_path_sha256"]) and
                   value["queried_from_retained_handle"] is True and
                   value["retained_identity_stable"] is True,
                   name + ":retained_OS_image_complete")
        self.check(isinstance(matches, list) and matches == sorted(set(matches)) and
                   set(matches) <= EXECUTABLE_ROLES and
                   value["path_classification"] in ("exact_executable", "system32", "other") and
                   (value["path_classification"] == "exact_executable") == bool(matches),
                   name + ":path_classification")
        for match in matches:
            self.check(value["sha256"] == executables[match] and
                       value["normalized_path_sha256"] == paths[match],
                       name + ":declared_exact_path_matches_freeze")
        if role is not None:
            expected_basename = "cmd.exe" if role == "native" else "conhost.exe" if role == "conhost" else "python.exe"
            self.check(role in matches and value["sha256"] == executables[role] and
                       value["normalized_path_sha256"] == paths[role] and basename.lower() == expected_basename,
                       name + ":independent_exact_image_role")
        return value

def replay_roles(case, freeze, lower, upper):
    """Reconstruct the exact primary/console policy from raw retained rows."""
    replay = Replay()
    check = replay.check
    executables, paths = freeze['executables_sha256'], freeze['executable_path_sha256']
    launcher = replay.identity(case['launcher'], 'role:launcher')
    worker = replay.identity(case['worker_identity']['self_receipt'], 'role:worker')
    native = replay.identity(case['native_descendant']['os_identity'], 'role:native')
    labels = ['before_native', *STAGES]
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
            check(case['memory_brackets'][label]['parent']['query_completed_perf_counter'] <= start and
                  decision_end <= case['memory_brackets'][label]['self_after']['query_started_perf_counter'],
                  tag + ':role_census_inside_memory_bracket')
    return retained, replay.checks

PROVIDER_EVENTS = ['socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                   'socket.gethostbyname_ex', 'socket.gethostbyaddr', 'socket.sendto', 'socket.bind']

PROVIDER_SOURCE_SHA256 = '2633bbdb69731e5ccb5cf4e4afd65605d86c7979cc5633126f50c92d5ad74a74'

PROVIDER_RELATIVE_PATH = 'urllib3/util/connection.py'

PROVIDER_POLICY_ID = 'urllib3-ipv6-loopback-capability-probe-v1'

PROVIDER_CONFIG = {'version_label':'2.8.0','family_code':23,'type_code':1,'protocol':0,
    'maximum_allowed_probes_per_ML_worker':1,'maximum_diagnostic_events':4,
    'maximum_saved_frames':8,'maximum_scanned_frames':9,'maximum_source_file_bytes':1048576,
    'caller_function':'_has_ipv6','caller_line':127,'module_function':'<module>','module_line':137}

def replay_provider(value, freeze, phase, budget, lower, upper, import_interval=None):
    """Independently replay saved exact allowance; no provider code is imported."""
    replay=Replay();check=replay.check
    expected_count=0 if phase in ('preimport','injected_import') else 1
    expected_fields={'installed','python_audit_only','native_network_sandbox','external_providers_permitted',
        'synthetic_probe_denials','unexpected_denied_events','denied_audit_events','policy_id','phase',
        'provider_source','allowed_local_probe_budget','allowed_local_probe_count','diagnostic_event_limit',
        'diagnostic_overflow_count','observed_event_count','diagnostic_events'}
    check(set(value)==expected_fields and value['installed'] is True and value['python_audit_only'] is True and
        value['native_network_sandbox'] is False and value['external_providers_permitted'] is False and
        value['policy_id']==PROVIDER_POLICY_ID and value['phase']==phase and
        value['denied_audit_events']==PROVIDER_EVENTS and value['unexpected_denied_events']==[],
        'provider:closed_policy_and_Python_only_boundary')
    integers={'synthetic_probe_denials':1,'allowed_local_probe_budget':budget,'allowed_local_probe_count':expected_count,
        'diagnostic_event_limit':4,'diagnostic_overflow_count':0,'observed_event_count':expected_count}
    check(all(type(value[k]) is int and value[k]==v for k,v in integers.items()),
        'provider:exact_one_synthetic_probe_and_bounded_real_event_counters')
    source=value['provider_source'];path_hash=freeze['provider_source_path_sha256']
    check(source=={'package_relative_path':PROVIDER_RELATIVE_PATH,'sha256':PROVIDER_SOURCE_SHA256,
        'normalized_path_sha256':path_hash} and fingerprint(path_hash) and
        freeze['provider_source_sha256']==PROVIDER_SOURCE_SHA256,'provider:exact_frozen_file_and_opaque_path')
    events=value['diagnostic_events']
    check(isinstance(events,list) and len(events)==expected_count and expected_count<=budget,
        'provider:no_unrecorded_dropped_or_extra_real_events')
    for index,event in enumerate(events):
        check(set(event)=={'event_index','event','perf_counter','phase','decision','socket_family_code',
            'socket_type_code','socket_protocol','endpoint','frames','frame_scope','frame_boundary',
            'frames_scanned_count','saved_frame_count','frames_truncated','source_hashes_complete','diagnostic_errors'},
            'provider:event_whitelisted_safe_fields')
        check(type(event['event_index']) is int and event['event_index']==index and event['event']=='socket.bind' and
            event['phase']=='import' and event['decision']=='allowed_local_capability_probe' and
            all(type(event[k]) is int and event[k]==v for k,v in
                [('socket_family_code',23),('socket_type_code',1),('socket_protocol',0)]),
            'provider:one_exact_import_phase_IPv6_stream_bind')
        endpoint={'shape':'tuple2','host_kind':'exact_ipv6_loopback','port_kind':'ephemeral_zero','address_logged':False}
        check(canonical(event['endpoint'])==canonical(endpoint),'provider:exact_loopback_ephemeral_argument_classification')
        check(event['frame_scope']=='contiguous_initial_urllib3_frames' and
            event['frame_boundary']=='outside_selected_package' and type(event['frames_scanned_count']) is int and
            event['frames_scanned_count']==3 and type(event['saved_frame_count']) is int and event['saved_frame_count']==2 and
            event['frames_truncated'] is False and event['source_hashes_complete'] is True and event['diagnostic_errors']==[],
            'provider:complete_two_frame_prefix_with_explicit_boundary_no_truncation')
        frames=[{'package_relative_path':PROVIDER_RELATIVE_PATH,'function':function,'line':line,
            'sha256':PROVIDER_SOURCE_SHA256,'normalized_path_sha256':path_hash}
            for function,line in [('_has_ipv6',127),('<module>',137)]]
        check(canonical(event['frames'])==canonical(frames),'provider:exact_pinned_caller_function_line_and_module_invocation')
        check(finite(event['perf_counter']) and lower<=event['perf_counter']<=upper,
            'provider:real_bind_event_inside_case_and_before_snapshot')
        if import_interval is not None:
            check(import_interval[0]<=event['perf_counter']<=import_interval[1],
                'provider:real_bind_event_inside_actual_ML_import_interval')
    return replay.checks

def bounded(path,maximum_bytes=1048576):
    with Path(path).open('rb') as stream:raw=stream.read(maximum_bytes+1)
    if not 0<len(raw)<=maximum_bytes:raise ValueError('empty JSON or saved receipt exceeds byte bound')
    def reject(v):raise ValueError('nonfinite JSON number:'+v)
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('duplicate JSON key:'+key)
            result[key]=value
        return result
    return raw,json.loads(raw,parse_constant=reject,object_pairs_hook=pairs)

def provider_file_hash(path):
    with Path(path).open('rb') as stream:raw=stream.read(PROVIDER_CONFIG['maximum_source_file_bytes']+1)
    if not 0<len(raw)<=PROVIDER_CONFIG['maximum_source_file_bytes']:
        raise ValueError('empty provider source or source exceeds fixed byte bound')
    return sha(raw)

def reading(replay,row,identity,lower,upper,name,cpu=False):
    check=replay.check
    check(replay.identity(row,name)==identity,name+':actual_retained_worker_identity')
    check(finite(row['perf_counter']) and lower<=row['perf_counter']<=upper,name+':bounded_sample_clock')
    memory=row['memory']
    check(all(integer(memory[key]) for key in ('resident_bytes','private_bytes','peak_resident_bytes')) and
        memory['peak_resident_bytes']>=memory['resident_bytes'],name+':current_memory_and_lifetime_resident_peak')
    if cpu:check(finite(row['native_cpu_seconds']) and row['native_cpu_seconds']>=0,name+':nonnegative_native_CPU')

def close(replay,left,right,name):
    return replay.check(finite(left) and finite(right) and math.isclose(left,right,rel_tol=1e-10,abs_tol=1e-8),name)


EXPERIMENT='windows-pinned-pythia-phase-current-memory-v1'
PROTOCOL_SHA256='dc935322fcddc13380b0a9aee88a60d3ef2826051cd18d8145196b98ecaa4c85'
SOURCE_HASHES={'experiments/training_phase_memory.py': '616fb694a36a1205f425f3e2db118e4ff4139a6d948a2e9e4c5e000c54ed0d3a', 'tests/test_training_phase_memory.py': 'c8731f92939765815c1106368e04601e9060f5b5017b0fc2adebe837a9a6ee19'}
DEPENDENCY_HASHES={'experiments/activation_cost_probe.py': '0f3f0062269ad2b2531e9a6ef2f94dbc65b5af46a89bad75ec9d7be5f1d661ce', 'scripts/capture_real_activation.py': '32ac2555ce2f2593efc5f08188ba7b7703c33efb510fa78d680ace22fdab1b87', 'experiments/process_observer.py': '3f247512aee1e50940d57e81a0290d658bad56cae098d45b2f92bb69deece175', 'experiments/process_observer_probe.py': 'cfbc7de447cdf7b1dbae98e34c9e642c7d7cc8d93343c961f6aec8f78ea31740', 'experiments/workload_observer_probe.py': 'cdb14b85a40f866676e3181eca513041d6c6fa5bc679429654b4b72b9e63eba3', 'fixtures/process-observer/protocol.json': 'e4b77a96ab8aa1a2857b3156f485226791c877b923f847798eaad97e1f4b58a0', 'fixtures/process-observer/implementation.json': '535c3e78a9abf53fd89452876796c1df8c39a5a8d2b21963f173f148fc03e954', 'fixtures/workload-observer/protocol.json': '659146a5f05ed88b23886fefc3a389268883b88c5ad8b3a869712c1d27dbb463', 'fixtures/workload-observer/implementation.json': 'db207618c0f5226dc5f2e509fdbf99cb32ae9d24af4066f1bd3a23fba47e293c', 'fixtures/activation-cost/train.json': '8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681', 'fixtures/activation-cost/manifest.json': '0d08ba2574148924da713a40a66e49f3a7adc4d280a6d8f2e0d5135aae5148eb', 'fixtures/activation-cost/protocol.json': '8908ca5362a51a1b0e2a9d27657b0b8e64ac5632fc695b30407331be5c1c87ed', 'fixtures/activation-cost/implementation.json': 'e28fe5df090bcc86dae9e0151e3765f130d40a28499df5b0714be32f4b826de5', 'experiments/training_observer_probe.py': '39fca84fc9c2eef2abf7f967f70b7d5752faccddf6f5456c9965ed3f9a06d728', 'experiments/role_policy_probe.py': '5481a1720ad00cd7cf83d7a86938fd09916b001d8b0187ae8307d536bf4d027a', 'experiments/dual_identity_census.py': '031c5c67ba84afe9b5af8ab69ac7b0cb31e418efe3e32781b96ec76fcd9e0a91', 'fixtures/role-policy-probe/protocol.json': '9248f0fa142c78b980d6e52ecce84d97c520aff52e910b2a00f0ad975b75a84a', 'fixtures/role-policy-probe/implementation.json': 'c0fc12d9209933f0304bba2d84ba127aa32e26d852788ddd830e11dd59f228ca', 'experiments/training_observer_v2.py': '8355af96bebca468b458401b3a70fd5de75e15ec4ac640c4678e0f48e72fc30b', 'fixtures/training-observer-v2/protocol.json': 'd381c42ac6f21fc33ac27a4fdc9980b1cd7beeee32f82f7295c58afa742cfd23', 'fixtures/training-observer-v2/implementation.json': 'a07656ffb21da55e750300b88e69ceead85b914dbef48855072a3fe1af5722ec', 'experiments/training_observer_v3.py': '74d470e41ce5268c6cc761b7cd004e0e7d8b264095b045e8207912710662d6d5', 'fixtures/training-observer-v3/protocol.json': 'b248a981ffe9db8aea50f4a0c85d057e968620df372c74acb0835e2b046e3552', 'fixtures/training-observer-v3/implementation.json': '3e72671b15a04e0ec99b6968e721d0f74f70bff51a30d7052ecb24cc229e1c21', 'experiments/observer_duty_probe.py': '37b6e82dcfd0e09a90e1837be05d05d50e7aef19a7fe06f323a46053d1aee80c', 'tests/test_observer_duty_probe.py': '46c12f50f519bf9793c3d61496fc171d887ba3d458778ba53269c5b88ed969e6', 'fixtures/observer-duty/protocol.json': '759d841360550416d9f000a82d6449dffb577a37c8e6e42c5875741c3e4601cd', 'fixtures/observer-duty/implementation.json': '7f054ebaba39db23180e792535fcbd8e8a7a65c197e3f8bff4c31e7ea75a07a6', 'scripts/audit_observer_duty.py': 'c4ee4fa690db672c72e4837d14f16dd48422ae0bdc9f7f404907ef39f5726252', 'tests/test_observer_duty_auditor.py': '66b451dbd151792f0bcb4af51e6855b7845670563abec8bcc4c3a30700bfce89', 'experiments/observer_duty_v2.py': '633fe591ebe5438a70faa672ae6365e480e2cc0e10eecedf6695a5128cea8d74', 'tests/test_observer_duty_v2.py': '8a9545baac306b8ae512c339b20ad0035ad9077090ec0746f4cf1fc91f3cd844', 'fixtures/observer-duty-v2/protocol.json': 'b5c845cd2df375f063aa245f48b2dc5d13dea7e1c11e9f233cd5dc3f5e38652d', 'fixtures/observer-duty-v2/implementation.json': '9c870a8cdfda231bb6b6f0bee780de26ac47c4d7ebb50c2d8b223c3758bf33c2', 'scripts/audit_observer_duty_v2.py': '932262a7f65386d2570b1d6639e8d28c03267aca7c21e373ac92ca9a7bce8819', 'tests/test_observer_duty_v2_auditor.py': '08f5409b4ddf0ceb93c515f81720893bf2457e3f516a5b63f1990eb108db2459', 'experiments/observer_query_treatment.py': '155a4d8a04ab434b273b7d7413c6dce6bf04c10f7e32b7c68426fb2a22804b75', 'tests/test_observer_query_treatment.py': '906c53d9c930c4ff9866ca9aafdea2d6908fc0b957ef5bebda074ef6898480f3', 'fixtures/observer-query-treatment/protocol.json': '370bc2918f4954e8afdfdcb9ec630e4252cd16717254dce084a87a3ec4a5672d', 'fixtures/observer-query-treatment/implementation.json': '0a72def74988fa2a9d0fb3fed72aeaa1209cf1f47822cf638b9f033039d82a38', 'scripts/audit_observer_query_treatment.py': '50cb0c9ecfe9bbe3d5262780c615e60c91f7fce8d977226f94a68a015e1166bc', 'tests/test_observer_query_treatment_auditor.py': '14d4da43baf0b118190eece433adadaad8ec364b64d34fbf40e12c5fbe085a15'}
SOURCE_PATHS=('experiments/training_phase_memory.py','tests/test_training_phase_memory.py')
REVIEW_PATHS=('scripts/audit_training_phase_memory.py','tests/test_training_phase_memory_auditor.py')
OPERATORS=('zero_grad','forward_loss','backward','optimizer_step')
OP_IDS=tuple('step'+str(step)+'_'+kind for step in (1,2) for kind in OPERATORS)
STAGES=('preimport','postimport','pretrain',*OP_IDS,'postvalidation')
BOUNDARIES=dict(zip(('pretrain',*OP_IDS),('B'+str(i) for i in range(9))))
PHASES={s:('preimport' if s=='preimport' else 'postimport' if s=='postimport' else 'postload' if s=='pretrain' else 'complete' if s=='postvalidation' else 'train') for s in STAGES}
CATEGORIES=('trainable_parameters','model_buffers','non_none_parameter_gradients','optimizer_exp_avg','optimizer_exp_avg_sq','optimizer_step_scalar','live_loss_tensor')
PARAM_NUMEL=14067712
PARAM_BYTES=PARAM_NUMEL*4
INVENTORY_METHOD='primitive metadata, snapshot-local backing union; activation saves/temporary buffers/input and batch backing/Python/native arenas excluded; not process current or peak'
CONTROL_PURPOSE = "pinned two-update stage-labelled current memory v1"
CONTROL_PLAN=[('create-native.json','create-native','before_native',0)]
for _index,_stage in enumerate(STAGES,1):
    CONTROL_PLAN.extend([(_stage+'-parent-done.json','parent-sampled',_stage,_index),(_stage+'-continue.json','continue',_stage,_index)])
CONTROL_PLAN.append(('finish.json','finish','postvalidation',12))
CONFIG = {"seed":503,"optimizer_steps":2,"intraop_threads":1,"interop_threads":1,"train_blocks":128,"batch_size":2,"sequence_input_tokens":64,
    "sampler_interval_seconds":0.02,"maximum_recorded_sample_gap_seconds":0.5,"maximum_active_observations":800,"maximum_active_polls":800,
    "case_timeout_seconds":60.0,"total_timeout_seconds":60.0,"cleanup_timeout_seconds":4.0,"import_timeout_seconds":20.0,"load_timeout_seconds":25.0,
    "training_timeout_seconds":15.0,"barrier_timeout_seconds":5.0,"memory_bracket_tolerance_bytes":4194304}
DEPENDENCY_PATHS=('experiments/activation_cost_probe.py', 'scripts/capture_real_activation.py', 'experiments/process_observer.py', 'experiments/process_observer_probe.py', 'experiments/workload_observer_probe.py', 'fixtures/process-observer/protocol.json', 'fixtures/process-observer/implementation.json', 'fixtures/workload-observer/protocol.json', 'fixtures/workload-observer/implementation.json', 'fixtures/activation-cost/train.json', 'fixtures/activation-cost/manifest.json', 'fixtures/activation-cost/protocol.json', 'fixtures/activation-cost/implementation.json', 'experiments/training_observer_probe.py', 'experiments/role_policy_probe.py', 'experiments/dual_identity_census.py', 'fixtures/role-policy-probe/protocol.json', 'fixtures/role-policy-probe/implementation.json', 'experiments/training_observer_v2.py', 'fixtures/training-observer-v2/protocol.json', 'fixtures/training-observer-v2/implementation.json', 'experiments/training_observer_v3.py', 'fixtures/training-observer-v3/protocol.json', 'fixtures/training-observer-v3/implementation.json', 'experiments/observer_duty_probe.py', 'tests/test_observer_duty_probe.py', 'fixtures/observer-duty/protocol.json', 'fixtures/observer-duty/implementation.json', 'scripts/audit_observer_duty.py', 'tests/test_observer_duty_auditor.py', 'experiments/observer_duty_v2.py', 'tests/test_observer_duty_v2.py', 'fixtures/observer-duty-v2/protocol.json', 'fixtures/observer-duty-v2/implementation.json', 'scripts/audit_observer_duty_v2.py', 'tests/test_observer_duty_v2_auditor.py', 'experiments/observer_query_treatment.py', 'tests/test_observer_query_treatment.py', 'fixtures/observer-query-treatment/protocol.json', 'fixtures/observer-query-treatment/implementation.json', 'scripts/audit_observer_query_treatment.py', 'tests/test_observer_query_treatment_auditor.py')
HISTORICAL_FILE_SHA256={
    'results/observer-duty/report.json':'1b838a380db6ef6cef8b025c678d68d4d6e124b05e1f2229dc04711cc535de3a',
    'results/observer-duty-v2/report.json':'1d6d27ea419e36df6de92407ee2682dbfec7e0e817e6249af6119ae7fe35be37',
    'results/observer-query-treatment/report.json':'f8dfa485ee8151419a37e8c3cde9c003dad083a87b4e5b91cf71532465cdcce5',
}


def schedule():
    order=list(range(128));random.Random(503).shuffle(order)
    return [order[:2],order[2:4]]


def add_checks(replay, values, prefix=''):
    replay.checks.extend({'check':prefix+c['check'],'passed':c['passed']} for c in values)


def query_reading(replay,wrapper,identity,lower,upper,name,self_nonce=None):
    q0,q1=wrapper['query_started_perf_counter'],wrapper['query_completed_perf_counter']
    replay.check(all(finite(t) for t in (q0,q1)) and lower<=q0<=q1<=upper,name+':complete_query_interval')
    sample=wrapper['sample']
    reading(replay,sample,identity,q0,q1,name+':sample',self_nonce is None)
    if self_nonce is not None:
        replay.message(wrapper,self_nonce,'worker',identity[0],name+':wrapper')
        replay.check(wrapper.get('creation_filetime')==identity[1],name+':wrapper_creation_identity')
    return q0,q1,sample


def replay_held(case,identity,lower,upper):
    r=Replay();check=r.check
    check(list(case['stages'])==list(STAGES) and list(case['memory_brackets'])==list(STAGES),'held:exact_twelve_stage_brackets')
    previous=lower
    for label in STAGES:
        tag='held:'+label;stage=case['stages'][label];br=case['memory_brackets'][label]
        r.message(stage,case['nonce'],'worker',identity[0],tag+':ready')
        ready=stage['stage_ready_perf_counter']
        check(type(stage['creation_filetime']) is int and stage['creation_filetime']==identity[1] and stage['stage']==label and finite(ready) and previous<=ready<=upper and integer(stage['native_thread_count'],1),tag+':ready_before_queries')
        check(set(br)=={'self_before','parent','self_after','comparison','full_interval_ordered'} and set(br['parent'])=={'query_started_perf_counter','query_completed_perf_counter','sample'} and all(set(br[k])=={'nonce','role','pid','creation_filetime','query_started_perf_counter','query_completed_perf_counter','sample'} for k in ('self_before','self_after')),tag+':exact_query_wrapper_schema')
        a,b,self_before=query_reading(r,br['self_before'],identity,ready,upper,tag+':before',case['nonce'])
        c,d,parent=query_reading(r,br['parent'],identity,ready,upper,tag+':parent')
        e,f,self_after=query_reading(r,br['self_after'],identity,ready,upper,tag+':after',case['nonce'])
        ordered=a<=b<=c<=d<=e<=f
        check(ordered and br['full_interval_ordered'] is True and f-a<=5,tag+':full_query_order_not_point_timestamp')
        expected={'same_identity':True,'ordered_monotonic_bracket':self_before['perf_counter']<=parent['perf_counter']<=self_after['perf_counter']}
        for metric in ('resident','private'):
            vals=[s['memory'][metric+'_bytes'] for s in (self_before,parent,self_after)]
            expected[metric+'_within_tolerance']=min(vals[0],vals[2])-4194304<=vals[1]<=max(vals[0],vals[2])+4194304
        expected['passed']=all(expected.values())
        check(expected['passed'] and br['comparison']==expected,tag+':independent_current_values_and_tolerance')
        check(parent in case['samples'],tag+':parent_sample_retained')
        previous=f
    return r.checks


def replay_phase_samples(case,identity,lower,upper):
    r=Replay();check=r.check
    operations=case['operation_receipts'];windows=case['active_windows'];summaries=case['phase_measurements']
    check([p['id'] for p in operations]==list(OP_IDS) and list(windows)==list(OP_IDS) and [s['id'] for s in summaries]==list(OP_IDS),'active:exact_eight_phase_inventory')
    all_coverage=[]
    prior_window=lower;prior_native_cpu=0
    for i,(op,stats) in enumerate(zip(operations,summaries)):
        tag='active:'+OP_IDS[i];window=windows[OP_IDS[i]]
        wide0,wide1=r.span(window,prior_window,upper,60,tag+':wider_parent_window');prior_window=wide1
        a,b=op['operator_started_perf_counter'],op['operator_completed_perf_counter']
        release=case['controller_controls'][6+2*i]
        check(wide0<=release['emitted_perf_counter']<=case['worker_controls'][6+2*i]['accepted_perf_counter']<=a<=b<=wide1,tag+':wider_window_covers_release_and_exact_operator')
        cpu0,cpu1,delta=[window[k] for k in ('parent_native_cpu_start_seconds','parent_native_cpu_end_seconds','parent_native_cpu_delta_seconds')]
        check(all(finite(v) for v in (cpu0,cpu1,delta)) and 0<=cpu0<=cpu1 and delta>=0,tag+':wider_parent_CPU_not_exact_operation')
        close(r,delta,cpu1-cpu0,tag+':wider_CPU_recomputed')
        observations=window['observations']
        check(isinstance(observations,list) and len(observations)<=800 and integer(window['poll_count']) and len(observations)==window['poll_count'],tag+':bounded_every_poll_retained')
        previous=wide0;selected=[]
        for j,row in enumerate(observations):
            check(set(row)=={'index','query_started_perf_counter','query_completed_perf_counter','sample','snapshot_started_perf_counter','snapshot_completed_perf_counter','snapshot_process_count'} and type(row['index']) is int and row['index']==j,tag+':query_exact_schema_and_index')
            q0,q1,sample=query_reading(r,row,identity,previous,wide1,tag+':query')
            check(all(row[k] is None for k in ('snapshot_started_perf_counter','snapshot_completed_perf_counter','snapshot_process_count')),tag+':Toolhelp_unperformed_null_not_zero')
            check(sample['native_cpu_seconds']>=prior_native_cpu,tag+':native_worker_CPU_monotonic')
            prior_native_cpu=sample['native_cpu_seconds'];previous=q1
            if a<=q0<=q1<=b:selected.append(row)
        stamps=[v['sample']['perf_counter'] for v in selected]
        count=len(selected);duration=b-a
        gap=max(y-x for x,y in zip([a]+stamps,stamps+[b]))
        wall=math.fsum(v['query_completed_perf_counter']-v['query_started_perf_counter'] for v in selected)
        coverage=count>0 and gap<=0.5
        all_coverage.append(coverage)
        status='unobserved' if not count else 'finite_sampled_lower_bound' if coverage else 'inadequate_gap'
        check(type(stats['raw_count']) is int and stats['raw_count']==len(observations) and type(stats['selected_count']) is int and stats['selected_count']==count,tag+':counts_recomputed_full_interval_selection')
        close(r,stats['maximum_gap_including_boundaries_seconds'],gap,tag+':endpoint_inclusive_gap_recomputed')
        close(r,stats['query_wall_seconds'],wall,tag+':selected_query_wall_recomputed_not_CPU')
        check(stats['coverage_status']==status and stats['coverage_gate_passed'] is coverage and stats['missed_peak_bytes_upper_bound'] is None,tag+':honest_coverage_no_byte_upper_bound')
        check(set(stats)=={'id','raw_count','selected_count','selected_indices','excluded_count','maximum_gap_including_boundaries_seconds','realized_samples_per_second','query_wall_seconds','query_wall_fraction','sampled_current_resident_max_bytes','sampled_current_private_max_bytes','coverage_status','coverage_gate_passed','missed_peak_bytes_upper_bound'},tag+':exact_phase_summary_schema')
        check(stats['selected_indices']==[v['index'] for v in selected] and all(type(v) is int for v in stats['selected_indices']),tag+':exact_selected_indices')
        check(type(stats['excluded_count']) is int and stats['excluded_count']==len(observations)-count,tag+':exact_excluded_count')
        for key,metric in [('sampled_current_resident_max_bytes','resident_bytes'),('sampled_current_private_max_bytes','private_bytes')]:
            expected=max(v['sample']['memory'][metric] for v in selected) if selected else None
            check(stats[key] is None if expected is None else type(stats[key]) is int and stats[key]==expected,tag+':'+key+'_current_lower_bound_or_null')
        if count:
            check(duration>0,tag+':positive_sampled_operation_duration')
            close(r,stats['realized_samples_per_second'],count/duration,tag+':realized_Hz')
            close(r,stats['query_wall_fraction'],wall/duration,tag+':wall_fraction_not_total_observer_cost')
        else:
            check(stats['realized_samples_per_second'] is None and stats['query_wall_fraction'] is None,tag+':unsampled_rates_and_fraction_null')
    check(case['all_phases_have_finite_sampled_coverage'] is all(all_coverage),'active:all_phase_coverage_separate_from_engineering_acceptance')
    return r.checks


def raw_payloads(case):
    result={'worker-ready.json':case['worker_identity']['self_receipt'],'native-ready.json':case['native_descendant']['launch_receipt']}
    for label,value in case.get('stages',{}).items():
        result[label+'-ready.json']=value
        bracket=case['memory_brackets'][label]
        result[label+'-before.json']=bracket['self_before']
        result[label+'-after.json']=bracket['self_after']
        if label in BOUNDARIES:result[label+'-inventory.json']=case['inventories'][BOUNDARIES[label]]
    for field,suffix in [('operation_receipts','-operation.json'),('housekeeping_receipts','-housekeeping.json')]:
        for row in case.get(field,[]):result[row['id']+suffix]=row
    result['worker-completed.json']=case['healthy_completion']
    for sent,ack in zip(case['controller_controls'],case['worker_controls']):
        result[sent['filename']]={k:v for k,v in sent.items() if k!='filename'}
        result[sent['filename'].replace('.json','-accepted.json')]=ack
    if 'worker_failure_receipt' in case:result['worker-failure.json']=case['worker_failure_receipt']
    return result


def replay_inventory(case,identity,lower,upper):
    r=Replay();check=r.check
    inventories=case['inventories']
    check(list(inventories)==['B'+str(i) for i in range(9)],'inventory:exact_nine_ordered_snapshots')
    base_parameters=None;base_buffers=None;moment_metadata=None
    for i,(stage,bid) in enumerate(BOUNDARIES.items()):
        inv=inventories[bid];tag='inventory:'+bid
        expected_fields={'nonce','role','pid','creation_filetime','boundary_id','snapshot_started_perf_counter','snapshot_completed_perf_counter','wall_seconds','tensors','storage_groups','categories','all_categories_unique_backing_bytes','optimizer_state_entries','optimizer_step_values','live_loss_tensor','tensor_count','method'}
        check(set(inv)==expected_fields and inv['boundary_id']==bid and inv['method']==INVENTORY_METHOD,tag+':exact_primitive_schema_and_method')
        r.message(inv,case['nonce'],'worker',identity[0],tag)
        check(inv['creation_filetime']==identity[1],tag+':actual_creation_identity')
        a,b=inv['snapshot_started_perf_counter'],inv['snapshot_completed_perf_counter']
        after=case['memory_brackets'][stage]['self_after']['query_completed_perf_counter']
        sent=case['controller_controls'][2*(STAGES.index(stage)+1)]['emitted_perf_counter']
        check(all(finite(v) for v in (a,b)) and lower<=after<=a<=b<=sent<=upper,tag+':inventory_after_native_current_before_continue')
        close(r,inv['wall_seconds'],b-a,tag+':inventory_cost_recomputed')
        tensors=inv['tensors'];groups=inv['storage_groups'];categories=inv['categories']
        check(isinstance(tensors,list) and len(tensors)<=1024 and integer(inv['tensor_count']) and inv['tensor_count']==len(tensors),tag+':bounded_tensor_inventory')
        check(isinstance(groups,list) and len(groups)<=len(tensors) and set(categories)==set(CATEGORIES),tag+':exact_categories_and_bounded_groups')
        names=[t['name'] for t in tensors]
        check(len(set(names))==len(names),tag+':unique_category_qualified_tensor_names')
        by_storage={};by_category={c:[] for c in CATEGORIES}
        for t in tensors:
            name=t['name'];cat=t['category'];sid=t['storage_id']
            check(set(t)=={'name','category','shape','dtype','device','numel','element_size_bytes','logical_bytes','storage_offset_elements','storage_id','backing_nbytes','requires_grad','is_leaf'},tag+':tensor_exact_fields')
            check(isinstance(name,str) and 0<len(name)<=256 and '\x00' not in name and cat in CATEGORIES and t['device']=='cpu' and isinstance(t['dtype'],str) and len(t['dtype'])<=32,tag+':bounded_name_category_device_dtype')
            prefixes={'trainable_parameters':'parameters.','non_none_parameter_gradients':'gradients.','model_buffers':'buffers.','optimizer_exp_avg':'optimizer.','optimizer_exp_avg_sq':'optimizer.','optimizer_step_scalar':'optimizer.'}
            check(name=='loss' if cat=='live_loss_tensor' else name.startswith(prefixes[cat]) and len(name)>len(prefixes[cat]),tag+':category_qualified_name')
            if cat.startswith('optimizer_'):
                check(name.endswith('.'+{'optimizer_exp_avg':'exp_avg','optimizer_exp_avg_sq':'exp_avg_sq','optimizer_step_scalar':'step'}[cat]),tag+':optimizer_name_matches_field')
            shape=t['shape']
            check(isinstance(shape,list) and len(shape)<=8 and all(integer(v) for v in shape),tag+':bounded_shape')
            numel=math.prod(shape)
            check(integer(t['numel']) and t['numel']==numel and type(t['element_size_bytes']) is int and t['element_size_bytes'] in (1,2,4,8,16),tag+':numel_and_element_size')
            logical=numel*t['element_size_bytes']
            check(type(t['logical_bytes']) is int and t['logical_bytes']==logical and integer(t['storage_offset_elements']) and integer(t['backing_nbytes']) and t['storage_offset_elements']*t['element_size_bytes']<=t['backing_nbytes'],tag+':logical_bytes_and_storage_offset_not_physical_range')
            check(type(t['requires_grad']) is bool and type(t['is_leaf']) is bool and integer(sid),tag+':primitive_flags_and_local_storage_ID')
            if sid in by_storage:
                old=by_storage[sid][0]
                check(old['device']==t['device'] and old['backing_nbytes']==t['backing_nbytes'],tag+':alias_backing_capacity_agrees')
            by_storage.setdefault(sid,[]).append(t);by_category[cat].append(t)
        group_ids=[g['id'] for g in groups]
        check(all(type(v) is int for v in group_ids) and group_ids==list(range(len(groups))) and set(group_ids)==set(by_storage),tag+':groups_exact_local_storage_partition')
        for group in groups:
            check(set(group)=={'id','device','backing_nbytes','members'},tag+':group_exact_fields')
            members=by_storage[group['id']]
            check(group['device']=='cpu' and integer(group['backing_nbytes']) and group['backing_nbytes']==members[0]['backing_nbytes'] and group['members']==[t['name'] for t in members],tag+':group_members_and_capacity_recomputed')
        union=sum(rows[0]['backing_nbytes'] for rows in by_storage.values())
        check(type(inv['all_categories_unique_backing_bytes']) is int and inv['all_categories_unique_backing_bytes']==union,tag+':whole_snapshot_unique_backing_union_not_peak')
        for cat,rows in by_category.items():
            expected={'tensor_count':len(rows),'logical_bytes':sum(t['logical_bytes'] for t in rows),'unique_backing_bytes':sum(by_storage[s][0]['backing_nbytes'] for s in {t['storage_id'] for t in rows})}
            check(set(categories[cat])==set(expected) and all(type(v) is int for v in categories[cat].values()) and categories[cat]==expected,tag+':recomputed_category_'+cat)
        params=by_category['trainable_parameters'];grads=by_category['non_none_parameter_gradients'];m1=by_category['optimizer_exp_avg'];m2=by_category['optimizer_exp_avg_sq'];steps=by_category['optimizer_step_scalar'];buffers=by_category['model_buffers'];loss=by_category['live_loss_tensor']
        check(len(params)==76 and sum(t['numel'] for t in params)==PARAM_NUMEL and sum(t['logical_bytes'] for t in params)==PARAM_BYTES and all(t['dtype']=='torch.float32' and t['element_size_bytes']==4 and t['requires_grad'] is True and t['is_leaf'] is True for t in params),tag+':exact_pinned_trainable_parameters')
        check(len(buffers)<=256,tag+':bounded_buffers')
        # Names are explicitly prefixed by category; native handles/addresses are never serialized.
        def strip(t):
            name=t['name'];cat=t['category']
            if cat=='trainable_parameters':return name.removeprefix('parameters.')
            if cat=='non_none_parameter_gradients':return name.removeprefix('gradients.')
            if cat.startswith('optimizer_'):return name.removeprefix('optimizer.').rsplit('.',1)[0]
            return name.removeprefix('buffers.')
        meta=lambda rows:{strip(t):(t['shape'],t['dtype'],t['device'],t['numel'],t['element_size_bytes'],t['logical_bytes']) for t in rows}
        pm=meta(params)
        if base_parameters is None:base_parameters=pm;base_buffers=meta(buffers)
        else:
            check(pm==base_parameters,tag+':parameter_shape_logical_capacity_stable')
            check(meta(buffers)==base_buffers,tag+':buffer_metadata_stable')
        grad_live=i in (3,4,7,8);state_live=i>=4;loss_live=i in (2,3,6,7)
        check(len(grads)==(76 if grad_live else 0) and (not grad_live or meta(grads)==pm),tag+':gradient_lifecycle_shape_exact_not_RSS_delta')
        check(type(inv['optimizer_state_entries']) is int and inv['optimizer_state_entries']==(76 if state_live else 0),tag+':first_optimizer_creates_state_entries')
        check(len(m1)==len(m2)==len(steps)==(76 if state_live else 0),tag+':moment_and_scalar_tensor_counts')
        if state_live:
            check(meta(m1)==meta(m2)==pm and all(t['requires_grad'] is False and t['is_leaf'] is True for t in m1+m2),tag+':both_moments_match_parameter_metadata')
            check(all(t['shape']==[] and t['numel']==1 and t['dtype']=='torch.float32' and t['element_size_bytes']==4 and t['logical_bytes']==4 and not t['requires_grad'] for t in steps),tag+':declared_float32_scalar_step_layout')
            step=2 if i==8 else 1
            values=inv['optimizer_step_values']
            check(isinstance(values,list) and len(values)==76 and all(type(v) is int and v==step for v in values),tag+':native_step_counters_one_then_two')
            capacities=(categories['optimizer_exp_avg']['unique_backing_bytes'],categories['optimizer_exp_avg_sq']['unique_backing_bytes'],categories['optimizer_step_scalar']['unique_backing_bytes'])
            if moment_metadata is None:moment_metadata=capacities
            else:check(capacities==moment_metadata,tag+':second_update_reuses_declared_backing_capacity')
            # Dense AdamW state/gradient/parameter storages must not alias one another.
            owned=params+grads+m1+m2+steps
            check(len({t['storage_id'] for t in owned})==len(owned),tag+':independent_dense_parameter_gradient_moment_scalar_backings')
        else:check(inv['optimizer_step_values']==[],tag+':no_accidental_defaultdict_state_creation')
        check(type(inv['live_loss_tensor']) is bool and inv['live_loss_tensor'] is loss_live and len(loss)==(1 if loss_live else 0),tag+':explicit_loss_binding_lifetime')
        if loss_live:check(loss[0]['shape']==[] and loss[0]['numel']==1 and loss[0]['dtype']=='torch.float32' and loss[0]['requires_grad'] is True,tag+':live_scalar_loss_metadata')
    return r.checks


def replay_operations(case,identity,lower,upper):
    r=Replay();check=r.check
    operations=case['operation_receipts'];houses=case['housekeeping_receipts']
    check([v['id'] for v in operations]==list(OP_IDS) and [v['id'] for v in houses]==[OP_IDS[3],OP_IDS[7]],'operations:exact_eight_operators_two_housekeepings')
    previous=lower;worker_cpu=0
    for i,op in enumerate(operations):
        tag='operation:'+OP_IDS[i]
        r.message(op,case['nonce'],'worker',identity[0],tag)
        check(set(op)=={'nonce','role','pid','creation_filetime','id','phase_index','step','kind','operator_started_perf_counter','operator_completed_perf_counter','wall_seconds','worker_process_cpu_start_seconds','worker_process_cpu_end_seconds','cpu_seconds','live_loss_after_operator','provider_guard'},tag+':exact_operation_schema')
        a,b=op['operator_started_perf_counter'],op['operator_completed_perf_counter']
        c,d=op['worker_process_cpu_start_seconds'],op['worker_process_cpu_end_seconds']
        check(op['creation_filetime']==identity[1] and type(op['phase_index']) is int and op['phase_index']==i and type(op['step']) is int and op['step']==i//4+1 and op['kind']==OPERATORS[i%4],tag+':exact_identity_and_plan')
        accepted=case['worker_controls'][6+2*i]['accepted_perf_counter']
        ready=case['stages'][OP_IDS[i]]['stage_ready_perf_counter']
        check(all(finite(v) for v in (a,b,c,d)) and previous<=accepted<=a<=b<=ready<=upper and 0<=worker_cpu<=c<=d,tag+':operation_only_wall_and_worker_CPU_order')
        close(r,op['wall_seconds'],b-a,tag+':wall_recomputed')
        close(r,op['cpu_seconds'],d-c,tag+':worker_CPU_recomputed')
        check(type(op['live_loss_after_operator']) is bool and op['live_loss_after_operator'] is (i%4!=0),tag+':loss_binding_at_operator_exit')
        previous=ready;worker_cpu=d
        if i%4==3:
            house=houses[i//4];r.message(house,case['nonce'],'worker',identity[0],tag+':housekeeping')
            check(set(house)=={'nonce','role','pid','creation_filetime','id','started_perf_counter','completed_perf_counter','wall_seconds','loss_live_before','loss_live_after','recorded_loss'} and house['id']==op['id'],tag+':exact_housekeeping_schema')
            h0,h1=house['started_perf_counter'],house['completed_perf_counter']
            check(house['creation_filetime']==identity[1] and all(finite(v) for v in (h0,h1)) and b<=h0<=h1<=ready and house['loss_live_before'] is True and house['loss_live_after'] is False and finite(house['recorded_loss']),tag+':post_optimizer_housekeeping_before_hold_not_in_opclock')
            close(r,house['wall_seconds'],h1-h0,tag+':housekeeping_wall')
    span=case['training_span'];a,b=r.span(span,lower,upper,15,'training:instrumented_envelope')
    check(a==operations[0]['operator_started_perf_counter'] and b==case['stages'][OP_IDS[-1]]['stage_ready_perf_counter'],'training:span_exact_declared_endpoints')
    close(r,span['operator_wall_sum_seconds'],math.fsum(op['wall_seconds'] for op in operations),'training:operator_sum_excludes_holds_and_housekeeping')
    close(r,span['housekeeping_wall_sum_seconds'],math.fsum(h['wall_seconds'] for h in houses),'training:separate_housekeeping_sum')
    check(span['operator_wall_sum_seconds']+span['housekeeping_wall_sum_seconds']<=span['wall_seconds']+1e-8,'training:instrumented_total_not_uninstrumented_throughput')
    # The original single training deadline begins with B0 release, not with each operator.
    release=case['controller_controls'][6]['emitted_perf_counter']
    check(case['training_deadline_perf_counter']==min(release+15,case['case_deadline_perf_counter'],case['suite_deadline_perf_counter']) and b<=case['training_deadline_perf_counter'],'training:one_nonrenewable_training_deadline')
    return r.checks


def replay_controls(case,freeze,identity,lower,upper):
    r=Replay();check=r.check;nonce=case['nonce'];worker=identity[0]
    sent,accepted=case['controller_controls'],case['worker_controls']
    check(len(sent)==len(accepted)==len(CONTROL_PLAN)==26,'control:exact_26_emit_accept_pairs')
    previous_send=previous_accept=lower;controllers=set();accepts={}
    for i,(row,ack,spec) in enumerate(zip(sent,accepted,CONTROL_PLAN)):
        filename,command,label,decision_index=spec;tag='control:'+filename
        decision=case['role_decisions'][decision_index]
        emitted,received=row['emitted_perf_counter'],ack['accepted_perf_counter']
        check(set(row)=={'filename','nonce','role','pid','command','purpose','observer_duty_authorized','role_policy_admitted','role_decision_index','role_decision_label','control_index','emitted_perf_counter'} and row['filename']==ack['filename']==filename and row['nonce']==nonce and row['role']=='controller' and integer(row['pid'],1) and row['pid']!=worker and row['command']==command and row['purpose']==CONTROL_PURPOSE and row['observer_duty_authorized'] is True and row['role_policy_admitted'] is True and type(row['control_index']) is int and row['control_index']==i and type(row['role_decision_index']) is int and row['role_decision_index']==decision_index and row['role_decision_label']==label,tag+':exact_current_envelope')
        check(decision['admitted'] is True and decision['label']==label and decision['requested_control']==decision['permitted_control']=='observer-duty',tag+':exact_role_admission')
        check(all(finite(v) for v in (emitted,received)) and previous_send<=emitted and previous_accept<=received and decision['completed_perf_counter']<=emitted<=received<=upper,tag+':decision_emit_accept_order')
        if decision_index+1<len(case['role_decisions']):check(received<=case['role_decisions'][decision_index+1]['started_perf_counter'],tag+':before_next_decision')
        r.message(ack,nonce,'worker',worker,tag+':ack')
        check(set(ack)==set(END_BARRIER['acknowledgment_fields']) and type(ack['creation_filetime']) is int and ack['creation_filetime']==identity[1] and canonical(ack['control_envelope'])==canonical({k:v for k,v in row.items() if k!='filename'}) and type(ack['next_control_index']) is int and ack['next_control_index']==i+1,tag+':exact_authenticated_worker_copy')
        if command=='parent-sampled':
            br=case['memory_brackets'][label]
            check(br['parent']['query_completed_perf_counter']<=decision['started_perf_counter']<=emitted<=received<=br['self_after']['query_started_perf_counter'],tag+':full_parent_query_then_after_release')
        elif command=='continue':
            br=case['memory_brackets'][label]
            check(br['self_after']['query_completed_perf_counter']<=emitted,tag+':after_complete_self_bracket')
            if label in BOUNDARIES:check(case['inventories'][BOUNDARIES[label]]['snapshot_completed_perf_counter']<=emitted,tag+':after_inventory')
        previous_send,previous_accept=emitted,received;controllers.add(row['pid']);accepts[filename]=received
    check(len(controllers)==1,'control:one_controller_identity')
    launch=case['native_descendant']['launch_receipt'];imported=case['stages']['postimport']
    check(accepts['create-native.json']<=launch['launch_started_perf_counter']<=launch['launch_completed_perf_counter']<=case['stages']['preimport']['stage_ready_perf_counter'],'control:native_after_permission')
    check(accepts['preimport-continue.json']<=imported['import_started_perf_counter']<=imported['import_completed_perf_counter']<=imported['stage_ready_perf_counter'],'control:import_after_release')
    model=case['stages']['pretrain']['model_info']
    check(accepts['postimport-continue.json']<=model['model_load_started_perf_counter'],'control:load_after_release')
    check(accepts[OP_IDS[-1]+'-continue.json']<=case['stages']['postvalidation']['validation']['started_perf_counter'],'control:validation_after_last_training_hold')
    check(accepts['finish.json']<=case['cleanup']['started_perf_counter'],'control:finish_before_cleanup')
    import_interval=(imported['import_started_perf_counter'],imported['import_completed_perf_counter'])
    guards=[(PHASES[label],case['stages'][label]['provider_guard'],case['stages'][label]['stage_ready_perf_counter']) for label in STAGES]
    guards.extend(('train',op['provider_guard'],op['operator_completed_perf_counter']) for op in case['operation_receipts'])
    guards.append(('complete',case['healthy_completion']['provider_guard'],case['cleanup']['started_perf_counter']))
    cumulative=[]
    for phase,value,bound in guards:
        add_checks(r,replay_provider(value,freeze,phase,1,lower,bound,import_interval))
        if phase!='preimport':cumulative.append(canonical(value['diagnostic_events']))
    check(len(set(cumulative))==1,'provider:unchanged_cumulative_one_probe_all_stages_operations_completion')
    return r.checks


def replay_final_ack(case,identity,lower,upper):
    r=Replay();check=r.check
    barrier=case['postvalidation_continue_ack_barrier'];request=case['controller_controls'][24];ack=case['worker_controls'][24]
    check(set(barrier)==set(END_BARRIER['success_receipt_fields']) and barrier['passed'] is True and barrier['control_filename']==END_BARRIER['control_filename'] and barrier['filename']==END_BARRIER['filename'],'ack:exact_successful_parent_wait_inventory')
    check(barrier['worker_identity']=={'pid':identity[0],'creation_filetime':identity[1]} and all(type(v) is int for v in barrier['worker_identity'].values()),'ack:actual_retained_identity')
    a,b=r.span(barrier,lower,upper,5,'ack:parent_wait')
    emitted=request['emitted_perf_counter'];deadline=barrier['deadline_perf_counter']
    check(barrier['requested_perf_counter']==emitted and emitted<=a<=b and deadline==min(a+5,case['case_deadline_perf_counter'],case['suite_deadline_perf_counter']) and a<deadline and b<=deadline,'ack:exact_request_nonrenewable_deadline')
    check(canonical(barrier['accepted_receipt'])==canonical(ack) and set(ack)==set(END_BARRIER['acknowledgment_fields']) and ack['creation_filetime']==identity[1] and ack['next_control_index']==25 and ack['filename']=='postvalidation-continue.json' and canonical(ack['control_envelope'])==canonical({k:v for k,v in request.items() if k!='filename'}),'ack:exact_saved_authoritative_envelope_and_creation')
    live=case['prefinish_live_members'];finish=case['controller_controls'][25]['emitted_perf_counter']
    check(finite(ack['accepted_perf_counter']) and emitted<=ack['accepted_perf_counter']<=b and all(b<=v['verified_perf_counter']<=finish for v in live) and finish<=case['cleanup']['started_perf_counter'],'ack:accept_wait_complete_before_both_live_and_finish')
    return r.checks


def replay_training(case,identity,lower,upper):
    r=Replay();check=r.check
    model=case['stages']['pretrain']['model_info'];validation=case['stages']['postvalidation']['validation']
    check(model['model_id']==MODEL_ID and model['model_revision']==MODEL_REVISION and model['train_sha256']==TRAIN_SHA256 and model['schedule']==schedule() and model['schedule_sha256']==sha(canonical(schedule()).encode()),'training:exact_pinned_two_batch_schedule_model_fixture')
    check(all(type(model[k]) is int and model[k]==v for k,v in [('seed',503),('parameter_tensors',76),('trainable_parameter_count',PARAM_NUMEL),('intraop_threads',1),('interop_threads',1),('optimizer_state_entries',0)]) and model['batch_shapes']==[[2,65]]*2 and model['optimizer_type']=='AdamW' and canonical(model['optimizer'])==canonical(OPTIMIZER),'training:fresh_AdamW_exact_parameter_batch_threads')
    check(model['loader_local_files_only'] is True and model['trust_remote_code'] is False and model['holdout_opened'] is False and model['device']=='cpu' and model['dtype']=='torch.float32' and model['deterministic_algorithms'] is True and model['offline_environment']==OFFLINE_ENV,'training:offline_float32_no_remote_loader')
    a,b=model['model_load_started_perf_counter'],model['model_load_completed_perf_counter']
    check(all(finite(v) for v in (a,b)) and lower<=a<=b<=case['stages']['pretrain']['stage_ready_perf_counter'] and b-a<=25,'training:one_local_load_before_baseline')
    check(fingerprint(model['initial_parameter_sha256']) and fingerprint(validation['final_parameter_sha256']) and validation['final_parameter_sha256']!=model['initial_parameter_sha256'],'training:streaming_initial_final_hashes_changed_not_reference_equivalence')
    counters=validation['final_validity']['optimizer_counters']
    check(validation['final_validity']['final_parameter_gradient_moments_finite'] is True and len(counters)==76 and all(type(v) is int and v==2 for v in counters),'training:final_76_counters_two_and_finite')
    check(validation['no_holdout_evaluation'] is True and validation['no_checkpoint_written'] is True,'training:no_holdout_checkpoint')
    a,b=validation['started_perf_counter'],validation['completed_perf_counter']
    check(all(finite(v) for v in (a,b)) and case['memory_brackets'][OP_IDS[-1]]['self_after']['query_completed_perf_counter']<=a<=b<=case['stages']['postvalidation']['stage_ready_perf_counter'],'training:final_checks_after_all_training_measurements')
    return r.checks


def replay_identity_cleanup(case,freeze,lower,upper):
    r=Replay();check=r.check
    lid=r.identity(case['launcher'],'identity:launcher');worker=case['worker_identity'];ready=worker['self_receipt']
    wid=r.identity(ready,'identity:worker');r.message(ready,case['nonce'],'worker',wid[0],'identity:ready')
    reading(r,ready,wid,lower,upper,'identity:ready_memory')
    check(case['launcher']['assigned_while_suspended'] is True and case['launcher']['job_handle_inherited'] is False,'identity:suspended_noninherited_Job')
    check(worker['launcher_differs_from_interpreter'] is (wid[0]!=lid[0]) and worker['self_executable_expected_role']=='launcher' and worker['retained_os_image_expected_role']=='base_python' and ready['self_executable']=={'source':'sys.executable','basename':'python.exe','sha256':freeze['executables_sha256']['launcher'],'normalized_path_sha256':freeze['executable_path_sha256']['launcher']},'identity:exact_self_launcher_retained_actual_image_roles')
    chain=worker['verified_ancestry'];refs=[r.identity(v,'identity:ancestor') for v in chain]
    check(len(refs)==2 and refs==[wid,lid] and ready['parent_pid']==chain[0]['parent_pid'] and chain[0]['parent_pid']==lid[0] and lid[1]<=wid[1] and all(v['job_member'] is True for v in chain),'identity:exact_actual_worker_ancestry')
    for value,identity,role_name in [(worker['os_image'],wid,'base_python'),(case['launcher']['os_image'],lid,'launcher')]:
        check(r.identity(value,'identity:OS_image')==identity and value['basename'].lower()=='python.exe' and value['sha256']==freeze['executables_sha256'][role_name] and value['queried_from_retained_handle'] is True and value['matches_frozen_path_and_hash'] is True and lower<=value['verified_perf_counter']<=case['memory_brackets']['preimport']['self_before']['query_started_perf_counter'],'identity:retained_OS_path_hash_before_import')
    native=case['native_descendant'];nid=r.identity(native['os_identity'],'identity:native');launch=native['launch_receipt']
    r.message(launch,case['nonce'],'worker',wid[0],'identity:native_launch')
    check(type(launch['native_pid']) is int and launch['native_pid']==nid[0] and native['os_identity']['parent_pid']==wid[0] and native['job_member'] is True and native['no_native_self_report'] is True and wid[1]<=nid[1],'identity:native_direct_parent_Job')
    check(native['os_image']=={'basename':'cmd.exe','sha256':freeze['executables_sha256']['native'],'matches_frozen':True} and launch['command_arguments']==NATIVE_ARGUMENTS and launch['close_fds'] is True and launch['stdin_anonymous_pipe'] is True and launch['shell'] is False and type(launch['creationflags']) is int and launch['creationflags']==0x08000000 and launch['stdout_devnull'] is True and launch['stderr_devnull'] is True,'identity:exact_hidden_native_command_image_pipe')
    retained,role_checks=replay_roles(case,freeze,lower,upper);add_checks(r,role_checks)
    done=case['healthy_completion'];r.message(done,case['nonce'],'worker',wid[0],'cleanup:completion')
    check(done['creation_filetime']==wid[1] and type(done['model_loads']) is int and done['model_loads']==1 and type(done['optimizer_steps']) is int and done['optimizer_steps']==2 and type(done['native_exit_code']) is int and done['native_exit_code']==0 and done['native_released_nonempty_line'] is True,'cleanup:one_load_two_updates_native_exit0')
    clean=case['cleanup'];ca,cb=r.span(clean,lower,upper,4,'cleanup:all_handles')
    check(finite(clean['timeout_seconds']) and 0<=cb-ca<=clean['timeout_seconds']<=4 and cb<=min(case['case_deadline_perf_counter'],case['suite_deadline_perf_counter']),'cleanup:bounded_nonrenewable_cleanup')
    live=case['prefinish_live_members'];live_refs=[r.identity(v,'cleanup:prefinish') for v in live]
    check(len(live)==len(set(live_refs))==2 and set(live_refs)=={wid,nid} and all(v['alive'] is True and v['job_member'] is True and case['postvalidation_continue_ack_barrier']['completed_perf_counter']<=v['verified_perf_counter']<=case['controller_controls'][25]['emitted_perf_counter']<=ca for v in live),'cleanup:exact_worker_native_liveness_after_wait')
    exits=clean['exit_codes'];exit_refs=[r.identity(v,'cleanup:exit') for v in exits]
    check(len(exit_refs)==len(set(exit_refs))==5 and set(exit_refs)==set(retained.items()) and all(type(v['exit_code']) is int and v['exit_code']==0 for v in exits) and clean['all_retained_handles_exited'] is True and type(clean['job_active_count']) is int and clean['job_active_count']==0,'cleanup:all_five_retained_exit0_empty_Job')
    return wid,r.checks


def replay_boundary_costs(case,identity,lower,upper):
    r=Replay();check=r.check;queries=case['parent_query_costs'];samples=case['samples']
    check(len(queries)==25 and len(samples)==12 and [q['kind'] for q in queries].count('boundary_worker_memory_and_cpu')==12 and [q['kind'] for q in queries].count('held_role_census_and_liveness')==13,'boundary_cost:12_memory_13_held_census_queries')
    previous=lower
    for q in queries:
        a,b=r.span(q,previous,upper,5,'boundary_cost:timed_query');previous=b
        close(r,q['parent_process_cpu_seconds'],q['completed_process_cpu_seconds']-q['started_process_cpu_seconds'],'boundary_cost:parent_process_CPU_delta')
        check(all(finite(q[k]) and q[k]>=0 for k in ('started_process_cpu_seconds','completed_process_cpu_seconds','parent_process_cpu_seconds')),'boundary_cost:nonnegative_CPU')
    memory=[q for q in queries if q['kind']=='boundary_worker_memory_and_cpu']
    for label,sample,q in zip(STAGES,samples,memory):
        br=case['memory_brackets'][label]['parent']
        check(sample==br['sample'] and q['started_perf_counter']<=br['query_started_perf_counter']<=br['query_completed_perf_counter']<=q['completed_perf_counter'],'boundary_cost:complete_wrapper_inside_timed_query')
        reading(r,sample,identity,q['started_perf_counter'],q['completed_perf_counter'],'boundary_cost:retained_sample',True)
    census=[q for q in queries if q['kind']=='held_role_census_and_liveness']
    for q,c,d in zip(census,case['censuses'],case['role_decisions']):
        check(q['started_perf_counter']<=c['started_perf_counter']<=c['completed_perf_counter']<=d['completed_perf_counter']<=q['completed_perf_counter'],'boundary_cost:every_held_census_inside_parent_cost')
    return r.checks


def audit(report,protocol,freeze,*,protocol_sha256,freeze_sha256,actual_source_sha256,actual_dependency_sha256,
          actual_review_tools_sha256,actual_raw_files=None,actual_executable_sha256=None,actual_model_assets=None,
          provider_source_sha256=None,provider_source_path_sha256=None,actual_historical_evidence_sha256=None):
    r=Replay();check=r.check;case=None;start=end=0
    try:
        check(all(type(v.get('schema_version')) is int and v['schema_version']==1 for v in (report,protocol,freeze)),'suite:exact_schema')
        check(report['experiment_id']==protocol['experiment_id']==EXPERIMENT,'suite:experiment_identity')
        check(canonical(protocol['config'])==canonical(CONFIG),'suite:fixed_numeric_protocol')
        check(tuple(protocol['source_paths'])==SOURCE_PATHS and tuple(protocol['frozen_dependency_paths'])==DEPENDENCY_PATHS and tuple(protocol['review_tool_paths'])==REVIEW_PATHS,'suite:exact_new_source_review_dependency_paths')
        check(protocol['cases_in_order']==[{'id':'phase_memory','sampling_enabled':True,'query_treatment':'memory_only'}] and protocol['stages']==list(STAGES) and protocol['provider_stage_phases']==PHASES and protocol['boundaries']==BOUNDARIES and protocol['categories']==list(CATEGORIES),'suite:one_case_eight_ops_nine_inventory_twelve_stages')
        expected_ops=[{'id':id,'phase_index':i,'step':i//4+1,'kind':OPERATORS[i%4]} for i,id in enumerate(OP_IDS)]
        check(protocol['operations']==expected_ops and protocol['control_plan']==[{'filename':f,'command':c,'decision_label':l,'decision_index':i} for f,c,l,i in CONTROL_PLAN] and protocol['control_purpose']==CONTROL_PURPOSE and protocol['end_barrier']==END_BARRIER,'suite:exact_control_operator_ack_contract')
        check(protocol['history']=={'observer_duty_v1_acceptance_passed':False,'observer_duty_v2_acceptance_passed':True,'query_treatment_acceptance_passed':True,'scientific_status_unchanged':True} and protocol['raw_success_JSON_files']==110,'suite:historical_negative_status_and_exact_raw_count')
        check(protocol['model']=={'id':MODEL_ID,'revision':MODEL_REVISION,'assets':ASSETS,'planned_model_loads':1,'planned_optimizer_updates':2},'suite:pinned_model_assets_and_execution_ceiling')
        expected_training={'seed':503,'steps':2,'schedule':schedule(),'schedule_sha256':sha(canonical(schedule()).encode()),'train_sha256':TRAIN_SHA256,'optimizer':OPTIMIZER,'optimizer_state_entries_before_loop':0,'dense_only':True,'holdout_opened':False,'checkpoint_written':False}
        check(protocol['training']==expected_training,'suite:exact_two_dense_updates_no_heldout_checkpoint')
        check(protocol['provider_custody']=={'policy_id':PROVIDER_POLICY_ID,'provider_config':PROVIDER_CONFIG,'provider_source_relative_path':PROVIDER_RELATIVE_PATH,'provider_source_sha256':PROVIDER_SOURCE_SHA256,'frame_scope':'contiguous_initial_urllib3_frames','native_network_sandbox':False,'external_providers_permitted':False},'suite:closed_provider_contract')
        check(fingerprint(protocol_sha256) and protocol_sha256==PROTOCOL_SHA256 and protocol_sha256==freeze['protocol_sha256']==report['protocol_sha256'],'suite:root_pinned_protocol_chain')
        check(fingerprint(freeze_sha256) and freeze_sha256==report['implementation_sha256'],'suite:freeze_report_hash_chain')
        for field,report_field,expected,actual,paths in [('new_source_files_sha256','source_sha256',SOURCE_HASHES,actual_source_sha256,SOURCE_PATHS),('frozen_dependency_files_sha256','frozen_dependencies_sha256',DEPENDENCY_HASHES,actual_dependency_sha256,DEPENDENCY_PATHS),('review_tools_sha256','review_tools_sha256',None,actual_review_tools_sha256,REVIEW_PATHS)]:
            values=freeze[field]
            check(set(values)==set(paths) and all(fingerprint(v) for v in values.values()) and values==report[report_field]==actual,'suite:actual_frozen_files_'+field)
            if expected is not None:check(values==expected,'suite:root_predeclared_file_pins_'+field)
        check(SOURCE_HASHES is not None and DEPENDENCY_HASHES is not None,'suite:root_source_dependency_pins_present_before_execution')
        exe,path_hashes=freeze['executables_sha256'],freeze['executable_path_sha256']
        check(set(exe)==set(path_hashes)==EXECUTABLE_ROLES and all(fingerprint(v) for v in [*exe.values(),*path_hashes.values()]) and report['executables_sha256']==exe and report['executable_path_sha256']==path_hashes,'suite:four_executable_file_and_opaque_path_pins')
        check(freeze['provider_source_sha256']==PROVIDER_SOURCE_SHA256 and fingerprint(freeze['provider_source_path_sha256']) and report['provider_source_sha256']==PROVIDER_SOURCE_SHA256 and report['provider_source_path_sha256']==freeze['provider_source_path_sha256'],'suite:provider_file_opaque_path_pin')
        if actual_executable_sha256 is not None:check(actual_executable_sha256==exe,'suite:optional_actual_executable_bytes')
        if actual_model_assets is not None:check(actual_model_assets==ASSETS,'suite:optional_actual_model_files')
        if provider_source_sha256 is not None:check(provider_source_sha256==PROVIDER_SOURCE_SHA256,'suite:optional_actual_provider_bytes')
        if provider_source_path_sha256 is not None:check(provider_source_path_sha256==freeze['provider_source_path_sha256'],'suite:optional_actual_provider_opaque_path')
        if actual_historical_evidence_sha256 is not None:check(actual_historical_evidence_sha256==HISTORICAL_FILE_SHA256,'suite:unmodified_historical_failed_and_accepted_reports')
        declared,frozen,started,completed=[stamp(v) for v in (protocol['predeclared_at'],freeze['frozen_at'],report['started_at'],report['completed_at'])]
        check(declared<=frozen<=started<=completed and report['protocol_predeclared_at']==protocol['predeclared_at'] and report['implementation_frozen_at']==freeze['frozen_at'],'suite:predeclare_freeze_execution_chronology')
        start,end=r.span(report,0,float('inf'),60,'suite:total_wall')
        check(abs((completed-started).total_seconds()-(end-start))<=0.25,'suite:UTC_and_perf_duration_agree')
        check(report['os_name']=='nt' and report['no_fallback'] is True and report['passed'] is True and not report.get('error'),'suite:Windows_no_fallback_no_reported_error')
        check(type(report['planned_model_loads']) is int and report['planned_model_loads']==1 and type(report['planned_optimizer_updates']) is int and report['planned_optimizer_updates']==2,'suite:exact_one_load_two_updates')
        cases=report['cases'];check(isinstance(cases,list) and len(cases)==1 and cases[0]['id']=='phase_memory','suite:exact_one_case')
        case=cases[0]
    except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,ZeroDivisionError) as error:
        check(False,'suite:invalid_or_incomplete:'+str(error))
    if case is not None:
        try:
            check(case['id']=='phase_memory' and case['sampling_enabled'] is True and case['query_treatment']=='memory_only' and fingerprint(case['nonce']),'case:exact_memory_only_nonce_spec')
            check(case['passed'] is True and case['outcome']=='normal_completion' and not any(case.get(k) for k in ('error','cleanup_error','job_close_error','process_handle_close_error','worker_failure_receipt','worker_failure_custody_error','failure_cleanup','case_wall_budget_exceeded')),'case:no_hidden_failure')
            ca,cb=r.span(case,start,end,60,'case:wall')
            check(case['case_deadline_perf_counter']==min(ca+60,start+60) and case['suite_deadline_perf_counter']==start+60 and cb<=case['case_deadline_perf_counter'],'case:original_case_suite_deadlines')
            check(all(case[k]==freeze[k] for k in ('executables_sha256','executable_path_sha256','provider_source_sha256','provider_source_path_sha256')),'case:exact_frozen_executables_provider')
            if actual_raw_files is not None:
                actual=actual_raw_files['phase_memory'];expected=raw_payloads(case)
                check(len(actual)==len(expected)==110 and canonical(actual)==canonical(expected),'case:exact_110_raw_worker_files_no_missing_or_extra')
            identity,values=replay_identity_cleanup(case,freeze,ca,cb);add_checks(r,values)
            check(case['stages']['preimport']['torch_imported'] is False and case['stages']['preimport']['transformers_imported'] is False and case['stages']['postimport']['torch_version']=='2.9.1+cpu' and case['stages']['postimport']['transformers_version']=='4.57.3','case:authorized_pinned_package_imports')
            for fn,args in [(replay_held,(case,identity,ca,cb)),(replay_controls,(case,freeze,identity,ca,cb)),(replay_boundary_costs,(case,identity,ca,cb)),(replay_operations,(case,identity,ca,cb)),(replay_inventory,(case,identity,ca,cb)),(replay_phase_samples,(case,identity,ca,cb)),(replay_training,(case,identity,ca,cb)),(replay_final_ack,(case,identity,ca,cb))]:
                try:add_checks(r,fn(*args))
                except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,ZeroDivisionError) as error:check(False,fn.__name__+':invalid_or_incomplete:'+str(error))
            check(case['provider_custody_verified'] is True,'case:producer_provider_custody_verified')
        except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,ZeroDivisionError) as error:check(False,'case:invalid_or_incomplete:'+str(error))
    failures=[v['check'] for v in r.checks if not v['passed']]
    omitted=[name for value,name in [(actual_raw_files,'raw_worker_receipt_files'),(actual_executable_sha256,'local_executable_files'),(actual_model_assets,'local_model_asset_files'),(provider_source_sha256,'local_provider_file'),(provider_source_path_sha256,'local_provider_opaque_path'),(actual_historical_evidence_sha256,'historical_failed_and_accepted_reports')] if value is None]
    return {'schema_version':1,'passed':not failures,'receipt_consistency_passed':not failures,'check_count':len(r.checks),'checks_passed':sum(v['passed'] for v in r.checks),'failures':failures,'checks':r.checks,'unperformed_optional_file_checks':omitted,'root_freeze_pins_set':all(v is not None for v in (PROTOCOL_SHA256,SOURCE_HASHES,DEPENDENCY_HASHES)),
        'scope':'Independent saved-receipt/hash/math replay only; no producer or ML import, native execution, OS remeasurement, network or rerun. One instrumented two-update sequence with held graph lifetimes and metadata/allocator history. Stage-labelled whole-process current readings and finite active sampled maxima are lower bounds, not isolated tensor/backward/full peaks or missed-peak byte bounds. Short unsampled operations retain null unknown coverage separately from engineering/receipt acceptance. Primitive within-snapshot logical/storage metadata do not equal OS memory. B4/B8 follow separately clocked scalar/deletion housekeeping. No OFF baseline, total monitoring overhead, causal first-step premium, compression/quality/GPU/hardcap/production claim. Historical scientific negatives and invalid RSS remain unchanged.'}


def audit_files(report_path,protocol_path,freeze_path,*,root=ROOT,python_path=None,base_python_path=None,native_path=None,conhost_path=None,provider_source=None,model_dir=None):
    rr,report=bounded(report_path,16*1048576);pr,protocol=bounded(protocol_path);fr,freeze=bounded(freeze_path)
    raw={}
    for case in report.get('cases',[]):
        if case.get('id')!='phase_memory':raise ValueError('unknown case receipt directory')
        folder=Path(report_path).parent/'phase_memory'
        files=sorted(folder.glob('*.json'))
        if len(files)>110:raise ValueError('raw receipt file count exceeds fixed bound')
        raw['phase_memory']={p.name:bounded(p)[1] for p in files}
    paths={'launcher':python_path,'base_python':base_python_path,'native':native_path,'conhost':conhost_path}
    if any(v is not None for v in paths.values()) and any(v is None for v in paths.values()):raise ValueError('supply all four optional executable files together')
    exe=None if python_path is None else {k:sha(Path(v).read_bytes()) for k,v in paths.items()}
    assets=None if model_dir is None else {n:{'bytes':(Path(model_dir)/n).stat().st_size,'sha256':sha((Path(model_dir)/n).read_bytes())} for n in ASSETS}
    result=audit(report,protocol,freeze,protocol_sha256=sha(pr),freeze_sha256=sha(fr),actual_source_sha256={p:sha((Path(root)/p).read_bytes()) for p in SOURCE_PATHS},actual_dependency_sha256={p:sha((Path(root)/p).read_bytes()) for p in DEPENDENCY_PATHS},actual_review_tools_sha256={p:sha((Path(root)/p).read_bytes()) for p in REVIEW_PATHS},actual_raw_files=raw,actual_executable_sha256=exe,actual_model_assets=assets,provider_source_sha256=None if provider_source is None else provider_file_hash(provider_source),provider_source_path_sha256=None if provider_source is None else sha(os.path.normcase(os.path.realpath(provider_source)).encode('utf-8')),actual_historical_evidence_sha256={p:sha((Path(root)/p).read_bytes()) for p in HISTORICAL_FILE_SHA256})
    result.update(report_file_sha256=sha(rr),protocol_file_sha256=sha(pr),implementation_freeze_file_sha256=sha(fr))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('report','protocol','freeze','output','root','python','base-python','native','conhost','provider-source','model-dir'):
        parser.add_argument('--'+name,type=Path,required=name in ('report','protocol','freeze','output'))
    args=parser.parse_args(argv)
    result=audit_files(args.report,args.protocol,args.freeze,root=args.root or ROOT,python_path=args.python,base_python_path=args.base_python,native_path=args.native,conhost_path=args.conhost,provider_source=args.provider_source,model_dir=args.model_dir)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as out:json.dump(result,out,ensure_ascii=False,indent=2,allow_nan=False);out.write('\n')
    print('phase-current-memory saved receipt audit: '+('passed' if result['passed'] else 'FAILED'))
    return 0 if result['passed'] else 1


END_BARRIER = {"control_filename":"postvalidation-continue.json","filename":"postvalidation-continue-accepted.json",
    "controller_control_index":24,"worker_next_control_index":25,"timeout_seconds":5.0,
    "worker_identity_fields":["pid","creation_filetime"],
    "acknowledgment_fields":["nonce","role","pid","creation_filetime","filename","control_envelope","accepted_perf_counter","next_control_index"],
    "success_receipt_fields":["control_filename","filename","requested_perf_counter","started_perf_counter","deadline_perf_counter","worker_identity","accepted_receipt","completed_perf_counter","wall_seconds","passed"],
    "order":"request <= acknowledgment <= wait completion <= both retained live checks <= finish emission; acknowledgment may precede wait start",
    "deadline":"min(wait start + original five-second barrier budget, original case deadline, original suite deadline); never renewed"}

if __name__=='__main__':raise SystemExit(main())
