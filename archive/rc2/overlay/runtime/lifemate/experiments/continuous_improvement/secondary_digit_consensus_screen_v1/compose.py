"""Expose same-clip secondary ASR/CTC digit agreement as unverified evidence."""
import copy,json
from experiments.continuous_improvement.spoken_digit_evidence_q8_v1.compose import facts as primary_facts,spans

def facts(payload,independent,ctc):
 if not isinstance(independent,dict) or not isinstance(ctc,dict):return None
 raw=primary_facts(payload) or [];out=[]
 for source in dict.fromkeys(x['source'] for x in raw):
  pri=[x for x in raw if x['source']==source];a=spans(independent.get(source));b=spans(ctc.get(source))
  if len(pri)!=1 or len(a)!=1 or len(b)!=1:continue
  if a[0]['literal_digits']!=b[0]['literal_digits'] or a[0]['literal_digits']==pri[0]['literal_digits']:continue
  out.append({'source':source,'primary_asr_digits':pri[0]['literal_digits'],'secondary_asr_words':a[0]['asr_words'],'secondary_asr_digits':a[0]['literal_digits'],'matching_recognizers':['independent_asr','p34_ctc'],'status':'unverified'})
 return out or None

def intervene(request,independent,ctc):
 q=copy.deepcopy(request)
 try:
  p=json.loads(q['messages'][1]['content']);v=facts(p,independent,ctc)
  if v is not None:p['unverified_secondary_asr_digit_sequences']=v;q['messages'][1]['content']=json.dumps(p,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return q
