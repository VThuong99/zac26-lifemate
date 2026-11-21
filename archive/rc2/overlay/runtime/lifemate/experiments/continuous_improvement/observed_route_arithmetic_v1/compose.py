"""Lossless, bounded arithmetic over one literal clock and one actual recent route."""
import copy,json,re
from experiments.p42_temporal_itn import temporal
_ARRIVAL=re.compile(r'(?<!\w)(?:đến|tới|có\s+mặt)(?!\w)',re.I)
_CONDITIONAL=re.compile(r'(?<!\w)(?:nếu|giả\s+sử|trừ\s+khi|hoặc|hay\s+là|nhầm|thay\s+vì)(?!\w)',re.I)
_NUM={'năm':5,'mười':10,'mười lăm':15,'hai mươi':20,'hai mươi lăm':25,'ba mươi':30,'bốn mươi lăm':45,'một':1,'hai':2,'ba':3}
_LEAD=re.compile(r'(?<!\w)(?P<cue>sớm|trước)\s+(?P<n>hai\s+mươi\s+lăm|bốn\s+mươi\s+lăm|mười\s+lăm|hai\s+mươi|ba\s+mươi|một|hai|ba|năm|mười|\d{1,3})\s+phút(?!\w)',re.I)
def time_math(total):
 day,minute=divmod(total,1440);return {'time':f'{minute//60:02d}:{minute%60:02d}','day_offset':day}
def evidence(payload):
 if not isinstance(payload,dict):return None
 text=payload.get('user_request');steps=payload.get('previous_steps')
 if not isinstance(text,str) or not isinstance(steps,list) or not _ARRIVAL.search(text) or _CONDITIONAL.search(text):return None
 for negation in temporal._NEGATION_OR_REVISION.finditer(text):
  if negation.group(0).casefold()=='khỏi' and re.search(r'(?<!\w)ra\s*$',text[:negation.start()],re.I):continue
  return None
 if len(list(temporal._MARKERS.finditer(text)))!=1 or len(list(temporal._TIME.finditer(text)))!=1 or temporal._ALT_TIME.search(text):return None
 match=next(temporal._TIME.finditer(text));one=temporal.annotate(match.group(0));anns=one['annotations']
 if len(anns)!=1:return None
 lead=list(_LEAD.finditer(text))
 if len(lead)>1:return None
 if re.search(r'(?<!\w)(?:sớm|trước)\b',text,re.I) and not lead:return None
 active=[s for s in steps if isinstance(s,dict) and 'action' in s]
 if not active or len([s for s in active if s.get('action',{}).get('name')=='maps.get_route'])!=1:return None
 last=active[-1];action=last.get('action');result=last.get('result')
 if action.get('name')!='maps.get_route' or not isinstance(result,dict) or result.get('ok') is not True:return None
 route=result.get('route');args=action.get('arguments')
 if not isinstance(route,dict) or not isinstance(args,dict):return None
 duration=route.get('duration_min')
 if isinstance(duration,bool) or not isinstance(duration,int) or not 1<=duration<=1440:return None
 if any(not isinstance(args.get(k),str) or not args[k] or route.get(k)!=args[k] for k in ('origin','destination')):return None
 hh,mm=map(int,anns[0]['time'].split(':'));clock=hh*60+mm
 out={'clock_span':match.group(0),'clock_time':anns[0]['time'],'source_tool':'maps.get_route','route_origin':args['origin'],'route_destination':args['destination'],'observed_duration_minutes':duration,'clock_minus_route_duration':time_math(clock-duration)}
 if lead:
  raw=' '.join(lead[0].group('n').casefold().split());n=int(raw) if raw.isdecimal() else _NUM.get(raw)
  if not isinstance(n,int) or not 1<=n<=180:return None
  out['early_or_before_span']=lead[0].group(0);out['literal_minutes']=n;out['clock_minus_literal_minutes_and_route_duration']=time_math(clock-n-duration)
 return out
def intervene(request):
 q=copy.deepcopy(request)
 try:
  payload=json.loads(q['messages'][1]['content']);v=evidence(payload)
  if v is not None:payload['route_clock_arithmetic']=v;q['messages'][1]['content']=json.dumps(payload,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return q
