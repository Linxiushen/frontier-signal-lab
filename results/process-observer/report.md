# Windows interpreter observer: five controlled cases passed

One frozen stdlib engineering acceptance ran **2026-10-16T16:58:13.646781+00:00–2026-10-16T16:58:19.466673+00:00**, in 5.819657s, on Windows-10-10.0.19045-SP0, Python3.12.14. No model, training, dataset, GPU or paid API was involved. This is a separate observer version; historical cost code and results remain unchanged.

| Case | Launcher / interpreter PID | Observed resident / private increase, bytes | Largest self-parent difference, bytes | Cleanup seconds | Gate |
|---|---|---:|---:|---:|---|
| healthy32 | 52504 / 36024 | 33562624 / 33619968 | 0 | 0.041345 | pass |
| healthy64 | 40852 / 23660 | 67117056 / 67239936 | 0 | 0.020770 | pass |
| private_cap64 | 47300 / 23740 | 67117056 / 67239936 | 0 | 0.021195 | pass |
| timeout_descendant | 56676 / 10856 | 4096 / 0 | 4096 | 0.021215 | pass |
| job_close_descendant | 53792 / 40400 | 0 / 0 | 8192 | 0.042034 | pass |

All five launchers differed from their actual interpreters. Every handshake retained a native handle, nonce, creation FILETIME, native parent chain and live job membership. Each case also authenticated its descendant and descendant launcher. The maximum self-before/parent/self-after discrepancy was8192bytes, inside the predeclared4MiB tolerance. These are synchronized controlled readings, not continuous peaks.

The two healthy controls touched32/64MiB and completed with all four retained exit codes0 and job active count0. The cap case touched64MiB after a baseline, crossed the actual interpreter's private-byte threshold **62418944bytes** (baseline+48MiB), and returned from TerminateJobObject **0.051469100s** after allocation-ready. All four retained process objects then exited and the job count became0. The controlled allocation can overshoot the48MiB increment before polling; this is **sampled threshold enforcement, not a kernel hard ceiling** or a limit on every descendant's memory.

The timeout case waited **1.511455200s** after its stalled barrier before whole-job termination. The explicit-close case closed the sole noninherited JobObject handle using KILL_ON_JOB_CLOSE, without TerminateJobObject; all retained process objects exited. Active job count is deliberately **null after close**, because that handle is no longer queryable. Exit code0 in this close control is not relabeled normal completion: live membership was checked immediately before close, and the worker's backstop was30s. Every recorded cleanup completed within4s. This finite cooperative suite is not adversarial escape or production reliability proof.

The [protocol](../../fixtures/process-observer/protocol.json) was declared16:43:12Z; [implementation](../../fixtures/process-observer/implementation.json) frozen16:58:04.591760Z, before the single acceptance. There were no retries, case replacements or tolerance changes. Fixed cases/allocations use no statistical seed;10fresh256-bit nonces bind process messages and are retained in the full trace. PIDs, FILETIMEs, timings and memory totals vary between runs.

The source was reviewed by a second local agent, including close-failure retry, launch cleanup and live-descendant negative controls.38mock tests passed; a base full suite265tests passed, and8new offline auditor tests separately passed. These are separate executions with overlap, not a claimed273-test full-suite run. The portable [auditor](../../scripts/audit_process_observer.py) passed **1170receipt/hash/algebra checks**; it neither remeasures Windows nor authenticates coherently rewritten evidence.

The new observer has **not been integrated into a training harness**. Native PyTorch/thread/provider/GPU descendants, crash-before-handshake, uncooperative child behavior and future workload sampling remain separate gates. This does not repair the old [invalid parent RSS evidence](../activation-cost/measurement-validity.json), establish measured training peak memory, or change any failed scientific screen. SaveScopev0.1's API remains fresh-state numerical auditing.

See [execution and portable receipt verification](../../fixtures/process-observer/README.md), [full trace](report.json), [offline audit](independent-audit.json), [local-agent code review](code-review.json) and [file hashes](SHA256SUMS).
