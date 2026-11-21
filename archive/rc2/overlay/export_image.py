"""Export an assembled, verified rootfs as local OCI and Docker-save artifacts.

No daemon, registry authentication, push, upload or submission is performed.
The artifact remains unqualified until Docker load and runtime tests execute.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

BASE=Path(__file__).resolve().parents[1]
TAG='lifemate-k:k48.46-20261115-rc1'
STAMP='2026-11-15T00:00:00Z'

def digest(path, algorithm='sha256'):
    h=hashlib.new(algorithm)
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''):h.update(b)
    return h.hexdigest()

def encoded(obj):return json.dumps(obj,sort_keys=True,separators=(',',':')).encode()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--assembled-rootfs',type=Path,required=True)
    args=parser.parse_args()
    root=args.assembled_rootfs.resolve()
    if not root.is_relative_to(BASE/'image_work'):raise ValueError('Only isolated image_work rootfs allowed')
    subprocess.run(['chroot',str(root),'/usr/bin/python3','/code/verify_release.py','--image'],check=True)
    out=BASE/'artifacts';out.mkdir(exist_ok=True)
    work=BASE/'image_work/export';work.mkdir(exist_ok=False)
    if (root/'code/native/sm80').exists():raise RuntimeError('Failed sm80 candidate must not be packaged')
    for directory in ['tmp','var/tmp','proc','dev','root/.cache']:
        path=root/directory
        if path.exists() and any(path.iterdir()):raise RuntimeError('Temporary build/test directory is not empty: '+directory)
    if (root/'etc/resolv.conf').exists() and (root/'etc/resolv.conf').read_bytes():
        raise RuntimeError('Do not export a borrowed host resolver configuration')
    # Normalized metadata enables deterministic archive generation for identical bytes.
    layer=work/'layer.tar'
    subprocess.run(['tar','--sort=name','--mtime=@1794700800','--owner=0','--group=0','--numeric-owner',
                    '-C',str(root),'-cf',str(layer),'.'],check=True)
    layer_hash=digest(layer);layer_size=layer.stat().st_size
    config=json.loads((BASE/'image_work/base-config.json').read_text())
    env=dict(x.split('=',1) for x in config['config'].get('Env',[]))
    env.update(PYTHONPATH='/opt/k-python/main:/opt/k-python/sherpa:/opt/k-python/jupyter',
               PYTHONHASHSEED='20261030',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',
               TOKENIZERS_PARALLELISM='false',CUBLAS_WORKSPACE_CONFIG=':4096:8',
               LIFEMATE_RUNTIME_ROOT='/code/runtime',LIFEMATE_NATIVE_ROOT='/code/native',
               LD_LIBRARY_PATH='/code/native/cuda13.1:/opt/k-python/main/torch/lib:/opt/k-python/main/nvidia/cuda_nvrtc/lib:/usr/local/nvidia/lib:/usr/local/nvidia/lib64')
    config.update(created=STAMP,architecture='amd64',os='linux',
                  rootfs={'type':'layers','diff_ids':['sha256:'+layer_hash]},
                  history=[{'created':STAMP,'created_by':'LifeMate explicit-input daemonless assembly',
                            'comment':'Normalized release timestamp; Docker runtime/A30/rights remain blocked'}])
    config.pop('container_config',None);config.pop('container',None);config.pop('docker_version',None)
    config['config'].update(Env=[k+'='+v for k,v in env.items()],WorkingDir='/code',Cmd=['/bin/bash','/code/predict.sh'])
    config['config'].setdefault('Labels',{}).update({'org.opencontainers.image.title':'LifeMate frozen K 48.46',
        'org.opencontainers.image.version':'k48.46-20261115-rc1','lifemate.release.status':'RELEASE_BLOCKED'})
    cfg=encoded(config);cfg_hash=hashlib.sha256(cfg).hexdigest()
    cfg_path=work/(cfg_hash+'.json');cfg_path.write_bytes(cfg)
    docker_manifest=[{'Config':cfg_path.name,'RepoTags':[TAG],'Layers':[layer_hash+'/layer.tar']}]
    (work/'manifest.json').write_bytes(encoded(docker_manifest))
    archive=out/'lifemate-k-k48.46-20261115-rc1.tar.gz'
    if archive.exists():raise FileExistsError(archive)
    # Stream Docker-save tar directly into deterministic gzip; do not create another 25-GB tar.
    with archive.open('xb') as f:
        compressor=subprocess.Popen(['gzip','-n','-1'],stdin=subprocess.PIPE,stdout=f)
        try:
            with tarfile.open(fileobj=compressor.stdin,mode='w|') as tar:
                def normalized(info):
                    info.uid=info.gid=0;info.uname=info.gname='';info.mtime=1794700800
                    return info
                tar.add(cfg_path,arcname=cfg_path.name,filter=normalized)
                tar.add(work/'manifest.json',arcname='manifest.json',filter=normalized)
                tar.add(layer,arcname=layer_hash+'/layer.tar',filter=normalized)
        finally:compressor.stdin.close()
        if compressor.wait()!=0:raise RuntimeError('gzip failed')
    # Also preserve a standards-based OCI layout, sharing the large uncompressed layer.
    oci=out/'oci';(oci/'blobs/sha256').mkdir(parents=True,exist_ok=False)
    manifest={'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json',
              'config':{'mediaType':'application/vnd.oci.image.config.v1+json','digest':'sha256:'+cfg_hash,'size':len(cfg)},
              'layers':[{'mediaType':'application/vnd.oci.image.layer.v1.tar','digest':'sha256:'+layer_hash,'size':layer_size}]}
    manifest_bytes=encoded(manifest);manifest_hash=hashlib.sha256(manifest_bytes).hexdigest()
    (oci/'blobs/sha256'/cfg_hash).write_bytes(cfg)
    (oci/'blobs/sha256'/manifest_hash).write_bytes(manifest_bytes)
    os.link(layer,oci/'blobs/sha256'/layer_hash)
    (oci/'oci-layout').write_bytes(encoded({'imageLayoutVersion':'1.0.0'}))
    (oci/'index.json').write_bytes(encoded({'schemaVersion':2,'manifests':[{
        'mediaType':manifest['mediaType'],'digest':'sha256:'+manifest_hash,'size':len(manifest_bytes),
        'platform':{'architecture':'amd64','os':'linux'},'annotations':{'org.opencontainers.image.ref.name':TAG}}]}))
    sha256=digest(archive);md5=digest(archive,'md5')
    for suffix,value in [('sha256',sha256),('md5',md5)]:
        archive.with_name(archive.name+'.'+suffix).write_text(value+'  '+archive.name+'\n')
    result={'status':'RELEASE_BLOCKED','local_tag':TAG,'archive':str(archive),'archive_bytes':archive.stat().st_size,
            'archive_md5':md5,'archive_sha256':sha256,'image_config_id':'sha256:'+cfg_hash,
            'oci_manifest_digest':'sha256:'+manifest_hash,'uncompressed_layer_diff_id':'sha256:'+layer_hash,
            'registry_digest':None,'docker_build_executed':False,'docker_load_executed':False,
            'construction':'digest-verified CUDA base; isolated chroot package install; explicit release files; flattened OCI/Docker-save assembly',
            'publication_performed':False,'normalized_release_timestamp':STAMP}
    (out/'ARTIFACTS.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
