"""Versioned same native-ledger integration; unchanged v2 producer cases.

Only its frozen saved-byte acceptance schema changes. The same worker, adapter,
native observer, ledger and admission policy remain frozen dependencies.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments import observed_job_probe_v2 as engine

native, dual, ROOT = engine.native, engine.dual, engine.ROOT
run_case = engine.run_case
SOURCES = (*engine.SOURCES, "experiments/observed_job_probe_v3.py",
    "scripts/audit_observed_job_v3.py", "tests/test_observed_job_v3.py")


def run(protocol_path, freeze_path, output):
    protocol, freeze = native.read_small(protocol_path), native.read_small(freeze_path)
    assert protocol["id"] == "native-observer-ledger-integration-v3"
    assert freeze["actual_suites_permitted"] == 1 and freeze["retries"] == 0
    assert freeze["model_loads_permitted"] == 0
    assert freeze["protocol_sha256"] == native.sha256_file(protocol_path)
    assert freeze["output_directory"] == output.relative_to(ROOT).as_posix()
    assert freeze["source_sha256"] == {p: native.sha256_file(ROOT / p) for p in SOURCES}
    paths = {"worker": Path(sys.executable), "conhost": Path(os.environ["SystemRoot"]) / "System32" / "conhost.exe"}
    hashes = {k: native.sha256_file(p) for k, p in paths.items()}
    assert hashes == freeze["executables_sha256"]
    assert {k: dual.path_hash(p) for k, p in paths.items()} == freeze["executable_path_sha256"]
    started = datetime.now(timezone.utc)
    assert datetime.fromisoformat(freeze["frozen_at"]) < started
    output.mkdir(exist_ok=False)
    report = {"started_at": started.isoformat(), "protocol_sha256": native.sha256_file(protocol_path),
        "freeze_sha256": native.sha256_file(freeze_path), "executables_sha256": hashes,
        "cases": [], "scientific_experiments": 0, "model_loads": 0, "optimizer_updates": 0}
    suite_end = time.perf_counter() + protocol["suite_seconds"]
    for name in protocol["cases"]:
        assert time.perf_counter() < suite_end, "Suite deadline"
        case = run_case(name, output, protocol, paths, hashes, suite_end)
        report["cases"].append(case)
        if not case["passed"]:
            break
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = len(report["cases"]) == len(protocol["cases"]) and all(c["passed"] for c in report["cases"]) and time.perf_counter() < suite_end
    native.write_new(output / "report.json", report)
    print(json.dumps({"passed": report["passed"], "cases": [(c["name"], c["passed"]) for c in report["cases"]]}))
    return report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("protocol", "freeze", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if run(args.protocol.resolve(), args.freeze.resolve(), args.output.resolve()) else 1)
