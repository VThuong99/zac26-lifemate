"""Paired original-audio P34 vs existing date anchor, authentic local execution."""
import hashlib,json,multiprocessing as mp,os,random,sys,time
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=Path(__file__).resolve().parent;B=R/'results/p19_submission_staging_v1';sys.path[:0]=[str(B),str(R)]
from experiments.p43_safe_temporal_itn import run_e2e as safe
from experiments.continuous_improvement.temporal_chat_wallet_v1.compose import intervene as base_compose
from experiments.continuous_improvement.temporal_chat_wallet_v1.compose import intervene as candidate_compose
from submission_p19.run import verify_bundle
from experiments.continuous_improvement.library_composed_v1.agent import LibraryComposedAgent
from experiments.continuous_improvement.delivery_composed_v1.agent import DeliveryComposedAgent
from experiments.continuous_improvement.grounded_clarification_v4.agent import GroundedClarificationV4Agent
from experiments.continuous_improvement.calendar_scope_composition_v1.agent import CalendarScopeAgent
from experiments.continuous_improvement.scoped_adapter_read_review_v1.agent import ScopedAdapterReadAgent
from experiments.continuous_improvement.schema_date_scope_v3.agent import ScopedDateAgent
from experiments.continuous_improvement.schema_feedback_review_v1.policy import review_request
from experiments.continuous_improvement.message_content_schema_v1.compose import intervene as message_compose
from experiments.continuous_improvement.weekday_temporal_scope_v3.anchor import intervene as weekday_compose
from contextlib import contextmanager
import socket,subprocess
from urllib.error import URLError
from src.llm_client import LLMClient
from unittest.mock import patch
from urllib.request import Request,urlopen
from experiments.continuous_improvement.library_composed_v1.agent import LibraryComposedAgent
P=safe.p32

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()

class StatePipe:
 def __init__(self,pipe,state):self.pipe=pipe;self.state=state
 def recv(self):
  value=self.pipe.recv()
  if value is not None:
   self.state['arm']=value[1]
   if value[1] in ('C','D','E'):value=(value[0],'B',*value[2:])
  return value
 def send(self,value):self.pipe.send(value)
def worker(pipe,port):
 state={};base=P.ControlledClient
 class Client(base):
  def generate(self,messages,*args,**kwargs):
   if state.get('arm')=='B':messages=base_compose({'messages':messages})['messages']
   elif state.get('arm') in ('C','D','E'):messages=candidate_compose({'messages':messages})['messages']
   if state.get('arm') in ('C','D','E'):messages=weekday_compose({'messages':messages})['messages']
   if state.get('arm') in ('C','D','E') and state.get('schema_review'):
    rev=state['schema_review'];messages=review_request({'messages':messages},rev['action'],rev['tools'])['messages']
   wire={}
   def controlled(request,timeout):
    payload=json.loads(request.data);payload['cache_prompt']=False;payload['lora']=[{'id':0,'scale':1.0 if state.get('arm') in ('C','E') and state.get('write_review') else 0.0},{'id':1,'scale':1.0 if state.get('arm')=='C' and state.get('read_review') else 0.0}]
    encoded=json.dumps(payload,ensure_ascii=False).encode('utf8');wire['request']=payload;wire['wire_sha256']=hashlib.sha256(encoded).hexdigest()
    return urlopen(Request(request.full_url,data=encoded,headers={'Content-Type':'application/json'},method='POST'),timeout=timeout)
   with patch('src.llm_client.urlopen',controlled):result=LLMClient.generate(self,messages,*args,**kwargs)
   response=result.raw_response
   if not isinstance(response,dict) or not isinstance(response.get('timings'),dict) or response['timings'].get('cache_n')!=0:raise RuntimeError('missing or nonzero cache telemetry')
   self.requests.append({**wire,'cache_n':0,'prompt_tokens':result.metrics.prompt_tokens,'response':result.content})
   return result
 P.ControlledClient=Client
 original=P.runtime.Agent
 kinds=json.loads((R/'experiments/continuous_improvement/adapter_read_before_write_v1/tool_kinds.json').read_text())
 def choose(*args,**kwargs):return ScopedAdapterReadAgent(*args,review_state=state,kinds=kinds,**kwargs) if state.get('arm')=='C' else CalendarScopeAgent(*args,review_state=state,kinds=kinds,**kwargs) if state.get('arm')=='E' else (DeliveryComposedAgent if state.get('arm')=='D' else original)(*args,**kwargs)
 P.runtime.Agent=choose;safe.p33_worker(StatePipe(pipe,state),port)

def launch(port):
 ctx=mp.get_context('spawn');a,b=ctx.Pipe();p=ctx.Process(target=worker,args=(b,port));p.start();b.close()
 if not a.poll(120):p.kill();p.join();raise RuntimeError('worker initialization timeout')
 status,value=a.recv()
 if status!='ready':p.join(timeout=2);raise RuntimeError('worker initialization: '+str(value))
 return p,a

