"""Post-run check of one pinned rejected census audit; performs no OS/ML work.

Passing preserves the negative result. It is not preregistered acceptance and
does not change the frozen producer, auditor or failed self-hash contract.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))
from scripts.audit_child_image_census import audit_files

REPORT_SHA256 = 'd43d85b84e0634b6b460d6db529367fa9cd44f41141a765d043935d4c8aec6b0'
EXPECTED_FAILURES = [name + ':base_worker_self_hash' for name in
                     ('native_census_graceful', 'injected_python_rejection')]


def check_record(report_path, *, root=ROOT):
    root = Path(root)
    raw = Path(report_path).read_bytes()
    report = json.loads(raw)
    freeze = json.loads((root / 'fixtures/child-image-census/implementation.json').read_bytes())
    frozen_audit = audit_files(report_path, root=root)
    checks = {
        'exact_original_report_bytes': hashlib.sha256(raw).hexdigest() == REPORT_SHA256,
        'frozen_auditor_bytes': all(hashlib.sha256((root / p).read_bytes()).hexdigest() == digest
                                  for p, digest in freeze['review_tools_sha256'].items()),
        'producer_runtime_pass_not_joint_acceptance': report['passed'] is True,
        'exact_frozen_rejection': frozen_audit['passed'] is False
            and frozen_audit['check_count'] == 424 and frozen_audit['checks_passed'] == 422
            and frozen_audit['failures'] == EXPECTED_FAILURES,
        'no_training_permission': report['training_permitted'] is False
            and report['model_loads'] == report['optimizer_steps'] == 0,
    }
    for case in report['cases']:
        ready = case['worker_identity']['self_receipt']
        nodes = [node for stage in case['censuses'] for node in stage['processes']
                 if node['pid'] == ready['pid']]
        checks[case['id'] + ':self_and_OS_identity_distinct'] = (
            ready['runtime_executable_sha256'] == freeze['executables_sha256']['launcher']
            and bool(nodes) and all(node['approved_known'] is True
                and node['creation_filetime'] == ready['creation_filetime']
                and node['image']['sha256'] == freeze['executables_sha256']['base_python']
                and node['image']['exact_path_matches'] == ['base_python'] for node in nodes))
    return {'schema_version': 1, 'post_hoc': True, 'preregistered': False,
            'negative_record_consistency_passed': all(checks.values()),
            'experiment_acceptance_passed': False, 'producer_reported_passed': report['passed'],
            'frozen_audit_passed': frozen_audit['passed'],
            'frozen_audit_failures': frozen_audit['failures'],
            'report_sha256': hashlib.sha256(raw).hexdigest(), 'checks': checks,
            'scope': __doc__}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=ROOT / 'results/child-image-census/report.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    result = check_record(args.report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2); stream.write('\n')
    print(json.dumps(result))
    return 0 if result['negative_record_consistency_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
