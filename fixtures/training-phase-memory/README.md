# Stage-labelled current memory in two dense updates

This independent protocol permits at most **one fresh pinned Pythia-14m load and
two dense AdamW updates** (seed 503, CPU float32/eager, threads 1/1). A separate
reviewed implementation freeze is required before the root runs the sole suite.
The sole execution is now [recorded with raw receipts](../../results/training-phase-memory/report.md):
one load, two updates, 23,382 portable checks; both zero_grad intervals remain
unsampled. Logical gradient clearing did not return equal native process capacity.

Eight operator intervals separate zero_grad(set_to_none=True), forward plus
cross-entropy, backward and optimizer.step in each update. Nine training holds
record fully ordered self/parent/self native current-memory query intervals,
then a primitive tensor inventory. Held identity, provider diagnostics, exact
role admission, authenticated acknowledgments, deadlines and whole-Job cleanup
remain required. The last continue acknowledgment precedes both retained live
checks and finish emission.

The parent performs memory/native-CPU queries through the authenticated actual
worker handle with a 20 ms target. There are no active Toolhelp snapshots or off
baseline. Only queries wholly inside the exact operator interval enter a phase
summary; boundary crossings remain saved. A short phase with no selected query
has **null maxima and unknown coverage**. Recorded gaps do not bound missed peak
bytes.

Parameters, buffers, gradients, two AdamW moment families, step scalars and live
loss have separate logical byte inventories. Backing storage is deduplicated
within each snapshot; addresses are neither published nor unioned over time.
Expected first-step AdamW state creation and second-step counter changes are
structural gates. These bytes do not reconstruct native resident/private memory;
clearing gradient references need not return allocator capacity to the OS.

Holds extend graph and loss lifetimes. Inventory, JSON, controls and allocator
history perturb later readings. Optimizer scalar-loss logging and loss deletion
are separately timed after the operator; B4/B8 follow that housekeeping. Results
can describe instrumented stage-labelled whole-process sampled lower bounds,
not isolated backward/full peaks, tensor-only allocation cost or uninstrumented
training performance. Final validation/hash occurs after B8. No retry, warmup,
compression arm, quality evaluation, GPU, hard-cap or production claim is allowed.
Historical rejected measurements and scientific failures remain unchanged.

After an actual report exists, the portable auditor can inspect its saved bytes
without Torch, native execution or live process queries. Use a fresh output path:

```powershell
python -S -X utf8 -m scripts.audit_training_phase_memory --report results/training-phase-memory/report.json --protocol fixtures/training-phase-memory/protocol.json --freeze fixtures/training-phase-memory/implementation.json --output reports/runs/your-fresh-review/training-phase-memory-audit.json
```

This command is a saved-receipt replay; it does not execute the model or replace
a separately reviewed Windows reproduction freeze with pinned local assets.
