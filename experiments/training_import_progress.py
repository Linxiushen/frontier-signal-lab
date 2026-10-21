"""Seven bounded import receipts inside the actual pretrained caller.

No package import, child launch or model execution occurs on module import.
These diagnostic receipts never extend the caller's nonrenewable deadline.
"""
import importlib
import json
import math
import os
from pathlib import Path
import time

from experiments import observer_duty_v2 as duty

STEPS = ("site-start", "site-complete", "torch-start", "torch-complete",
         "transformers-start", "transformers-complete", "versions-verified")
MAX_BYTES = 8192


class ImportProgress:
    def __init__(self, directory, nonce, identity, guard):
        self.directory = Path(directory)
        self.nonce, self.identity, self.guard = nonce, identity, guard
        self.index = 0

    def emit(self, step):
        if self.index >= len(STEPS) or step != STEPS[self.index]:
            raise duty.obs.ObserverError("Import progress order/bound differs")
        row = duty.base.envelope(self.nonce, "worker", seq=self.index, step=step,
            creation_filetime=self.identity["creation_filetime"],
            emitted_perf_counter=time.perf_counter(), provider_guard=self.guard.receipt())
        if row["pid"] != self.identity["pid"]:
            raise duty.obs.ObserverError("Import progress actual interpreter differs")
        # Same encoding as write_new; refuse before creating a file.
        raw = (json.dumps(row, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        if len(raw) > MAX_BYTES:
            raise duty.obs.ObserverError("Import progress receipt byte bound exceeded")
        duty.obs.write_new(self.directory / f"import-progress-{self.index:02d}.json", row)
        self.index += 1


def import_packages(progress):
    """Original import sequence, versions and offline policy, with fixed markers."""
    os.environ.update(duty.prior.OFFLINE_ENV)
    import site
    site.ENABLE_USER_SITE = False
    progress.emit("site-start")
    site.main()
    progress.emit("site-complete")
    progress.emit("torch-start")
    torch = importlib.import_module("torch")
    progress.emit("torch-complete")
    progress.emit("transformers-start")
    transformers = importlib.import_module("transformers")
    progress.emit("transformers-complete")
    if (str(torch.__version__) != duty.prior.CONFIG["torch_version"] or
            str(transformers.__version__) != duty.prior.CONFIG["transformers_version"]):
        raise duty.obs.ObserverError("actual ML package version differs from fixed local versions")
    progress.emit("versions-verified")
    return torch, transformers


def read_prefix(directory, nonce, identity, lower, upper, *, complete=False):
    """Read one-use published rows; incomplete/pending bytes are never success."""
    paths = sorted(Path(directory).glob("import-progress-*.json"))
    if len(paths) > len(STEPS):
        raise duty.obs.ObserverError("Import progress file bound exceeded")
    if complete and len(paths) != len(STEPS):
        raise duty.obs.ObserverError("Import progress is incomplete")
    rows, previous = [], lower
    for i, path in enumerate(paths):
        if path.name != f"import-progress-{i:02d}.json":
            raise duty.obs.ObserverError("Import progress filename gap")
        row = duty.obs.validate_message(duty.obs.read_small(path, MAX_BYTES), nonce, "worker")
        stamp = row.get("emitted_perf_counter")
        if (type(row.get("seq")) is not int or row["seq"] != i or row.get("step") != STEPS[i]
            or row["pid"] != identity["pid"] or row.get("creation_filetime") != identity["creation_filetime"]
            or type(stamp) not in (int, float) or not math.isfinite(stamp) or not previous <= stamp <= upper):
            raise duty.obs.ObserverError("Import progress identity/order/clock differs")
        rows.append(row)
        previous = stamp
    if complete and list(Path(directory).glob("import-progress-*.pending")):
        raise duty.obs.ObserverError("Uncommitted import progress remains")
    return rows
