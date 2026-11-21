"""Require literal, recent conversation evidence before a date-time repair."""
import re
from datetime import date,datetime
from experiments.continuous_improvement.schema_feedback_review_v1.policy import invalid_formats,review_request,accept as base_accept
NEGATION=re.compile(r'(?<!\w)(?:không|đừng|chớ|nếu|trừ|nhầm|sửa|khoan)(?!\w)',re.I)
REFERENCE=re.compile(r'(?<!\w)(?:đó|đấy|ấy|kia|vừa|lúc\s+nãy|như\s+cũ|trước\s+đó|(?:ngày|hôm|lúc)\b.{0,24}\bhẹn)(?!\w)',re.I)

def date_grounded(value,text,context,history):
 try:
  target=date.fromisoformat(value);now=datetime.fromisoformat(context['current_time'].replace('Z','+00:00')).date()
 except (ValueError,TypeError,KeyError,AttributeError):return False
 if not isinstance(text,str) or not isinstance(history,list) or NEGATION.search(text):return False
 sources=[text]
 # Use historical assistant text only when the current request points back and
 # the last conversational turn is a complete assistant reply.
 turns=[x for x in history if isinstance(x,dict) and x.get('role') in ('user','assistant')]
 if REFERENCE.search(text) and len(turns)>=2 and turns[-1].get('role')=='assistant' and turns[-2].get('role')=='user':
  latest=turns[-1].get('text')
  if isinstance(latest,str) and latest.strip() and not NEGATION.search(latest):sources.append(latest)
 for source in sources:
  if re.search(r'(?<!\d)'+re.escape(value)+r'(?!\d)',source):return True
  for m in re.finditer(r'(?<!\d)(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?(?![\d/-])',source):
   day,month,year=m.groups()
   if int(day)!=target.day or int(month)!=target.month:continue
   if year is not None and int(year)==target.year:return True
   if year is None and target.year==now.year and target.month==now.month:return True
 return False

def accept(original,secondary,tools,text,context,history):
 if not base_accept(original,secondary,tools,text,context):return False
 fields=invalid_formats(original,tools)
 return bool(fields) and all(fmt=='date-time' and date_grounded(original['arguments'][k],text,context,history) for k,fmt in fields.items())
