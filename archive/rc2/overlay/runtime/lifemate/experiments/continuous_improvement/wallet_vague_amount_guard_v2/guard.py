"""Clarify a vague wallet amount only after conservative history and alarm proof."""
import datetime as dt
import re,unicodedata

def norm(s):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s).casefold()).strip() if isinstance(s,str) else ''
MONEY=re.compile(r'\b(?:tiền|triệu|nghìn|ngàn|tỷ|vnd|usd|đồng|đô|dollar|euro|yên|bạc|số\s+dư|ví|chuyển\s+khoản|ewallet|banking|thanh\s+toán)\b|\d\s*(?:k|đ)\b',re.I)
MONEY_KEYS={'amount','balance','price','cost','currency','total','số_tiền','số_dư'}
PRONOUN=re.compile(r'\b(?:ảnh|anh\s+ấy|chị\s+ấy|cô\s+ấy|bác\s+ấy|ông\s+ấy|bà\s+ấy|họ|người\s+đó)\b',re.I)
BARE_NUMBER=re.compile(r'^(?:(?:không|một|mốt|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|trăm|lẻ|linh|\d+)(?:\s+|$))+(?:(?:nhé|nha|ạ|nghe))?$',re.I)
TITLES={'anh','chị','cô','bác','em','ông','bà','chú','dì','cậu','mợ','bố','ba','mẹ','má','tôi','mình','ấy','đó'}
TRANSFER=re.compile(r'^(?P<prefix>.*?)\bchuyển\s+ví\s+cho\s+(?P<recipient>[\w\s]{1,60}?)\s+(?:(?:một\s+)?(?:chút|ít))\s+tiền(?:\s+(?:nhé|nha|ạ|giúp|em|tôi|anh|chị))*[\s.!?]*$',re.I)
HOURS={'một':1,'hai':2,'ba':3,'bốn':4,'năm':5,'sáu':6,'bảy':7,'tám':8,'chín':9,'mười':10,'mười một':11,'mười hai':12}
NUM=r'(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười(?:\s+một|\s+hai)?|\d{1,2})'
PREFIX=re.compile(rf'^(?:(?:em|con|bạn)\s+ơi\s+)?(?:đặt|cài)\s+báo\s+thức\s+(?P<hour>{NUM})(?:\s+giờ(?:\s+(?P<half_after>rưỡi))?|\s+(?P<half_direct>rưỡi))\s+(?P<part>sáng|chiều|tối)\s+(?:mai|ngày\s+mai)(?:\s+cho\s+(?:em|anh|chị|tôi|mình))?(?:\s+(?:nhé|nha|ạ|giúp|em|tôi|anh|chị))*(?:\s+(?:rồi|với\s+lại|với|và))?$',re.I)
FILLER=re.compile(r'^(?:(?:em|con|bạn)\s+ơi)?$',re.I)

def history_may_supply_amount(value,name):
 if isinstance(value,str):
  s=norm(value)
  return bool(MONEY.search(s) or PRONOUN.search(s) or BARE_NUMBER.fullmatch(s) or (name and re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',s)))
 if isinstance(value,list):return any(history_may_supply_amount(x,name) for x in value)
 if isinstance(value,dict):return any(norm(str(k)) in MONEY_KEYS or history_may_supply_amount(v,name) for k,v in value.items())
 return False

def alarm_matches(prefix,context,history):
 m=PREFIX.fullmatch(prefix)
 if not m or not isinstance(context,dict):return False
 try:
  now=dt.datetime.fromisoformat(context['current_time']);assert context['timezone']=='Asia/Ho_Chi_Minh' and now.utcoffset()==dt.timedelta(hours=7)
  raw=norm(m.group('hour'));hour=int(raw) if raw.isdigit() else HOURS[raw];assert 1<=hour<=11
  if m.group('part') in ('chiều','tối'):hour+=12
  minute=30 if m.group('half_after') or m.group('half_direct') else 0
  expected=dt.datetime.combine(now.date()+dt.timedelta(days=1),dt.time(hour,minute),tzinfo=now.tzinfo)
  alarms=[z for z in history if isinstance(z,dict) and isinstance(z.get('action'),dict) and z['action'].get('name')=='alarm.create' and isinstance(z.get('result'),dict) and z['result'].get('ok') is True and isinstance(z['result'].get('item'),dict) and z['result']['item'].get('id')]
  assert len(alarms)==1
  item=alarms[0]['result']['item'];assert item.get('enabled') is not False and item.get('repeat') in (None,'once')
  actual=dt.datetime.fromisoformat(item['time']);assert actual.utcoffset()==now.utcoffset() and actual==expected
  return True
 except (KeyError,TypeError,ValueError,AssertionError):return False

def repair(text,context,prior_history,history,proposal,names):
 if not isinstance(text,str) or not isinstance(context,dict) or not isinstance(prior_history,list) or not isinstance(history,list) or not isinstance(proposal,dict) or not isinstance(names,set):return None
 if proposal.get('type')!='call' or proposal.get('name')!='ewallet.transfer' or 'sys.ask_missing_info' not in names:return None
 s=norm(text);m=TRANSFER.fullmatch(s)
 if not m:return None
 recipient=norm(m.group('recipient'));name=' '.join(w for w in recipient.split() if w not in TITLES)
 if not recipient or (prior_history and not name) or history_may_supply_amount(prior_history,name):return None
 prefix=norm(m.group('prefix')).strip(' ,;.!?')
 if MONEY.search(prefix):return None
 if PREFIX.fullmatch(prefix):
  if not alarm_matches(prefix,context,history):return None
 elif not FILLER.fullmatch(prefix):return None
 return {'kind':'ask_for_unspecified_transfer_amount','action':{'type':'call','name':'sys.ask_missing_info','arguments':{'tool_name':'ewallet.transfer','params':['amount']}}}
