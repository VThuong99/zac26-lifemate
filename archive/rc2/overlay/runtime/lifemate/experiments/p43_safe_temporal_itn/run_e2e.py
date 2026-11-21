"""P43: P34 greedy and safe latest-transcript temporal annotation through the frozen P32/P19 worker."""
import hashlib, importlib.util, json, multiprocessing as mp, os, random, sys, time, wave
from pathlib import Path

ROOT=Path((__import__('os').environ['LIFEMATE_CODE_ROOT'] + ''))
ASSETS=ROOT/'results/p33_chunkformer_assets_v1'
BUNDLE=ROOT/'results/p19_submission_staging_v1'
MANIFEST=ROOT/'experiments/p43_safe_temporal_itn/cohort.json'
OUT=Path(os.environ.get('P43_OUTPUT',str(ROOT/'results/p43_safe_temporal_itn_v1/e2e'))).resolve()
PORT=18196

spec=importlib.util.spec_from_file_location('p32_original',ROOT/'experiments/p32_oracle_text_v1/run.py')
p32=importlib.util.module_from_spec(spec); spec.loader.exec_module(p32)

class PipeWithAnnotations:
    def __init__(self, pipe, state): self.pipe=pipe; self.state=state
    def recv(self):
        value=self.pipe.recv()
        if value is not None:
            self.state.clear(); self.state.update({'arm':value[1], 'annotations':[], 'annotation_seconds':0.0})
        return value
    def send(self,value):
        if value[0]=='result':
            value[1]['annotations']=self.state.get('annotations',[])
            value[1].setdefault('timing',{})['annotation_seconds']=self.state.get('annotation_seconds',0.0)
        self.pipe.send(value)

def p33_worker(pipe,port):
    try:
        from experiments.p43_safe_temporal_itn.temporal import annotate
        selection_path=ROOT/'results/p34_gipformer_finetune_v1/selection.json'
        protocol=json.loads((ROOT/'experiments/p43_safe_temporal_itn/protocol.json').read_text())
        if hashlib.sha256(selection_path.read_bytes()).hexdigest()!=protocol['selection_sha256']: raise ValueError('selection mismatch')
        selected=json.loads(selection_path.read_text()); model=ROOT/selected['onnx_dir']
        for name,expected in protocol['p34_onnx_sha256'].items():
            h=hashlib.sha256()
            with (model/name).open('rb') as f:
                for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
            if h.hexdigest()!=expected:raise ValueError('P34 ASR mismatch: '+name)
        greedy=p32.GipformerASR(model,4)
        p32.GipformerASR=lambda unused,threads: greedy
        p32.ReferenceASR=lambda unused: greedy
        original_transform=p32.transform
        state={}
        def transform(text,mode):
            original=original_transform(text,mode)
            if state.get('arm')!='B':return original
            started=time.perf_counter(); result=annotate(original)
            state['annotation_seconds']=time.perf_counter()-started
            state['annotations']=result['annotations']
            return result['text']
        p32.transform=transform
        p32.worker(PipeWithAnnotations(pipe,state),port)
    except BaseException as exc:
        try: pipe.send(('fatal',f'{type(exc).__name__}: {exc}'))
        except Exception: pass

def launch():
    ctx=mp.get_context('spawn'); parent,child=ctx.Pipe(); proc=ctx.Process(target=p33_worker,args=(child,PORT)); proc.start(); child.close()
    if not parent.poll(120): proc.kill(); proc.join(); raise RuntimeError('Worker initialization timed out')
    status,value=parent.recv()
    if status!='ready': proc.join(timeout=2); raise RuntimeError(f'Worker initialization failed: {value}')
    return proc,parent

def main():
    seal=json.loads((ROOT/'experiments/p43_safe_temporal_itn/seal.json').read_text())
    for name,expected in seal['source_sha256'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:raise RuntimeError('source seal mismatch: '+name)
    if not Path(p32.runtime.__file__).resolve().is_relative_to(BUNDLE.resolve()):
        raise RuntimeError('P19 runtime did not load from verified bundle')
    random.seed(20261030)
    import numpy as np
    np.random.seed(20261030)
    p32.verify_bundle(BUNDLE)
    m=json.loads(MANIFEST.read_text()); ids=m['ids']; selected=set(ids)
    inputs={}
    with (ROOT/'train/train.jsonl').open(encoding='utf8') as f:
        for line in f:
            row=json.loads(line)
            if row['id'] in selected: inputs[row['id']]=p32.inference_input(row)
    if set(inputs)!=selected or len(ids)!=len(selected): raise ValueError('cohort coverage error')
    protocol=json.loads((ROOT/'experiments/p43_safe_temporal_itn/protocol.json').read_text())
    if hashlib.sha256(MANIFEST.read_bytes()).hexdigest()!=protocol['cohort_sha256']:raise ValueError('cohort fingerprint mismatch')
    screen=json.loads((ROOT/'results/p43_safe_temporal_itn_v1/screen/summary.json').read_text())
    if screen['requests']!=200 or screen['failed_ids']:raise RuntimeError('annotation screening failed')
    if not (ROOT/'results/p43_safe_temporal_itn_v1/screen/review.json').is_file():raise RuntimeError('annotation review missing')
    OUT.mkdir(parents=True,exist_ok=False)
    (OUT/'config.json').write_text(json.dumps({'ids':ids,'manifest_sha256':hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),'arms':{'A':'P34 live greedy','B':'P34 live greedy plus temporal annotation'},'deadline_seconds':30,'order':'alternate A/B and B/A by request','labels_or_references_in_worker':False},indent=2)+'\n')
    with p32.server(BUNDLE/'backend/bin/llama-server',BUNDLE/'models/p19.gguf',PORT,OUT/'server.log') as (startup,command):
        proc,pipe=launch()
        with (OUT/'trajectories.jsonl').open('x',encoding='utf8',buffering=1) as target:
            for n,i in enumerate(ids):
                for arm in (('A','B') if n%2==0 else ('B','A')):
                    path=OUT/f'{i}_{arm}_events.jsonl'; start=time.monotonic()
                    # Both arms receive only the sanitized organizer input and no reference map.
                    pipe.send((inputs[i],arm,None,str(path)))
                    if pipe.poll(max(0,30-(time.monotonic()-start))):
                        typ,result=pipe.recv(); elapsed=time.monotonic()-start
                        if typ!='result': result={'status':'worker_error','error':str(result),'prediction':None,'timing':{}}
                        if elapsed>=30: result['status']='timeout'
                        result.setdefault('timing',{})['dispatch_wall_seconds']=elapsed
                    else:
                        proc.kill(); proc.join(); pipe.close()
                        result={'status':'timeout','error':'hard deadline; worker terminated','prediction':None,'timing':{'dispatch_wall_seconds':time.monotonic()-start}}
                        proc,pipe=launch()
                    target.write(json.dumps({'id':i,'arm':arm,**result},ensure_ascii=False)+'\n'); target.flush(); os.fsync(target.fileno())
                    print(json.dumps({'completed':n+1,'total':len(ids),'id':i,'arm':arm,'status':result['status']}),flush=True)
        pipe.send(None); proc.join(timeout=10)
        if proc.is_alive(): proc.kill(); proc.join()
    (OUT/'server_metadata.json').write_text(json.dumps({'startup_seconds':startup,'command':command},indent=2)+'\n')
if __name__=='__main__': main()
