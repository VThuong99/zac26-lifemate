"""Populate only a new isolated CUDA rootfs; no host filesystem export."""
import os
from pathlib import Path
import shutil
import stat
import subprocess

BASE=Path(__file__).resolve().parents[1]

def main():
    root=BASE/'image_work/rootfs'
    if not (root/'usr/local/cuda-13.2').exists():raise RuntimeError('Pinned CUDA rootfs not bootstrapped')
    for path in [root/'tmp',root/'var/tmp']:
        path.mkdir(parents=True,exist_ok=True);path.chmod(0o1777)
    (root/'dev').mkdir(exist_ok=True)
    for name,major,minor in [('null',1,3),('zero',1,5),('random',1,8),('urandom',1,9)]:
        p=root/'dev'/name
        if not p.exists():os.mknod(p,stat.S_IFCHR|0o666,os.makedev(major,minor))
        p.chmod(0o666)
    resolver=root/'etc/resolv.conf'
    previous=resolver.read_bytes() if resolver.exists() else None
    shutil.copyfile('/etc/resolv.conf',resolver)
    packages=(BASE/'source/apt-packages.install.txt').read_text().splitlines()
    try:
        subprocess.run(['chroot',str(root),'/usr/bin/env','DEBIAN_FRONTEND=noninteractive','apt-get','update'],check=True)
        subprocess.run(['chroot',str(root),'/usr/bin/env','DEBIAN_FRONTEND=noninteractive','apt-get','install','-y','--no-install-recommends',*packages],check=True)
    finally:
        if previous is None:resolver.unlink(missing_ok=True)
        else:resolver.write_bytes(previous)
    for group in ['main','sherpa','jupyter']:
        shutil.copytree(BASE/'dependencies'/group,root/'opt/k-python'/group,dirs_exist_ok=True)
    shutil.copytree(BASE/'source',root/'code',dirs_exist_ok=True)
    shutil.copytree(BASE/'model_artifacts/runtime',root/'code/runtime',dirs_exist_ok=True)
    for group in ['sm120','cuda13.1']:
        shutil.copytree(BASE/'native'/group,root/'code/native'/group,dirs_exist_ok=True)
    subprocess.run(['chroot',str(root),'/usr/bin/python3','/code/verify_release.py','--image'],check=True)
    subprocess.run(['chroot',str(root),'/usr/bin/env',
                    'PYTHONPATH=/opt/k-python/main:/opt/k-python/sherpa:/opt/k-python/jupyter',
                    'PYTHONDONTWRITEBYTECODE=1','/usr/bin/python3','-m','ipykernel','install',
                    '--prefix=/usr/local','--name=python3'],check=True)
    for directory in ['var/lib/apt/lists','var/cache/apt/archives','tmp','var/tmp','dev','root/.cache']:
        p=root/directory
        if p.exists():
            for child in p.iterdir():
                if child.is_dir() and not child.is_symlink():shutil.rmtree(child)
                else:child.unlink()
    print('Prepared isolated rootfs. Docker runtime validation still required.')

if __name__=='__main__':main()
