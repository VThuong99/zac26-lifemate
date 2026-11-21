"""Route both Q8 candidate C and Q8 parent D through the same ASR logic."""
from experiments.continuous_improvement.max_entropy_asr_e2e_v1.runtime import Router
class _ASRStateView:
 def __init__(self,state):self.state=state
 def get(self,key,default=None):
  value=self.state.get(key,default)
  return 'C' if key=='arm' and value=='D' else value
 def __getitem__(self,key):return self.state[key]
 def __setitem__(self,key,value):self.state[key]=value
class ParentCompatibleRouter(Router):
 def __init__(self,state,p34,sidecars):super().__init__(_ASRStateView(state),p34,sidecars)
