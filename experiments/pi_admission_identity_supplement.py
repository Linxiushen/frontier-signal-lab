"""Post-outcome saved-byte checks; not part of the preregistered acceptance.

The original frozen admission auditor runs unchanged before this supplement.
No native runtime, provider, model, database or network is opened here.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

from experiments.pi_generation_admission_audit import audit as frozen_audit


def load_evidence(directory):
    directory = Path(directory)

    def read(name):
        return json.loads((directory / name).read_bytes())

    return {
        'identities': read('identities.json'),
        'events': [json.loads(line) for stage in range(3) for line in
                   (directory / f'stage{stage}.jsonl').read_text(encoding='utf-8-sig').splitlines()],
        'endpoints': {(service, stage): read(f'service{service}-stage{stage}-endpoint.json')
                      for service in range(2) for stage in range(3)},
        'snapshots': {stage: read(f'stage{stage}-snapshot.json') for stage in (0, 1)},
    }


def validate_evidence(evidence):
    """Check supplementary identities on parsed saved evidence, without mutation."""
    admitted = [r for r in evidence['identities']['requests'] if r['status'] == 'admit']
    by_key = {(r['service'], r['key']): r for r in admitted}
    assert len(admitted) == len(by_key) == 20, 'Exact admitted request identities'
    events = evidence['events']
    enters = [e for e in events if e['type'] == 'tool-enter']
    effects = [e for e in events if e['type'] == 'tool-effect']
    assert len(enters) == 26, 'Exact global tool-enter count'
    assert {(e['service'], e['key']) for e in enters} == set(by_key), 'Exhaustive tool-enter keys'
    expected_effect_keys = {key for key, r in by_key.items() if r['intent'] != 'pre-abort'}
    assert len(effects) == 24, 'Exact global tool-effect count'
    assert {(e['service'], e['key']) for e in effects} == expected_effect_keys, 'Exhaustive tool-effect keys'

    for key, request in by_key.items():
        endpoint = evidence['endpoints'][request['service'], 2]
        call_id = 'call-' + hashlib.sha256(request['key'].encode()).hexdigest()[:24]
        native = [t for t in endpoint['tasks'] if t['kind'] == 'pi.tool'
                  and t['conversationId'] == request['conversation']
                  and t['input']['callId'] == call_id]
        assert len(native) == 1, 'One exact native tool per request'
        own_enters = [e for e in enters if (e['service'], e['key']) == key]
        own_effects = [e for e in effects if (e['service'], e['key']) == key]
        stage = request['stage']
        stages = ([stage, stage + 1] if request['intent'] in ('recover', 'submit-gap')
                  else [stage + int(request['intent'] == 'reserve-gap')])
        assert [e['stage'] for e in own_enters] == stages, 'Exact tool-enter replay stages'
        assert [e['stage'] for e in own_effects] == ([] if request['intent'] == 'pre-abort' else stages), 'Exact tool-effect replay stages'
        assert all(e['taskId'] == native[0]['id'] for e in own_enters + own_effects), 'Exact native effect task identity'
        assert all(e['conversation'] == request['conversation'] and e['callId'] == call_id
                   for e in own_enters), 'Exact tool-enter conversation and call identity'

    phases = {'recover': 'after-link', 'reserve-gap': 'after-reserve', 'submit-gap': 'after-submit'}
    expected_faults = Counter((r['stage'], r['service'], r['key'], phases[r['intent']])
                              for r in admitted if r['intent'] in phases)
    actual_faults = Counter((e['stage'], e['service'], e['key'], e['phase'])
                            for e in events if e['type'] == 'admission-gap-held')
    assert sum(expected_faults.values()) == 8 and actual_faults == expected_faults, 'Exact admission fault identities'

    entry_counts = {}
    for service in range(2):
        entries = evidence['endpoints'][service, 2]['entries']
        assert len({e['id'] for e in entries}) == len(entries), 'Unique final entry identities'
        kinds = Counter(e['kind'] for e in entries)
        assert kinds['pi.user'] == kinds['pi.assistant'] == kinds['pi.tool-result'] == 10, 'Exact final entry counts'
        assert set(kinds) <= {'pi.user', 'pi.assistant', 'pi.tool-result', 'pi.system'}, 'Allowed final entry kinds'
        entry_counts[str(service)] = dict(kinds)

    for stage in (0, 1):
        snapshot = evidence['snapshots'][stage]
        expected_held = {key for key, r in by_key.items() if r['stage'] == stage and r['intent'] in phases}
        held = snapshot['held']
        assert len(held) == 4 and {(r['service'], r['key']) for r in held} == expected_held, 'Exact held reservation inventory'
        for request in held:
            canonical = by_key[request['service'], request['key']]
            assert all(request[k] == canonical[k] for k in
                       ('service', 'key', 'conversation', 'requestId', 'payload', 'version', 'intent', 'stage', 'status')), 'Canonical held reservation identity'
            assert 'terminal' not in request and request['heldPhase'] == phases[request['intent']], 'Exact pending admission phase'
            if request['intent'] == 'reserve-gap':
                assert 'submissionId' not in request, 'Host-only reservation has no native ID'
            else:
                assert request['submissionId'] == canonical['submissionId'], 'Canonical held native submission'

    return {
        'status': 'passed', 'review_timing': 'post-outcome', 'preregistered': False,
        'scope': 'Supplementary saved-byte identity checks; original frozen acceptance is unchanged.',
        'native_executions': 0, 'scientific_experiments': 0,
        'checks': {
            'exhaustive_tool_enter_keys_and_count': 26,
            'exhaustive_tool_effect_keys_and_count': 24,
            'requests_with_exact_tool_and_effect_identity_and_replay_stages': 20,
            'exact_fault_stage_service_key_phase_tuples': 8,
            'service0_exact_final_entry_counts': entry_counts['0'],
            'service1_exact_final_entry_counts': entry_counts['1'],
            'canonical_held_reservations': 8,
        },
    }


def audit(directory):
    """Run the unchanged frozen auditor, then the separate post-outcome checks."""
    frozen_audit(directory)
    result = validate_evidence(load_evidence(directory))
    result['original_frozen_audit'] = 'passed'
    return result
