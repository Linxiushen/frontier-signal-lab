# pi context transformation source

These are the complete, unchanged MIT-licensed `packages/ai/src/api/transform-messages.ts` files from the authentic parent `5ab7fe74c400097b386662205cd93900695b8a71` and merged `911309429175254550837167baee245d5f9dbcb6` of [pi PR 11000](https://github.com/earendil-works/pi/pull/11000), authored and merged by `davidbrai`. Copyright attribution remains with Mario Zechner as stated in the upstream license.

`provenance.json` pins the URLs, fetch intervals and SHA256 hashes. Both source files were checked byte-for-byte against fetched UTF-8 source. The license adds a final LF to the fetched text; its recorded hash covers the local file.

The experiment imports both `.ts` files directly with native Node TypeScript support. Their sole import is erased `import type`; there are no runtime dependencies or substitutions. It calls `transformMessages(messages, model)` without the optional ID normalizer. Every tool-call fixture supplies real fixture results, so nondeterministic orphan-result timestamps are not exercised.

This covers the context transformation primitive. No model/provider request, signature validation, streaming transport, actual model handoff, harness, recovery, quality or token-cost result is established. Opaque signature strings are synthetic fixture sentinels.
