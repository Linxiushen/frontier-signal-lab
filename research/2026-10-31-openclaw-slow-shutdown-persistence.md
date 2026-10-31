# OpenClaw slow-shutdown persistence landing

- PR: https://github.com/openclaw/openclaw/pull/188920
- Merge commit: `4e55843a8e01be918b282a81193b96633912a858`
- Base/head: `403e12ae73614d77f706a796081127d21e2a2f97` / `7ef7b81f7d8455a7af476b72bdece048c6a88106`
- Captured: `2026-10-31T02:17:09.627053+00:00`

## Facts from the saved first-party API response

The merged change keeps the required connection-work join alive until accepted finalizers settle before Gateway ownership and state admission are released. Session shutdown waits for accepted persistence siblings. The existing shutdown deadline, hard-exit watchdog, marker-before-cancellation ordering and snapshot abort remain in the upstream description. The PR explicitly leaves the production agent-database reopen caller and wider plugin-work fence for follow-up work.

## Evidence boundary

The upstream body reports red base regressions and candidate Node/Bun checks. This project did not check out OpenClaw or execute those tests. The record is therefore source/API evidence only; it does not establish native runtime behavior, provider effects, GPU or production reliability.

## H2 implication

The landing sharpens the required shutdown gate: accepted durable work must retain custody through finalizer settlement. A future H2 run must pin one packaged runtime and verify pre-entry cancellation, already-started writes, lock/state and agent-database custody, current authority, once-only effects, bounded settlement and two real restarts under fixed load and resource limits.

Receipt: `research/receipts/20261031T020126Z-openclaw-slow-shutdown.json`.
