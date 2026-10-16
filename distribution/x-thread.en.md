# X thread draft — not posted

The release is public; see [publication status](publication.md). An existing X session is available; the user's channel-account choice is pending. No post has been sent. No tags, mentions, or guaranteed reach. Do not reuse this AI-generated draft on Hacker News.

Each numbered block below is one proposed post. Evidence links target the SaveScope v0.1.0 release tag; confirm the release exists before posting. The conditions in post 1 are part of the result, not optional fine print.

Post 1 works as a standalone launch post (269 weighted characters, counting the
URL as 23). Attach [the result figure](../docs/assets/first-step-fidelity.png).
The following blocks are optional technical follow-ups. A draft is not a post.

## 1

SaveScope: Pythia-14m, CPU float32, 3 overlapping synthetic batches, fresh moments, lr=1e-4, wd=0.01. Gradient cosine ~0.999, but actual first-step AdamW deltas had 10.9–11.9% relative L2 error vs dense; all 3 failed the predeclared 10% ceiling.
https://github.com/Linxiushen/frontier-signal-lab/releases/tag/savescope-v0.1.0

## 2

The measured error is relative L2 of actual float32 first-step parameter deltas vs dense: 0.1193 / 0.1167 / 0.1090. All three predeclared joint gates failed the 0.10 absolute limit. A high gradient cosine was insufficient.

## 3

We kept exact CE, 13 LayerNorm scopes and six attention forwards. Gradient error fell sharply, but the update gate still failed. Broad scopes, 320 unique target positions; no stateful-training, quality, VRAM or speed conclusion.

## 4

Evidence, controls and failed gate:
https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/results/activation-update/report.md
SaveScope compares saved scopes, reference gradients and actual first-step updates. Native parameter/moment updates also passed independent NumPy rounding bounds.

## 5

Try `python -m savescope replay --output replay` to inspect recorded observations, or `python -m savescope demo --output tiny-run` for an actual tiny run after CPU dependencies. No model download.
https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/SAVESCOPE.md

## 6

We would value one independent reproducer or small architecture adapter: identical weights/data/optimizer state, actual module scopes, reference gradients + parameter deltas, and all failed gates retained.
https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/CONTRIBUTING.md

## Evidence links for replies, if relevant

- [Product and support boundary](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/SAVESCOPE.md)
- [Fixed Pythia gradient report](https://github.com/Linxiushen/frontier-signal-lab/blob/4c9683a408625817500843161e40383527c30455/results/activation-attention-gradient/report.md)
- [Actual first-step update result](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/results/activation-update/report.md)
- [Predeclared update protocol](https://github.com/Linxiushen/frontier-signal-lab/blob/savescope-v0.1.0/fixtures/activation-update/README.md)
- [Negative training result](https://github.com/Linxiushen/frontier-signal-lab/blob/4c9683a408625817500843161e40383527c30455/results/activation-training/report.md)
- [PyTorch's existing saved-tensor hook tutorial](https://docs.pytorch.org/tutorials/intermediate/autograd_saved_tensors_hooks_tutorial.html)

Use only a verified live demo URL. Do not add GPU claims, affiliation claims, or suggestions that a named researcher endorsed the tool. The earlier training run cut logical saved inventory by 54% but ran slower on CPU with higher process peak; it remains a negative result.
