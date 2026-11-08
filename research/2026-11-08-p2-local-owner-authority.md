# p2 local owner authentication: transport location, session identity and work lifetime

This is a source review of [Pi commit 7d073328](https://github.com/earendil-works/pi/commit/7d073328e44337d3292a7db9b0f0308f679c5e97), authored and committed by the GitHub account `mitsuhiko` on 2026-11-08. It changes the implemented p2 server and clients. The captured main ref equals this commit. Its README labels p2 an unsupported experimental prototype whose formats and APIs can change; it supplies no stable production integration contract. The earlier p3 session-resource selection sketches in this repository remain a separate, unbuilt proposal. No upstream code, server, browser, model or test was executed for this review.

## The native caller and the change

A p2 browser, TUI or local script reaches an HTTP/WebSocket server that can hold agent sessions and owner-only operations. On a shared machine, another OS user can also connect to the same loopback port. The adjacent parent `9879bb44754ce42f52800371aac8cfbccf521cb7` still has a cookieless loopback-owner fallback in `apps/p2/src/hosts/server.ts`; the reviewed commit removes that fallback and returns only an authenticator's principal.

The parent already had signed remote-device cookies, persistent revocation and bounded invitations. The distinct change is integrating a credential-proven local session into the actual request resolver. The devices plugin now recognizes signed owner sessions of two kinds. A `local` session grants local-owner access only on a nonremote origin. A device session retains its separate device identity. A browser can redeem a one-use owner link on loopback for a local session. The TUI and scripts instead read the server data directory's `owner-key`, answer a one-use challenge and obtain a session cookie. The client sends HMAC-SHA256 of `p2-local-owner:<port>:<challenge>` rather than transmitting that key. The server makes the data directory mode 0700; owner-key handling uses mode 0600.

`OwnerAccess` keeps at most 32 outstanding challenges, each with a 60-second lifetime. The challenge is consumed before proof comparison, including a wrong answer; the proof includes the server port. Challenges are in memory and are cleared on close or key rotation. These are authentication-challenge bounds. They establish no bound on admitted agent work, queued tasks or model calls.

The signed session includes its kind, random session ID and expiry, with the port included in the signature. Local session cookies last 30 days and an authenticated app-page load renews the same session ID. The source distinguishes a cookie's port-bound validation from browser delivery: browsers send cookies to other ports on the same host. The README explicitly retains exposure to another local user's HTTP server. Its later shorthand that cookies are “port-scoped” should not be read as a browser transport guarantee.

## Revocation has three different scopes

Individual logout persists revocation of a session cookie. The local sessions deliberately share the principal `{kind: "owner", access: "local"}`. Consequently, logging out one local session does **not** invoke the host's live-link revocation: other local sessions' links remain. Device logout can revoke the identified device's live links.

Logout-all rotates the signing key, clears outstanding invitations and challenges, and invokes revocation for both remote and local owner principals. That is a broader live-link/object boundary than individual local logout. The README separately says already-admitted agent work continues. Neither cookie invalidation nor live-link revocation proves cancellation of an already-admitted operation, termination of its physical work, or prevention/rollback of an external effect.

This distinction matters for H2: request authentication, durable authority for a future effect, ownership of a live connection and custody of admitted work require separate checks. The new p2 request-authentication implementation does not upgrade the project's earlier pinned Harness/HTTP recovery experiments, and does not reopen a closed finite experiment gate.

## What the upstream test definitions cover

The changed devices test file defines cases for unauthenticated loopback pages, routes and WebSockets, while `/health` stays open. It also defines wrong-key, one-use and wrong-port challenge controls; tunnel refusal; missing/mismatched data-directory errors; local-session renewal; individual logout; and logout-all followed by local sign-in with the new key. Existing persistence tests reopen `OwnerAccess`, and now include a local cookie.

These are inspected definitions, not test passes observed here. They do not establish the full multi-session workload required by H2, two process restarts under load, effect idempotence, cancellation closure, quality, throughput, tail latency, peak resources or communication costs. The complete changed-path inventory has 98 files; the review captures selected full files and parent context rather than the full dependency or security boundary.

## Engineering decision

The useful integration point is the actual p2 HTTP/WebSocket principal resolver, devices session storage and the TUI/script local-owner client. It provides a concrete implemented authority boundary beyond the earlier p3 sketches. No dependency is adopted and no competing upstream repair is proposed by this source review.

A future H2 study would first freeze a distinct protocol on an exact implemented runtime. It must name the OS users, data-directory and cookie identities, request/authority epochs, concurrent arrivals, admission/queue limits and resource ceilings. It must separately exercise individual and all-session revocation, in-flight work, durable cancellation and idempotent effects across two actual process restarts. It must use a fixed success denominator and report applicable quality/success, useful throughput, end-to-end and tail latency, peak resources/communication and observation cost. These are future admission requirements; no such protocol was frozen or run here.

All existing H1 negative results, failed evaluator and memory/resource limits, H2 closed finite slices and failed concurrent audit, and unmet full H3/H4 requirements remain unchanged. This review advances source knowledge only. It makes no complete-security, production, performance, training-quality or accelerator claim.
