"""Prepare new original synthetic history/audit blocks; no model execution."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.activation_training_probe import file_hash, write_json
from scripts.capture_real_activation import MODEL_ID, MODEL_REVISION, PINNED_ASSETS

ROOT = Path(__file__).resolve().parents[1]


def synthetic_sources():
    train = []
    audit = []
    places = ("observatory", "harbor", "greenhouse", "library", "workshop", "reservoir")
    for i in range(24):
        place = places[i % len(places)]
        train.append(
            f"Record {i + 1}: At the {place}, the morning team counted {17 + i} sealed boxes. "
            f"The blue ledger listed {9 + i} completed checks and {8} checks still waiting. "
            "A second reader compared the written total with the labels before moving anything. "
            "When a label was unclear, the team kept the box on the marked shelf and recorded the uncertainty. "
            "At noon a fresh observer repeated the count, noted the time, and signed the corrected ledger. "
            "The afternoon shift used that exact revision rather than an older copy."
        )
        audit.append(
            f"Case {i + 1}: A traveling cartographer reached station {41 + i} after sunset. "
            "She drew the footbridge, the river bend, and a narrow path through the orchard. "
            "Her compass reading disagreed with the faded wall map, so she preserved both observations. "
            f"The next morning she measured {23 + i} paces to the gate and {31 + i} paces to the well. "
            "A local guide explained which stones had been moved during the winter flood. "
            "They wrote a dated correction on a separate sheet and left the original map intact."
        )
    return {"train": "\n\n".join(train) + "\n", "audit": "\n\n".join(audit) + "\n"}


def prepare(model_dir, output):
    from tokenizers import Tokenizer
    output = Path(output)
    targets = [output / name for name in ("train.txt", "audit.txt", "data.json", "manifest.json")]
    if any(path.exists() for path in targets):
        raise ValueError("fresh fixture paths required")
    tokenizer_path = Path(model_dir) / "tokenizer.json"
    if file_hash(tokenizer_path) != PINNED_ASSETS["tokenizer.json"][1]:
        raise ValueError("pinned tokenizer mismatch")
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    output.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1}
    sources = {}
    for split, source in synthetic_sources().items():
        path = output / (split + ".txt")
        path.write_bytes(source.encode("utf-8"))
        tokens = tokenizer.encode(source, add_special_tokens=False).ids
        count = 8 if split == "train" else 4
        if len(tokens) < count * 65:
            raise ValueError("insufficient source tokens")
        data[split] = [tokens[i * 65:(i + 1) * 65] for i in range(count)]
        sources[split] = {"file": path.name, "sha256": file_hash(path), "source_tokens": len(tokens),
            "selected_tokens": count * 65, "blocks": count, "tokens_per_block": 65,
            "license": "MIT", "origin": "original model-written synthetic prose; numerical diagnostic only"}
    if set(map(tuple, data["train"])) & set(map(tuple, data["audit"])):
        raise ValueError("train/audit block overlap")
    write_json(output / "data.json", data)
    manifest = {"schema_version": 1, "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "data_sha256": file_hash(output / "data.json"), "sources": sources,
        "tokenizer_sha256": file_hash(tokenizer_path), "preparation_script_sha256": file_hash(__file__),
        "recipe": "Pinned tokenizer, no special tokens. First8train and first4audit nonoverlapping65-token blocks; inputs0..63 predict1..64. No padding or cross-source joins.",
        "purpose": "New fixed history batches and audit batches. Audit data are numerical controls, not sealed model-quality holdout."}
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "fixtures/activation-history")
    args = parser.parse_args()
    prepare(args.model_dir, args.output)


if __name__ == "__main__":
    main()
