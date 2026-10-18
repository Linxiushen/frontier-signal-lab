"""Replay the three preregistered saved-receipt mutations, without workloads.

This consumer was written after the v2 outcome. The control names and rejection
requirements were frozen before execution; this script is not a frozen producer.
Only disposable copies are changed. Gradient digest mutation is metadata-only.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.audit_codec_allocation_v2 import audit, canonical, read, sha

ROOT = Path(__file__).resolve().parents[1]


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                          encoding='utf-8', newline='\n')


def run(result, protocol, freeze):
    result = Path(result)
    original = {p.relative_to(result).as_posix(): sha(p) for p in result.rglob('*') if p.is_file()}
    baseline = audit(result, protocol, freeze)
    if baseline.get('passed') is not True or baseline.get('execution_acceptance') is not True:
        raise ValueError('controls require the unmodified, accepted v2 saved suite')
    kinds = ['raw_byte_mutation', 'poststudy_stale_hash', 'gradient_equality_corruption']
    if read(protocol)['saved_receipt_rejection_controls'] != kinds:
        raise ValueError('control names/order differ from the frozen protocol')
    controls = []
    with tempfile.TemporaryDirectory(prefix='codec-v2-receipt-controls-') as temporary:
        for kind in kinds:
            dest = Path(temporary)/kind
            shutil.copytree(result, dest)
            report = read(dest/'report.json')
            if kind == 'raw_byte_mutation':
                path = dest/'05_on_dense/allocation-trace.json'
                path.write_bytes(path.read_bytes()+b' ')
            else:
                case = report['cases'][0]
                operation = case['operation']
                path = dest/case['id']/'operation.json'
                if kind == 'poststudy_stale_hash':
                    operation['forward_loss_wall_seconds'] += 0.000001
                else:
                    operation['gradient']['sha256'] = '0'*64
                write(path, operation)
                if kind == 'gradient_equality_corruption':
                    digest = sha(path)
                    for key in ('stages', 'received_stage_receipts'):
                        case[key]['poststudy']['operation_sha256'] = digest
                    write(dest/case['id']/'poststudy-ready.json', case['stages']['poststudy'])
                    report['math_controls']['dense']['gradient_bytes_identical'] = False
                write(dest/(case['id']+'-result.json'), case)
                report['result_sha256'] = hashlib.sha256(canonical({
                    k:v for k,v in report.items() if k != 'result_sha256'})).hexdigest()
                write(dest/'report.json', report)
            checked = audit(dest, protocol, freeze)
            rejected = (checked.get('passed') is False and checked.get('execution_acceptance') is None
                        and checked.get('reported_execution_acceptance') is True)
            controls.append({'name':kind, 'performed':True, 'rejected':rejected,
                'reported_execution_acceptance':checked.get('reported_execution_acceptance'),
                'execution_acceptance':checked.get('execution_acceptance'),
                'failed_checks':[k for k,v in checked.get('checks', {}).items() if not v]})
    unchanged = original == {p.relative_to(result).as_posix():sha(p) for p in result.rglob('*') if p.is_file()}
    return {'schema_version':1, 'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'passed':unchanged and all(c['rejected'] for c in controls), 'controls':controls,
        'original_result_files_unchanged':unchanged, 'baseline_execution_acceptance':True,
        'actual_additional_suites':0, 'suite_payload_sha256':baseline['suite_payload_sha256'],
        'consumer_sha256':sha(__file__),
        'limits':'Post-outcome consumer of three predeclared saved-receipt controls. No model/process/allocator execution; no independent gradient tensor rehash or OS/GPU/quality claim.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, default=ROOT/'results/codec-allocation-v2')
    parser.add_argument('--protocol', type=Path, default=ROOT/'fixtures/codec-allocation-v2/protocol.json')
    parser.add_argument('--freeze', type=Path, default=ROOT/'fixtures/codec-allocation-v2/implementation.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    checked = run(args.result, args.protocol, args.freeze)
    if args.output:
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(checked, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
    print(json.dumps(checked, ensure_ascii=False))
    return 0 if checked['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
