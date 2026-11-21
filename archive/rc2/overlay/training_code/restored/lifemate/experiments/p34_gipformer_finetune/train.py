"""Bounded P34 native Icefall adaptation; original checkpoint stays immutable."""
import argparse,hashlib,json,os,random,subprocess,sys,time
from pathlib import Path
import numpy as np
import torch,k2,kaldifeat,sentencepiece as spm
ROOT=Path('/workspace/GPU_benchmark/lifemate')
OUT=ROOT/'results/p34_gipformer_finetune_v1'
MODEL=ROOT.parent/'models/gipformer15-68m-dd9227d-p12'
ICE=ROOT.parent/'third_party/icefall-p12-3f848bb6'
sys.path[:0]=[str(ICE),str(ICE/'egs/librispeech/ASR'),str(ICE/'egs/librispeech/ASR/zipformer')]
os.environ['GIT_DIR']=str(ICE/'.git')
from train import add_model_arguments,get_model,get_params,set_batch_count
from src.p11_phowhisper import read_wav
from src.p10_audio import audio_path

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for x in iter(lambda:f.read(4*1024*1024),b''):h.update(x)
 return h.hexdigest()
def read(p):return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
def atomic_save(value,p):
 tmp=p.with_suffix('.tmp');torch.save(value,tmp);os.replace(tmp,p)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--smoke',action='store_true');args=ap.parse_args()
 cfg=json.loads((ROOT/'experiments/p34_gipformer_finetune/protocol.json').read_text());
 for p,expected in [(ROOT/cfg['train_manifest'],cfg['train_sha256']),(ROOT/cfg['dev_manifest'],cfg['dev_sha256']),(MODEL/'model.pt',cfg['native_checkpoint_sha256']),(MODEL/'bpe.model',cfg['bpe_sha256']),(MODEL/'tokens.txt',cfg['tokens_sha256'])]:
  if sha(p)!=expected:raise ValueError(f'fingerprint mismatch {p}')
 if subprocess.check_output(['git','-C',str(ICE),'rev-parse','HEAD'],text=True).strip()!=cfg['icefall_revision'] or subprocess.check_output(['git','-C',str(ICE),'status','--porcelain','--untracked-files=no'],text=True).strip():raise ValueError('Icefall checkout differs from pinned clean revision')
 train=read(ROOT/cfg['train_manifest']);dev=read(ROOT/cfg['dev_manifest'])
 if (len(train),len(dev))!=(2475,282) or {x['request_id'] for x in train}&{x['request_id'] for x in dev}:raise ValueError('manifest identity or request separation failed')
 sp=spm.SentencePieceProcessor(model_file=str(MODEL/'bpe.model'))
 for r in train+dev:
  ids=sp.encode(r['training_text'],out_type=int)
  if ids!=r['training_token_ids'] or not ids or sp.unk_id() in ids or 0 in ids or sp.decode(ids)!=r['training_text'] or r['status']!='eligible':raise ValueError('bad target')
 random.seed(cfg['seed']);np.random.seed(cfg['seed']);torch.manual_seed(cfg['seed']);torch.cuda.manual_seed_all(cfg['seed']);torch.set_num_threads(4)
 if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
 params=get_params();parser=argparse.ArgumentParser();add_model_arguments(parser);params.update(vars(parser.parse_args([])));sym=k2.SymbolTable.from_file(str(MODEL/'tokens.txt'));params.blank_id=sym['<blk>'];params.unk_id=sym['<unk>'];params.vocab_size=sum(not s.startswith('#') for s in sym.symbols);params.context_size=2;params.use_ctc=True
 if (params.blank_id,params.unk_id,params.vocab_size)!=(0,2,2000):raise ValueError('token config mismatch')
 model=get_model(params);state=torch.load(MODEL/'model.pt',map_location='cpu',weights_only=True)['model'];result=model.load_state_dict(state,strict=True)
 if result.missing_keys or result.unexpected_keys:raise ValueError('partial checkpoint load')
 baseline=state['joiner.output_linear.weight'].clone();del state;model.to('cuda');set_batch_count(model,100000)
 opt=kaldifeat.FbankOptions();opt.device=torch.device('cuda');opt.frame_opts.dither=0;opt.frame_opts.snip_edges=False;opt.frame_opts.samp_freq=16000;opt.mel_opts.num_bins=80;opt.mel_opts.high_freq=-400;fbank=kaldifeat.Fbank(opt)
 optimizer=torch.optim.AdamW(model.parameters(),lr=1e-5,weight_decay=0.0)
 def loss_one(r):
  samples,_=read_wav(audio_path(ROOT,'train',r['audio']));features=fbank([torch.from_numpy(samples).to('cuda')])[0].unsqueeze(0);lens=torch.tensor([features.shape[1]],dtype=torch.int64,device='cuda');targets=k2.RaggedTensor([r['training_token_ids']]);simple,pruned,ctc,_,_=model(x=features,x_lens=lens,y=targets,prune_range=5,am_scale=0.,lm_scale=.25);loss=.75*simple+.55*pruned+.2*ctc
  if not torch.isfinite(loss):raise RuntimeError('nonfinite loss '+r['clip_id'])
  return loss
 def backward(loss):
  loss.backward()
  # A non-finite entry makes the aggregate norm non-finite; the check also
  # avoids synchronizing once per tensor on every step.
  norm=torch.nn.utils.clip_grad_norm_(model.parameters(),5.0,error_if_nonfinite=True)
  if not torch.isfinite(norm):raise RuntimeError('nonfinite grad norm')
  return float(norm)
 def validate():
  model.eval();total=0.
  with torch.no_grad():
   for r in dev:total+=float(loss_one(r))
  return total/len(dev)
 if args.smoke:
  model.train();optimizer.zero_grad(set_to_none=True);loss=loss_one(train[0]);grad=backward(loss);changed=torch.equal(baseline,model.joiner.output_linear.weight.detach().cpu());report={'loss':float(loss.detach()),'gradient_norm':grad,'all_nonfinite_gradients':0,'checkpoint_strict':True,'pretrained_parameters':sum(p.numel() for p in model.parameters()),'smoke_optimizer_step':False,'weights_unchanged':changed,'clip_id':train[0]['clip_id'],'pytorch':torch.__version__,'gpu':torch.cuda.get_device_name(0)};(OUT/'training_smoke.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True);return
 if (OUT/'epoch-1.pt').exists():raise FileExistsError('existing run; refusing restart')
 torch.cuda.reset_peak_memory_stats();base_dev=validate();print(json.dumps({'baseline_dev_loss':base_dev}),flush=True)
 with (OUT/'epochs.jsonl').open('x',buffering=1) as log:
  for epoch in (1,2):
   t=time.monotonic();order=list(range(len(train)));random.shuffle(order);model.train();running=0.
   for step,idx in enumerate(order,1):
    r=train[idx];optimizer.zero_grad(set_to_none=True);loss=loss_one(r);grad=backward(loss);optimizer.step();running+=float(loss.detach())
    if step%100==0:print(json.dumps({'epoch':epoch,'step':step,'total':len(train),'running_loss':running/step,'grad_norm':grad,'elapsed':time.monotonic()-t}),flush=True)
   dev_loss=validate();torch.cuda.synchronize();seconds=time.monotonic()-t;changed=not torch.equal(baseline,model.joiner.output_linear.weight.detach().cpu())
   if not changed:raise RuntimeError('model did not update')
   checkpoint={'model':model.state_dict(),'optimizer':optimizer.state_dict(),'epoch':epoch,'python_rng':random.getstate(),'numpy_rng':np.random.get_state(),'torch_rng':torch.get_rng_state(),'cuda_rng':torch.cuda.get_rng_state_all(),'protocol_sha256':sha(ROOT/'experiments/p34_gipformer_finetune/protocol.json'),'baseline_sha256':cfg['native_checkpoint_sha256']}
   atomic_save(checkpoint,OUT/f'epoch-{epoch}.pt');result={'epoch':epoch,'train_loss_mean_per_clip':running/len(train),'dev_loss_mean_per_clip':dev_loss,'baseline_dev_loss':base_dev,'seconds':seconds,'gpu_peak_allocated_bytes':torch.cuda.max_memory_allocated(),'gpu_peak_reserved_bytes':torch.cuda.max_memory_reserved(),'weight_changed':changed,'checkpoint_sha256':sha(OUT/f'epoch-{epoch}.pt')};log.write(json.dumps(result)+'\n');log.flush();os.fsync(log.fileno());print(json.dumps(result),flush=True)
if __name__=='__main__':main()
