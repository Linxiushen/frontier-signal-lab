"""Tokenize original disjoint prose for a small, fixed training-cost diagnostic."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

if __package__:
    from .capture_real_activation import MODEL_ID, MODEL_REVISION, PINNED_ASSETS
else:
    from capture_real_activation import MODEL_ID, MODEL_REVISION, PINNED_ASSETS

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {
    "steps": 24, "batch_size": 2, "sequence_length": 64,
    "train_blocks": 8, "holdout_blocks": 8, "seeds": [11, 29, 47],
    "learning_rate": 1e-4, "optimizer": "AdamW", "weight_decay": 0.0,
    "betas": [0.9, 0.999], "optimizer_eps": 1e-8,
    "max_training_seconds_per_worker": 180,
    "methods": ["dense", "int8_saved_tensors"],
    "compression": "eligible non-parameter-backed finite CPU float32 tensors with at least256elements, symmetric maxabs per last dimension; backward saved-tensor approximation only",
    "evaluation": "initial and final heldout NLL only; no intermediate holdout selection",
    "budget": "matched training tokens/steps; wall-clock measured, not matched; time limit aborts incomplete runs",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def prepare(model_dir, output):
    started = datetime.now(timezone.utc).isoformat()
    if (output/"manifest.json").exists():
        raise ValueError("output already contains a manifest; use a fresh output directory")
    # Only tokenizer assets are opened; model weights are neither loaded nor run.
    asset_records = {}
    for name in ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]:
        data = (model_dir/name).read_bytes()
        expected_size, expected_sha = PINNED_ASSETS[name]
        if len(data) != expected_size or digest(data) != expected_sha:
            raise ValueError("tokenizer asset does not match pinned revision: "+name)
        asset_records[name] = {"bytes":len(data), "sha256":digest(data),
            "origin_url":f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/{name}"}
    for name in ["added_tokens.json", "vocab.json", "merges.txt", "vocab.txt", "tokenizer.model", "chat_template.jinja"]:
        if (model_dir/name).exists():
            raise ValueError("unpinned tokenizer override: "+name)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True,
        trust_remote_code=False, use_fast=True)
    sources = {"train":ROOT/"fixtures/real-activation/source.txt",
               "holdout":ROOT/"fixtures/activation-training/holdout.txt"}
    result = {"schema_version":1}
    records = {}
    for split, path in sources.items():
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw)>65536:
            raise ValueError("source exceeds64KiB")
        ids = tokenizer(raw.decode("utf-8"), add_special_tokens=False, padding=False,
            truncation=False, return_attention_mask=False)["input_ids"]
        count = CONFIG[split+"_blocks"]
        width = CONFIG["sequence_length"]+1
        if len(ids)<count*width:
            raise ValueError("source has insufficient tokens for "+split)
        result[split] = [[int(v) for v in ids[i*width:(i+1)*width]] for i in range(count)]
        records[split] = {"path":path.relative_to(ROOT).as_posix(),"sha256":digest(raw),
            "source_tokens":len(ids),"selected_tokens":count*width,
            "selected_target_positions":count*(width-1),"license":"MIT", "origin":"original model-written synthetic prose in this repository"}
    if records["train"]["sha256"]==records["holdout"]["sha256"]:
        raise ValueError("train and holdout source must differ")
    if {tuple(b) for b in result["train"]} & {tuple(b) for b in result["holdout"]}:
        raise ValueError("exact token blocks overlap across split")
    output.mkdir(parents=True, exist_ok=True)
    write(output/"data.json",result)
    manifest = {"schema_version":1,"data_sha256":digest((output/"data.json").read_bytes()),
        "model_id":MODEL_ID,"model_revision":MODEL_REVISION,
        "train_source_sha256":records["train"]["sha256"],
        "holdout_source_sha256":records["holdout"]["sha256"],
        "tokenizer_sha256":asset_records["tokenizer.json"]["sha256"],
        "source_files":records,"tokenizer_assets":asset_records,
        "predeclared_config":CONFIG,"predeclared_config_sha256":digest(canonical(CONFIG)),
        "preparation_script_sha256":digest(Path(__file__).read_bytes()),
        "started_at":started,"completed_at":datetime.now(timezone.utc).isoformat(),
        "library_versions":{k:importlib.metadata.version(k) for k in ["transformers","tokenizers"]},
        "split_protocol":"Separate complete source files; take first8nonoverlapping65token blocks from each. No padding/special tokens, no cross-file joins.64inputs predict positions1..64. Unused suffixes excluded.",
        "limitations":["Tiny synthetic prose diagnostic, not a natural language benchmark or general model-quality claim.","The original train prose was used previously for frozen forward capture; it was not held out in that earlier experiment.","Equal token/step budgets only. Timing and process peaks remain machine-specific observations.","Training with backward saved-tensor compression is independent activation-memory research, not an AttnRes implementation."]}
    write(output/"manifest.json",manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=ROOT/"fixtures/activation-training")
    args=parser.parse_args()
    result=prepare(args.model_dir,args.output)
    print(json.dumps({k:result[k] for k in ["data_sha256","predeclared_config_sha256","train_source_sha256","holdout_source_sha256"]},indent=2))


if __name__=="__main__":
    main()
