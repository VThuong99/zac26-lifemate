"""Verify materialized release artifacts against reviewed SHA-256 manifests."""
import argparse
import hashlib
import json
from pathlib import Path

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--image',action='store_true')
    args=parser.parse_args()
    source=Path(__file__).resolve().parent
    base=source.parent
    checks=[]
    for item in json.loads((source/'manifests/models.json').read_text()):
        rel=Path(item['path']).relative_to('model_artifacts/runtime')
        path=(source/'runtime'/rel) if args.image else base/item['path']
        checks.append((path,item['sha256']))
    for item in json.loads((source/'manifests/native.json').read_text()):
        path=(source/item['path']) if args.image else base/item['path']
        checks.append((path,item['sha256']))
    for item in json.loads((source/'manifests/python-files.json').read_text()):
        path=(Path('/opt/k-python')/item['path']) if args.image else base/'dependencies'/item['path']
        checks.append((path,item['sha256']))
    for item in json.loads((source/'manifests/source-release.json').read_text()):
        checks.append((source/item['path'],item['sha256']))
    failed=[str(p) for p,h in checks if not p.is_file() or sha(p)!=h]
    print(json.dumps({'checked':len(checks),'mismatches':failed}))
    if failed:raise SystemExit(1)

if __name__=='__main__':main()
