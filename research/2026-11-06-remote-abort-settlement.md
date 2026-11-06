# Pi remote cancellation: local settlement and unknown remote effects

Mario Zechner's Pi commit [c96e368](https://github.com/earendil-works/pi/commit/c96e368e265f886820a68b651b2ec086ecf3906b), dated 2026-11-06 07:55:34Z, changes the actual `RemoteExecutionEnv` → `Connection` → remote daemon path. Its message reports a bash-tool wait while a host rebooted. That incident is the author's report; we did not reproduce it. This review pins parent `d07548004ae12d8dfc3d5817cdbb4f975356aede` and authenticates all six changed paths plus the license, contribution guide and package metadata. The package still says 1.5.0 and the changelog entry is unreleased; a landed commit does not establish a published package or installation in our runtime.

This is a source and test-design review, with zero local upstream tests, native executions, model calls or scientific experiments. The interrupted previous pass discovered the commit metadata; no detailed-source readback was retained from that pass. The source evidence here was actually fetched in this pass.

## The caller now stops waiting at two different boundaries

While a connection starts, `untilAborted` lets a request or `info(signal)` reject on cancellation. It deliberately leaves the shared startup promise running for other callers. Abandoning this wait therefore does not stop platform detection, daemon deployment or the connection start itself.

After a request has been sent, cancellation sends a protocol `CANCEL` and starts a one-second grace timer. A result or error received during that grace still settles the request normally. If no answer arrives, the timer removes that exact pending entry and rejects it as `aborted`; later answers find no pending request and are dropped. Ordinary connection loss remains a separate `unknown` outcome.

`RemoteExecutionEnv.exec` also starts a local timeout before resolving an optional working directory and waiting for the remote request. Timeout-triggered cancellation maps an eventual `aborted` error to `timeout`, and cleanup clears the timer, signal listener and local running-command entry. For an already sent silent request, the cancellation grace can add about a second to the configured timeout, subject to event-loop scheduling. This is no hard deadline or measured service latency. The author's timeout=1 test permits elapsed time below three seconds.

Path resolution, directory listing's feature check and several other connection-info waits now receive the context signal. This does not cover every later file operation: for example, the inspected `createTempDir` still calls `remotePath(connection)` and sends `mkdtemp` without a signal after its first signal-aware info wait. Avoid upgrading this patch into a universal file-operation cancellation guarantee.

SSH argument construction adds `ConnectTimeout=15`. Detection/check/upload commands and protocol readiness have their own timeouts and can involve multiple steps. Fifteen seconds is an SSH connection setting, not a bound on an entire deployment, tool call or recovery.

## Why admission and effect receipts still matter

The practical bottleneck is a tool caller retaining a local task slot while a remote machine stops answering. The patch gives the caller a way to settle that wait. It does not acknowledge that a remote command stopped, roll back a mutation or recover its receipt. After grace expiry, the local pending entry and the environment's running-command entry disappear while the remote outcome can remain unknown.

Our engineering inference is that a bounded agent service must account for these two populations separately: locally pending calls and remote operations whose terminal effect is unresolved. Releasing a local slot alone does not establish a bound on remotely running work. Replaying an uncertain mutation needs durable request identity and an independently recoverable effect receipt; the change supplies neither guarantee. This is a proposed integration criterion, not a demonstrated upstream defect or a claim that this repository promises exactly-once effects.

The source retains a per-frame size limit and connection keepalives. Neither the new cancellation timer nor that frame limit supplies an aggregate pending-call, byte, startup or process-resource ceiling. No throughput, tail-latency, memory, model-quality or production improvement was measured here.

## Validation scope and a possible native integration

The added test file defines seven cases after expanding its two-element loop: two connection cases, four execution cases and one file-read case. Its subprocess scripts either never announce readiness or answer the protocol hello and then remain silent. The definitions cover local settlement and error classification; we read them without running them. They do not reboot an SSH host, execute the actual remote daemon, observe a committed side effect, test concurrent owners or perform two process restarts.

A future study needs a concrete actual caller before admission: a Pi remote tool service with fixed adjacent runtime versions and a bounded workload of healthy, never-ready and silent-after-send operations. Freeze local and unresolved-remote admission ceilings, cancellation times, total attempts, payloads, resources and two restart points. Acceptance must distinguish settled-local, acknowledged-remote-terminal and unknown-effect records, retain exact late-result identities and demonstrate no duplicate committed effect or automatic replay of an uncertain mutation. Report success denominators, effective completed-work throughput, end-to-end and tail latency, peak resources/communication and observation cost against a matched baseline. Native daemon and SSH evidence must be named separately from a scripted transport fixture.

This is not a new observer prerequisite or a registered experiment. Our installed native runtime is unchanged; previously closed finite H2 and evaluation fixtures stay closed. H1 negative results, invalid memory endpoints, prior failed freezes and full H3/H4 unmet gates remain unchanged. Pi requires prior maintainer `lgtm` for new PRs; no issue, PR, comment or admission request was sent.

[Authenticated source identities and review scope](receipts/20261106T105340Z-remote-abort-settlement.json).
