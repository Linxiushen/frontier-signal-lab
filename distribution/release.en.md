SaveScope v0.1 is an experimental CPU toolkit for auditing saved-tensor compression.

It includes an installable Python package, a reusable `audit(model, forward_fn,
loss_fn, ...)` API, a real tiny-model demo, and a self-contained interactive report
that can inspect recorded observations without ML dependencies.

In the bundled pinned Pythia-14m case, gradient cosine near 0.999 still left
10.9–11.9% actual float32 AdamW first-step update error. All three predeclared
joint update gates failed the 10% absolute error condition; independent NumPy
parameter/moment controls passed. Three overlapping synthetic batches, fresh
moments, CPU float32, weight decay0.01. This is a useful negative result, not a
compression-success announcement.

- [Interactive recorded case](https://linxiushen.github.io/frontier-signal-lab/)
- [Install, API and boundaries](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/SAVESCOPE.md)
- [Predeclared update result](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/results/activation-update/report.md)
- [Earlier negative training result](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/results/activation-training/report.md)

Install the attached wheel, then run `python -m savescope replay --output replay`.
Open `replay/index.html`. This route runs no model. The executed `demo` needs CPU
Torch + NumPy as documented. Use a fresh output directory each time.

No demonstrated quality, speed, peak-memory or GPU gains. Single-threaded CPU
float32 eager first-order execution only. No accumulated optimizer state in v0.
Original code/examples MIT; no model weights bundled. Implementation and release
materials used AI assistance. Independent reproductions and counterexamples
with small runnable cases are welcome.
