# Finite Sinkhorn needs a training cost budget

> Version scope: this note preserves the saved open head `755e8476`. The [merged-version correction](2026-10-19-sinkhorn-recomputation-correction.md) replaces the current global-tape cost expectation with input retention and block recomputation. The original receipt and observations below remain historical.

[FLA #1524](https://github.com/fla-org/flash-linear-attention/pull/1524), by `yzhangcs` (GitHub profile: Yu Zhang), is open and unmerged at our saved read. It was created on 19 October 2026 at 07:42:20 UTC; this was already a deferred lead in the preceding pass. The new evidence here is review of head `755e8476c6e59ebd222e3e5f4cb2422badf56656`, not a new release. The public repository and that head's MIT license were read. The 12 returned commits carry the same account's author/committer attribution, including branch merges; this is not Nathan Chen's contribution or evidence of his next employer.

The proposed operator alternates column and row log normalizations for a fixed positive iteration count. The CUDA entry accepts square matrices with side 1–8, computes/returns FP32 and returns input gradients in the input dtype. Backward differentiates this finite sequence, rather than an implicitly converged doubly stochastic projection. Its saved callable comes from the forward-selected backend, so a later dispatch-flag change need not choose a different backward implementation. Higher-order gradients are excluded by `once_differentiable`.

The material cost is visible in all three backend wrappers: when autograd is enabled and logits require gradients, history has shape `(2 * iterations, M, N, N)` in FP32, where `M` is the product of leading dimensions. It stores probabilities after each column and row normalization. With 20 iterations, B=H=1, the logical history alone is:

| Sequence length | N | FP32 history bytes | MiB |
| ---: | ---: | ---: | ---: |
| 8,192 | 4 | 20,971,520 | 20 |
| 8,192 | 8 | 83,886,080 | 80 |
| 32,768 | 4 | 83,886,080 | 80 |
| 32,768 | 8 | 335,544,320 | 320 |

These are source-derived `8 * iterations * M * N²` bytes, not measured peak memory or residual-bank savings. The saved output is separate; gradients, input-layout copies, allocator overhead and kernel/compiler workspace require their own accounting. Overlapping lifetimes determine peak cost, so these bytes cannot simply be added to or subtracted from an unrelated bank estimate. No-grad inference omits this history.

The default unified benchmark's `fwd` label does **not** mean no-grad inference: its FP32 logits use `TensorSpec`'s default `requires_grad=True`, and the timed forward callable leaves autograd enabled. The author explicitly describes this distinction and also reports separate cudagraph timings. These timing protocols cannot be mixed. GB200 test counts and performance tables are author reports, not our execution. Our full-file comparison uses the PR merge base, not the immediately preceding head, so it does not verify the author's last-refactor performance or unchanged-kernel claim. Exact-head CI metadata still includes queued, in-progress and cancelled rows; no logs were read.

The added numerical tests compare outputs and vector-Jacobian products with the same finite PyTorch reference, including extreme logits, layout and backend controls. They assert row sums, not exact column sums or convergence. Non-NVIDIA and unavailable optional backends skip. Source inspection does not establish correctness on another device, training quality or a usable mHC/learned-routing consumer; linked consumer code was not reviewed.

This adds a conditional H1 gate. Before incorporating this normalization into a residual-bank mechanism, freeze the actual consumer, iteration count, dtypes, backend/callable identity and complete runtime dependencies. Check forward values, an independent derivative calculation and row/column residuals under extreme logits, layouts and flag changes. Measure grad-enabled forward, full backward and no-grad inference separately, using one declared timing protocol, saved-storage lifetimes and an appropriate actual allocator/device peak measurement. Include normalization and packing/retrieval in matched training cost, with fixed data/optimizer/token/time budgets and sealed final-quality evaluation. Any numerical/backend mismatch or failure of the predeclared cost, peak or quality budget rejects that candidate. A source allocation formula alone cannot pass this gate.

The alternative explanation is straightforward: an isolated fast normalization kernel may add a large training tape or change the differentiated objective, while a complete consumer may use other shapes or amortize costs differently. Its relevance to a residual bank remains conditional. We release no local experiment from this review. H1's six failed cost/final-quality screens, all 12 regressed final endpoints and invalid historical parent RSS remain; H2's full recovery gates and H3/H4's planned status are unchanged.

The [review receipt](receipts/20261019T111651Z-sinkhorn-training-cost.json) binds 24 bounded GETs, 11 complete head files and five full comparison-parent files, 75 custody checks, the pinned license and all 18 returned check-run metadata rows. Exact PR-file path/SHA/status sets match the immutable comparison, and both commit endpoints end at the pinned head. No upstream code is redistributed or executed; this is a source-specific experimental requirement, with no new speed, memory-saving, novelty or model-quality claim.
