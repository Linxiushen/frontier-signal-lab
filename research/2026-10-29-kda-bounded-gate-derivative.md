# Bounded KDA gate derivative: landed source evidence

FLA [PR1607](https://github.com/fla-org/flash-linear-attention/pull/1607), by
**zhiyuan1i**, landed as `54ab79ec9cbb4c66ada960e21043870825359a7a`
at08:08:37Z on2026-10-29. Its03:36:44Z proposal was already sampled before the
prior07:33:19Z cutoff; the landing is new, not the proposal. The
[portable receipt](receipts/20261029T134004Z-kda-bounded-gate.json) identifies
four complete immutable parent/landed blobs, license and static comparison
digests. No upstream implementation is redistributed.

Both default and Ascend KDA bounded-gate backward branches replace
`sigmoid(z) * (1 - sigmoid(z))` with `r / (1 + r)^2`, where
`r = exp(-abs(z))`. Complete AST comparisons isolate that assignment block in
each file; the remaining AST, including forward functions and public interfaces,
is identical. This differs from [FLA1554](2026-10-22-import-boundary-and-safe-gate.md),
which sets eight backward dot-product precision arguments. Removing subtraction
from one addresses a distinct cancellation mechanism; compiled arithmetic,
remaining tail underflow and full-model effects are unmeasured here.

The actual caller is `fused_kda_gate` through `KDAGateFunction.backward`, with
the corresponding Ascend path. Saturated bounded gates can affect gradient
propagation in recurrent/attention training; this review measures no magnitude,
prevalence or benefit at scale. The integration points are the two backward
kernels under `USE_LOWER_BOUND`.

Future falsifiable controls should pin backend, Triton version, dtype, lower
bound and optional A_log/bias; fix positive/negative saturated and nonsaturated
inputs, an independent higher-precision derivative reference, full input/A_log/
bias gradients and tolerances before execution. Distinguish cancellation from
underflow. Any performance claim also requires a fixed matched workload/resource
ceiling and measured quality, useful throughput, end-to-end/tail latency, peak
resources and observation cost. These are recommendations, not a preregistered
or executed runtime experiment.

The author reports formatting passed and explicitly did not run accelerator
tests. The two-file landing adds no tests. Our evidence is metadata, complete
source bytes and AST comparison only: zero kernel, accelerator, model, gradient
or scientific execution. Four hypothesis states, six H1 failed joint screens,
invalid historical parent RSS and H2–H4 runtime gates remain unchanged. The
accepted caller/observer prerequisites stay closed; this KDA change does not
repair the unsupported20-second startup of our tiny GPT2 training caller.
