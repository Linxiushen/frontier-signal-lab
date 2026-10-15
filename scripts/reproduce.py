"""Run the local checks and probes, then record exact source/result fingerprints."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    import numpy

    commands = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        [sys.executable, "experiments/attnres_budget_probe.py", "--output", "results/attnres-budget"],
        [sys.executable, "experiments/recovery_contract_probe.py", "--output", "results/recovery-contract"],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)
    files = sorted(
        list((ROOT / "experiments").glob("*.py"))
        + list((ROOT / "frontier_radar").glob("*.py"))
        + list((ROOT / "tests").glob("*.py"))
        + [ROOT / "scripts/reproduce.py", ROOT / "requirements.txt"]
        + list((ROOT / "results").rglob("*.json"))
        + list((ROOT / "results").rglob("*.md"))
    )
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in files if p.name != "reproduction.json"}
    manifest = {
        "python": platform.python_version(), "numpy": numpy.__version__,
        "platform": platform.system(),
        "commands": [["python", *c[1:]] for c in commands],
        "sha256": hashes,
        "scope": "Exact local checks and synthetic probes; excludes live GitHub data. Float rounding can differ across NumPy/BLAS platforms.",
    }
    (ROOT / "results/reproduction.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("Saved results/reproduction.json")


if __name__ == "__main__":
    main()
