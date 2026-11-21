"""Paired original-audio P34 vs existing date anchor, authentic local execution."""
import hashlib,json,multiprocessing as mp,os,random,sys,time,shutil,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=Path(__file__).resolve().parent;B=R/'results/p19_submission_staging_v1';sys.path[:0]=[str(B),str(R)]
sys.path.append(str(R.parent/'.venvs/lifemate-p10/lib/python3.12/site-packages'))
from experiments.p43_safe_temporal_itn import run_e2e as safe
from experiments.continuous_improvement.temporal_chat_wallet_v1.compose import intervene as base_compose
from experiments.continuous_improvement.temporal_chat_wallet_v1.compose import intervene as candidate_compose
from submission_p19.run import verify_bundle
from experiments.continuous_improvement.library_composed_v1.agent import LibraryComposedAgent
from experiments.continuous_improvement.delivery_composed_v1.agent import DeliveryComposedAgent
from experiments.continuous_improvement.grounded_clarification_v4.agent import GroundedClarificationV4Agent
from experiments.continuous_improvement.calendar_scope_composition_v1.agent import CalendarScopeAgent
from experiments.continuous_improvement.unified_reference_grounding_v1.agent import UnifiedReferenceAgent
from experiments.continuous_improvement.colloquial_clock_scope_v4.compose import intervene as eligibility_compose
from experiments.continuous_improvement.text_search_identity_scope_v3.compose import intervene as route_compose
from experiments.continuous_improvement.contextual_route_time_scope_v3.compose import intervene as route_math
from experiments.continuous_improvement.ctc_entropy_corroboration_v1.runtime import Sidecars
from experiments.continuous_improvement.shared_asr_parent_router_v1.router import ParentCompatibleRouter as Router
from experiments.continuous_improvement.shared_asr_digit_composition_v1.shared_ctc import SharedCTC
from experiments.continuous_improvement.corroborated_digit_evidence_q8_v1.runtime import collect
from experiments.continuous_improvement.secondary_digit_consensus_runtime_v1.runtime import collect as collect_ctc
from experiments.continuous_improvement.corroborated_digit_evidence_q8_v1.compose import intervene as digit_compose
from experiments.continuous_improvement.secondary_digit_consensus_screen_v1.compose import intervene as secondary_compose
from experiments.continuous_improvement.schema_date_scope_v3.agent import ScopedDateAgent
from experiments.continuous_improvement.schema_feedback_review_v1.policy import review_request
from experiments.continuous_improvement.message_content_schema_v1.compose import intervene as message_compose
from experiments.continuous_improvement.weekday_temporal_scope_v3.anchor import intervene as weekday_compose
from experiments.continuous_improvement.scoped_adapter_read_e2e_v1.run import overlay_server
from src.controller import Controller
from experiments.continuous_improvement.conditional_terminal_pref_flight_e2e_v1.safety_gate import install as install_safety_gate
from experiments.continuous_improvement.recipient_provenance_e2e_v1.run import launch as launch_strong
from src.llm_client import LLMClient
from experiments.continuous_improvement.finish_consistent_review_e2e_v1.compose import intervene as pair_compose
from experiments.continuous_improvement.finish_consistent_review_e2e_v1.agent import FinishSourceOrderAgent
from experiments.continuous_improvement.finish_verbatim_recap_v1.transform import intervene as source_order
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
   self.state['arm']=value[1];self.state['current_id']=value[0]['id'];self.state['preflight_reads']=[];self.state['preflight_mutations']=0;self.state['safety_events']=[];self.state['current_clips']=[];self.state['independent_by_source']={};self.state['acoustic_evidence']=[];self.state['ctc_by_source']={};self.state['ctc_evidence']=[]
   self.state['history_remaining']=sum(1 for turn in value[0]['history'] if isinstance(turn,dict) and turn.get('role')=='user' and 'audio' in turn)
   if value[1] in ('C','D','E'):value=(value[0],'B',*value[2:])
  return value
 def send(self,value):
  if value[0]=='result':value[1]['acoustic_evidence']=self.state.get('acoustic_evidence',[]);value[1]['ctc_evidence']=self.state.get('ctc_evidence',[]);value[1]['safety_events']=self.state.get('safety_events',[])
  self.pipe.send(value)
