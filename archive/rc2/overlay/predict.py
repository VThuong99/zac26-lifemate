"""Deployment transport for sealed K; all decisions run in the preserved worker."""
import argparse
import ast
import contextlib
import hashlib
import importlib
import inspect
import ipaddress
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import socket
import subprocess
import sys
import time
import traceback

SEED = 20261030
HERE = Path(__file__).resolve().parent

def seed_everything():
    random.seed(SEED)
    import numpy as np
    np.random.seed(SEED)
    import torch
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    # K's PhoWhisper loader also sets deterministic algorithms and this workspace.
    torch.use_deterministic_algorithms(True)
    os.environ['CUBLAS_WORKSPACE_CONFIG'] = ':4096:8'

def offline_guard():
    """Loopback serves the local llama process; reject external Python connections."""
    def audit(event, args):
        if event == 'socket.connect':
            address = args[1]
            if isinstance(address, tuple):
                try:
                    local = ipaddress.ip_address(address[0]).is_loopback
                except ValueError:
                    local = False
                if not local:
                    raise RuntimeError('Offline inference rejected an external socket')
    sys.addaudithook(audit)

def discover_split(root, requested=None):
    root = Path(root).resolve()
    candidates = [p.name for p in root.iterdir() if p.is_dir()
                  and (p / (p.name + '.jsonl')).is_file()
                  and (p / (p.name + '_tools_catalog.json')).is_file()
                  and (p / 'zaic_tools/__init__.py').is_file()]
    if requested is not None:
        if requested not in candidates:
            raise ValueError('Requested split does not satisfy the mounted split contract')
        return requested
    if len(candidates) != 1:
        raise ValueError('Expected exactly one mounted split; use --split when several exist')
    return candidates[0]

def read_cases(root, split, limit=None):
    """Read only organizer inputs, never labels or environment files."""
    cases, seen = [], set()
    with (Path(root) / split / (split + '.jsonl')).open(encoding='utf8') as f:
        for line in f:
            item = json.loads(line)
            if set(item) != {'id', 'audio', 'context', 'history'}:
                raise ValueError('Input must contain only id, audio, context, history')
            if not isinstance(item['id'], str) or item['id'] in seen:
                raise ValueError('Invalid or duplicate identifier')
            for turn in item['history']:
                if isinstance(turn, dict) and {'label','audio_text','final_state','state_hash'} & set(turn):
                    raise ValueError('Reference fields are forbidden at inference')
            seen.add(item['id'])
            cases.append(item)
            if limit is not None and len(cases) >= limit:
                break
    return cases

def _imports(code_root):
    os.environ['LIFEMATE_CODE_ROOT'] = str(code_root)
    bundle = code_root / 'results/p19_submission_staging_v1'
    sys.path[:0] = [str(bundle), str(code_root)]
    extra = os.environ.get('LIFEMATE_EXTRA_SITE')
    if extra:
        sys.path.append(extra)  # Native validation only; Docker has a unified environment.
    return importlib.import_module('experiments.continuous_improvement.conditional_terminal_pref_flight_e2e_v1.worker')

