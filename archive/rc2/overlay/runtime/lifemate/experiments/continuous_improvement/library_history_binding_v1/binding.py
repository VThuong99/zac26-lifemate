"""Conservative resolution of an explicitly selected large-print library edition."""
import re, unicodedata

def norm(x):
 return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', x).casefold()).strip() if isinstance(x,str) else ''

CURRENT=re.compile(r'^(?:ừ\s+đúng\s+rồi\s+)?(?:em\s+)?đặt\s+giữ\s+giúp\s+(?:chị|em|tôi|anh)\s+(?:cuốn|quyển)\s+(?:đấy|đó|này)(?:\s+(?:nhé|nhá|ạ))?[.!?]*$')
SELECTION=re.compile(r'^lấy\s+bản\s+chữ\s+lớn(?:\s|[,.!?]|$)')
CONFLICT=re.compile(r'\b(?:đừng|thôi|không(?!\s+nổi\b)|đổi|thay|nhưng|trừ|nếu|hoặc|hay\s+là)\b')
EDITION=re.compile(r'^(.*?)\s*\(\s*bản\s+chữ\s+lớn\s*\)$')

def derive(text,prior,steps,proposal,names):
 if not CURRENT.fullmatch(norm(text)) or 'library.reserve' not in names:return None
 if proposal!={'type':'call','name':'sys.ask_missing_info','arguments':{'tool_name':'library.reserve','params':['book_id']}}:return None
 if not isinstance(prior,list) or not isinstance(steps,list) or len(steps)!=1:return None
 users=[x for x in prior if isinstance(x,dict) and x.get('role')=='user']
 if not users:return None
 selected=norm(users[-1].get('audio_text') or users[-1].get('text'))
 if not SELECTION.match(selected) or CONFLICT.search(selected):return None
 s=steps[0];a=s.get('action',{});result=s.get('result',{})
 if a.get('type')!='call' or a.get('name')!='library.search' or not result.get('ok'):return None
 query=norm(a.get('arguments',{}).get('query'));books=result.get('books')
 if not query or not isinstance(books,list) or not books:return None
 ids=[x.get('id') for x in books if isinstance(x,dict)]
 if len(ids)!=len(books) or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):return None
 matches=[]
 for b in books:
  m=EDITION.fullmatch(norm(b.get('title')))
  if m and norm(m.group(1))==query and b.get('available') is True:matches.append(b)
 if len(matches)!=1:return None
 return {'action':{'type':'call','name':'library.reserve','arguments':{'book_id':matches[0]['id']}},'query':query,'selected_history':selected,'matched_title':matches[0]['title']}

def effect_confirmed(result,action):
 r=result.get('reservation',{}) if isinstance(result,dict) else {}
 return result.get('ok') is True and isinstance(r,dict) and bool(r.get('id')) and r.get('book_id')==action['arguments']['book_id'] and r.get('status') in ('ready','waiting')
