"""Saved negative evidence and bounded mutations only; no OS/ML execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import audit_training_observer_failure as auditor

REPORT=auditor.ROOT/'results/training-observer/report.json'


class TrainingFailureAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw,cls.report=auditor.success.bounded(REPORT,16*1048576)
        _,cls.protocol=auditor.success.bounded(auditor.ROOT/'fixtures/training-observer/protocol.json')
        _,cls.freeze=auditor.success.bounded(auditor.ROOT/'fixtures/training-observer/implementation.json')
        cls.acceptance=auditor.success.audit_files(REPORT,auditor.ROOT/'fixtures/training-observer/protocol.json',
            auditor.ROOT/'fixtures/training-observer/implementation.json')

    def run_audit(self,report=None,acceptance=None,**overrides):
        args={'report_sha256':auditor.REPORT_SHA256,'protocol_sha256':auditor.PROTOCOL_SHA256,
            'freeze_sha256':auditor.FREEZE_SHA256,'success_auditor_sha256':auditor.SUCCESS_AUDITOR_SHA256,
            'success_test_sha256':auditor.SUCCESS_TEST_SHA256,'actual_source_sha256':dict(auditor.success.SOURCE_HASHES),
            'actual_dependency_sha256':dict(auditor.success.DEPENDENCY_HASHES)}
        args.update(overrides)
        return auditor.audit(copy.deepcopy(self.report) if report is None else report,
            copy.deepcopy(self.acceptance) if acceptance is None else acceptance,
            copy.deepcopy(self.protocol),copy.deepcopy(self.freeze),**args)

    def rejects(self,mutation,label):
        # JSON round trip prevents aliasing and allows field checks to be tested
        # independently of the separate exact-byte pin, using an unchanged pin
        # argument here. The real audit_files always computes the actual hash.
        report=json.loads(json.dumps(self.report)); mutation(report)
        result=self.run_audit(report)
        self.assertFalse(result['failure_receipt_consistency_passed'],label)
        self.assertTrue(any(label in x for x in result['failures']),result['failures'])

    def test_original_negative_report_preserves_acceptance_rejection(self):
        result=auditor.audit_files(REPORT)
        self.assertTrue(result['failure_receipt_consistency_passed'],result['failures'])
        self.assertIs(result['experiment_acceptance_passed'],False)
        self.assertIs(result['preregistered'],False)
        self.assertEqual(result['frozen_success_auditor_failures'],auditor.EXPECTED_ACCEPTANCE_FAILURES)
        self.assertEqual((result['observed_authenticated_preimport_failures'],result['observed_unknown_descendants'],
            result['observed_retained_exit_receipts'],result['model_load_receipts'],result['training_update_receipts']),(4,8,21,0,0))

    def test_pins_and_frozen_success_audit_cannot_be_rewritten(self):
        for key in ['report_sha256','protocol_sha256','freeze_sha256','success_auditor_sha256','success_test_sha256']:
            with self.subTest(key=key): self.assertFalse(self.run_audit(**{key:'0'*64})['failure_receipt_consistency_passed'])
        changed=copy.deepcopy(self.acceptance); changed.update(passed=True,failures=[])
        self.assertFalse(self.run_audit(acceptance=changed)['failure_receipt_consistency_passed'])

    def test_success_or_training_receipts_cannot_be_invented(self):
        self.rejects(lambda r:r.update(passed=True),'original_experiment_stays_failed')
        self.rejects(lambda r:r['cases'][4].update(passed=True,outcome='expected_injected_import_failure38'),'four_failures_one_exit37_success')
        self.rejects(lambda r:r['cases'][0]['stages'].update(postload={'model':{}}),'only_preimport_stage_reached')
        self.rejects(lambda r:r['cases'][0].update(operation={'optimizer_steps':2}),'no_import_failure_model_or_training_receipts')
        self.rejects(lambda r:r['cases'][4].update(import_failure_receipt={'expected_exit_code':38}),'no_import_failure_model_or_training_receipts')
        self.rejects(lambda r:r['cases'][0]['stages']['preimport'].update(torch_imported=True),'authenticated_no_ML_at_preimport')

    def test_unknown_descendants_and_retained_exits_cannot_be_dropped(self):
        self.rejects(lambda r:r['cases'][0]['stage_process_inventories'][0]['unknown_descendants'].pop(),'exact_two_unknown_descendants_preserved')
        self.rejects(lambda r:r['cases'][0]['failure_cleanup']['exit_codes'].pop(),'every_retained_identity_has_exact_exit')
        def replace_creation(r):
            inv=r['cases'][0]['stage_process_inventories'][0]; pid=inv['unknown_descendants'][0]
            next(x for x in inv['processes'] if x['pid']==pid)['creation_filetime']+=1
        self.rejects(replace_creation,'every_retained_identity_has_exact_exit')
        def orphan_unknown(r):
            inv=r['cases'][1]['stage_process_inventories'][0]; pid=inv['unknown_descendants'][0]
            next(x for x in inv['processes'] if x['pid']==pid)['parent_pid']=999999
        self.rejects(orphan_unknown,'incomplete_negative_receipt')

    def test_identity_bracket_and_query_cost_mutations_rejected(self):
        self.rejects(lambda r:r['cases'][0]['worker_identity']['self_receipt'].update(nonce='0'*64),'nonce_role_actual_pid')
        self.rejects(lambda r:r['cases'][0]['worker_identity']['os_image'].update(sha256=r['launch_executable_sha256']),'retained_OS_image_hash_path_identity')
        self.rejects(lambda r:r['cases'][0]['memory_brackets']['preimport']['comparison'].update(passed=False),'memory_comparison_independently_recomputed')
        self.rejects(lambda r:r['cases'][0]['parent_query_costs'][0].update(parent_process_cpu_seconds=1),'parent_CPU_cost_recomputed')

    def test_cleanup_exit37_and_whole_interval_shifts_rejected(self):
        self.rejects(lambda r:r['cases'][0]['failure_cleanup'].update(job_active_count=1),'all_exited_job_zero')
        self.rejects(lambda r:r['cases'][0]['failure_cleanup']['exit_codes'][0].update(exit_code=0),'exact_exit_codes')
        self.rejects(lambda r:r['cases'][3]['cleanup']['exit_codes'][0].update(exit_code=38),'exact_exit_codes')
        def shift_cleanup(r):
            c=r['cases'][2]; row=c['failure_cleanup']; delta=row['started_perf_counter']-c['started_perf_counter']-0.01
            row['started_perf_counter']-=delta; row['completed_perf_counter']-=delta
        self.rejects(shift_cleanup,'cleanup_after_receipts_within_4s')

    def test_actual_file_rewrite_is_rejected_by_exact_report_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'changed.json'; data=copy.deepcopy(self.report); data['cases'][0]['error']='rewritten'
            path.write_text(json.dumps(data),encoding='utf-8')
            result=auditor.audit_files(path)
            self.assertFalse(result['failure_receipt_consistency_passed'])
            self.assertIn('exact_original_failed_report_bytes',result['failures'])


if __name__=='__main__': unittest.main()
