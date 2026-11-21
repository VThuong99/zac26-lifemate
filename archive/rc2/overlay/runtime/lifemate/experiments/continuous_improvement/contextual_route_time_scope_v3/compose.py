"""Derive clock-minus-route facts when an explicit earlier period scopes one bare clock."""
import copy,json,re
from experiments.p42_temporal_itn import temporal
from experiments.continuous_improvement.observed_route_arithmetic_v1.compose import evidence as original, time_math, _ARRIVAL, _CONDITIONAL
_PERIOD=re.compile(r'(?<!\w)(sáng|chiều|tối)\s+(nay|mai)(?!\w)',re.I)
_BARE=re.compile(r'(?<!\w)(?P<h>'+temporal._H+r')\s+giờ(?!\w)',re.I)
_FOLLOWING_MINUTE=re.compile(r'^\s+(?:rưỡi|kém|'+temporal._M+r'|\d+)(?!\w)',re.I)
_BEFORE=re.compile(r'(?<!\w)trước(?!\w)',re.I)
_OTHER_DATE=re.compile(r'(?<!\w)(?:nay|mai|mốt|hôm\s+qua|hôm\s+kia|ngày\s+\d{1,2}|thứ\s+(?:hai|ba|tư|năm|sáu|bảy|[2-7])|chủ\s+nhật|\d{1,2}[/-]\d{1,2})(?!\w)',re.I)

def evidence(payload):
 old=original(payload)
 if old is not None:return old
 if not isinstance(payload,dict):return None
 text=payload.get('user_request');steps=payload.get('previous_steps')
 if not isinstance(text,str) or not isinstance(steps,list) or not _ARRIVAL.search(text) or _CONDITIONAL.search(text):return None
 for n in temporal._NEGATION_OR_REVISION.finditer(text):
  if n.group(0).casefold()=='khỏi' and re.search(r'(?<!\w)ra\s*$',text[:n.start()],re.I):continue
  return None
 if re.search(r'(?<!\w)sớm(?!\w)',text,re.I):return None
 for m in _BEFORE.finditer(text):
  if not re.search(r'(?<!\w)giữ\s*$',text[:m.start()],re.I):return None
 periods=list(_PERIOD.finditer(text));bare=list(_BARE.finditer(text));markers=list(temporal._MARKERS.finditer(text))
 if len(periods)!=1 or len(bare)!=1 or len(markers)!=1 or periods[0].end()>bare[0].start() or temporal._ALT_TIME.search(text):return None
 # An extra date cue can belong to a different goal; never transfer the earlier period across it.
 if _OTHER_DATE.search(text[:periods[0].start()]+' '+text[periods[0].end():]):return None
 if len(re.findall(r'(?<!\w)(?:sáng|chiều|tối)(?!\w)',text,re.I))!=1:return None
 m=bare[0]
 if temporal._NUM_PREFIX.search(text[:m.start()]) or _FOLLOWING_MINUTE.search(text[m.end():]):return None
 one=temporal.annotate(m.group(0)+' '+periods[0].group(1));anns=one['annotations']
 if len(anns)!=1:return None
 actions=[s for s in steps if isinstance(s,dict) and isinstance(s.get('action'),dict)]
 if not actions or len([s for s in actions if s['action'].get('name')=='maps.get_route'])!=1:return None
 step=actions[-1];action=step['action'];result=step.get('result')
 if action.get('name')!='maps.get_route' or not isinstance(result,dict) or result.get('ok') is not True:return None
 route=result.get('route');args=action.get('arguments')
 if not isinstance(route,dict) or not isinstance(args,dict):return None
 duration=route.get('duration_min')
 if isinstance(duration,bool) or not isinstance(duration,int) or not 1<=duration<=1440:return None
 if any(not isinstance(args.get(k),str) or not args[k] or route.get(k)!=args[k] for k in ('origin','destination')):return None
 hh,mm=map(int,anns[0]['time'].split(':'))
 return {'clock_span':m.group(0),'explicit_earlier_period_span':periods[0].group(0),'clock_time':anns[0]['time'],'source_tool':'maps.get_route','route_origin':args['origin'],'route_destination':args['destination'],'observed_duration_minutes':duration,'clock_minus_route_duration':time_math(hh*60+mm-duration)}

def intervene(request):
 q=copy.deepcopy(request)
 try:
  p=json.loads(q['messages'][1]['content']);v=evidence(p)
  if v is not None:p['route_clock_arithmetic']=v;q['messages'][1]['content']=json.dumps(p,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return q
