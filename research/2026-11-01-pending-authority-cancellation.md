# Pending authority and durable cancellation: prepared, not executed

The next H2 workload returns to the same optional two-Session native
`Harness → Conversation.submit → GenerationTask → official Faux → ToolTask`
service. A separate adapter adds a checkpoint **after the cancellation mark is
committed and before native abort**. The previously frozen admission adapter,
its raw data, acceptance and separate post-outcome supplement remain unchanged.

No native suite or implementation freeze was created on 2026-11-01 02:02Z.
The local preflight observed **451,641,344 free bytes**, below the unchanged
**1,073,741,824-byte** H2 gate. H1's original 5 GiB gate also remains unmet.
This is a prepared implementation and protocol, with no new recovery result or
scientific confidence upgrade. It does not reopen the closed observer work.

The caller is a single trusted host serving two conversations in each of two
independent SQLite Sessions, with capacity two per Session. A lost process can
leave a host-only reservation whose permission has changed, or a durable cancel
mark whose native abort has not happened. Recovery must consume those decisions
before resuming work and eventually release capacity.

The [complete protocol](../experiments/pi_generation_cancellation_protocol.json)
predeclares 18 unique arrivals: 12 host admissions and six overload refusals.
Four host-only requests must never create native submissions: two lose current
authority and two acquire durable cancellation. Eight inputs reach the native
generation/provider/tool chain. Two native inputs are cancelled before effect,
two after effect, and four complete normally; the intended final inventory is
six local effects, each count one, 12 host terminal records, 16 native terminal
tasks and zero active reservations. **These numbers are acceptance targets.**

Three worker processes and two forced kills/reopens cover both pending-authority
and cancellation boundaries. At the first kill, each Session contains one
revoked host-only reservation and one marked, pre-effect native cancellation.
At the second, each contains a marked host-only cancellation and a marked,
post-effect native cancellation. Reconciliation runs before explicit native
resume; it must reuse exact native identities and avoid cancelled tool replay.
The final phase checks normal admission and terminal capacity release. Eight
direct native duplicate probes and host conflict/stale/duplicate controls remain.

The optional sources are
[adapter](../experiments/pi_generation_cancellation_service.mjs),
[worker](../scripts/pi_generation_cancellation_worker.mjs),
[controller](../scripts/run_pi_generation_cancellation.py),
[saved-byte auditor](../experiments/pi_generation_cancellation_audit.py) and
[portable checker](../scripts/check_pi_generation_cancellation.py). The new
auditor includes exact global entry/event counts and effect task identities
before any outcome, informed by the disclosed blind spots in the earlier
frozen auditor. It does not retroactively change that earlier acceptance.

Preparation validation covers 19 Python methods and seven Node tests, including
three calls to the actual adapter method against a **fake Harness**. Those
checks verify commit/checkpoint/abort ordering, the optional hook's default and
unknown-request refusal without opening SQLite or the installed runtime.
Saved historical native graphs exercise identity/cancellation mutations; they
are earlier evidence, not executions of the new workload. Worker syntax and
the unchanged earlier 107-item frozen checker and separate seven-check
post-outcome supplement pass. The complete native workload remains unverified.

When the original resource gate is satisfied, directly review and separately
freeze the complete source/runtime closure, workload and bounds, then invoke
`python scripts/run_pi_generation_cancellation.py --freeze <new-freeze>` once.
Do not reuse any earlier freeze or outcome directory. The prepared controller
retains 90-second suite, 20-second process, eight-second condition, 128 MiB Node
heap, 256 MiB polled private-memory and 20 MiB output bounds. Preserve a failed
first attempt without retries or acceptance changes after seeing its outcome.

If executed, report the host/native/refused/effect denominators, useful work per
full suite and controller wall time, 12-sample descriptive p50/p95/p99,
sampled private memory and OS working-set peak, sampling gaps, callback/flush
cost and raw bytes. No matched baseline or observer-OFF arm is proposed, so no
performance gain or SLO follows. Scope remains one Windows host, official local
Faux and local transactional effects. Real HTTP/models, independent tenant
authentication, concurrent owners, external exactly-once effects, arbitrary
crash-log durability, native busy/submit-error/ID-collision cells, GPU,
distributed and production behavior remain unverified. Histories grow and
reconcile/reap are explicit. H1/H3/H4 and all historical failures are unchanged.
