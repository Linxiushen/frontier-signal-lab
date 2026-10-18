"""SaveScope CLI. Replay and inspect intentionally need no ML dependencies."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .report import load_report, recorded_case, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect saved-tensor compression before a training run.")
    parser.add_argument("--version", action="version", version="SaveScope 0.2.0")
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("replay", help="Verify and render recorded Pythia evidence; no model execution")
    replay.add_argument("--output", required=True, help="New output directory")
    demo = commands.add_parser("demo", help="Execute a tiny CPU audit offline (Torch + NumPy required)")
    demo.add_argument("--output", required=True, help="New output directory")
    inspect = commands.add_parser("inspect", help="Validate a report and print its comparisons")
    inspect.add_argument("report")
    render = commands.add_parser("report", help="Render an existing validated SaveScope report")
    render.add_argument("report")
    render.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if getattr(args, "output", None) and Path(args.output).exists():
            raise FileExistsError("Use a new output directory to preserve prior evidence: " + args.output)
        if args.command == "replay":
            data = recorded_case()
            print(json.dumps({"mode": data["mode"], "model_execution": False, "report": str(write_report(data, args.output))}))
        elif args.command == "demo":
            from .demo import run_demo
            data = run_demo()
            print(json.dumps({"mode": data["mode"], "model_execution": True, "report": str(write_report(data, args.output))}))
        elif args.command == "report":
            print(write_report(load_report(args.report), args.output))
        elif args.command == "inspect":
            data = load_report(args.report)
            print(json.dumps({"mode": data["mode"], "content_sha256": data["content_sha256"], "runs": [
                {"label": run["label"], "arms": [{"policy": a["id"], **{
                    key: {k: a[key].get(k) for k in ("relative_l2", "cosine_similarity")}
                    for key in ("gradient", "update") if a.get(key) is not None}}
                    for a in run["arms"]]} for run in data["runs"]]}, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        print("savescope: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
