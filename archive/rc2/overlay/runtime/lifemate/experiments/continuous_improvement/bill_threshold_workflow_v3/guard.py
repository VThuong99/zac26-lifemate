"""Bounded bank-bill workflow using only explicit scope and real tool effects."""
import datetime as dt
import re,unicodedata

def norm(s):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s).casefold()).strip() if isinstance(s,str) else ''
DIGITS={'một':1,'hai':2,'ba':3,'bốn':4,'năm':5,'sáu':6,'bảy':7,'tám':8,'chín':9}
NUM=r'(?:một|hai|ba|bốn|năm|sáu|bảy|tám|chín)'
BILL=re.compile(r'\b(?:hóa|hoá)\s+đơn\b|\b(?:mấy|các|những|tất\s+cả)\s+(?:cái\s+)?đơn(?!\s+hàng)(?:\s+hợp)?\b',re.I)
WINDOW=re.compile(rf'\btrong(?:\s+vòng)?\s+(?P<days>{NUM})\s+ngày\s+tới\b',re.I)
HIGH=re.compile(rf'\b(?:cái|(?:hóa|hoá)\s+đơn|đơn)(?:\s+nào)?\s+(?:(?:nhiều|cao)\s+hơn|hơn|trên|quá|vượt)\s+(?P<hundreds>{NUM})\s+trăm\s+(?:nghìn|ngàn)\s+thì\s+(?P<tail>.*)$',re.I)
EXCLUSION=re.compile(r'^(?:(?:cứ\s+)?(?:để|giữ)(?:\s+(?:lại|đấy|đó|đã|chưa|trả)){{1,5}}|(?:khoan|đừng|không|chưa)\s+(?:trả|để)(?:\s+(?:lại|đấy|đó|đã|chưa|trả)){{0,5}})(?:\s+(?:nhé|nha|ạ|nghe|đi|giúp|em|anh|chị|tôi|mình))*[\s.!?]*$',re.I)
# The regex above is a raw literal rather than an f-string.
EXCLUSION=re.compile(EXCLUSION.pattern.replace('{{','{').replace('}}','}'),re.I)
ALLOWED_PREFIX=set('mấy các những tất cả toàn bộ hóa hoá đơn cái hợp hạn đến tới trong vòng ngày thì trả thanh toán bằng qua dùng ngân hàng hết luôn đi giúp cho tôi em anh chị mình nhé nha ạ nghe mà riêng trừ còn nào một hai ba bốn năm sáu bảy tám chín'.split())
EXTRA=re.compile(r'\b(?:nếu|chỉ\s+khi|hoặc|nhầm|nhắn|gọi|nhắc|bật|tắt|đặt|hủy|huỷ|chuyển|tạo|lưu|mua|đổi\s+ý|khoá|khóa|rồi|xong|và|xem|kiểm\s+tra|thời\s+tiết|báo\s+thức)\b',re.I)

def request_scope(text):
 s=norm(text)
 if not s or EXTRA.search(s) or len(list(BILL.finditer(s)))<1:return None
 windows=list(WINDOW.finditer(s));highs=list(HIGH.finditer(s))
 if len(windows)!=1 or len(highs)!=1 or not EXCLUSION.fullmatch(highs[0].group('tail')):return None
 h=highs[0];before=s[:h.start()]
 if any(token not in ALLOWED_PREFIX for token in re.findall(r'\w+',before)):return None
 if not re.search(r'\b(?:mấy|các|những|tất\s+cả|toàn\s+bộ|hết|nào)\b',before):return None
 if re.search(r'\b(?:đã\s+trả|đã\s+thanh\s+toán|bao\s+nhiêu)\b',before):return None
 bank=list(re.finditer(r'\bngân\s+hàng\b',before))
 if len(bank)!=1 or not re.search(r'\b(?:trả|thanh\s+toán)\b',before):return None
 if re.search(r'\b(?:không|đừng|chớ|khỏi|tránh|chưa)\b',before[max(0,bank[0].start()-45):bank[0].start()]):return None
 if re.search(r'\b(?:ít\s+hơn|dưới|không\s+quá|từ)\b',before[max(0,h.start()-35):]):return None
 return {'days':DIGITS[windows[0].group('days')],'maximum':DIGITS[h.group('hundreds')]*100000}

