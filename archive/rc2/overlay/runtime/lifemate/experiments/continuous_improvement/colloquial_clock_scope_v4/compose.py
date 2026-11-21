"""Conservatively expose colloquial clock readings only in clock contexts."""
import copy,json,re
from experiments.continuous_improvement.colloquial_clock_candidates_v2.compose import candidates as readings,CLOCK

DURATION=re.compile(r'(?<!\w)(?:trong|mất|suốt|liên tục|kéo\s+dài|thời\s+lượng|tổng\s+cộng|đợi|chờ)(?!\w)',re.I)
CLOCK_CUE=re.compile(r'(?<!\w)(?:lúc|vào\s+lúc|vào|hẹn)\s*$',re.I)
QUESTION=re.compile(r'(?<!\w)(?:mấy\s+giờ|giờ\s+nào|mấy\s+h|thời\s+gian\s+nào)(?!\w)',re.I)

def scoped(text,history):
 v=readings(text)
 if v is None or DURATION.search(text):return None
 match=CLOCK.search(text);before=text[:match.start()]
 explicit=bool(CLOCK_CUE.search(before))
 turns=history if isinstance(history,list) else []
 while turns and isinstance(turns[-1],dict) and 'action' in turns[-1] and 'result' in turns[-1] and 'role' not in turns[-1]:turns=turns[:-1]
 clarification=(not before.strip(' ,.!?') and bool(turns) and isinstance(turns[-1],dict) and turns[-1].get('role')=='assistant' and isinstance(turns[-1].get('text'),str) and bool(QUESTION.search(turns[-1]['text'])) and not DURATION.search(turns[-1]['text']))
 return v if explicit or clarification else None

def intervene(request):
 out=copy.deepcopy(request)
 try:
  msg=out['messages'][1]
  if msg.get('role')!='user':return out
  p=json.loads(msg['content'])
  if not isinstance(p,dict) or 'spoken_clock_candidates' in p:return out
  v=scoped(p.get('user_request'),p.get('previous_steps'))
  if v is not None:p['spoken_clock_candidates']=v;msg['content']=json.dumps(p,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return out
