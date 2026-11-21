"""Current-audio-only acoustic sidecars; all errors preserve native P34 text."""
import argparse,hashlib,importlib.util,json,os,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=Path(__file__).resolve().parent;P=D.parent;ICE=R.parent/'third_party/icefall-p12-3f848bb6';MODEL=R.parent/'models/gipformer15-68m-dd9227d-p12';sys.path.append(str(R.parent/'.venvs/lifemate-p12-gipformer/lib/python3.12/site-packages'))
from experiments.continuous_improvement.ctc_entropy_corroboration_v1.policy import decide,EXTRA_PROTECTED
from experiments.continuous_improvement.asr_entropy_substitution_v1.policy import propose
from experiments.continuous_improvement.asr_token_confidence_v1.confidence import ConfidenceASR
from src.p11_phowhisper import PhoWhisperASR,PHOWHISPER_WEIGHT_SHA256,read_wav
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
class Sidecars:
 def __init__(self):
  started=time.perf_counter();import torch,k2,kaldifeat,sentencepiece as spm
  self.torch=torch;self.sp=spm.SentencePieceProcessor(model_file=str(MODEL/'bpe.model'));sel=json.loads((R/'results/p34_gipformer_finetune_v1/selection.json').read_text());checkpoint=R/sel['checkpoint'];assert sha(checkpoint)==sel['checkpoint_sha256'];onnx=R/'results/p34_gipformer_finetune_v1/export_epoch2';assert all(sha(onnx/k)==v for k,v in sel['onnx_sha256'].items());self.confidence=ConfidenceASR([onnx],MODEL/'bpe.model');os.environ['GIT_DIR']=str(ICE/'.git');paths=[str(ICE),str(ICE/'egs/librispeech/ASR'),str(ICE/'egs/librispeech/ASR/zipformer')];sys.path[:0]=paths
  try:
   spec=importlib.util.spec_from_file_location('lifemate_icefall_p34_train',ICE/'egs/librispeech/ASR/zipformer/train.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  finally:
   for path in paths:
    if path in sys.path:sys.path.remove(path)
  params=module.get_params();parser=argparse.ArgumentParser();module.add_model_arguments(parser);params.update(vars(parser.parse_args([])));sym=k2.SymbolTable.from_file(str(MODEL/'tokens.txt'));params.blank_id=sym['<blk>'];params.unk_id=sym['<unk>'];params.vocab_size=sum(not s.startswith('#') for s in sym.symbols);params.context_size=2;params.use_ctc=True;assert (params.blank_id,params.unk_id,params.vocab_size)==(0,2,2000);model=module.get_model(params);state=torch.load(checkpoint,map_location='cpu',weights_only=False)['model'];model.load_state_dict(state,strict=True);del state;model.to('cuda').eval();module.set_batch_count(model,100000);self.model=model;self.blank=params.blank_id
  opt=kaldifeat.FbankOptions();opt.device=torch.device('cuda');opt.frame_opts.dither=0;opt.frame_opts.snip_edges=False;opt.frame_opts.samp_freq=16000;opt.mel_opts.num_bins=80;opt.mel_opts.high_freq=-400;self.fbank=kaldifeat.Fbank(opt);self.pho=PhoWhisperASR(R.parent/'models/phowhisper-medium-55a7e3e',device='cuda',num_threads=4);self.init_seconds=time.perf_counter()-started;self.model_parameters=sum(p.numel() for p in self.model.parameters());self.pho_parameters=self.pho.resource_metrics()['parameters_deduplicated'];self.ctc_checkpoint_sha256=sel['checkpoint_sha256'];self.pho_sha256=PHOWHISPER_WEIGHT_SHA256
 def ctc(self,path):
  samples,_=read_wav(path);torch=self.torch
  with torch.inference_mode():
   feats=self.fbank([torch.from_numpy(samples).to('cuda')])[0].unsqueeze(0);lens=torch.tensor([feats.shape[1]],dtype=torch.int64,device='cuda');enc,outlen=self.model.forward_encoder(feats,lens);seq=self.model.ctc_output(enc)[0,:int(outlen[0])].argmax(-1).tolist();ids=[];prev=None
   for z in seq:
    if z!=prev and z!=self.blank:ids.append(z)
    prev=z
  torch.cuda.synchronize();return self.sp.decode(ids)
 def review(self,path,raw):
  started=time.perf_counter();result={'raw':raw,'text':raw,'change':None,'native_parity':None,'ctc':None,'independent':None,'error':None,'pho_called':False}
  try:
   side=self.confidence.transcribe(path);result['sidecar_text']=side['text'];result['native_parity']=side['text']==raw;result['confidence_seconds']=side['seconds'];result['emissions']=side['emissions']
   if not result['native_parity']:return result
   tick=time.perf_counter();ctc=self.ctc(path);result['ctc']=ctc;result['ctc_seconds']=time.perf_counter()-tick;pre=propose(raw,ctc,side['emissions']);change=pre['change']
   if not change or change['original'].casefold() in EXTRA_PROTECTED or change['replacement'].casefold() in EXTRA_PROTECTED:return result
   pho=self.pho.transcribe(path);result['pho_called']=True;result['independent']=pho['text'];result['pho_seconds']=pho['seconds'];selected=decide(raw,ctc,side['emissions'],pho['text'],True);result.update(text=selected['text'],change=selected['change'],reason=selected['reason'])
  except (ValueError,RuntimeError,OSError,TypeError,KeyError) as e:result.update(text=raw,change=None,error=type(e).__name__+': '+str(e))
  finally:result['review_seconds']=time.perf_counter()-started
  return result
class Router:
 def __init__(self,state,p34,sidecars):self.state=state;self.p34=p34;self.sidecars=sidecars
 def transcribe(self,path):
  if self.state.get('arm')!='C':return self.p34.transcribe(path)
  if self.state.get('history_remaining',0)>0:self.state['history_remaining']-=1;return self.p34.transcribe(path)
  start=time.perf_counter();result=self.p34.transcribe(path);review=self.sidecars.review(path,result['text']);result['text']=review['text'];result['seconds']=time.perf_counter()-start;result['asr_review']=review;return result
