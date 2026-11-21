"""Merge an existing P9 adapter offline and compare a synthetic greedy generation."""
import argparse,json,sys
from pathlib import Path
import torch
from peft import PeftModel
from transformers import AutoTokenizer,Qwen3_5ForConditionalGeneration
from scripts.train_p9 import PINNED_SHARDS,digest

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--model',type=Path,required=True);p.add_argument('--adapter',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 for name,expected in PINNED_SHARDS.items():
  if digest(a.model/name)!=expected:raise ValueError(f'base weight hash mismatch: {name}')
 a.output.mkdir(parents=True,exist_ok=False)
 tok=AutoTokenizer.from_pretrained(a.model,local_files_only=True)
 model=Qwen3_5ForConditionalGeneration.from_pretrained(a.model,dtype=torch.bfloat16,local_files_only=True,attn_implementation='sdpa').to('cuda')
 model=PeftModel.from_pretrained(model,a.adapter).eval()
 messages=[{'role':'system','content':'You are a helpful Vietnamese assistant.'},{'role':'user','content':'Xin chào.'}]
 text=tok.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
 inputs=tok(text,return_tensors='pt').to('cuda')
 def generate():
  with torch.inference_mode():return model.generate(**inputs,max_new_tokens=32,do_sample=False).tolist()
 before=generate();model=model.merge_and_unload().eval();after=generate()
 if before!=after:raise RuntimeError('Merged model changed the synthetic greedy token sequence')
 model.save_pretrained(a.output,safe_serialization=True);tok.save_pretrained(a.output)
 check=AutoTokenizer.from_pretrained(a.output,local_files_only=True)
 if check.get_vocab()!=tok.get_vocab() or check.chat_template!=tok.chat_template or check.all_special_ids!=tok.all_special_ids:raise RuntimeError('Export tokenizer differs')
 record={'base_revision':'851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a','base_shards':PINNED_SHARDS,'adapter_path':str(a.adapter.resolve()),'adapter_sha256':digest(a.adapter/'adapter_model.safetensors'),'synthetic_messages':messages,'generated_tokens_sha256':__import__('hashlib').sha256(json.dumps(before).encode()).hexdigest(),'synthetic_tokens_identical':True,'tokenizer_and_template_match':True,'python':sys.version}
 (a.output/'p19_export_verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n');print(json.dumps(record,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
