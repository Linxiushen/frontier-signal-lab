"""Verify the published metadata without Torch, checkpoints or model execution.

Run this file from the repository checkout. Metadata is restored only into a
temporary directory. This checks receipt consistency; it cannot independently
reload/evaluate the model checkpoints deliberately omitted from publication.
"""
from pathlib import Path, PurePosixPath
import copy
from datetime import datetime
import gzip
import hashlib
import json
import sys
import tempfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent.parent
sys.path.insert(0, str(ROOT))
from scripts.audit_native_training_cost import audit
from experiments import native_training_cost_scopes_v4 as study


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inside(base, name):
    assert isinstance(name, str) and name and '\\' not in name and ':' not in name
    path = PurePosixPath(name)
    assert not path.is_absolute() and '..' not in path.parts and path.as_posix() == name
    target = (base / path).resolve()
    assert target.is_relative_to(base.resolve()) and target != base.resolve()
    return target


def main():
    manifest = json.loads((BASE / 'raw-manifest.json').read_bytes())
    rows = manifest['files']
    assert len(rows) == len({row['path'] for row in rows}) == manifest['original_file_count']
    assert sum(row['bytes'] for row in rows) == manifest['original_byte_total']
    published = [row for row in rows if row['published']]
    omitted = [row for row in rows if not row['published']]
    assert len(published) == manifest['published_metadata_file_count']
    assert sum(row['bytes'] for row in published) == manifest['published_metadata_original_bytes']
    assert sum(row['public_bytes'] for row in published) == manifest['published_metadata_stored_bytes']
    assert len(omitted) == manifest['omitted_checkpoint_count']
    assert sum(row['bytes'] for row in omitted) == manifest['omitted_checkpoint_bytes']
    freeze_path = ROOT / 'fixtures/native-training-cost-scopes-v4-reviewed/implementation.json'
    protocol_path = freeze_path.with_name('protocol.json')
    freeze = json.loads(freeze_path.read_bytes())
    assert sha(protocol_path.read_bytes()) == freeze['protocol_sha256']
    for name, expected in {**freeze['source_sha256'], **freeze['additional_source_sha256']}.items():
        assert sha((ROOT / name).read_bytes()) == expected, name
    with tempfile.TemporaryDirectory(prefix='savescope-metadata-') as directory:
        output = Path(directory)
        for row in manifest['files']:
            target = inside(output, row['path'])
            if not row['published']:
                assert row['path'].endswith('/endpoint.pt')
                continue
            packed = inside(BASE, row['public_path']).read_bytes()
            assert len(packed) == row['public_bytes'] and sha(packed) == row['public_sha256']
            assert row['encoding'] in ('identity', 'gzip')
            data = gzip.decompress(packed) if row['encoding'] == 'gzip' else packed
            assert len(data) == row['bytes'] and sha(data) == row['sha256']
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
        report = json.loads((output / 'report.json').read_bytes())
        assert report['protocol_sha256'] == sha(protocol_path.read_bytes())
        assert report['freeze_sha256'] == sha(freeze_path.read_bytes())
        result = audit(output, checkpoints=False)
        expected_checkpoints = {}
        for case in report['cases']:
            if case['passed']:
                recomputed = copy.deepcopy(case)
                study.validate_case(recomputed)
                assert recomputed == case
                validation = case['stages']['postvalidation']['validation']
                expected_checkpoints[case['id'] + '/endpoint.pt'] = (
                    validation['checkpoint_bytes'], validation['checkpoint_sha256'])
        assert {row['path']: (row['bytes'], row['sha256']) for row in omitted} == expected_checkpoints
        if (output / 'evaluation.json').exists():
            release = json.loads((output / 'evaluation-release.json').read_bytes())
            evaluation = json.loads((output / 'evaluation.json').read_bytes())
            assert len(report['cases']) == 12 and all(case['passed'] is True for case in report['cases'])
            assert [case['job'] for case in report['cases']] == study.jobs()
            assert set(release) == {'id', 'all_training_completed', 'endpoints', 'training_sealed_at', 'protocol_sha256'}
            assert release['id'] == evaluation['id'] == study.ID
            assert release['all_training_completed'] is True
            assert release['protocol_sha256'] == report['protocol_sha256']
            assert [row['job'] for row in release['endpoints']] == study.jobs()
            assert [row['job'] for row in evaluation['endpoints']] == study.jobs()
            assert evaluation['release_sha256'] == sha((output / 'evaluation-release.json').read_bytes())
            assert datetime.fromisoformat(release['training_sealed_at']) <= datetime.fromisoformat(evaluation['started_at'])
            for case, scored, sealed in zip(report['cases'], evaluation['endpoints'], release['endpoints']):
                assert case['job'] == scored['job'] == sealed['job']
                model = case['stages']['pretrain']['model']
                validation = case['stages']['postvalidation']['validation']
                assert sealed['initial_parameter_sha256'] == model['initial_parameter_sha256'] == evaluation['initial_parameter_sha256']
                assert sealed['final_parameter_sha256'] == validation['final_parameter_sha256']
                assert set(sealed) == {'job', 'checkpoint_sha256', 'initial_parameter_sha256', 'final_parameter_sha256'}
                for field in ('checkpoint_sha256', 'initial_parameter_sha256', 'final_parameter_sha256'):
                    assert scored[field] == sealed[field]
                assert scored['checkpoint_sha256'] == expected_checkpoints[case['id'] + '/endpoint.pt'][1]
                scores = scored['evaluation']
                assert len(scores['block_mean_nll']) == 64 and scores['scored_target_positions'] == 4096
                assert abs(scores['mean_nll'] - sum(scores['block_mean_nll']) / 64) < 1e-12
            supplement = json.loads((BASE / 'post-outcome-comparisons.json').read_bytes())
            assert supplement['frozen_execution_accepted'] is report['passed']
            assert supplement['raw_report_sha256'] == sha((output / 'report.json').read_bytes())
            assert supplement['raw_evaluation_sha256'] == sha((output / 'evaluation.json').read_bytes())
            assert supplement['paired_results'] == study.paired_results(report['cases'], evaluation)
            result['post_outcome_joint_screens_passed'] = supplement['paired_results']['all_six_joint_screens_passed']
            result['evaluation_scope'] = 'Saved scoring records only; frozen evaluator acceptance is unchanged.'
    assert not {'torch', 'transformers', 'numpy'} & set(sys.modules)
    result.update(published_metadata_files_verified=len(published),
                  checkpoint_bytes_publicly_available=False,
                  independent_quality_evaluation_performed=False)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
