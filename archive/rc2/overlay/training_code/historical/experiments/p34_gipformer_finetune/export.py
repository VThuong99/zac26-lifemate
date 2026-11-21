"""Call pinned Icefall ONNX exporter with strict checkpoint loading enabled."""
import importlib.util,logging,sys
from pathlib import Path
ICE=Path('/workspace/GPU_benchmark/third_party/icefall-p12-3f848bb6')
sys.path[:0]=[str(ICE),str(ICE/'egs/librispeech/ASR'),str(ICE/'egs/librispeech/ASR/zipformer')]
script=ICE/'egs/librispeech/ASR/zipformer/export-onnx.py'
spec=importlib.util.spec_from_file_location('p34_icefall_export',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
load=module.load_checkpoint
def strict_load(filename,model,*args,**kwargs):
 kwargs['strict']=True
 return load(filename,model,*args,**kwargs)
module.load_checkpoint=strict_load
logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',level=logging.INFO)
module.main()