def evidence(text,context,history):
 scope=request_scope(text)
 if scope is None or not isinstance(context,dict) or not isinstance(history,list):return None
 try:
  now=dt.datetime.fromisoformat(context['current_time']);assert context['timezone']=='Asia/Ho_Chi_Minh' and now.utcoffset()==dt.timedelta(hours=7)
  today=now.date();end=today+dt.timedelta(days=scope['days'])
 except (KeyError,TypeError,ValueError,AssertionError):return None
 reads=[(i,z) for i,z in enumerate(history) if isinstance(z,dict) and isinstance(z.get('action'),dict) and z['action'].get('name')=='bill_payment.list_bills']
 if len(reads)!=1:return None
 idx,step=reads[0];act=step['action'];result=step.get('result')
 if act.get('arguments')!={} or not isinstance(result,dict) or result.get('ok') is not True or not isinstance(result.get('bills'),list):return None
 bills={}
 try:
  for b in result['bills']:
   assert isinstance(b,dict) and isinstance(b.get('id'),str) and b['id'] and b['id'] not in bills
   assert isinstance(b.get('amount'),int) and not isinstance(b['amount'],bool) and b['amount']>=0 and b.get('paid') is False
   due=dt.date.fromisoformat(b['due_date']);assert due not in (today,end)
   bills[b['id']]={'id':b['id'],'amount':b['amount'],'due_date':due.isoformat()}
 except (KeyError,TypeError,ValueError,AssertionError):return None
 eligible={i:b for i,b in bills.items() if today<dt.date.fromisoformat(b['due_date'])<end and b['amount']<=scope['maximum']}
 if len(eligible)>5:return None
 completed=set();failed=False;waiting=False;ambiguous_history=False
 for z in history[:idx]:
  if not isinstance(z,dict) or not isinstance(z.get('action'),dict):ambiguous_history=True;continue
  name=z['action'].get('name')
  if name=='sys.ask_missing_info':waiting=True
  elif name!='banking.get_balance':ambiguous_history=True
 for z in history[idx+1:]:
  if not isinstance(z,dict) or not isinstance(z.get('action'),dict):ambiguous_history=True;continue
  a=z['action'];r=z.get('result');name=a.get('name')
  if name=='sys.ask_missing_info':waiting=True;continue
  if name in ('banking.get_balance',):continue
  if name!='bill_payment.pay' or not isinstance(a.get('arguments'),dict) or not isinstance(r,dict):ambiguous_history=True;continue
  args=a['arguments'];bid=args.get('bill_id');item=r.get('bill')
  if bid not in eligible or args.get('source')!='bank' or bid in completed:ambiguous_history=True;continue
  if r.get('ok') is not True or not isinstance(item,dict) or item.get('id')!=bid or item.get('paid') is not True or item.get('paid_with')!='bank' or item.get('amount')!=eligible[bid]['amount']:
   failed=True;continue
  completed.add(bid)
 remaining=sorted((b for i,b in eligible.items() if i not in completed),key=lambda x:(x['due_date'],x['id']))
 return {'days':scope['days'],'maximum':scope['maximum'],'eligible_ids':sorted(eligible),'completed_ids':sorted(completed),'remaining':remaining,'failed_effect':failed,'waiting_for_user':waiting,'ambiguous_history':ambiguous_history}

def repair(text,context,history,proposal,names):
 if not isinstance(proposal,dict) or not isinstance(names,set) or 'bill_payment.pay' not in names:return None
 if proposal.get('type') not in ('finish','call'):return None
 if proposal.get('type')=='call' and proposal.get('name')!='bill_payment.pay':return None
 proof=evidence(text,context,history)
 if proof is None:return None
 if proof['failed_effect'] or proof['waiting_for_user'] or proof['ambiguous_history']:
  if proposal.get('type')=='call':return {'kind':'stop_after_unverified_effect_or_clarification','action':{'type':'finish'},'proof':proof}
  return None
 remaining=proof['remaining']
 if proposal.get('type')=='finish':
  if not remaining:return None
 elif remaining:
  args=proposal.get('arguments')
  if isinstance(args,dict) and set(args)=={'bill_id','source'} and args['bill_id'] in {x['id'] for x in remaining} and args['source']=='bank':return None
 else:return {'kind':'stop_excluded_bill_payment','action':{'type':'finish'},'proof':proof}
 return {'kind':'pay_next_observed_eligible_bill','action':{'type':'call','name':'bill_payment.pay','arguments':{'bill_id':remaining[0]['id'],'source':'bank'}},'proof':proof}
