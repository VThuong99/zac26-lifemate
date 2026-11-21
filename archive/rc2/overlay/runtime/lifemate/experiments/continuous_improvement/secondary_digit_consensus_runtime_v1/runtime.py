"""Lazy and bounded CTC worker for same-source ASR disagreements."""
import json,select,subprocess,sys,time
from pathlib import Path
from experiments.continuous_improvement.spoken_digit_evidence_q8_v1.compose import facts,spans
R=Path(__file__).resolve().parents[3];D=Path(__file__).resolve().parent

def eligible_sources(payload,independent):
 raw=facts(payload) or [];out=[]
 for source in dict.fromkeys(x['source'] for x in raw):
  p=[x for x in raw if x['source']==source];i=spans(independent.get(source))
  if len(p)==len(i)==1 and p[0]['literal_digits']!=i[0]['literal_digits']:out.append(source)
 return out

class LazyCTC:
 def __init__(self):self.proc=None;self.log=None;self.ready=None
 def _read(self,timeout):
  if not self.proc or self.proc.poll() is not None:raise RuntimeError('CTC worker exited')
  if not select.select([self.proc.stdout],[],[],timeout)[0]:raise TimeoutError('CTC worker response timed out')
  line=self.proc.stdout.readline()
  if not line:raise RuntimeError('CTC worker closed output')
  result=json.loads(line)
  if result.get('error'):raise RuntimeError(result['error'])
  return result
 def start(self):
  if self.proc:return
  self.log=(D/'ctc_worker.log').open('a');self.proc=subprocess.Popen([str(R.parent/'.venvs/lifemate-p12-gipformer/bin/python'),str(D/'ctc_server.py')],cwd=R,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,text=True,bufsize=1)
  try:
   self.ready=self._read(15)
   if self.ready.get('ready') is not True or self.ready.get('parameters',0)>69651511:raise RuntimeError('invalid CTC worker identity')
  except Exception:self.close();raise
 def decode(self,audio,audio_sha256):
  self.start();self.proc.stdin.write(json.dumps({'audio':audio,'audio_sha256':audio_sha256})+'\n');self.proc.stdin.flush();out=self._read(8)
  if out.get('audio')!=audio or out.get('audio_sha256')!=audio_sha256 or not isinstance(out.get('ctc'),str):raise RuntimeError('CTC source mismatch')
  return out
 def close(self):
  if self.proc:
   try:self.proc.stdin.close();self.proc.wait(timeout=2)
   except (OSError,subprocess.TimeoutExpired):
    self.proc.terminate()
    try:self.proc.wait(timeout=2)
    except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=2)
  if self.log:self.log.close()
  self.proc=None;self.log=None;self.ready=None

def collect(payload,independent,independent_evidence,worker):
 bysource={e.get('source'):e for e in independent_evidence if e.get('audio') and e.get('audio_sha256') and 'independent' in e};ctc={};evidence=[]
 for source in eligible_sources(payload,independent):
  e=bysource.get(source)
  if not e:evidence.append({'source':source,'error':'missing same-source acoustic evidence'});continue
  try:
   result=worker.decode(e['audio'],e['audio_sha256']);ctc[source]=result['ctc'];evidence.append({'source':source,**result})
  except (OSError,RuntimeError,TimeoutError,ValueError,TypeError,KeyError) as exc:
   evidence.append({'source':source,'audio':e['audio'],'audio_sha256':e['audio_sha256'],'error':type(exc).__name__+': '+str(exc)});worker.close()
 return ctc,evidence
