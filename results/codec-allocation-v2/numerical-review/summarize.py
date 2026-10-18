"""Post-outcome descriptive arithmetic over saved JSON only; stdlib only.

Does not import producer, frozen auditor, Torch, NumPy or upstream modules.
This post-outcome review tool is not part of the frozen experiment implementation.
"""
import argparse
import collections
import datetime
import hashlib
import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
ACTUAL = WORKSPACE / 'results/codec-allocation-v2'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=pathlib.Path, help='Optional new full-summary JSON path; existing files are never overwritten. Without this option, only a compact receipt is printed.')
parser.add_argument('--expected-summary', type=pathlib.Path, help='Optional saved summary to compare; only the review timestamp is excluded.')
args = parser.parse_args()
INPUTS, CHECKS = [], []

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read(path):
    data = path.read_bytes()
    INPUTS.append({'path': path.relative_to(WORKSPACE).as_posix(), 'sha256': sha(data), 'bytes': len(data)})
    return json.loads(data)

def check(name, passed):
    CHECKS.append({'name': name, 'passed': bool(passed)})
    if not passed:
        raise ValueError(name)

def callback_summary(marker, allocations, bindings):
    start, end, tid = marker['start_ns'], marker['end_ns'], marker['start_tid']
    output_ids = {b['allocation'] for b in bindings if b['marker_id'] == marker['id'] and b['at'] == 'exit' and b['allocation'] is not None}
    created = [a for a in allocations if start < a['created_ns'] < end and a['create_tid'] == tid]
    temporary = [a for a in created if a['id'] not in output_ids and a['destroyed_ns'] is not None and a['destroyed_ns'] < end and a['destroy_tid'] == tid]
    points = collections.defaultdict(int)
    for a in temporary:
        points[a['created_ns']] += a['bytes']
        points[a['destroyed_ns']] -= a['bytes']
    live, peak = 0, 0
    for stamp in sorted(points):
        live += points[stamp]
        peak = max(peak, live)
    return {'id': marker['id'], 'kind': marker['kind'], 'allocation_events_created': len(created),
            'requested_bytes_created': sum(a['bytes'] for a in created), 'temporary_allocation_count': len(temporary),
            'temporary_requested_live_max_bytes': peak, 'returned_allocation_ids': sorted(output_ids)}

def ratio_group(name, pair_ids, operations):
    fields = ['forward_loss_wall_seconds', 'backward_wall_seconds', 'forward_plus_backward_wall_seconds']
    rows = []
    for numerator, denominator in pair_ids:
        rows.append({'numerator': numerator, 'denominator': denominator,
                     'ratios': {field: operations[numerator][field] / operations[denominator][field] for field in fields}})
    return {'name': name, 'pairs': rows,
            'geometric_means': {field: math.exp(sum(math.log(row['ratios'][field]) for row in rows) / len(rows)) for field in fields},
            'descriptive_only': True, 'paired_observations': len(rows)}

