"""Pure preregistration boundaries; no optional runtime or native execution."""
from pathlib import Path
import copy
import json
import unittest

from scripts.check_pi_generation_concurrent_http import validate_workload, WORKLOAD, MANDATORY_SOURCES
from experiments.pi_generation_concurrent_http_audit import audit

ROOT = Path(__file__).resolve().parents[1]


class ConcurrentHTTPContractTests(unittest.TestCase):
    def test_protocol_matches_fixed_workload_and_existing_resource_gates(self):
        protocol = json.loads((ROOT / 'experiments/pi_generation_concurrent_http_protocol.json').read_bytes())
        previous = json.loads((ROOT / 'experiments/pi_generation_http_protocol.json').read_bytes())
        validate_workload(protocol['workload'])
        for key in ('suite_wall_seconds', 'process_wall_seconds', 'condition_seconds', 'node_max_old_space_mib',
                    'polled_process_private_bytes_ceiling', 'server_private_bytes_ceiling',
                    'output_bytes_ceiling', 'min_free_disk_bytes', 'poll_seconds'):
            self.assertEqual(protocol[key], previous[key])
        self.assertEqual(protocol['workload']['total_admission_calls'], 12 + 6 + 6 + 4)

    def test_extra_missing_wrong_or_boolean_workload_fields_are_rejected(self):
        for kind in ('extra', 'missing', 'wrong', 'boolean'):
            with self.subTest(kind=kind):
                workload = copy.deepcopy(WORKLOAD)
                if kind == 'extra': workload['unregistered'] = 1
                if kind == 'missing': del workload['concurrent_rounds']
                if kind == 'wrong': workload['concurrent_rounds'] = 7
                if kind == 'boolean': workload['suites_permitted' if 'suites_permitted' in workload else 'final_active'] = False
                with self.assertRaises(AssertionError): validate_workload(workload)

    def test_all_new_execution_and_acceptance_paths_are_frozen(self):
        for name in ('experiments/pi_concurrent_admission.mjs', 'scripts/pi_generation_concurrent_http_worker.mjs',
                     'experiments/pi_generation_concurrent_http_audit.py', 'scripts/run_pi_generation_concurrent_http.py'):
            self.assertIn(name, MANDATORY_SOURCES)
            self.assertTrue((ROOT / name).is_file())

    def test_previously_accepted_serial_evidence_cannot_pass_concurrent_acceptance(self):
        with self.assertRaises(AssertionError):
            audit(ROOT / 'results/pi-generation-http/raw')


if __name__ == '__main__':
    unittest.main()
