"""Saved FAILED v2 record mutations only; no experiment/model/process work."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import check_training_observer_v2_record as checker


def fixture():
    root=checker.ROOT
    folder=root/'results/training-observer-v2'
    read=lambda path:checker.frozen.bounded(path,16*1048576)[1]
    report=read(folder/'report.json');audit=read(folder/'frozen-audit.json')
    protocol=read(root/'fixtures/training-observer-v2/protocol.json')
    implementation=read(root/'fixtures/training-observer-v2/implementation.json')
    receipts={name:read(folder/name) for name in checker.RAW_SHA256}
    hashes={'report':checker.REPORT_SHA256,'audit':checker.AUDIT_SHA256,'protocol':checker.PROTOCOL_SHA256,
        'implementation':checker.FREEZE_SHA256,'auditor':checker.AUDITOR_SHA256,'auditor_tests':checker.AUDITOR_TEST_SHA256,
        'sources':dict(checker.frozen.SOURCE_HASHES),'dependencies':dict(checker.frozen.DEPENDENCY_HASHES),
        'raw':dict(checker.RAW_SHA256)}
    return [report,audit,protocol,implementation,receipts,hashes]


class TrainingV2FailureRecordTests(unittest.TestCase):
    def setUp(self):
        self.data=fixture()

    def run_check(self):
        return checker.check_record(*self.data)

    def reject(self,mutation,label=None):
        original=copy.deepcopy(self.data)
        mutation()
        result=self.run_check()
        self.assertFalse(result['record_preservation_checks_passed'],result)
        self.assertFalse(result['experiment_acceptance_passed'])
        if label:self.assertTrue(any(label in row for row in result['failures']),result['failures'])
        self.data=original

    def test_exact_negative_record_can_pass_preservation_only(self):
        result=self.run_check()
        self.assertTrue(result['record_preservation_checks_passed'],result['failures'])
        self.assertFalse(result['experiment_acceptance_passed'])
        self.assertFalse(result['frozen_success_auditor_passed'])
        self.assertEqual(sum(row['retained_exit_receipts'] for row in result['case_summaries']),21)
        self.assertEqual(sum(row['real_package_import_completion_receipts'] for row in result['case_summaries']),3)
        self.assertTrue(all(row['model_load_receipts']==row['optimizer_update_receipts']==0 for row in result['case_summaries']))

    def test_experiment_failure_is_never_upgraded(self):
        self.reject(lambda:self.data[0].update(passed=True),'experiment_acceptance_remains_false')
        self.reject(lambda:self.data[0]['cases'][0].update(passed=True),'three_ML_failures_two_precise_controls')
        self.reject(lambda:self.data[0]['cases'][0].update(error='different error'),'generic_original_guard_failure_preserved')

    def test_exact_report_audit_protocol_and_implementation_bytes_are_pinned(self):
        for key in ('report','audit','protocol','implementation','auditor','auditor_tests'):
            with self.subTest(key=key):self.reject(lambda:self.data[5].update({key:'0'*64}))

    def test_source_and_dependency_freezes_are_not_self_asserted(self):
        self.reject(lambda:self.data[5]['sources'].update({checker.frozen.SOURCE_PATHS[0]:'0'*64}),'frozen_actual_producer_source_chain')
        self.reject(lambda:self.data[5]['dependencies'].update({checker.frozen.DEPENDENCY_PATHS[0]:'0'*64}),'frozen_actual_dependency_chain')

    def test_exact_frozen_rejection_list_and_counts_remain_negative(self):
        self.reject(lambda:self.data[1].update(passed=True),'exact_10_rejections_retained')
        self.reject(lambda:self.data[1]['failures'].pop(),'exact_10_rejections_retained')
        self.reject(lambda:self.data[1].update(checks_passed=11725),'exact_10_rejections_retained')
        result=checker.check_record(*self.data,recomputed_acceptance={'passed':True})
        self.assertFalse(result['record_preservation_checks_passed'])
        self.assertIn('frozen_auditor_recomputes_identical_rejection',result['failures'])

    def test_hidden_or_added_provider_events_cannot_be_laundered(self):
        name='healthy_dense2/postimport-ready.json'
        for events in ([],['socket.connect'],['socket.bind','socket.connect']):
            with self.subTest(events=events):
                self.reject(lambda:self.data[4][name]['provider_guard'].update(unexpected_denied_events=events),'denied_socket_bind_retained')
        self.reject(lambda:self.data[4][name]['provider_guard'].update(native_network_sandbox=True),'denied_socket_bind_retained')

    def test_raw_postimport_identity_threads_and_version_custody(self):
        name='dense2_busy_deadline/postimport-ready.json'
        for field,value,label in [('pid',999,'nonce_role_actual_PID'),('native_thread_count',1,'versions_thread7'),
                                  ('torch_version','other','versions_thread7'),('nonce','0'*64,'nonce_role_actual_PID')]:
            with self.subTest(field=field):self.reject(lambda:self.data[4][name].update({field:value}),label)

    def test_actual_import_completion_chronology_is_retained(self):
        self.reject(lambda:self.data[4]['healthy_dense2/postimport-ready.json'].update(import_started_perf_counter=0),'real_package_import_completed_before_failure_cleanup')
        self.reject(lambda:self.data[4]['healthy_dense2/postimport-before.json'].update(perf_counter=0),'real_package_import_completed_before_failure_cleanup')

    def test_missing_or_changed_raw_receipts_fail_even_with_original_report(self):
        for name in ('healthy_dense2/postimport-ready.json','dense2_private_cap64/preimport-continue-accepted.json'):
            with self.subTest(name=name):self.reject(lambda:self.data[4].pop(name),'all_51_exact_raw_receipt_bytes_and_names')
        self.reject(lambda:self.data[5]['raw'].update({'healthy_dense2/postimport-ready.json':'0'*64}),'all_51_exact_raw_receipt_bytes_and_names')

    def test_exact_emitted_and_worker_accepted_controls_are_bound(self):
        name='healthy_dense2/preimport-continue-accepted.json'
        self.reject(lambda:self.data[4][name]['control_envelope'].update(training_v2_authorized=False),'exact_raw_emit_accept_authority')
        self.reject(lambda:self.data[4][name].update(accepted_perf_counter=0),'monotonic_policy_emit_accept')
        self.reject(lambda:self.data[0]['cases'][0]['controller_controls'][0].update(role_decision_index=1),'exact_raw_emit_accept_authority')

    def test_postimport_or_training_cannot_be_added_after_failure(self):
        self.reject(lambda:self.data[0]['cases'][0]['stages'].update(postimport={}), 'only_preimport_accepted')
        self.reject(lambda:self.data[0]['cases'][0]['stages'].update(postload={'model':{}}),'zero_model_update_work_receipts')
        self.reject(lambda:self.data[4].update({'healthy_dense2/finish.json':{}}),'all_51_exact_raw_receipt_bytes_and_names')

    def test_cleanup_identity_omission_reuse_and_nonzero_job_fail(self):
        self.reject(lambda:self.data[0]['cases'][0]['failure_cleanup']['exit_codes'].pop(),'exact_retained_exit_set_and_job_zero')
        self.reject(lambda:self.data[0]['cases'][0]['failure_cleanup']['exit_codes'][0].update(creation_filetime=999),'exact_retained_exit_set_and_job_zero')
        self.reject(lambda:self.data[0]['cases'][0]['failure_cleanup'].update(job_active_count=1),'exact_retained_exit_set_and_job_zero')
        self.reject(lambda:self.data[0]['cases'][0]['failure_cleanup']['exit_codes'][0].update(exit_code=0),'original_five_failure_exit_codes57347')

    def test_healthy_failure_cannot_substitute_another_census_or_console(self):
        self.reject(lambda:self.data[0]['cases'][0]['censuses'][0]['processes'][-1]['image'].update(sha256='0'*64))
        self.reject(lambda:self.data[0]['cases'][0]['role_decisions'][1]['pinned_auxiliaries']['launcher']['auxiliary_ref'].update(creation_filetime=999))

    def test_expected_exit_controls_are_precise(self):
        self.reject(lambda:self.data[0]['cases'][3]['cleanup']['exit_codes'][0].update(exit_code=38),'original_exit37')
        self.reject(lambda:self.data[0]['cases'][4]['import_failure_receipt'].update(model_loads=1),'precise_injected_import38')
        self.reject(lambda:self.data[0]['cases'][4]['cleanup']['exit_codes'][0].update(exit_code=0),'precise_both_Python_exit38')

    def test_canonical_file_check_recomputes_original_rejection_and_detects_changes(self):
        source=checker.ROOT/'results/training-observer-v2'
        baseline=checker.check_files(source/'report.json',source/'frozen-audit.json')
        self.assertTrue(baseline['record_preservation_checks_passed'],baseline['failures'])
        self.assertFalse(baseline['experiment_acceptance_passed'])
        with tempfile.TemporaryDirectory() as folder:
            copied=Path(folder)/'saved';shutil.copytree(source,copied)
            # Git omits the original run's empty prehandshake directory.
            # Exercise that fresh-checkout layout even on the original host.
            empty_case=copied/'prehandshake_exit37'
            if empty_case.is_dir():empty_case.rmdir()
            run=lambda:checker.check_files(copied/'report.json',copied/'frozen-audit.json')
            path=copied/'healthy_dense2/postimport-ready.json'
            saved=path.read_bytes();value=json.loads(saved);value['provider_guard']['unexpected_denied_events']=[]
            path.write_text(json.dumps(value),encoding='utf-8')
            self.assertFalse(run()['record_preservation_checks_passed'])
            path.write_bytes(saved)
            extra=copied/'prehandshake_exit37/finish.json'
            extra.parent.mkdir(parents=True,exist_ok=True)
            extra.write_text('{}',encoding='utf-8')
            self.assertFalse(run()['record_preservation_checks_passed']);extra.unlink()
            (copied/'dense2_busy_deadline/preimport-continue-accepted.json').unlink()
            self.assertFalse(run()['record_preservation_checks_passed'])


if __name__=='__main__':
    unittest.main()
