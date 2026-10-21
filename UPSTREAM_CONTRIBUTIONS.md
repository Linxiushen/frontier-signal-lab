# Upstream AI contributions

The user requested stronger, ongoing PR contributions on 2026-10-19, prioritizing AI open source from leading AI companies and research labs. This authorization covers implementing, testing, publishing and maintaining relevant PRs through `Linxiushen` forks. The former no-upstream-PR restriction in this research task is superseded. This is an ongoing contribution stream; the separate campaign's completed 50-PR target is not a stopping condition here.

## Scope and priorities

Use `contributions/targets.json` as the discovery queue. Verify each selected repository's current official owner, public status, license, maintenance activity and contribution rules before admitting it. The queue is a list of candidates, not a claim that every repository accepts our proposed change. Company reputation helps discovery; user impact and reproducible evidence determine selection.

Prioritize inference and training correctness, numerical stability, evaluation/scoring consistency, tokenization, model/data interoperability, agent tool execution, cancellation, streaming, durable recovery and multimodal data processing. A performance claim needs a valid baseline and reproducible measurements on supported hardware. CPU or offline SDK regression tests are useful when they exercise the actual affected code. A mocked provider test does not validate a real model or service.

The user's 2026-10-21 engineering direction also applies to candidate selection. Record the actual caller, the failure or cost amplified by scale, the patch's integration point and the validation that can establish its effect. Prefer substantive fixes in real batching/variable-length paths, numerical optimization, scheduling/backpressure, streaming cancellation, cache lifetime, durable recovery/idempotency and evaluation/data consistency. Follow `research/engineering-roadmap.md`; measure applicable end-to-end costs and state local versus GPU/distributed validation limits. A bounded CPU or SDK fix can be valuable without claiming scale performance or requiring unavailable hardware.

## Work intensity

Keep the existing two-hour heartbeat and increase the work performed within it. Each pass checks recent evidence and pending contributions, then screens 6–10 candidate repositories across at least three relevant organizations when public access permits. Reuse still-current metadata; do not repeatedly download unchanged trees. Deeply inspect up to three independent concrete candidates in parallel and take suitable fixes through reproduction, code, tests, review and publication. Resume useful unfinished fixes before replacing them with more news.

Submit every independently validated change that is ready within those lanes. There is no lifetime PR quota after which new contributions stop. Do not turn screening counts into mandatory PR counts, split one fix into several PRs, or submit cosmetic changes merely to raise volume. If no candidate is ready, retain the actual work and specific blockers rather than an empty publication.

The research limit of at most one scientific experiment per pass still applies to H1–H4. Ordinary upstream bug reproductions, unit/regression tests and reviewer-requested corrections are contribution engineering and do not consume that scientific-experiment slot. Conversely, calling model training a regression test does not bypass the research protocol.

## Before changing code

1. Check the user's GitHub PRs, current upstream issues and open/closed PRs for duplicates, maintainer decisions and work already in progress. Search truncation is a coverage gap. Inspect a candidate's exact current base, contribution guide, AI assistance policy, test workflow and any relevant maintainer discussion.
2. Prefer a concrete user-facing defect with a small failing reproduction or an explicitly accepted feature. Respect requests for prior issue approval; an unapproved proposal stays local. Do not create unrelated issues or soliciting messages to manufacture activity.
3. Create a separate checkout under ignored `local-state/upstream/` with a `codex/` branch. Do not mutate another task's checkout, branch, fork PR or ledger. The research repository's sole `origin` remains `Linxiushen/frontier-signal-lab`.
4. Record the issue/source URL, base SHA, ownership/license evidence, contribution policy, expected behavior and relevant test command before implementing. Do not reuse the other PR task's historical tests as current validation.

## Publication and follow-through

Require a reproducible failure on the unchanged supported base, a focused fix, passing meaningful regression/nearby tests, and exact-diff review. If a feature has no failing baseline, document its accepted behavior and validation instead. Follow project formatting, generated-code and changelog conventions; disclose AI assistance where requested. Do not attest to human testing, contributor identity, DCO or CLA agreements without the user's actual action. No paid GPU/API calls or purchases are authorized.

Use the user's fork and a dedicated branch; never push to an upstream default/protected branch or merge upstream. Immediately before creating a PR, recheck duplicates and unresolved publication attempts. Save the exact title/body/base/head, create once, read back the PR URL and commit, attach the PR to this chat and inspect CI. A fork push is not a submitted PR; queued/permission-gated CI is not a pass. Unknown creation results must be reconciled before retrying.

PR descriptions explain the concrete defect or accepted behavior, reproduction, fix, validation and practical limits. Do not advertise SaveScope, claim company affiliation, paste template praise or infer novelty. Answer substantive feedback on PRs owned by this task, update the patch/tests and read back the result. Do not send repetitive review pings, private outreach or social posts. Requests for agreements or genuinely missing user facts are reported with the exact link.

## Coordination and measurement

The existing PR task in `C:/Users/somle/Documents/github PR提交` maintains its existing contributions and summaries. Read its contribution inventory only when useful for deduplication; do not change its files, automations, messages or PR branches from this task. Global GitHub search is the final duplicate check. This task owns only the new contributions it records locally, so it can maintain them without competing with that task.

Keep a local `local-state/upstream-contributions.json` ledger: repository, issue/source, exact base/head, branch, reproduction/tests, review, policy/license, publication attempt, verified URL, CI and next action. Preserve human/concurrent edits with rereads and atomic updates. Record actual counts separately for screened, reproduced, ready, submitted, updated, merged, rejected/closed and blocked. Do not count existing-PR maintenance, a draft branch or an unresolved attempt as a new PR. Measure acceptance and useful maintainer feedback alongside submission volume.

Publish selected original reusable research improvements here when warranted. Never commit copied upstream checkouts, raw rolling runs, credentials or local state. Notify in this chat for a verified PR submission/merge, substantive feedback or repair, meaningful research result, real failure or required user action; otherwise record locally. Scheduling is a polling configuration, not a guarantee of throughput or future successful execution.
