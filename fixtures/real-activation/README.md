# Frozen pretrained activation fixture

This fixture captures real, learned residual activations from a frozen
`EleutherAI/pythia-14m` forward pass at revision
`cf967c0a9a04383db6f7b1108d86b2962634b4ac`. The model is a conventional
GPT-NeoX residual model. The capture supplies a detached bank for the existing
depth-mixing operator experiment; it does not turn that model into an AttnRes
network.

`source.txt` is original English prose written for this repository, released
under the repository's MIT license. It is not copied from a training dataset.
The tokenizer processes this text without padding, truncation or special tokens.
The first 512 token IDs are reshaped into **four independent 128-token sequences**.
Positions restart for each sequence; this is not a single 512-token context.

The script registers a forward pre-hook, with keyword arguments enabled, on each
of the six GPT-NeoX layers. It clones the incoming `hidden_states` before each
block, including layer zero's embedding residual. Each capture has shape
`[4, 128, 128]`. Flattening batch then token produces the float32 C-contiguous
bank `[6, 512, 128]`; the final post-block state is not included.

## Capture from local assets

Obtain the model assets separately from the [pinned public revision](https://huggingface.co/EleutherAI/pythia-14m/tree/cf967c0a9a04383db6f7b1108d86b2962634b4ac).
Keep the downloaded weights in an ignored local cache. Provide the exact
revision's seven required files: `README.md`, `config.json`,
`generation_config.json`, `model.safetensors`, `special_tokens_map.json`,
`tokenizer.json` and `tokenizer_config.json`. Also retain applicable license and
notice files. The script checks each required file's exact size and SHA256 before
loading; unpinned tokenizer/adapter override files are rejected.
The expected `model.safetensors` size is 28,143,920 bytes and its SHA256 is:

```text
116a02532db461f91386a5b20f942ff2c8d4de7341e21b55caafc3d7b25f49a1
```

The supplied fixture was captured on 2026-10-16 UTC with Python `3.12.14`, CPU
PyTorch `2.9.1+cpu`, Transformers `4.57.3`, NumPy `2.3.5`, safetensors `0.7.0`
and tokenizers `0.22.2`. The manifest records these actual versions. To prepare a
separate capture environment from the repository root:

```powershell
python -m venv local-state/activation-venv
& local-state/activation-venv/Scripts/python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu "torch==2.9.1+cpu"
& local-state/activation-venv/Scripts/python.exe -m pip install -r requirements-real-activation.txt "tokenizers==0.22.2"
& local-state/activation-venv/Scripts/python.exe scripts/capture_real_activation.py --model-dir local-state/models/pythia-14m-cf967c0 --output fixtures/real-activation --source fixtures/real-activation/source.txt
```

Place the separately obtained pinned assets in the indicated local model
directory, or pass another local directory. The capture script itself does not
install packages or download model files.

The source is limited to 64 KiB, and the pinned configuration is checked before
model loading. Both Hugging Face
offline environment flags and `local_files_only=True` are enforced;
`trust_remote_code=False` and `use_safetensors=True` prohibit loading repository
code or pickle weights. Execution uses CPU float32, eager attention, evaluation
mode, frozen parameters, `torch.no_grad()`, one compute/inter-op thread, seed zero
and deterministic algorithms. The script checks the model architecture and
per-sequence maximum context before the forward pass.

## Completed capture

The original 714-word input encoded to 850 tokens. The supplied fixture uses the
first 512 IDs as four independent sequences, with exactly one pre-hook capture
at each of the six layers. The completed model forward used 14,067,712 frozen
parameters and produced the finite `[6, 512, 128]` bank described above. A second
capture reproduced the bank, input-token and capture-configuration hashes.

The manifest and source hashes identify this capture. Independent verification
also checked that the first bank slice exactly equals the pinned input embedding
weights indexed by the recorded token IDs. These checks establish the fixture's
recorded source and boundary; downstream operator measurements have their own
reports.

## Output and hash conventions

- `bank.npz` contains only the float32 `bank` array. `trace_file_sha256` hashes
  the actual NPZ file bytes. `bank_sha256` hashes raw little-endian float32 bytes
  in C order, excluding NPZ/container metadata.
- `token_ids.json` stores the actual nested `[4, 128]` model input IDs.
  `token_ids_sha256` hashes that file's exact UTF-8 bytes, including its final LF.
- `manifest.json` records the model identity, activation boundary, capture
  configuration, actual model/configuration and parameter metadata, library
  versions, UTC capture/forward intervals and source-file hashes.
  `capture_config_sha256` hashes UTF-8 JSON with sorted keys,
  `ensure_ascii=False`, compact separators and no terminal newline.
- `source_files` lists the capture script, source text and locally present model
  assets. Upstream assets have URLs pinned to the public revision; local cache
  paths are not published. All seven required asset sizes and hashes are checked
  against the pinned revision. Optional license/notice file hashes identify the
  supplied local bytes without a separate pinned-digest assertion.

## Provenance and scope

The [Pythia model repository](https://huggingface.co/EleutherAI/pythia-14m)
declares Apache-2.0 for its weights. Model weights are not committed here.
[LICENSE-model.txt](LICENSE-model.txt) preserves the standard Apache-2.0 text
verbatim from the [Apache Software Foundation](https://www.apache.org/licenses/LICENSE-2.0.txt).
Retain that license and any applicable upstream notice with the trace's model
provenance when redistributing it; the repository MIT license does not relicense
upstream weights. The original input prose and capture code are MIT.

This is forward-only capture of frozen pretrained activations. A later backward
replay can differentiate an independent query/operator over the detached bank;
it does not include backbone gradients, train the language model, or measure
end-to-end training memory. The fixture does not establish language-model
quality, perplexity, GPU throughput, or an advantage for an AttnRes architecture.
