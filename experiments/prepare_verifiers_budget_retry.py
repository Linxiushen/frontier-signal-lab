"""Build, but never execute, a content-bound protocol for the native Linux suite.

Run only after the authentic harness lock exists and exact source/protocol/code
review is complete. Mount project/source/output at /project,/source,/output in
the separately authorized bounded network-none container.
"""
import argparse
import json
import subprocess
from pathlib import Path

from experiments.eval_budget_runner import canonical, digest


def prepare(source: Path, harness_lock: Path, package_lock: Path, output: Path,
            harness_preparation: Path | None = None) -> dict:
    project = Path(__file__).resolve().parents[1]
    spec = json.loads((project / "research/protocols/verifiers-budget-native-retry-v1.json").read_bytes())
    # Read the required completed locks before creating any output/freeze.
    locks = {"harness": harness_lock.read_bytes(), "packages": package_lock.read_bytes()}
    if any(not data.strip() for data in locks.values()):
        raise ValueError("completed nonempty dependency locks required")
    if harness_preparation is None:
        raise ValueError("actual harness preparation receipt required")
    prepared = json.loads(harness_preparation.read_bytes())
    script_path = prepared["script_path"]
    script_sha = prepared["script_sha256"]
    if (prepared["lock_sha256"] != digest(locks["harness"])
            or len(script_sha) != 64
            or script_path != f"/root/.cache/verifiers/runtimes/scripts/{script_sha}.py"):
        raise ValueError("harness lock or actual prepared script identity mismatch")
    git = lambda *args: subprocess.check_output(["git", "-C", str(source), *args]).decode().strip()
    if git("rev-parse", "HEAD") != spec["source_head"] or git("status", "--porcelain"):
        raise ValueError("exact clean pinned source required")
    source_paths = [
        "verifiers/v1/cli/run.py", "verifiers/v1/env.py", "verifiers/v1/task.py",
        "verifiers/v1/agent.py", "verifiers/v1/trace.py", "verifiers/v1/episode.py",
        "verifiers/v1/harnesses/null/harness.py", "verifiers/v1/harnesses/utils/launch.py",
        "verifiers/v1/runtimes/runtime.py", "verifiers/v1/runtimes/backends/subprocess.py",
        "verifiers/v1/clients/eval.py", "tests/integration/fixtures/echo.py"]
    project_paths = ["experiments/eval_budget_runner.py", "experiments/verifiers_budget_suite_v2.py",
                     "experiments/prepare_verifiers_budget_retry.py", "research/protocols/verifiers-budget-native-retry-v1.json",
                     "experiments/eval_http_budget.py", "experiments/verifiers_budget_retry_suite.py"]
    versions = {"/source/" + p: digest((source / p).read_bytes()) for p in source_paths}
    versions.update({"/project/" + p: digest((project / p).read_bytes()) for p in project_paths})
    versions["/project/pyproject.toml"] = digest((project / "pyproject.toml").read_bytes())
    for path in sorted((project / "frontier_savescope.egg-info").rglob("*")):
        if path.is_file():
            versions["/project/" + path.relative_to(project).as_posix()] = digest(path.read_bytes())
    versions.update({"/inputs/" + k + ".lock": digest(v) for k, v in locks.items()})
    versions[script_path] = script_sha
    versions[script_path + ".lock"] = digest(locks["harness"])
    datasets = {}
    for phase in ["development", "final"]:
        relative = spec["workload"][phase + "_data"]
        data = (project / relative).read_bytes()
        if data != (canonical(json.loads(data)) + "\n").encode():
            raise ValueError("fixture request binding requires exact canonical one-phrase bytes")
        if len(json.loads(data)) != 1:
            raise ValueError("fixed one-task dataset required")
        datasets[phase] = {"path": "/project/" + relative, "sha256": digest(data)}
    result = {"id": spec["id"], "source_head": spec["source_head"], "versions": versions,
              "datasets": datasets, "evaluator_path": "/source/tests/integration/fixtures/echo.py",
              "limitations": spec["limitations"], "specification": spec,
              "status": "frozen_not_executed", "scientific_experiments": 0}
    output.mkdir(exist_ok=False)
    for name, data in locks.items():
        (output / (name + ".lock")).write_bytes(data)
    with (output / "protocol.json").open("x", encoding="utf8") as stream:
        stream.write(canonical(result) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--harness-lock", type=Path, required=True)
    parser.add_argument("--package-lock", type=Path, required=True)
    parser.add_argument("--harness-preparation", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.source, args.harness_lock, args.package_lock, args.out, args.harness_preparation)
    print(canonical({"status": result["status"], "output": str(args.out)}))
