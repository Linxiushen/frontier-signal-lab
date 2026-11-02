"""Supplement original saved-byte review; no native/server/scientific invocation."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
load = lambda p: json.loads(Path(p).read_bytes())
saved = load(HERE / 'radar-postoutcome-review.json')
original = ROOT / saved['original_output_directory']
assert all((original / r['path']).stat().st_size == r['bytes'] and sha(original / r['path']) == r['sha256']
           for r in saved['original_inventory'])
e = load(original / 'execution.json')
assert e['status'] == 'passed'
ids = load(original / 'identities.json')
events = [json.loads(line) for s in range(3) for line in (original / f'stage{s}.jsonl').read_text(encoding='utf-8-sig').splitlines()]
remote = load(original / 'effects-stage2-endpoint.json')
by_key = {(r['service'], r['key']): r for r in ids['requests'] if r['status'] == 'admit'}
receipt_pairs = {(r['scope'], r['key']) for r in remote['effects']}
controls = []
for tag, name, committed, cancelled in [
    ((0, 0, 'revoke'), 'remote current authority refused before effect', False, False),
    ((1, 0, 'cancel'), 'cancel marked before effect', False, True),
    ((0, 1, 'live'), 'host current authority refused before effect', False, False),
    ((0, 1, 'post'), 'cancel/revoke after remote commit; historical GET recovery', True, True),
]:
    r = next(r for r in by_key.values() if (r['service'], r['stage'], r['intent']) == tag)
    state = load(original / f"service{r['service']}-stage2-endpoint.json")['state']
    present = (r['scope'], r['key']) in receipt_pairs
    assert present is committed and bool(state['requests'][r['key']].get('cancelled')) is cancelled
    attempts = [a for a in remote['attempts'] if a[2:4] == [r['scope'], r['key']]]
    controls.append({'name': name, 'service': r['service'], 'key': r['key'],
                     'effect_present': present, 'cancelled': cancelled,
                     'native_submission_status': r['terminal']['status'],
                     'effect_intent_status': state['effectIntents'][r['key']]['status'],
                     'ordered_SQL_HTTP_attempts': attempts})
assert [c['effect_intent_status'] for c in controls] == ['denied', 'aborted', 'denied', 'committed']
assert [[(a[1], a[4]) for a in c['ordered_SQL_HTTP_attempts']] for c in controls] == [
    [('GET', 404), ('POST', 403)], [('GET', 404)], [('GET', 404)],
    [('GET', 404), ('POST', 201), ('GET', 200), ('POST', 200), ('POST', 409)]]
recovered = load(original / 'stage2-recovered.json')
post = controls[-1]
r = by_key[post['service'], post['key']]
assert [r['scope'], r['conversation'], 2, 0] in recovered['server']['authority']
assert recovered['states'][0]['requests'][r['key']]['cancelled'] is True
assert recovered['states'][0]['effectIntents'][r['key']]['status'] == 'committed'
assert not [ev for ev in events if ev['type'] in ('runtime-report', 'network-access-denied')]
assert Counter(ev['type'] for ev in events)['tool-enter'] == 14
http = [ev for ev in events if ev['type'] == 'http-result']
effect_http = [ev for ev in http if ev['path'].startswith('/effects/')]
launch = load(HERE / 'launch-receipt.json')
assert launch['returncode'] == 0 and launch['attempt'] == launch['native_suites'] == launch['H2_scientific_suites'] == 1
assert launch['retries'] == launch['model_loads'] == 0 and launch['freeze_sha256'] == e['freeze_sha256']
assert sha(HERE / 'native.stdout') == launch['stdout_sha256'] and sha(HERE / 'native.stderr') == launch['stderr_sha256']
assert e['acceptance']['HTTP_request_body_bytes'] == sum(ev['request_body_bytes'] for ev in http)
assert e['acceptance']['HTTP_response_body_bytes'] == sum(ev['response_body_bytes'] for ev in http)
resources = {}
for group in ('processes', 'servers'):
    resources[group] = [{
        'stage': row['stage'], 'pid': row['pid'], 'returncode': row['returncode'],
        'elapsed_seconds': row['elapsed_seconds'], 'samples': len(row['memory_samples']),
        'maximum_sampled_private_bytes': max(s['PrivateUsage'] for s in row['memory_samples']),
        'maximum_sampled_working_set_bytes': max(s['WorkingSetSize'] for s in row['memory_samples']),
        'maximum_observed_OS_peak_working_set_bytes': max(s['PeakWorkingSetSize'] for s in row['memory_samples']),
        'first_sample_seconds': row['memory_samples'][0]['elapsed'],
        'last_sample_seconds': row['memory_samples'][-1]['elapsed'],
        'maximum_interior_sample_gap_seconds': max(b['elapsed'] - a['elapsed'] for a, b in zip(row['memory_samples'], row['memory_samples'][1:])),
        'unobserved_end_interval_seconds': row['elapsed_seconds'] - row['memory_samples'][-1]['elapsed'],
    } for row in e[group]]
old_dir = ROOT / 'results/pi-generation-concurrent-http'
old_report_path = old_dir / 'report.json'
old_report = load(old_report_path)
assert old_report['execution_status'] == 'failed' and old_report['execution_accepted'] is False
assert old_report['error'] == "KeyError('service')" and old_report['acceptance'] is None
assert old_report['retries'] == 0 and old_report['saved_observation']['acceptance_rescue'] is False
old_manifest = load(old_dir / 'raw-manifest.json')
assert sha(old_dir / 'raw-manifest.json') == old_report['raw_manifest_sha256']
assert len(old_manifest['files']) == old_report['raw_files'] == 95
assert {r['path'] for r in old_manifest['files']} == {p.relative_to(old_dir / 'raw').as_posix() for p in (old_dir / 'raw').rglob('*') if p.is_file()}
for row in old_manifest['files']:
    p = old_dir / 'raw' / row['path']
    assert p.stat().st_size == row['bytes'] and sha(p) == row['sha256']
assert load(old_dir / 'raw/execution.json')['status'] == 'failed'
git_old = subprocess.run(['git', 'show', 'HEAD:results/pi-generation-concurrent-http/report.json'],
                         cwd=ROOT, capture_output=True, check=True).stdout
assert hashlib.sha256(git_old).hexdigest() == sha(old_report_path), 'Old failed report changed from HEAD'
report = {
    'status': 'passed_saved_controls_metrics_review',
    'reviewed_at': datetime.now(timezone.utc).isoformat(), 'reviewer': 'radar_resume',
    'original_review_sha256': sha(HERE / 'radar-postoutcome-review.json'),
    'freeze_sha256': e['freeze_sha256'], 'launch_receipt_sha256': sha(HERE / 'launch-receipt.json'),
    'source_sha256': saved['source_sha256'], 'negative_controls': controls,
    'postcancel_receipt_recovered_while_remote_authority_false_before_v3': True,
    'current_authority_denials': 2, 'pre_effect_cancellation': 1,
    'post_commit_historical_reconciliation': 1, 'expected_effects': 9, 'observed_effects': 9,
    'native_tool_entries': 14, 'native_unique_tool_tasks': 12,
    'SQL_HTTP_attempts': len(remote['attempts']),
    'HTTP_settled_results': len(http), 'HTTP_settled_effect_results': len(effect_http),
    'HTTP_error_results': len([ev for ev in http if 'error' in ev]),
    'HTTP_body_byte_scope': 'Encoded request payloads and observed response chunks for emitted settled operations only; killed held-reply client may have no result event. SQL attempt count differs. Headers/socket/wire bytes unmeasured.',
    'HTTP_encoded_request_body_bytes_settled': sum(ev['request_body_bytes'] for ev in http),
    'HTTP_observed_response_body_bytes_settled': sum(ev['response_body_bytes'] for ev in http),
    'suite_elapsed_seconds': e['elapsed_seconds'],
    'authentication_elapsed_seconds': e['authentication_elapsed_seconds'],
    'full_controller_elapsed_seconds': e['full_controller_elapsed_seconds'],
    'full_CLI_elapsed_seconds': launch['full_cli_elapsed_seconds'],
    'descriptive_fixture_effects_per_suite_second': 9 / e['elapsed_seconds'],
    'descriptive_fixture_effects_per_full_controller_second': 9 / e['full_controller_elapsed_seconds'],
    'descriptive_fixture_effects_per_full_CLI_second': 9 / launch['full_cli_elapsed_seconds'],
    'terminal_latency_ms': e['acceptance']['terminal_latency_ms'],
    'resource_observations': resources,
    'observation_callback_ms': sum(load(original / f'stage{s}-sink.json')['callback_ms'] for s in range(3)),
    'observation_flush_ms': sum(load(original / f'stage{s}-sink.json')['flush_ms'] for s in range(3)),
    'old_failed_result_preserved': {'report_sha256': sha(old_report_path),
        'report_matches_HEAD_bytes': True, 'raw_manifest_sha256': sha(old_dir / 'raw-manifest.json'),
        'verified_raw_files': 95, 'execution_status': 'failed', 'acceptance_rescue': False},
    'limits': 'Single trusted Windows owner, two isolated native Sessions, actual loopback HTTP and official deterministic Faux; no real model quality, GPU, distributed, tenant authentication, concurrent native owners or production evidence. Nine effects is a preregistered fixture outcome, not model success rate. Latencies include imposed holds/restarts. Resource maxima are observed samples/OS counters with reported gaps, not continuous peaks. Callback/flush totals have no observer-OFF comparison. No baseline or causal speedup. Old failed suite remains failed. No native/server/model/scientific rerun.'}
target = HERE / 'radar-controls-metrics-review.json'
assert not target.exists()
target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'path': target.relative_to(ROOT).as_posix(), 'sha256': sha(target),
                  'old_failed_result_preserved': report['old_failed_result_preserved'],
                  'SQL_HTTP_attempts': report['SQL_HTTP_attempts'],
                  'HTTP_settled_effect_results': report['HTTP_settled_effect_results']}))
