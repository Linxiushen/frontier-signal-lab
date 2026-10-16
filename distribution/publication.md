# SaveScope publication record

Verified 2026-10-16 at 09:45 UTC. A shipped project and a prepared community
submission have different status; the table records what actually happened.

| Surface | Actual status | Evidence |
| --- | --- | --- |
| GitHub source | Public, MIT original toolkit and examples | [Release source](https://github.com/Linxiushen/frontier-signal-lab/tree/savescope-v0.1.0) |
| GitHub release | Public experimental prerelease, five uploaded assets | [v0.1.0](https://github.com/Linxiushen/frontier-signal-lab/releases/tag/savescope-v0.1.0) |
| Interactive viewer | Live, HTTP 200; exact bytes match the reviewed offline HTML | [Open case](https://linxiushen.github.io/frontier-signal-lab/) |
| Package CI | Passed: wheel, installed replay, engineering contracts and executed tiny demo | [Run](https://github.com/Linxiushen/frontier-signal-lab/actions/runs/38882050400) |
| Model CI | Passed: execution/controls, preserving failed scientific gates | [Run](https://github.com/Linxiushen/frontier-signal-lab/actions/runs/38882050415) |
| GitHub discovery | Description, demo homepage, relevant PyTorch/autograd/AdamW topics applied | [Repository](https://github.com/Linxiushen/frontier-signal-lab) |
| X | Signed-in browser session found; account choice pending; **no post sent** | [Reviewed post and figure](x-thread.en.md) |
| PyTorch Projects | Category inspected; browser shows Log In / Sign Up; **no post sent** | [Tailored technical draft](pytorch-post.en.md) |
| Hugging Face Show and Tell | Hub and forum show Log In; **no post, article or Space created** | [Tailored architecture-adapter draft](huggingface-post.en.md) |
| Hacker News | No submission; user-authored text/manual posting required by its guidelines | [Channel evidence](README.md) |

Release commit: `ad126b57c4dbd5492b0f6cb07eba578fb40fafa7`.
The package source and scientific observations are identical to the launch
commit; the release adds an exact-gradient test correction for FP64 norm
rounding and fixed evidence links. No scientific threshold was relaxed.

Public wheel:
[frontier_savescope-0.1.0-py3-none-any.whl](https://github.com/Linxiushen/frontier-signal-lab/releases/download/savescope-v0.1.0/frontier_savescope-0.1.0-py3-none-any.whl)
(513,165 bytes), SHA256
`df10712e71f0f154cfcff2c5f6a0c77476d573a06841cfe0564fde8512ea6e09`.

Offline HTML SHA256:
`f210a747c6ee7e9db800707af74826766c7667af3598036b6511927de352bcad`.
Bundled observation content SHA256:
`85f36b31f557caafa7d229544d0f498a1d0eedfe7714bded3a0bb1a47ea17477`.
The wheel was downloaded without authentication after publication and matched
the reviewed local artifact. The live site matched the local HTML byte for byte.

## First distribution steps

1. Use the X standalone post and attached figure after the user's account choice.
   Lead with the bounded first-step-update counterexample, linking the release.
   Confirm a public permalink before recording it as posted.
2. In PyTorch Projects, publish the tailored toolkit post from the user's logged-in
   account and ask for one scope/restoration reproducer. Supply the verified
   viewer and install command. Keep follow-up discussion in that one topic.
3. In HF Show and Tell, use its distinct architecture-adapter question. Start
   with a free static Space only when an authenticated user namespace is available;
   the initial static viewer needs no paid inference or model weights.
4. Record actual independent installs, counterexamples, bug reports and adapters.
   Those are useful outcomes; draft counts, impressions and hypothetical reach
   do not establish research impact. There is no evidence yet of attention or
   endorsement from any named researcher.

No researcher messages, upstream issues/PRs, paid promotion, vote requests or
social posts were sent as part of this release. The user can publish the prepared
technical material without inventing a result or implying a new employer.
