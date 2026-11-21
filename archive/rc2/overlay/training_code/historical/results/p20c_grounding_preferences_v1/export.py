"""Merge P19 and the new adapter in FP32, then export the fixed Q4_K_M arm."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
import torch
from peft import PeftModel
from transformers import AutoTokenizer,Qwen3_5ForConditionalGeneration
R=Path.cwd();D=R/'results/p20c_grounding_preferences_v1';BASE=R.parent/'models/qwen35-4b-p9-merged-v1';P19=R/'results/p19_real_asr_sft_train_v1/adapter';LL=R.parent/'third_party/llama.cpp-p9-8ca4060b'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def th(x):return hashlib.sha256(x.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--arm',choices=['sft','dpo'],required=True);a=ap.parse_args();out=D/a.arm;res=json.loads((out/'result.json').read_text());adapter=out/'adapter/p20c';assert sha(adapter/'adapter_model.safetensors')==res['adapter_sha256'];assert sha(P19/'adapter_model.safetensors')=='cd3926c12a82d52a0ee1f1a75aefbb284076c527bd4507a6d8a3048972fbaa20';start=time.monotonic();modeldir=out/'merged_fp32';assert not modeldir.exists()
 tok=AutoTokenizer.from_pretrained(BASE,local_files_only=True);model=Qwen3_5ForConditionalGeneration.from_pretrained(BASE,dtype=torch.float32,local_files_only=True,attn_implementation='sdpa').to('cuda');model=PeftModel.from_pretrained(model,P19,is_trainable=False);model.load_adapter(adapter,adapter_name='p20c',is_trainable=False);model.base_model.set_adapter(['default','p20c'],inference_mode=True);model.eval()
 ex=json.loads((D/'preservation.json').read_text())[0];ids=tok.apply_chat_template(ex['messages'],tokenize=True,return_dict=False,add_generation_prompt=True,enable_thinking=False);ids=torch.tensor([ids],device='cuda')
 with torch.no_grad():
  logits=model(input_ids=ids,use_cache=False,logits_to_keep=1).logits.float().cpu();expected=[]
  for name,layer in model.named_modules():
   if not hasattr(layer,'lora_A') or 'default' not in layer.lora_A:continue
   assert 'p20c' in layer.lora_A;w=layer.get_base_layer().weight;delta1=layer.get_delta_weight('default');delta2=layer.get_delta_weight('p20c');assert w.dtype==torch.float32 and torch.isfinite(delta1).all() and torch.isfinite(delta2).all();expected.append((name,layer.get_base_layer(),th((w.detach()+delta1)+delta2)))
  assert len(expected)==248;merged=model.merge_and_unload(safe_merge=True,adapter_names=['default','p20c']).eval();mismatch=[name for name,layer,h in expected if th(layer.weight)!=h];assert not mismatch;logits2=merged(input_ids=ids,use_cache=False,logits_to_keep=1).logits.float().cpu();err=float((logits-logits2).abs().max());assert err<0.01,(err,'FP32 merge exceeds tolerance');assert logits.argmax()==logits2.argmax();merged.save_pretrained(modeldir,safe_serialization=True,max_shard_size='5GB');tok.save_pretrained(modeldir)
 del model,merged;torch.cuda.empty_cache();env=os.environ.copy();env.update({'PYTHONPATH':str(R)+':'+str(R/'results/e4_model_preflight_v1/converter_deps'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PYTHONDONTWRITEBYTECODE':'1'});gguf=out/'model_f32.gguf';q4=out/'model_q4.gguf';subprocess.run([str(R.parent/'.venvs/lifemate-p9/bin/python'),str(LL/'convert_hf_to_gguf.py'),str(modeldir),'--outfile',str(gguf),'--outtype','f32','--no-nextn'],check=True,env=env);subprocess.run([str(LL/'build-cpu/bin/llama-quantize'),str(gguf),str(q4),'Q4_K_M','8'],check=True,env=env)
 info={'arm':a.arm,'p19_adapter_sha256':sha(P19/'adapter_model.safetensors'),'new_adapter_sha256':res['adapter_sha256'],'checked_merge_modules':len(expected),'merge_hash_mismatches':len(mismatch),'dynamic_vs_merged_fp32_max_abs_logits':err,'dynamic_vs_merged_argmax_equal':True,'q4_sha256':sha(q4),'seconds':time.monotonic()-start,'note':'One prompt checks FP32 merge logits; Q4 can change behavior, which is measured separately.'}
 with (out/'export.json').open('x') as f:json.dump(info,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 print(json.dumps(info),flush=True)
if __name__=='__main__':main()