report = read(ACTUAL / 'report.json')
protocol = read(WORKSPACE / 'fixtures/codec-allocation-v2/protocol.json')
check('one suite / zero retries / producer success', report['passed'] and report['suite_launches'] == 1 and report['retries'] == 0)
check('eight exact predeclared case order', [c['spec'] for c in report['cases']] == protocol['cases_in_order'])
operations, cases, on = {}, [], []
for case in report['cases']:
    name = case['id']
    operation = read(ACTUAL / name / 'operation.json')
    operations[name] = operation
    op_bytes = (ACTUAL / name / 'operation.json').read_bytes()
    check(name + ': operation custody', sha(op_bytes) == case['stages']['poststudy']['operation_sha256'])
    check(name + ': forward/backward sum', operation['forward_plus_backward_wall_seconds'] == operation['forward_loss_wall_seconds'] + operation['backward_wall_seconds'])
    check(name + ': exact1forward1backward zero optimizer', (operation['forward_calls'], operation['backward_calls'], operation['optimizer_updates']) == (1, 1, 0))
    cases.append({'id': name, 'method': operation['spec']['method'], 'observer_enabled': operation['observer_enabled'],
        'forward_loss_wall_seconds': operation['forward_loss_wall_seconds'], 'backward_wall_seconds': operation['backward_wall_seconds'],
        'study_operator_sum_wall_seconds': operation['forward_plus_backward_wall_seconds'],
        'forward_start_to_backward_completed_interval_seconds': operation['backward_completed_perf_counter'] - operation['forward_started_perf_counter'],
        'callback_pack_codec_body_wall_seconds': operation['callback_pack_wall_seconds'],
        'callback_unpack_codec_body_wall_seconds': operation['callback_unpack_wall_seconds'],
        'loss': operation['loss'], 'gradient_sha256': operation['gradient']['sha256'],
        'no_optimizer_update_or_holdout_quality': True})
    if not operation['observer_enabled']:
        check(name + ': OFF callback and trace results null', operation['trace_sha256'] is None and operation['callback_pack_wall_seconds'] is None and operation['callback_unpack_wall_seconds'] is None)
        continue
    trace = read(ACTUAL / name / 'allocation-trace.json')
    check(name + ': trace custody', sha((ACTUAL / name / 'allocation-trace.json').read_bytes()) == operation['trace_sha256'])
    check(name + ': saved measurement gates all true', trace['measurement_valid'] and all(trace['measurement_gates'].values()))
    # Independently rebuild allocator epochs from raw events; no original reducer imported.
    events = trace['events']
    ordered = sorted(events, key=lambda x: (x['t_ns'], x['ordinal']))
    check(name + ': no same-pointer same-time ambiguity', len({(e['ptr'], e['t_ns']) for e in events}) == len(events))
    allocations, active, unknown_frees = [], {}, []
    for event in ordered:
        ptr = event['ptr']
        if event['bytes'] > 0:
            check(name + ': raw positive pointer unoccupied ' + str(event['ordinal']), ptr not in active)
            row = {'id': 'allocation-' + str(len(allocations)), 'ptr': ptr, 'bytes': event['bytes'],
                   'created_ns': event['t_ns'], 'created_ordinal': event['ordinal'], 'create_tid': event['start_tid'],
                   'allocation_id': event['allocation_id'], 'destroyed_ns': None, 'destroyed_ordinal': None,
                   'destroy_tid': None, 'ambiguous': False}
            allocations.append(row)
            active[ptr] = row
        else:
            row = active.pop(ptr, None)
            if row is None:
                unknown_frees.append(event)
            else:
                check(name + ': exact raw free size ' + str(event['ordinal']), -event['bytes'] == row['bytes'])
                row.update(destroyed_ns=event['t_ns'], destroyed_ordinal=event['ordinal'], destroy_tid=event['start_tid'])
    check(name + ': independently rebuilt allocation epochs equal saved reducer', allocations == trace['reduced']['allocations'])
    check(name + ': independently identified unknown frees', unknown_frees == trace['reduced']['unknown_preexisting_frees'])
    amap = {a['id']: a for a in allocations}
    byptr = collections.defaultdict(list)
    for a in allocations:
        byptr[a['ptr']].append(a)
    markers = {m['id']: m for m in trace['markers']}
    bindings = []
    for ref in trace['references']:
        marker = markers[ref['marker_id']]
        stamp = marker['start_ns'] if ref['at'] == 'entry' else marker['end_ns']
        candidates = [a for a in byptr[ref['ptr']] if a['bytes'] == ref['nbytes'] and a['created_ns'] < stamp and (a['destroyed_ns'] is None or stamp < a['destroyed_ns'])]
        bindings.append({**ref, 'allocation': candidates[0]['id'] if len(candidates) == 1 else None,
                         'candidate_count': len(candidates), 'status': 'bound' if len(candidates) == 1 else 'unknown'})
    check(name + ': independent bindings equal saved', bindings == trace['reduced']['bindings'])
    summaries = [callback_summary(m, allocations, bindings) for m in trace['markers'] if m['kind'] in ('pack', 'unpack')]
    saved = {s['id']: s for s in trace['reduced']['callback_summaries']}
    for s in summaries:
        check(name + ': independent callback arithmetic ' + s['id'], all(saved[s['id']][key] == value for key, value in s.items()) and saved[s['id']]['valid'])
    callbacks = {c['id']: c for c in trace['callbacks']}
    check(name + ': callback wall sums', sum(c['codec_wall_seconds'] for c in trace['callbacks'] if c['kind'] == 'pack') == operation['callback_pack_wall_seconds'] and sum(c['codec_wall_seconds'] for c in trace['callbacks'] if c['kind'] == 'unpack') == operation['callback_unpack_wall_seconds'])
    def group_stats(label, selected):
        output_ids = {a for s in selected for a in s['returned_allocation_ids']}
        created_output_ids = {key for s in selected for key in s['returned_allocation_ids']
                              if markers[s['id']]['start_ns'] < amap[key]['created_ns'] < markers[s['id']]['end_ns'] and amap[key]['create_tid'] == markers[s['id']]['start_tid']}
        return {'label': label, 'callbacks': len(selected),
                'created_allocation_events_sum': sum(s['allocation_events_created'] for s in selected),
                'created_requested_bytes_sum': sum(s['requested_bytes_created'] for s in selected),
                'maximum_single_callback_created_requested_bytes': max((s['requested_bytes_created'] for s in selected), default=0),
                'temporary_allocations_sum': sum(s['temporary_allocation_count'] for s in selected),
                'maximum_single_callback_temporary_requested_live_bytes': max((s['temporary_requested_live_max_bytes'] for s in selected), default=0),
                'returned_distinct_allocation_count': len(output_ids),
                'returned_distinct_requested_bytes_union': sum(amap[a]['bytes'] for a in output_ids),
                'returned_created_strictly_in_own_callback_count': len(created_output_ids),
                'returned_created_strictly_in_own_callback_requested_bytes_union': sum(amap[a]['bytes'] for a in created_output_ids)}
    callback_groups = []
    for label, selected in [
        ('all_callbacks', summaries), ('all_pack', [s for s in summaries if s['kind'] == 'pack']),
        ('all_unpack', [s for s in summaries if s['kind'] == 'unpack']),
        ('outer_eligible_pack', [s for s in summaries if callbacks[s['id']]['scope'] == 'outer' and s['kind'] == 'pack' and callbacks[s['id']]['eligible']]),
        ('outer_compressed_unpack', [s for s in summaries if callbacks[s['id']]['scope'] == 'outer' and s['kind'] == 'unpack' and callbacks[s['id']]['compressed']]),
    ]:
        callback_groups.append(group_stats(label, selected))
    # Recompute each held owner boundary against strict raw allocator intervals.
    bystorage = collections.defaultdict(set)
    for b in bindings:
        if b['allocation'] is not None:
            bystorage[b['storage_id']].add(b['allocation'])
    boundary_rows, boundaries = {}, []
    for boundary in trace['boundaries']:
        marker = markers[boundary['marker_id']]
        unique_live = set()
        for row in boundary['rows']:
            ids = bystorage[row['storage_id']]
            check(name + ': owner unique binding ' + boundary['marker_id'] + ':' + row['storage_id'], len(ids) == 1)
            a = amap[next(iter(ids))]
            alive = a['created_ns'] < marker['start_ns'] and (a['destroyed_ns'] is None or a['destroyed_ns'] > marker['end_ns'])
            check(name + ': owner/allocator agreement ' + boundary['marker_id'] + ':' + row['storage_id'], alive == (not row['expired']) and row['agreement'] is True and row['allocator_status'] == ('live' if alive else 'not_live'))
            if alive:
                unique_live.add(a['id'])
        selected = sum(amap[a]['bytes'] for a in unique_live)
        check(name + ': independent selected subset ' + boundary['marker_id'], selected == boundary['selected_bound_subset_requested_bytes'])
        boundary_rows[boundary['marker_id']] = {row['storage_id']: row for row in boundary['rows']}
        boundaries.append({key: value for key, value in boundary.items() if key != 'rows'})
    outer_pack = [c for c in trace['callbacks'] if c['scope'] == 'outer' and c['kind'] == 'pack' and c['eligible']]
    source_ids = {c['source_storage'] for c in outer_pack}
    payload_ids = {s for c in outer_pack for s in c['returned_storages']}
    decoded_ids = {b['storage_id'] for b in bindings if b['role'] == 'decoded' and callbacks[b['marker_id']]['scope'] == 'outer'}
    code_ids = {c['returned_storages'][0] for c in outer_pack if c['compressed']}
    scale_ids = {c['returned_storages'][1] for c in outer_pack if c['compressed']}
    def role_summary(label, storage_ids):
        refs = [b for b in bindings if b['storage_id'] in storage_ids]
        alloc_ids = {a for storage in storage_ids for a in bystorage[storage]}
        rows = []
        for boundary in trace['boundaries']:
            owners = boundary_rows[boundary['marker_id']]
            present = [owners[s] for s in storage_ids if s in owners]
            live = {row['allocation'] for row in present if row['allocator_status'] == 'live'}
            rows.append({'boundary': boundary['marker_id'], 'registered_storage_count': len(present),
                         'not_yet_registered_storage_count': len(storage_ids) - len(present),
                         'strong_owner_alive_count': sum(not row['expired'] for row in present),
                         'strong_owner_expired_count': sum(row['expired'] for row in present),
                         'live_distinct_allocation_count': len(live), 'live_requested_bytes_union': sum(amap[a]['bytes'] for a in live)})
        details = []
        for storage in sorted(storage_ids, key=lambda x: int(x.split('-')[1])):
            check(name + ': outer role unique lifetime ' + storage, len(bystorage[storage]) == 1)
            a = amap[next(iter(bystorage[storage]))]
            details.append({'storage_id': storage, 'allocation_id': a['id'], 'requested_bytes': a['bytes'],
                            'created_ns': a['created_ns'], 'destroyed_ns': a['destroyed_ns'],
                            'observed_allocator_lifetime_ns': None if a['destroyed_ns'] is None else a['destroyed_ns'] - a['created_ns'],
                            'right_censored': a['destroyed_ns'] is None,
                            'registered_roles': next(s['roles'] for s in trace['storage_records'] if s['storage_id'] == storage)})
        return {'label': label, 'distinct_storage_count': len(storage_ids), 'distinct_allocation_count': len(alloc_ids),
                'requested_bytes_union': sum(amap[a]['bytes'] for a in alloc_ids),
                'right_censored_allocation_count': sum(amap[a]['destroyed_ns'] is None for a in alloc_ids),
                'boundaries': rows, 'all_storage_lifetimes': details}
    roles = [role_summary(label, ids) for label, ids in [
        ('outer_eligible_source', source_ids), ('outer_eligible_returned_payload', payload_ids),
        ('outer_returned_codes_tuple_element0', code_ids), ('outer_returned_scales_tuple_element1', scale_ids),
        ('outer_decoded_returned_float', decoded_ids)]]
    positive = [e for e in events if e['bytes'] > 0]
    negative = [e for e in events if e['bytes'] < 0]
    on.append({'id': name, 'method': operation['spec']['method'],
               'trace_window': 'Profiler starts before model preparation/load and includes held postload, forward/CE/backward, held owner boundaries, gradient validation and zero_grad; not training-only allocation trace.',
               'raw_event_count': len(events), 'positive_allocation_event_count': len(positive), 'negative_free_event_count': len(negative),
               'positive_requested_bytes_total': sum(e['bytes'] for e in positive), 'negative_freed_requested_bytes_total': sum(-e['bytes'] for e in negative),
               'maximum_single_allocation_requested_bytes': max(e['bytes'] for e in positive),
               'raw_allocation_id_missing_count': sum(e['allocation_id'] is None for e in events),
               'unknown_preexisting_free_count': len(unknown_frees), 'reduction_problem_count': len(trace['reduced']['problems']),
               'right_censored_allocation_count': sum(a['destroyed_ns'] is None for a in allocations),
               'right_censored_requested_bytes_total': sum(a['bytes'] for a in allocations if a['destroyed_ns'] is None),
               'callback_groups': callback_groups, 'held_boundaries': boundaries,
               'outer_storage_roles': roles,
               'source_payload_storage_overlap_count': len(source_ids & payload_ids),
               'roles_overlap_warning': 'Role totals can alias; never add group byte totals. Dense returned payload is the same backing as eligible source. Codes/scales are children of combined payload group.'})

