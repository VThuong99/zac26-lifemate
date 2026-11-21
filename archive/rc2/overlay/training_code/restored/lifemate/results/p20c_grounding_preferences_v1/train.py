"""Matched P19-start SFT and anchored preference update, no environment execution."""
import argparse,copy,hashlib,json,math,os,pickle,random,time,zlib
from pathlib import Path
import numpy as np,torch,torch.nn.functional as F
from peft import PeftModel
from transformers import AutoTokenizer,Qwen3_5ForConditionalGeneration
from src.p9_data import tokenize_example
R=Path.cwd();D=R/'results/p20c_grounding_preferences_v1';BASE=R.parent/'models/qwen35-4b-p9-merged-v1';P19=R/'results/p19_real_asr_sft_train_v1/adapter'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def persist(p,x):
 with p.open('x') as f:json.dump(x,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def completion(model,ex):
 labels=ex['labels']; first=next(i for i,v in enumerate(labels) if v!=-100);assert first>0 and all(v!=-100 for v in labels[first:]);target=torch.tensor(labels[first:],device='cuda');ids=torch.tensor([ex['input_ids']],device='cuda');logits=model(input_ids=ids,use_cache=False,logits_to_keep=len(target)+1).logits[0,:-1,:].float();assert logits.shape[0]==len(target);return -F.cross_entropy(logits,target,reduction='mean')
def grammatical(model,rec,packed,vocab):
 p=rec['prompt'];c=rec['completion'];assert c[-1]==248046 and len(c)==len(rec['masks']);ids=torch.tensor([p+c],device='cuda');logits=model(input_ids=ids,use_cache=False,logits_to_keep=len(c)+1).logits[0,:-1,:].float();assert len(logits)==len(c)
 total=logits.new_zeros(())
 for i,(token,key) in enumerate(zip(c,rec['masks'])):
  mask=torch.from_numpy(np.unpackbits(np.frombuffer(packed[key],dtype=np.uint8))[:vocab].copy()).to(device='cuda',dtype=torch.bool);assert bool(mask[token]);assert logits.shape[-1]>=vocab;mask=F.pad(mask,(0,logits.shape[-1]-vocab),value=False);l=logits[i].masked_fill(~mask,float('-inf'));selected=l[token]-torch.logsumexp(l,0)
  if i==0: assert torch.allclose(selected.detach(),F.log_softmax(l.detach(),dim=0)[token],rtol=1e-5,atol=1e-5)
  total=total+selected
 return total
def setup(model,train):
 model.base_model.set_adapter(['default','p20c'] if train else ['default'],inference_mode=not train)
 for name,p in model.named_parameters():p.requires_grad_('.lora_' in name and '.p20c.' in name and train)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--arm',choices=['sft','dpo'],required=True);ap.add_argument('--fidelity-only',action='store_true');a=ap.parse_args();out=D/('fidelity' if a.fidelity_only else a.arm);out.mkdir(exist_ok=False)
 assert sha(BASE/'model.safetensors')=='f8d3ddf17460618aada6d8e8ec8bd1d6b735a207612e2b282773eecf4bde6045' and sha(P19/'adapter_model.safetensors')=='cd3926c12a82d52a0ee1f1a75aefbb284076c527bd4507a6d8a3048972fbaa20'
 cfg=json.loads((D/'frozen_inputs.json').read_text()); assert sha(D/'pairs_audited.jsonl')==cfg['pairs_sha256'] and sha(D/'preservation.json')==cfg['preservation_sha256'] and sha(D/'training_order.json')==cfg['order_sha256']
 random.seed(20261101);np.random.seed(20261101);torch.manual_seed(20261101);torch.cuda.manual_seed_all(20261101);torch.cuda.set_per_process_memory_fraction(.92,0);assert torch.cuda.is_bf16_supported()
 tok=AutoTokenizer.from_pretrained(BASE,local_files_only=True);pairs=[json.loads(l) for l in (D/'pairs_audited.jsonl').read_text().splitlines()];preserve=json.loads((D/'preservation.json').read_text());order=json.loads((D/'training_order.json').read_text())
 def token(p):return tokenize_example(tok,{'id':p['request_id'],'prefix':p.get('prefix',p.get('prior_count',0)),'messages':p['messages'],'target':json.dumps(p['chosen'],ensure_ascii=False,separators=(',',':'))},8192)
 chosen=[token(x) for x in pairs];pvals=[tokenize_example(tok,x,8192) for x in preserve]
 model=Qwen3_5ForConditionalGeneration.from_pretrained(BASE,dtype=torch.bfloat16,local_files_only=True,attn_implementation='sdpa').to('cuda');model.config.use_cache=False;model=PeftModel.from_pretrained(model,P19,is_trainable=False).eval()
 # P19 dynamic BF16 reference logits before adding any new adapter.
 probes=[]
 with torch.no_grad():
  for ix in (0,10,25,45):
   ex=chosen[ix];first=next(i for i,v in enumerate(ex['labels']) if v!=-100);ids=torch.tensor([ex['input_ids'][:first]],device='cuda');probes.append(model(input_ids=ids,use_cache=False,logits_to_keep=1).logits.detach().float().cpu())
 config=copy.deepcopy(model.peft_config['default']);config.inference_mode=False;model.add_adapter('p20c',config);setup(model,True)
 diffs=[]
 with torch.no_grad():
  for j,ix in enumerate((0,10,25,45)):
   ex=chosen[ix];first=next(i for i,v in enumerate(ex['labels']) if v!=-100);ids=torch.tensor([ex['input_ids'][:first]],device='cuda');y=model(input_ids=ids,use_cache=False,logits_to_keep=1).logits.detach().float().cpu();diffs.append(float((y-probes[j]).abs().max()))
 if max(diffs)>1e-6:raise ValueError(f'P19 starting logits changed by zero adapter: {diffs}')
 trainable=[(n,p) for n,p in model.named_parameters() if p.requires_grad];assert len(trainable)>0 and all('.p20c.' in n for n,p in trainable) and not any('visual' in n for n,p in trainable)
 # Verify reference switch gives the same dynamic P19 logits and restores trainability.
 setup(model,False)
 with torch.no_grad():
  ex=chosen[0];first=next(i for i,v in enumerate(ex['labels']) if v!=-100);ids=torch.tensor([ex['input_ids'][:first]],device='cuda');referr=float((model(input_ids=ids,use_cache=False,logits_to_keep=1).logits.detach().float().cpu()-probes[0]).abs().max())
 assert referr<=1e-6;setup(model,True)
 fidelity={'parent_sha256':sha(BASE/'model.safetensors'),'p19_adapter_sha256':sha(P19/'adapter_model.safetensors'),'bf16_dynamic_start_max_logit_diffs':diffs,'reference_switch_max_logit_diff':referr,'trainable_tensors':len(trainable),'trainable_params':sum(p.numel() for n,p in trainable),'new_B_zero':all(torch.count_nonzero(p).item()==0 for n,p in trainable if '.lora_B.' in n),'note':'BF16 P9 base plus original frozen P19 adapter is the starting and reference policy; new LoRA is additive. Q4 deployment starts from an FP32 merge and can differ.'};assert fidelity['new_B_zero'];persist(out/'fidelity.json',fidelity);print('fidelity',json.dumps(fidelity),flush=True)
 if a.fidelity_only:return
 model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False});model.train();optim=torch.optim.AdamW([p for n,p in trainable],lr=5e-6,weight_decay=0.0);optim.zero_grad(set_to_none=True);g=None
 if a.arm=='dpo':g=pickle.loads(zlib.decompress((D/'grammar_masks.pkl.z').read_bytes()));assert len(g['rows'])==len(pairs)
 start=time.monotonic();losses=[];before={n:p.detach().cpu().clone() for n,p in trainable};log=(out/'train_log.jsonl').open('x',buffering=1);eos=tok.eos_token_id
 for pos,item in enumerate(order):
  idx=item['index'];is_pair=item['kind']=='pair';ex=chosen[idx] if is_pair else pvals[idx];assert eos in [v for v in ex['labels'] if v!=-100]
  if a.arm=='dpo' and is_pair:
   row=g['rows'][idx];setup(model,False)
   with torch.no_grad():rc=grammatical(model,row['chosen'],g['masks'],g['vocab_size']);rr=grammatical(model,row['rejected'],g['masks'],g['vocab_size'])
   setup(model,True);pc=grammatical(model,row['chosen'],g['masks'],g['vocab_size']);pr=grammatical(model,row['rejected'],g['masks'],g['vocab_size']);
   if pos==next(i for i,v in enumerate(order) if v['kind']=='pair'):
    assert pos<16 and abs(float((pc-rc).detach()))<1e-5 and abs(float((pr-rr).detach()))<1e-5; print('initial grammar likelihood and frozen reference match',flush=True)
   pref=-F.logsigmoid(.1*((pc-pr)-(rc-rr)))
  else:pref=None
  lp=completion(model,ex);loss=-lp+(pref if pref is not None else 0);assert torch.isfinite(loss).item();block=min(16,len(order)-(pos//16)*16);(loss/block).backward();losses.append(float(loss.detach()))
  if (pos+1)%16==0 or pos+1==len(order):
   grads=[p.grad for n,p in trainable if p.grad is not None];assert grads and all(torch.isfinite(v).all().item() for v in grads);norm=torch.nn.utils.clip_grad_norm_([p for n,p in trainable],1.,error_if_nonfinite=True);assert float(norm)>0;optim.step();optim.zero_grad(set_to_none=True);entry={'step':pos//16+1,'examples':pos+1,'loss_mean':sum(losses[-block:])/block,'gradient_norm':float(norm),'seconds':round(time.monotonic()-start,1)};log.write(json.dumps(entry)+'\n');log.flush();os.fsync(log.fileno());print(a.arm,json.dumps(entry),flush=True)
 log.close();changes=sum(not torch.equal(before[n],p.detach().cpu()) for n,p in trainable);assert changes>0
 model.save_pretrained(out/'adapter',selected_adapters=['p20c']);apath=out/'adapter/p20c/adapter_model.safetensors';assert apath.exists()
 persist(out/'result.json',{'arm':a.arm,'examples':len(order),'pairs':len(pairs),'preservation':len(preserve),'updates':math.ceil(len(order)/16),'mean_loss':sum(losses)/len(losses),'duration_seconds':time.monotonic()-start,'changed_lora_tensors':changes,'adapter_sha256':sha(apath),'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'fidelity':fidelity,'grammar':'E16 full JSON schema grammar at temperature 1; includes EOS, not claimed equivalent to llama.cpp','frozen_inputs_sha256':sha(D/'frozen_inputs.json')});print('saved',a.arm,flush=True)
if __name__=='__main__':main()
