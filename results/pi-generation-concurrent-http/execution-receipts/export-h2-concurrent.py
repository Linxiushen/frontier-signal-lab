"""Export one failed frozen attempt and separately labelled saved observations; never rerun."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / 'reports/runs/20261102T170820Z'
sys.path.insert(0, str(ROOT))
from scripts.check_pi_generation_concurrent_http import check, MANDATORY_SOURCES


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def stamp():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def inventory(directory):
    return {p.relative_to(directory).as_posix(): sha(p)
            for p in directory.rglob('*') if p.is_file()}


source = RUN / 'h2-native-concurrent-http'
result = ROOT / 'results/pi-generation-concurrent-http'
freeze_path = ROOT / 'fixtures/pi-generation-concurrent-http/implementation.json'
freeze = load(freeze_path)
protocol = load(ROOT / 'experiments/pi_generation_concurrent_http_protocol.json')
# Check the terminal original outcome and all required inputs before creating output.
execution = load(source / 'execution.json')
outer = load(RUN / 'h2-native-CLI.receipt.json')
assert execution['status'] == 'failed' and execution.get('error') == "KeyError('service')"
assert execution['scientific_suites'] == 1 and execution['retries'] == execution['model_loads'] == 0
assert execution['freeze_sha256'] == sha(freeze_path)
assert outer['exit_code'] == 1 and outer['CLI_invocations'] == 1 and outer['retries'] == 0
assert outer['completed_at'] and outer['started_at']
for stream in ('stdout', 'stderr'):
    assert sha(RUN / f'h2-native-CLI.{stream}.log') == outer[f'{stream}_sha256']
assert set(freeze['source_sha256']) == MANDATORY_SOURCES
for mapping in (freeze['source_sha256'], freeze['preserved_previous_source_sha256']):
    for name, digest in mapping.items():
        assert sha(ROOT / name) == digest, name

receipt_paths = [RUN / 'h2-native-CLI.receipt.json', RUN / 'h2-native-CLI.stdout.log',
                 RUN / 'h2-native-CLI.stderr.log', RUN / 'scientific-reservation.json',
                 RUN / 'freeze-and-launch-h2.py', Path(__file__).resolve()]
receipt_hashes = {p: sha(p) for p in receipt_paths}
preparation = RUN / 'h2-concurrent'
preparation_paths = sorted(p for p in preparation.iterdir() if p.is_file())
preparation_hashes = {p: sha(p) for p in preparation_paths}
diagnosis = load(preparation / 'original-audit-failure-analysis.json')
assert diagnosis['original_execution_accepted'] is False and diagnosis['acceptance_rescue'] is False
saved_path = preparation / 'saved-observation.json'
saved_observation = load(saved_path)
assert saved_observation['status'] == 'saved_observation_completed'
assert saved_observation['execution_accepted'] is False
assert saved_observation['native_invocations'] == saved_observation['model_loads'] == 0
assert saved_observation['raw_unchanged'] and saved_observation['source_unchanged']
supplement_source = ROOT / 'experiments/pi_generation_concurrent_http_saved_observation.py'
assert sha(supplement_source) == saved_observation['source_sha256']
before = inventory(source)
assert len(before) == saved_observation['raw_files'] == 95
assert not result.exists()
result.mkdir()
raw = result / 'raw'
shutil.copytree(source, raw)
after = inventory(raw)
assert before == after == inventory(source)
rows = [{'path': name, 'bytes': (raw / name).stat().st_size, 'sha256': digest}
        for name, digest in sorted(after.items())]
save(result / 'raw-manifest.json', {'recorded_at': stamp(), 'files': rows,
     'total_bytes': sum(row['bytes'] for row in rows)})
receipts = result / 'execution-receipts'
receipts.mkdir()
(result / 'review').mkdir()
for path, expected in receipt_hashes.items():
    assert sha(path) == expected
    target = receipts / path.name
    target.write_bytes(path.read_bytes())
    assert sha(target) == sha(path) == expected
for path, expected in preparation_hashes.items():
    assert sha(path) == expected
    target = receipts / 'preparation' / path.name
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(path.read_bytes())
    assert sha(target) == sha(path) == expected
save(receipts / 'preparation-copy-manifest.json', {'recorded_at': stamp(),
     'scope': 'Preparation and post-outcome saved-byte diagnosis snapshot; neither overrides the failed frozen attempt.',
     'files': [{'path': f'preparation/{p.name}', 'sha256': digest}
               for p, digest in preparation_hashes.items()]})
save(receipts / 'raw-copy-verification.json', {'recorded_at': stamp(), 'files': len(before),
     'original_and_public_copy_equal': before == after, 'bytes': sum(row['bytes'] for row in rows),
     'scientific_reexecution': False})

events = []
parse_diagnostics = []
for stage in range(3):
    path = raw / f'stage{stage}.jsonl'
    if path.exists():
        for index, line in enumerate(path.read_bytes().splitlines(), 1):
            try:
                events.append(json.loads(line))
            except (ValueError, UnicodeError) as error:
                parse_diagnostics.append({'path': path.name, 'line': index, 'error': repr(error)})
http = [event for event in events if event.get('type') == 'http-result']
effects = [event for event in http if event['path'].startswith('/effects/')]


def memory(group):
    values = []
    for row in execution[group]:
        samples = row.get('memory_samples', [])
        elapsed = [sample['elapsed'] for sample in samples]
        values.append({'stage': row['stage'], 'pid': row.get('pid'), 'returncode': row.get('returncode'),
            'elapsed_seconds': row.get('elapsed_seconds'), 'samples': len(samples),
            'record_complete': all(key in row for key in ('pid', 'returncode', 'elapsed_seconds')),
            'maximum_polled_private_bytes': max((s['PrivateUsage'] for s in samples), default=None),
            'maximum_observed_OS_peak_working_set_bytes': max((s['PeakWorkingSetSize'] for s in samples), default=None),
            'first_sample_seconds': elapsed[0] if elapsed else None,
            'last_sample_seconds': elapsed[-1] if elapsed else None,
            'maximum_interior_sample_gap_seconds': max((b-a for a, b in zip(elapsed, elapsed[1:])), default=None),
            'unobserved_end_interval_seconds': row['elapsed_seconds']-elapsed[-1]
                if elapsed and 'elapsed_seconds' in row else None})
    return values


sinks = []
for stage in range(3):
    path = raw / f'stage{stage}-sink.json'
    if path.exists():
        try:
            sinks.append(load(path))
        except (ValueError, UnicodeError) as error:
            parse_diagnostics.append({'path': path.name, 'error': repr(error)})
event_types = Counter(event.get('type') for event in events)
metrics = {'suite_elapsed_seconds': execution['elapsed_seconds'],
    'authentication_elapsed_seconds': execution['authentication_elapsed_seconds'],
    'full_controller_elapsed_seconds': execution['full_controller_elapsed_seconds'],
    'complete_CLI_wall_seconds': outer['full_CLI_wall_seconds'],
    'time_scope': {'suite': 'Three native/server stages, controlled native kills, graceful server reopens, SQLite copies and the failed original audit; excludes authentication.',
                   'controller': 'Starts inside execute before source/runtime authentication; excludes interpreter startup/imports.',
                   'complete_CLI': outer['includes'], 'complete_CLI_excludes': outer['excludes']},
    'native_process_memory': memory('processes'), 'independent_server_memory': memory('servers'),
    'callback_ms': sum(s['callback_ms'] for s in sinks), 'flush_ms': sum(s['flush_ms'] for s in sinks),
    'native_JSONL_bytes': sum(s['bytes'] for s in sinks), 'native_JSONL_events': sum(s['events'] for s in sinks),
    'observed_trace_event_types': dict(sorted(event_types.items())),
    'observed_HTTP_results': len(http), 'observed_effect_HTTP_results': len(effects),
    'observed_effect_HTTP_errors': sum('error' in event for event in effects),
    'encoded_HTTP_request_body_bytes_for_settled_operations': sum(e['request_body_bytes'] for e in http),
    'observed_HTTP_response_body_bytes': sum(e['response_body_bytes'] for e in http),
    'encoded_effect_HTTP_request_body_bytes_for_settled_operations': sum(e['request_body_bytes'] for e in effects),
    'observed_effect_HTTP_response_body_bytes': sum(e['response_body_bytes'] for e in effects),
    'observed_effect_request_elapsed_ms': [e['elapsed_ms'] for e in effects],
    'SQLite_file_bytes': {row['path']: row['bytes'] for row in rows if '.sqlite' in row['path']},
    'partial_parse_diagnostics': parse_diagnostics,
    'observation_limits': 'Original frozen acceptance failed. These are descriptive saved observations, without throughput, success-rate or acceptance promotion. HTTP result events appear only after a client operation settles; two killed held-reply clients may lack a result event. Request fields measure encoded payload length for settled operations, not wire bytes. Response bodies include observed chunks; SQL attempts/effects and wire traffic are distinct. Headers/socket traffic are unmeasured. Callback/flush totals have no observer-OFF arm. Poll/start/end gaps are reported; extrema inside gaps and controller memory are unmeasured. OS peak working set differs from sampled private bytes. No baseline, causal speedup, SLO or model-quality claim.'}

report = {'recorded_at': stamp(), 'execution_status': 'failed', 'execution_accepted': False,
    'result_label': 'Failed frozen concurrent native admission/HTTP effect attempt; no acceptance or retry',
    'scientific_suites': 1, 'retries': 0, 'model_loads': 0, 'acceptance': None,
    'error': execution['error'], 'metrics': metrics,
    'failure_diagnosis': {'first_trigger': diagnosis['first_trigger'],
        'latent_subsequent_hazard': diagnosis['latent_subsequent_hazard'],
        'analysis_receipt': 'execution-receipts/preparation/original-audit-failure-analysis.json',
        'analysis_sha256': preparation_hashes[preparation / 'original-audit-failure-analysis.json'],
        'original_receipt_correction': diagnosis['supersedes_scope_explanation_only'],
        'original_acceptance_unchanged': True},
    'saved_observation': {**saved_observation,
        'receipt': 'execution-receipts/preparation/saved-observation.json',
        'receipt_sha256': preparation_hashes[saved_path],
        'source_path': supplement_source.relative_to(ROOT).as_posix(),
        'acceptance_rescue': False, 'new_scientific_execution': False,
        'scope': 'Separate post-outcome saved-byte joins only; original eight-source frozen attempt remains failed. No native, model, HTTP or service invocation. Archive regressions are reported separately after actual execution.'},
    'native_process_starts': sum('pid' in p for p in execution['processes']),
    'independent_server_process_starts': sum('pid' in p for p in execution['servers']),
    'forced_native_kills': sum(p.get('forced_termination', False) for p in execution['processes']),
    'raw_files': len(rows), 'raw_bytes': sum(row['bytes'] for row in rows), 'freeze_sha256': sha(freeze_path),
    'raw_manifest_sha256': sha(result / 'raw-manifest.json'),
    'outer_CLI_receipt': 'execution-receipts/h2-native-CLI.receipt.json',
    'outer_CLI_receipt_sha256': sha(receipts / 'h2-native-CLI.receipt.json'),
    'engineering': {'caller': 'Two pinned native Harness SQLite Sessions, official deterministic local Faux GenerationTask/ToolTask and separate loopback SQLite authority/effect store. Three overlapping public admit calls per Session: two distinct conversations and one exact retry.',
        'scale_bottleneck': 'Concurrent callers can race durable reservation, native submit and link commits. Exact retry must reuse the original submission; changed content must be refused and bounded capacity retained. Only one trusted owner is exercised.',
        'integration_point': 'Opt-in public admit wrapper and before-reserve barrier, stable native identities and scoped remote intent/receipt reconciliation; paused public abortTask gate before conversation abort resumes scheduling.',
        'rollback': 'Separate opt-in module/controller; all 85 inherited source pins and prior accepted/negative results remain unchanged.'},
    'preparation': {'new_pinned_sources': len(MANDATORY_SOURCES),
        'inherited_pins': len(freeze['preserved_previous_source_sha256']),
        'selected_Python_module_pins': len(freeze['python_runtime_modules']),
        'complete_Python_dependency_closure': False,
        'historical_prefreeze_reviews_do_not_override_failed_outcome': True},
    'next_gate': 'Preserve this failed original freeze and its raw evidence. Do not repeat the unchanged native suite solely to obtain green acceptance. Return to an actual runner or an independently justified current-authority/cancellation interleaving, with a separate preregistration and corrected auditor. No further standalone observer prerequisite.',
    'limits': protocol['limits'], 'H1_H3_H4_unchanged': True}
save(result / 'report.json', report)
md = ['# Concurrent native admission with a separate local HTTP effect', '', report['result_label'] + '.', '',
      f"Original failure: `{execution['error']}`. One frozen suite, zero retries/model loads; original execution acceptance is false. Native processes: {report['native_process_starts']}; independent server processes: {report['independent_server_process_starts']}. Raw evidence: {len(rows)} files / {report['raw_bytes']} bytes.", '',
      'The first original-auditor failure is its per-round service assertion: six round-bearing content-conflict events omit service. A later mixed-event admission filter also indexes service before testing event type. The saved traceback and corrected explanatory analysis are retained; the initial diagnostic receipt is unchanged.', '',
      f"Suite {metrics['suite_elapsed_seconds']:.3f}s; full controller {metrics['full_controller_elapsed_seconds']:.3f}s; complete CLI {metrics['complete_CLI_wall_seconds']:.3f}s. Authentication and preparation are distinct costs.", '',
      'A separately named post-outcome saved-byte observation reports 16 arrivals / 12 host reservations / four overload refusals, 12 native generation/tool chains, eight remote effects, 14 GETs/14 POSTs, 12 host/24 native task terminals, six recovered reservations and final active0. It also joins 28 admission results across six rounds, including six exact retries and six changed-content refusals. This does not replace the failed frozen acceptance or constitute another native execution.', '',
      metrics['observation_limits'], '', report['limits'], '', report['next_gate'], '',
      'Source/freeze, raw inventory and metrics are in [implementation](../../fixtures/pi-generation-concurrent-http/implementation.json), [raw manifest](raw-manifest.json) and [report JSON](report.json). Preparation, original failure diagnosis, separate saved observation and outer CLI receipts are under execution-receipts.']
with (result / 'report.md').open('x', encoding='utf-8') as stream:
    stream.write('\n'.join(md) + '\n')
# In the failed branch this checker validates frozen sources/report/raw only; it never calls audit.
checked = check()
assert checked['execution_accepted'] is False
assert inventory(source) == inventory(raw) == before
save(receipts / 'initial-saved-checker.json', {'recorded_at': stamp(), **checked, 'native_reexecution': False})
print(json.dumps({'exported': True, 'accepted': False, 'raw_files': len(rows),
                  'raw_bytes': report['raw_bytes'], 'saved_observation_status': saved_observation['status']}))
