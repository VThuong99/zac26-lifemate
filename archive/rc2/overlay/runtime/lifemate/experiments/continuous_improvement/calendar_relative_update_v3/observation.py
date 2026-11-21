"""Expose a uniquely grounded explicit relative shift of an actual calendar event."""
import copy,json,re,unicodedata
from datetime import datetime,timedelta
AMOUNTS={'một tiếng rưỡi':90,'hai tiếng rưỡi':150,'nửa tiếng':30,'ba mươi phút':30,'một tiếng':60,'hai tiếng':120,'sáu mươi phút':60,'bốn mươi lăm phút':45,'bốn lăm phút':45}
UNIT='|'.join(sorted((re.escape(s) for s in AMOUNTS),key=len,reverse=True))
PAT=re.compile(rf'\b(?:dời|lùi|đẩy|chuyển)\b[^,.!?]{{0,100}}?\b(muộn|trễ|sớm)\b(?:\s+(?:lại|hơn|thêm|lên|đi))?\s+({UNIT})\b')
def norm(x):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',x).casefold()).strip() if isinstance(x,str) else ''
def evidence(payload):
 u=norm(payload.get('user_request',''))
 if re.search(r'\b(?:nếu|không|đừng|chớ|hoặc|trừ khi|thay vì|nhầm|khoan|chưa|hổng)\b',u):return None
 matches=list(PAT.finditer(u))
 if len(matches)!=1:return None
 tail=u[matches[0].end():]
 if tail.strip() and not re.match(r'\s*(?:[.!?]+\s*$|[,;:]*\s*(?:nhé|nha|ạ|giùm|giúp|hộ|tôi|em|anh|chị|mình|đi|rồi|xong|đặt|nhắn|gửi|báo|và)\b)',tail):return None
 if re.match(r'\s+(?:rưỡi|và\s+(?:nửa|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|[0-9]+)|(?:[0-9]+|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười)(?:\s+(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|lăm|mươi)){0,2}\s+(?:phút|giờ|tiếng))\b',tail):return None
 direction,amount=matches[0].groups();minutes=AMOUNTS[amount]*(1 if direction in ('muộn','trễ') else -1)
 steps=[s for s in payload.get('previous_steps',[]) if isinstance(s,dict) and isinstance(s.get('action'),dict) and isinstance(s.get('result'),dict)]
 if not steps or steps[-1]['action'].get('name')!='calendar.list_events':return None
 lists=[s for s in steps if s['action'].get('name')=='calendar.list_events']
 if len(lists)!=1:return None
 result=lists[0]['result'];events=result.get('events')
 if result.get('ok') is not True or not isinstance(events,list):return None
 candidates=[]
 for e in events:
  if not isinstance(e,dict) or e.get('status') in ('cancelled','canceled'):continue
  title=norm(e.get('title'));eid=e.get('id')
  if len(title)<4 or not isinstance(eid,str) or not eid:continue
  if re.search(r'(?<!\w)'+re.escape(title)+r'(?!\w)',u):candidates.append(e)
 if len(candidates)!=1:return None
 event=candidates[0]
 try:
  start=datetime.fromisoformat(event['start']);end=datetime.fromisoformat(event['end'])
  if start.tzinfo is None or end.tzinfo is None or start.utcoffset()!=end.utcoffset() or end<=start:return None
  new_start=start+timedelta(minutes=minutes);new_end=end+timedelta(minutes=minutes)
 except (KeyError,TypeError,ValueError,OverflowError):return None
 return {'observed_event_id':event['id'],'observed_title':event['title'],'observed_start':event['start'],'observed_end':event['end'],'requested_relative_minutes':minutes,'calculated_start':new_start.isoformat(timespec='seconds'),'calculated_end':new_end.isoformat(timespec='seconds'),'source':'Giờ mới được tính từ sự kiện duy nhất trong kết quả lịch và độ dời người dùng nói.'}

def intervene(request):
 q=copy.deepcopy(request)
 try:
  p=json.loads(q['messages'][1]['content']);v=evidence(p)
  if v:p['observed_relative_calendar_shift']=v;q['messages'][1]['content']=json.dumps(p,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return q
