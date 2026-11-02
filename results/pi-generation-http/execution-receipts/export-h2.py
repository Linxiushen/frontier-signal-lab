"""Export this single frozen attempt and descriptive measured costs, never rerun it."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import sys

ROOT = Path.cwd(); RUN = ROOT / 'reports/runs/20261102T125850Z'
sys.path.insert(0, str(ROOT))
from scripts.check_pi_generation_http import check, MANDATORY_SOURCES

sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
load = lambda p: json.loads(p.read_bytes())
stamp = lambda: datetime.now(timezone.utc).isoformat()
def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

source = RUN / 'h2-native-http'; result = ROOT / 'results/pi-generation-http'
assert (source / 'execution.json').exists(), 'This exporter handles reached-suite outcomes; preserve pre-suite authentication failures separately from outer receipts.'
assert not result.exists(); result.mkdir(); raw = result / 'raw'
before = {p.relative_to(source).as_posix(): sha(p) for p in source.rglob('*') if p.is_file()}
shutil.copytree(source, raw)
after = {p.relative_to(raw).as_posix(): sha(p) for p in raw.rglob('*') if p.is_file()}
assert before == after
rows = [{'path': name, 'bytes': (raw / name).stat().st_size, 'sha256': digest} for name, digest in sorted(after.items())]
save(result / 'raw-manifest.json', {'recorded_at': stamp(), 'files': rows, 'total_bytes': sum(r['bytes'] for r in rows)})
execution = load(raw / 'execution.json'); outer = load(RUN / 'h2-native-CLI.receipt.json')
freeze_path = ROOT / 'fixtures/pi-generation-http/implementation.json'; freeze = load(freeze_path)
assert execution['freeze_sha256'] == sha(freeze_path)
assert execution['scientific_suites'] == 1 and execution['retries'] == 0
accepted = execution['status'] == 'passed'
assert (outer['exit_code'] == 0) == accepted
for stream in ('stdout', 'stderr'):
    assert sha(RUN / f'h2-native-CLI.{stream}.log') == outer[f'{stream}_sha256']
receipts = result / 'execution-receipts'; receipts.mkdir(); (result / 'review').mkdir()
for path in [RUN / 'h2-native-CLI.receipt.json', RUN / 'h2-native-CLI.stdout.log', RUN / 'h2-native-CLI.stderr.log',
             RUN / 'scientific-reservation.json', RUN / 'freeze-and-launch-h2.py',
             RUN / 'freeze-helper-initial.py.txt', RUN / 'freeze-helper-schema-diagnostic.json', Path(__file__)]:
    (receipts / path.name).write_bytes(path.read_bytes())
    assert (receipts / path.name).read_bytes() == path.read_bytes()
for path in sorted((RUN / 'h2-preparation').iterdir()):
    if path.is_file():
        target = receipts / 'preparation' / path.name; target.parent.mkdir(exist_ok=True)
        target.write_bytes(path.read_bytes())
        assert target.read_bytes() == path.read_bytes()
save(receipts / 'raw-copy-verification.json', {'recorded_at': stamp(), 'files': len(before),
    'original_and_public_copy_equal': before == after, 'bytes': sum(r['bytes'] for r in rows), 'scientific_reexecution': False})
events = []; parse_diagnostics = []
for stage in range(3):
    path = raw / f'stage{stage}.jsonl'
    if path.exists():
        for index, line in enumerate(path.read_bytes().splitlines(), 1):
            try: events.append(json.loads(line))
            except (ValueError, UnicodeError) as error:
                if accepted: raise
                parse_diagnostics.append({'path': path.name, 'line': index, 'error': repr(error)})
http = [e for e in events if e['type'] == 'http-result']
effects = [e for e in http if e['path'].startswith('/effects/')]
def memory(group):
    values = []
    for row in execution[group]:
        samples = row.get('memory_samples', []); elapsed = [s['elapsed'] for s in samples]
        values.append({'stage': row['stage'], 'pid': row.get('pid'), 'returncode': row.get('returncode'),
            'elapsed_seconds': row.get('elapsed_seconds'), 'samples': len(samples),
            'record_complete': all(k in row for k in ('pid', 'returncode', 'elapsed_seconds')),
            'maximum_polled_private_bytes': max((s['PrivateUsage'] for s in samples), default=None),
            'maximum_observed_OS_peak_working_set_bytes': max((s['PeakWorkingSetSize'] for s in samples), default=None),
            'first_sample_seconds': elapsed[0] if elapsed else None,
            'last_sample_seconds': elapsed[-1] if elapsed else None,
            'maximum_interior_sample_gap_seconds': max((b-a for a,b in zip(elapsed,elapsed[1:])), default=None),
            'unobserved_end_interval_seconds': row['elapsed_seconds']-elapsed[-1] if elapsed and 'elapsed_seconds' in row else None})
    return values
sinks = []
for stage in range(3):
    path = raw / f'stage{stage}-sink.json'
    if path.exists():
        try: sinks.append(load(path))
        except (ValueError, UnicodeError) as error:
            if accepted: raise
            parse_diagnostics.append({'path': path.name, 'error': repr(error)})
metrics = {'suite_elapsed_seconds': execution['elapsed_seconds'],
    'authentication_elapsed_seconds': execution['authentication_elapsed_seconds'],
    'full_controller_elapsed_seconds': execution['full_controller_elapsed_seconds'],
    'complete_CLI_wall_seconds': outer['full_CLI_wall_seconds'],
    'time_scope': {'suite': 'Three native/server stages, controlled native kills, graceful server reopens, SQLite copies and audit; excludes authentication.',
                   'controller': 'Starts inside execute before source/runtime authentication; excludes interpreter startup/imports.',
                   'complete_CLI': outer['includes'], 'complete_CLI_excludes': outer['excludes']},
    'native_process_memory': memory('processes'), 'independent_server_memory': memory('servers'),
    'callback_ms': sum(s['callback_ms'] for s in sinks), 'flush_ms': sum(s['flush_ms'] for s in sinks),
    'native_JSONL_bytes': sum(s['bytes'] for s in sinks), 'native_JSONL_events': sum(s['events'] for s in sinks),
    'observed_HTTP_results': len(http), 'observed_effect_HTTP_results': len(effects),
    'observed_effect_HTTP_errors': sum('error' in e for e in effects),
    'encoded_HTTP_request_body_bytes_for_settled_operations': sum(e['request_body_bytes'] for e in http),
    'observed_HTTP_response_body_bytes': sum(e['response_body_bytes'] for e in http),
    'encoded_effect_HTTP_request_body_bytes_for_settled_operations': sum(e['request_body_bytes'] for e in effects),
    'observed_effect_HTTP_response_body_bytes': sum(e['response_body_bytes'] for e in effects),
    'observed_effect_request_elapsed_ms': [e['elapsed_ms'] for e in effects],
    'SQLite_file_bytes': {r['path']: r['bytes'] for r in rows if '.sqlite' in r['path']},
    'partial_parse_diagnostics': parse_diagnostics,
    'observation_limits': 'HTTP result events are emitted only when a client operation settles; the two killed held-reply clients may have no result event. Request body byte fields measure encoded serialized payload length for settled operations, not bytes sent on the wire. Response bodies include observed chunks; SQL attempts/effects and all wire traffic are distinct. Headers/socket traffic not measured. Callback/flush totals are partial observations without an observer-OFF arm. Poll/start/end gap durations are reported, but extrema within uncovered intervals and controller memory are unmeasured; OS peak working set is distinct from sampled private bytes. No baseline, causal speedup, SLO or model-quality claim.'}
if accepted:
    acceptance = execution['acceptance']
    metrics['terminal_latency_ms'] = {**acceptance['terminal_latency_ms'], 'estimator': 'nearest rank',
        'scope': '12 mixed host dispositions, including deliberate holds and restarts; no model/SLO inference.'}
    for scope, seconds in [('suite', execution['elapsed_seconds']), ('controller', execution['full_controller_elapsed_seconds']), ('complete_CLI', outer['full_CLI_wall_seconds'])]:
        metrics[f'remote_effects_per_{scope}_second'] = 8 / seconds
        metrics[f'normal_native_completions_per_{scope}_second'] = 6 / seconds
    metrics['disposition_success'] = '12/12 host records reached intended finite dispositions: six normal completions, two pre-effect cancels, two remote authority refusals and two post-effect cancels with one remote effect each. Four overload refusals remained outside reservations. No real model/task-quality estimate.'
report = {'recorded_at': stamp(), 'execution_status': execution['status'], 'execution_accepted': accepted,
    'result_label': 'Accepted finite native ToolTask/separate loopback HTTP effect slice' if accepted else 'Failed frozen native HTTP effect attempt; no acceptance or retry',
    'scientific_suites': 1, 'retries': 0, 'model_loads': 0,
    'acceptance': execution.get('acceptance'), 'error': execution.get('error'), 'metrics': metrics,
    'native_process_starts': sum('pid' in p for p in execution['processes']), 'independent_server_process_starts': sum('pid' in p for p in execution['servers']),
    'forced_native_kills': sum(p.get('forced_termination', False) for p in execution['processes']),
    'raw_files': len(rows), 'raw_bytes': sum(r['bytes'] for r in rows), 'freeze_sha256': sha(freeze_path),
    'raw_manifest_sha256': sha(result / 'raw-manifest.json'),
    'outer_CLI_receipt': 'execution-receipts/h2-native-CLI.receipt.json', 'outer_CLI_receipt_sha256': sha(receipts / 'h2-native-CLI.receipt.json'),
    'engineering': {'caller': 'Two actual pinned native Harness SQLite Sessions, official deterministic local Faux GenerationTask/ToolTask, bounded loopback node:http, separate Python SQLite authority/effect store.',
        'scale_bottleneck': 'Unknown reply after independent commit can duplicate effects or release unresolved capacity; Session-local numeric IDs can alias remote authority without scope.',
        'integration_point': 'Durable intents and lookup-first scoped remote receipts; public paused abortTask batch before any resuming conversation abort; no native runtime edits.',
        'rollback': 'Separate opt-in module/controller; all 71 inherited source file pins and old results remain unchanged.'},
    'preparation': {'new_pinned_sources': len(MANDATORY_SOURCES), 'inherited_pins': len(freeze['preserved_previous_source_sha256']),
                    'selected_Python_module_pins': len(freeze['python_runtime_modules']), 'complete_Python_dependency_closure': False},
    'next_gate': 'CLOSED: finite single-owner independently persisted local HTTP caller accepted. Next work requires separately justified real runner or concurrent current-authority/cancellation integration with preregistered limits.' if accepted else 'Preserve this failure. Diagnose only from saved evidence; correct the same integration in a separate version and separately freeze at a later pass. No native retry this pass.',
    'limits': load(ROOT / 'experiments/pi_generation_http_protocol.json')['limits'], 'H1_H3_H4_unchanged': True}
save(result / 'report.json', report)
md = ['# Native ToolTask with a separate local HTTP effect', '', report['result_label'] + '.', '',
      f"One frozen suite, zero retries/model loads. Native processes: {report['native_process_starts']}; independent server processes: {report['independent_server_process_starts']}. Raw evidence: {len(rows)} files / {report['raw_bytes']} bytes.", '',
      f"Suite {metrics['suite_elapsed_seconds']:.3f}s; full controller {metrics['full_controller_elapsed_seconds']:.3f}s; complete CLI {metrics['complete_CLI_wall_seconds']:.3f}s. Authentication and preparation are distinct costs.", '']
if accepted:
    md.extend(['16 arrivals / 12 reservations / four overload refusals; 12 native generation/tool chains and official local Faux calls; eight remote effects (count1), 14 GETs/14 POSTs; six recovered reservations; 12 host/24 native task terminals, final active0. Six normal completions; two pre-effect cancels, two remote authority refusals, two post-effect cancels.', '',
      'Two native forced kills/reopens and two graceful independent server reopens preserve both databases. Lookup recovers committed receipts after cancellation; no recovery POST duplicates the held-reply effects. Explicit duplicate and changed-content probes bind the original scoped identities. Paused public task abort marks cover every original generation/tool pair before any conversation abort resumes scheduling.', ''])
else: md.extend([f"Failure: `{execution.get('error')}`. Partial observations are preserved without acceptance or throughput promotion.", ''])
md.extend(['Actual IDs are numeric and Session-local; remote authority binds stable service scope plus the original numeric conversation. Acceptance requires independent rereads of nine stopped SQLite backups, joins of original user/assistant/submission/tasks/intents/receipts and exact trace/PID/stage/control evidence. A failed attempt does not imply these checks completed.', '',
    metrics['observation_limits'], '', report['limits'], '', report['next_gate'], '',
    'Source/freeze, raw hash inventory and exact metrics are in [implementation](../../fixtures/pi-generation-http/implementation.json), [raw manifest](raw-manifest.json) and [report JSON](report.json). Preparation diagnostics, software tests and outer CLI receipts are retained under execution-receipts.'])
(result / 'report.md').write_text('\n'.join(md)+'\n', encoding='utf-8')
assert check()['execution_accepted'] == accepted
save(receipts / 'initial-saved-checker.json', {'recorded_at': stamp(), **check(), 'native_reexecution': False})
print(json.dumps({'exported': True, 'accepted': accepted, 'raw_files': len(rows), 'raw_bytes': report['raw_bytes']}))
