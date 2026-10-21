"""Mutations of saved post-outcome evidence, no native execution."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.check_observed_job_v2_failure import check

ROOT = Path(__file__).resolve().parents[1]


class ObservedJobV2PreservationTests(unittest.TestCase):
    def verify(self, output):
        return check(output, ROOT/'fixtures/observed-job-v2/protocol.json',
            ROOT/'fixtures/observed-job-v2/implementation.json', ROOT)

    def test_preservation_keeps_frozen_acceptance_false(self):
        result = self.verify(ROOT/'results/observed-job-v2/raw')
        self.assertTrue(result['preservation_passed'])
        self.assertFalse(result['frozen_acceptance'])
        self.assertEqual(result['retained_exits'], 10)
        self.assertEqual(result['committed_rows'], 38)

    def test_rejects_cleanup_identity_and_admission_mutations(self):
        mutations = [lambda r: r.update(passed=False),
            lambda r: r['cases'][0]['shutdown']['native_cleanup'].update(job_active_count=1),
            lambda r: r['cases'][0]['worker_ref'].update(creation_filetime=1),
            lambda r: r['cases'][3]['decisions'][1].update(admitted=True),
            lambda r: r['cases'][3]['censuses'][1]['processes'][-1]['image'].update(sha256='0'*64),
            lambda r: r['cases'][2]['shutdown']['ledger'].update(poisoned=False)]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index), tempfile.TemporaryDirectory() as temp:
                output = Path(temp)/'raw'
                shutil.copytree(ROOT/'results/observed-job-v2/raw', output)
                report = json.loads((output/'report.json').read_bytes())
                mutate(report)
                (output/'report.json').write_text(json.dumps(report),encoding='utf8')
                for case in report['cases']:
                    (output/case['name']/'result.json').write_text(json.dumps(case),encoding='utf8')
                with self.assertRaises(AssertionError):
                    self.verify(output)

    def test_partial_tail_cannot_be_replaced_with_expected_old_literal(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)/'raw'
            shutil.copytree(ROOT/'results/observed-job-v2/raw', output)
            path = output/'partial_write/trace.jsonl'
            path.write_bytes(path.read_bytes()[:-5] + b'{"kin')
            with self.assertRaises(AssertionError):
                self.verify(output)


if __name__ == '__main__':
    unittest.main()
