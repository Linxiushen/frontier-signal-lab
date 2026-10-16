# Frozen process observer engineering case

This Windows-only, standard-library probe verifies actual-interpreter identity,
synchronous resident/private memory readings and controlled descendant cleanup.
It launches only bounded diagnostic workers (maximum64MiB explicit allocation).
It is separate from SaveScope's public API and frozen historical model probes.

## Verify the published receipts on any platform

From the repository root, with Python3.11+; no third-party packages or process
launch is involved:

```bash
python -S -m scripts.audit_process_observer --report results/process-observer/report.json --protocol fixtures/process-observer/protocol.json --freeze fixtures/process-observer/implementation.json --output local-state/my-observer-audit.json
```

The output path must be new. A pass checks recorded hashes, identities, brackets,
allocation deltas, termination reasons/timing and exit coverage. It is not fresh
Windows execution, proof of authentic historical telemetry or model validation.

## Execute once on another Windows host

Use an existing trusted CPython3.11+ installation to create a venv. The original
freeze pins the launch executable hash, so a different interpreter requires a
separate reproduction freeze. Keep the original protocol, implementation and
published results unchanged. The following PowerShell commands prepare that
local freeze, then launch one complete five-case suite into a new directory:

```powershell
python -m venv .venv
New-Item -ItemType Directory -Force local-state | Out-Null
@'
from pathlib import Path
import datetime as dt, hashlib, json
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
protocol = Path('fixtures/process-observer/protocol.json')
source = json.loads(Path('fixtures/process-observer/implementation.json').read_text('utf-8'))
assert all(sha(p) == h for p,h in source['new_source_files_sha256'].items())
freeze = {'schema_version':1, 'frozen_at':dt.datetime.now(dt.timezone.utc).isoformat(),
    'protocol_sha256':sha(protocol),
    'new_source_files_sha256':source['new_source_files_sha256'],
    'python_executable_sha256':sha('.venv/Scripts/python.exe'),
    'kind':'new-host reproduction freeze; original published freeze unchanged'}
with Path('local-state/my-observer-freeze.json').open('x',encoding='utf-8',newline='\n') as f:
    f.write(json.dumps(freeze,indent=2)+'\n')
'@ | & .venv/Scripts/python.exe -S -
& .venv/Scripts/python.exe -S experiments/process_observer_probe.py --python .venv/Scripts/python.exe --protocol fixtures/process-observer/protocol.json --freeze local-state/my-observer-freeze.json --output reports/runs/my-observer
& .venv/Scripts/python.exe -S -m scripts.audit_process_observer --report reports/runs/my-observer/report.json --protocol fixtures/process-observer/protocol.json --freeze local-state/my-observer-freeze.json --python .venv/Scripts/python.exe --output local-state/my-executed-observer-audit.json
```

Review failures rather than reusing the output directory or selecting cases.
Unsupported platforms fail closed, with no Windows validation. Successful
32/64MiB controls prevent a kill-everything implementation from passing. The
cap is a sampled private-byte threshold on the actual interpreter with bounded
whole-job termination; it allows controlled overshoot and is not a hard memory
ceiling, continuous peak, arbitrary descendant cap or production guarantee.

The5cases and38mock tests are frozenv1. Any implementation change needs a new
version/protocol/freeze and a separate acceptance; do not rewrite this history.
The additional8auditor tests use synthetic/tampered receipts and never launch
real processes. CI performs those tests and an offline audit of published
Windows receipts, not another Windows acceptance or new model-cost study.
