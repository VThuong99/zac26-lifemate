"""Clarify an ambiguous callback from a real current missed-call list."""
import re,unicodedata

def norm(s):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s).casefold()).strip() if isinstance(s,str) else ''
REQUEST=re.compile(r'^(?:(?:lúc|hồi)\s+(?:đi\s+)?ăn\s+trưa\s+(?:anh|chị|em|tôi|mình)\s+để\s+máy\s+im\s+lặng\s+)?(?:(?:em|con|bạn)\s+)?(?:coi|xem|kiểm\s+tra)\s+(?:ai|người\s+nào)\s+(?:đã\s+)?gọi\s+nhỡ\s+rồi\s+gọi\s+lại\s+(?:giùm|giúp|hộ)\s+(?:anh|chị|em|tôi|mình)(?:\s+chắc\s+họ\s+gọi\s+(?:confirm|xác\s+nhận)\s+(?:lịch|hẹn))?[\s.!?]*$',re.I)
PRIOR_REFERENCE=re.compile(r'\b(?:gọi\s+nhỡ|gọi\s+lại|cuộc\s+gọi\s+nhỡ|người\s+đó|người\s+ấy)\b',re.I)
TITLES={'anh','chị','cô','bác','em','ông','bà','chú','dì','cậu','mợ','sếp','vợ','chồng','mẹ','bố','ba','má'}

def prior_may_identify(value,terms):
 if isinstance(value,str):
  s=norm(value)
  return bool(PRIOR_REFERENCE.search(s) or any(re.search(r'(?<!\w)'+re.escape(t)+r'(?!\w)',s) for t in terms if t))
 if isinstance(value,list):return any(prior_may_identify(x,terms) for x in value)
 if isinstance(value,dict):return any(prior_may_identify(v,terms) for k,v in value.items() if k not in ('chats','contacts','audio'))
 return False

def repair(text,prior_history,history,proposal,names):
 if not isinstance(text,str) or not isinstance(prior_history,list) or not isinstance(history,list) or not isinstance(proposal,dict) or not isinstance(names,set):return None
 if proposal.get('type')!='call' or proposal.get('name')!='phone.call' or 'sys.ask_missing_info' not in names or not REQUEST.fullmatch(norm(text)):return None
 if any(isinstance(z,dict) and isinstance(z.get('action'),dict) and z['action'].get('name')=='phone.call' for z in history):return None
 reads=[z for z in history if isinstance(z,dict) and isinstance(z.get('action'),dict) and z['action'].get('name')=='phone.recent_calls' and isinstance(z.get('result'),dict) and z['result'].get('ok') is True]
 if len(reads)!=1 or not isinstance(reads[0]['result'].get('calls'),list):return None
 missed=[c for c in reads[0]['result']['calls'] if isinstance(c,dict) and c.get('direction')=='incoming' and c.get('status')=='missed']
 if any(not isinstance(c.get('contact_id'),str) or not c['contact_id'] or not isinstance(c.get('phone_number'),str) or not re.fullmatch(r'\d{7,15}',c['phone_number']) for c in missed):return None
 pairs={(c['contact_id'],c['phone_number']) for c in missed};ids={x[0] for x in pairs};phones={x[1] for x in pairs}
 if len(pairs)<2 or len(ids)!=len(pairs) or len(phones)!=len(pairs):return None
 args=proposal.get('arguments')
 if not isinstance(args,dict):return None
 id_=args.get('contact_id');phone=args.get('phone_number')
 if id_ is None and phone is None:return None
 if not any((id_ is None or id_==a) and (phone is None or phone==b) for a,b in pairs):return None
 terms=set(phones)
 for c in missed:
  name=norm(c.get('name'));parts=[w for w in name.split() if w not in TITLES]
  if parts:terms.add(' '.join(parts))
 if prior_may_identify(prior_history,terms):return None
 return {'kind':'clarify_multiple_distinct_missed_callers','action':{'type':'call','name':'sys.ask_missing_info','arguments':{'tool_name':'phone.call','params':['contact_id']}},'observed_distinct_callers':len(pairs)}
