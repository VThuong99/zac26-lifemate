"""Matched P19-initialized authentic LoRA SFT; only current action contributes loss."""
import argparse,copy,hashlib,json,math,os,pickle,random,time,shutil
from pathlib import Path
import numpy as np,torch
from peft import PeftModel
from transformers import Qwen3_5ForConditionalGeneration
from src.p9_training import completion_loss
from experiments.continuous_improvement.conditional_terminal_preference_sft_v1.branch_preference import branch_preference
R=Path(__file__).resolve().parents[3];D=Path(__file__).resolve().parent;BASE=R.parent/'models/qwen35-4b-p9-merged-v1';P19=R/'results/p19_real_asr_sft_train_v1/adapter'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def dump(p,obj):
 with p.open('x') as f:json.dump(obj,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--arm',choices=['S','K'],required=True);ap.add_argument('--resume',type=Path);a=ap.parse_args();out=D/a.arm
 cfg=json.loads((D/'recipe.json').read_text());assert shutil.disk_usage(R).free>=10000000000;assert sha(D/'training_inputs.pkl')==cfg['training_inputs_sha256'];assert sha(BASE/'model.safetensors')==cfg['base_sha256']=='f8d3ddf17460618aada6d8e8ec8bd1d6b735a207612e2b282773eecf4bde6045';assert sha(P19/'adapter_model.safetensors')==cfg['p19_adapter_sha256']=='cd3926c12a82d52a0ee1f1a75aefbb284076c527bd4507a6d8a3048972fbaa20'
 if not a.resume:out.mkdir(exist_ok=False)
 data=pickle.loads((D/'training_inputs.pkl').read_bytes());examples=data['examples'];order=data['schedules']['B']['indices'];weights=[1.0]*len(order);assert len(order)==len(weights)==cfg['presentations_per_arm']
 assert sha(D/'pairs.pkl')==cfg['pairs_sha256'];pairs=pickle.loads((D/'pairs.pkl').read_bytes())['pairs'];assert [x['id'] for x in pairs]==cfg['pair_ids'] and cfg['preference_beta']==1.0 and cfg['preference_weight']==0.1
 seed=cfg['seed'];random.seed(seed);np.random.seed(seed);torch.manual_seed(seed);torch.cuda.manual_seed_all(seed);torch.use_deterministic_algorithms(True);assert torch.cuda.is_bf16_supported();torch.cuda.set_per_process_memory_fraction(.92,0)
 for ex in examples:
  first=next(i for i,v in enumerate(ex['labels']) if v!=-100);assert first>0 and all(x==-100 for x in ex['labels'][:first]) and ex['labels'][first:]==ex['input_ids'][first:]
 model=Qwen3_5ForConditionalGeneration.from_pretrained(BASE,dtype=torch.bfloat16,local_files_only=True,attn_implementation='sdpa').to('cuda');model.config.use_cache=False;model=PeftModel.from_pretrained(model,P19,is_trainable=False).eval()
 ix=order[0];ex=examples[ix];first=next(i for i,x in enumerate(ex['labels']) if x!=-100);ids=torch.tensor([ex['input_ids'][:first]],device='cuda')
 with torch.no_grad():before_logits=model(input_ids=ids,use_cache=False,logits_to_keep=1).logits.detach().float().cpu()
 if a.resume:model.load_adapter(a.resume/'adapter/p23',adapter_name='p23',is_trainable=True)
 else:
  from peft import LoraConfig
  config=LoraConfig(r=4,lora_alpha=4,lora_dropout=0.0,target_modules=cfg['target_modules'],bias='none',inference_mode=False);model.add_adapter('p23',config)
 model.base_model.set_adapter(['default','p23'],inference_mode=False)
 for n,p in model.named_parameters():p.requires_grad_('.lora_' in n and '.p23.' in n)
 trainable=[(n,p) for n,p in model.named_parameters() if p.requires_grad];assert len(trainable)==224 and all('.language_model.' in n and 'visual' not in n for n,p in trainable);assert all(any('.'+part+'.' in n for n,p in trainable) for part in cfg['target_modules'])
 if not a.resume:
  with torch.no_grad():after_logits=model(input_ids=ids,use_cache=False,logits_to_keep=1).logits.detach().float().cpu()
  diff=float((before_logits-after_logits).abs().max());assert diff==0 and all(torch.count_nonzero(p).item()==0 for n,p in trainable if '.lora_B.' in n)
  dump(out/'initialization.json',{'P19_base_sha256':cfg['base_sha256'],'P19_adapter_sha256':cfg['p19_adapter_sha256'],'zero_added_adapter_max_logit_difference':diff,'trainable_tensors':len(trainable),'trainable_parameters':sum(p.numel() for n,p in trainable),'recipe_sha256':sha(D/'recipe.json')})
 model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False});model.train();optim=torch.optim.AdamW([p for n,p in trainable],lr=cfg['learning_rate'],weight_decay=0);pos0=0
 if a.resume:
  saved=torch.load(a.resume/'state.pt',map_location='cpu',weights_only=False);assert saved['arm']==a.arm and saved['recipe_sha256']==sha(D/'recipe.json');optim.load_state_dict(saved['optimizer']);pos0=saved['position'];random.setstate(saved['python_rng']);np.random.set_state(saved['numpy_rng']);torch.set_rng_state(saved['torch_rng']);torch.cuda.set_rng_state_all(saved['cuda_rng'])
 optim.zero_grad(set_to_none=True);torch.cuda.reset_peak_memory_stats();started=time.monotonic();losses=[];seenin=0;seentarget=0
 log=(out/'training.jsonl').open('a' if a.resume else 'x',buffering=1)
 for pos in range(pos0,len(order)):
  ex=examples[order[pos]];block=min(8,len(order)-(pos//8)*8);loss=completion_loss(model,ex,'cuda');assert torch.isfinite(loss).item();(loss*weights[pos]/block).backward();losses.append(float(loss.detach()));seenin+=ex['input_tokens'];seentarget+=ex['supervised_tokens']
  if (pos+1)%8==0 or pos+1==len(order):
   pair=pairs[(pos//8)%len(pairs)];preference=None
   if a.arm=='K':
    ids=torch.tensor([pair['input_ids']],dtype=torch.long,device='cuda');assert len(pair['input_ids'])==pair['prefix_tokens']+pair['divergence_index'];logits=model(input_ids=ids,use_cache=False,logits_to_keep=1).logits[0,-1];preference=branch_preference(logits,pair['chosen_id'],pair['rejected_id'],pair['reference_margin'],cfg['preference_beta']);assert torch.isfinite(preference).item();(cfg['preference_weight']*preference).backward()
   grads=[p.grad for n,p in trainable if p.grad is not None];assert grads and all(torch.isfinite(g).all().item() for g in grads);norm=torch.nn.utils.clip_grad_norm_([p for n,p in trainable],1.,error_if_nonfinite=True);assert float(norm)>0;optim.step();optim.zero_grad(set_to_none=True);step=math.ceil((pos+1)/8)
   if step==1: assert any(torch.count_nonzero(p).item()>0 for n,p in trainable if '.lora_B.' in n), 'no LoRA update after first optimizer step'
   rec={'step':step,'presentations':pos+1,'loss_mean':sum(losses[-block:])/block,'preference_pair':pair['id'],'branch_preference_loss':float(preference.detach()) if preference is not None else None,'reference_margin':pair['reference_margin'],'gradient_norm':float(norm),'elapsed_seconds_this_run':time.monotonic()-started,'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved()};log.write(json.dumps(rec)+'\n');log.flush();os.fsync(log.fileno());print(a.arm,json.dumps(rec),flush=True)
   if step%4==0:
    if shutil.disk_usage(R).free<10000000000:raise RuntimeError('disk reserve below 10 GB; last checkpoint retained')
    cp=out/f'checkpoint-{step}';cp.mkdir(exist_ok=False);model.save_pretrained(cp/'adapter',selected_adapters=['p23']);torch.save({'arm':a.arm,'recipe_sha256':sha(D/'recipe.json'),'position':pos+1,'optimizer':optim.state_dict(),'python_rng':random.getstate(),'numpy_rng':np.random.get_state(),'torch_rng':torch.get_rng_state(),'cuda_rng':torch.cuda.get_rng_state_all()},cp/'state.pt')
 log.close();model.save_pretrained(out/'adapter',selected_adapters=['p23']);path=out/'adapter/p23/adapter_model.safetensors'
 from safetensors.torch import load_file
 weights_saved=load_file(str(path));changed=sum(int(torch.count_nonzero(v).item()>0) for n,v in weights_saved.items() if 'lora_B' in n);assert changed>0
 dump(out/'result.json',{'completed':True,'arm':a.arm,'recipe_sha256':sha(D/'recipe.json'),'presentations':len(order),'optimizer_steps':math.ceil(len(order)/8),'realized_input_tokens':seenin,'realized_supervised_tokens':seentarget,'changed_lora_B_tensors':changed,'adapter_sha256':sha(path),'duration_seconds_this_run':time.monotonic()-started,'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),'resume_from':str(a.resume) if a.resume else None});print('completed',a.arm,flush=True)
if __name__=='__main__':main()
