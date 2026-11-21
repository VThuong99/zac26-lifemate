"""Decode only user clips containing literal digit sequences; fail closed on errors."""
import hashlib,time
from experiments.continuous_improvement.spoken_digit_evidence_q8_v1.compose import facts


def collect(item,root,split,text,history,recognizer,audio_path):
    seen={};evidence=[];independent={};sources=facts({'user_request':text,'previous_steps':history}) or []
    for source in dict.fromkeys(x['source'] for x in sources):
        if source=='current_user':relative=item.get('audio')
        elif source.startswith('user_history_'):
            try:
                turn=history[int(source.rsplit('_',1)[-1])]
                relative=turn.get('audio') if isinstance(turn,dict) and turn.get('role')=='user' else None
            except (ValueError,IndexError,TypeError):relative=None
        else:relative=None
        if not relative:
            evidence.append({'source':source,'audio':relative,'error':'no_user_audio'});continue
        try:
            path=audio_path(root,split,relative)
            if relative not in seen:
                start=time.perf_counter();z=recognizer.transcribe(path);sha=hashlib.sha256(path.read_bytes()).hexdigest()
                seen[relative]={'audio':relative,'audio_sha256':sha,'independent':z['text'],'seconds':time.perf_counter()-start}
            result={'source':source,**seen[relative]};independent[source]=result['independent'];evidence.append(result)
        except (OSError,ValueError,TypeError,KeyError,RuntimeError) as e:
            evidence.append({'source':source,'audio':relative,'error':type(e).__name__+': '+str(e)})
    return independent,evidence
