"""One separately frozen import observation in the existing native cost caller.

The original worker, role admission, provider guard and 20-second deadline stay
unchanged. A one-shot 15-second stack dump is cancelled on import completion;
the wrapper always raises before returning to the model-loading worker path.
"""
import argparse
import faulthandler
import json
from pathlib import Path
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import native_training_cost as study

SCRIPT = Path(__file__).resolve()
DUMP_AFTER_SECONDS = 15
MAX_STACK_BYTES = 8 * 1024 * 1024


class ImportBoundaryStopped(RuntimeError):
    """Intentional stop: this observation cannot enter model loading."""


def observe_import(progress, importer=None):
    # The parent pins this source. Worker uses exactly one actual import call.
    original = importer if importer is not None else ORIGINAL_IMPORT
    path = progress.directory / 'import-stack.txt'
    with path.open('xb') as stream:
        study.obs.write_new(progress.directory / 'import-stack-armed.json',
            study.base.envelope(progress.nonce, 'worker',
                creation_filetime=progress.identity['creation_filetime'],
                armed_perf_counter=time.perf_counter(),
                timeout_seconds=DUMP_AFTER_SECONDS, repeat=False,
                output='import-stack.txt', before_model_load=True))
        faulthandler.dump_traceback_later(DUMP_AFTER_SECONDS, repeat=False,
                                        file=stream, exit=False)
        outcome = 'raised'
        try:
            original(progress)
            outcome = 'completed'
        finally:
            faulthandler.cancel_dump_traceback_later()
            stream.flush()
            study.obs.write_new(progress.directory / 'import-stack-disarmed.json',
                study.base.envelope(progress.nonce, 'worker',
                    creation_filetime=progress.identity['creation_filetime'],
                    disarmed_perf_counter=time.perf_counter(),
                    import_outcome=outcome, before_model_load=True,
                    provider_guard=progress.guard.receipt()))
    # Never return successful package objects to the original load path.
    raise ImportBoundaryStopped('Import observed; model loading is not permitted')


ORIGINAL_IMPORT = study.progress.import_packages


def parent(protocol, freeze, output, plan):
    protocol, freeze, output, plan = (Path(p).resolve() for p in
                                     [protocol, freeze, output, plan])
    pins = json.loads(freeze.read_bytes())
    contract = json.loads(protocol.read_bytes())
    if (pins.get('entrypoint_sha256') != study.cost.file_hash(SCRIPT)
        or pins.get('additional_source_sha256') != {
            p: study.cost.file_hash(study.ROOT / p) for p in
            ['scripts/observe_native_training_import.py',
             'tests/test_native_training_import_observation.py']}
        or contract.get('import_observation') != {
            'dump_after_seconds': 15, 'stage_deadline_seconds': 20,
            'stack_bytes_ceiling': MAX_STACK_BYTES,
            'model_loads_permitted': 0, 'original_invocations': 1,
            'retries': 0, 'stop_before_model_load': True}):
        raise ValueError('Separate frozen import-observation contract required')
    previous = study.SCRIPT
    study.SCRIPT = SCRIPT
    try:
        return study.run(protocol, freeze, output, json.loads(plan.read_bytes()))
    finally:
        study.SCRIPT = previous


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', action='store_true')
    for name in ['protocol', 'freeze', 'output', 'plan', 'directory', 'native',
                 'provider-source', 'model-dir', 'fixture']:
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--nonce')
    for name in ['case-end', 'suite-end']:
        parser.add_argument('--' + name, type=float)
    args = parser.parse_args(argv)
    if args.worker:
        study.progress.import_packages = observe_import
        try:
            return study.worker(args.directory, args.nonce, args.native,
                args.provider_source, args.model_dir, args.fixture,
                args.case_end, args.suite_end)
        finally:
            study.progress.import_packages = ORIGINAL_IMPORT
    for name in ['protocol', 'freeze', 'output', 'plan']:
        if getattr(args, name) is None:
            parser.error('--' + name + ' is required in parent mode')
    return parent(args.protocol, args.freeze, args.output, args.plan)


if __name__ == '__main__':
    raise SystemExit(0 if main() else 1)