ratios = [ratio_group('same-method observer ON/OFF dense', [('05_on_dense', '01_off_dense'), ('08_on_dense', '04_off_dense')], operations),
          ratio_group('same-method observer ON/OFF int8', [('06_on_int8', '02_off_int8'), ('07_on_int8', '03_off_int8')], operations),
          ratio_group('observer OFF int8/dense', [('02_off_int8', '01_off_dense'), ('03_off_int8', '04_off_dense')], operations)]
summary = {'schema_version': 1, 'summarized_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
           'post_outcome_review_not_frozen_experiment_implementation': True,
           'scope': 'Post-outcome descriptive arithmetic and independent raw allocator/callback/owner recomputation; saved JSON only, no producer/auditor/ML imports, network or workloads.',
           'result_payload_sha256': report['result_sha256'], 'producer_suite_wall_seconds': report['wall_seconds'],
           'cases': cases, 'descriptive_ratios': ratios, 'observer_on_raw_allocation_and_lifetime': on,
           'scientific_status': 'No optimizer update, heldout evaluation, training-quality, OS capacity/peak, GPU peak, causal slowdown/saving or total observer-cost result.',
           'limitations': protocol['limitations'] + [
               'Both ON observations occur after all OFF observations in one fixed sequence; two per cell, no randomization, inferential statistics or causal attribution.',
               'Forward+backward is the sum of two operator timers. It excludes the between-operator held owner snapshot and post-backward validation/cleanup; the wider interval is separately shown.',
               'ON callback timers enclose codec body only, excluding registry.add and record_function setup/teardown. Callback sums are not full instrumentation or profiler cost.',
               'Requested-byte totals sum repeated allocation requests, not simultaneously resident memory. Temporary callback peak excludes identified returned backing and is bounded to same-thread callback lifetime.',
               'Boundary selected subset contains overlapping saved-source/payload/decoded roles including exact/parameter backing; it excludes unregistered buffers and is not all saved activations or whole process.',
               'Decoded storage is not yet registered at the after-forward boundary; zero observed live decoded bytes there is not an expiry observation.',
               'Owner expiry and profiler free concern backing lifetime only, not pages returned to OS. Instrumentation changes lifetimes and microstudy timing.'],
           'inputs': INPUTS, 'independent_checks': {'passed': sum(c['passed'] for c in CHECKS), 'total': len(CHECKS), 'all_passed': all(c['passed'] for c in CHECKS)},
           'checks': CHECKS}
