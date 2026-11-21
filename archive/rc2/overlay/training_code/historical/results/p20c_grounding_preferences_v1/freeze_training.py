"""Freeze one-epoch training and disjoint diagnostic inputs before model fitting."""
import hashlib,json,os,random
from pathlib import Path
R=Path.cwd(); D=R/'results/p20c_grounding_preferences_v1'; E=R/'results/e17_offline_trajectory_v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(path,obj):
 with path.open('x') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
pairs=[json.loads(s) for s in (D/'pairs_audited.jsonl').read_text().splitlines()]; audit=json.loads((D/'data_audit.json').read_text());assert sha(D/'pairs_audited.jsonl')==audit['pairs_sha256'] and audit['training_gate_passed']
groups=json.loads((R/'results/e2_gold_prefix_pilot_v1/folds_conservative.json').read_text())['groups']; by={rid:i for i,g in enumerate(groups) for rid in g};manifest=json.loads((E/'manifest.json').read_text()); protected={by[i] for i in manifest['protected_ids']+manifest['diagnostic_ids']}; occupied={x['connected_group_index'] for x in pairs};assert not protected&occupied
rows=json.loads((E/'training.json').read_text());ordered=sorted(rows,key=lambda x:hashlib.sha256(f"p20c-preserve-20261101:{x['id']}:{x['prefix']}".encode()).hexdigest()); preserve=[];used=set(occupied)|protected
# Equal call/finish preservation where possible, distinct groups and authentic reference-prefix histories.
for typ in ('call','finish'):
 for x in ordered:
  group=by[x['id']]
  if group in used or json.loads(x['target'])['type']!=typ:continue
  preserve.append(x);used.add(group)
  if sum(json.loads(t['target'])['type']==typ for t in preserve)==16:break
assert len(preserve)==32 and len({by[x['id']] for x in preserve})==32
write(D/'preservation.json',preserve)
order=[{'kind':'pair','index':i} for i in range(len(pairs))]+[{'kind':'preserve','index':i} for i in range(len(preserve))];random.Random(20261101).shuffle(order);write(D/'training_order.json',order)
diag=json.loads((E/'diagnostic.json').read_text());assert len(diag)==229 and not {by[x['id']] for x in diag}&({by[x['request_id']] for x in pairs}|{by[x['id']] for x in preserve})
write(D/'frozen_inputs.json',{'pairs_sha256':sha(D/'pairs_audited.jsonl'),'preservation_sha256':sha(D/'preservation.json'),'order_sha256':sha(D/'training_order.json'),'diagnostic_sha256':sha(E/'diagnostic.json'),'pair_count':len(pairs),'preservation_count':len(preserve),'preservation_calls':16,'preservation_finishes':16,'epochs':1,'optimizer_steps':6,'accumulation':16,'grammar':'E16 full action JSON token grammar; constrained likelihood at temperature 1.0, including end-of-turn EOS; not claimed equivalent to llama.cpp','training_positive_loss':'mean completion-token NLL including EOS, same weighting for both arms','dpo_loss':'-logsigmoid(0.1 * ((policy_chosen-policy_rejected)-(P19_chosen-P19_rejected))); pair examples only','dpo_weight':1.0,'batch_order_seed':20261101,'preservation_provenance':'E17 train-side authentic reference-prefix examples, deterministic group-disjoint sample; 16 call and 16 finish','diagnostic_group_overlap':0})
print((D/'frozen_inputs.json').read_text())
