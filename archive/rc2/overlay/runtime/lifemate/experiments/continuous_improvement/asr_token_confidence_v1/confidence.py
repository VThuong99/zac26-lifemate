"""P34 greedy RNNT with observational token-posterior telemetry."""
import time
import numpy as np,soundfile as sf
from experiments.continuous_improvement.asr_logit_ensemble_v1.ensemble import EnsembleASR,features,log_probs
class ConfidenceASR(EnsembleASR):
 def transcribe(self,path):
  if len(self.models)!=1:raise ValueError('one frozen P34 model required')
  start=time.perf_counter();wave,sr=sf.read(path,dtype='float32')
  if sr!=16000 or wave.ndim!=1 or not len(wave):raise ValueError('expected mono 16kHz')
  f=features(wave);enc,dec,join=self.models[0];out,lens=enc.run(None,{'x':f[None],'x_lens':np.array([len(f)],dtype=np.int64)});context=[0,0];prediction=dec.run(None,{'y':np.array([context],dtype=np.int64)})[0];ids=[];emissions=[]
  for frame in range(int(lens[0])):
   logits=join.run(None,{'encoder_out':out[:,frame,:],'decoder_out':prediction})[0];lp=log_probs(logits)[0];token=int(np.argmax(lp));
   if token!=0:
    probability=np.exp(lp);top=np.partition(lp,-2)[-2:];ids.append(token);emissions.append({'frame':frame,'id':token,'piece':self.sp.id_to_piece(token),'logprob':float(lp[token]),'margin':float(np.max(top)-np.min(top)),'entropy':float(-np.sum(probability*lp))});context=(context+[token])[-2:];prediction=dec.run(None,{'y':np.array([context],dtype=np.int64)})[0]
  text=self.sp.decode(ids).strip()
  if not text:raise ValueError('empty transcript')
  return {'text':text,'audio_seconds':len(wave)/sr,'seconds':time.perf_counter()-start,'tokens':ids,'emissions':emissions}
