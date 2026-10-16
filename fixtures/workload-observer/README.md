# Frozen CPU Torch workload observer

This six-case Windows engineering probe integrates the unchanged process
observer with a real Torch import, one CPU forward/backward/SGD update and a
native `cmd.exe` descendant. It is separate from SaveScope's public API and
all historical scientific probes. Constants replace RNG and pretrained data.

## Audit recorded receipts on any platform

Python 3.11+ and the standard library suffice. From the repository root:

```bash
python -S -m scripts.audit_workload_observer --report results/workload-observer/report.json --protocol fixtures/workload-observer/protocol.json --freeze fixtures/workload-observer/implementation.json --output local-state/my-workload-audit.json
```

The output path must be new. This checks the recorded identities, nonce/ancestry,
native image, single-update receipt, memory brackets, allocation deltas, busy
sampling/CPU progress, termination timing and exit coverage. It does not import
Torch, start processes or authenticate telemetry against the original OS. The
optional `--python` and `--native` arguments also hash those local executable
files; without them the two file checks are explicitly omitted.

An incomplete or failed acceptance is rejected with its failed checks retained.
Passing an offline audit is receipt consistency, not another Windows run.

## Execute a separate reproduction on Windows

Use an existing trusted CPython and a virtual environment containing
`torch==2.9.1+cpu`. The original run used CPython 3.12.14. Do not overwrite the
published protocol, implementation freeze or results. Create a new local freeze
for the reproduction's launcher and native executable bytes:

```powershell
New-Item -ItemType Directory -Force local-state | Out-Null
@'
from pathlib import Path
import datetime as dt, hashlib, json, os
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
original = json.loads(Path('fixtures/workload-observer/implementation.json').read_text('utf-8'))
for field in ('new_source_files_sha256', 'frozen_dependency_files_sha256'):
    assert all(sha(p) == h for p,h in original[field].items())
native = Path(os.environ['SystemRoot']) / 'System32/cmd.exe'
freeze = {
    'schema_version': 1,
    'frozen_at': dt.datetime.now(dt.timezone.utc).isoformat(),
    'protocol_sha256': sha('fixtures/workload-observer/protocol.json'),
    'new_source_files_sha256': original['new_source_files_sha256'],
    'frozen_dependency_files_sha256': original['frozen_dependency_files_sha256'],
    'python_executable_sha256': sha('.venv/Scripts/python.exe'),
    'native_executable_sha256': sha(native),
    'kind': 'new-host reproduction freeze; original freeze unchanged',
}
with Path('local-state/my-workload-freeze.json').open('x', encoding='utf-8', newline='\n') as f:
    f.write(json.dumps(freeze, indent=2)+'\n')
'@ | & .venv/Scripts/python.exe -S -
& .venv/Scripts/python.exe -S experiments/workload_observer_probe.py --python .venv/Scripts/python.exe --native "$env:SystemRoot/System32/cmd.exe" --protocol fixtures/workload-observer/protocol.json --freeze local-state/my-workload-freeze.json --output reports/runs/my-workload
& .venv/Scripts/python.exe -S -m scripts.audit_workload_observer --report reports/runs/my-workload/report.json --protocol fixtures/workload-observer/protocol.json --freeze local-state/my-workload-freeze.json --python .venv/Scripts/python.exe --native "$env:SystemRoot/System32/cmd.exe" --output local-state/my-executed-workload-audit.json
```

Execute the fixed six cases once, retain failures, and review them before
designing another version. The cases are two healthy 32/64 MiB controls, a busy
1.5-second timeout, a post-import baseline plus 48 MiB sampled private threshold
with 64 MiB touched payload, exact pre-handshake exit 37 and an authenticated
missing-module/exit 38 control. The bounds are 20 seconds per case, 120 seconds
per suite, cleanup at most 4 seconds within the remaining budget, and maximum
64 MiB manual allocation; Torch/runtime allocation is separate.

Configured 2/2 Torch threads and native thread counts do not identify every
kernel thread. CPU progress measures the worker, not sampler overhead. The
native child has OS/parent evidence but no nonce-bearing self-report; pipe EOF
can contribute to its exit. The memory threshold permits overshoot and is not a
hard ceiling, descendant memory cap or continuous peak measurement. These
controlled cooperative processes do not establish production containment.

Pretrained-model loading, training-harness integration, provider children,
GPU behavior, cost/quality and the historical invalid parent RSS remain open
gates. Any change to frozen experiment files needs a new version and separate
acceptance, preserving the original receipts.
