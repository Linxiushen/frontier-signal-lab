"""Independent stdlib replay of a frozen Windows observer-duty ABBA study.

Reads saved receipts and hashes only. Never imports producer or ML packages,
starts a workload, opens a socket or revises any experiment outcome.
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
EXPERIMENT='windows-pinned-pythia-observer-duty-v1'
PROTOCOL_SHA256='759d841360550416d9f000a82d6449dffb577a37c8e6e42c5875741c3e4601cd'
SOURCE_HASHES={'experiments/observer_duty_probe.py': '37b6e82dcfd0e09a90e1837be05d05d50e7aef19a7fe06f323a46053d1aee80c', 'tests/test_observer_duty_probe.py': '46c12f50f519bf9793c3d61496fc171d887ba3d458778ba53269c5b88ed969e6'}
DEPENDENCY_HASHES={'experiments/activation_cost_probe.py': '0f3f0062269ad2b2531e9a6ef2f94dbc65b5af46a89bad75ec9d7be5f1d661ce', 'scripts/capture_real_activation.py': '32ac2555ce2f2593efc5f08188ba7b7703c33efb510fa78d680ace22fdab1b87', 'experiments/process_observer.py': '3f247512aee1e50940d57e81a0290d658bad56cae098d45b2f92bb69deece175', 'experiments/process_observer_probe.py': 'cfbc7de447cdf7b1dbae98e34c9e642c7d7cc8d93343c961f6aec8f78ea31740', 'experiments/workload_observer_probe.py': 'cdb14b85a40f866676e3181eca513041d6c6fa5bc679429654b4b72b9e63eba3', 'fixtures/process-observer/protocol.json': 'e4b77a96ab8aa1a2857b3156f485226791c877b923f847798eaad97e1f4b58a0', 'fixtures/process-observer/implementation.json': '535c3e78a9abf53fd89452876796c1df8c39a5a8d2b21963f173f148fc03e954', 'fixtures/workload-observer/protocol.json': '659146a5f05ed88b23886fefc3a389268883b88c5ad8b3a869712c1d27dbb463', 'fixtures/workload-observer/implementation.json': 'db207618c0f5226dc5f2e509fdbf99cb32ae9d24af4066f1bd3a23fba47e293c', 'fixtures/activation-cost/train.json': '8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681', 'fixtures/activation-cost/manifest.json': '0d08ba2574148924da713a40a66e49f3a7adc4d280a6d8f2e0d5135aae5148eb', 'fixtures/activation-cost/protocol.json': '8908ca5362a51a1b0e2a9d27657b0b8e64ac5632fc695b30407331be5c1c87ed', 'fixtures/activation-cost/implementation.json': 'e28fe5df090bcc86dae9e0151e3765f130d40a28499df5b0714be32f4b826de5', 'experiments/training_observer_probe.py': '39fca84fc9c2eef2abf7f967f70b7d5752faccddf6f5456c9965ed3f9a06d728', 'experiments/role_policy_probe.py': '5481a1720ad00cd7cf83d7a86938fd09916b001d8b0187ae8307d536bf4d027a', 'experiments/dual_identity_census.py': '031c5c67ba84afe9b5af8ab69ac7b0cb31e418efe3e32781b96ec76fcd9e0a91', 'fixtures/role-policy-probe/protocol.json': '9248f0fa142c78b980d6e52ecce84d97c520aff52e910b2a00f0ad975b75a84a', 'fixtures/role-policy-probe/implementation.json': 'c0fc12d9209933f0304bba2d84ba127aa32e26d852788ddd830e11dd59f228ca', 'experiments/training_observer_v2.py': '8355af96bebca468b458401b3a70fd5de75e15ec4ac640c4678e0f48e72fc30b', 'fixtures/training-observer-v2/protocol.json': 'd381c42ac6f21fc33ac27a4fdc9980b1cd7beeee32f82f7295c58afa742cfd23', 'fixtures/training-observer-v2/implementation.json': 'a07656ffb21da55e750300b88e69ceead85b914dbef48855072a3fe1af5722ec', 'experiments/training_observer_v3.py': '74d470e41ce5268c6cc761b7cd004e0e7d8b264095b045e8207912710662d6d5', 'fixtures/training-observer-v3/protocol.json': 'b248a981ffe9db8aea50f4a0c85d057e968620df372c74acb0835e2b046e3552', 'fixtures/training-observer-v3/implementation.json': '3e72671b15a04e0ec99b6968e721d0f74f70bff51a30d7052ecb24cc229e1c21'}
SOURCE_PATHS=('experiments/observer_duty_probe.py','tests/test_observer_duty_probe.py')
REVIEW_PATHS=('scripts/audit_observer_duty.py','tests/test_observer_duty_auditor.py')
DEPENDENCY_PATHS=('experiments/activation_cost_probe.py', 'scripts/capture_real_activation.py', 'experiments/process_observer.py', 'experiments/process_observer_probe.py', 'experiments/workload_observer_probe.py', 'fixtures/process-observer/protocol.json', 'fixtures/process-observer/implementation.json', 'fixtures/workload-observer/protocol.json', 'fixtures/workload-observer/implementation.json', 'fixtures/activation-cost/train.json', 'fixtures/activation-cost/manifest.json', 'fixtures/activation-cost/protocol.json', 'fixtures/activation-cost/implementation.json', 'experiments/training_observer_probe.py', 'experiments/role_policy_probe.py', 'experiments/dual_identity_census.py', 'fixtures/role-policy-probe/protocol.json', 'fixtures/role-policy-probe/implementation.json', 'experiments/training_observer_v2.py', 'fixtures/training-observer-v2/protocol.json', 'fixtures/training-observer-v2/implementation.json', 'experiments/training_observer_v3.py', 'fixtures/training-observer-v3/protocol.json', 'fixtures/training-observer-v3/implementation.json')
CONFIG={'seed': 503, 'optimizer_steps': 16, 'intraop_threads': 1, 'interop_threads': 1, 'train_blocks': 128, 'batch_size': 2, 'sequence_input_tokens': 64, 'sampler_interval_seconds': 0.02, 'maximum_recorded_sample_gap_seconds': 0.5, 'minimum_active_samples': 20, 'maximum_active_observations': 800, 'maximum_active_polls': 800, 'case_timeout_seconds': 60.0, 'total_timeout_seconds': 240.0, 'cleanup_timeout_seconds': 4.0, 'import_timeout_seconds': 20.0, 'load_timeout_seconds': 25.0, 'training_timeout_seconds': 15.0, 'barrier_timeout_seconds': 5.0, 'memory_bracket_tolerance_bytes': 4194304}
CASES=(('pair1_off',False),('pair1_on',True),('pair2_on',True),('pair2_off',False))
STAGES=('preimport','postimport','pretrain','postloop','postvalidation')
PHASES={'preimport':'preimport','postimport':'postimport','pretrain':'postload','postloop':'postupdate','postvalidation':'complete'}
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
def schedule():
    order = list(range(128)); random.Random(503).shuffle(order)
    return [order[index*2:(index+1)*2] for index in range(16)]


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
            check(case['memory_brackets'][label]['parent']['perf_counter'] <= start and
                  decision_end <= case['memory_brackets'][label]['self_after']['perf_counter'],
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



CONTROL_PURPOSE='pinned observer duty v1; fixed dense measurement controls'
CONTROL_PLAN=[('create-native.json','create-native','before_native',0)]
for _index,_stage in enumerate(STAGES,1):
    CONTROL_PLAN.extend([(_stage+'-parent-done.json','parent-sampled',_stage,_index),
                         (_stage+'-continue.json','continue',_stage,_index)])
CONTROL_PLAN.append(('finish.json','finish','postvalidation',5))


def replay_controls(case,freeze,lower,upper):
    replay=Replay();check=replay.check
    worker=case['worker_identity']['self_receipt']['pid'];nonce=case['nonce']
    sent,accepted=case['controller_controls'],case['worker_controls']
    check(len(sent)==len(accepted)==12,'control:exact_twelve_emit_accept_pairs')
    previous_send=previous_accept=lower;controller_pids=set();accepts={}
    for index,(row,ack,spec) in enumerate(zip(sent,accepted,CONTROL_PLAN)):
        name,command,label,decision_index=spec;tag='control:'+name
        decision=case['role_decisions'][decision_index]
        emitted,received=row['emitted_perf_counter'],ack['accepted_perf_counter']
        check(set(row)=={'filename','nonce','role','pid','command','purpose','observer_duty_authorized',
            'role_policy_admitted','role_decision_index','role_decision_label','control_index','emitted_perf_counter'} and
            row['filename']==ack['filename']==name and row['nonce']==nonce and row['role']=='controller' and
            integer(row['pid'],1) and row['pid']!=worker and row['command']==command and row['purpose']==CONTROL_PURPOSE and
            row['observer_duty_authorized'] is True and row['role_policy_admitted'] is True and
            type(row['role_decision_index']) is int and row['role_decision_index']==decision_index and
            type(row['control_index']) is int and row['control_index']==index and row['role_decision_label']==label,
            tag+':exact_current_authority_and_envelope')
        controller_pids.add(row['pid'])
        check(decision['admitted'] is True and decision['label']==label and
            decision['requested_control']==decision['permitted_control']=='observer-duty',tag+':exact_admitted_role_decision')
        check(all(finite(v) for v in (emitted,received)) and previous_send<=emitted and previous_accept<=received and
            decision['completed_perf_counter']<=emitted<=received<=upper,tag+':monotonic_decision_emit_accept')
        if decision_index+1<len(case['role_decisions']):
            check(received<=case['role_decisions'][decision_index+1]['started_perf_counter'],tag+':before_successor_decision')
        replay.message(ack,nonce,'worker',worker,tag)
        check(canonical(ack['control_envelope'])==canonical({k:v for k,v in row.items() if k!='filename'}) and
            type(ack['next_control_index']) is int and ack['next_control_index']==index+1,tag+':exact_saved_worker_copy')
        if command=='parent-sampled':
            b=case['memory_brackets'][label]
            check(b['parent']['perf_counter']<=decision['started_perf_counter']<=emitted<=received<=b['self_after']['perf_counter'],tag+':held_bracket_release')
        elif command=='continue':
            check(case['memory_brackets'][label]['self_after']['perf_counter']<=emitted,tag+':continue_after_bracket')
        previous_send,previous_accept=emitted,received;accepts[name]=received
    check(len(controller_pids)==1,'control:one_controller_identity')
    native=case['native_descendant']['launch_receipt']
    check(accepts['create-native.json']<=native['launch_started_perf_counter']<=native['launch_completed_perf_counter']<=
        case['stages']['preimport']['stage_ready_perf_counter'],'control:native_after_permission')
    for label in STAGES:
        stage=case['stages'][label]
        check(finite(stage['stage_ready_perf_counter']) and lower<=stage['stage_ready_perf_counter']<=
            case['memory_brackets'][label]['self_before']['perf_counter'],'control:'+label+':stage_ready_before_bracket')
    imported=case['stages']['postimport']
    check(accepts['preimport-continue.json']<=imported['import_started_perf_counter']<=imported['import_completed_perf_counter']<=
        imported['stage_ready_perf_counter'],'control:import_after_release')
    check(accepts['postimport-continue.json']<=case['stages']['pretrain']['model']['model_load_started_perf_counter'],
        'control:model_load_after_release')
    check(accepts['pretrain-continue.json']<=case['loop_before']['before_loop_perf_counter'],
        'control:training_after_release')
    check(accepts['postloop-continue.json']<=case['stages']['postvalidation']['validation']['started_perf_counter'],
        'control:validation_after_release')
    check(accepts['finish.json']<=case['cleanup']['started_perf_counter'],'control:finish_before_cleanup')
    interval=(imported['import_started_perf_counter'],imported['import_completed_perf_counter'])
    guards=[(PHASES[label],case['stages'][label]['provider_guard'],case['stages'][label]['stage_ready_perf_counter']) for label in STAGES]
    guards.extend([('train',case['loop_before']['provider_guard'],case['loop_before']['before_loop_perf_counter']),
        ('postupdate',case['loop_after']['provider_guard'],case['loop_after']['after_loop_perf_counter']),
        ('complete',case['healthy_completion']['provider_guard'],case['cleanup']['started_perf_counter'])])
    cumulative=[]
    for phase,value,bound in guards:
        replay.checks.extend(replay_provider(value,freeze,phase,1,lower,bound,interval))
        if phase!='preimport':cumulative.append(canonical(value['diagnostic_events']))
    check(len(set(cumulative))==1,'provider:unchanged_cumulative_event_all_stages_loop_and_completion')
    return replay.checks


def raw_payloads(case):
    result={}
    if 'worker_identity' in case:result['worker-ready.json']=case['worker_identity']['self_receipt']
    if 'native_descendant' in case:result['native-ready.json']=case['native_descendant']['launch_receipt']
    for label,value in case.get('stages',{}).items():
        result[label+'-ready.json']=value
        bracket=case.get('memory_brackets',{}).get(label,{})
        for field,suffix in [('self_before','-before.json'),('self_after','-after.json')]:
            if field in bracket:result[label+suffix]=bracket[field]
    for field,name in [('loop_before','before-loop.json'),('loop_after','after-loop.json'),
        ('healthy_completion','worker-completed.json'),('worker_failure_receipt','worker-failure.json')]:
        if field in case:result[name]=case[field]
    for row,ack in zip(case.get('controller_controls',[]),case.get('worker_controls',[])):
        result[row['filename']]={k:v for k,v in row.items() if k!='filename'}
        result[row['filename'].replace('.json','-accepted.json')]=ack
    return result


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


def replay_training(case,lower,upper):
    replay=Replay();check=replay.check
    model=case['stages']['pretrain']['model'];loop=case['loop_after']['loop']
    valid=case['stages']['postvalidation']['validation'];before=case['loop_before'];after=case['loop_after']
    check(model['model_id']==MODEL_ID and model['model_revision']==MODEL_REVISION and model['train_sha256']==TRAIN_SHA256 and
        model['schedule']==schedule() and model['schedule_sha256']==sha(canonical(schedule()).encode()),'training:pinned_model_data_and_sixteen_batch_schedule')
    check(all(type(model[k]) is int and model[k]==v for k,v in [('seed',503),('parameter_tensors',76),
        ('trainable_parameter_count',14067712),('intraop_threads',1),('interop_threads',1),('optimizer_state_entries',0)]) and
        model['batch_shapes']==[[2,65]]*16 and model['optimizer_type']=='AdamW' and
        canonical(model['optimizer'])==canonical(OPTIMIZER),'training:fresh_AdamW_exact_model_and_batch_dimensions')
    check(model['loader_local_files_only'] is True and model['trust_remote_code'] is False and model['holdout_opened'] is False and
        model['device']=='cpu' and model['dtype']=='torch.float32' and model['deterministic_algorithms'] is True and
        model['offline_environment']==OFFLINE_ENV,'training:fixed_offline_CPU_threads_and_loader')
    load_start,load_end=model['model_load_started_perf_counter'],model['model_load_completed_perf_counter']
    check(finite(load_start) and finite(load_end) and lower<=load_start<=load_end<=case['stages']['pretrain']['stage_ready_perf_counter'] and
        load_end-load_start<=25,'training:local_load_before_training_ready')
    start,end=loop['loop_perf_counter_start'],loop['loop_perf_counter_end']
    check(all(finite(v) for v in (start,end,before['before_loop_perf_counter'],after['after_loop_perf_counter'])) and
        lower<=before['before_loop_perf_counter']<=start<end<=after['after_loop_perf_counter']<=upper and end-start<=15,
        'training:exact_before_full_loop_after_clock_bracket')
    close(replay,loop['training_loop_wall_seconds'],end-start,'training:loop_wall_recomputed')
    check(type(loop['steps_completed']) is int and loop['steps_completed']==16 and
        type(loop['training_target_positions']) is int and loop['training_target_positions']==2048 and
        finite(loop['training_loop_cpu_seconds']) and loop['training_loop_cpu_seconds']>=0 and loop.get('time_control') is None,
        'training:exact_sixteen_updates_and_2048_targets')
    losses=loop['preupdate_batch_losses_recorded_after_updates']
    check(isinstance(losses,list) and len(losses)==16 and all(finite(v) for v in losses),'training:finite_sixteen_loss_trajectory')
    close(replay,loop['training_targets_per_second'],2048/(end-start),'training:target_throughput_recomputed')
    check(fingerprint(model['initial_parameter_sha256']) and fingerprint(valid['final_parameter_sha256']) and
        valid['final_parameter_sha256']!=model['initial_parameter_sha256'],'training:complete_changed_parameter_digests')
    counters=valid['final_validity']['optimizer_counters']
    check(valid['final_validity']['final_parameter_gradient_moments_finite'] is True and len(counters)==76 and
        all(type(v) is int and v==16 for v in counters),'training:all_76_optimizer_counters_sixteen_and_finite')
    check(valid['no_holdout_evaluation'] is True and valid['no_checkpoint_written'] is True,'training:no_holdout_or_checkpoint')
    a,b=valid['started_perf_counter'],valid['completed_perf_counter']
    check(finite(a) and finite(b) and after['after_loop_perf_counter']<=case['stages']['postloop']['stage_ready_perf_counter']<=
        case['memory_brackets']['postloop']['self_after']['perf_counter']<=a<=b<=case['stages']['postvalidation']['stage_ready_perf_counter'],
        'training:final_validation_and_digest_outside_actual_loop_and_postloop_hold')
    return replay.checks


def replay_active(case,identity,lower,upper):
    replay=Replay();check=replay.check;window=case['active_window'];loop=case['loop_after']['loop']
    start,end=loop['loop_perf_counter_start'],loop['loop_perf_counter_end']
    wide_start,wide_end=replay.span(window,lower,upper,60,'active:wider_release_completion_window')
    release=case['controller_controls'][6]['emitted_perf_counter']
    check(wide_start<=release<=case['loop_before']['before_loop_perf_counter']<=start<end<=
        case['loop_after']['after_loop_perf_counter']<=wide_end,'active:wider_window_covers_release_and_entire_loop_receipt')
    cpu0,cpu1,delta=[window[k] for k in ('parent_native_cpu_start_seconds','parent_native_cpu_end_seconds','parent_native_cpu_delta_seconds')]
    check(all(finite(v) for v in (cpu0,cpu1,delta)) and 0<=cpu0<=cpu1 and delta>=0,'active:wider_parent_CPU_nonnegative')
    close(replay,delta,cpu1-cpu0,'active:wider_parent_CPU_delta_recomputed_not_loop_only_CPU')
    check(type(window['poll_count']) is int and 1<=window['poll_count']<=800,'active:bounded_common_poll_count')
    observations=window['observations'];enabled=case['sampling_enabled']
    check(isinstance(observations,list) and len(observations)<=800 and (not enabled or len(observations)==window['poll_count']),
        'active:bounded_ON_observation_per_common_poll')
    prior=wide_start;previous_cpu=0;selected=[]
    for index,row in enumerate(observations):
        q0,q1,s0,s1=[row[k] for k in ('query_started_perf_counter','query_completed_perf_counter','snapshot_started_perf_counter','snapshot_completed_perf_counter')]
        check(set(row)=={'index','query_started_perf_counter','query_completed_perf_counter','sample','snapshot_started_perf_counter',
            'snapshot_completed_perf_counter','snapshot_process_count'} and type(row['index']) is int and row['index']==index and
            all(finite(v) for v in (q0,q1,s0,s1)) and prior<=q0<=q1<=s0<=s1<=wide_end,
            'active:ordered_bounded_exact_observation_fields')
        check(type(row['snapshot_process_count']) is int and row['snapshot_process_count']>0,
            'active:global_Toolhelp_count_not_role_admission')
        reading(replay,row['sample'],identity,q0,q1,'active:sample',True)
        check(row['sample']['native_cpu_seconds']>=previous_cpu,'active:worker_native_CPU_monotonic')
        previous_cpu=row['sample']['native_cpu_seconds'];prior=s1
        if start<=q0<=q1<=s0<=s1<=end:selected.append(row)
    indices=[r['index'] for r in selected]
    check(canonical(case['active_observation_indices'])==canonical(indices),'active:exact_whole_query_and_snapshot_inside_actual_loop_selection')
    if not enabled:
        check(observations==[] and indices==[] and case['training_memory'] is None and case['active_sampling'] is None,
            'active:OFF_no_active_queries_and_unknown_memory_is_null')
    else:
        stamps=[r['sample']['perf_counter'] for r in selected]
        gap=max(b-a for a,b in zip([start]+stamps,stamps+[end]))
        check(len(selected)>=20 and 0<=gap<=0.5,'active:ON_twenty_samples_and_boundary_gap_gate')
        memory=case['training_memory'];stats=case['active_sampling']
        check(set(memory)=={'sampled_current_resident_max_bytes','sampled_current_private_max_bytes','boundary'} and
            all(type(memory[key]) is int and memory[key]==max(r['sample']['memory'][metric] for r in selected)
                for key,metric in [('sampled_current_resident_max_bytes','resident_bytes'),('sampled_current_private_max_bytes','private_bytes')]) and
            memory['boundary']=='lower bounds on process current readings during full dense loop, not backward/full peak or memory saving',
            'active:ON_current_sample_maxima_only_lower_bounds')
        check(type(stats['selected_count']) is int and stats['selected_count']==len(selected),'active:selected_count_recomputed')
        close(replay,stats['maximum_gap_including_boundaries_seconds'],gap,'active:boundary_gap_recomputed')
        close(replay,stats['realized_samples_per_second'],len(selected)/(end-start),'active:realized_rate_recomputed')
        qw=sum(r['query_completed_perf_counter']-r['query_started_perf_counter'] for r in selected)
        sw=sum(r['snapshot_completed_perf_counter']-r['snapshot_started_perf_counter'] for r in selected)
        close(replay,stats['memory_cpu_query_wall_seconds'],qw,'active:memory_CPU_query_cost_recomputed')
        close(replay,stats['snapshot_wall_seconds'],sw,'active:global_snapshot_cost_recomputed')
        close(replay,stats['combined_query_wall_fraction'],(qw+sw)/(end-start),'active:combined_query_wall_fraction_recomputed')
    return replay.checks


def audit(report,protocol,freeze,*,protocol_sha256,freeze_sha256,actual_source_sha256,
        actual_dependency_sha256,actual_review_tools_sha256,actual_raw_files=None,
        actual_executable_sha256=None,actual_model_assets=None,provider_source_sha256=None,
        provider_source_path_sha256=None):
    replay=Replay();check=replay.check;cases=[];suite_a=suite_b=None;suite_utc=None
    try:
        check(all(type(v.get('schema_version')) is int and v['schema_version']==1 for v in (report,protocol,freeze)),'suite:schema')
        check(report['experiment_id']==protocol['experiment_id']==EXPERIMENT,'suite:experiment_identity')
        check(canonical(protocol['config'])==canonical(CONFIG),'suite:fixed_numeric_protocol')
        check(tuple(protocol['source_paths'])==SOURCE_PATHS and tuple(protocol['frozen_dependency_paths'])==DEPENDENCY_PATHS and
            tuple(protocol['review_tool_paths'])==REVIEW_PATHS,'suite:exact_frozen_file_inventories')
        check([(r['id'],r['sampling_enabled']) for r in protocol['cases_in_order']]==list(CASES) and
            all(type(r['sampling_enabled']) is bool for r in protocol['cases_in_order']),'suite:fixed_ABBA_order')
        check(canonical(protocol['control_plan'])==canonical([{'filename':f,'command':c,'decision_label':l,'decision_index':i} for f,c,l,i in CONTROL_PLAN]),
            'suite:fixed_control_plan')
        check(protocol['control_purpose']==CONTROL_PURPOSE and protocol['role_requested_control']=='observer-duty' and
            protocol['stages']==list(STAGES) and protocol['provider_stage_phases']==PHASES,'suite:declared_control_stage_contract')
        check(canonical(protocol['model'])==canonical({'id':MODEL_ID,'revision':MODEL_REVISION,'assets':ASSETS,
            'planned_model_loads':4,'planned_optimizer_updates':64}),'suite:declared_model_asset_and_load_contract')
        check(canonical(protocol['training'])==canonical({'seed':503,'steps':16,'schedule':schedule(),
            'schedule_sha256':sha(canonical(schedule()).encode()),'train_sha256':TRAIN_SHA256,'optimizer':OPTIMIZER,
            'optimizer_state_entries_before_loop':0,'dense_only':True,'holdout_opened':False,'checkpoint_written':False}),
            'suite:declared_fixed_dense_training_contract')
        check(canonical(protocol['provider_custody'])==canonical({'policy_id':PROVIDER_POLICY_ID,'provider_config':PROVIDER_CONFIG,
            'provider_source_relative_path':PROVIDER_RELATIVE_PATH,'provider_source_sha256':PROVIDER_SOURCE_SHA256,
            'frame_scope':'contiguous_initial_urllib3_frames','native_network_sandbox':False,'external_providers_permitted':False}),
            'suite:declared_provider_contract')
        check(fingerprint(protocol_sha256) and protocol_sha256==freeze['protocol_sha256']==report['protocol_sha256'],'suite:protocol_hash_chain')
        check(fingerprint(freeze_sha256) and freeze_sha256==report['implementation_sha256'],'suite:implementation_hash_chain')
        for values,actual,field,reported,names in [(freeze['new_source_files_sha256'],actual_source_sha256,'sources','source_sha256',SOURCE_PATHS),
            (freeze['frozen_dependency_files_sha256'],actual_dependency_sha256,'dependencies','frozen_dependencies_sha256',DEPENDENCY_PATHS),
            (freeze['review_tools_sha256'],actual_review_tools_sha256,'review_tools','review_tools_sha256',REVIEW_PATHS)]:
            check(set(values)==set(names) and all(fingerprint(v) for v in values.values()) and values==actual==report[reported],
                'suite:actual_'+field+'_file_hashes')
        if PROTOCOL_SHA256 is not None:check(protocol_sha256==PROTOCOL_SHA256,'suite:root_frozen_protocol_pin')
        if SOURCE_HASHES is not None:check(freeze['new_source_files_sha256']==SOURCE_HASHES,'suite:root_frozen_source_pins')
        if DEPENDENCY_HASHES is not None:check(freeze['frozen_dependency_files_sha256']==DEPENDENCY_HASHES,'suite:historical_dependency_pins')
        exe,paths=freeze['executables_sha256'],freeze['executable_path_sha256']
        check(set(exe)==set(paths)==EXECUTABLE_ROLES and all(fingerprint(v) for v in [*exe.values(),*paths.values()]) and
            report['executables_sha256']==exe and report['executable_path_sha256']==paths,'suite:four_exact_executables_and_opaque_paths')
        if actual_executable_sha256 is not None:check(actual_executable_sha256==exe,'suite:actual_four_local_executable_files')
        check(freeze['provider_source_sha256']==PROVIDER_SOURCE_SHA256 and fingerprint(freeze['provider_source_path_sha256']) and
            report['provider_source_sha256']==PROVIDER_SOURCE_SHA256 and report['provider_source_path_sha256']==freeze['provider_source_path_sha256'],
            'suite:exact_frozen_provider_file_and_opaque_path')
        if provider_source_sha256 is not None:check(provider_source_sha256==PROVIDER_SOURCE_SHA256,'suite:actual_local_provider_source_hash')
        if provider_source_path_sha256 is not None:check(provider_source_path_sha256==freeze['provider_source_path_sha256'],'suite:actual_provider_source_path_hash')
        if actual_model_assets is not None:check(actual_model_assets==ASSETS,'suite:actual_local_model_asset_files')
        declared,frozen,started,completed=[stamp(v) for v in (protocol['predeclared_at'],freeze['frozen_at'],report['started_at'],report['completed_at'])]
        check(declared<=frozen<=started<=completed,'suite:predeclare_freeze_execution_chronology')
        check(report['protocol_predeclared_at']==protocol['predeclared_at'] and report['implementation_frozen_at']==freeze['frozen_at'],
            'suite:declared_frozen_timestamps')
        suite_a,suite_b=replay.span(report,0,float('inf'),240,'suite:wall')
        check(abs((completed-started).total_seconds()-(suite_b-suite_a))<=0.25,'suite:UTC_perf_wall_agrees')
        check(report['os_name']=='nt' and report['no_fallback'] is True,'suite:Windows_only_no_fallback')
        check(report['passed'] is True and not report.get('error'),'suite:reported_failure_never_upgraded')
        check(type(report['planned_model_loads']) is int and report['planned_model_loads']==4 and
            type(report['planned_optimizer_updates']) is int and report['planned_optimizer_updates']==64,'suite:exact_four_loads_64_updates')
        cases=report['cases'];check(isinstance(cases,list) and len(cases)==4 and [v['id'] for v in cases]==[v[0] for v in CASES],
            'suite:complete_four_cases_in_ABBA_order')
        check(len(set(c['nonce'] for c in cases))==4 and all(fingerprint(c['nonce']) for c in cases),'suite:four_fresh_nonces')
        suite_utc=(started,completed)
    except (KeyError,ValueError,TypeError,IndexError,AttributeError,OverflowError) as error:
        check(False,'suite:invalid_or_incomplete:'+str(error));cases=report.get('cases',[]) if isinstance(report,dict) else []
        if not isinstance(cases,list):cases=[]
    previous=suite_a;last_utc=suite_utc[0] if suite_utc else None;worker_refs=set();trajectories=[];loop_walls={}
    for case,spec in zip(cases,CASES):
        prefix=spec[0]+':'
        try:
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
        except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,ZeroDivisionError) as error:
            check(False,prefix+'invalid_or_incomplete_receipt:'+str(error))
    try:
        parity=len(trajectories)==4 and len(set(trajectories))==1
        check(parity,'paired:all_four_initial_schedule_final_hashes_and_entire_loss_trajectories_exactly_equal')
        summary=report['paired_summary'];pairs=summary['pairs'];ratios=[]
        check(summary['valid'] is True and summary['all_four_trajectories_matched'] is True and parity,
            'paired:valid_interpretation_only_after_exact_four_trajectory_gate')
        check(len(pairs)==2,'paired:exact_two_pairs')
        for row,(off,on) in zip(pairs,[('pair1_off','pair1_on'),('pair2_off','pair2_on')]):
            check(row['off_case']==off and row['on_case']==on and row['exact_trajectory_matched'] is True and parity,'paired:exact_members_and_valid_trajectory')
            ratio=loop_walls[on]/loop_walls[off];ratios.append(ratio)
            close(replay,row['on_off_wall_ratio'],ratio,'paired:ON_OFF_actual_loop_wall_ratio_recomputed')
        close(replay,summary['geometric_mean_on_off_wall_ratio'],math.sqrt(ratios[0]*ratios[1]),'paired:geometric_mean_recomputed_no_favorable_threshold')
    except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,ZeroDivisionError) as error:
        check(False,'paired:invalid_or_incomplete:'+str(error))
    failures=[r['check'] for r in replay.checks if not r['passed']]
    omitted=[name for value,name in [(actual_raw_files,'raw_case_receipt_files'),(actual_executable_sha256,'local_four_executable_files'),
        (actual_model_assets,'local_model_asset_files'),(provider_source_sha256,'local_provider_source_file'),
        (provider_source_path_sha256,'local_provider_source_path')] if value is None]
    return {'schema_version':1,'passed':not failures,'receipt_consistency_passed':not failures,'check_count':len(replay.checks),
        'checks_passed':sum(c['passed'] for c in replay.checks),'failures':failures,'checks':replay.checks,
        'unperformed_optional_file_checks':omitted,'root_freeze_pins_set':all(v is not None for v in (PROTOCOL_SHA256,SOURCE_HASHES,DEPENDENCY_HASHES)),
        'scope':'Independent saved-receipt/hash/math replay only. No producer/ML import, native process, network, OS remeasurement or rerun. Exact raw files and local bytes only when supplied. ABBA n=2 paired comparisons exploratory with exact four-trajectory validity and no favorable ratio threshold. ON sampled current RSS/private maxima are lower bounds; OFF is unknown/null. Global active Toolhelp counts do not admit roles; held role censuses are bounded snapshots. Parent CPU spans wider release-to-completion window, not exact loop CPU. No isolated backward peak, compression/quality/GPU/production claim; historical failures remain unchanged.'}


def audit_files(report_path,protocol_path,freeze_path,*,root=ROOT,python_path=None,base_python_path=None,
        native_path=None,conhost_path=None,provider_source=None,model_dir=None):
    rr,report=bounded(report_path,16*1048576);pr,protocol=bounded(protocol_path);fr,freeze=bounded(freeze_path)
    raw={}
    for case in report.get('cases',[]):
        case_id=case['id']
        if case_id not in {c[0] for c in CASES}:raise ValueError('unknown case receipt directory')
        folder=Path(report_path).parent/case_id
        raw[case_id]={path.name:bounded(path)[1] for path in sorted(folder.glob('*.json'))}
    executable_paths={'launcher':python_path,'base_python':base_python_path,'native':native_path,'conhost':conhost_path}
    if any(v is not None for v in executable_paths.values()) and any(v is None for v in executable_paths.values()):
        raise ValueError('supply all four optional executable files together')
    executable_hashes=None if python_path is None else {k:sha(Path(v).read_bytes()) for k,v in executable_paths.items()}
    assets=None if model_dir is None else {name:{'bytes':(Path(model_dir)/name).stat().st_size,
        'sha256':sha((Path(model_dir)/name).read_bytes())} for name in ASSETS}
    result=audit(report,protocol,freeze,protocol_sha256=sha(pr),freeze_sha256=sha(fr),
        actual_source_sha256={p:sha((Path(root)/p).read_bytes()) for p in SOURCE_PATHS},
        actual_dependency_sha256={p:sha((Path(root)/p).read_bytes()) for p in DEPENDENCY_PATHS},
        actual_review_tools_sha256={p:sha((Path(root)/p).read_bytes()) for p in REVIEW_PATHS},actual_raw_files=raw,
        actual_executable_sha256=executable_hashes,actual_model_assets=assets,
        provider_source_sha256=None if provider_source is None else provider_file_hash(provider_source),
        provider_source_path_sha256=None if provider_source is None else sha(os.path.normcase(os.path.realpath(provider_source)).encode('utf-8')))
    result.update(report_file_sha256=sha(rr),protocol_file_sha256=sha(pr),implementation_freeze_file_sha256=sha(fr))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('report','protocol','freeze','output'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('python','base-python','native','conhost','provider-source','model-dir'):parser.add_argument('--'+name,type=Path)
    a=parser.parse_args(argv)
    result=audit_files(a.report,a.protocol,a.freeze,python_path=a.python,base_python_path=a.base_python,native_path=a.native,
        conhost_path=a.conhost,provider_source=a.provider_source,model_dir=a.model_dir)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({k:result[k] for k in ('passed','check_count','checks_passed','failures')}))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
