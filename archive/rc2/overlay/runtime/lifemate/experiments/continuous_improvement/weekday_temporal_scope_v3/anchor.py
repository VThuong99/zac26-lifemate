"""Explicit Vietnamese calendar-week dates derived from the local clock."""
import copy,datetime,json,re,unicodedata
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
DAY=r'(?:thứ\s+(?:hai|ba|tư|bốn|năm|sáu|bảy)|chủ\s+nhật)';WEEK=r'tuần\s+(?:sau|tới|này)';PAT=re.compile(r'(?<!\w)(?:'+DAY+r'\s+'+WEEK+r'|'+WEEK+r'\s+(?:vào\s+)?'+DAY+r')(?!\w)',re.I)
UNSAFE=re.compile(r'(?<!\w)(?:nếu|trừ|không|chưa|chẳng|đừng|chớ|hông|nhầm|lộn|sai|sửa|đổi|dời|hoãn|lùi|hoặc|hay|khoảng|tầm|gần|trước|sau|nữa|kia|mỗi)(?!\w)|(?<!\w)(?:hằng|hàng)\s+(?:ngày|tuần|tháng|năm|thứ|chủ)(?!\w)',re.I)
OTHER_DAY=re.compile(r'(?<!\w)(?:thứ\s+(?:hai|ba|tư|bốn|năm|sáu|bảy)|chủ\s+nhật|ngày\s+mai|hôm\s+nay|(?:sáng|trưa|chiều|tối|đêm)\s+(?:mai|nay)|hôm\s+qua|ngày\s+kia|mai|nay|mốt)(?!\w)|(?<!\d)\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?(?!\d)',re.I)
MAP={'hai':0,'ba':1,'tư':2,'bốn':2,'năm':3,'sáu':4,'bảy':5}
def anchors(text,context):
 if not isinstance(text,str) or not isinstance(context,dict):return []
 ms=list(PAT.finditer(text))
 if len(ms)!=1:return []
 m=ms[0];before=text[:m.start()];after=text[m.end():];outside=before+' '+after
 if re.search(r'(?<!\w)(?:sau|từ|đến|tới|qua|kể\s+từ|cho\s+đến)\s+(?:(?:sáng|trưa|chiều|tối|đêm)\s+)?$',before,re.I) or re.search(r'^\s*(?:trở\s+đi|về\s+sau)(?!\w)',after,re.I) or (re.search(r'(?<!\w)(?:hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|\d+)\s*$',before,re.I) and m.group().casefold().startswith('tuần')) or re.search(r'(?<!\d)(?:19|20)\d{2}(?!\d)',outside):return []
 if UNSAFE.search(outside) or OTHER_DAY.search(outside) or re.search(r'(?<!\w)(?:mùng|mồng|ngày)\s+(?:\d{1,2}|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười)(?!\w)',outside,re.I):return []
 try:
  now=datetime.datetime.fromisoformat(context['current_time'].replace('Z','+00:00'));tz=ZoneInfo(context['timezone'])
  if now.utcoffset() is None or now.utcoffset()!=now.astimezone(tz).utcoffset():return []
  local=now.astimezone(tz).date()
 except (ValueError,KeyError,TypeError,AttributeError,ZoneInfoNotFoundError):return []
 phrase=m.group().casefold();dm=re.search(r'thứ\s+(hai|ba|tư|bốn|năm|sáu|bảy)',phrase);weekday=MAP[dm.group(1)] if dm else 6;next_week=bool(re.search(r'tuần\s+(?:sau|tới)',phrase));monday=local-datetime.timedelta(days=local.weekday());day=monday+datetime.timedelta(days=weekday+(7 if next_week else 0));return [{'span':m.group(),'date':day.isoformat(),'timezone':context['timezone']}]
def intervene(req):
 q=copy.deepcopy(req);p=json.loads(q['messages'][1]['content']);out=anchors(p.get('user_request'),p.get('context'))
 if out:p['weekday_calendar_anchors']=out;q['messages'][1]['content']=json.dumps(p,ensure_ascii=False)
 return q
