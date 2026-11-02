"""Read immutable JSON/JSONL/source bytes only; do not call an auditor or runtime."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import hashlib
import json

ROOT = Path(__file__).resolve().parents[4]
RUN = ROOT / 'reports/runs/20261102T170820Z'
RAW = RUN / 'h2-native-concurrent-http'
OUT = Path(__file__).resolve().parent
started = datetime.now(timezone.utc).isoformat()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
digest = lambda v: hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
inventory = lambda root: {p.relative_to(root).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
                          for p in sorted(root.rglob('*')) if p.is_file()}
raw_before = inventory(RAW)
freeze_path = ROOT / 'fixtures/pi-generation-concurrent-http/implementation.json'
freeze_sha = sha(freeze_path)
freeze = json.loads(freeze_path.read_bytes())
source_groups = {}
for group in ('source_sha256', 'preserved_previous_source_sha256'):
    actual = {name: sha(ROOT / name) for name in freeze[group]}
    source_groups[group] = {'count': len(actual), 'all_exact': actual == freeze[group],
                            'actual_sha256': actual}
manifest_path = ROOT / freeze['runtime_manifest_path']
manifest = json.loads(manifest_path.read_bytes())
runtime_root = ROOT / freeze['runtime_directory']
runtime_actual = []
runtime_mismatches = []
for item in manifest['files']:
    path = runtime_root / item['path']
    current = {'path': item['path'], 'bytes': path.stat().st_size, 'sha256': sha(path)}
    runtime_actual.append(current)
    if current != item:
        runtime_mismatches.append({'expected': item, 'actual': current})
runtime_paths = {item['path'] for item in manifest['files']}
actual_runtime_paths = {p.relative_to(runtime_root).as_posix() for p in runtime_root.rglob('*') if p.is_file()}
runtime_extras = sorted(actual_runtime_paths - runtime_paths)
runtime_missing = sorted(runtime_paths - actual_runtime_paths)
module_mismatches = []
for item in freeze['python_runtime_modules']:
    if 'path' in item and sha(Path(item['path'])) != item['sha256']:
        module_mismatches.append(item['name'])
execution = json.loads((RAW / 'execution.json').read_bytes())
events = []
per_stage = []
for stage in range(3):
    stage_events = [dict(json.loads(line), _line=i + 1) for i, line in enumerate(
        (RAW / f'stage{stage}.jsonl').read_text(encoding='utf-8-sig').splitlines())]
    events.extend(stage_events)
    per_stage.append({'stage': stage, 'event_count': len(stage_events),
                      'types': dict(Counter(e['type'] for e in stage_events)),
                      'missing_service_types': dict(Counter(e['type'] for e in stage_events if 'service' not in e))})
ids = json.loads((RAW / 'identities.json').read_bytes())
rounds = []
for stage in range(3):
    for service in range(2):
        name = f'stage{stage}-service{service}'
        own = [e for e in events if e.get('round') == name]
        opened = next(e for e in own if e['type'] == 'concurrent-admission-open')
        closed = next(e for e in own if e['type'] == 'concurrent-admission-close')
        conflict = next(e for e in own if e['type'] == 'concurrent-content-conflict')
        values = closed['results']
        admissions = [e for e in events if e['type'] == 'admission' and e['stage'] == stage and e.get('service') == service]
        rounds.append({'round': name, 'stage': stage, 'service_from_round': service,
                       'event_types': [e['type'] for e in own],
                       'service_field_present': [e['type'] for e in own if 'service' in e],
                       'service_field_missing': [{'type': e['type'], 'line': e['_line']} for e in own if 'service' not in e],
                       'arrivals': [e['arrival'] for e in own if e['type'] == 'concurrent-reserve-arrival'],
                       'opened_keys': opened['keys'], 'closed_keys': closed['keys'],
                       'results': values, 'round_elapsed_ms_observed_only': closed['elapsed_ms'],
                       'retry_same_submissionId': values[0].get('submissionId') == values[2].get('submissionId'),
                       'conflict': {k:v for k,v in conflict.items() if k not in ('pid','monotonic_ms','epoch_ms')},
                       'actual_admission_counts': dict(Counter(e['status'] for e in admissions))})
audit_path = ROOT / 'experiments/pi_generation_concurrent_http_audit.py'
worker_path = ROOT / 'scripts/pi_generation_concurrent_http_worker.mjs'
def lines_matching(path, needles):
    return [{'line': i, 'text': line} for i, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1)
            if any(n in line for n in needles)]
first_failure = next(e for e in events if e.get('round') == 'stage0-service0' and 'service' not in e)
first_latent = next(e for e in events if e['stage'] == 0 and 'service' not in e)
process_summary = lambda items: [{k:v for k,v in p.items() if k not in ('memory_samples','argv')} for p in items]
raw_after = inventory(RAW)
frozen_sources_after_exact = all(sha(ROOT / p) == expected for group in
    ('source_sha256','preserved_previous_source_sha256') for p,expected in freeze[group].items())
receipt = {
    'started_at': started, 'completed_at': datetime.now(timezone.utc).isoformat(),
    'reviewer': '/root/radar_resume', 'status': 'failed_frozen_schema_integration_independent_diagnosis',
    'scientific_outcome': 'failed', 'original_execution_accepted': False,
    'acceptance_rescue': False, 'patched_audit_or_replay_executed': False,
    'scope': 'Static source and saved JSON/JSONL parsing plus byte hashes only. No project module imports, project auditor execution, native/HTTP/model execution, tests, source edits or retry.',
    'observed_failure': {'execution_status': execution['status'], 'error': execution['error'],
        'traceback_receipt': 'reports/runs/20261102T170820Z/h2-concurrent/original-audit-failure.stdout',
        'traceback_sha256': sha(OUT / 'original-audit-failure.stdout'),
        'primary': 'Auditor line18 requires service on every round event. Worker concurrent-content-conflict uses the top-level emit and omits service; top-level emit adds stage/pid/timestamps only. The first missing record is stage0.jsonl line22. All six such conflict records lack service.',
        'first_missing_round_event': first_failure,
        'latent': 'Auditor line43 admission list indexes e[service] before checking event type. Even with the first round-schema error repaired in a future separate freeze, the first stage0 remote-authority event lacks service and would raise. Safe type-first filtering or explicit heterogeneous schema handling is needed in a future revision.',
        'first_missing_heterogeneous_event': first_latent,
        'source_locations': {'auditor': lines_matching(audit_path, ("assert all(e['stage']", "admissions =")),
                             'worker': lines_matching(worker_path, ('const emit =', 'events.push(JSON.stringify', 'concurrent-content-conflict'))}},
    'review_gap': 'My preexecution passed_for_separate_freeze review missed the real conflict-event schema and unsafe heterogeneous filter. The frozen pure Python suite verifies rejection of old serial evidence, but has no positive real-emitter schema fixture; Node helper tests do not exercise the Python saved-byte auditor. Prior review receipt remains preserved as superseded for outcome validation.',
    'execution_counters': {k: execution[k] for k in ('scientific_suites','retries','model_loads','elapsed_seconds','authentication_elapsed_seconds','full_controller_elapsed_seconds')},
    'finite_saved_observations_only': {
        'not_acceptance': True, 'event_count': len(events), 'per_stage': per_stage, 'rounds': rounds,
        'actual_admission_statuses': dict(Counter(e['status'] for e in events if e['type'] == 'admission')),
        'six_round_conflicts_missing_service': len([e for e in events if e['type'] == 'concurrent-content-conflict' and 'service' not in e]),
        'identity_request_count': len(ids['requests']), 'identity_native_count': len(ids['native']),
        'identity_recovery_entries': len(ids['recovered']),
        'native_processes': process_summary(execution['processes']), 'effect_server_processes': process_summary(execution['servers']),
        'stage_pending': [json.loads((RAW / f'stage{s}-ready.json').read_bytes())['pending'] for s in range(3)],
        'stage_effect_counts': [len(json.loads((RAW / f'effect-server{s}-ready-snapshot.json').read_bytes())['effects']) for s in range(3)],
        'limits': 'One trusted owner, two native Sessions, before-reserve overlap; conflicts after each round closes. These saved counters do not validate the failed acceptance protocol, arbitrary concurrent owners/interleavings, general exactly-once, model/GPU/production behavior or a performance improvement.'},
    'preservation': {'freeze_path': freeze_path.relative_to(ROOT).as_posix(), 'freeze_sha256': freeze_sha,
        'freeze_unchanged_after': sha(freeze_path) == freeze_sha,
        'freeze_matches_execution': execution['freeze_sha256'] == freeze_sha,
        'source_groups': source_groups, 'all_frozen_sources_still_exact_after': frozen_sources_after_exact,
        'runtime_manifest_sha256': sha(manifest_path), 'runtime_manifest_matches_freeze': sha(manifest_path) == freeze['runtime_manifest_sha256'],
        'installed_runtime_file_count': len(runtime_actual), 'installed_runtime_inventory_sha256': digest(runtime_actual),
        'installed_runtime_mismatches': runtime_mismatches, 'installed_runtime_extras': runtime_extras,
        'installed_runtime_missing': runtime_missing,
        'node_binary_exact': sha(Path(freeze['node'])) == freeze['node_sha256'],
        'python_binary_exact': sha(Path(freeze['python'])) == freeze['python_sha256'],
        'python_runtime_module_mismatches': module_mismatches,
        'raw_files': len(raw_before), 'raw_inventory_before_sha256': digest(raw_before),
        'raw_inventory_after_sha256': digest(raw_after), 'raw_unchanged': raw_before == raw_after,
        'raw_artifacts': raw_before},
    'executions_by_reviewer': {'native_suites': 0, 'scientific_suites': 0, 'model_loads': 0,
                              'project_tests': 0, 'project_auditor_calls': 0},
    'tracked_or_shared_edits_by_reviewer': 0,
    'future_work_only': 'Preserve this failed freeze and all raw evidence; any emitter/auditor integration repair needs a separate revision with positive and mutated-schema pure controls and separate preregistration before another permitted scientific round.'}
target = OUT / 'postoutcome-independent-diagnosis.json'
with target.open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'path': target.relative_to(ROOT).as_posix(), 'sha256': sha(target),
                  'raw_files':len(raw_before), 'raw_unchanged':raw_before == raw_after,
                  'runtime_files':len(runtime_actual), 'runtime_mismatches':len(runtime_mismatches),
                  'frozen_sources_exact': frozen_sources_after_exact, 'outcome':'failed_not_rescued'}))
