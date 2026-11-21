"""Clarify two real historical QR merchants without rewriting speech or choosing one."""
import re,unicodedata

def norm(s):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s).casefold()).strip() if isinstance(s,str) else ''
REQUEST=re.compile(r'^(?:(?:rứa|vậy|thế)\s+)?(?:trả|thanh\s+toán)\s+(?:qua|bằng)\s+ví\s+(?:tiền\s+)?(?:ăn\s+trưa|bữa\s+trưa)\s+(?:chưa\s+trả|chưa\s+thanh\s+toán)\s+trong\s+ghi\s+chú\s+cho\s+quán\s+(?P<alias>[a-z]{6,30})(?:\s+(?:giùm|giúp|anh|chị|em|tôi|mình|nghe|nhé|nha|ạ))*[\s.!?]*$',re.I)
ID=re.compile(r'(?<!\w)mch_[a-z0-9]+(?!\w)',re.I)

def edit_distance(a,b):
 previous=list(range(len(b)+1))
 for i,x in enumerate(a,1):
  row=[i]
  for j,y in enumerate(b,1):row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
  previous=row
 return previous[-1]

def repair(text,prior_history,history,proposal,names):
 if not isinstance(text,str) or not isinstance(prior_history,list) or len(prior_history)<2 or not isinstance(history,list) or not isinstance(proposal,dict) or not isinstance(names,set):return None
 if proposal.get('type')!='call' or proposal.get('name')!='ewallet.pay_qr' or 'sys.ask_missing_info' not in names:return None
 m=REQUEST.fullmatch(norm(text));args=proposal.get('arguments');merchant=args.get('merchant_id') if isinstance(args,dict) else None
 if not m or not isinstance(merchant,str) or not merchant:return None
 if any(isinstance(z,dict) and isinstance(z.get('action'),dict) and z['action'].get('name')=='ewallet.pay_qr' for z in history):return None
 user,assistant=prior_history[-2:]
 if not isinstance(user,dict) or user.get('role')!='user' or not isinstance(assistant,dict) or assistant.get('role')!='assistant':return None
 prev=norm(user.get('audio_text') or user.get('text'));summary=norm(assistant.get('text'))
 if not re.search(r'\bqr\b',prev) or not re.search(r'\bquán\b',prev) or not re.search(r'\b(?:nhắn|gửi)\b',prev):return None
 calls=assistant.get('tool_calls');results=assistant.get('tool_results')
 if not isinstance(calls,list) or not isinstance(results,list) or len(calls)!=len(results):return None
 sources=[]
 for c,r in zip(calls,results):
  if isinstance(c,dict) and c.get('name')=='sms.read_recent' and c.get('arguments')=={} and isinstance(r,dict) and r.get('ok') is True and isinstance(r.get('messages'),list):sources.append(r['messages'])
 if len(sources)!=1:return None
 groups={}
 for msg in sources[0]:
  if not isinstance(msg,dict) or msg.get('direction')!='incoming':continue
  sender=norm(msg.get('sender'));content=msg.get('content')
  if not isinstance(content,str) or not re.search(r'\bqr\b',content,re.I):continue
  parts=sender.split();ids=ID.findall(content)
  if len(parts)<2 or len(ids)!=1:continue
  prefix=parts[0]
  if len(prefix)<6 or not prefix.isascii() or not prefix.isalpha() or not re.search(r'(?<!\w)'+re.escape(sender)+r'(?!\w)',summary):continue
  groups.setdefault(prefix,set()).add((sender,ids[0]))
 alias=m.group('alias').lower();eligible=[]
 for prefix,pairs in groups.items():
  mids={x[1] for x in pairs};senders={x[0] for x in pairs}
  if len(mids)<2 or len(mids)!=len(senders) or merchant not in mids:continue
  if alias[0]!=prefix[0] or alias[-1]!=prefix[-1] or abs(len(alias)-len(prefix))>2:continue
  distance=edit_distance(alias,prefix)
  if distance<=2:eligible.append((prefix,distance,sorted(mids)))
 if len(eligible)!=1:return None
 return {'kind':'clarify_two_historical_qr_merchants','action':{'type':'call','name':'sys.ask_missing_info','arguments':{'tool_name':'ewallet.pay_qr','params':['merchant_id']}},'raw_spoken_alias':alias,'observed_shared_prefix':eligible[0][0],'edit_distance':eligible[0][1],'observed_merchant_ids':eligible[0][2]}
