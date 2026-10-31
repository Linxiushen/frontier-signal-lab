"""Prepare an isolated 4.57.3 runtime with one explicit initialization backport.

This copies files; it never imports Torch/Transformers or runs a model. The
directory enumeration change follows Hugging Face Transformers PR #44253
(Apache-2.0, commit 652f2f7a50096f1fc65356b4e7bb1b50fe1888fc).
Unlike that upstream patch, this backport retains 4.57.3's module filtering.
Native startup and training still require their own frozen caller execution.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

SOURCE_SHA256 = "66b2ac40be2c538dbd9409370c1f6bf769934b8b232edac365e16299c5ec1108"
RELATIVE_SOURCE = "Lib/site-packages/transformers/utils/import_utils.py"
OLD = '''    for f in os.listdir(module_path):
        if f != "__pycache__" and os.path.isdir(os.path.join(module_path, f)):
            import_structure[f] = create_import_structure_from_path(os.path.join(module_path, f))

        elif not os.path.isdir(os.path.join(directory, f)):
            adjacent_modules.append(f)
'''
NEW = '''    with os.scandir(module_path) as entries:
        for entry in entries:
            if entry.name == "__pycache__":
                continue
            if entry.is_dir():
                import_structure[entry.name] = create_import_structure_from_path(entry.path)
            else:
                adjacent_modules.append(entry.name)
'''
MAX_FILES = 30000
MAX_BYTES = 1024 ** 3


def digest(data):
    return hashlib.sha256(data).hexdigest()


def patch_source(raw):
    if digest(raw) != SOURCE_SHA256:
        raise ValueError("Only the reviewed, unmodified Transformers 4.57.3 source is supported")
    text = raw.decode("utf-8")
    if text.count(OLD) != 1:
        raise ValueError("Reviewed enumeration block is not unique")
    changed = text.replace(OLD, NEW, 1)
    ast.parse(changed)
    return changed.encode("utf-8")


def inventory(root):
    """No symlink/junction traversal; retain existing bytecode and timestamps."""
    root = Path(root).resolve(strict=True)
    rows, total, pending = [], 0, [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & 1024:
                    raise ValueError("Linked/reparse runtime entries are unsupported")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise ValueError("Only ordinary runtime files are supported")
                total += info.st_size
                if len(rows) >= MAX_FILES or total > MAX_BYTES:
                    raise ValueError("Runtime inventory exceeds fixed preparation ceiling")
                rows.append({"path": Path(entry.path).relative_to(root).as_posix(),
                             "bytes": info.st_size, "sha256": digest(Path(entry.path).read_bytes())})
    return sorted(rows, key=lambda row: row["path"])


def prepare(source, destination):
    source, destination = Path(source).resolve(strict=True), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("A disjoint, new runtime directory is required")
    if destination.exists():
        raise FileExistsError(destination)
    raw = (source / RELATIVE_SOURCE).read_bytes()
    patched = patch_source(raw)
    before = inventory(source)
    if shutil.disk_usage(destination.parent).free < sum(row["bytes"] for row in before) + 2 * 1024 ** 3:
        raise ValueError("Preparation must leave at least 2 GiB free")
    destination.mkdir()
    for row in before:
        target = destination / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        data = (source / row["path"]).read_bytes()
        if len(data) != row["bytes"] or digest(data) != row["sha256"]:
            raise ValueError("Source runtime changed during preparation")
        target.write_bytes(patched if row["path"] == RELATIVE_SOURCE else data)
        # Otherwise all copied .pyc files would become stale, introducing a
        # second initialization treatment unrelated to directory enumeration.
        shutil.copystat(source / row["path"], target, follow_symlinks=False)
    after = inventory(destination)
    expected = [dict(row, bytes=len(patched), sha256=digest(patched))
                if row["path"] == RELATIVE_SOURCE else row for row in before]
    if after != expected or inventory(source) != before:
        raise ValueError("Prepared runtime or original runtime differs from declared copy")
    return {"prepared_at": datetime.now(timezone.utc).isoformat(),
            "scope": "Isolated disk copy with one scanner backport; no package import, native startup or model validation",
            "upstream": "https://github.com/huggingface/transformers/pull/44253",
            "filtering": "Original 4.57.3 modular/conversion behavior retained",
            "source_sha256": SOURCE_SHA256, "patched_sha256": digest(patched),
            "files": after, "original_files": before,
            "file_count": len(after), "bytes": sum(row["bytes"] for row in after)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "destination", "manifest"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    # Reserve the receipt before mutating the destination; preserve failed copies.
    with args.manifest.open("x", encoding="utf-8") as stream:
        report = prepare(args.source, args.destination)
        stream.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({key: report[key] for key in ("file_count", "bytes", "patched_sha256")}))


if __name__ == "__main__":
    main()
