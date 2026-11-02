# Scope-qualified durable effect resources

The existing H2 loopback effect service has a namespace collision: two independent
Session owners can legitimately produce the same conversation/request key, but
the original effect table uses `key` alone as its primary key. Its authority table
already uses `(scope, conversation)`. On unmodified commit
`2a7eed62ac6676a1cf81beb6b04c696c93593f6f`, an actual background HTTP reproduction
authorizes `service0` and `service1` for conversation `1`. Both send key
`1:same-request`, with identical payloads. The first gets HTTP 201; the second
gets HTTP 409 `identity-conflict`. GET returns the first scope's receipt. The
existing client's complete receipt check rejects that foreign identity. This is
a collision that prevents legitimate progress; it does not demonstrate an
unauthorized mutation. Earlier native fixtures used service-specific request IDs,
which avoided this case.

## Caller, integration and bounded repair

The caller is the existing `openGenerationService` / `makeEffectDispatcher`
integration, which turns durable host intents into separately persisted HTTP
effects. Repeated native numeric IDs are local to each Session. As independently
owned Session databases share one effect endpoint, unqualified keys collide.
No throughput or capacity improvement is claimed.

The opt-in `pi_scoped_effect_http_server.py` uses a separate
`effects-scoped.sqlite`, schema version 2, and a composite `(scope, key)` primary
key. Reads, writes, held replies and attempt records include the same scope.
Resources use `/effects/<scope>/<encoded-key>`. POST requires the path and full
payload identity to agree. The server rejects the legacy effects schema and v1
protocol header; it does not migrate or rewrite an old database.

`pi_scoped_effect_http_client.mjs` requires an explicit stable scope and validates
the complete receipt with the existing identity implementation. It retains
bounded loopback transport and refuses foreign-scope identities before network
I/O. Inject it through the existing `effectClient` parameter, with the same
`effectScope`. The convenience `openScopedGenerationService` constructs that
pair and delegates to the unchanged native owner. That wrapper has source review
only; this pass did not open a native Session through it.

```js
import { createEffectClient } from '../experiments/pi_scoped_effect_http_client.mjs';
// Persist this namespace alongside the host database; reuse it across reopens.
const effectScope = 'service0';
const effectClient = createEffectClient(effectBase, { scope: effectScope });
// Existing caller: openGenerationService({ ...options, effectScope, effectClient });
```

Start the separately named server with an existing empty output directory:

```sh
python -B -S experiments/pi_scoped_effect_http_server.py --output /tmp/scoped-effects --stage 0
```

It binds an ephemeral `127.0.0.1` port and writes its actual base URL to
`effect-server0-ready.json`. A trusted host sets current authority separately for
each scope. The fixture header is a protocol discriminator, not authentication;
administrative snapshot/authority controls remain trusted local controls.

## Verification and limits

The baseline failure and exact test receipts are retained under
[`receipts/20261102T210823Z-scoped-effect-namespace/`](receipts/20261102T210823Z-scoped-effect-namespace/).
The repair criteria were defined before the regressions: independent same-key
effects in two scopes, exact replay count 1, conflicting identity refusal,
current-authority refusal, historical receipt recovery after revocation, durable
reopen, and refusal of legacy schema/protocol and path/body mismatches.

Run the focused regression sets without ML dependencies:

```sh
python -B -S -m unittest tests.test_pi_scoped_effect_http_server tests.test_pi_effect_http_server -v
node --test tests/pi_scoped_effect_http.test.mjs tests/pi_effect_http.test.mjs
```

Set `FRONTIER_TEST_PYTHON` to the Python executable when it is not on PATH. The
Node regression starts and stops only its own hidden background Python server.
It exercises real HTTP and SQLite through the original dispatcher, with an
in-memory Harness test double. Two scopes with the same key and different
payloads both commit; wrong-path, wrong-scope and legacy requests fail without
mutation. A held reply commits before a client abort; the other scope's same key
is not held, and a later lookup recovers the original receipt. Separate Node
HTTP checks cover wrong receipt, malformed response, byte ceiling and wall
deadline. Python checks cover store reopen and non-destructive legacy refusal.
These are engineering regressions, not a native cancellation/restart experiment.

Final focused results are 12/12 Python tests (7 new, 5 adjacent) and 12/12 Node
tests (3 new, 9 adjacent), with no skips. The first Python invocation exposed an
unclosed connection in the new test's own cleanup on Windows; the test now uses
the store's closing context manager. That initial error is retained in the
receipt. The production modules did not change between those two invocations.

The bounded prerequisite ends at this transport/store repair. Future adoption
must return to a separately justified actual-runner integration or native
authority/cancellation protocol, with bounded admission and two process reopens.
There is no new native, model, GPU, multi-owner, tenant isolation, production or
performance evidence in this pass. All hypotheses, scientific gates and prior
frozen sources/results remain unchanged, including the failed concurrent H2
freeze and its separate saved-only observations. The old serial accepted result
remains historical. Rollback is to continue using the original module and its
original database; do not reinterpret either schema under the other protocol.
