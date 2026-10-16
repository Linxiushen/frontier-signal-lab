# Predeclared training-cost question

Does deterministic int8 storage of eligible tensors saved for backward reduce
retained saved-tensor payloads in an actual small causal-language-model training
loop, and what costs or changes accompany it?

The fixed inputs and optimizer budget are recorded in `manifest.json` before
any training output: Pythia-14m revision `cf967c0a...`, eight65tokenblocks per
split,24updates with two64targetsequences each, AdamW learning rate0.0001,
weight decay0, betas0.9/0.999, epsilon1e-8, seeds11/29/47. Each paired method
uses identical pretrained parameters and the same seed-dependent batch order.
The budget is3,072training target positions per method/seed, revisiting512unique
positions. A180second training-loop cap aborts incomplete workers and prevents
classifying them as completed comparisons. Training-loop and per-step timings
are recorded; OS memory snapshots also bracket loading and evaluation.

Both methods use dense forward activations. One keeps ordinary saved tensors;
the other stores eligible finite CPU float32 saved tensors with at least256
elements as deterministic symmetric per-last-dimension int8 codes plus float32
scales. Parameter-backed storage, including transposed aliases, is excluded.
Backward reconstruction approximates saved operands and therefore gradients;
this is not quantized model-forward inference or an identity STE. Eligibility
can include attention, MLP and loss tensors; it is not residual-bank-only.

All model parameters participate in the optimizer. Record per-step training CE,
finite gradient coverage/norm, optimizer updates, pack/unpack payload inventories
and elapsed costs, plus initial/final parameter hashes and actual OS process
lifetime peaks. Saved payload inventory and process memory are different
measurements. Instrumentation, the model, gradients, optimizer state, evaluation
and allocator history contribute to the process peak.

Evaluate the separate synthetic holdout only before and after training; choose
no learning rate, checkpoint or method by intermediate holdout scores. Retain
every seed and negative outcome. This is a tiny optimization/cost diagnostic,
not a generalization benchmark. A lower NLL here does not establish broadly
better language-model quality, numerical equivalence or deployment usefulness.

Both arms must complete the fixed token budget with finite losses, gradients
and parameters and changed parameter hashes. Compression should have eligible
packets, protect parameter aliases and actually reconstruct saved operands.
Failure of these checks rejects the implementation/comparison. Differences in
final heldout NLL and CPU costs are observations; no universal pass threshold or
statistical superiority is declared from three seeds.

Matched wall-clock training, learned depth-routing queries, faithful AttnRes
training, larger natural-language holdouts and measured GPU peaks/throughput
remain separate gates. Activation-compressed training is established prior work,
including [ActNN](https://arxiv.org/abs/2104.14129); this deterministic8bit CPU
probe does not reproduce its2bit stochastic mixed-precision method or results.
