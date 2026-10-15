# pi context transformation probe

Runs both complete, unchanged upstream TypeScript files directly. No runtime imports, module hooks, substitutions or normalization callback are used.

| Trace | Parent exact oracle | Merged exact oracle | Parent desired boundary | Merged desired boundary | Inputs unchanged |
|---|---|---|---|---|---|
| same_identity_opaque_reasoning | true | true | true | true | true |
| model_identity_change_tools | true | true | false | true | true |
| provider_identity_change | true | true | false | true | true |
| api_identity_change | true | true | false | true | true |
| alternating_models_a_b_a | true | true | false | true | true |
| error_and_aborted_turns | true | true | true | true | true |
| complete_tools_with_system_message | true | true | true | true | true |
| unsigned_blank_thinking | true | true | true | true | true |

The authentic parent is an expected negative control: readable reasoning from another model becomes visible text in four traces. The merged version drops it. Same-identity signed/redacted empty blocks, ordinary text and complete tool-call/results match their exact oracles.

Traces: 8; module executions: 16; merged boundary failures: 0.

Result SHA256 (canonical JSON excluding result_sha256): `515d9b4ed33baf53af338946ffe2c2d633ea1081b3308cc2b34a284ced9f2cab`.

## Scope

Only transformMessages context transformation. No provider requests, full harness, signature validation or model behavior measured.

- Opaque signatures and redaction flags are synthetic sentinels; retaining them does not establish cryptographic or provider validity.
- The authentic parent intentionally fails the desired no-foreign-thinking-as-visible-text boundary on four traces; that expected negative result is preserved.
- Every successful tool-call fixture has matching results. Orphan synthesis, its Date.now timestamp and optional ID normalizer are not exercised.
- The complete modules also export splitErrorToolResultImages; that separate helper and image downgrade/null normalization branches are not exercised.
- Eight bounded fixtures do not establish transport acceptance, actual model handoff, persistence, liveness, quality, token cost or production reliability.
- The upstream fix predates this pass and is not a new merge or our algorithmic invention.
