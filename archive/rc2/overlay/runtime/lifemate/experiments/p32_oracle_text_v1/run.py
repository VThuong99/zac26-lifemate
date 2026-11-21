"""Train-only paired P19 transcript diagnostic; never produces a submission."""
import copy, json, multiprocessing as mp, os, random, sys, time, traceback
from pathlib import Path

ROOT = Path((__import__('os').environ['LIFEMATE_CODE_ROOT'] + ''))
BUNDLE = ROOT/'results/p19_submission_staging_v1'
OUT = Path(os.environ.get('P32_OUTPUT', str(ROOT/'results/p32_oracle_text_v1'))).resolve()
MANIFEST = ROOT/'experiments/p32_oracle_text_v1/manifest.json'

# Called with the frozen bundle ahead of the working tree on PYTHONPATH.
from src.p10_audio import GipformerASR, inference_input, transcribe_input
import src.p10_audio as runtime
from scripts.evaluate_p10 import server
from scripts.evaluate_p15_robustness import ControlledClient, transform
from scripts.run_p10_audio import tool_env_for_split
from submission_p19.run import verify_bundle

class ReferenceASR:
    def __init__(self, clips): self.clips = clips
    def transcribe(self, path):
        key = str(path)
        if key not in self.clips: raise ValueError('Reference missing for audio path')
        return {'text': self.clips[key], 'audio_seconds': None, 'seconds': 0.0}

def reference_map(row):
    pairs = [(row['audio'], row['audio_text'])]
    pairs += [(t['audio'],t['audio_text']) for t in row['history'] if t.get('role') == 'user' and 'audio' in t]
    refs = {}
    for path, value in pairs:
        if not isinstance(value,str) or not value.strip(): raise ValueError('Empty reference')
        full = str(runtime.audio_path(ROOT, 'train', path))
        if full in refs and refs[full] != value: raise ValueError('Conflicting references for same WAV')
        refs[full] = value
    return refs

def worker(pipe, port):
    try:
        asr = GipformerASR(BUNDLE/'models/asr',4)
        tool_env = tool_env_for_split(ROOT,'train')
        prompt = (BUNDLE/'prompts/explicit_stopping.txt').read_text().strip()
        client = ControlledClient(endpoint=f'http://127.0.0.1:{port}/v1/chat/completions',timeout=30,decoding_mode='strict')
        pipe.send(('ready',None))
        while True:
            data = pipe.recv()
            if data is None: return
            item, arm, refs, events_path = data
            started = time.perf_counter()
            try:
                with open(events_path,'x',encoding='utf8',buffering=1) as eventfile:
                    original_planner, original_agent = runtime.LLMPlanner, runtime.Agent
                    def wrap(cls):
                        def construct(*args, **kwargs):
                            sink=kwargs.get('trace_sink')
                            def record(event):
                                sink(event)
                                eventfile.write(json.dumps(event,ensure_ascii=False)+'\n'); eventfile.flush()
                            kwargs['trace_sink']=record
                            return cls(*args,**kwargs)
                        return construct
                    runtime.LLMPlanner=wrap(original_planner); runtime.Agent=wrap(original_agent)
                    try:
                        text,history,clips=transcribe_input(item,ROOT,'train',asr if arm=='A' else ReferenceASR(refs))
                        source_seconds=time.perf_counter()-started
                        text=transform(text,'sentence')
                        client.requests=[]
                        result=runtime.run_trajectory(item,text,history,ROOT,'train',tool_env,client,prompt,30,max_steps=7,started=started)
                        result['timing']['transcript_source_seconds']=source_seconds
                        result['transcripts']=clips; result['requests']=client.requests
                    finally:
                        runtime.LLMPlanner=original_planner; runtime.Agent=original_agent
                pipe.send(('result',result))
            except Exception as exc:
                pipe.send(('result',{'status':'worker_error','error':f'{type(exc).__name__}: {exc}','traceback':traceback.format_exc(),'prediction':None,'timing':{'total_seconds':time.perf_counter()-started}}))
    except BaseException as exc:
        try: pipe.send(('fatal',repr(exc)))
        except Exception: pass

def launch(port):
    ctx=mp.get_context('spawn'); parent, child=ctx.Pipe(); proc=ctx.Process(target=worker,args=(child,port)); proc.start(); child.close()
    if not parent.poll(60): proc.kill(); proc.join(); raise RuntimeError('Worker initialization timed out')
    status,value=parent.recv()
    if status!='ready': proc.join(timeout=2); raise RuntimeError(f'Worker initialization failed: {value}')
    return proc,parent

def main():
    random.seed(20261030)
    import numpy as np
    np.random.seed(20261030)
    verify_bundle(BUNDLE)
    ids=json.loads(MANIFEST.read_text())['ids']; selected=set(ids)
    rows={}
    with (ROOT/'train/train.jsonl').open(encoding='utf8') as f:
        for line in f:
            row=json.loads(line)
            if row['id'] in selected: rows[row['id']]=row
    if set(rows)!=selected: raise ValueError('Cohort missing from dataset')
    # Validate all reference links before inference; no gold fields are sent to workers.
    refs={i:reference_map(rows[i]) for i in ids}
    inputs={i:inference_input(rows[i]) for i in ids}
    OUT.mkdir(parents=True,exist_ok=False)
    port=18189
    (OUT/'config.json').write_text(json.dumps({'ids':ids,'timeout_seconds':30,'arms':{'A':'live Gipformer greedy','B':'organizer audio_text; diagnostic'},'order':'A,B for even index; B,A for odd','model_sha256':'fc596f336207a81766df77f66a7d445d2d7371798746173176a1483a52487b46','source':'verified P19 staging bundle','time_boundary':'request dispatch through result receipt; initialization excluded'},indent=2)+'\n')
    with server(BUNDLE/'backend/bin/llama-server',BUNDLE/'models/p19.gguf',port,OUT/'server.log') as (startup,command):
        proc,pipe=launch(port)
        with (OUT/'trajectories.jsonl').open('x',encoding='utf8',buffering=1) as target:
            for n,i in enumerate(ids):
                for arm in (('A','B') if n%2==0 else ('B','A')):
                    events=OUT/f'{i}_{arm}_events.jsonl'
                    start=time.monotonic()
                    pipe.send((inputs[i],arm,refs[i] if arm=='B' else None,str(events)))
                    if pipe.poll(max(0,30-(time.monotonic()-start))):
                        typ,result=pipe.recv()
                        elapsed=time.monotonic()-start
                        if typ!='result': result={'status':'worker_error','error':str(result),'prediction':None,'timing':{}}
                        if elapsed>=30: result['status']='timeout'
                        result.setdefault('timing',{})['dispatch_wall_seconds']=elapsed
                    else:
                        proc.kill(); proc.join(); pipe.close()
                        result={'status':'timeout','error':'hard deadline; worker terminated','prediction':None,'timing':{'dispatch_wall_seconds':time.monotonic()-start}}
                        proc,pipe=launch(port)
                    target.write(json.dumps({'id':i,'arm':arm,**result},ensure_ascii=False)+'\n'); target.flush(); os.fsync(target.fileno())
                    print(json.dumps({'completed':n+1,'total':len(ids),'id':i,'arm':arm,'status':result['status']}),flush=True)
        pipe.send(None); proc.join(timeout=10)
        if proc.is_alive(): proc.kill(); proc.join()
    (OUT/'server_metadata.json').write_text(json.dumps({'startup_seconds':startup,'command':command},indent=2)+'\n')
if __name__=='__main__': main()
