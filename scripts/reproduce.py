"""Run the local checks and probes, then record exact source/result fingerprints."""
import hashlib
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    import numpy

    commands = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        [sys.executable, "experiments/attnres_budget_probe.py", "--output", "results/attnres-budget"],
        [sys.executable, "experiments/attnres_memory_probe.py", "--output", "results/attnres-memory"],
        [sys.executable, "experiments/recovery_contract_probe.py", "--output", "results/recovery-contract"],
        [sys.executable, "experiments/sqlite_migration_probe.py", "--output", "results/sqlite-migration"],
        ["node", "experiments/pi_adapter_queue_probe.mjs", "--output", "results/pi-adapter-queue"],
        ["node", "experiments/pi_context_transform_probe.mjs", "--output", "results/pi-context-transform"],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)
    files = sorted(
        list((ROOT / "experiments").glob("*.py"))
        + list((ROOT / "experiments").glob("*.mjs"))
        + list((ROOT / "frontier_radar").glob("*.py"))
        + list((ROOT / "tests").glob("*.py"))
        + [ROOT / "scripts/reproduce.py", ROOT / "requirements.txt"]
        + list((ROOT / "results").rglob("*.json"))
        + list((ROOT / "results").rglob("*.md"))
        + list((ROOT / "results").rglob("*.sql"))
        + list((ROOT / "results").rglob("*.npy"))
        + list((ROOT / "third_party/pi").glob("*"))
        + list((ROOT / "third_party/pi-context").rglob("*"))
    )
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in files if p.is_file() and p.name != "reproduction.json"}
    manifest = {
        "python": platform.python_version(), "numpy": numpy.__version__,
        "sqlite": sqlite3.sqlite_version,
        "node": subprocess.check_output(["node", "--version"], text=True).strip(),
        "platform": platform.system(),
        "commands": [["python" if c[0] == sys.executable else c[0], *c[1:]] for c in commands],
        "sha256": hashes,
        "scope": "Exact local checks and probes, including synthetic CPU residual-bank process-memory/timing measurements, an independent SQLite fixture, a pinned pi database adapter primitive with a substituted unused factory dependency over a Node SQLite stand-in, and complete unchanged pi context-transform modules before/after a model-handoff fix without runtime dependency substitution. Excludes training, GPU memory, provider requests, full upstream harness/Cloudflare execution and live data. Memory and timing vary per run; float rounding can differ across NumPy/BLAS platforms.",
    }
    (ROOT / "results/reproduction.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("Saved results/reproduction.json")


if __name__ == "__main__":
    main()
