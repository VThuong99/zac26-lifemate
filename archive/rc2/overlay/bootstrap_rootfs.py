"""Assemble the pinned public CUDA base locally without a daemon or host overlay mounts.

This is not Docker runtime validation. Never imports the host root filesystem.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile
import urllib.request

BASE=Path(__file__).resolve().parents[1]
STORE=BASE/'image_work'
ROOT=STORE/'rootfs'
DIGEST='sha256:d266e59b88c295bc5fa0e4cef9064eaff84939381b09e2c3d76a5532a303e42d'

def get_token():
    with urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io&scope=repository:nvidia/cuda:pull',timeout=60) as r:
        return json.load(r)['token']

def download(kind,digest):
    dest=STORE/'blobs'/digest.split(':')[1]
    if dest.exists():return dest
    req=urllib.request.Request('https://registry-1.docker.io/v2/nvidia/cuda/'+kind+'/'+digest,
        headers={'Authorization':'Bearer '+get_token(),'Accept':'application/vnd.docker.distribution.manifest.v2+json'})
    h=hashlib.sha256()
    with urllib.request.urlopen(req,timeout=120) as r, dest.with_suffix('.partial').open('xb') as f:
        while block:=r.read(8*1024*1024):h.update(block);f.write(block)
    assert 'sha256:'+h.hexdigest()==digest,('digest mismatch',digest)
    dest.with_suffix('.partial').replace(dest)
    return dest

def remove(path):
    if path.is_symlink() or path.is_file():path.unlink()
    elif path.is_dir():shutil.rmtree(path)

def apply_layer(path):
    # Re-express absolute symlinks as equivalent root-contained relative symlinks.
    # data_filter checks traversal and resolved link targets, and rejects devices.
    with tarfile.open(path,'r:*') as archive:
        for entry in archive:
            name=Path(entry.name)
            if name.is_absolute() or '..' in name.parts:raise RuntimeError('Unsafe base archive path')
            dest=ROOT/name
            if not dest.parent.resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('Escaping layer path')
            if name.name=='.wh..wh..opq':
                if dest.parent.exists():
                    for p in dest.parent.iterdir():remove(p)
                continue
            if name.name.startswith('.wh.'):
                remove(dest.parent/name.name[4:]);continue
            if entry.issym() and entry.linkname.startswith('/'):
                entry.linkname=os.path.relpath(ROOT/entry.linkname.lstrip('/'),dest.parent)
            if entry.ischr() or entry.isblk() or entry.isfifo():continue
            archive.extract(entry,ROOT,filter='data')

def main():
    (STORE/'blobs').mkdir(parents=True,exist_ok=True)
    ROOT.mkdir(exist_ok=False)
    manifest=json.loads(download('manifests',DIGEST).read_text())
    config=download('blobs',manifest['config']['digest'])
    shutil.copy2(config,STORE/'base-config.json')
    (STORE/'base-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Base compressed layer bytes:',sum(x['size'] for x in manifest['layers']),flush=True)
    for i,layer in enumerate(manifest['layers']):
        path=download('blobs',layer['digest']);apply_layer(path)
        print('Applied layer',i+1,len(manifest['layers']),layer['digest'],flush=True)
    print('Pinned public base rootfs ready; Docker launch not tested',flush=True)

if __name__=='__main__':main()
