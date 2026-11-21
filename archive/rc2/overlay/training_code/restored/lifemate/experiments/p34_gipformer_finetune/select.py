"""Seal exactly one completed epoch using only the predeclared dev WER."""
import hashlib,json
from pathlib import Path
ROOT=Path('/workspace/GPU_benchmark/lifemate');OUT=ROOT/'results/p34_gipformer_finetune_v1'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 if (OUT/'selection.json').exists():raise FileExistsError('selection already frozen')
 epochs=[json.loads(x) for x in (OUT/'epochs.jsonl').read_text().splitlines()]
 if [x['epoch'] for x in epochs]!=[1,2]:raise ValueError('training did not complete as frozen')
 for x in epochs:
  if sha(OUT/f"epoch-{x['epoch']}.pt")!=x['checkpoint_sha256']:raise ValueError('checkpoint hash differs from training record')
 if (OUT/'e2e').exists():raise ValueError('end-to-end evaluation already exists')
 metrics=[]
 for e in (1,2):
  m=json.loads((OUT/f'dev_epoch{e}/metrics.json').read_text())
  if m['clips_scored']!=282 or m['failures']:raise ValueError('incomplete dev evaluation')
  metrics.append((m['wer'],e,m['cer']))
 wer,best,cer=min(metrics); model=(OUT/f'export_epoch{best}').resolve()
 record={'selection_rule':'minimum P34 dev corpus WER; ties earlier epoch','epoch':best,'dev_wer':wer,'dev_cer':cer,'candidate_metrics':metrics,'checkpoint':str((OUT/f'epoch-{best}.pt').resolve()),'checkpoint_sha256':sha(OUT/f'epoch-{best}.pt'),'onnx_dir':str(model),'onnx_sha256':{name:sha(model/name) for name in ('encoder.onnx','decoder.onnx','joiner.onnx','tokens.txt')},'evaluation_cohort_used_for_selection':False}
 (OUT/'selection.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
if __name__=='__main__':main()
