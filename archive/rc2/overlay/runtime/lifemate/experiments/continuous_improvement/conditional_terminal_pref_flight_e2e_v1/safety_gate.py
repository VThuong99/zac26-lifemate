"""Evaluation-only stop if genuine preflight observations or action drift."""
import copy

def clip_identity(clips):return [(x['history_index'],x['audio'],x['text']) for x in clips]
def install(controller_class,kinds,state,approved):
 original=controller_class.execute
 def execute(self,action):
  if isinstance(action,dict) and kinds.get(action.get('name'))=='read':
   result=original(self,action);state.setdefault('preflight_reads',[]).append({'action':copy.deepcopy(action),'result':copy.deepcopy(result)});return result
  expected=approved.get(state.get('current_id'));checks={'case_present':isinstance(expected,dict),'first_nonread':state.get('preflight_mutations',0)==0}
  if isinstance(expected,dict):checks.update(audio=clip_identity(state.get('current_clips',[]))==[tuple(x) for x in expected['clips']],reads=state.get('preflight_reads',[])==expected['reads'],action=action==expected['action'])
  allowed=all(checks.values());state.setdefault('safety_events',[]).append({'action':copy.deepcopy(action),'checks':checks,'allowed':allowed})
  if not allowed:raise RuntimeError('LIFEMATE_PREFLIGHT_GATE_STOP')
  state['preflight_mutations']=state.get('preflight_mutations',0)+1;return original(self,action)
 controller_class.execute=execute;return original
