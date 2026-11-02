import copy
import unittest

from experiments.pi_generation_http_audit import expected_receipt, validate_attempts
from scripts.check_pi_generation_http import MANDATORY_SOURCES, validate_freeze


def saved_attempts():
    # Independent fixed observation transcript: two remote denials, two cancels,
    # two lost replies recovered by read, and six ordinary commits.
    rows = []
    requests = []
    def case(key, intent, observations):
        requests.append({'key': key, 'intent': intent})
        for method, status in observations:
            rows.append([len(rows) + 1, method, key, status])
    for key in ('a', 'b'):
        case(key, 'remote-deny', [('GET', 404), ('POST', 403)])
    for key in ('c', 'd'):
        case(key, 'pre-cancel', [('GET', 404)])
    for key in ('e', 'f'):
        case(key, 'post-cancel', [('GET', 404), ('POST', 201), ('GET', 200), ('POST', 200), ('POST', 409)])
    for key in ('g', 'h', 'i', 'j', 'k', 'l'):
        case(key, 'commit', [('GET', 404), ('POST', 201)])
    return requests, rows


class HttpAuditTests(unittest.TestCase):
    def test_lost_reply_read_and_duplicate_transport_are_distinct_from_new_mutation(self):
        requests, rows = saved_attempts()
        validate_attempts(requests, rows)
        changed = copy.deepcopy(rows)
        next(row for row in changed if row[2] == 'e' and row[3] == 200 and row[1] == 'POST')[3] = 201
        with self.assertRaises(AssertionError):
            validate_attempts(requests, changed)

    def test_global_status_counts_cannot_hide_cross_request_effect_swap(self):
        requests, rows = saved_attempts()
        # Preserve aggregate counts and sequence, but transfer denied mutation to
        # a cancelled request: exact per-identity audit must reject it.
        changed = copy.deepcopy(rows)
        changed[1][2] = 'c'
        with self.assertRaises(AssertionError):
            validate_attempts(requests, changed)

    def test_missing_or_duplicate_attempt_sequence_rejected(self):
        requests, rows = saved_attempts()
        for changed in (rows[:-1], [rows[0], *rows[0:-1]]):
            with self.assertRaises(AssertionError):
                validate_attempts(requests, changed)

    def test_receipt_binds_original_payload_version_conversation_and_key(self):
        r = {'key': '2:r', 'payload': 'abc', 'version': 7, 'conversation': 2, 'service': 1}
        receipt = expected_receipt(r)
        self.assertEqual(receipt['fingerprint'], 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
        self.assertEqual({k: receipt[k] for k in r if k != 'service'}, {k: v for k, v in r.items() if k != 'service'})
        self.assertEqual(receipt['scope'], 'service1')
        self.assertEqual(receipt['count'], 1)

    def test_prior_fixture_cannot_authorize_new_transport_execution(self):
        from pathlib import Path
        import json
        root = Path(__file__).resolve().parents[1]
        old = json.loads((root / 'fixtures/pi-generation-conflict/implementation.json').read_bytes())
        self.assertNotEqual(set(old['source_sha256']), MANDATORY_SOURCES)
        with self.assertRaises(AssertionError):
            validate_freeze(root, old)


if __name__ == '__main__':
    unittest.main()
