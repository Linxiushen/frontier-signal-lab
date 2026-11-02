"""Curate saved bytes only; never launch the producer or load a model."""
from pathlib import Path
from datetime import datetime, timezone
import gzip
import hashlib
import json
import re

ROOT = Path.cwd()
RUN = ROOT / 'reports/runs/20261102T065705Z'
RAW = RUN / 'native-training-cost-scopes-v4'
DEST = ROOT / 'results/native-training-cost-scopes-v4'
MAINT = RUN / 'maintenance/resume-20261102T090052Z'
sha = lambda b: hashlib.sha256(b).hexdigest()
now = lambda: datetime.now(timezone.utc).isoformat()
rel = lambda p: p.relative_to(ROOT).as_posix()
selected = {}


def save(path, data, source=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    assert path.read_bytes() == data
    selected[rel(path)] = {'bytes': len(data), 'sha256': sha(data),
                           'source': rel(source) if source else 'curation_metadata'}


def save_json(path, data):
    save(path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())


assert (RUN / 'h1-suite-completed.json').exists() and (RAW / 'report.json').exists()
assert not DEST.exists()
files = sorted(p for p in RAW.rglob('*') if p.is_file())
assert not any(p.is_symlink() for p in RAW.rglob('*'))
before = {p.relative_to(RAW).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
          for p in files}
rows = []
for source in files:
    path = source.relative_to(RAW).as_posix()
    checkpoint = source.suffix == '.pt'
    row = {'path': path, **before[path], 'published': not checkpoint}
    if checkpoint:
        row.update(public_path=None, encoding=None,
                   omission='Model checkpoint retained locally; only its exact size/hash is public. Public metadata replay cannot reload or independently reevaluate this checkpoint.')
    else:
        data = source.read_bytes()
        compressed = len(data) >= 131072
        packed = gzip.compress(data, mtime=0) if compressed else data
        target = DEST / 'raw' / (path + '.gz' if compressed else path)
        save(target, packed, source)
        assert (gzip.decompress(target.read_bytes()) if compressed else target.read_bytes()) == data
        row.update(public_path=target.relative_to(DEST).as_posix(), encoding='gzip' if compressed else 'identity',
                   public_bytes=len(packed), public_sha256=sha(packed), exact_original_bytes_verified=True)
    rows.append(row)
save_json(DEST / 'raw-manifest.json', {
    'recorded_at': now(), 'source_directory': rel(RAW),
    'original_file_count': len(files), 'original_byte_total': sum(v['bytes'] for v in before.values()),
    'published_metadata_file_count': sum(r['published'] for r in rows),
    'published_metadata_original_bytes': sum(r['bytes'] for r in rows if r['published']),
    'published_metadata_stored_bytes': sum(r.get('public_bytes', 0) for r in rows),
    'omitted_checkpoint_count': sum(not r['published'] for r in rows),
    'omitted_checkpoint_bytes': sum(r['bytes'] for r in rows if not r['published']),
    'scope': 'All noncheckpoint raw files retained byte-identically, either directly or as verified lossless gzip. All model checkpoints stay local; complete original hashes/sizes are listed. No model execution during curation.',
    'files': rows,
})
review = [
    RUN / name for name in [
        'execute-h1-once.py', 'h1-suite-reserved.json', 'h1-suite-completed.json',
        'h1-execution.stdout.log', 'h1-execution.stderr.log', 'h1-execution-plan.json',
        'h1-prefreeze-review.json', 'h1-qualified-prefreeze-review.json',
        'h1-runtime-preflight.json', 'h1-current-python-authentication.json',
        'h1-current-python-identity.json', 'authenticate-current-base.py',
        'prepare-h1-v4.py', 'h1-focused-prefreeze.receipt.json',
        'h1-focused-prefreeze.stdout.log', 'h1-focused-prefreeze.stderr.log',
    ]
]
review += [MAINT / name for name in [
    'h1-initial-prefreeze-findings.json', 'h1-independent-qualified-prefreeze-review.json',
    'h1-independent-prefreeze-accepted.json', 'review-h1-prefreeze.py',
    'h1-independent-base-signatures.json',
    'h1-independent-outcome-review.json', 'review-h1-outcome.py',
    'h1-independent-outcome-accepted-review.json', 'h1-post-outcome-paired-supplement.json',
    'h1-independent-evaluator-supplement.json', 'h1-independent-evaluator-supplement-v2.json',
    'review-h1-evaluator-supplement.py', 'review-h1-evaluator-supplement-v2.py',
    'compose-h1-outcome-review.py',
]]
for source in review:
    assert source.is_file(), source
    save(DEST / 'review' / source.name, source.read_bytes(), source)
inventories = []
for source, name in [
    (ROOT / 'reports/runs/20261031T080306Z/h1-static/runtime-manifest.json', 'prepared-runtime-full-inventory.json.gz'),
    (RUN / 'h1-base-standard-library-manifest.json', 'current-base-full-inventory.json.gz'),
]:
    data = source.read_bytes(); packed = gzip.compress(data, mtime=0)
    target = DEST / 'review' / name
    save(target, packed, source)
    assert gzip.decompress(target.read_bytes()) == data
    inventories.append({'source': rel(source), 'source_bytes': len(data), 'source_sha256': sha(data),
                        'public_path': target.relative_to(DEST).as_posix(),
                        'gzip_bytes': len(packed), 'gzip_sha256': sha(packed), 'roundtrip_exact': True})
save_json(DEST / 'review/inventory-compression-manifest.json', {'recorded_at': now(), 'inventories': inventories})
secret = re.compile(rb'(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{25,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|Authorization:\s*Bearer\s+\S+)', re.I)
for name in selected:
    path = ROOT / name
    data = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
    assert not secret.search(data), name
assert not any(p.is_symlink() for p in RAW.rglob('*'))
assert before == {p.relative_to(RAW).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p.read_bytes())}
                  for p in RAW.rglob('*') if p.is_file()}
assert not list(DEST.rglob('*.pt'))
receipt = {'recorded_at': now(), 'status': 'byte_verified', 'selected': selected,
           'raw_original_files': len(files), 'raw_original_bytes': sum(r['bytes'] for r in before.values()),
           'metadata_files': sum(r['published'] for r in rows),
           'metadata_stored_bytes': sum(r.get('public_bytes', 0) for r in rows),
           'checkpoint_count': sum(not r['published'] for r in rows),
           'checkpoint_bytes': sum(r['bytes'] for r in rows if not r['published']),
           'all_raw_bytes_unchanged': True, 'all_gzip_roundtrips_exact': True,
           'scientific_suites': 0, 'native_jobs': 0, 'model_loads': 0}
with (RUN / 'h1-evidence-curation-receipt.json').open('x', encoding='utf-8', newline='\n') as stream:
    json.dump(receipt, stream, ensure_ascii=False, indent=2); stream.write('\n')
print(json.dumps({k: v for k, v in receipt.items() if k != 'selected'}))
