"""Post-outcome record-checker mutations only; no experiment execution."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from scripts import check_observer_duty_record as checker


def fixture():
    cases=[]
    for index,(name,enabled) in enumerate(checker.frozen.CASES):
        tick=100+index*10
        cases.append({'id':name,'sampling_enabled':enabled,'passed':True,'outcome':'normal_completion',
            'controller_controls':[{}]*10+[{'emitted_perf_counter':tick+1},{'emitted_perf_counter':tick+3}],
            'worker_controls':[{}]*10+[{'accepted_perf_counter':tick+4}],
            'prefinish_live_members':[{'alive':True,'job_member':True,'verified_perf_counter':tick+2},
                {'alive':True,'job_member':True,'verified_perf_counter':tick+2.5}],
            'cleanup':{'job_active_count':0,'exit_codes':[{'exit_code':0} for _ in range(5)]}})
    report={'experiment_id':checker.frozen.EXPERIMENT,'passed':True,'protocol_sha256':checker.PROTOCOL_SHA256,
        'implementation_sha256':checker.FREEZE_SHA256,'cases':cases}
    audit={'passed':False,'receipt_consistency_passed':False,'check_count':5528,'checks_passed':5524,
        'failures':list(checker.EXPECTED_FAILURES),'root_freeze_pins_set':True,'checks':[{'check':'synthetic-known-rejection','passed':False}]}
    hashes={key:getattr(checker,const) for key,const in [('report','REPORT_SHA256'),('protocol','PROTOCOL_SHA256'),
        ('freeze','FREEZE_SHA256'),('audit','AUDIT_SHA256'),('auditor','AUDITOR_SHA256'),('auditor_tests','AUDITOR_TEST_SHA256'),
        ('raw_inventory','RAW_INVENTORY_SHA256')]}
    hashes.update(sources=dict(checker.frozen.SOURCE_HASHES),dependencies=dict(checker.frozen.DEPENDENCY_HASHES),
        raw_count=176,raw_files_only=True)
    return report,audit,copy.deepcopy(audit),hashes


class ObserverDutyRecordTests(unittest.TestCase):
    def rejects(self,mutation,fragment):
        data=fixture();mutation(data);result=checker.check_record(*data)
        self.assertFalse(result['record_preservation_checks_passed'])
        self.assertFalse(result['experiment_acceptance_passed'])
        self.assertTrue(any(fragment in s for s in result['failures']),result['failures'])

    def test_known_rejection_preservation_is_explicitly_not_acceptance(self):
        result=checker.check_record(*fixture())
        self.assertTrue(result['record_preservation_checks_passed'],result['failures'])
        self.assertFalse(result['experiment_acceptance_passed']);self.assertFalse(result['frozen_success_auditor_passed'])
        self.assertTrue(result['post_outcome_checker']);self.assertFalse(result['preregistered_acceptance'])

    def test_all_byte_pins_and_raw_inventory_count_must_survive(self):
        for key in ('report','protocol','freeze','audit','auditor','auditor_tests','raw_inventory'):
            with self.subTest(key=key):self.rejects(lambda d:d[3].__setitem__(key,'0'*64),'exact_original_'+key)
        self.rejects(lambda d:d[3].__setitem__('raw_count',175),'exact_176_raw')
        self.rejects(lambda d:d[3].__setitem__('raw_files_only',False),'exact_176_raw')
        self.rejects(lambda d:d[3]['sources'].__setitem__(checker.frozen.SOURCE_PATHS[0],'0'*64),'exact_frozen_producer')
        self.rejects(lambda d:d[3]['dependencies'].pop(checker.frozen.DEPENDENCY_PATHS[0]),'exact_historical')

    def test_success_missing_duplicate_and_extra_failures_are_rejected(self):
        for index in (1,2):
            with self.subTest(index=index):
                self.rejects(lambda d:d[index].__setitem__('passed',True),'frozen_auditor_still_rejects')
                self.rejects(lambda d:d[index]['failures'].pop(),'exact_unchanged_four')
                self.rejects(lambda d:d[index]['failures'].append(checker.EXPECTED_FAILURES[0]),'exact_unchanged_four')
                self.rejects(lambda d:d[index].__setitem__('check_count',5527),'exact_unchanged_four')
                self.rejects(lambda d:d[index].__setitem__('checks_passed',5525),'exact_unchanged_four')
        self.rejects(lambda d:d[2]['checks'].append({'check':'relaxed-after-outcome','passed':True}),'frozen_checks_replayed_exactly')

    def test_observed_pre_acceptance_live_order_cannot_be_rewritten(self):
        self.rejects(lambda d:d[0]['cases'][0]['worker_controls'][10].__setitem__('accepted_perf_counter',100.5),'observed_parent_release')
        self.rejects(lambda d:d[0]['cases'][0]['prefinish_live_members'][0].__setitem__('alive',False),'observed_parent_release')
        self.rejects(lambda d:d[0]['cases'][0]['controller_controls'][11].__setitem__('emitted_perf_counter',105),'observed_parent_release')
        self.rejects(lambda d:d[0]['cases'][0]['cleanup'].__setitem__('job_active_count',1),'original_normal_exit')
        self.rejects(lambda d:d[0].__setitem__('passed',False),'original_producer_success_claim')

    def test_cli_zero_means_preservation_only_and_unreadable_fails(self):
        valid=checker.check_record(*fixture())
        with mock.patch.object(checker,'check_files',return_value=valid),mock.patch('builtins.print'):
            self.assertEqual(checker.main([]),0)
        valid['experiment_acceptance_passed']=True
        with mock.patch.object(checker,'check_files',return_value=valid),mock.patch('builtins.print'):
            self.assertEqual(checker.main([]),1)
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'failed.json'
            with mock.patch.object(checker,'check_files',side_effect=FileNotFoundError()),mock.patch('builtins.print'):
                self.assertEqual(checker.main(['--output',str(output)]),1)
            self.assertIn('unreadable_saved_record',output.read_text())


if __name__=='__main__':unittest.main()
