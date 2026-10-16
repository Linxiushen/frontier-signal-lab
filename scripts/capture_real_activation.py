"""Capture a frozen Pythia residual bank from already-downloaded local assets.

The model forward pass is offline and gradient-free. The resulting detached bank
can drive an operator replay; it is not an AttnRes network or model training run.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform


MODEL_ID = "EleutherAI/pythia-14m"
MODEL_REVISION = "cf967c0a9a04383db6f7b1108d86b2962634b4ac"
WEIGHTS_SHA256 = "116a02532db461f91386a5b20f942ff2c8d4de7341e21b55caafc3d7b25f49a1"
WEIGHTS_BYTES = 28_143_920
MAX_SOURCE_BYTES = 64 * 1024
PINNED_ASSETS = {
    "README.md": (10_560, "d1f2cf1d5181daedeaa70208ddd5cc5251867bde9acf6db7bb45a2265e25e163"),
    "config.json": (698, "f97f966a66c444890ed461fff2a51eefb15d74303df05b948124719f199b0b17"),
    "generation_config.json": (111, "494cbba887cc299273f0c54d7612596918e74c7881a27cbd95e4e7e2464ea090"),
    "model.safetensors": (WEIGHTS_BYTES, WEIGHTS_SHA256),
    "special_tokens_map.json": (441, "10b8c8852c1e1f70b54d9aff61728408c28971c0e97a6c5a7b2debbd1d3e9c0c"),
    "tokenizer.json": (2_114_042, "870f4e2baa6b683221fa52004d5d6f40ab8c9d31961617304b78c910c2c3caf2"),
    "tokenizer_config.json": (4_834, "eee017c5bd133137f45907bd0a6e781e2ccd1a533734b7ed2a2f2f4446659809"),
}
BATCH_SIZE = 4
SEQUENCE_LENGTH = 128
DEPTH = 6
WIDTH = 128
TOTAL_TOKENS = BATCH_SIZE * SEQUENCE_LENGTH
REPOSITORY = Path(__file__).resolve().parents[1]
MODEL_ASSETS = (
    "config.json", "generation_config.json", "model.safetensors",
    "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json",
    "added_tokens.json", "vocab.json", "merges.txt", "vocab.txt",
    "tokenizer.model", "chat_template.jinja", "README.md", "LICENSE",
    "LICENSE.txt", "NOTICE",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_json(path: Path, value: object) -> None:
    # Hash consumers use the actual UTF-8 file bytes, including this final LF.
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2,
                                 allow_nan=False) + "\n").encode("utf-8"))


def owned_source_record(path: Path) -> dict:
    try:
        label = path.resolve().relative_to(REPOSITORY).as_posix()
        origin = "this_repository"
    except ValueError:
        # A caller-supplied source must not leak an absolute local path.
        label, origin = "input/source.txt", "caller_supplied_local_file"
    return {"path": label, "sha256": file_sha256(path), "origin": origin}


def capture(model_dir: Path, output: Path, source: Path) -> dict:
    started_at = utc_now()
    model_dir, source = model_dir.resolve(), source.resolve()
    if not model_dir.is_dir():
        raise ValueError("--model-dir must be an existing local model directory")
    if not source.is_file():
        raise ValueError("--source must be an existing UTF-8 text file")
    for name, (expected_bytes, expected_sha256) in PINNED_ASSETS.items():
        asset = model_dir / name
        if not asset.is_file():
            raise ValueError(f"missing required local model asset: {name}")
        if asset.stat().st_size != expected_bytes or file_sha256(asset) != expected_sha256:
            raise ValueError(f"{name} does not match the pinned Pythia-14m size/SHA256")
    # These optional files could override tokenizer/model behavior but are not
    # present in the pinned asset set. Do not silently consume local additions.
    loader_overrides = ("added_tokens.json", "vocab.json", "merges.txt", "vocab.txt",
                        "tokenizer.model", "chat_template.jinja", "adapter_config.json")
    if any((model_dir / name).exists() for name in loader_overrides):
        raise ValueError("local model directory contains an unpinned loader override")
    with source.open("rb") as stream:
        source_bytes = stream.read(MAX_SOURCE_BYTES + 1)
    if len(source_bytes) > MAX_SOURCE_BYTES:
        raise ValueError("source text exceeds the 64 KiB capture limit")
    source_text = source_bytes.decode("utf-8")
    raw_config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    if (raw_config.get("model_type") != "gpt_neox"
            or raw_config.get("num_hidden_layers") != DEPTH
            or raw_config.get("hidden_size") != WIDTH
            or raw_config.get("max_position_embeddings", 0) < SEQUENCE_LENGTH):
        raise ValueError("pinned configuration does not satisfy the expected architecture/context")

    # Set these before importing Transformers/Hugging Face modules. Both loaders
    # additionally require local files and disallow repository-provided code.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    import numpy as np
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(0)
    np.random.seed(0)
    torch.use_deterministic_algorithms(True)
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False,
        use_fast=True,
    )
    encoded = tokenizer(
        source_text, add_special_tokens=False, padding=False, truncation=False,
        return_attention_mask=False,
    )["input_ids"]
    if len(encoded) < TOTAL_TOKENS:
        raise ValueError(f"source must yield at least {TOTAL_TOKENS} tokens; got {len(encoded)}")
    ids = [int(token) for token in encoded[:TOTAL_TOKENS]]
    input_ids = torch.tensor(ids, dtype=torch.long, device="cpu").reshape(
        BATCH_SIZE, SEQUENCE_LENGTH)
    model = AutoModelForCausalLM.from_pretrained(
        str(model_dir), local_files_only=True, trust_remote_code=False,
        use_safetensors=True, dtype=torch.float32,
        attn_implementation="eager",
    ).to(device="cpu", dtype=torch.float32)
    model.eval()
    model.requires_grad_(False)
    config = model.config
    if (config.model_type != "gpt_neox"
            or config.num_hidden_layers != DEPTH or config.hidden_size != WIDTH):
        raise ValueError("local model config is not the expected six-layer, width-128 GPT-NeoX")
    max_context = int(config.max_position_embeddings)
    if SEQUENCE_LENGTH > max_context:
        raise ValueError(f"sequence length {SEQUENCE_LENGTH} exceeds model context {max_context}")
    layers = model.gpt_neox.layers
    if len(layers) != DEPTH:
        raise ValueError("loaded GPT-NeoX layer count does not match expected depth")
    if config._attn_implementation != "eager":
        raise ValueError("loaded attention implementation must be eager")
    parameter_dtypes = sorted({str(p.dtype) for p in model.parameters()})
    parameter_devices = sorted({str(p.device) for p in model.parameters()})
    if parameter_dtypes != ["torch.float32"] or parameter_devices != ["cpu"]:
        raise ValueError("all model parameters must be CPU float32")

    captured = {}
    calls = [0] * DEPTH

    def make_hook(index: int):
        def pre_hook(_module, args, kwargs):
            hidden = kwargs.get("hidden_states")
            if hidden is None and args:
                hidden = args[0]
            if not isinstance(hidden, torch.Tensor):
                raise ValueError(f"layer {index} pre-hook did not receive hidden_states")
            if tuple(hidden.shape) != (BATCH_SIZE, SEQUENCE_LENGTH, WIDTH):
                raise ValueError(f"unexpected pre-block residual shape at layer {index}")
            calls[index] += 1
            if calls[index] != 1:
                raise ValueError(f"layer {index} executed more than once")
            # Clone at entry so later model operations cannot mutate the snapshot.
            captured[index] = hidden.detach().to(device="cpu", dtype=torch.float32).contiguous().clone()
        return pre_hook

    handles = [layer.register_forward_pre_hook(make_hook(index), with_kwargs=True)
               for index, layer in enumerate(layers)]
    forward_started_at = utc_now()
    try:
        with torch.no_grad():
            forward_output = model(
                input_ids=input_ids, attention_mask=torch.ones_like(input_ids),
                use_cache=False, output_attentions=False,
                output_hidden_states=False, return_dict=True,
            )
        del forward_output
    finally:
        for handle in handles:
            handle.remove()
    forward_finished_at = utc_now()
    if calls != [1] * DEPTH or sorted(captured) != list(range(DEPTH)):
        raise ValueError("each of the six layer pre-hooks must capture exactly once")
    bank = np.ascontiguousarray(np.stack([
        captured[index].reshape(TOTAL_TOKENS, WIDTH).numpy()
        for index in range(DEPTH)
    ]), dtype=np.dtype("<f4"))
    if bank.shape != (DEPTH, TOTAL_TOKENS, WIDTH) or not np.isfinite(bank).all():
        raise ValueError("captured residual bank has an invalid shape or nonfinite values")

    capture_config = {
        "device": "cpu", "dtype": "float32", "seed": 0,
        "torch_num_threads": torch.get_num_threads(),
        "torch_num_interop_threads": torch.get_num_interop_threads(),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "model_eval": not model.training, "model_parameters_frozen": True,
        "grad_mode": "no_grad", "attention_implementation": config._attn_implementation,
        "use_cache": False, "output_hidden_states": False,
        "output_attentions": False, "return_dict": True,
        "batch_size": BATCH_SIZE, "sequence_length": SEQUENCE_LENGTH,
        "total_tokens": TOTAL_TOKENS, "source_token_count": len(encoded),
        "token_selection": "first_512_without_special_tokens",
        "add_special_tokens": False, "padding": False, "truncation": False,
        "attention_mask": "all_ones", "reshape_order": "row_major",
        "position_ids": "model_default_independent_0_to_127_per_sequence",
        "independent_sequence_contexts": True,
        "layer_indices": list(range(DEPTH)),
        "activation_boundary": "pre_block_residual",
        "pre_hook_with_kwargs": True, "pre_hook_calls": calls,
        "flatten_order": "batch_then_token",
        "local_files_only": True, "trust_remote_code": False,
        "use_safetensors": True,
        "source_byte_limit": MAX_SOURCE_BYTES,
    }
    output.mkdir(parents=True, exist_ok=True)
    token_file, trace_file = output / "token_ids.json", output / "bank.npz"
    write_json(token_file, input_ids.tolist())
    np.savez(trace_file, bank=bank)
    source_files = [owned_source_record(Path(__file__)), owned_source_record(source)]
    for name in MODEL_ASSETS:
        asset = model_dir / name
        if asset.is_file():
            source_files.append({
                "path": f"model/{name}", "sha256": file_sha256(asset),
                "origin_url": f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/{name}",
                "pinned_size_and_sha256_verified": name in PINNED_ASSETS,
            })
    # Transformers populates this field with the caller's local directory.
    public_config = {key: value for key, value in config.to_dict().items()
                     if key not in ("_name_or_path", "name_or_path")}
    versions = {name: importlib.metadata.version(name)
                for name in ("torch", "transformers", "numpy", "safetensors", "tokenizers")}
    versions["python"] = platform.python_version()
    manifest = {
        "schema_version": 1, "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "activation_boundary": "pre_block_residual", "trace_file": "bank.npz",
        "trace_file_sha256": file_sha256(trace_file),
        "bank_sha256": hashlib.sha256(bank.tobytes(order="C")).hexdigest(),
        "bank_shape": list(bank.shape), "bank_dtype": "float32",
        "bank_byte_order": "little", "bank_order": "C", "npz_keys": ["bank"],
        "source_text_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "token_ids_file": "token_ids.json", "token_ids_sha256": file_sha256(token_file),
        "token_ids_hash_convention": "actual UTF-8 token_ids.json file bytes, including final LF",
        "token_ids_shape": [BATCH_SIZE, SEQUENCE_LENGTH],
        "capture_config": capture_config,
        "capture_config_sha256": hashlib.sha256(canonical_json(capture_config)).hexdigest(),
        "capture_config_hash_convention": "UTF-8 JSON, sorted keys, ensure_ascii=False, compact separators, no final newline",
        "source_files": source_files, "library_versions": versions,
        "capture_started_at_utc": started_at, "forward_started_at_utc": forward_started_at,
        "forward_finished_at_utc": forward_finished_at, "capture_completed_at_utc": utc_now(),
        "model_config": public_config,
        "actual_model": {
            "class": type(model).__name__, "layer_class": type(layers[0]).__name__,
            "tokenizer_class": type(tokenizer).__name__, "parameter_count": sum(p.numel() for p in model.parameters()),
            "trainable_parameter_count": sum(p.numel() for p in model.parameters() if p.requires_grad),
            "parameter_dtypes": parameter_dtypes, "parameter_devices": parameter_devices,
            "max_position_embeddings": max_context,
        },
        "provenance": {
            "model_license": "Apache-2.0", "weights_sha256_verified": WEIGHTS_SHA256,
            "weights_bytes_verified": WEIGHTS_BYTES,
            "pinned_asset_sha256s_verified": {name: digest for name, (_size, digest) in PINNED_ASSETS.items()},
            "model_repository_url": f"https://huggingface.co/{MODEL_ID}/tree/{MODEL_REVISION}",
            "local_asset_origin_note": "All seven required assets are size/SHA256 checked against the pinned revision before loading. Optional local license/notice files have hashes recorded but no separate pinned digest assertion.",
            "source_text_license": "MIT for the original source.txt supplied in this repository; caller-supplied alternatives require their own provenance",
        },
        "scope": "Frozen pretrained GPT-NeoX forward activations; detached pre-block residual bank only.",
        "limitations": [
            "Four independent 128-token sequences, not one 512-token context; flattening preserves batch-then-token order.",
            "Pythia-14m is a conventional residual model, not an AttnRes model. Its six pre-block inputs are the entire captured depth bank; no final post-block state is added.",
            "No backbone gradients or model training are captured. A later query/operator backward replay on this detached bank does not differentiate through the pretrained model.",
            "No language-model quality, perplexity, end-to-end training memory, GPU throughput or architecture advantage is measured by this capture.",
        ],
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True,
                        help="existing local directory containing the pinned assets; never downloaded")
    parser.add_argument("--output", type=Path, default=REPOSITORY / "fixtures/real-activation")
    parser.add_argument("--source", type=Path, default=REPOSITORY / "fixtures/real-activation/source.txt")
    args = parser.parse_args()
    manifest = capture(args.model_dir, args.output, args.source)
    print(json.dumps({key: manifest[key] for key in
                      ("trace_file_sha256", "bank_sha256", "bank_shape", "bank_dtype",
                       "model_id", "model_revision", "capture_config_sha256")}, indent=2))


if __name__ == "__main__":
    main()
