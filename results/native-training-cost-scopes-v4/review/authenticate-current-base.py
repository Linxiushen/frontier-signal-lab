from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,sys
ROOT=Path.cwd();RUN=ROOT/'reports/runs/20261102T065705Z'
BASE=Path(sys.base_prefix).resolve()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def base_inventory():
    files=[];pending=[BASE/'Lib',BASE/'DLLs']
    for p in BASE.iterdir():
        if p.is_file():files.append(p)
    while pending:
        directory=pending.pop()
        if not directory.exists():continue
        with os.scandir(directory) as entries:
            for entry in entries:
                if directory==BASE/'Lib' and entry.name=='site-packages':continue
                info=entry.stat(follow_symlinks=False)
                assert not entry.is_symlink() and not getattr(info,'st_file_attributes',0)&1024
                if entry.is_dir(follow_symlinks=False):pending.append(Path(entry.path))
                else:
                    assert entry.is_file(follow_symlinks=False)
                    files.append(Path(entry.path))
    return sorted([{'path':p.relative_to(BASE).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in files],key=lambda r:r['path'])
if __name__=='__main__':
    auth=json.loads((RUN/'h1-current-python-authentication.json').read_text(encoding='utf-8-sig'))
    assert auth['configured_bundle_version']=='26.1026.10807'
    assert Path(auth['configured_python_path']).resolve()==Path(sys.executable).resolve()
    assert all(r['status']=='Valid' and 'OpenAI OpCo' in r['signer_subject'] and r['signer_thumbprint']=='45E8B6511C6E88838E0038B13037A8B1146858A9' for r in auth['signatures'])
    assert len(auth['signatures'])==3
    files=base_inventory()
    result={'recorded_at':datetime.now(timezone.utc).isoformat(),'base_prefix':str(BASE),'version':sys.version,
        'files':files,'file_count':len(files),'bytes':sum(r['bytes'] for r in files),
        'authentication_sha256':sha(RUN/'h1-current-python-authentication.json'),
        'identity_sha256':sha(RUN/'h1-current-python-identity.json'),
        'scope':'All base-prefix root files, Lib excluding site-packages, and DLLs. Target venv site-packages is independently full-manifest pinned. Actual configured current interpreter; no equivalence to old executable/DLL/stdlib bytes asserted. No ML import or native scientific launch.'}
    path=RUN/'h1-base-standard-library-manifest.json'
    with path.open('x',encoding='utf-8',newline='\n')as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({'status':'authenticated','files':len(files),'bytes':result['bytes'],'manifest_sha256':sha(path)}))
