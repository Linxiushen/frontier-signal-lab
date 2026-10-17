# Codec allocation diagnostic: stopped before model import

The sole frozen suite failed at its first `preimport` gate. **No model was
loaded; no forward, backward, allocation trace, or optimizer update ran.**
There is no new compression cost, memory or quality result.

The first OFF/dense worker reported a local capability-probe **budget of 1**
and **usage of 0**. The parent passed `0` as the existing validator's
`expected_budget` argument. That validator already derives usage zero from
the preimport phase. The worker's valid budget therefore failed the parent's
check. This is our integration error, rather than evidence of an unauthorized
provider operation. The frozen producer is preserved with that error.

| Recorded item | Outcome |
| --- | --- |
| Protocol declared / implementation frozen (UTC) | 2026-10-17 23:17:44 / 23:20:59 |
| Actual suite (UTC) | 23:21:05.078742–23:21:05.549725 |
| Planned / attempted cases | 8 / 1; stopped on first failure |
| Preimport thread count | 4, within declared ceiling 32 |
| Model loads / forwards / backwards / updates | 0 / 0 / 0 / 0 |
| Controller releases / accepted stages / allocation traces | 0 / 0 / 0 |
| Retained launcher and interpreter | Both terminated, exit code 57347 each; Job active count 0 |
| Actual retries | 0 |
| Frozen saved-receipt audit | 42/42 consistency checks; execution acceptance **false** |

The [four original JSON files](original-manifest.json) are copied byte for
byte. The raw [preimport receipt](01_off_dense/preimport-ready.json) is
important: the frozen producer rejected it before inserting it into the
top-level `stages` map. The frozen audit checks that empty failed prefix and
the original file hashes; it does **not** independently validate this omitted
receipt or the failure cleanup. A separately identified post-outcome
[review and audit](independent-review.json) covers those observations.

The 27 guarded prefreeze tests passed but missed this caller/validator
contract error. Separate post-outcome regressions execute the frozen
`run_case` branch against an in-memory Job and the saved receipt. They show
the actual zero-budget call, rejection before inventory/release, and acceptance
of the same guard with budget one. They do not repair or rerun the experiment.

All three predeclared allocation/gradient receipt mutations are **unperformed**:
there is no raw allocation trace, poststudy receipt, or gradient digest to
mutate. Post-outcome raw-failure audit mutations are recorded separately and
are not substitutes for those controls.

The intended study used pinned Pythia-14m CPU float32, seed 503, natural-text
blocks 116/73, one forward/exact-CE/backward per worker, and no optimizer or
holdout. OFF dense/INT8/INT8/dense then ON dense/INT8/INT8/dense would compare
hooked dense and INT8, with raw allocator request events and weak storage
ownership only in ON. None of those comparisons was reached. The experimental
profiler interface remains unvalidated. Even a later accepted trace would
describe observed CPU allocator requests and observer-perturbed lifetimes,
not OS memory returned, complete native/GPU peaks or training quality.

Next: separately freeze a corrected budget contract with a real-validator
mocked parent/worker handshake before authorizing a new actual suite. Keep
the allocator/gradient controls and timing claims gated until they execute.
Historical six failed joint training-cost/final-quality screens, invalid old
parent RSS, uncovered zero_grad intervals, H2 full-runtime gates, and H3/H4
planned status remain unchanged.

[Reproduction and hashes](../../fixtures/codec-allocation/README.md) ·
[Machine-readable summary](summary.json) ·
[Chinese research note](../../research/2026-10-18-codec-allocation-preimport-failure.md)