@contextmanager
def overlay_server(binary,model,port,log_path,adapters):
 with socket.socket() as sock:
  sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('127.0.0.1',port))
 command=[str(binary),'--model',str(model),'--host','127.0.0.1','--port',str(port),'--ctx-size','8192','--n-gpu-layers','99','--parallel','1','--threads','8','--batch-size','512','--ubatch-size','512','--flash-attn','on','--seed','20261030','--jinja']
 command+=['--lora-scaled',','.join(str(a)+':0' for a in adapters)]
 with log_path.open('x',encoding='utf8') as log:
  started=time.perf_counter();process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
  try:
   while True:
    if process.poll() is not None:raise RuntimeError(f'server exited {process.returncode}; see {log_path}')
    try:
     with urlopen(f'http://127.0.0.1:{port}/health',timeout=1) as response:
      if response.status==200:break
    except (URLError,TimeoutError,ConnectionError):pass
    if time.perf_counter()-started>=120:raise TimeoutError('server startup timeout')
    time.sleep(.1)
   yield time.perf_counter()-started,command
  finally:
   process.terminate()
   try:process.wait(timeout=10)
   except subprocess.TimeoutExpired:process.kill();process.wait()


def main():
 cfg=json.loads((D/'protocol.json').read_text());ids=cfg['cohort'];assert len(ids)==len(set(ids))==8
 for name,expected in json.loads((D/'source_seal.json').read_text()).items():
  assert sha(R/name)==expected,name
 verify_bundle(B)
 if not Path(P.runtime.__file__).resolve().is_relative_to(B.resolve()):raise RuntimeError('runtime not frozen P19')
 wanted=set(ids);items={x['id']:P.inference_input(x) for x in map(json.loads,(R/'train/train.jsonl').open()) if x['id'] in wanted};assert set(items)==wanted
 audio_paths={x['audio'] for x in items.values()}|{v['audio'] for x in items.values() for v in x['history'] if v.get('role')=='user' and 'audio' in v};audio_hashes={a:sha(P.runtime.audio_path(R,'train',a)) for a in sorted(audio_paths)}
 out=D/'run';out.mkdir(exist_ok=False);(out/'events').mkdir();(out/'claims').mkdir();(out/'config.json').write_text(json.dumps({'protocol_sha256':sha(D/'protocol.json'),'seed':20261030,'labels_or_references_in_worker':False,'arms':['A','E','C'],'deadline_seconds':30,'audio_sha256':audio_hashes},indent=2)+'\n')
 random.seed(20261030);import numpy as np;np.random.seed(20261030)
 port=18507
 adapter=R/'experiments/continuous_improvement/dpo_finish_overlay_v1/adapter_f32.gguf'
 assert sha(adapter)==json.loads((adapter.parent/'conversion_verify.json').read_text())['adapter_sha256']
 with overlay_server(B/'backend/bin/llama-server',B/'models/p19.gguf',port,out/'server.log',[adapter,R/'experiments/continuous_improvement/verified_multi_family_sft_v1/B/adapter_f32.gguf']) as (startup,command):
  proc,pipe=launch(port)
  try:
   with (out/'trajectories.jsonl').open('x',encoding='utf8',buffering=1) as target:
    for n,i in enumerate(ids):
     for arm in cfg['fresh_arms'].get(i,[]):
      claim=out/'claims'/f'{i}_{arm}.json'
      with claim.open('x') as f:json.dump({'id':i,'arm':arm,'index':n},f);f.flush();os.fsync(f.fileno())
      path=out/'events'/f'{i}_{arm}_events.jsonl';start=time.monotonic();pipe.send((items[i],arm,None,str(path)))
      if pipe.poll(max(0,30-(time.monotonic()-start))):
       typ,res=pipe.recv();elapsed=time.monotonic()-start
       if typ!='result':res={'status':'worker_error','error':str(res),'prediction':None,'timing':{}}
       if elapsed>=30:res['status']='timeout'
       res.setdefault('timing',{})['dispatch_wall_seconds']=elapsed
      else:
       proc.kill();proc.join();pipe.close();res={'status':'timeout','error':'hard deadline; no retry','prediction':None,'timing':{'dispatch_wall_seconds':time.monotonic()-start}};proc,pipe=launch(port)
      target.write(json.dumps({'id':i,'arm':arm,**res},ensure_ascii=False)+'\n');target.flush();os.fsync(target.fileno());print(n+1,len(ids),i,arm,res['status'],flush=True)
  finally:
   if proc.is_alive():
    try:pipe.send(None);proc.join(timeout=10)
    except (BrokenPipeError,EOFError):pass
    if proc.is_alive():proc.kill();proc.join()
   pipe.close()
 (out/'server_metadata.json').write_text(json.dumps({'startup_seconds':startup,'command':command,'trajectory_sha256':sha(out/'trajectories.jsonl')},indent=2)+'\n');verify_bundle(B)
if __name__=='__main__':main()
