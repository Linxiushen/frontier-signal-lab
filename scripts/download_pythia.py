"""Download only seven immutable, size/SHA256-pinned Pythia assets."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

if __package__:
    from .capture_real_activation import MODEL_ID, MODEL_REVISION, PINNED_ASSETS
else:
    from capture_real_activation import MODEL_ID, MODEL_REVISION, PINNED_ASSETS


def sha(data):
    return hashlib.sha256(data).hexdigest()


def download(output):
    output.mkdir(parents=True,exist_ok=True)
    records=[]
    for name,(size,expected_sha) in PINNED_ASSETS.items():
        started=datetime.now(timezone.utc).isoformat()
        path=output/name
        origin=f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/{name}"
        cached=path.is_file() and path.stat().st_size==size and sha(path.read_bytes())==expected_sha
        if not cached:
            request=urllib.request.Request(origin,headers={"User-Agent":"frontier-signal-lab/pinned-model-reproduction"})
            with urllib.request.urlopen(request,timeout=60) as response:
                data=response.read(size+1)
                status=response.status
            if status!=200 or len(data)!=size or sha(data)!=expected_sha:
                raise ValueError("immutable model asset size/hash/status mismatch: "+name)
            temporary=path.with_suffix(path.suffix+".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
        records.append({"name":name,"origin_url":origin,"bytes":size,"sha256":expected_sha,
            "verified_existing_cache":cached,"started_at":started,
            "completed_at":datetime.now(timezone.utc).isoformat()})
    return {"model_id":MODEL_ID,"revision":MODEL_REVISION,"license":"Apache-2.0",
        "license_copy":"fixtures/real-activation/LICENSE-model.txt",
        "files":records,"weights_committed":False,
        "scope":"No repository code, pickle, remote execution, API or GPU usage. Existing optional loader overrides are rejected by capture/training validation."}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--record",type=Path,required=True)
    args=parser.parse_args()
    result=download(args.output)
    args.record.parent.mkdir(parents=True,exist_ok=True)
    args.record.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"verified_assets":len(result["files"]),"revision":MODEL_REVISION}))


if __name__=="__main__":
    main()
