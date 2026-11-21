"""Expose ambiguous 12-hour readings of literal Vietnamese colloquial clocks."""
import copy,json,re
H={'một':1,'hai':2,'ba':3,'bốn':4,'tư':4,'năm':5,'sáu':6,'bảy':7,'tám':8,'chín':9,'mười':10,'mười một':11,'mười hai':12}
M={'mười lăm':15,'hai lăm':25,'ba lăm':35,'bốn lăm':45,'năm lăm':55}
CLOCK=re.compile(r'(?<!\w)(?P<h>mười\s+(?:một|hai)|một|hai|ba|bốn|tư|năm|sáu|bảy|tám|chín|mười)\s+giờ\s+(?P<m>mười\s+lăm|hai\s+lăm|ba\s+lăm|bốn\s+lăm|năm\s+lăm)(?:\s+phút)?(?!\w)',re.I)
MARKER=re.compile(r'(?<!\w)(?:giờ|\d{1,2}\s*:\s*\d{2}|\d{1,2}\s*h\s*\d{0,2})(?!\w)',re.I)
UNSAFE=re.compile(r'(?<!\w)(?:không|chưa|chẳng|đừng|chớ|khỏi|hủy|huỷ|nhầm|sửa|thay|đổi|dời|lùi|hoãn|hoặc|hay|nhưng|chứ|trừ|khoảng|tầm|chừng|trước|sau|muộn|sớm|kém|nữa)(?!\w)',re.I)

def candidates(text):
 if not isinstance(text,str) or UNSAFE.search(text) or len(list(MARKER.finditer(text)))!=1:return None
 matches=list(CLOCK.finditer(text))
 if len(matches)!=1:return None
 match=matches[0];h=H[' '.join(match.group('h').casefold().split())];m=M[' '.join(match.group('m').casefold().split())]
 return {'spoken_span':match.group(0),'possible_24h_times':[f'{h%12:02d}:{m:02d}',f'{h%12+12:02d}:{m:02d}'],'basis':'literal clock in 12-hour form; choose daypart only from the original request and actual conversation; these are only times of day, retain the appropriate full date and timezone for timestamp arguments'}

def intervene(request):
 out=copy.deepcopy(request)
 try:
  msg=out['messages'][1]
  if msg.get('role')!='user':return out
  p=json.loads(msg['content'])
  if not isinstance(p,dict) or 'spoken_clock_candidates' in p:return out
  v=candidates(p.get('user_request'))
  if v is not None:p['spoken_clock_candidates']=v;msg['content']=json.dumps(p,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return out
