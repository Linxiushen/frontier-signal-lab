# Active disk Move now has a landed custody handoff implementation

OpenClaw [#189350](https://github.com/openclaw/openclaw/pull/189350) landed as `af7cee29336523d3f8c2f3ae5c6af5f55e570772` (commit dated 2026-11-01 06:23:16 UTC; merged 06:23:17 UTC), single adjacent parent `92d75eec930aa976eb6758e262a99b2ef5eae0da`. GitHub records roboclaw-bot; the PR credits galiniliev. This advances the previously recorded explicit final-Move implementation gap, while disk mode remains unselectable and paused preparation stays open.

The existing authorized `sessions.move` route obtains a reclaim result and current owner fences, captures the exact original attached disk, retains its fresh export in the pending result, and binds the verified managed worktree/session. The repository owner then retires disk custody under the exact intent/result/receipt claim; original environment cleanup and pending-result completion remain with their existing owners. Before binding, interrupted recovery captures the original disk again and refuses an unknown local HEAD. After binding, it preserves the worktree and resumes retirement/cleanup without recapture or artifact reapplication.

The complete changed inventory has 37 paths. Fifteen relevant paths have 29 full head/parent bodies and one metadata-confirmed added-file parent absence; all fifteen candidate bodies equal landed bytes. The scope covers actual caller/materializer/settlement/recovery changes and the new thirteen-scenario test design, not an exhaustive audit of every dependency. Raw and gzip hashes are retained in the manifest/verdict.

The test uses the actual authorization entry and local Git/native-store fixtures, with synthetic provider destruction and GitHub identity. Its interruption/restart design uses spies and same-process store/harness recreation; it does not establish an OS kill/restart. The author's current 25-case and earlier 13-case execution claims remain external. No current-head hosted CI pass or local test/native/model/cloud run is claimed here.

This is an additive source implementation finding only. It does not establish concurrent-owner serialization, arbitrary crash recovery, real provider deletion, paused wake, external effects exactly once, production scale or model quality. Existing H2 scientific status and the prepared same-service pending-authority/cancel-mark caller remain unchanged behind the original resource gate; no additional observer prerequisite is introduced.

Version and hash evidence: [curated source receipt](receipts/20261101T080614Z-repository-disk-custody-source-review.json).
