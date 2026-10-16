"""Build a portable replay from reviewed raw reports; never execute a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from savescope.report import SCHEMA, seal, validate, render


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def comparison(value):
    return {**value["aggregate"], "per_parameter": value["per_parameter"]}


def build():
    gradient_path = ROOT / "results/activation-attention-gradient/report.json"
    if sha(gradient_path) != "5c86f13e522bf09f8fe269f580026eabaeede7a437989c854aac09c5badc8d51":
        raise ValueError("Recorded gradient source changed; review before repackaging")
    original = json.loads(gradient_path.read_text(encoding="utf-8"))
    update_path = ROOT / "results/activation-update/report.json"
    if update_path.exists() and sha(update_path) != "5fdaeca50029a81073634e6e718e0ca3aecacca41e72d5363ef40f49711710e5":
        raise ValueError("Recorded update source changed; review before repackaging")
    update = json.loads(update_path.read_text(encoding="utf-8")) if update_path.exists() else None
    updates = {w["seed"]: w for w in update["stable_results"]["workers"]} if update else {}
    labels = [("dense", "Dense reference", "exact everywhere"),
              ("norm_only", "INT8 / exact norms", "loss + 13 norm scopes exact"),
              ("keep_attention", "INT8 / exact attention", "loss + 13 norms + 6 attention scopes exact")]
    runs = []
    for worker in original["stable_results"]["workers"]:
        arms = []
        for i, method in enumerate(worker["methods"]):
            identity, label, subtitle = labels[i]
            arm = {"id": identity, "label": label, "short_label": ["Dense", "INT8 + norms", "INT8 + norms + attention"][i],
                "subtitle": subtitle, "loss": method["forward_loss"],
                "scope": "Actual GPTNeoXAttention forward includes QKV projections, rotary operations, causal attention and output projection. No single-operand attribution.",
                "gradient": comparison(method["parameter_gradient_comparison"]), "update": None}
            if update:
                candidate = updates[worker["seed"]]["methods"][i]
                # Every gradient hash/statistic must agree before joining evidence.
                if candidate["gradient_diagnostic"] != method:
                    raise ValueError("Update and gradient evidence refer to different backwards")
                arm["update"] = comparison(candidate["update_comparison"])
            arms.append(arm)
        run = {"label": "seed " + str(worker["seed"]), "parameter_tensors": 76, "parameter_elements": 14067712,
            "context": "Pythia-14m · pinned pretrained weights · batch " + str(worker["batch_indices"]) + " · 128 targets. Three batches overlap: 320 unique target positions; not independent replicates.",
            "exact_scopes": ["CE outside hooks", "13 actual LayerNorm scopes", "6 actual attention scopes (selected arm)"],
            "gradient_gate": "All 3 recorded batches pass the predeclared attention-scope half-error / cosine gate. Fixed pretrained point only.",
            "arms": arms}
        if update:
            gate = updates[worker["seed"]]["update_fidelity_gate"]
            run["update_gate"] = "Predeclared joint update gate: " + ("PASS" if gate["passed"] else "FAIL") + ". Required: relative L2 ≤ 0.10, cosine ≥ 0.99, ≤ half norm-only error, and cosine no worse. Fresh-state first step only."
        runs.append(run)
    limitations = ["CPU float32, eager, one fixed pretrained point. Not general rotary backward or AttnRes.",
        "Earlier training was slower, used higher CPU peak memory, and regressed on both synthetic holdouts. Those negative results remain part of the evidence.",
        "Logical saved payload bytes do not measure allocator peak memory. This tool does not demonstrate speed or memory savings.",
        "Gradient or first-step update fidelity does not establish accumulated-state behavior, convergence or model quality."]
    paths = [gradient_path] + ([update_path] if update else [])
    result = seal({"schema": SCHEMA, "mode": "recorded_replay", "description": "Pythia-14m saved-operand diagnostic · three fixed training batches · inspected against dense backward.",
        "observed_at_utc": (update or original)["worker_measurements"][-1]["completed_at"],
        "context": "A replay of committed research observations; no model executes when this page opens.",
        "limitations": limitations, "runs": runs,
        "source_files": {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in paths},
        "sources": [{"label": "Original gradient evidence", "url": "https://github.com/Linxiushen/frontier-signal-lab/blob/main/results/activation-attention-gradient/report.md"},
                    {"label": "Earlier negative training result", "url": "https://github.com/Linxiushen/frontier-signal-lab/blob/main/results/activation-training/report.md"}] + ([
                    {"label": "Predeclared update diagnostic", "url": "https://github.com/Linxiushen/frontier-signal-lab/blob/main/results/activation-update/report.md"}] if update else [])})
    validate(result)
    output = ROOT / "savescope/data"
    output.mkdir(exist_ok=True)
    case_path = output / "pythia14m.json"
    case_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    (output / "manifest.json").write_text(json.dumps({"pythia14m.json": sha(case_path)}, indent=2) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "docs/index.html").write_text(render(result), encoding="utf-8", newline="\n")
    print(json.dumps({"case_sha256": sha(case_path), "content_sha256": result["content_sha256"], "update_included": bool(update)}))


if __name__ == "__main__":
    build()
