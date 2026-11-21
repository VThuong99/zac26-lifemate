"""Review invalid temporal argument formats without claiming a tool was run."""
import copy,json,re
from datetime import datetime
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from k_schema_helpers import format_ok,schema_error
GUIDANCE=('\n- A previous proposal failed local schema validation before execution. It was not sent to a tool and produced no tool observation. '
          'Reconsider only the invalid fields using the actual request and existing observations. Preserve all other arguments and the tool. '
          'Do not invent an unknown date, time, timezone or identifier. The field expected_format describes syntax, not an example value.')

def invalid_formats(action,tools):
 if not isinstance(action,dict) or action.get('type')!='call' or not isinstance(action.get('arguments'),dict):return {}
 t=next((x for x in tools if x.get('name')==action.get('name')),None)
 if not t:return {}
 props=t.get('parameters',{}).get('properties',{});out={}
 for k,v in action['arguments'].items():
  fmt=props.get(k,{}).get('format')
  if fmt in ('date','date-time','time') and v not in (None,'',[],{}) and not format_ok(v,fmt):out[k]=fmt
 return out

def review_request(request,action,tools):
 fields=invalid_formats(action,tools)
 if not fields:return None
 q=copy.deepcopy(request);payload=json.loads(q['messages'][1]['content']);payload['local_preflight']={'unexecuted_proposal':action,'invalid_argument_formats':fields};q['messages'][1]['content']=json.dumps(payload,ensure_ascii=False);q['messages'][0]['content']+=GUIDANCE;return q

def accept(original,secondary,tools,text,context):
 fields=invalid_formats(original,tools)
 if not fields or not isinstance(secondary,dict) or secondary.get('type')!='call' or secondary.get('name')!=original.get('name'):return False
 a=original['arguments'];b=secondary.get('arguments')
 if not isinstance(b,dict) or set(a)!=set(b) or any(a[k]!=b[k] for k in a if k not in fields):return False
 if schema_error(secondary['name'],b,tools,{t['name'] for t in tools}) is not None:return False
 # Do not guess missing time or move dates. One explicit normalized user clock is
 # required, and a supplied offset must agree with the actual context timezone.
 for k,fmt in fields.items():
  old=a[k];new=b[k]
  if not isinstance(old,str) or not isinstance(new,str):return False
  if fmt=='date-time':
   if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',old) or not new.startswith(old+'T'):return False
   clocks=set(re.findall(r'(?<!\d)([01]\d|2[0-3]):([0-5]\d)(?!\d)',text))
   if len(clocks)!=1 or new[11:16]!=':'.join(next(iter(clocks))):return False
   try:
    dt=datetime.fromisoformat(new.replace('Z','+00:00'));tz=ZoneInfo(context['timezone'])
    if dt.tzinfo is None or dt.utcoffset()!=dt.replace(tzinfo=tz).utcoffset():return False
   except (ValueError,KeyError,TypeError,ZoneInfoNotFoundError):return False
  else:
   # Other format conversions can discard a date or otherwise change meaning.
   return False
 return True
