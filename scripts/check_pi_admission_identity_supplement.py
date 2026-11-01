"""Replay a post-outcome identity supplement; never execute native workloads."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiments.pi_admission_identity_supplement import audit


def check(directory=None):
    return audit(ROOT / 'results/pi-generation-admission/raw' if directory is None else Path(directory))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, help='Saved raw directory; defaults to the archived admission outcome.')
    print(json.dumps(check(parser.parse_args().raw)))