def worker(pipe,port):
 state={};base=P.ControlledClient
 class Client(base):
  def generate(self,messages,*args,**kwargs):
   if state.get('arm')=='B':messages=base_compose({'messages':messages})['messages']
   elif state.get('arm') in ('C','D','E'):messages=candidate_compose({'messages':messages})['messages']
   if state.get('arm') in ('C','D','E'):messages=weekday_compose({'messages':messages})['messages']
   if state.get('arm') in ('C','D','E') and state.get('schema_review'):
    rev=state['schema_review'];messages=review_request({'messages':messages},rev['action'],rev['tools'])['messages']
   if state.get('arm') in ('C','D','E'):messages=eligibility_compose({'messages':messages})['messages']
   if state.get('arm') in ('C','D'):messages=digit_compose({'messages':messages},state.get('independent_by_source',{}))['messages'];messages=secondary_compose({'messages':messages},state.get('independent_by_source',{}),state.get('ctc_by_source',{}))['messages']
   if state.get('arm')=='C':messages=pair_compose({'messages':messages})['messages']
   if state.get('arm')=='C' and state.get('finish_source_review'):messages=source_order({'messages':messages})[0]['messages']
   wire={}
   def controlled(request,timeout):
    payload=json.loads(request.data);payload['cache_prompt']=False;payload['lora']=[{'id':0,'scale':1.0 if state.get('write_review') and not state.get('finish_source_review') else 0.0},{'id':1,'scale':1.0 if state.get('write_review') and state.get('finish_source_review') else 0.0}]
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
 if os.environ.get('LIFEMATE_PREFLIGHT_FILE'):
  approved=json.loads(Path(os.environ['LIFEMATE_PREFLIGHT_FILE']).read_text());install_safety_gate(Controller,kinds,state,approved)
 def choose(*args,**kwargs):return FinishSourceOrderAgent(*args,review_state=state,kinds=kinds,**kwargs) if state.get('arm')=='C' else UnifiedReferenceAgent(*args,review_state=state,kinds=kinds,**kwargs) if state.get('arm') in ('D','E') else (DeliveryComposedAgent if state.get('arm')=='D' else original)(*args,**kwargs)
 P.runtime.Agent=choose
 asr_class=P.GipformerASR
 def make_asr(unused,threads):
  side=Sidecars();assert side.model_parameters==69651511 and side.pho_parameters==763857920 and 4659865088<5000000000 and 4659865088+69651511+side.model_parameters+side.pho_parameters+(R/'experiments/continuous_improvement/dpo_finish_overlay_v1/adapter_f32.gguf').stat().st_size//4<6000000000
  state['sidecars']=side
  return Router(state,asr_class(R/'results/p34_gipformer_finetune_v1/export_epoch2',threads),side)
 P.GipformerASR=make_asr
 original_transcribe=P.transcribe_input
 def transcribe(item,root,split,asr):
  text,history,clips=original_transcribe(item,root,split,asr)
  if state.get('arm') in ('C','D'):
   side=state['sidecars'];independent,evidence=collect(item,root,split,text,history,side.pho,P.runtime.audio_path)
   state['independent_by_source']=independent;state['acoustic_evidence']=evidence
   ctc,ctc_evidence=collect_ctc({'user_request':text,'previous_steps':history},independent,evidence,SharedCTC(side,root,split,P.runtime.audio_path));state['ctc_by_source']=ctc;state['ctc_evidence']=ctc_evidence
  state['current_clips']=clips
  return text,history,clips
 P.transcribe_input=transcribe;safe.p33_worker(StatePipe(pipe,state),port)

def launch(port):
 ctx=mp.get_context('spawn');a,b=ctx.Pipe();p=ctx.Process(target=worker,args=(b,port));p.start();b.close()
 if not a.poll(120):p.kill();p.join();raise RuntimeError('worker initialization timeout')
 status,value=a.recv()
 if status!='ready':p.join(timeout=2);raise RuntimeError('worker initialization: '+str(value))
 return p,a

