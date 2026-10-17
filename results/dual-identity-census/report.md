# Dual self-path / OS-image census — controlled engineering acceptance

**Both predeclared no-ML cases and the frozen audits pass.** This acceptance covers bounded identity and cleanup controls only. Model loads and optimizer updates are zero; training remains forbidden.

The single suite ran from `2026-10-17T03:00:34.298764+00:00` to `2026-10-17T03:00:35.681458+00:00` in 1.382908100 seconds. It saved five held snapshots and twelve retained process identities. All retained handles exited and both Jobs ended with zero active members.

| Case | Producer runtime flag | Retained exits | Final Job count |
| --- | --- | --- | --- |
| Graceful native census | pass | 5 | 0 |
| Same-image helper rejection | pass | 7 | 0 |

The worker's `sys.executable` file/path matches the frozen venv launcher. Its retained OS process image independently matches the frozen base interpreter. The helper's self-path and OS image independently match base Python; its exact PID/creation role remains unapproved, so the entire Job is terminated. `conhost.exe` and other extras also remain unapproved. The auditor never requires the two identity descriptions to be equal or different.

The portable frozen auditor passes **430/430** checks. The local executable-file rehash mode passes **431/431**. These are receipt consistency checks, not new measurements or proof that rewritten evidence is authentic. [Raw report](report.json), [summary](summary.json), [raw trace hashes](trace-manifest.json), [protocol and reproduction](../../fixtures/dual-identity-census/README.md).

Before freezing, the final protocol clarified that existing repository CPU numerical/CLI regression tests are distinct from the guarded new-census preflight; its original draft date and [change receipt](protocol-prefreeze-clarification.json) are retained. Identity roles, budgets and case order did not change. The producer, tests, final protocol, dependencies, executable file/path hashes and auditor were frozen before this one suite; no retry or post-result threshold change occurred. All 419 repository unit tests passed.

The [previous child-image census](../child-image-census/report.md) remains rejected with its two original audit failures. This new run cannot identify the eight older unrecorded training-run children or repair historical invalid RSS, failed cost/quality screens, or establish continuous coverage/loaded DLL integrity/production reliability. A new narrow-role policy and actual loader/thread/native/provider/healthy/failure/busy/cap/overhead/cleanup controls remain separate training gates.

Report SHA256: `b245d25cc280acfda611c07b8990e56732978a152568b1730fc1c138af0d0863`.
