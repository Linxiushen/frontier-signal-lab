"""Independent stdlib audit of pinned training/Windows observer receipts.

Reads saved JSON, raw control custody and file hashes only. Never imports experiment modules or ML,
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
EXPERIMENT = 'windows-pinned-pythia-training-observer-integration-v2'
# Root-approved stable sources; the implementation file is written after review.
PROTOCOL_SHA256 = 'd381c42ac6f21fc33ac27a4fdc9980b1cd7beeee32f82f7295c58afa742cfd23'
SOURCE_HASHES = {'experiments/training_observer_v2.py': '8355af96bebca468b458401b3a70fd5de75e15ec4ac640c4678e0f48e72fc30b', 'tests/test_training_observer_v2.py': 'cce005f32ce87f65fc0b119d19c4d759fb79bc06f7fcb5ad97137ad9caa66b31'}
DEPENDENCY_HASHES = {'experiments/activation_cost_probe.py': '0f3f0062269ad2b2531e9a6ef2f94dbc65b5af46a89bad75ec9d7be5f1d661ce', 'scripts/capture_real_activation.py': '32ac2555ce2f2593efc5f08188ba7b7703c33efb510fa78d680ace22fdab1b87', 'experiments/process_observer.py': '3f247512aee1e50940d57e81a0290d658bad56cae098d45b2f92bb69deece175', 'experiments/process_observer_probe.py': 'cfbc7de447cdf7b1dbae98e34c9e642c7d7cc8d93343c961f6aec8f78ea31740', 'experiments/workload_observer_probe.py': 'cdb14b85a40f866676e3181eca513041d6c6fa5bc679429654b4b72b9e63eba3', 'fixtures/process-observer/protocol.json': 'e4b77a96ab8aa1a2857b3156f485226791c877b923f847798eaad97e1f4b58a0', 'fixtures/process-observer/implementation.json': '535c3e78a9abf53fd89452876796c1df8c39a5a8d2b21963f173f148fc03e954', 'fixtures/workload-observer/protocol.json': '659146a5f05ed88b23886fefc3a389268883b88c5ad8b3a869712c1d27dbb463', 'fixtures/workload-observer/implementation.json': 'db207618c0f5226dc5f2e509fdbf99cb32ae9d24af4066f1bd3a23fba47e293c', 'fixtures/activation-cost/train.json': '8c48afcc68af60070b1f31b36c38bbe412ce3578bffec3283f956ed3f07b4681', 'fixtures/activation-cost/manifest.json': '0d08ba2574148924da713a40a66e49f3a7adc4d280a6d8f2e0d5135aae5148eb', 'fixtures/activation-cost/protocol.json': '8908ca5362a51a1b0e2a9d27657b0b8e64ac5632fc695b30407331be5c1c87ed', 'fixtures/activation-cost/implementation.json': 'e28fe5df090bcc86dae9e0151e3765f130d40a28499df5b0714be32f4b826de5', 'experiments/training_observer_probe.py': '39fca84fc9c2eef2abf7f967f70b7d5752faccddf6f5456c9965ed3f9a06d728', 'experiments/role_policy_probe.py': '5481a1720ad00cd7cf83d7a86938fd09916b001d8b0187ae8307d536bf4d027a', 'experiments/dual_identity_census.py': '031c5c67ba84afe9b5af8ab69ac7b0cb31e418efe3e32781b96ec76fcd9e0a91', 'fixtures/role-policy-probe/protocol.json': '9248f0fa142c78b980d6e52ecce84d97c520aff52e910b2a00f0ad975b75a84a', 'fixtures/role-policy-probe/implementation.json': 'c0fc12d9209933f0304bba2d84ba127aa32e26d852788ddd830e11dd59f228ca'}
SOURCE_PATHS = ('experiments/training_observer_v2.py', 'tests/test_training_observer_v2.py')
DEPENDENCY_PATHS = ('experiments/activation_cost_probe.py', 'scripts/capture_real_activation.py',
    'experiments/process_observer.py', 'experiments/process_observer_probe.py',
    'experiments/workload_observer_probe.py', 'fixtures/process-observer/protocol.json',
    'fixtures/process-observer/implementation.json', 'fixtures/workload-observer/protocol.json',
    'fixtures/workload-observer/implementation.json', 'fixtures/activation-cost/train.json',
    'fixtures/activation-cost/manifest.json', 'fixtures/activation-cost/protocol.json',
    'fixtures/activation-cost/implementation.json', 'experiments/training_observer_probe.py',
    'experiments/role_policy_probe.py', 'experiments/dual_identity_census.py',
    'fixtures/role-policy-probe/protocol.json', 'fixtures/role-policy-probe/implementation.json')
REVIEW_PATHS = ('scripts/audit_training_observer_v2.py', 'tests/test_training_observer_v2_auditor.py')
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


EXECUTABLE_ROLES = {"launcher", "base_python", "native", "conhost"}

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
    mode = case['mode']
    labels = ['before_native', 'preimport'] if mode == 'import_fail' else ['before_native', *STAGES]
    if mode in ('timeout', 'private_cap'):
        labels.append('pretermination')
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
        if label == 'pretermination':
            check(case['busy_sampling']['completed_perf_counter'] <= start and
                  decision_end <= case['termination_request_started_perf_counter'], tag + ':role_census_before_termination')
    return retained, replay.checks


CONTROL_PURPOSE = 'pinned offline training observer v2; fixed engineering controls'
CONTROL_PLAN = [('create-native.json', 'create-native', 'before_native', 0)]
for _index, _stage in enumerate(STAGES, 1):
    CONTROL_PLAN.extend([(_stage + '-parent-done.json', 'parent-sampled', _stage, _index),
                         (_stage + '-continue.json', 'continue', _stage, _index)])
CONTROL_PLAN.append(('finish.json', 'finish', 'allocated', 5))
PROVIDER_EVENTS = ['socket.connect', 'socket.getaddrinfo', 'socket.gethostbyname',
                   'socket.gethostbyname_ex', 'socket.gethostbyaddr', 'socket.sendto', 'socket.bind']


def provider_expected():
    return {'installed': True, 'python_audit_only': True, 'native_network_sandbox': False,
            'external_providers_permitted': False, 'synthetic_probe_denials': 1,
            'unexpected_denied_events': [], 'denied_audit_events': list(PROVIDER_EVENTS)}


def provider_ok(value):
    return isinstance(value,dict) and canonical(value)==canonical(provider_expected())


def replay_controls(case, freeze, lower, upper):
    replay = Replay()
    check = replay.check
    nonce, mode = case['nonce'], case['mode']
    worker = case['worker_identity']['self_receipt']['pid']
    count = {'healthy': 12, 'timeout': 11, 'private_cap': 11, 'import_fail': 3}[mode]
    sent, accepted = case['controller_controls'], case['worker_controls']
    check(len(sent) == len(accepted) == count, 'control:exact_mode_control_count')
    previous_send, previous_accept = lower, lower
    controller_pids, accepts = set(), {}
    for index, (row, ack, spec) in enumerate(zip(sent, accepted, CONTROL_PLAN[:count])):
        filename, command, label, decision_index = spec
        tag = 'control:' + filename
        decision = case['role_decisions'][decision_index]
        emitted, received = row['emitted_perf_counter'], ack['accepted_perf_counter']
        check(row['filename'] == ack['filename'] == filename and row['nonce'] == nonce and row['role'] == 'controller' and
              type(row['pid']) is int and row['pid'] > 0 and row['pid'] != worker and
              row['command'] == command and row['purpose'] == CONTROL_PURPOSE and
              row['training_v2_authorized'] is True and row['role_policy_admitted'] is True and
              type(row['control_index']) is int and row['control_index'] == index and
              type(row['role_decision_index']) is int and row['role_decision_index'] == decision_index and
              row['role_decision_label'] == label, tag + ':fixed_envelope_authority')
        controller_pids.add(row['pid'])
        check(decision['label'] == label and decision['admitted'] is True and
              decision['requested_control'] == decision['permitted_control'] == 'training-v2',
              tag + ':exact_current_role_decision')
        check(all(finite(value) for value in (emitted, received)) and
              previous_send <= emitted and previous_accept <= received and
              decision['completed_perf_counter'] <= emitted <= received <= upper,
              tag + ':monotonic_decision_emit_accept_chain')
        if decision_index + 1 < len(case['role_decisions']):
            check(received <= case['role_decisions'][decision_index + 1]['started_perf_counter'],
                  tag + ':accepted_before_successor_policy')
        replay.message(ack, nonce, 'worker', worker, tag)
        check(set(row) == {'filename','nonce','role','pid','command','purpose','training_v2_authorized',
              'role_policy_admitted','role_decision_index','role_decision_label','control_index','emitted_perf_counter'} and
              canonical(ack['control_envelope']) == canonical({key: value for key, value in row.items() if key != 'filename'}) and
              type(ack['next_control_index']) is int and ack['next_control_index'] == index + 1,
              tag + ':exact_worker_custody_of_emitted_payload')
        accepts[filename] = received
        previous_send, previous_accept = emitted, received
        if command == 'parent-sampled':
            bracket = case['memory_brackets'][label]
            check(bracket['parent']['perf_counter'] <= decision['started_perf_counter'] <= emitted <= received <=
                  bracket['self_after']['perf_counter'], tag + ':held_bracket_release_chronology')
        elif command == 'continue':
            check(case['memory_brackets'][label]['self_after']['perf_counter'] <= emitted,
                  tag + ':stage_continue_after_bracket')
    check(len(controller_pids) == 1, 'control:single_controller_identity_claim')
    launch = case['native_descendant']['launch_receipt']
    check(finite(launch['launch_started_perf_counter']) and finite(launch['launch_completed_perf_counter']) and
          accepts['create-native.json'] <= launch['launch_started_perf_counter'] <= launch['launch_completed_perf_counter'] <=
          case['stages']['preimport']['stage_ready_perf_counter'], 'control:native_launch_after_accepted_permission')
    labels = ['preimport'] if mode == 'import_fail' else STAGES
    for label in labels:
        stage = case['stages'][label]
        check(provider_ok(stage['provider_guard']), 'provider:' + label + ':local_Python_only_guard')
        check(finite(stage['stage_ready_perf_counter']) and lower <= stage['stage_ready_perf_counter'] <=
              case['memory_brackets'][label]['self_before']['perf_counter'], 'control:' + label + ':ready_before_bracket')
    if mode == 'import_fail':
        failure = case['import_failure_receipt']
        check(accepts['preimport-continue.json'] <= failure['import_started_perf_counter'] <=
              failure['failure_perf_counter'] <= case['cleanup']['started_perf_counter'] and
              provider_ok(failure['provider_guard']), 'control:precise_import_failure_after_authorization')
    else:
        stage = case['stages']['postimport']
        check(accepts['preimport-continue.json'] <= stage['import_started_perf_counter'] <=
              stage['import_completed_perf_counter'] <= stage['stage_ready_perf_counter'], 'control:import_after_authorized_release')
        model = case['stages']['postload']['model']
        loop = case['stages']['postupdate']['operation']['loop']
        check(accepts['postimport-continue.json'] <= model['preparation_timing']['started_perf_counter'],
              'control:actual_loader_after_authorized_release')
        check(accepts['postload-continue.json'] <= loop['loop_perf_counter_start'],
              'control:two_updates_after_authorized_release')
        check(accepts['postupdate-continue.json'] <= case['stages']['allocated']['stage_ready_perf_counter'],
              'control:allocation_stage_after_authorized_release')
        if mode == 'healthy':
            check(provider_ok(case['healthy_completion']['provider_guard']) and
                  accepts.get('finish.json',float('inf')) <= case['cleanup']['started_perf_counter'], 'provider:healthy_final_guard')
        else:
            check(accepts['allocated-continue.json'] <= case['busy_ready']['perf_counter'] and
                  all(provider_ok(case[key]['provider_guard']) for key in ('busy_ready','busy_first_operation')),
                  'provider:busy_only_after_authorization_with_guard')
    return replay.checks


def audit(report, protocol, freeze, *, protocol_sha256, freeze_sha256,
          actual_source_sha256, actual_dependency_sha256, actual_review_tools_sha256, launch_sha256=None,
          base_python_sha256=None, native_sha256=None, conhost_sha256=None, actual_model_assets=None,
          actual_control_files=None):
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
        check(canonical(protocol['control_plan'])==canonical([{'filename':name,'command':command,
            'decision_label':label,'decision_index':index} for name,command,label,index in CONTROL_PLAN]),
            'declared_fixed_control_plan')
        provider=protocol['provider_custody']
        check(provider['denied_python_audit_events']==PROVIDER_EVENTS and
            provider['external_providers_permitted'] is False and provider['native_network_sandbox'] is False and
            type(provider['synthetic_probe_denials']) is int and provider['synthetic_probe_denials']==1 and
            type(provider['unexpected_denied_events_allowed']) is int and provider['unexpected_denied_events_allowed']==0,
            'declared_bounded_local_provider_custody')
        check(fingerprint(protocol_sha256) and protocol_sha256==freeze['protocol_sha256']==report.get('protocol_sha256'),'protocol_hash_chain')
        if PROTOCOL_SHA256 is not None: check(protocol_sha256==PROTOCOL_SHA256,'root_frozen_protocol_pin')
        check(fingerprint(freeze_sha256) and freeze_sha256==report.get('implementation_sha256'),'implementation_freeze_hash')
        sources=freeze['new_source_files_sha256']; dependencies=freeze['frozen_dependency_files_sha256']
        check(set(sources)==set(SOURCE_PATHS) and all(fingerprint(x) for x in sources.values())
            and sources==actual_source_sha256==report.get('source_sha256'),'actual_source_file_hashes')
        check(set(dependencies)==set(DEPENDENCY_PATHS) and all(fingerprint(x) for x in dependencies.values())
            and dependencies==actual_dependency_sha256==report.get('frozen_dependencies_sha256'),'actual_dependency_file_hashes')
        reviews=freeze['review_tools_sha256']
        check(set(reviews)==set(REVIEW_PATHS) and all(fingerprint(x) for x in reviews.values())
            and reviews==actual_review_tools_sha256==report.get('review_tools_sha256'),'actual_review_tool_file_hashes')
        check(tuple(protocol['review_tool_paths'])==REVIEW_PATHS,'declared_review_tools')
        if SOURCE_HASHES is not None: check(sources==SOURCE_HASHES,'root_frozen_source_pins')
        if DEPENDENCY_HASHES is not None: check(dependencies==DEPENDENCY_HASHES,'historical_dependency_pins')
        executables,paths=freeze['executables_sha256'],freeze['executable_path_sha256']
        check(set(executables)==set(paths)==EXECUTABLE_ROLES and
            all(fingerprint(v) for v in list(executables.values())+list(paths.values())) and
            report.get('executables_sha256')==executables and report.get('executable_path_sha256')==paths,
            'four_exact_file_and_opaque_path_freeze')
        check(executables['launcher']==freeze['python_executable_sha256'] and
            executables['base_python']==freeze['base_python_executable_sha256'] and
            executables['native']==freeze['native_executable_sha256'],'singular_and_role_executable_hashes_agree')
        if conhost_sha256 is not None:
            check(conhost_sha256==executables['conhost'],'actual_conhost_file_hash')
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
                'process_handle_close_error','failure_cleanup','final_wall_budget_exceeded','case_wall_budget_exceeded')),prefix+'no_hidden_failure')
            start,end=interval(case,suite_a,suite_b,prefix+'case')
            check(0<=end-start<=60 and previous_end<=start,prefix+'ordered_case_60s_bound'); previous_end=end
            begin_utc,end_utc=stamp(case['started_at']),stamp(case['completed_at'])
            check(previous_utc<=begin_utc<=end_utc<=suite_end,prefix+'case_utc_order'); previous_utc=end_utc
            check(abs((end_utc-begin_utc).total_seconds()-(end-start))<=0.25,prefix+'case_utc_wall_agrees')
            nonce=case['nonce']; launcher=case['launcher']; lid=ident(launcher,prefix+'launcher')
            check(case.get('executables_sha256')==freeze['executables_sha256'] and
                case.get('executable_path_sha256')==freeze['executable_path_sha256'],prefix+'case_exact_executable_freeze')
            check(finite(case['case_deadline_perf_counter']) and finite(case['suite_deadline_perf_counter']) and
                case['suite_deadline_perf_counter']==suite_a+180.0 and
                case['case_deadline_perf_counter']==min(start+60.0,suite_a+180.0) and
                end<=case['case_deadline_perf_counter'],prefix+'nonrenewable_case_suite_deadlines')
            check(launcher.get('assigned_while_suspended') is True and launcher.get('job_handle_inherited') is False,prefix+'suspended_job_assignment')
            retained={lid[0]:lid[1]}
            if mode=='prehandshake_fail':
                check(case.get('prehandshake_control')=={'exit_code':37,'handshake_absent':True,
                    'actual_interpreter_identity_unavailable':True},prefix+'exact_prehandshake_control')
                check(not any(case.get(k) for k in ('worker_identity','native_descendant','stages','memory_brackets',
                    'samples','parent_query_costs','stage_process_inventories','import_failure_receipt')),prefix+'no_substituted_worker_or_training')
                check(case.get('outcome')=='expected_prehandshake_exit37',prefix+'outcome')
                check(not any(case.get(k) for k in ('censuses','role_decisions','controller_controls','worker_controls')),
                    prefix+'no_preauthentication_controls_or_roles')
                check(case.get('cleanup_exact_retained_identity_set') is True and case.get('control_custody_verified') is True,
                    prefix+'producer_cleanup_and_control_flags')
                if actual_control_files is not None:
                    check(actual_control_files.get(case_id)=={},prefix+'no_raw_prehandshake_control_files')
                cleanup(case,retained,mode,start,end,prefix); continue

            worker=case['worker_identity']; ready=worker['self_receipt']; wid=ident(ready,prefix+'worker')
            msg(ready,nonce,wid[0],prefix+'worker'); reading(ready,wid,start,end,prefix+'worker_ready')
            check(wid not in seen_worker_identities,prefix+'fresh_worker_identity'); seen_worker_identities.add(wid)
            check(worker.get('launcher_differs_from_interpreter') is (lid[0]!=wid[0]),prefix+'launcher_actual_distinction')
            self_image=ready['self_executable']
            check(worker.get('self_executable_expected_role')=='launcher' and
                worker.get('retained_os_image_expected_role')=='base_python' and
                self_image=={'source':'sys.executable','basename':'python.exe',
                'sha256':freeze['executables_sha256']['launcher'],
                'normalized_path_sha256':freeze['executable_path_sha256']['launcher']} and
                not any(k.startswith('runtime_executable_') for k in ready),prefix+'separate_self_launcher_OS_base_role')
            chain=worker['verified_ancestry']; pairs=[ident(x,prefix+'ancestor') for x in chain]
            check(len(chain)==2 and pairs[0]==wid and pairs[-1]==lid
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
                check(last_query_end<=a and row.get('kind') in ('actual_interpreter_memory_and_cpu_query','Toolhelp_process_tree_snapshot','held_role_census_and_liveness'),prefix+'query_order_and_kind'); last_query_end=b
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

            role_retained,role_checks=replay_roles(case,freeze,ready['perf_counter'],end)
            checks.extend({'check':prefix+x['check'],'passed':x['passed']} for x in role_checks)
            check(all(role_retained.get(pid)==creation for pid,creation in retained.items()),prefix+'role_raw_preserves_authenticated_primary_refs')
            retained=role_retained
            decisions=case['role_decisions']
            census_queries=[q for q in queries if q['kind']=='held_role_census_and_liveness']
            check(len(census_queries)==len(decisions),prefix+'every_full_census_has_query_cost')
            for q,c,d in zip(census_queries,case['censuses'],decisions):
                check(q['started_perf_counter']<=c['started_perf_counter']<=c['completed_perf_counter']
                    <=d['completed_perf_counter']<=q['completed_perf_counter'],prefix+'census_inside_timed_query')
            check(case.get('cleanup_exact_retained_identity_set') is True and case.get('control_custody_verified') is True,
                prefix+'producer_cleanup_and_control_flags')
            checks.extend({'check':prefix+x['check'],'passed':x['passed']} for x in replay_controls(case,freeze,start,end))
            if actual_control_files is not None:
                raw=actual_control_files[case_id]
                expected={}
                for row,ack in zip(case['controller_controls'],case['worker_controls']):
                    expected[row['filename']]={k:v for k,v in row.items() if k!='filename'}
                    expected[row['filename'].replace('.json','-accepted.json')]=ack
                check(canonical(raw)==canonical(expected),prefix+'exact_saved_controller_and_worker_control_files')
            # Cross-record anchors catch a shifted whole cleanup interval even
            # when its own duration and enclosing case bounds remain valid.
            live_rows=case.get('prefinish_live_members',[])+case.get('pretermination_live_members',[])
            anchor=max([ready['perf_counter']]+[x['completed_perf_counter'] for x in decisions]
                +[x['perf_counter'] for x in samples]+[x['completed_perf_counter'] for x in queries]
                +[x['verified_perf_counter'] for x in live_rows])
            check(anchor<=case['cleanup']['started_perf_counter'],prefix+'cleanup_after_all_known_live_and_work_receipts')

            if mode=='import_fail':
                failure=case['import_failure_receipt']; msg(failure,nonce,wid[0],prefix+'import_failure')
                check(failure.get('stage')=='import' and failure.get('exception_type')=='ModuleNotFoundError'
                    and failure.get('missing_module')=='training_observer_v2_missing_dependency_'+nonce
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
                check(decisions[-1]['completed_perf_counter']<=req and decisions[-1]['started_perf_counter']>=b,prefix+'pretermination_snapshot_before_request')
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
                codes={x['pid']:x['exit_code'] for x in case['cleanup']['exit_codes']}
                check(codes.get(lid[0])==codes.get(wid[0])==0xE003,prefix+'precise_busy_held_Python_termination_codes')
            clean_a,_=cleanup(case,retained,mode,start,end,prefix)
            check(last<=clean_a and samples[-1]['perf_counter']<=clean_a,prefix+'cleanup_after_recorded_work')
        except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,ZeroDivisionError) as error:
            check(False,prefix+'invalid_or_incomplete_receipt:'+str(error))
    failures=[x['check'] for x in checks if not x['passed']]
    omitted=[label for value,label in [(launch_sha256,'launcher_executable_file'),(base_python_sha256,'actual_base_interpreter_file'),
        (native_sha256,'native_executable_file'),(conhost_sha256,'conhost_executable_file'),(actual_model_assets,'local_model_asset_files'),
        (actual_control_files,'raw_controller_and_worker_receipt_files')] if value is None]
    return {'schema_version':1,'passed':not failures,'receipt_consistency_passed':not failures,
        'check_count':len(checks),'checks_passed':sum(x['passed'] for x in checks),'failures':failures,'checks':checks,
        'unperformed_optional_file_checks':omitted,'root_freeze_pins_set':PROTOCOL_SHA256 is not None and SOURCE_HASHES is not None and DEPENDENCY_HASHES is not None,
        'scope':'Offline stdlib receipt/hash/algebra consistency only; no OS remeasurement, experiment/ML import or process execution. Canonical file audit also checks every fixed sender/worker control JSON and rejects missing/extra fixed controls. Optional local executable/model bytes are unverified unless supplied. Two-update semantics also rely on the frozen historical helper; counters are not independent per-call tracing. Timestamped envelopes prove receipt ordering within the saved clock domain, not an independently observed atomic publish instant. Snapshot inventories cannot prove continuous child absence or exact concurrent kernel thread ownership. Provider guard is a single synthetic Python audit-event denial plus offline configuration, not native network isolation or an executed external provider. Memory brackets are current readings and peaks are process-lifetime values; cap is sampled with overshoot, not an import/training hard ceiling. Held off/on windows are descriptive, ordered, and do not estimate causal training slowdown. Cannot authenticate coherently rewritten evidence, establish quality/compression/cost gains or revise historic scientific negatives.'}


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


def audit_files(report_path,protocol_path,freeze_path,python_path=None,base_python_path=None,native_path=None,model_dir=None,root=ROOT,conhost_path=None):
    # Fixed before real acceptance: full180s sampling can exceed1MiB. Protocol
    # and implementation metadata retain the smaller1MiB bound.
    raw,report=bounded(report_path,16*1048576); pr,protocol=bounded(protocol_path); fr,freeze=bounded(freeze_path)
    controls={}
    allowed={row[0] for row in CONTROL_PLAN}
    allowed |= {name.replace('.json','-accepted.json') for name in allowed}
    for case in report.get('cases',[]):
        case_id=case['id']
        if case_id not in {row[0] for row in CASES}:
            raise ValueError('unknown case receipt directory')
        for row in case.get('controller_controls',[]):
            if row['filename'] not in {item[0] for item in CONTROL_PLAN}:
                raise ValueError('unknown control receipt filename')
        directory=Path(report_path).parent/case_id
        controls[case_id]={name:bounded(directory/name)[1] for name in sorted(allowed) if (directory/name).exists()}
    model_assets=None if model_dir is None else {name:{'bytes':(Path(model_dir)/name).stat().st_size,
        'sha256':sha((Path(model_dir)/name).read_bytes())} for name in ASSETS}
    result=audit(report,protocol,freeze,protocol_sha256=sha(pr),freeze_sha256=sha(fr),
        actual_source_sha256={p:sha((Path(root)/p).read_bytes()) for p in SOURCE_PATHS},
        actual_dependency_sha256={p:sha((Path(root)/p).read_bytes()) for p in DEPENDENCY_PATHS},
        actual_review_tools_sha256={p:sha((Path(root)/p).read_bytes()) for p in REVIEW_PATHS},
        launch_sha256=None if python_path is None else sha(Path(python_path).read_bytes()),
        base_python_sha256=None if base_python_path is None else sha(Path(base_python_path).read_bytes()),
        native_sha256=None if native_path is None else sha(Path(native_path).read_bytes()),
        conhost_sha256=None if conhost_path is None else sha(Path(conhost_path).read_bytes()),actual_model_assets=model_assets,
        actual_control_files=controls)
    result.update(report_file_sha256=sha(raw),protocol_file_sha256=sha(pr),implementation_freeze_file_sha256=sha(fr))
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('report','protocol','freeze','output'): parser.add_argument('--'+key,type=Path,required=True)
    for key in ('python','base-python','native','model-dir','conhost'): parser.add_argument('--'+key,type=Path)
    args=parser.parse_args(argv)
    result=audit_files(args.report,args.protocol,args.freeze,args.python,args.base_python,args.native,args.model_dir,conhost_path=args.conhost)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n')
    print(json.dumps({k:result[k] for k in ('passed','check_count','checks_passed','failures')}))
    return 0 if result['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
