"""Aligned equal-probability RNNT greedy ensemble over a shared token prefix."""
import time
from pathlib import Path
import kaldi_native_fbank as knf,numpy as np,onnxruntime as ort,sentencepiece as spm,soundfile as sf

def features(wave):
 o=knf.FbankOptions();o.frame_opts.dither=0;o.frame_opts.snip_edges=False;o.mel_opts.num_bins=80;o.mel_opts.high_freq=-400;f=knf.OnlineFbank(o);f.accept_waveform(16000,wave.tolist());f.input_finished();return np.stack([f.get_frame(i) for i in range(f.num_frames_ready)]).astype(np.float32)
def log_probs(logits):
 m=np.max(logits,axis=-1,keepdims=True);a=logits-m;return a-np.log(np.sum(np.exp(a),axis=-1,keepdims=True))
def consensus_token(logits):
 if not logits:raise ValueError('no model logits')
 distributions=[log_probs(x) for x in logits];combined=np.logaddexp.reduce(distributions)-np.log(len(distributions));return int(np.argmax(combined,axis=-1)[0])
class EnsembleASR:
 def __init__(self,models,bpe,threads=4):
  if not models:raise ValueError('no models')
  so=ort.SessionOptions();so.intra_op_num_threads=threads;so.inter_op_num_threads=1;self.models=[];provider=['CPUExecutionProvider'];tokens=None
  for path in map(Path,models):
   current=(path/'tokens.txt').read_bytes()
   if tokens is not None and tokens!=current:raise ValueError('token map mismatch')
   tokens=current;self.models.append(tuple(ort.InferenceSession(str(path/(n+'.onnx')),so,providers=provider) for n in ('encoder','decoder','joiner')))
  self.sp=spm.SentencePieceProcessor(model_file=str(bpe));table={int(x.rsplit(' ',1)[1]):x.rsplit(' ',1)[0] for x in tokens.decode().splitlines()}
  if len(table)!=self.sp.get_piece_size() or any(self.sp.id_to_piece(i)!=table.get(i) for i in range(self.sp.get_piece_size())):raise ValueError('BPE mismatch')
 def transcribe(self,path):
  start=time.perf_counter();wave,sr=sf.read(path,dtype='float32');
  if sr!=16000 or wave.ndim!=1 or not len(wave):raise ValueError('expected mono 16kHz')
  f=features(wave);encodings=[];predictions=[];context=[0,0]
  for enc,dec,join in self.models:
   output,lens=enc.run(None,{'x':f[None],'x_lens':np.array([len(f)],dtype=np.int64)});encodings.append((output,int(lens[0])));predictions.append(dec.run(None,{'y':np.array([context],dtype=np.int64)})[0])
  if len({x[1] for x in encodings})!=1:raise ValueError('encoder frame alignment mismatch')
  ids=[]
  for t in range(encodings[0][1]):
   logits=[model[2].run(None,{'encoder_out':encoding[0][:,t,:],'decoder_out':prediction})[0] for model,encoding,prediction in zip(self.models,encodings,predictions)];token=consensus_token(logits)
   if token!=0:
    ids.append(token);context=(context+[token])[-2:];y=np.array([context],dtype=np.int64);predictions=[model[1].run(None,{'y':y})[0] for model in self.models]
  text=self.sp.decode(ids).strip()
  if not text:raise ValueError('empty transcript')
  return {'text':text,'audio_seconds':len(wave)/sr,'seconds':time.perf_counter()-start,'tokens':ids}
