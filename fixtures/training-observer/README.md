# Pinned pretrained training observer integration

This is a fixed Windows engineering experiment: offline Pythia-14m loading and
exactly two dense AdamW updates in each of three controlled processes. It does
not test compression efficacy, final model quality or comparative training cost.
The earlier frozen probes and their negative results remain unchanged.

The recorded single attempt **failed before model import**: four cases observed
two unexpected descendants each and stopped; only the exact exit37 control
passed. Actual model loads and optimizer updates were both zero. See the
[failure evidence](../../results/training-observer/report.md). The frozen code
and planned training gates remain unvalidated; do not retry this version to
replace its result.

The five ordered cases are healthy completion with a held 64 MiB allocation,
busy model-forward timeout, a sampled post-training private-memory threshold,
exit37 before handshake, and an authenticated injected missing-module exit38.
The last two cases load no pretrained model. The healthy allocation is the
negative control for the private threshold. A full run plans at most three model
loads and six optimizer updates, with no retry or adaptive threshold change.

`protocol.json` fixes the model/assets, train blocks, seed503, batches, AdamW,
cases, deadlines and boundaries. `implementation.json` freezes new code, tests,
historical dependencies, launcher, actual base interpreter and native executable
hashes before execution. No model weights are bundled.

The parent authenticates actual worker PID/creation/ancestry/job membership and
queries its OS image through a retained handle before allowing imports. The
native cmd child is independently checked. Held self/parent/self memory brackets
separate preimport, postimport, postload and postupdate stages; the last includes
validation and parameter hashing, so it is not an isolated backward peak.
Toolhelp inventories are point samples; raw thread counts do not prove thread
ownership or the absence of short-lived provider children. No provider is used.

The private threshold applies after training and permits sampled overshoot.
Idle held windows describe parent query cost with/without sampling; they do not
estimate causal training slowdown or total observer overhead. Neither this
experiment nor its auditor repairs historical parent RSS or cap measurements.

Verify the recorded receipts without Torch, model assets, child processes or
Windows system calls:

```bash
python -S -m scripts.audit_training_observer \
  --report results/training-observer/report.json \
  --protocol fixtures/training-observer/protocol.json \
  --freeze fixtures/training-observer/implementation.json \
  --output reports/training-observer-audit.json
```

The audit checks recorded hashes, identity links, timing, memory algebra,
optimizer counters, expected failures and cleanup. It checks consistency, not
authenticity against coherently rewritten receipts or behavior on another host.
The command above intentionally returns exit1 for this failed recorded run.
Optional local executable arguments additionally rehash the three frozen
Windows binaries, and `--model-dir` rehashes the pinned model assets. Portable
audits omit these four local checks. To verify the preserved negative result:

```bash
python -S -m scripts.audit_training_observer_failure \
  --report results/training-observer/report.json \
  --output reports/training-observer-failure-audit.json
```

This second auditor was written after the run. It checks the pinned failure
receipt and leaves experimental acceptance false; its passing status does not
clear any planned training gate.

Actual re-execution requires Windows, the exact frozen local Python/runtime and
cmd hashes, and all pinned model files already present. Use a fresh output
directory; never replace the recorded run. The PowerShell command is:

```powershell
& $TrainingPython -S -X utf8 experiments/training_observer_probe.py `
  --python $TrainingPython --base-python $BasePython --native $NativeCmd `
  --model-dir $PinnedModelDirectory --fixture fixtures/activation-cost `
  --protocol fixtures/training-observer/protocol.json `
  --freeze fixtures/training-observer/implementation.json `
  --output reports/runs/your-new-directory/training-acceptance
```

Supply the three local executable paths and pinned model directory explicitly.
Changing a frozen binary, package, model, threshold, training setting or protocol
requires a new version and independent declaration. There is no fallback to
network loading, GPU, uncontained processes or a synthetic model.

[Recorded result](../../results/training-observer/report.md) ·
[Research interpretation](../../research/2026-10-16-pretrained-training-observer.md)
