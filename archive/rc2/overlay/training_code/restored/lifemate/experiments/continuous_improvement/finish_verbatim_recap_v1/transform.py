"""Append a verbatim user-request copy to a saved terminal-decision payload."""
import copy,json

def intervene(request):
 out=copy.deepcopy(request);payload=json.loads(out['messages'][1]['content'])
 if not isinstance(payload,dict) or not isinstance(payload.get('user_request'),str) or 'current_request_verbatim' in payload:return out,False
 payload['current_request_verbatim']=payload['user_request'];out['messages'][1]['content']=json.dumps(payload,ensure_ascii=False);return out,True
