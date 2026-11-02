"""Post-outcome archive controls; never invoke a runtime, server or model."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest

from experiments.pi_generation_concurrent_http_audit import audit as frozen_audit
from experiments.pi_generation_concurrent_http_saved_observation import observe_saved_concurrent_admission

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'results/pi-generation-concurrent-http/raw'


@unittest.skipUnless(RAW.is_dir(), 'Published saved archive is required')
class ConcurrentSavedObservationTests(unittest.TestCase):
    def test_original_freeze_still_rejects_heterogeneous_real_trace(self):
        with self.assertRaisesRegex(KeyError, 'service'):
            frozen_audit(RAW)

    def test_separate_observation_reads_real_unscoped_and_scoped_records(self):
        events = [json.loads(line) for line in (RAW / 'stage0.jsonl').read_bytes().splitlines()]
        self.assertTrue(any(e['type'] == 'remote-authority' and 'service' not in e for e in events))
        self.assertTrue(any(e['type'] == 'concurrent-content-conflict' and 'service' not in e for e in events))
        result = observe_saved_concurrent_admission(RAW)
        self.assertEqual(result['total_admission_calls'], 28)
        self.assertEqual(result['concurrent_rounds'], 6)
        self.assertEqual(result['concurrent_exact_retries'], 6)

    def corrupted_copy(self, mutate):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        raw = Path(directory.name) / 'raw'
        shutil.copytree(RAW, raw)
        path = raw / 'stage0.jsonl'
        events = [json.loads(line) for line in path.read_bytes().splitlines()]
        mutate(events)
        path.write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
        return raw

    def test_missing_scope_on_actual_admission_is_rejected(self):
        def mutate(events):
            del next(e for e in events if e['type'] == 'admission')['service']
        with self.assertRaises((KeyError, AssertionError)):
            observe_saved_concurrent_admission(self.corrupted_copy(mutate))

    def test_retry_with_foreign_native_submission_is_rejected(self):
        def mutate(events):
            row = next(e for e in events if e['type'] == 'concurrent-admission-close')
            row['results'][2]['submissionId'] += 1
        with self.assertRaises(AssertionError):
            observe_saved_concurrent_admission(self.corrupted_copy(mutate))

    def test_release_before_all_arrivals_is_rejected(self):
        def mutate(events):
            row = next(e for e in events if e['type'] == 'concurrent-reserve-release')
            row['arrivals'] = 2
        with self.assertRaises(AssertionError):
            observe_saved_concurrent_admission(self.corrupted_copy(mutate))

    def test_conflict_cannot_claim_a_foreign_scope(self):
        def mutate(events):
            row = next(e for e in events if e['type'] == 'concurrent-content-conflict')
            row['service'] = 1
        with self.assertRaises(AssertionError):
            observe_saved_concurrent_admission(self.corrupted_copy(mutate))


if __name__ == '__main__':
    unittest.main()
