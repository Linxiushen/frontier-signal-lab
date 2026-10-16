"""Freeze a separate-book natural-text diagnostic without loading a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.capture_real_activation import MODEL_ID, MODEL_REVISION, PINNED_ASSETS

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "train": ("alice.txt", "https://www.gutenberg.org/ebooks/11", "Alice's Adventures in Wonderland",
              "01b38ea4c710a84bc18d0bd41271a5a1a92b94e97b2812f4dece97d4a694725e", "CHAPTER I.\nDown the Rabbit-Hole", 128),
    "holdout": ("looking-glass.txt", "https://www.gutenberg.org/ebooks/12", "Through the Looking-Glass",
                "e40a38f5da841f9fb6acc557355c447b7c2ccb56a208caf5fcf2b05081f14d42", "CHAPTER I.\nLooking-Glass house", 64),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def prepare(model_dir, source_dir, output):
    from tokenizers import Tokenizer
    output, source_dir = Path(output), Path(source_dir)
    if output.exists():
        raise ValueError("fresh nonexistent fixture directory required")
    tokenizer_raw = (Path(model_dir) / "tokenizer.json").read_bytes()
    if sha(tokenizer_raw) != PINNED_ASSETS["tokenizer.json"][1]:
        raise ValueError("pinned tokenizer mismatch")
    tokenizer = Tokenizer.from_str(tokenizer_raw.decode("utf-8"))
    previous = set()
    for path in (ROOT / "fixtures").glob("activation-*/data.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for rows in data.values():
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, list) and all(type(x) is int for x in row):
                        previous.add(tuple(row))
    prepared, source_records, selected = {}, {}, set()
    for split, (name, url, title, expected, marker, count) in SOURCES.items():
        raw = (source_dir / name).read_bytes()
        if sha(raw) != expected:
            raise ValueError("frozen upstream source bytes changed: " + split)
        text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
        start = text.index(marker)
        end = text.index("*** END OF THE PROJECT GUTENBERG EBOOK", start)
        body = text[start:end]
        tokens = tokenizer.encode(body, add_special_tokens=False).ids
        if len(tokens) < count * 65:
            raise ValueError("insufficient fixed source tokens")
        blocks = [tokens[i * 65:(i + 1) * 65] for i in range(count)]
        current = set(map(tuple, blocks))
        if len(current) != count or current & (previous | selected):
            raise ValueError("duplicate/prior/cross-split full block overlap")
        selected.update(current)
        prepared[split] = {"schema_version": 1, split: blocks}
        source_records[split] = {
            "file": name, "source_url": url, "author": "Lewis Carroll (1832-1898)", "title": title,
            "source_sha256": expected, "source_bytes": len(raw),
            "source_rights": "Public domain in the USA according to the source catalog; complete Project Gutenberg wrapper and license retained in the exact source file.",
            "normalized_body_sha256": sha(body.encode("utf-8")),
            "normalization": "UTF-8-sig decode; CRLF/CR to LF; slice from the unique chapter-I heading through before the END marker.",
            "body_start_character": start, "body_end_character": end, "body_start_marker": marker,
            "body_token_count": len(tokens), "selected_token_count": count * 65,
            "block_count": count, "tokens_per_block": 65, "targets_per_block": 64,
            "mapping": [{"block": i, "body_token_start": i * 65, "body_token_end_exclusive": (i + 1) * 65} for i in range(count)],
            "chapter_boundaries": "Contiguous token blocks may cross chapter boundaries within this one book; no source-file concatenation or header/footer/license tokens.",
        }
    output.mkdir(parents=True)
    for split, (name, *_) in SOURCES.items():
        (output / name).write_bytes((source_dir / name).read_bytes())
        write_json(output / (split + ".json"), prepared[split])
    manifest = {
        "schema_version": 1, "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "train_sha256": sha((output / "train.json").read_bytes()),
        "holdout_sha256": sha((output / "holdout.json").read_bytes()),
        "tokenizer_sha256": sha(tokenizer_raw),
        "train_source_sha256": source_records["train"]["source_sha256"],
        "holdout_source_sha256": source_records["holdout"]["source_sha256"],
        "preparation_script_sha256": sha(Path(__file__).read_bytes()), "sources": source_records,
        "recipe": "First128 train/64 holdout nonoverlapping65-token blocks, no special tokens/padding. Each block positions0..63 predict1..64. Mechanical selection only; exact full-block duplicates and prior fixture reuse rejected.",
        "evaluation_boundary": "All fixed endpoints must finish before a separate evaluator computes initial/final heldout losses. Public visible test bytes, local procedural seal only; no pretraining cleanliness or broad quality claim.",
        "previous_full_blocks_checked": len(previous), "full_blocks_are_disjoint": True,
    }
    write_json(output / "manifest.json", manifest)
    return {"train_sha256": manifest["train_sha256"], "holdout_sha256": manifest["holdout_sha256"],
            "manifest_sha256": sha((output / "manifest.json").read_bytes()), "blocks": {"train": 128, "holdout": 64}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "fixtures/activation-cost")
    args = parser.parse_args()
    print(json.dumps(prepare(args.model_dir, args.source_dir, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