def _child(pipe, port, code_root, data_root, split):
    try:
        if os.environ.get('LIFEMATE_PREFLIGHT_FILE'):
            raise RuntimeError('Research preflight gates are forbidden in the sealed submission')
        offline_guard()
        seed_everything()
        module = _imports(Path(code_root))
        original = inspect.getsource(module.P.worker)
        if original.count("'train'") != 3:
            raise RuntimeError('Frozen worker split bridge changed')
        modified = original.replace("'train'", repr(split))
        before, after = ast.parse(original), ast.parse(modified)
        class Undo(ast.NodeTransformer):
            def visit_Constant(self, node):
                if node.value == split: node.value = 'train'
                return node
        if ast.dump(before) != ast.dump(Undo().visit(after)):
            raise RuntimeError('Split bridge changed the worker policy')
        exec(compile(modified, '<split-only-K-worker>', 'exec'), module.P.__dict__)
        module.P.ROOT = Path(data_root)
        # Count only constructor calls; do not inspect or clone ToolEnv state.
        original_factory = module.P.tool_env_for_split
        counts = {}
        def factory(root, selected):
            native = original_factory(root, selected)
            def construct(actual_split, sample_id, **kwargs):
                counts[sample_id] = counts.get(sample_id, 0) + 1
                if counts[sample_id] != 1:
                    raise RuntimeError('More than one ToolEnv for this request')
                return native(actual_split, sample_id, **kwargs)
            return construct
        module.P.tool_env_for_split = factory
        class ReceiptPipe:
            def recv(self): return pipe.recv()
            def send(self, value):
                if value[0] == 'ready':
                    loaded = sorted({str(Path(m.__file__).resolve()) for m in list(sys.modules.values())
                                     if getattr(m, '__file__', None) and Path(m.__file__).is_file()
                                     and Path(m.__file__).resolve().is_relative_to(Path(code_root).parent)})
                    value = ('ready', {'python_version':sys.version, 'loaded_release_modules':loaded})
                if value[0] == 'result':
                    prediction = value[1].get('prediction')
                    value[1]['toolenv_instances'] = counts.get(prediction['id'], 0) if prediction else None
                    import resource
                    value[1]['worker_peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
                pipe.send(value)
        module.worker(ReceiptPipe(), port)
    except BaseException:
        try: pipe.send(('fatal', traceback.format_exc()))
        except (OSError, EOFError): pass

def backend_for_device(native_root):
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA GPU required; no CPU backend substitution')
    capability = torch.cuda.get_device_capability(0)
    # rc2 uses the existing native dual-target build on Ampere; actual A30 remains unverified.
    # Blackwell retains the original qualified binary and CUDA library, byte for byte.
    target = {(8, 0): 'sm80', (12, 0): 'sm120'}.get(capability)
    if target is None:
        raise RuntimeError('Unqualified GPU compute capability: ' + repr(capability))
    binary = Path(native_root) / target / 'bin/llama-server'
    if not binary.is_file():
        raise FileNotFoundError('Required GPU backend missing: ' + str(binary))
    return target, binary

class KRuntime:
    def __init__(self, data_root='/data', split=None, evidence_dir='/result/diagnostics',
                 runtime_root=None, native_root=None):
        self.data_root = Path(data_root).resolve()
        self.split = discover_split(self.data_root, split)
        self.code_root = Path(runtime_root or os.environ.get('LIFEMATE_RUNTIME_ROOT', HERE/'runtime')).resolve() / 'lifemate'
        self.native_root = Path(native_root or os.environ.get('LIFEMATE_NATIVE_ROOT', HERE/'native')).resolve()
        self.evidence = Path(evidence_dir)
        self.evidence.mkdir(parents=True, exist_ok=False)
        self.stack = contextlib.ExitStack()
        self.proc = self.pipe = None

    def load(self):
        start = time.perf_counter()
        try:
            offline_guard()
            seed_everything()
            module = _imports(self.code_root)
            target, binary = backend_for_device(self.native_root)
            os.environ['LD_LIBRARY_PATH'] = str(binary.parent) + ':' + os.environ.get('LD_LIBRARY_PATH', '')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            pref = self.code_root / 'experiments/continuous_improvement'
            model = pref / 'p19_champion_q8_v1/p19_q8.gguf'
            adapters = [pref/'dpo_finish_overlay_v1/adapter_f32.gguf',
                        pref/'conditional_terminal_preference_sft_v1/K/adapter_f32.gguf']
            startup, command = self.stack.enter_context(module.overlay_server(binary, model, port, self.evidence/'llama-server.log', adapters))
            ctx = mp.get_context('spawn')
            parent, child = ctx.Pipe()
            self.proc = ctx.Process(target=_child, args=(child,port,str(self.code_root),str(self.data_root),self.split))
            self.pipe = parent
            self.proc.start()
            child.close()
            if not parent.poll(180):
                raise RuntimeError('ASR worker model loading timed out')
            status, detail = parent.recv()
            if status != 'ready': raise RuntimeError(str(detail))
            metadata = {'backend': target, 'llm_load_seconds': startup,
                        'all_models_load_seconds': time.perf_counter()-start,
                        'command': command, 'seed': SEED, 'split':self.split,
                        'worker_details': detail,
                        'a30_runtime_verified': False}
            (self.evidence/'loading.json').write_text(json.dumps(metadata,indent=2)+'\n')
            print(json.dumps({'model_loading':metadata}), flush=True)
            return self
        except BaseException:
            self.close()
            raise

    def infer(self, item, index):
        if self.proc is None: raise RuntimeError('Load models first')
        events = self.evidence / f'{index:06d}.events.jsonl'
        start = time.perf_counter()  # Before audio IO, ASR, ToolEnv, all decisions and final hash.
        self.pipe.send((item, 'C', None, str(events)))
        if not self.pipe.poll(max(0, 30-(time.perf_counter()-start))):
            self.proc.kill()
            self.proc.join()
            raise TimeoutError('K exceeded 30 seconds; no fabricated output or second ToolEnv')
        kind, result = self.pipe.recv()
        seconds = time.perf_counter()-start
        if kind != 'result': raise RuntimeError(str(result))
        receipt = {'id':item['id'], 'index':index, 'dispatch_seconds':seconds, **result}
        (self.evidence/f'{index:06d}.result.json').write_text(json.dumps(receipt,ensure_ascii=False)+'\n')
        if seconds >= 30 or result['status'] in ('timeout','worker_error','inference_error'):
            raise RuntimeError('K request failed: '+str(result.get('error') or result['status']))
        prediction = result['prediction']
        if prediction['id'] != item['id'] or result['toolenv_instances'] != 1:
            raise RuntimeError('ToolEnv output integrity failure')
        output = {**prediction, 'time':int(seconds*1000)}
        print(json.dumps({'id':item['id'],'status':result['status'],'time_ms':output['time']}), flush=True)
        return output

    def close(self):
        if self.proc is not None:
            if self.proc.is_alive():
                try: self.pipe.send(None)
                except (OSError, EOFError): pass
                self.proc.join(10)
            if self.proc.is_alive(): self.proc.kill(); self.proc.join()
            self.pipe.close()
            self.proc = self.pipe = None
        self.stack.close()

    def __enter__(self): return self.load()
    def __exit__(self, *args): self.close()

def write_predictions(runtime, cases, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Do not leave a partial file named submission.jsonl after a failure.
    partial = output.with_suffix(output.suffix + '.partial')
    if output.exists(): raise FileExistsError(output)
    with partial.open('x', encoding='utf8') as f:
        for index, item in enumerate(cases):
            prediction = runtime.infer(item, index)
            f.write(json.dumps(prediction,ensure_ascii=False,separators=(',',':'))+'\n')
            f.flush()
        os.fsync(f.fileno())
    partial.replace(output)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-root', default='/data')
    parser.add_argument('--split')
    parser.add_argument('--output', default='/result/submission.jsonl')
    parser.add_argument('--limit', type=int, help='Local smoke tests only; omit for submission')
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0: parser.error('--limit must be positive')
    split = discover_split(args.data_root, args.split)
    cases = read_cases(args.data_root, split, args.limit)
    evidence = Path(args.output).parent / (Path(args.output).stem + '.diagnostics')
    with KRuntime(args.data_root, split, evidence) as runtime:
        write_predictions(runtime, cases, args.output)

if __name__ == '__main__': main()
