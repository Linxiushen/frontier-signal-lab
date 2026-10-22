"""Explicit path-normalizing launcher for the next separately frozen suite.

The v1 failed launch and its frozen sources remain unchanged. This launcher
requires its own pre-execution hash in a new freeze; it does not authorize a
retry of v1. Import and --help never execute a model.
"""
import argparse
import json
from pathlib import Path
import sys
if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments import native_training_cost as study


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['protocol','freeze','output','plan']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(argv)
    protocol,freeze,output,plan=(getattr(args,k).resolve()for k in ['protocol','freeze','output','plan'])
    record=json.loads(freeze.read_bytes())
    if record.get('entrypoint_sha256')!=study.cost.file_hash(Path(__file__)):
        raise ValueError('A new freeze must explicitly pin this corrected entrypoint')
    return study.run(protocol,freeze,output,json.loads(plan.read_bytes()))


if __name__=='__main__':raise SystemExit(0 if main()else 1)
