"""Block the wrong conditional transfer using a strictly grounded reminder."""
import datetime as dt
import re
from experiments.continuous_improvement.gold_price_comparison_v1.observation import evidence,normalize,PATTERN,ELSE
HOURS={'một':1,'hai':2,'ba':3,'bốn':4,'năm':5,'sáu':6,'bảy':7,'tám':8,'chín':9,'mười':10,'mười một':11,'mười hai':12}
HOUR=r'(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười(?:\s+một|\s+hai)?)'
TRUE=re.compile(rf'^(?:ngày\s+)?mai\s+(?P<hour>{HOUR})\s+giờ\s+(?P<part>sáng|chiều|tối)\s+nhắc\s+(?:tôi|mình|anh|chị|em|cô|bác)\s+(?P<content>(?:đi\s+)?bán\s+vàng)$',re.I)
EXTRA=re.compile(r'\b(?:và|rồi|nhưng|nếu|sau\s+đó|đồng\s+thời|ngoài\s+ra|thêm\s+nữa)\b',re.I)

def repair(text,context,history,proposal,names):
 if not isinstance(text,str) or not isinstance(context,dict) or not isinstance(history,list) or not isinstance(proposal,dict) or not isinstance(names,set):return None
 if proposal.get('type')!='call' or proposal.get('name')!='banking.transfer' or 'reminders.create' not in names:return None
 proof=evidence(text,history)
 if not proof or proof['điều_kiện_đúng'] is not True:return None
 s=normalize(text);matches=list(PATTERN.finditer(s));branches=list(ELSE.finditer(s))
 if len(matches)!=1 or len(branches)!=1:return None
 prefix=s[:matches[0].start()]
 if not re.fullmatch(r'(?:nếu\s+)?',prefix):return None
 yes=s[matches[0].end():branches[0].start()].strip(' ,.;:');no=s[branches[0].end():].strip(' ,.;:!?')
 if not no.startswith('chuyển ') or EXTRA.search(no):return None
 m=TRUE.fullmatch(yes)
 if not m:return None
 try:
  now=dt.datetime.fromisoformat(context['current_time']);assert context['timezone']=='Asia/Ho_Chi_Minh' and now.utcoffset()==dt.timedelta(hours=7)
  hour=HOURS[normalize(m.group('hour'))];part=normalize(m.group('part'))
  if part=='sáng':assert 1<=hour<=11
  else:assert 1<=hour<=11;hour+=12
  tomorrow=now.date()+dt.timedelta(days=1);when=dt.datetime.combine(tomorrow,dt.time(hour=hour),tzinfo=now.tzinfo)
  assert when>now
 except (KeyError,TypeError,ValueError,AssertionError):return None
 content=normalize(m.group('content'));timestamp=when.isoformat(timespec='seconds')
 reminders=[z for z in history if isinstance(z,dict) and isinstance(z.get('action'),dict) and z['action'].get('name')=='reminders.create']
 if reminders:
  if len(reminders)!=1:return None
  item=reminders[0].get('result',{}).get('item',{})
  if not isinstance(item,dict) or normalize(item.get('content'))!=content or item.get('time')!=timestamp or reminders[0].get('result',{}).get('ok') is not True:return None
  return {'kind':'stop_wrong_transfer_after_observed_reminder','action':{'type':'finish'},'reminder_id':item.get('id')}
 return {'kind':'substitute_grounded_true_branch_reminder','action':{'type':'call','name':'reminders.create','arguments':{'content':content,'time':timestamp}},'price_comparison':proof}
