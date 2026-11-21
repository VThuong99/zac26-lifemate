"""Score genuine P34 dev WAVs with unchanged P19 Sherpa greedy decoder."""
import argparse,json,sys,time,hashlib
from pathlib import Path
from collections import Counter
ROOT=Path('/workspace/GPU_benchmark/lifemate');sys.path.insert(0,str(ROOT))
from src.p10_audio import GipformerASR,audio_path
from src.p10_metrics import analyze

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--model',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
 manifest=ROOT/'results/p34_tokenizer_fix_v4/dev.jsonl';assert hashlib.sha256(manifest.read_bytes()).hexdigest()=='fba7f3483c9037f145d4f0ff28be8113429de5a383ee528d3518a7676690f60c'
 rows=[json.loads(x) for x in manifest.read_text().splitlines()];assert len(rows)==282
 decoder=GipformerASR(args.model,4);args.output.mkdir(parents=True,exist_ok=False);start=time.monotonic();wc=Counter();cc=Counter();failures=[]
 with (args.output/'transcripts.jsonl').open('x',buffering=1) as f:
  for index,r in enumerate(rows):
   try:
    result=decoder.transcribe(audio_path(ROOT,'train',r['audio']));hyp=result['text'];score=analyze(r['training_text'],hyp);wc.update(score['word_edits']);cc.update(score['character_edits']);f.write(json.dumps({'clip_id':r['clip_id'],'audio':r['audio'],'hypothesis':hyp,'reference':r['training_text'],'timing':result['seconds'],'word_edits':score['word_edits'],'character_edits':score['character_edits']},ensure_ascii=False)+'\n')
   except Exception as e:failures.append({'clip_id':r['clip_id'],'error':f'{type(e).__name__}: {e}'});break
   if (index+1)%50==0:print(json.dumps({'completed':index+1,'total':len(rows)}),flush=True)
 report={'clips_expected':len(rows),'clips_scored':sum(1 for _ in (args.output/'transcripts.jsonl').open()),'failures':failures,'wer':wc['errors']/wc['reference_units'] if wc['reference_units'] else None,'cer':cc['errors']/cc['reference_units'] if cc['reference_units'] else None,'word_edits':dict(wc),'character_edits':dict(cc),'normalization':'NFC, casefold, unicode alphanumeric words; ignore punctuation and whitespace for CER; no number expansion','elapsed_seconds':time.monotonic()-start,'model':str(args.model)};(args.output/'metrics.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
 if failures:raise RuntimeError('dev decoding failure')
if __name__=='__main__':main()