def main():
 cfg=json.loads((D/'protocol.json').read_text());ids=cfg['cohort'];assert len(ids)==len(set(ids))==3;limit=int(os.environ.get('LIFEMATE_FRESH_LIMIT','0'));assert 0<=limit<=3;runids=ids[:limit] if limit else ids
 for name,expected in json.loads((D/'source_seal.json').read_text()).items():
  assert sha(R/name)==expected,name
 verify_bundle(B)
 if not Path(P.runtime.__file__).resolve().is_relative_to(B.resolve()):raise RuntimeError('runtime not frozen P19')
 wanted=set(ids);items={x['id']:P.inference_input(x) for x in map(json.loads,(R/'train/train.jsonl').open()) if x['id'] in wanted};assert set(items)==wanted
 audio_paths={x['audio'] for x in items.values()}|{v['audio'] for x in items.values() for v in x['history'] if v.get('role')=='user' and 'audio' in v};audio_hashes={a:sha(P.runtime.audio_path(R,'train',a)) for a in sorted(audio_paths)}
 out=D/'run';out.mkdir(exist_ok=True);(out/'events').mkdir(exist_ok=True);(out/'claims').mkdir(exist_ok=True)
 config={'protocol_sha256':sha(D/'protocol.json'),'seed':20261030,'labels_or_references_in_worker':False,'arms':['A','E','C','D'],'deadline_seconds':30,'audio_sha256':audio_hashes}
 def atomic(path,value):
  tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');os.replace(tmp,path)
 if (out/'config.json').exists():assert json.loads((out/'config.json').read_text())==config
 else:atomic(out/'config.json',config)
 traj=out/'trajectories.jsonl';completed={}
 if traj.exists():
  for line in traj.open():
   row=json.loads(line);key=(row['id'],row['arm']);assert key not in completed and row['id'] in wanted and row['arm'] in 'ACDE';completed[key]=row

 random.seed(20261030);import numpy as np;np.random.seed(20261030)
 port=18587
 adapter=R/'experiments/continuous_improvement/dpo_finish_overlay_v1/adapter_f32.gguf'
 assert sha(adapter)==json.loads((adapter.parent/'conversion_verify.json').read_text())['adapter_sha256']
 metadata=json.loads((out/'server_metadata.json').read_text()) if (out/'server_metadata.json').exists() else {'attempts':[]}
 with traj.open('a',encoding='utf8',buffering=1) as target:
  for name,model,arms in [('q4',B/'models/p19.gguf',['A','E']),('q8',R/'experiments/continuous_improvement/p19_champion_q8_v1/p19_q8.gguf',['C','D'])]:
   remaining=[(i,arm) for i in runids for arm in cfg['fresh_arms'][i] if arm in arms and (i,arm) not in completed]
   if not remaining:continue
   with overlay_server(B/'backend/bin/llama-server',model,port,out/('server_'+name+'_'+str(time.time_ns())+'.log'),adapter) as (startup,command):
    metadata['attempts'].append({'model':name,'model_sha256':sha(model),'startup_seconds':startup,'command':command});proc,pipe=(launch_strong(port) if name=='q4' else launch(port))
    try:
     for i in runids:
      for arm in cfg['fresh_arms'][i]:
       if arm not in arms or (i,arm) in completed:continue
       if shutil.disk_usage(out).free<10000000000:raise RuntimeError('disk reserve below 10 GB; preserve completed trajectories')
       claim=out/'claims'/f'{i}_{arm}.json';path=out/'events'/f'{i}_{arm}_events.jsonl'
       for stale in (claim,path):
        if stale.exists():stale.rename(stale.with_name(stale.name+'.interrupted.'+str(time.time_ns())))
       with claim.open('x') as f:json.dump({'id':i,'arm':arm},f);f.flush();os.fsync(f.fileno())
       started=time.monotonic();pipe.send((items[i],'C' if arm=='E' else arm,None,str(path)))
       if pipe.poll(max(0,30-(time.monotonic()-started))):
        typ,res=pipe.recv();elapsed=time.monotonic()-started
        if typ!='result':res={'status':'worker_error','error':str(res),'prediction':None,'timing':{}}
        if elapsed>=30:res['status']='timeout'
        res.setdefault('timing',{})['dispatch_wall_seconds']=elapsed
       else:
        proc.kill();proc.join();pipe.close();res={'status':'timeout','error':'hard deadline; no retry','prediction':None,'timing':{'dispatch_wall_seconds':time.monotonic()-started}};proc,pipe=(launch_strong(port) if name=='q4' else launch(port))
       target.write(json.dumps({'id':i,'arm':arm,**res},ensure_ascii=False)+'\n');target.flush();os.fsync(target.fileno());completed[i,arm]=res;metadata['trajectory_sha256']=sha(traj);atomic(out/'server_metadata.json',metadata);print(name,i,arm,res['status'],'free',shutil.disk_usage(out).free,flush=True)
    finally:
     if proc.is_alive():
      try:pipe.send(None);proc.join(timeout=10)
      except (BrokenPipeError,EOFError):pass
      if proc.is_alive():proc.kill();proc.join()
     pipe.close()
 metadata['trajectory_sha256']=sha(traj);atomic(out/'server_metadata.json',metadata);assert limit or len(completed)==sum(len(v) for v in cfg['fresh_arms'].values());verify_bundle(B)
if __name__=='__main__':main()
