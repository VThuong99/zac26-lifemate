"""Exclude ambiguous pronouns from the v1 exact direct-chat binding."""
import copy,json
from experiments.continuous_improvement.unique_chat_binding_v1.binding import bind as original_bind,norm
GENERIC={'anh','chị','em','tôi','mình','bạn','cô','chú','bác','ông','bà','anh ấy','chị ấy','cô ấy','chú ấy','ông ấy','bà ấy','bạn ấy','người ấy','người đó','người này','ai đó','họ'}
def bind(payload):
 proof=original_bind(payload)
 if proof is None or norm(proof['user_named_chat']) in GENERIC:return None
 return proof
def intervene(req):
 q=copy.deepcopy(req)
 try:
  payload=json.loads(q['messages'][1]['content']);proof=bind(payload)
  if proof is not None:payload['observed_unique_chat_binding']=proof;q['messages'][1]['content']=json.dumps(payload,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(req)
 return q
