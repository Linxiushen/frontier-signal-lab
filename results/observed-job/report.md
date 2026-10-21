# Native ledger integration: failed topology admission

One separately frozen Windows native run failed on 2026-10-21. The existing
`WindowsJob` and bounded thread-safe ledger were composed in an experimental
`ObservedWindowsJob` adapter. This addresses the training observer's concrete
need to serialize concurrent native reads, trace sequence and cleanup under
diagnostic failure. It is a step toward the actual training caller; the adapter
has not been connected to that pretrained training loop.

## Fixed workload and acceptance

The protocol was frozen at **11:54:44.489736 UTC**, before the producer interval
**11:54:45.467199–11:54:45.769820 UTC**. It declared one native worker per Job,
four sampling threads × eight calls (34 lifecycle/sample rows), then one-row
capacity and five-byte partial-write fault cases, in that order. Limits were
64 rows, 32,768 bytes per row, 1,048,576 committed bytes, 3 s handshake, 10 s
worker backstop, 4 s cooperative cleanup and 25 s suite ceiling. Stop on first
unexpected failure, one execution, no retries or model loads.

Acceptance required all three native cases, exact request identities and
contiguous canonical events, refusal after trace faults, retained worker exits,
empty Job accounting and both handle-close paths. A separate saved-byte auditor
had to accept the result. This was correctness/cleanup admission; no matched
baseline or useful-throughput, tail-latency or resource benefit was tested.

## Observed outcome

| Item | Saved observation |
| --- | --- |
| Native cases | 1 failed; capacity and partial-write cases not run |
| Worker | PID 17736, creation FILETIME 134370572854742801, parent 3084; native/self image hashes match the frozen Python |
| Topology | Native Job membership true; active count **2**, frozen expectation **1** |
| Sampling | No sampler thread IDs, sample rows, stop command or finished receipt; source order stops before sampling |
| Trace | Two canonical rows, `started`/`closed`, seq 0/1, 521 bytes; no I/O failure |
| Cleanup | Retained worker exited `57347` (`0xE003`), Job accounting 0, both close paths reported successful |
| Science | 0 H1–H4 scientific experiments, model loads and optimizer updates |

The extra process's identity was **not captured**. This run cannot attribute it
to a console auxiliary or give it a per-process exit receipt. The generic
`AssertionError: ` lacks a stack or assertion label. Saved preceding identity
fields and frozen source order locate the mismatch; this diagnosis is a
post-outcome review, not an additional runtime observation.

`trace_complete: true` means only that the two attempted lifecycle writes had
no ledger error. It does not mean all planned samples/cases completed. The
unchanged frozen acceptance auditor rejects this report. The later preservation
checker verifies failure, exact sources/bytes, stopped cases and saved cleanup;
its successful exit is **not native acceptance**.

Before this run, seven adapter mock controls, ten ledger controls and 38 native
observer mock controls passed (55 relevant unique cases, no skips). The base
suite ran 946 cases: 865 passed, 81 skipped. A final seven-control adapter rerun
covered the added failed-launch retry assertion. These tests did not detect
the actual one-process topology assumption. Later preservation controls are
reported separately and run no native work. All reviews were by the same agent;
the separate auditor shares neither producer imports nor runtime execution.

## Saved evidence and next gate

[`raw/report.json`](raw/report.json) and its first-case files are byte copies of
the failed output. [`native-execution.json`](native-execution.json) records exit
1; [`rejection-execution.json`](rejection-execution.json) records the frozen
auditor's exit 1. The [fixture](../../fixtures/observed-job/README.md) gives the
offline commands and exact freeze. Hashes:

- Protocol: `49cf4a850da7881a150f2808a8229ab711080c4c980cbdfe00b5fdec40ba95c9`
- Freeze: `66c3f25c04491da1bedabd20490337bc106b109b14e5d88745b83fe6b26b037a`
- Trace: `3379ae06fe7d65ac179d6031ddf6701c1b1608ce587976e7867e5d4ae813f510`

Next, separately freeze the same native integration with the existing explicit
role census/retained identity policy and labelled failure receipts. Do not add
another general-purpose diagnostic subsystem or retrospectively identify the
unrecorded process. Once native thread/fault/cleanup admission passes, return to
the real training entry point and predeclare matched full-cost/quality work.

This failure does not change the six failed H1 cost/final-quality screens,
invalid historical parent RSS, unmet H2 runtime/two-restart gates or H3/H4 planned
status. No GPU, distributed or production result is claimed.
