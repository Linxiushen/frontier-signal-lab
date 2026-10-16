# Pretrained training observer integration: FAIL before model import

The single frozen five-case Windows acceptance failed. Four authenticated cases
stopped at the preimport process inventory because each observed two unexpected
descendants. The explicit exit-37 control passed. **No pretrained model was
loaded and no optimizer update ran.** Code for the intended loader and training
integration is published, but that integration has not passed runtime validation.

| Fixed case | Observed result | Wall seconds |
| --- | --- | --- |
| healthy_dense2 | unexpected descendants at preimport; failed | 0.667 |
| dense2_busy_deadline | unexpected descendants at preimport; failed | 0.603 |
| dense2_private_cap64 | unexpected descendants at preimport; failed | 0.602 |
| prehandshake_exit37 | exact exit37, absent handshake; passed | 0.430 |
| injected_import_failure38 | unexpected descendants at preimport; failed before injection | 0.601 |

Actual interval: `2026-10-16T21:03:56.676205+00:00`–
`2026-10-16T21:03:59.901063+00:00`; total **3.225s**. One attempt, zero retries.
The freeze preceded execution at `2026-10-16T21:03:39.632411+00:00`.
Raw report SHA256:
`29213227dbc96d700d73bef4a82eea272b28506d977f5f3d90a3c482c2d397ab`.

Four actual interpreter images were queried through retained OS handles and
matched the frozen base Python hash; their four venv launcher PIDs differed.
Four cmd images and native parent relationships were also verified. Each
preimport inventory then contained five processes where three were expected:
one additional child of the launcher and one additional child of cmd. Their
PID/creation/parent/job/liveness receipts are retained. **Their executable images
were not recorded.** The data cannot identify them as console hosts, Python
helpers or provider processes. No observed child was silently allowed.

All four held preimport self/parent/self memory brackets passed, with a maximum
absolute resident/private discrepancy of 4096 bytes. This says nothing about
model import, training peaks or later allocation stages. All 21 retained process
handles across the five cases exited, with Job active count zero in every case;
the longest recorded cleanup was 0.021023s. This is bounded observed cleanup,
not production containment or proof of an exclusive kill cause.

The frozen success auditor correctly rejects the result: **14 failed checks**,
including failed acceptance, missing later stages and unexpected descendants.
It records 451/465 local consistency checks and 447/461 portable checks passing;
neither is a successful acceptance audit. The four extra local checks rehash the
launcher, base Python, cmd and pinned model assets. The model files were hashed,
not loaded. The separate [post-run failure audit](failure-audit.json) validates
the preserved negative evidence and explicitly keeps acceptance false. It was
written after seeing this result; its passing status is not a preregistered
experimental success.

The planned two dense AdamW steps per model, busy forward timeout, post-training
private threshold, held sampler-overhead windows and precise injected exit38
were **not reached**. No held-out evaluation or checkpoint was produced. The
historical natural-text cost/quality failures and invalid parent RSS remain.

The next gate needs a new protocol version that records OS image/hash and
creation relationships for every observed child before any narrow identity
policy is justified, preserves an unknown-child rejection control, and checks
cleanup of all retained children. Only then can a new frozen attempt address
the unreached loader, training, memory and liveness gates. This run is immutable.

[Code and reproduction](../../fixtures/training-observer/README.md) ·
[Raw report](report.json) · [Derived summary](summary.json) ·
[Raw trace manifest](trace-manifest.json) ·
[Rejected portable success audit](acceptance-audit-portable.json) ·
[Rejected local success audit](acceptance-audit-local.json) ·
[Independent result review](result-review.json) ·
[Failure-auditor review](failure-auditor-review.json) · [Validation](validation.json)
