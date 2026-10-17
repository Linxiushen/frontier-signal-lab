"""Post-outcome preservation check of one FAILED v2 integration.

This is a saved-record check, not acceptance. The frozen success auditor must
continue to reject. No experiment/model imports, processes or network requests.
The observed socket.bind audit event records a denied Python audit action; its
caller, arguments, purpose and native network effects were not recorded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))
from scripts import audit_training_observer_v2 as frozen

REPORT_SHA256 = '5a6cec898c46c1daaebd48d3ce0543eac3d097b6848b737c2047b379aa495873'
AUDIT_SHA256 = 'f2d012b248ed3c50ccee2372f581982b3da12ce67948857a817d9d9e832439b6'
PROTOCOL_SHA256 = 'd381c42ac6f21fc33ac27a4fdc9980b1cd7beeee32f82f7295c58afa742cfd23'
FREEZE_SHA256 = 'a07656ffb21da55e750300b88e69ceead85b914dbef48855072a3fe1af5722ec'
AUDITOR_SHA256 = '57c76b3cb0ac1dccbc222835cb71a09df06f812d8b9dda8e587480f713539822'
AUDITOR_TEST_SHA256 = 'ae1ec687d059249f80b696378e9a4102ebe10da51bdae15f6e57700cee0c3a11'
EXPECTED_ERROR = 'ObserverError: stage identity/thread count differs'
EXPECTED_FAILURES = ['reported_acceptance_pass_not_laundered']
for _case in ('healthy_dense2', 'dense2_busy_deadline', 'dense2_private_cap64'):
    EXPECTED_FAILURES.extend([_case + ':no_hidden_failure', _case + ':exact_stage_inventory',
                              _case + ":invalid_or_incomplete_receipt:'postimport'"])
RAW_SHA256 = {'dense2_busy_deadline/create-native-accepted.json': 'ad35ba5401a445a37cd060617eb76a4ecc6e14ae892e0647da74d81985bf9df2', 'dense2_busy_deadline/create-native.json': 'b53f68bb8e47ffecaf27ec14a2ecf0f54adebb6c1094cc02af89b1c9d999e40f', 'dense2_busy_deadline/native-ready.json': '16394e19a153c58e1b8a615b62ea1378dde95c609e2557772a0b938037c758c9', 'dense2_busy_deadline/postimport-before.json': '43a06dab900d45f4d17a1e3e673fae56dab3bae6f3ffc1722826421c8858f912', 'dense2_busy_deadline/postimport-ready.json': '8d60ee19b07353c41379979ca4871dfaa317ea71f210fa7ac13b5c58d942aee1', 'dense2_busy_deadline/preimport-after.json': '25bbb98704d181db1b696a1e832df9d19846df8cf18d9d189baae13b9241a646', 'dense2_busy_deadline/preimport-before.json': '53e5183421239bf3adb26c0ff20d539b32096b3ed513ebffc5e01ba73173ea7f', 'dense2_busy_deadline/preimport-continue-accepted.json': 'b2d7e9172c049954bfd96cda1b549f1d6b770e75598608796c83d1dfb69961c7', 'dense2_busy_deadline/preimport-continue.json': '18af2c02aea73f8e30836b4d16230330a7af6b1078a267d311f1ed22749c6039', 'dense2_busy_deadline/preimport-parent-done-accepted.json': '69f8a17d93f90f765a84858302a02dbc34c00f597feccae6935f87b2e6afbef5', 'dense2_busy_deadline/preimport-parent-done.json': '16c6ed10fc634ba66d1670d26ffc56a26fe0f5e0651a941e03b81371171ca7e1', 'dense2_busy_deadline/preimport-ready.json': 'a13611befa0046fa6d2fb6f049c8e0a178628b6245d267c91eef358010953771', 'dense2_busy_deadline/worker-ready.json': '37161fb32027d2d2f42d46225e76f3049feb4cdbdce2626bb3badb2880345b3c', 'dense2_private_cap64/create-native-accepted.json': '53efaaa34d7f4001c7edaf09728882e49b7c4b581316146eb8d90292d5fa2ef6', 'dense2_private_cap64/create-native.json': '766acfdbdb67590df8d307e3248bd37e19e04e0d486f766f4e45618459fd40bd', 'dense2_private_cap64/native-ready.json': '7461151e8d1c999093e881508ad406c6ba9d3af424781db05f16dbab43c7c584', 'dense2_private_cap64/postimport-before.json': '87025ee29df3c13f13e7511bbeef30294f70c449ffd37441051438a972ccc500', 'dense2_private_cap64/postimport-ready.json': '0962bfc613a88cfb631bbec6a17f5b2b22c8fd8712c3063a70370361d01ea2bd', 'dense2_private_cap64/preimport-after.json': '47b752d606e8fcead132397a1f1f384b0235973b14ec86a7acca8ea41d0e4f3e', 'dense2_private_cap64/preimport-before.json': '1f1a7b269d9dee5c043c3b196a53930040e38f337bcf8a706a0160667e0aecd1', 'dense2_private_cap64/preimport-continue-accepted.json': '94135483c9d190df2a03aedc34a2f280f0bf0cb1e29baebbc0aabaa80cc04ddd', 'dense2_private_cap64/preimport-continue.json': '466702194413265372dbe04cb20ac36b0aaa7b979c27a71d77517ba6fbe985a6', 'dense2_private_cap64/preimport-parent-done-accepted.json': '62c5785db8056774f41494d04e5bc588d6133b07854def50e5a7d62ebfc62656', 'dense2_private_cap64/preimport-parent-done.json': 'e27ae0140542000ac7e0586082a63e17ede9cd55c9e6f3ce01d3f56dab1994a5', 'dense2_private_cap64/preimport-ready.json': 'e9107aec7653d7e59c8418ecd0826bbf4c1aa3ed35e851ef17a9af12949b016b', 'dense2_private_cap64/worker-ready.json': '46be525e40aeb4605ba24185c8b39b53476cab9894dd851880637758e607ddc3', 'healthy_dense2/create-native-accepted.json': 'aa3af7b99bd2369b63661a1f086196f13cb7a5b2f7d5ab602011cc76e36cead1', 'healthy_dense2/create-native.json': 'e35317f1d92d612e6cc03208d10ec279c3f3473ae11e2df3d84e568c2704f609', 'healthy_dense2/native-ready.json': 'ea7938c48ee6a97b250500c94fe106daf4fdbd62e2f8b694032230d07558860f', 'healthy_dense2/postimport-before.json': '767c58ece4101ed30914ad3bd62334c0b50a1c2c099f96223354bacb6c70b03c', 'healthy_dense2/postimport-ready.json': '4958d32122ee47b2d919423b36a092dfa0e207b8f4994da54a3755ab49cc8eba', 'healthy_dense2/preimport-after.json': '166cc7a7ee83970c957630bc533b8542b9da3d287583086328b4921124858f49', 'healthy_dense2/preimport-before.json': '94543114e3d683d1c7e10b155f487fe7365f905b2b7f5b1611a456e5b0b9f7fa', 'healthy_dense2/preimport-continue-accepted.json': '2058bc932bb3f9cdf1aa223bf6dace12a51bd9fdccba635385d4a106071749e1', 'healthy_dense2/preimport-continue.json': 'ede318d13e8918d173a36f7d70643ec33b76582f81dfb42edf23609a8828e621', 'healthy_dense2/preimport-parent-done-accepted.json': 'ddff633321d69ba70ced9c689c561fafc7c42ddb1139544755cce4c171d38955', 'healthy_dense2/preimport-parent-done.json': 'dddd9e92d6ccbdafc7c6ad7e41775e42a18aa38478739b72f5b60fdf2ae6cb10', 'healthy_dense2/preimport-ready.json': 'd515dd288fbead4e40b394efc5c7c5e0b4ae9419d9f5893c4cc4b4d044df1edd', 'healthy_dense2/worker-ready.json': 'd057962dbecb5cec79802c521d9163b0d052475ba1b65c203ae1e17e4ee633a0', 'injected_import_failure38/create-native-accepted.json': '0b2c01ae84a89efc59534eb90a575e2dadda71f362beeba3e580e13b29da1e85', 'injected_import_failure38/create-native.json': '6d7577f9719dc092225c9ef2745152c49b0a958f04b7458b524755d59a4b95d7', 'injected_import_failure38/expected-import-failure.json': '2b5e0cfbfae88b130198e5a5948291fc4ddcc0b6f19980a5634789e1177e56a4', 'injected_import_failure38/native-ready.json': 'd7dc8d6536060af1d60a20fdb4971a79d3ca6652004832108b8e0f9817cc7b1c', 'injected_import_failure38/preimport-after.json': '29b015788e6841b29868172cf35d34f3af484a74aa603c85d35ccfed01ec4e26', 'injected_import_failure38/preimport-before.json': 'f6383759605e5f0aa60eee361032008b9ddfc7af3535385f7a9673d07657b9b6', 'injected_import_failure38/preimport-continue-accepted.json': 'b9313bfccc5371c51773214dd11856858dabd4ba420edb65d30256ad6b506d85', 'injected_import_failure38/preimport-continue.json': '0b92bd3ef3b2ad7698368080ff60c8e331dd18683bab5da60c33b47314f19ca4', 'injected_import_failure38/preimport-parent-done-accepted.json': '514086f1fc9ef459ab1b92298e4f656635eef12419a3982240d21bfee4e98e85', 'injected_import_failure38/preimport-parent-done.json': 'fb4e6cd2cdb961eeffd0ea66bbdd03a8331cd882148aab844a852c1fe35e9fc4', 'injected_import_failure38/preimport-ready.json': 'fc1d9b5ddbd8014338f791fa63c7a8a6e0bff6bf1e7bb0d1120c6523b3cea060', 'injected_import_failure38/worker-ready.json': 'de36035245d5b74bb906ad9ba6626fadbdcdc452ac44fd8fe9176daf3ca97106'}


def sha(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def check_record(report, acceptance, protocol, implementation, receipts, hashes, *, recomputed_acceptance=None):
    """Check fields independently of the immutable byte pins; never upgrade failure."""
    checks, summaries = [], []
    def check(value, name):
        checks.append({'check': name, 'passed': bool(value)})
        return bool(value)
    def equal(a, b):
        return canonical(a) == canonical(b)
    def ident(row, name):
        pair = row['pid'], row['creation_filetime']
        check(all(type(v) is int and v > 0 for v in pair), name + ':PID_creation')
        return pair
    def message(row, case, worker, name):
        check(row.get('nonce') == case['nonce'] and row.get('role') == 'worker' and
              type(row.get('pid')) is int and row['pid'] == worker[0], name + ':nonce_role_actual_PID')
    def span(row, lower, upper, name):
        a, b = row['started_perf_counter'], row['completed_perf_counter']
        check(all(finite(v) for v in (a, b, row['wall_seconds'])) and lower <= a <= b <= upper and
              math.isclose(b-a, row['wall_seconds'], rel_tol=1e-10, abs_tol=1e-8), name + ':monotonic_span')
        return a, b
    cases = []
    try:
        check(hashes['report'] == REPORT_SHA256, 'exact_original_failed_report_bytes')
        check(hashes['audit'] == AUDIT_SHA256, 'exact_original_frozen_audit_bytes')
        check(hashes['protocol'] == PROTOCOL_SHA256 == report['protocol_sha256'] == implementation['protocol_sha256'], 'exact_protocol_hash_chain')
        check(hashes['implementation'] == FREEZE_SHA256 == report['implementation_sha256'], 'exact_implementation_freeze')
        check(hashes['auditor'] == AUDITOR_SHA256 and hashes['auditor_tests'] == AUDITOR_TEST_SHA256 and
              implementation['review_tools_sha256'] == {'scripts/audit_training_observer_v2.py': AUDITOR_SHA256,
                  'tests/test_training_observer_v2_auditor.py': AUDITOR_TEST_SHA256}, 'frozen_acceptance_auditor_and_tests_unchanged')
        check(hashes['sources'] == frozen.SOURCE_HASHES == report['source_sha256'] == implementation['new_source_files_sha256'], 'frozen_actual_producer_source_chain')
        check(hashes['dependencies'] == frozen.DEPENDENCY_HASHES == report['frozen_dependencies_sha256'] == implementation['frozen_dependency_files_sha256'], 'frozen_actual_dependency_chain')
        check(hashes['raw'] == RAW_SHA256 and set(receipts) == set(RAW_SHA256), 'all_51_exact_raw_receipt_bytes_and_names')
        check(report['passed'] is False and report['experiment_id'] == protocol['experiment_id'] == frozen.EXPERIMENT and
              not report.get('error') and report.get('no_fallback') is True and not report.get('final_wall_budget_exceeded'), 'experiment_acceptance_remains_false')
        check(acceptance['passed'] is False and acceptance['receipt_consistency_passed'] is False and
              acceptance['check_count'] == 11725 and acceptance['checks_passed'] == 11715 and
              acceptance['failures'] == EXPECTED_FAILURES and len(acceptance['checks']) == 11725 and
              sum(row['passed'] is True for row in acceptance['checks']) == 11715 and
              [row['check'] for row in acceptance['checks'] if row['passed'] is False] == EXPECTED_FAILURES,
              'original_11715_of_11725_and_exact_10_rejections_retained')
        check(acceptance['report_file_sha256'] == REPORT_SHA256 and acceptance['protocol_file_sha256'] == PROTOCOL_SHA256 and
              acceptance['implementation_freeze_file_sha256'] == FREEZE_SHA256, 'original_audit_same_saved_bytes')
        check(acceptance['unperformed_optional_file_checks'] == ['launcher_executable_file','actual_base_interpreter_file',
              'native_executable_file','conhost_executable_file','local_model_asset_files'], 'no_unperformed_local_remeasurement_claim')
        if recomputed_acceptance is not None:
            check(equal(recomputed_acceptance, acceptance), 'frozen_auditor_recomputes_identical_rejection')
        cases = report['cases']
        check(len(cases) == 5 and [row['id'] for row in cases] == [row[0] for row in frozen.CASES] and
              [row['passed'] for row in cases] == [False, False, False, True, True] and
              all(type(row['passed']) is bool for row in cases), 'three_ML_failures_two_precise_controls')
        suite_a, suite_b = span(report, 0, float('inf'), 'suite')
        check(suite_b - suite_a <= 180, 'original_180s_suite_budget')
        check(frozen.stamp(protocol['predeclared_at']) <= frozen.stamp(implementation['frozen_at']) <=
              frozen.stamp(report['started_at']) <= frozen.stamp(report['completed_at']), 'original_declare_freeze_run_chronology')
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError) as error:
        check(False, 'invalid_original_record:' + type(error).__name__)
        cases = report.get('cases', []) if isinstance(report, dict) else []
    total_exits = 0
    for case, spec in zip(cases, frozen.CASES):
        name, mode, allocation = spec
        tag = name + ':'
        try:
            a, b = span(case, report['started_perf_counter'], report['completed_perf_counter'], tag + 'case')
            check(b-a <= 60 and (case['id'], case['mode'], case['manual_allocation_bytes']) == spec, tag + 'fixed_case_and_budget')
            check(not any(case.get(key) for key in ('cleanup_error','job_close_error','process_handle_close_error','case_wall_budget_exceeded')), tag + 'no_hidden_cleanup_failure')
            launcher = ident(case['launcher'], tag + 'launcher')
            if mode == 'prehandshake_fail':
                check(case['passed'] is True and case['outcome'] == 'expected_prehandshake_exit37' and not case.get('error') and
                      case['prehandshake_control'] == {'exit_code':37,'handshake_absent':True,'actual_interpreter_identity_unavailable':True}, tag + 'precise_exit37')
                check(not any(case.get(key) for key in ('worker_identity','stages','controller_controls','worker_controls','samples','censuses','role_decisions')), tag + 'no_unauthenticated_substitution')
                retained = {launcher}; cleanup = case['cleanup']; anchor = a
            else:
                worker = ident(case['worker_identity']['self_receipt'], tag + 'worker')
                check(set(case['stages']) == set(case['memory_brackets']) == {'preimport'}, tag + 'only_preimport_accepted')
                check([row['label'] for row in case['censuses']] == [row['label'] for row in case['role_decisions']] == ['before_native','preimport'], tag + 'only_two_held_censuses')
                # The frozen independent identity algebra checks only this saved
                # prefix. Its import-failure branch has this exact same prefix;
                # this temporary view never changes the original case or verdict.
                prefix = dict(case, mode='import_fail')
                retained_map, role_checks = frozen.replay_roles(prefix, implementation, case['worker_identity']['self_receipt']['perf_counter'], b)
                checks.extend({'check':tag+'saved_prefix_'+row['check'],'passed':row['passed']} for row in role_checks)
                retained = set(retained_map.items())
                check(len(retained) == 5, tag + 'all_five_role_identities_retained')
                raw = {key.split('/',1)[1]: value for key,value in receipts.items() if key.startswith(name+'/')}
                check(equal(raw['worker-ready.json'],case['worker_identity']['self_receipt']) and
                      equal(raw['native-ready.json'],case['native_descendant']['launch_receipt']) and
                      equal(raw['preimport-ready.json'],case['stages']['preimport']) and
                      equal(raw['preimport-before.json'],case['memory_brackets']['preimport']['self_before']) and
                      equal(raw['preimport-after.json'],case['memory_brackets']['preimport']['self_after']), tag + 'raw_identity_native_preimport_payload_custody')
                stage = case['stages']['preimport']
                check(stage['torch_imported'] is False and stage['transformers_imported'] is False and frozen.provider_ok(stage['provider_guard']), tag + 'clean_preimport_guard')
                sent = case['controller_controls']
                check(len(sent) == 3, tag + 'only_three_emitted_controls')
                accepts = {}; previous_emit = a; previous_accept = a
                for index, (row, control_spec) in enumerate(zip(sent, frozen.CONTROL_PLAN[:3])):
                    filename, command, label, decision_index = control_spec
                    ack = raw[filename.replace('.json','-accepted.json')]
                    envelope = {key:value for key,value in row.items() if key != 'filename'}
                    message(ack, case, worker, tag + filename)
                    check(row['filename'] == filename and equal(raw[filename],envelope) and equal(ack['control_envelope'],envelope) and
                          row['nonce'] == case['nonce'] and row['role'] == 'controller' and row['command'] == command and
                          row['purpose'] == frozen.CONTROL_PURPOSE and row['training_v2_authorized'] is True and row['role_policy_admitted'] is True and
                          type(row['control_index']) is int and row['control_index'] == index and row['role_decision_label'] == label and
                          type(row['role_decision_index']) is int and row['role_decision_index'] == decision_index and
                          ack['filename'] == filename and type(ack['next_control_index']) is int and ack['next_control_index'] == index+1,
                          tag + filename + ':exact_raw_emit_accept_authority')
                    emitted, accepted = row['emitted_perf_counter'], ack['accepted_perf_counter']
                    check(all(finite(v) for v in (emitted,accepted)) and previous_emit <= emitted <= accepted <= b and
                          previous_accept <= accepted and case['role_decisions'][decision_index]['completed_perf_counter'] <= emitted,
                          tag + filename + ':monotonic_policy_emit_accept')
                    accepts[filename] = accepted; previous_emit = emitted; previous_accept = accepted
                check(accepts['create-native.json'] <= raw['native-ready.json']['launch_started_perf_counter'], tag + 'native_action_after_accepted_control')
                if mode == 'import_fail':
                    failure = case['import_failure_receipt']; message(failure, case, worker, tag + 'failure38')
                    check(equal(raw['expected-import-failure.json'],failure) and failure['exception_type'] == 'ModuleNotFoundError' and
                          failure['missing_module'] == 'training_observer_v2_missing_dependency_'+case['nonce'] and
                          failure['torch_imported'] is False and failure['transformers_imported'] is False and
                          type(failure['model_loads']) is int and failure['model_loads'] == 0 and
                          type(failure['optimizer_steps']) is int and failure['optimizer_steps'] == 0 and
                          frozen.provider_ok(failure['provider_guard']) and case['passed'] is True and
                          case['outcome'] == 'expected_injected_import_failure38' and not case.get('error'), tag + 'precise_injected_import38')
                    check(accepts['preimport-continue.json'] <= failure['import_started_perf_counter'] <= failure['failure_perf_counter'] <= b, tag + 'injected_import_after_authorization')
                    cleanup = case['cleanup']; anchor = failure['failure_perf_counter']
                else:
                    check(case['passed'] is False and case['outcome'] is None and case['error'] == EXPECTED_ERROR and 'cleanup' not in case and
                          'worker_controls' not in case and not case.get('control_custody_verified'), tag + 'generic_original_guard_failure_preserved')
                    post, before = raw['postimport-ready.json'], raw['postimport-before.json']
                    message(post, case, worker, tag + 'raw_postimport'); message(before, case, worker, tag + 'raw_postimport_before')
                    check(post['stage'] == 'postimport' and type(post['native_thread_count']) is int and post['native_thread_count'] == 7 and
                          post['torch_version'] == '2.9.1+cpu' and post['transformers_version'] == '4.57.3', tag + 'raw_postimport_correct_PID_versions_thread7')
                    expected = frozen.provider_expected(); expected['unexpected_denied_events'] = ['socket.bind']
                    check(equal(post['provider_guard'],expected) and not frozen.provider_ok(post['provider_guard']), tag + 'raw_postimport_denied_socket_bind_retained')
                    check(accepts['preimport-continue.json'] <= post['import_started_perf_counter'] <= post['import_completed_perf_counter'] <=
                          post['stage_ready_perf_counter'] <= before['perf_counter'] <= case['failure_cleanup']['started_perf_counter'], tag + 'real_package_import_completed_before_failure_cleanup')
                    check(ident(before,tag+'postimport_before') == worker and not any(key in raw for key in
                          ('postimport-after.json','postimport-parent-done.json','postimport-continue.json','postload-ready.json','postupdate-ready.json','finish.json')),
                          tag + 'no_postimport_admission_or_model_update_release')
                    cleanup = case['failure_cleanup']; anchor = before['perf_counter']
                check(not any(key in case for key in ('healthy_completion','busy_ready','busy_first_operation','allocation_check','held_parent_overhead_windows')) and
                      not any(stage_name in case['stages'] for stage_name in ('postload','postupdate','allocated')), tag + 'zero_model_update_work_receipts')
            ca, cb = span(cleanup, anchor, b, tag + 'cleanup')
            exits = cleanup['exit_codes']; refs = [ident(row,tag+'exit') for row in exits]
            check(len(refs) == len(set(refs)) and set(refs) == retained and
                  cleanup['all_retained_handles_exited'] is True and type(cleanup['job_active_count']) is int and cleanup['job_active_count'] == 0 and
                  finite(cleanup['timeout_seconds']) and 0 <= cb-ca <= cleanup['timeout_seconds'] <= 4,
                  tag + 'exact_retained_exit_set_and_job_zero')
            check(all(type(row['exit_code']) is int and 0 <= row['exit_code'] < 2**32 for row in exits), tag + 'uint32_exit_codes_preserved')
            if mode in ('healthy','timeout','private_cap'):
                check(all(row['exit_code'] == 57347 for row in exits), tag + 'original_five_failure_exit_codes57347')
            elif mode == 'prehandshake_fail':
                check(exits[0]['exit_code'] == 37, tag + 'original_exit37')
            else:
                codes = {row['pid']:row['exit_code'] for row in exits}
                check(codes[launcher[0]] == codes[worker[0]] == 38, tag + 'precise_both_Python_exit38')
            total_exits += len(exits)
            summaries.append({'id':name,'experiment_case_passed':case['passed'],'retained_exit_receipts':len(exits),
                'job_active_count':0,'real_package_import_completion_receipts':1 if mode in ('healthy','timeout','private_cap') else 0,
                'model_load_receipts':0,'optimizer_update_receipts':0,'postimport_accepted':False})
        except (KeyError, TypeError, ValueError, AttributeError, IndexError, OverflowError) as error:
            check(False, tag + 'incomplete_failed_receipt:' + type(error).__name__)
    check(len(summaries) == 5 and total_exits == 21, 'five_complete_negative_record_cases_21_retained_exits')
    failures = [row['check'] for row in checks if not row['passed']]
    return {'schema_version':1,'record_preservation_checks_passed':not failures,'experiment_acceptance_passed':False,
        'frozen_success_auditor_passed':False,'check_count':len(checks),'checks_passed':sum(row['passed'] for row in checks),
        'failures':failures,'checks':checks,'case_summaries':summaries,'original_report_sha256':REPORT_SHA256,
        'original_frozen_audit_sha256':AUDIT_SHA256,'scope':__doc__}


def check_files(report_path, acceptance_path, *, root=ROOT):
    root, report_path = Path(root), Path(report_path)
    pp=root/'fixtures/training-observer-v2/protocol.json'; fp=root/'fixtures/training-observer-v2/implementation.json'
    rb, report=frozen.bounded(report_path,16*1048576); ab, acceptance=frozen.bounded(acceptance_path,16*1048576)
    pb, protocol=frozen.bounded(pp); fb, implementation=frozen.bounded(fp)
    receipts, raw_hashes = {}, {}
    for name in RAW_SHA256:
        path=report_path.parent/name
        if path.is_file():
            content,value=frozen.bounded(path)
            receipts[name]=value;raw_hashes[name]=sha(content)
    # Extra files in a fixed case directory also violate the immutable inventory.
    for name,_,_ in frozen.CASES:
        folder=report_path.parent/name
        if folder.exists():
            for path in folder.iterdir():
                rel=path.relative_to(report_path.parent).as_posix()
                if rel not in RAW_SHA256:
                    raw_hashes[rel]='unexpected-file-or-directory'
    hashes={'report':sha(rb),'audit':sha(ab),'protocol':sha(pb),'implementation':sha(fb),
        'auditor':sha((root/'scripts/audit_training_observer_v2.py').read_bytes()),
        'auditor_tests':sha((root/'tests/test_training_observer_v2_auditor.py').read_bytes()),
        'sources':{name:sha((root/name).read_bytes()) for name in frozen.SOURCE_PATHS},
        'dependencies':{name:sha((root/name).read_bytes()) for name in frozen.DEPENDENCY_PATHS},'raw':raw_hashes}
    try:
        recomputed=frozen.audit_files(report_path,pp,fp,root=root)
    except (KeyError,TypeError,ValueError,OSError) as error:
        recomputed={'unable_to_recompute':type(error).__name__}
    return check_record(report,acceptance,protocol,implementation,receipts,hashes,recomputed_acceptance=recomputed)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=ROOT/'results/training-observer-v2/report.json')
    parser.add_argument('--acceptance-audit',type=Path,default=ROOT/'results/training-observer-v2/frozen-audit.json')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    result=check_files(args.report,args.acceptance_audit)
    if args.output:
        with args.output.open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(result,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({key:result[key] for key in ('record_preservation_checks_passed','experiment_acceptance_passed','check_count','checks_passed','failures')}))
    return 0 if result['record_preservation_checks_passed'] and result['experiment_acceptance_passed'] is False else 1


if __name__=='__main__':
    raise SystemExit(main())