def stable_payload(value):
    return {key: item for key, item in value.items() if key != 'summarized_at'}

expected_matches = None
if args.expected_summary is not None:
    expected = json.loads(args.expected_summary.read_bytes())
    expected_matches = stable_payload(summary) == stable_payload(expected)
    if not expected_matches:
        raise ValueError('recomputed summary differs from expected saved summary beyond review timestamp')
encoded = (json.dumps(summary, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
output_label = None
if args.output is not None:
    # Exclusive creation preserves both the experiment's raw evidence and prior reviews.
    with args.output.open('xb') as stream:
        stream.write(encoded)
    try:
        output_label = args.output.resolve().relative_to(WORKSPACE).as_posix()
    except ValueError:
        output_label = '<external-output>/' + args.output.name
payload_sha256 = sha(json.dumps(stable_payload(summary), sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
print(json.dumps({'output': output_label, 'sha256': sha(encoded), 'stable_payload_sha256': payload_sha256,
                  'post_outcome_review_not_frozen_experiment_implementation': True,
                  'expected_summary_matches_excluding_review_timestamp': expected_matches,
                  'checks': summary['independent_checks'],
                  'study_ratio_gms': [r['geometric_means']['forward_plus_backward_wall_seconds'] for r in ratios]}, indent=2))
