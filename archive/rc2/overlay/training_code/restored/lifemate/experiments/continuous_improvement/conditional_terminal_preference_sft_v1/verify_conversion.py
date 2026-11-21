"""Verify F32 adapter tensor values, required Qwen3.5 permutations and Q4 compatibility."""
import hashlib,json,re,sys
from pathlib import Path
import gguf,numpy as np
from safetensors import safe_open
R=Path(__file__).resolve().parents[3];D=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
arm=sys.argv[1];assert arm in ('K','S');src=D/arm/'adapter/p23/adapter_model.safetensors';converted=D/arm/'adapter_f32.gguf';base=R/'results/p19_submission_staging_v1/models/p19.gguf';r=gguf.GGUFReader(str(converted));q=gguf.GGUFReader(str(base));gt={x.name:x for x in r.tensors};bt={x.name:x for x in q.tensors};assert len(gt)==224 and len(r.tensors)==224 and r.fields['general.architecture'].contents()=='qwen35' and q.fields['general.architecture'].contents()=='qwen35' and r.fields['adapter.type'].contents()=='lora' and r.fields['adapter.lora.alpha'].contents()==4.0
mapping={'linear_attn.in_proj_a':'ssm_alpha','linear_attn.in_proj_b':'ssm_beta','linear_attn.in_proj_qkv':'attn_qkv','linear_attn.in_proj_z':'attn_gate','linear_attn.out_proj':'ssm_out','self_attn.q_proj':'attn_q','self_attn.k_proj':'attn_k','self_attn.v_proj':'attn_v','self_attn.o_proj':'attn_output','mlp.down_proj':'ffn_down','mlp.up_proj':'ffn_up','mlp.gate_proj':'ffn_gate'}
def perm(head_dim):return np.arange(16*2*head_dim).reshape(16,2,head_dim).transpose(1,0,2).reshape(-1)
verified=[];mapped=set();transformed=0
with safe_open(str(src),framework='np') as f:
 assert len(f.keys())==224
 for key in f.keys():
  m=re.fullmatch(r'base_model\.model\.model\.language_model\.layers\.(\d+)\.(.+)\.lora_([AB])\.weight',key);assert m and m[2] in mapping,key
  module=m[2];side=m[3];target=f'blk.{m[1]}.{mapping[module]}.weight.lora_{side.lower()}';tensor=gt[target];array=f.get_tensor(key);expect=array
  if side=='B' and module in ('linear_attn.in_proj_a','linear_attn.in_proj_b'):expect=array[perm(1),:];transformed+=1
  elif side=='B' and module=='linear_attn.in_proj_z':expect=array[perm(128),:];transformed+=1
  elif side=='B' and module=='linear_attn.in_proj_qkv':expect=np.concatenate((array[:4096,:],array[4096:,:][perm(128),:]),axis=0);transformed+=1
  elif side=='A' and module=='linear_attn.out_proj':expect=array[:,perm(128)];transformed+=1
  assert str(tensor.tensor_type)=='0' and np.array_equal(expect,tensor.data) and np.isfinite(tensor.data).all(),key
  weight=target.rsplit('.lora_',1)[0];assert weight in bt,(key,weight);mapped.add(target);verified.append(key)
assert len(verified)==len(mapped)==224 and transformed==0 and set(gt)==mapped
for name in gt:
 if not name.endswith('.lora_a'):continue
 stem=name[:-7];a=gt[name];b=gt[stem+'.lora_b'];w=bt[stem];assert tuple(w.shape)==(int(a.shape[0]),int(b.shape[1])) and int(a.shape[1])==int(b.shape[0])==4,(stem,w.shape,a.shape,b.shape)
out={'verified_source_tensors':len(verified),'exact_after_required_qwen35_permutation':len(verified),'reordered_tensors':transformed,'target_modules':len(verified)//2,'rank':4,'alpha':4.0,'base_architecture':'qwen35','all_target_shapes_compatible':True,'source_sha256':sha(src),'adapter_sha256':sha(converted),'base_sha256':sha(base),'limitations':'Tensor mapping and layout verified; overlay on P19 Q4 differs numerically from BF16 training and does not establish behavioral parity.'};(D/arm/'conversion_verify.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
