"""Portable, dependency-free SaveScope report validation and rendering."""
from __future__ import annotations

import hashlib
import json
import math
from importlib.resources import files
from pathlib import Path

SCHEMA = "savescope.report.v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def seal(report):
    report = dict(report)
    report.pop("content_sha256", None)
    report["content_sha256"] = fingerprint(report)
    return report


def _metrics(entry):
    if not isinstance(entry, dict):
        raise ValueError("Metrics must be an object")
    for key in ("relative_l2", "cosine_similarity"):
        number = entry.get(key)
        if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)):
            raise ValueError("Metrics must be finite numbers or null")
    if entry.get("relative_l2") is not None and entry["relative_l2"] < 0:
        raise ValueError("Relative L2 cannot be negative")
    cosine = entry.get("cosine_similarity")
    if cosine is not None and not -1.000001 <= cosine <= 1.000001:
        raise ValueError("Cosine must be between -1 and 1, within rounding tolerance")


def validate(report):
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ValueError("Expected savescope.report.v1")
    value = dict(report)
    expected = value.pop("content_sha256", None)
    if expected != fingerprint(value):
        raise ValueError("Report content SHA256 mismatch")
    if report.get("mode") not in ("recorded_replay", "executed_tiny_demo", "executed_audit"):
        raise ValueError("Unknown execution mode")
    if not isinstance(report.get("limitations"), list) or any(not isinstance(x, str) for x in report["limitations"]):
        raise ValueError("limitations must be an array of strings")
    if not isinstance(report.get("sources", []), list):
        raise ValueError("sources must be an array")
    for source in report.get("sources", []):
        if not isinstance(source, dict) or any(not isinstance(source.get(k), str) for k in ("label", "url")):
            raise ValueError("Sources need string labels and URLs")
    if not isinstance(report.get("runs"), list) or not report["runs"]:
        raise ValueError("Report needs at least one run")
    for run in report["runs"]:
        if not isinstance(run, dict) or not isinstance(run.get("label"), str):
            raise ValueError("Run needs an object and label")
        if not isinstance(run.get("exact_scopes", []), list) or any(not isinstance(x, str) for x in run.get("exact_scopes", [])):
            raise ValueError("exact_scopes must be an array of strings")
        if not isinstance(run.get("arms"), list) or not run["arms"]:
            raise ValueError("Run needs comparison arms")
        identities = set()
        for arm in run["arms"]:
            if not isinstance(arm, dict) or not isinstance(arm.get("id"), str) or not isinstance(arm.get("label"), str):
                raise ValueError("Arm needs a policy id and label")
            if arm["id"] in identities:
                raise ValueError("Policy IDs must be unique within a run")
            identities.add(arm["id"])
            for metric in ("gradient", "update"):
                entry = arm.get(metric)
                if entry is None:
                    continue
                _metrics(entry)
                if not isinstance(entry.get("per_parameter", []), list):
                    raise ValueError("per_parameter must be an array")
                for parameter in entry.get("per_parameter", []):
                    if not isinstance(parameter, dict) or not isinstance(parameter.get("name"), str):
                        raise ValueError("Each parameter needs a name")
                    elements = parameter.get("elements")
                    if isinstance(elements, bool) or not isinstance(elements, int) or elements < 0:
                        raise ValueError("Parameter elements must be a nonnegative integer")
                    _metrics(parameter)
    # Reject nested NaN/Infinity even when it is not a displayed aggregate.
    canonical(report)
    return report


def load_report(path):
    return validate(json.loads(Path(path).read_text(encoding="utf-8")))


def recorded_case():
    """Load shipped observations and check the independent package manifest."""
    root = files("savescope").joinpath("data")
    payload = root.joinpath("pythia14m.json").read_bytes()
    manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(payload).hexdigest() != manifest["pythia14m.json"]:
        raise ValueError("Bundled case differs from its manifest")
    return validate(json.loads(payload))


def render(report):
    validate(report)
    template = files("savescope").joinpath("templates/report.html").read_text(encoding="utf-8")
    # A report may contain user-controlled parameter names. Never interpolate
    # them as HTML; also prevent data from terminating its JSON script element.
    payload = canonical(report).decode().replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return template.replace("__SAVESCOPE_DATA__", payload)


def write_report(report, output):
    validate(report)
    destination = Path(output)
    if destination.exists():
        raise FileExistsError("Use a new output directory to preserve prior evidence: " + str(destination))
    html = render(report)
    destination.mkdir(parents=True)
    (destination / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    (destination / "index.html").write_text(html, encoding="utf-8", newline="\n")
    return destination / "index.html"
