# SaveScope v0.2: inspect an existing AdamW state

`audit(..., optimizer=optimizer)` now compares policies from the caller's
current moments and per-parameter counters. Each policy steps private clones.
This closes the reusable API's previous fresh-state-only restriction.

The frozen original CPU fixture ran once on 2026-10-18, 11:34:15–11:34:20 UTC:
seed **20261018**, float32, one Torch thread, Torch **2.9.1+cpu**, NumPy **2.3.5**.
Four source warmups left normal parameters at step4, an initialized unused
parameter at step2, and a never-used parameter without state. The suite made
nine native updates in total: four source, one independent reference, three
audit policies, and one fresh-state control. No pretrained model was loaded.

All **16 controls passed**:

- Dense parameter, update and used-gradient hashes match a separately cloned
  authentic native AdamW initialized from the same accumulated state.
- Caller parameter/gradient objects, values/storage/versions, optimizer state
  and RNG remain unchanged. The fixture starts with cleared source gradients;
  separate unit tests cover existing gradient objects and values.
- Initialized unused state retains its counter/moments, while absent lazy state
  stays absent. Resetting to fresh moments gives a different update.
- A negative second moment refuses before the callback. A callback exception
  preserves untouched caller optimizer state and registered model/RNG state.
- All three policy arms pass the independent NumPy transition controls.

These are product correctness checks on one random fixture. They do not test
training quality, trajectory equivalence, performance, memory savings or GPUs.
The six historical H1 cost/final-quality failures and invalid parent RSS
measurement remain unchanged. No scientific fidelity threshold was assigned
to the compressed arms.

Validation includes **43 passing toolkit tests, zero skips**, and wheel import
plus offline replay. The initial focused test run retained two failures caused
by an invalid test assumption: PyTorch Parameter deepcopy omits `.grad`. The
corrected oracle captures original gradient identities and cloned values;
14 focused tests then pass. The first receipt-review attempt also retained a
failure because the runner hashed LF text before writing Windows CRLF files;
the corrected review verifies the normalized text and raw file hashes separately.
Neither correction reran the frozen product suite.

Reproduce into a new directory:

```bash
python -m pip install '.[audit]'
python experiments/savescope_optimizer_probe.py --output my-state-check
python -S experiments/savescope_optimizer_receipt_audit.py --result my-state-check --output my-receipt-review.json
```

Numeric hashes are same-runtime controls, not a requirement for cross-platform
bitwise equality. The original code and random fixture are MIT.

| Artifact | SHA256 |
| --- | --- |
| [Protocol](../../fixtures/savescope-optimizer-state/protocol.json) | `00a9cb9ea7d615c67490fe24deed8e7af3b1f3f4b87af2b23e2cc568b8548070` |
| [Implementation freeze](../../fixtures/savescope-optimizer-state/implementation.json) | `64d6f33a8a946980bdfebb9cb9c2ed19cc0fe15465d06b18706cab363586a3a9` |
| [Result file](report.json) | `3018179d2ff3dc703f5e3bde38b487b352eaab5b87e9b88ba71a4bbd3e32b529` |
| Result canonical payload | `8b5148f9ba1f492c6006b7aeebbb9a0dfcdfceb8715a723e66ebcb75423d6d37` |
| [Trajectory, including dense gradient values](trajectory.json) | `6bf7cd08854ac4ce918bbfe16fd93d07216590c5520d2b23c942715d830933f6` |

[API contract](../../SAVESCOPE.md#use-your-own-model) ·
[Offline viewer](viewer/index.html) · [Validation summary](validation.json)
