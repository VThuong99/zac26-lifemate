"""Use the already loaded frozen CTC model for a hash-bound user clip."""
import hashlib
from pathlib import Path
class SharedCTC:
 def __init__(self,sidecars,root,split,resolver):self.sidecars=sidecars;self.root=Path(root);self.split=split;self.resolver=resolver
 def decode(self,audio,audio_sha256):
  path=Path(self.resolver(self.root,self.split,audio)).resolve();allowed=(self.root/self.split/'audio').resolve()
  if not path.is_relative_to(allowed) or not path.is_file():raise ValueError('audio path outside authorized split')
  h=hashlib.sha256()
  with path.open('rb') as f:
   for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
  if h.hexdigest()!=audio_sha256:raise ValueError('audio hash mismatch')
  value=self.sidecars.ctc(path)
  if not isinstance(value,str):raise TypeError('invalid CTC output')
  return {'audio':audio,'audio_sha256':audio_sha256,'ctc':value}
