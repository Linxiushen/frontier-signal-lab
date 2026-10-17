# Frozen failed codec allocation diagnostic

This snapshot preserves a failed experiment. The producer has a known
preimport budget-argument error and is intentionally unchanged. The saved
evidence can be audited on any Python 3.11+ host without Torch, model loading,
network access, or Windows process creation:

```bash
python -S scripts/audit_codec_allocation.py --result results/codec-allocation
python -S scripts/audit_codec_preimport_failure.py --result results/codec-allocation --expected-review results/codec-allocation/independent-review.json
python -S -m unittest tests.test_codec_allocation_probe tests.test_codec_allocation_events tests.test_codec_preimport_failure tests.test_codec_preimport_audit -v
```

The first audit reports receipt consistency `true` and execution acceptance
`false`. It does not validate the raw preimport receipt omitted from the
producer's accepted-stage map. The second audit is a **post-outcome**,
evidence-specific supplement, including that receipt and termination evidence.
Neither command repeats the actual suite or turns its failure into success.
The final two test modules were written after the failure; the first two
contain the 27 prefreeze pure tests.

- [Protocol](protocol.json): declared settings, sole attempt, eight-case
  ceiling and stop-on-failure policy.
- [Implementation](implementation.json): exact source, dependency, executable,
  provider, protocol and pre-execution-review hashes.
- [Pre-execution review](pre-execution-review.json): guarded tests and static
  reviews before execution. These passed and missed the budget contract error.
- [Original result](../../results/codec-allocation/report.json) and
  [original-file manifest](../../results/codec-allocation/original-manifest.json).
- [Post-outcome summary](../../results/codec-allocation/summary.json), independent
  review and regression/mutation receipts remain separate from the freeze.

The original suite was run once on Windows with the existing pinned local
Pythia checkpoint (`cf967c0a9a04383db6f7b1108d86b2962634b4ac`) and explicitly
hashed local executables. It rejected before ML imports, so no Torch/profiler
runtime compatibility or codec comparison was established. Do not use a
second invocation to overwrite or rescue this snapshot. A corrected future
suite needs its own predeclaration, reviewed implementation and fresh output.

No upstream implementation code is copied. Existing official PyTorch API
and tagged weak-storage semantics were [read separately](../../research/receipts/20261017T230210Z-torch-profiler-api.json);
their retrieval dates are not new research announcement dates.
