# SaveScope distribution notes

Prepared 2026-10-16. These are reviewable drafts and a channel research record. At preparation time no external post, message, issue, PR, Hugging Face repository, or Space had been created. Actual publication status is tracked separately; prepared copy is not proof of posting.

## Lead with a problem another engineer can reproduce

SaveScope is a CPU float32 toolkit for auditing saved-tensor compression against a dense reference: saved-tensor scope inventory, parameter-gradient fidelity, and actual first-step AdamW update fidelity with fresh moments. The product entry point is [SAVESCOPE.md](../SAVESCOPE.md). PyTorch already provides [saved-tensor hooks](https://docs.pytorch.org/tutorials/intermediate/autograd_saved_tensors_hooks_tutorial.html); our useful contribution is an inspectable audit workflow, controls, and reports. Stateful optimizer trajectories are outside this initial contract.

The reader should be able to answer: **which saved-tensor scopes can I compress in this configuration before the gradients or optimizer updates change too much?**

Use these two entry points distinctly:

```bash
git clone https://github.com/Linxiushen/frontier-signal-lab.git
cd frontier-signal-lab
python -m pip install .
python -m savescope replay --output replay
python -m savescope inspect replay/report.json
```

This exports the bundled recorded case to `replay/index.html` and `replay/report.json`; it does not execute a model. After installing the optional CPU Torch/NumPy dependencies documented in [SAVESCOPE.md](../SAVESCOPE.md), `python -m savescope demo --output tiny-run` executes the tiny model locally without a model download. Call these a recorded replay and an executed demo, respectively.

The Pythia-14m case provides the motivation: preserving exact CE and 13 LayerNorm scopes did not pass the gradient-error gate; additionally preserving saves inside six actual attention forwards reduced full-gradient relative L2 from 4.05–7.70 to 0.034–0.041 across three fixed batches. These are broad module execution scopes. The subsequent [actual first-step AdamW diagnostic](../results/activation-update/report.md) retained gradient cosines of about 0.999, but actual float32 parameter-delta relative L2 errors were **0.119295 / 0.116722 / 0.108971**. All three predeclared joint gates failed the absolute error limit of 0.10, although cosine and relative-improvement conditions passed. This is the strongest concrete launch example: a useful negative result rather than a compression-success announcement.

Keep its conditions adjacent to the result: pinned Pythia-14m, CPU float32, three overlapping synthetic batches with 320 unique target positions, fresh optimizer moments, learning rate 1e-4, weight decay 0.01. All native parameter/moment updates were checked against independent NumPy equations within stated float32 rounding bounds. This does not identify one operand, validate FLA kernels, or show stateful training, quality, VRAM, or speed gains. The [fixed public gradient report](https://github.com/Linxiushen/frontier-signal-lab/blob/4c9683a408625817500843161e40383527c30455/results/activation-attention-gradient/report.md), [update protocol](../fixtures/activation-update/README.md), and earlier [negative training result](https://github.com/Linxiushen/frontier-signal-lab/blob/4c9683a408625817500843161e40383527c30455/results/activation-training/report.md) must remain discoverable. Pin the new update-report URL to the actual published commit before posting.

## Match the channel to the contribution

First-party rules were read on 2026-10-16; precise URLs, observations, hashes, and failures are in [channel-evidence.json](channel-evidence.json). A public page proves that a channel exists, not that our account can publish there or that moderators will accept a submission.

| Channel | Suitable contribution | Readiness / boundary |
| --- | --- | --- |
| [PyTorch Projects](https://discuss.pytorch.org/c/projects/33) | Runnable CPU audit, report schema, an example where forward loss hides backward error, and a request for one independent reproducer. | Best first technical audience. Projects explicitly invites how people use PyTorch. Read existing discussions; do not repeat the announcement in Autograd. Use [Autograd](https://discuss.pytorch.org/c/autograd/7) only for a specific minimal engine question. Posting access unverified. |
| [HF Show and Tell](https://discuss.huggingface.co/c/show-and-tell/65) | [Forum draft](huggingface-post.en.md): technical open-source details, Pythia scope evidence, runnable tiny example, and one Transformers adapter question. | Its [category guidance](https://discuss.huggingface.co/t/about-the-show-and-tell-category/30513) asks for technical insights rather than promotional content. Follow the [forum guidelines](https://discuss.huggingface.co/guidelines), including no duplicate cross-posting. Posting access unverified. |
| [HF Blog Articles](https://huggingface.co/docs/hub/en/blog-articles) | A longer engineering explanation or open-source tool release, with exact controls and evidence. | Officially suitable content, but current personal eligibility requires confirmed email plus PRO or a qualifying Team/Enterprise write/admin role. Organization publishing requires Team/Enterprise and write/admin. Managed users cannot publish under their personal namespace. Our eligibility is unverified. The community listing is not proof of publishing access or featured placement. |
| [HF Static Space](https://huggingface.co/docs/hub/en/spaces-sdks-static) | A mirror of the static report explorer and a clearly labelled recorded example. | Static Spaces are free and serve HTML without compute. Creating Gradio/Docker Spaces currently requires a qualifying paid plan, subject to the official ZeroGPU exception. No HF repository or build has been created or tested. See the static plan below. |
| [FLA organization Show and tell](https://github.com/orgs/fla-org/discussions/categories/show-and-tell) | A pinned FLA operator/reference adapter, exact supported outputs/gradients, then one integration question. | Conditional. Current GPTNeoX/Pythia evidence is not FLA validation. Category text says “Show off something you've made”; the public page had partial loading errors. Read [CONTRIBUTING](https://github.com/fla-org/flash-linear-attention/blob/main/CONTRIBUTING.md) before any upstream work. No generic launch issue or author pings. |
| [X](https://x.com/) | [Short evidence thread](x-thread.en.md), linking code, negative results, and one concrete question. | A draft only. User account, posting capability, and channel policy review are unverified. No institution/name tags are needed for relevance. |
| [Show HN](https://news.ycombinator.com/showhn.html) | A runnable artifact the user personally made and can discuss. | Deferred. [HN guidelines](https://news.ycombinator.com/newsguidelines.html) say “Don't post generated text or AI-edited text” and “please don't automate posting.” The user must write their own submission and comments. No HN submission prose is provided here. |

## Reader matching and useful questions

These are topic matches from public work, not outreach targets, predictions of private plans, or suggestions that anyone endorses SaveScope.

| Public reader / work | Why it may be relevant | A concrete question or contribution |
| --- | --- | --- |
| PyTorch autograd users; [official hook tutorial](https://docs.pytorch.org/tutorials/intermediate/autograd_saved_tensors_hooks_tutorial.html) | They already use packing, unpacking, and selective offload and need faithful comparisons. | Can an independent tiny example expose a scope-restoration, repeated-module, or nested-hook failure? Supply a minimal test and reference gradients. |
| FLA training/operator contributors; [contribution rules](https://github.com/fla-org/flash-linear-attention/blob/main/CONTRIBUTING.md) | Their own rules require supported outputs and gradients against naive/reference implementations. | Can a fixed operator and differentiable reference be added without changing strict tolerances, with complete parameter/optimizer controls? Start locally; upstream only after an actual FLA-relevant result. |
| Nathan Chen's public [KDA backward contribution](https://github.com/fla-org/flash-linear-attention/pull/688) and [Attention Residuals](https://github.com/MoonshotAI/Attention-Residuals) lineage | Public backward-kernel, architecture, and budget questions overlap with fidelity auditing. | Which independently implemented depth-routing or attention-reference case is small enough to compare saved scopes and actual updates under identical controls? Current Pythia evidence is not an AttnRes reproduction. No employer inference is involved. |
| Guangxuan Xiao's public [attention-capacity note](https://guangxuanx.com/blog/attn-capacity.html) | Attention information budgets are a related public line. Those notes do not establish interest in our training audit. | Can an open training example distinguish backward-saved compression from inference/KV-cache compression? This is a secondary audience until such an adapter exists. |
| Transformers/Pythia practitioners in HF Show and Tell | They can reproduce another architecture using the same report contract. | Reproduce on a small, licensed HF architecture; document actual module types and optimizer state, and retain failed gates. |

The agent-recovery/RL-environment audiences in the broader research log are a weaker match for this release. Avoid putting SaveScope into their unrelated issue threads. Do not request stars, likes, upvotes, or mass tagging. A useful outcome is an independent successful install/reproduction, a concrete bug report, a reviewed adapter, or a merged contribution.

## Static Space plan, not a deployment

Use a separate HF Space only after the user has chosen an account/namespace and publication is authorized. Suggested repository paths:

```text
README.md       # metadata below, plus source and evidence links
index.html      # same static report explorer as the verified release
report.json     # optional bundled example matching the HTML data
LICENSE         # project MIT license; keep third-party notices where applicable
```

Suggested Space README front matter:

```yaml
---
title: SaveScope audit report
emoji: 🔬
colorFrom: blue
colorTo: gray
sdk: static
app_file: index.html
pinned: false
license: mit
---
```

Follow the [static SDK documentation](https://huggingface.co/docs/hub/en/spaces-sdks-static) and the [content policy](https://huggingface.co/content-policy). A static viewer can inspect recorded data; it cannot run Python/PyTorch training in the browser. State the example's execution mode and date in the app. Do not include model weights, private reports, credentials, or tensor values merely to make a demonstration. Validate any future Space's build, public URL, content, and source/release correspondence before calling it live.

## Release and publication sequence

1. Publish the product documentation, meaningful CPU checks, installable package source, recorded example, actual tiny demo, and [contribution guide](../CONTRIBUTING.md) together. Confirm the public commit contains those files.
2. Run the documented commands from a clean environment, record which executed, and inspect generated reports. Verify any advertised demo URL; proposed GitHub Pages URL `https://linxiushen.github.io/frontier-signal-lab/` was not verified during this channel audit.
3. Review channel-specific drafts against the released behavior. Replace moving evidence links with release/commit links where practical. Keep the recorded Pythia gradient/update case distinct from a newly executed tiny-model run.
4. Once channel identity and publishing authorization are established, publish one substantive PyTorch Projects post and/or one tailored HF Show and Tell post. Each should carry a different community-specific question; do not paste duplicates across forum categories.
5. Answer actual reproduction questions, update known failures, and offer small reviewable adapter tasks. Approach FLA only with matching evidence. A short X thread may link the verified release. No reach or researcher attention is guaranteed.
6. For Show HN, give the user the facts below and let them personally write and participate. Do not generate, edit, or automate HN text.

## Facts the user can independently consult for HN

This is an engineering checklist, not submission text or a title:

- Source, license, exact release/commit, and the user's actual role in making the artifact.
- An immediately usable static viewer; a fresh-install replay; an actual no-model-download tiny run. Verify each first.
- Which path displays recorded data, which executes a model, and exact execution environment.
- What the dense reference, gradients, actual parameter deltas, optimizer state, policy scopes, and logical inventory mean.
- The exact published Pythia observation and the preserved negative training result.
- Explicitly unmeasured training quality, GPU memory, throughput, larger-model generalization, and unsupported integrations.
- One specific problem the user wants independent evidence about, and the user's availability to discuss it.

The [Show HN page](https://news.ycombinator.com/showhn.html) excludes blog posts, signup pages, newsletters, and lists/reading material as Show HN artifacts. The user must not solicit votes or comments, arrange coordinated engagement, or delete/repost for visibility.
