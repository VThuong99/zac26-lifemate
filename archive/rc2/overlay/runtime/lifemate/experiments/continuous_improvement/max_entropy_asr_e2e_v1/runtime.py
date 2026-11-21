"""Current-audio-only acoustic alternative; preserve raw and fail closed."""
import time
from experiments.continuous_improvement.max_subword_entropy_consensus_v1.policy import preflight,decide
class Router:
 def __init__(self,state,p34,sidecars):self.state=state;self.p34=p34;self.sidecars=sidecars
 def transcribe(self,path):
  if self.state.get('arm')!='C':return self.p34.transcribe(path)
  if self.state.get('history_remaining',0)>0:self.state['history_remaining']-=1;return self.p34.transcribe(path)
  start=time.perf_counter();result=self.p34.transcribe(path);raw=result['text'];review={'raw':raw,'text':raw,'change':None,'native_parity':None,'sidecar_text':None,'ctc':None,'emissions':None,'preflight':[],'independent':None,'pho_called':False,'error':None}
  try:
   t=time.perf_counter();conf=self.sidecars.confidence.transcribe(path);review['confidence_seconds']=time.perf_counter()-t;review['sidecar_text']=conf['text'];review['emissions']=conf['emissions'];review['native_parity']=conf['text']==raw
   if review['native_parity']:
    t=time.perf_counter();ctc=self.sidecars.ctc(path);review['ctc_seconds']=time.perf_counter()-t;review['ctc']=ctc;review['preflight']=preflight(raw,ctc,conf['emissions'],True)
    if review['preflight']:
     pho=self.sidecars.pho.transcribe(path);review['pho_called']=True;review['independent']=pho['text'];review['pho_seconds']=pho['seconds'];decision=decide(raw,ctc,conf['emissions'],pho['text'],True);review.update(text=decision['text'],change=decision['change'],reason=decision['reason'])
  except (ValueError,RuntimeError,OSError,TypeError,KeyError) as e:review.update(text=raw,change=None,error=type(e).__name__+': '+str(e))
  review['review_seconds']=time.perf_counter()-start;review['sidecar_init_seconds']=getattr(self.sidecars,'init_seconds',None);review['ctc_parameters']=getattr(self.sidecars,'model_parameters',None);review['independent_parameters']=getattr(self.sidecars,'pho_parameters',None);review['sidecar_peak_reserved_bytes']=self.sidecars.torch.cuda.max_memory_reserved();result['text']=review['text'];result['seconds']=time.perf_counter()-start;result['asr_review']=review;return result
