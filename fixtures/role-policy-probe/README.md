# Fixed stdlib process-role controls

This separately versioned Windows engineering probe adds a narrow admission
policy over the immutable dual-identity census. The policy registers exact
launcher, actual interpreter and native identities, plus exactly one frozen
System32 `conhost.exe` auxiliary for each registered launcher/native owner.
It pins each owner's retained PID and creation time to one auxiliary identity
across held stages. Identified files, basenames and directory categories do not
register additional processes.

The three fixed cases are a graceful positive control, an unregistered
image-identical Python helper, and an unregistered second image-identical native
command. Each rejection case first requires the same successful five-identity
baseline. It passes only when the controlled extra identity and at most one
observed console child cause the rejection; missing approved roles or unrelated
failures cannot substitute for that result.

`protocol.json` declares the exact cases, fixed topology, budgets and limits.
Root must review the new producer, tests and independent auditor, freeze their
bytes and all four executable file/path identities, then run at most one fresh
suite. The prefreeze checks are guarded stdlib/mock tests. No old census,
training experiment, native measurement or live process preflight is part of
those checks.

Every controller receipt forbids training. No Torch, Transformers, model,
provider, GPU or training release path exists. This exact-one console topology
is specific to the declared environment and deliberately rejects other console
arrangements. Held snapshots cannot attest continuous process coverage, loaded
code or production reliability. Older rejected controls, unidentified historical
children and scientific negatives remain unchanged.

The recorded suite passes all three controls and the frozen portable auditor's
1053 checks. See the [result](../../results/role-policy-probe/report.md). The
report auditor reads saved evidence only; a separate post-hoc review checks raw
controller files. Those envelopes have no monotonic emission timestamps, so the
saved chain does not independently timestamp controller emissions.

```bash
python -S -m scripts.audit_role_policy_probe --report results/role-policy-probe/report.json --output reports/role-policy-audit.json
```

For a new Windows execution, supply explicit paths for all four executable
roles. The recorded freeze is tied to its files and opaque canonical paths;
another environment needs a separate reviewed declaration and freeze.

```powershell
& $RolePython -S -X utf8 -m experiments.role_policy_probe --python $RolePython --base-python $RoleBasePython --native $RoleNativeCmd --conhost $RoleConhost --protocol fixtures/role-policy-probe/protocol.json --freeze fixtures/role-policy-probe/implementation.json --output reports/runs/your-new-directory/role-policy-acceptance
```
