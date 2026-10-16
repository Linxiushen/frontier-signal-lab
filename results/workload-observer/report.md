# CPU Torch workload observer: PASS

One frozen six-case Windows engineering acceptance, executed once. No pretrained model, compression study, historical rerun, provider or GPU is involved. Constants replace RNG.

| Case | Outcome | Gate | Wall seconds |
| --- | --- | --- | --- |
| healthy32 | normal_completion | pass | 6.065 |
| healthy64 | normal_completion | pass | 6.364 |
| busy_timeout | timeout | pass | 8.318 |
| busy_private_cap64 | memory_private_limit | pass | 5.718 |
| prehandshake_exit37 | expected_prehandshake_exit37 | pass | 0.353 |
| injected_import_failure38 | expected_injected_import_failure38 | pass | 0.479 |

Actual interval: `2026-10-16T19:08:14.855082+00:00`–`2026-10-16T19:08:42.400619+00:00`; total 27.545s. Report SHA256: `e4de046a3653b7a7f16006344ce9b43556097c67d00bfbb10da07bd907a2837c`.

4 real CPU Torch forward/backward/SGD updates were recorded across the four workload cases. 5 interpreters and 5 native descendants were authenticated after handshake; 5 launcher/interpreter pairs differ. The exit-37 control deliberately has no actual-interpreter identity.

8 held memory brackets were recorded; maximum absolute resident/private parent–self difference 4096 bytes. These are synchronized controlled readings, not continuous peaks or model-training measurements.

Offline audit: pass, 9316 checks, with both original executable files rehashed locally. This is receipt consistency, not independent-host replication. The portable CI audit omits those two optional local binary checks.

The timeout requires sampled native CPU progress; the cap is a sampled post-import baseline plus 48 MiB threshold, permits overshoot and is checked with a 64 MiB healthy negative control. Native pipe EOF can contribute to descendant exit after whole-job termination. Raw native thread counts and Torch 2/2 settings do not prove exact kernel-thread ownership; parent sampler overhead is unmeasured.

Historical natural-text cost/final-quality failures and invalid parent RSS remain unchanged. Pretrained loading, actual training-harness integration, provider children, GPU behavior and production containment remain separate gates.

[Protocol and reproduction](../../fixtures/workload-observer/README.md) · [Full receipt](report.json) · [Derived summary](summary.json) · [Offline audit](independent-audit.json) · [Independent source review](code-review.json) · [Second source review](second-code-review.json) · [Auditor review](auditor-review.json)

The worker runtime-file hash comes from sys.executable, which names the venv launcher here; it is not an OS query of the actual worker image. Only the native cmd image receives that separate OS image/path/hash check. Actual worker PID/creation/handle and memory identity remain the checked observer contract.
