# Pi MCP stdio framing: source-only engineering review

This is a completed source review of an older landed change, first captured by the interrupted 2026-11-04 09:44Z round. It is not a new release today. No Pi code, tests, benchmark, native subprocess, model or scientific workload was executed in this lane.

## Exact identity and attribution

- Repository: `earendil-works/pi`; package `@earendil-works/pi-mcp` at version 1.5.0 in the pinned source, MIT. The root license credits Mario Zechner, 2025; this is not evidence Mario authored this fix.
- PR [11791](https://github.com/earendil-works/pi/pull/11791), `fix(mcp): read large stdio messages in linear time`, authored by `robopipi[bot]`, merged 2026-11-04T09:09:24Z.
- Landed commit `f6278a472e9b97579e9e9ef512303aa91a926a67`, parent `f4427f8a3edd0de0332e44fed9e53d4f37ae0953`. Both changed paths reviewed completely: reader implementation and its added unit test file.
- Origin [issue 11761](https://github.com/earendil-works/pi/issues/11761) is by `lishuangqiang`, created 2026-11-04T00:42:43Z, closed when the fix landed. The issue explicitly discloses AI assistance. The PR says it was requested by `@badlogic`; that statement is the PR author's attribution, not a new independently verified maintainer conversation.
- Eleven full saved source/policy versions were read and verified byte for byte against the prior GitHub JSON response, decoded content and Git blob SHA1: old/new reader, added tests, real stdio and pipe callers, package, transport interface, JSON-RPC parser, AGENTS, CONTRIBUTING and LICENSE. Full versions and original HTTP receipts remain under `reports/runs/20261104T094436Z/radar`; the [curated receipt](receipts/20261105T004019Z-pi-framing-source-review.json) binds the immutable versions and original observation receipts.
- All 225 curated source objects were checked using PR, issue, commit and mechanism terms; there was no existing matching source object. The exact source-dedup supplement found no match; an earlier search included an unrelated issue number and is preserved in the raw receipt. This curated review appends one source object and changes no hypothesis.

## Fact from implementation

The real [`StdioTransport`](https://github.com/earendil-works/pi/blob/f6278a472e9b97579e9e9ef512303aa91a926a67/packages/mcp/src/transports/stdio.ts) feeds child stdout chunks to `JsonRpcLineReader.readStdout`. `PipeTransport` feeds the same reader from `McpPipeHandlers.onStdout`; both call `end()` on exit. The default message limit in the pinned transport interface is 16 MiB.

The parent implementation appends each chunk with `Buffer.concat` and scans the entire accumulated incomplete message from byte zero. With fixed-size chunks and no newline until the end, the prefix is copied and scanned repeatedly.

The [landed reader](https://github.com/earendil-works/pi/blob/f6278a472e9b97579e9e9ef512303aa91a926a67/packages/mcp/src/transports/lines.ts) stores copied incomplete tails as `Buffer[]` plus `stdoutPendingBytes`, scans only the new `Uint8Array` region, and concatenates the pending chunks once when a delimiter completes that line. A complete line contained in the incoming chunk is sliced directly. Incomplete tails are copied because a caller may reuse the input storage. Existing UTF-8 decoding, CRLF trimming, blank-line skipping, JSON-RPC parsing and error callback behavior remain in the path. Pending-byte overflow resets the stored queue; this is source-level behavior rather than proof of a complete oversized-frame discard protocol.

The four [added test definitions](https://github.com/earendil-works/pi/blob/f6278a472e9b97579e9e9ef512303aa91a926a67/packages/mcp/test/lines.test.ts) check one concat for a 1 MiB message fed in 4 KiB pieces, mixed multi-byte UTF-8/CRLF/blank/invalid/multiple lines across every positive chunk size of a finite input, recovery after oversized data, and incomplete-message error at end. Reading these assertions is not a passing local test result.

## Author reports and our inference

The PR reports 64 KiB chunk microbenchmarks for 1/4/12 MiB messages: before 5.4/49.9/348 ms; after 2.2/7.9/21.6 ms. Its tests and root check are reported as passing by the author. The origin issue, at a different old commit and macOS/Node24.20 environment, reports cumulative concat output about 1.23 GB versus 12.6 MB and separate parser/subprocess timings. These are distinct author measurement scopes and must not be combined into a local or end-to-end result. Cumulative copy volume is explicitly not peak memory or a leak.

Our source inference: this removes repeated growing-prefix work in a real MCP receive path and supplies a concrete integration point when large tool results dominate framing. The pending byte limit does not bound incoming chunk allocation, retained chunk-object overhead, delimiter-time concatenation, UTF-8 strings, JSON objects, all concurrent readers, or process peak memory. The code retains current transport delivery and close mechanisms; it does not add bounded aggregate admission, flow control, durable effects, two-restart recovery, current authority, scorer version identity or model-quality evidence. No local performance conclusion follows.

## Candidate engineering boundary, not a new experiment

Actual caller/load: a future separately justified MCP runner integration using real `StdioTransport`/`PipeTransport`, a fixed distribution of small control messages and large valid tool results, and fixed chunk boundaries. Bottleneck: repeated prefix copy/scan and cross-reader retained data at scale. Native rollback: retain the pinned parent reader behind the integration's explicit version selection; this review changes neither upstream nor local runtime.

Before any run, preregister decoded-message/error sequence equality, byte/frame limits and post-error semantics, cumulative copy/scan counters, useful message throughput, terminal success/failure denominators, end-to-end and tail latency, retained-interpreter resource maxima and observation cost under fixed resource ceilings. A restart/authority/receipt question requires additional caller-level controls; a parser microbenchmark cannot close it. Resource failure in the present native evaluation preparation stays a blocker, and this source review does not create another observer prerequisite or justify rerunning accepted H2 workloads.

Validated level: complete pinned source and author-test-design review only. Local tests0; native/provider/model runs0; scientific experiments0; H1-H4 scientific statuses unchanged. Pi's source contribution policy requires prior maintainer `lgtm` for new PRs; this review is not contribution admission and sends no issue, PR or comment.
