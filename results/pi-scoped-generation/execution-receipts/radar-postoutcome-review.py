"""Run only after root reports completion. Saved bytes, no runtime/server startup."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from experiments.pi_scoped_generation_audit import audit, verify_copied_endpoint
from scripts.check_pi_scoped_generation import validate_freeze


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_bytes())


def inventory(directory):
    return [{'path': p.relative_to(directory).as_posix(), 'bytes': p.stat().st_size,
             'sha256': sha(p)} for p in sorted(directory.rglob('*')) if p.is_file()]


def execute():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root-completed', action='store_true', required=True,
                        help='Explicit root completion message must precede execution')
    parser.parse_args()
    here = Path(__file__).resolve().parent
    started = datetime.now(timezone.utc).isoformat()
    freeze_path = ROOT / 'fixtures/pi-scoped-generation/implementation.json'
    frozen = load(freeze_path)
    protocol, _ = validate_freeze(ROOT, frozen, authenticate_runtime=False)
    original = ROOT / frozen['output_directory']
    before = inventory(original)
    execution = load(original / 'execution.json')
    assert execution['status'] in ('passed', 'failed'), 'Incomplete execution must not be audited'
    assert execution.get('completed_at')
    assert execution['freeze_sha256'] == sha(freeze_path)
    assert execution['scientific_suites'] == 1 and execution['retries'] == execution['model_loads'] == 0
    assert execution['limits'] == protocol['limits']
    source_before = {n: sha(ROOT / n) for n in frozen['source_sha256']}
    assert source_before == frozen['source_sha256']
    copies = []
    for stage in range(3):
        for service in (None, 0, 1):
            stem = f'effects-stage{stage}' if service is None else f'service{service}-stage{stage}'
            if (original / f'{stem}.sqlite').exists():
                endpoint = verify_copied_endpoint(original, stage, service)
                copies.append({'stage': stage, 'service': service, 'stem': stem,
                               'sqlite_sha256': sha(original / f'{stem}.sqlite'),
                               'endpoint_sha256': sha(original / f'{stem}-endpoint.json'),
                               'endpoint_keys': sorted(endpoint),
                               'effect_rows': len(endpoint['effects']) if service is None else len(endpoint['state']['effects']),
                               'attempts': len(endpoint['attempts']) if service is None else None})
    observed_acceptance = None
    if execution['status'] == 'passed':
        observed_acceptance = audit(original)
        assert observed_acceptance == execution['acceptance']
        assert len(copies) == 9
    else:
        assert execution.get('error'), 'Failed execution must retain original error'
    after = inventory(original)
    assert after == before, 'Saved-byte review changed original evidence'
    assert source_before == {n: sha(ROOT / n) for n in frozen['source_sha256']}
    report = {'status': 'saved_bytes_verified', 'started_at': started,
              'completed_at': datetime.now(timezone.utc).isoformat(),
              'reviewer': 'radar_resume', 'freeze_path': freeze_path.relative_to(ROOT).as_posix(),
              'freeze_sha256': sha(freeze_path), 'source_sha256': source_before,
              'original_output_directory': original.relative_to(ROOT).as_posix(),
              'execution_status': execution['status'],
              'execution_error': execution.get('error'),
              'execution_accepted': execution['status'] == 'passed',
              'original_files': len(before), 'original_bytes': sum(r['bytes'] for r in before),
              'inventory_unchanged': True, 'original_inventory': before,
              'copied_endpoints': copies, 'acceptance': observed_acceptance,
              'runtime_reauthenticated': False,
              'scope': 'Original saved evidence and immutable copied SQLite only. No native, HTTP server, model, network or scientific execution. A failed execution remains failed.'}
    target = here / 'radar-postoutcome-review.json'
    assert not target.exists(), 'Keep the first independent review receipt'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'path': target.relative_to(ROOT).as_posix(), 'sha256': sha(target),
                      'execution_status': execution['status'], 'copied_endpoints': len(copies),
                      'original_files': len(before), 'inventory_unchanged': True}))


if __name__ == '__main__':
    execute()
