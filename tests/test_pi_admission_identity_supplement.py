"""Saved evidence and mutation controls only; no native or scientific execution."""
import copy
from pathlib import Path
import unittest

from experiments.pi_admission_identity_supplement import load_evidence, validate_evidence
from scripts.check_pi_admission_identity_supplement import check

RAW = Path(__file__).resolve().parents[1] / 'results/pi-generation-admission/raw'


class AdmissionIdentitySupplementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = load_evidence(RAW)

    def evidence(self):
        return copy.deepcopy(self.saved)

    def reject(self, mutate, message):
        evidence = self.evidence()
        mutate(evidence)
        with self.assertRaisesRegex(AssertionError, message):
            validate_evidence(evidence)

    def test_archived_outcome_passes_both_audits_and_is_labeled_post_outcome(self):
        result = check()
        self.assertEqual(result, check(RAW))
        self.assertEqual(result['original_frozen_audit'], 'passed')
        self.assertEqual(result['review_timing'], 'post-outcome')
        self.assertFalse(result['preregistered'])
        self.assertEqual(result['native_executions'], 0)
        self.assertEqual(len(result['checks']), 7)

    def test_previously_accepted_nonexistent_effect_task_identity_is_rejected(self):
        def mutate(evidence):
            for event in evidence['events']:
                if event['type'] == 'tool-effect':
                    event['taskId'] = 0
        self.reject(mutate, 'Exact native effect task identity')

    def test_previously_accepted_extra_assistant_and_result_entries_are_rejected(self):
        for kind in ('pi.assistant', 'pi.tool-result'):
            def mutate(evidence):
                evidence['endpoints'][0, 2]['entries'].append({'id': -999, 'kind': kind})
            with self.subTest(kind=kind):
                self.reject(mutate, 'Exact final entry counts')

    def test_global_unknown_and_duplicate_tool_event_inventory_is_rejected(self):
        for kind in ('tool-enter', 'tool-effect'):
            def unknown(evidence):
                next(e for e in evidence['events'] if e['type'] == kind)['key'] = 'unknown'
            def duplicate(evidence):
                evidence['events'].append(copy.deepcopy(next(e for e in evidence['events'] if e['type'] == kind)))
            with self.subTest(kind=kind, mutation='unknown'):
                self.reject(unknown, 'Exhaustive tool-')
            with self.subTest(kind=kind, mutation='duplicate'):
                self.reject(duplicate, 'Exact global tool-')

    def test_missing_effect_and_same_count_duplicate_effect_are_rejected(self):
        def missing(evidence):
            evidence['events'].remove(next(e for e in evidence['events'] if e['type'] == 'tool-effect'))
        self.reject(missing, 'Exact global tool-effect count')
        def replace(evidence):
            indices = [i for i, e in enumerate(evidence['events']) if e['type'] == 'tool-effect']
            evidence['events'][indices[-1]] = copy.deepcopy(evidence['events'][indices[0]])
        self.reject(replace, 'Exhaustive tool-effect keys')

    def test_recovery_and_delayed_submission_stages_are_exact(self):
        for kind in ('tool-enter', 'tool-effect'):
            for intent in ('recover', 'submit-gap', 'reserve-gap'):
                def mutate(evidence):
                    request = next(r for r in evidence['identities']['requests'] if r['intent'] == intent)
                    event = next(e for e in evidence['events'] if e['type'] == kind and
                                 (e['service'], e['key']) == (request['service'], request['key']))
                    event['stage'] = (event['stage'] + 1) % 3
                with self.subTest(kind=kind, intent=intent):
                    self.reject(mutate, 'Exact tool-.* replay stages')

    def test_fault_phase_counts_cannot_hide_wrong_request_or_service(self):
        for field, value in (('key', 'unknown'), ('service', 4), ('stage', 2), ('phase', 'before-reserve')):
            def mutate(evidence):
                next(e for e in evidence['events'] if e['type'] == 'admission-gap-held')[field] = value
            with self.subTest(field=field):
                self.reject(mutate, 'Exact admission fault identities')

    def test_held_reservations_cannot_change_identity_or_pending_phase(self):
        for field, value in (('payload', 'changed'), ('conversation', -1), ('requestId', 'other'),
                             ('intent', 'commit'), ('heldPhase', 'after-submit'), ('terminal', {})):
            def mutate(evidence):
                evidence['snapshots'][0]['held'][0][field] = value
            with self.subTest(field=field):
                self.reject(mutate, 'Canonical held reservation identity|Exact pending admission phase')

    def test_held_inventory_and_gap_native_id_are_exact(self):
        def duplicate(evidence):
            held = evidence['snapshots'][0]['held']
            held[1] = copy.deepcopy(held[0])
        self.reject(duplicate, 'Exact held reservation inventory')
        def host_only_id(evidence):
            next(r for r in evidence['snapshots'][0]['held'] if r['intent'] == 'reserve-gap')['submissionId'] = 1
        self.reject(host_only_id, 'Host-only reservation has no native ID')
        def wrong_link(evidence):
            evidence['snapshots'][0]['held'][0]['submissionId'] = -1
        self.reject(wrong_link, 'Canonical held native submission')

    def test_extra_entry_kinds_and_duplicate_entry_ids_are_rejected(self):
        def extra_kind(evidence):
            evidence['endpoints'][0, 2]['entries'].append({'id': -999, 'kind': 'unowned'})
        self.reject(extra_kind, 'Allowed final entry kinds')
        def duplicate(evidence):
            entries = evidence['endpoints'][0, 2]['entries']
            entries[-1]['id'] = entries[0]['id']
        self.reject(duplicate, 'Unique final entry identities')

    def test_tool_event_call_and_conversation_cannot_be_reassigned(self):
        for field, value in (('callId', 'other'), ('conversation', -1), ('taskId', 0)):
            def mutate(evidence):
                next(e for e in evidence['events'] if e['type'] == 'tool-enter')[field] = value
            with self.subTest(field=field):
                self.reject(mutate, 'Exact native effect task identity|Exact tool-enter conversation and call identity')


if __name__ == '__main__':
    unittest.main()
