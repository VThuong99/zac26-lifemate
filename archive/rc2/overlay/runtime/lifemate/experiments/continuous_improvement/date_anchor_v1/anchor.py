"""Conservative source-span date hints; no tool arguments or transcript rewrites."""
import copy,datetime,json,re
# Avoid ambiguous speech repairs, negation, alternatives, ranges and approximations.
UNSAFE=re.compile(r'(?<!\w)(?:không|chưa|chẳng|đừng|chớ|hông|hổng|khum|nhầm|sai|sửa|đổi|dời|hoãn|lùi|nói\s+lại|ý\s+là|thay\s+vì|nhưng|chứ|hoặc|hay|từ|đến|tới|trước|sau|khoảng|tầm|gần|chừng|trừ)(?!\w)',re.I)
# Bare "mai" is allowed only at the beginning of the utterance followed by a clock.
CUES=re.compile(r'(?<!\w)(?:ngày\s+mai|hôm\s+nay|ngày\s+hôm\s+nay|(?:sáng|trưa|chiều|tối|đêm)\s+(?:mai|nay)|mai(?=\s+(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|\d{1,2})\s+giờ))(?!\w)',re.I)
CONFLICTING_DAYPART=re.compile(r'(?<!\w)(?:sáng|trưa|chiều|tối|đêm)\s+(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|lăm|\d+)(?:\s+(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|lăm|\d+))*\s+(?:sáng|trưa|chiều|tối|đêm)(?!\w)',re.I)
def anchors(text,current_time):
 if not isinstance(text,str) or not isinstance(current_time,str) or UNSAFE.search(text) or CONFLICTING_DAYPART.search(text):return []
 try:
  clock=datetime.datetime.fromisoformat(current_time)
  if clock.utcoffset() is None:return []
 except (ValueError,TypeError):return []
 out=[]
 for m in CUES.finditer(text):
  span=m.group();low=' '.join(span.casefold().split())
  if low=='mai' and text[:m.start()].strip():continue
  day=clock.date()+datetime.timedelta(days=1 if low.endswith('mai') else 0)
  out.append({'span':span,'date':day.isoformat()})
 return out

def intervene(req):
 q=copy.deepcopy(req);p=json.loads(q['messages'][1]['content']);items=anchors(p['user_request'],p.get('context',{}).get('current_time'))
 if items:p['relative_date_anchors']=items;q['messages'][1]['content']=json.dumps(p,ensure_ascii=False)
 return q
