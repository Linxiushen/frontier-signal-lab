"""A small real eager/autograd example. It never downloads weights or data."""
from __future__ import annotations

import datetime as dt

from .report import SCHEMA, seal


def as_report(audit_result, *, mode="executed_audit", title="Your model", run_label="fixed batch"):
    """Convert the reusable audit API's detailed result into the portable viewer."""
    comparisons = {x["policy"]: x for x in audit_result["comparisons"]}
    labels = {"dense": "Exact saved tensors", "int8": "INT8 saved tensors", "int8_keep_sensitive": "INT8 + exact sensitive scopes"}
    arms = []
    for arm in audit_result["arms"]:
        policy = arm["policy"]
        valid = arm.get("numerically_valid", False)
        if policy == "dense":
            comparison = {}
            for measure in ("gradient", "update"):
                summary = arm[measure]
                finite = valid and summary.get("finite") is True
                comparison[measure] = {"relative_l2": 0.0 if finite else None,
                    "cosine_similarity": 1.0 if finite else None,
                    "per_parameter": [{**p, "relative_l2": 0.0 if p.get("finite", True) else None,
                        "cosine_similarity": 1.0 if p.get("finite", True) else None}
                        for p in summary.get("per_parameter", [])]}
        else:
            comparison = comparisons[policy]
        if not valid:
            comparison = {key: {"relative_l2": None, "cosine_similarity": None, "per_parameter": []}
                          for key in ("gradient", "update")}
        if not arm.get("update", {}).get("executed", False):
            comparison = {**comparison, "update": None}
        arms.append({"id": policy, "label": labels.get(policy, policy), "short_label": policy,
                     "subtitle": "Valid backward + actual cloned update" if valid else "INVALID / see execution record",
                     "numerically_valid": valid, "update_executed": arm.get("update", {}).get("executed", False),
                     "scope": "Loss outside SaveScope hooks. Exact scopes selected by actual module type; full inventory is embedded in report.json.",
                     "loss": arm["loss"], "gradient": comparison["gradient"], "update": comparison["update"],
                     "inventory": arm.get("inventory", {})})
    sensitive_types = audit_result.get("scope", {}).get("sensitive_module_types", [])
    return seal({"schema": SCHEMA, "mode": mode, "description": title + " · CPU float32 diagnostic. Per-arm records state whether the optimizer step executed.",
        "observed_at_utc": audit_result.get("created_at_utc", dt.datetime.now(dt.timezone.utc).isoformat()),
        "context": "These measurements are diagnostic comparisons on one fixed batch, not quality or efficiency estimates.",
        "limitations": audit_result.get("limitations", []), "sources": [
            {"label": "API and scope contract", "url": "https://github.com/Linxiushen/frontier-signal-lab/blob/main/SAVESCOPE.md"}],
        "audit_result": audit_result, "runs": [{"label": run_label, "context": title,
            "gradient_gate": "No scientific threshold assigned to this generic audit." if all(a["numerically_valid"] for a in arms) else "INVALID EXECUTION: one or more arms could not compute finite gradients. See report.json.",
            "update_gate": "One fresh-state AdamW step on independent clones; no scientific threshold assigned." if all(a["update_executed"] for a in arms) else "INCOMPLETE: one or more optimizer steps were skipped. See report.json.",
            "parameter_tensors": len(arms[0]["gradient"].get("per_parameter", [])),
            "exact_scopes": ["loss outside SaveScope hooks"] + ["Exact type: " + name for name in sensitive_types], "arms": arms}]})


def run_demo():
    try:
        import torch
    except ImportError as error:
        raise ImportError("The executed demo needs Torch + NumPy. See SAVESCOPE.md; replay works without them.") from error
    from .audit import audit

    class TinyBlock(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.project = torch.nn.Linear(16, 32)
            self.norm = torch.nn.LayerNorm(32)
            self.attention = torch.nn.MultiheadAttention(32, 4, dropout=0, batch_first=True)
            self.head = torch.nn.Linear(32, 16)

        def forward(self, x):
            y = self.norm(self.project(x))
            # need_weights=True selects explicit eager attention in this example.
            attended, _ = self.attention(y, y, y, need_weights=True)
            return self.head(torch.nn.functional.gelu(y + attended))

    prior = torch.get_rng_state().clone()
    try:
        torch.manual_seed(11)
        model = TinyBlock().train()
        inputs, targets = torch.randn(2, 8, 16), torch.randn(2, 8, 16)
        result = audit(model, lambda m: m(inputs), lambda output: (output - targets).square().mean())
    finally:
        torch.set_rng_state(prior)
    return as_report(result, mode="executed_tiny_demo", title="Tiny attention block / seed 11 / original random fixture", run_label="seed 11")
