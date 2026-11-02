"""Additional saved-byte controls for concurrent admission into the native caller."""
from collections import Counter
from pathlib import Path
import json
import math
from experiments.pi_generation_http_audit import audit as base_audit


def audit(directory):
    d = Path(directory)
    result = base_audit(d)
    events = [json.loads(line) for stage in range(3) for line in (d / f'stage{stage}.jsonl').read_text(encoding='utf-8-sig').splitlines()]
    ids = json.loads((d / 'identities.json').read_bytes())
    by_key = {r['key']: r for r in ids['requests'] if r['intent'] != 'overload'}
    rounds = {(stage, service): f'stage{stage}-service{service}' for stage in range(3) for service in range(2)}
    for (stage, service), name in rounds.items():
        own = [e for e in events if e.get('round') == name]
        assert all(e['stage'] == stage and e['service'] == service for e in own)
        types = [e['type'] for e in own]
        assert types == ['concurrent-admission-open', 'concurrent-reserve-arrival', 'concurrent-reserve-arrival',
                         'concurrent-reserve-arrival', 'concurrent-reserve-release', 'concurrent-admission-close',
                         'concurrent-content-conflict']
        opened, closed = own[0], own[-2]
        assert opened['calls'] == 3 and len(opened['keys']) == 3
        first, second, retry = opened['keys']
        assert first == retry and first != second
        assert {first, second} <= set(by_key)
        assert all(by_key[k]['stage'] == stage and by_key[k]['service'] == service for k in (first, second))
        assert [e['arrival'] for e in own if e['type'] == 'concurrent-reserve-arrival'] == [1, 2, 3]
        assert Counter(e['key'] for e in own if e['type'] == 'concurrent-reserve-arrival') == Counter(opened['keys'])
        assert own[4]['arrivals'] == 3
        assert closed['keys'] == opened['keys'] and math.isfinite(closed['elapsed_ms']) and closed['elapsed_ms'] >= 0
        values = closed['results']
        assert len(values) == 3
        assert sorted((values[0]['status'], values[2]['status'])) == ['admit', 'duplicate']
        assert values[1]['status'] == 'admit'
        for key, value in zip(opened['keys'], values):
            assert value['key'] == key and value['submissionId'] == by_key[key]['submissionId']
        conflict = own[-1]
        assert conflict['key'] == first and conflict['changed_payload'] == 'changed-' + by_key[first]['payload']
        assert conflict['result'] == {'status': 'conflict', 'key': first}
        # Bind caller outcomes to actual service admission events, not just wrapper summaries.
        admissions = [e for e in events if e['stage'] == stage and e['service'] == service and e['type'] == 'admission']
        expected = Counter((k, v['status'], v.get('submissionId')) for k, v in zip(opened['keys'], values))
        expected[(first, 'conflict', None)] += 1
        for r in ids['requests']:
            if r['stage'] == stage and r['service'] == service and r['intent'] == 'overload':
                expected[(r['key'], 'overloaded', None)] += 1
        assert Counter((e['key'], e['status'], e.get('submissionId')) for e in admissions) == expected
    assert len([e for e in events if e['type'] == 'admission']) == 28
    assert len([e for e in events if e['type'] == 'concurrent-admission-open']) == 6
    assert len([e for e in events if e['type'] == 'concurrent-reserve-arrival']) == 18
    assert len([e for e in events if e['type'] == 'concurrent-content-conflict']) == 6
    return {**result, 'total_admission_calls': 28, 'concurrent_rounds': 6,
            'concurrent_exact_retries': 6, 'changed_content_conflicts': 6, 'callers_per_round': 3}
