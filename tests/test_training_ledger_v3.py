"""Prefreeze archived full-directory controls; no model/process execution."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts import audit_training_ledger_v3 as audit

ROOT=Path(__file__).resolve().parents[1]
ARCHIVE=ROOT/'results/training-ledger-v2/raw'
FREEZE=ROOT/'fixtures/training-ledger-v2/implementation.json'


class FullCallerDirectory(unittest.TestCase):
    def setUp(self):
        self.report=json.loads((ARCHIVE/'report.json').read_bytes())
        self.freeze=json.loads(FREEZE.read_bytes())

    def test_archived_complete_directories_before_future_execution(self):
        result=audit.audit_cases(self.report,ARCHIVE,self.freeze)
        self.assertTrue(result['complete_directory_schema'])
        self.assertEqual(result['healthy_original_payload_checks'],1818)
        self.assertEqual((result['model_loads'],result['optimizer_updates'],result['retained_exits'],result['empty_jobs']),(2,16,10,2))

    def test_frozen_v2_acceptance_is_still_rejected(self):
        with self.assertRaisesRegex(AssertionError,'exact_raw_identity'):
            audit.saved.audit_files(ARCHIVE,ROOT/'fixtures/training-ledger-v2/protocol.json',FREEZE)

    def test_every_missing_progress_file_rejects_complete_audit_in_both_cases(self):
        for case in ('healthy','partial_pretrain'):
            for i in range(7):
                with self.subTest(case=case,index=i),tempfile.TemporaryDirectory()as tmp:
                    target=Path(tmp)/'raw';shutil.copytree(ARCHIVE,target)
                    (target/case/f'import-progress-{i:02d}.json').unlink()
                    with self.assertRaises((AssertionError,FileNotFoundError)):
                        audit.audit_cases(self.report,target,self.freeze)

    def test_missing_original_unknown_json_and_pending_reject_complete_audit(self):
        for case in ('healthy','partial_pretrain'):
            for mutation in ('missing-original','unknown-json','pending'):
                with self.subTest(case=case,mutation=mutation),tempfile.TemporaryDirectory()as tmp:
                    target=Path(tmp)/'raw';shutil.copytree(ARCHIVE,target)
                    if mutation=='missing-original':(target/case/'worker-ready.json').unlink()
                    else:(target/case/('unknown.json'if mutation=='unknown-json'else'orphan.pending')).write_text('{}')
                    with self.assertRaises((AssertionError,FileNotFoundError)):
                        audit.audit_cases(self.report,target,self.freeze)

    def test_semantic_progress_ledger_and_fault_acceptance_mutations_reject(self):
        for mutation in ('progress-identity','progress-provider','ledger','fault-counter'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory()as tmp:
                target=Path(tmp)/'raw';shutil.copytree(ARCHIVE,target)
                if mutation=='ledger':
                    with (target/'healthy/trace.jsonl').open('ab')as f:f.write(b'{}\n')
                else:
                    name='partial_pretrain/create-native-accepted.json'if mutation=='fault-counter'else'healthy/import-progress-00.json'
                    path=target/name;row=json.loads(path.read_bytes())
                    if mutation=='fault-counter':row['next_control_index']=99
                    elif mutation=='progress-identity':row['pid']+=1
                    else:row['provider_guard']['allowed_local_probe_count']=1
                    path.write_text(json.dumps(row),encoding='utf8')
                with self.assertRaises(AssertionError):audit.audit_cases(self.report,target,self.freeze)

    def test_unknown_suite_entry_rejects(self):
        with tempfile.TemporaryDirectory()as tmp:
            target=Path(tmp)/'raw';shutil.copytree(ARCHIVE,target);(target/'orphan.pending').write_text('{}')
            with self.assertRaises(AssertionError):audit.audit_cases(self.report,target,self.freeze)

    def test_version_three_reuses_the_exact_producer_and_worker(self):
        from experiments import training_ledger_v2 as old,training_ledger_v3 as new
        self.assertIs(new.run_case,old.run_case)
        self.assertTrue(set(old.SOURCES)<=set(new.SOURCES))
        self.assertEqual(old.SCRIPT,ROOT/'experiments/training_ledger_worker_v2.py')


if __name__=='__main__':unittest.main()
