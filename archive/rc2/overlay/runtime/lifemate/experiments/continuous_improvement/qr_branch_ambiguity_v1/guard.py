"""Clarify an exact-name QR merchant with multiple observed branches."""
import re,unicodedata

def norm(s):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s).casefold()).strip() if isinstance(s,str) else ''
NUM=r'(?:không|một|mốt|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|chục|trăm|nghìn|ngàn|triệu|đồng|\d+)'

def request_matches(text,base):
 s=norm(text);b=norm(base)
 if not s or not b or len(b.split())<2:return False
 pattern=(r'^(?:(?:con|em|bạn)\s+ơi\s+)?(?:cô|tôi|anh|chị|em|mình|bác)\s+ăn\s+(?:ở\s+)?'+re.escape(b)+r'\s+xong\s+rồi\s+'
          r'(?:đừng\s+trừ\s+tiền\s+ngân\s+hàng(?:\s+(?:nhé|nha|ạ|con|em|cô))*)?\s*'
          r'(?:(?:con|em|bạn)\s+)?(?:thanh\s+toán|trả)\s+(?:cái\s+)?(?:mã\s+)?qr\s+(?:của\s+)?quán\s+(?:qua|bằng)\s+ví\s+'
          +NUM+r'(?:\s+'+NUM+r')*(?:\s+(?:nhé|nha|ạ|giúp|em|anh|chị|cô|con))*[\s.!?]*$')
 return bool(re.fullmatch(pattern,s,re.I))

def repair(text,prior_history,history,proposal,names):
 if not isinstance(text,str) or not isinstance(prior_history,list) or prior_history or not isinstance(history,list) or not isinstance(proposal,dict) or not isinstance(names,set):return None
 if proposal.get('type')!='call' or proposal.get('name')!='ewallet.pay_qr' or 'sys.ask_missing_info' not in names:return None
 args=proposal.get('arguments');merchant=args.get('merchant_id') if isinstance(args,dict) else None
 if not isinstance(merchant,str) or not merchant:return None
 reads=[z for z in history if isinstance(z,dict) and isinstance(z.get('action'),dict) and z['action'].get('name')=='food_delivery.list_restaurants']
 if len(reads)!=1 or reads[0]['action'].get('arguments')!={} or not isinstance(reads[0].get('result'),dict) or reads[0]['result'].get('ok') is not True:return None
 restaurants=reads[0]['result'].get('restaurants')
 if not isinstance(restaurants,list):return None
 groups={}
 for r in restaurants:
  if not isinstance(r,dict) or not isinstance(r.get('name'),str) or not isinstance(r.get('merchant_id'),str) or not r['merchant_id']:continue
  parts=re.split(r'\s+-\s+',r['name'],maxsplit=1)
  if len(parts)!=2 or not norm(parts[0]) or not norm(parts[1]):continue
  base=norm(parts[0]);groups.setdefault(base,[]).append((r['merchant_id'],norm(parts[1])))
 eligible=[]
 for base,entries in groups.items():
  mids={x[0] for x in entries};branches={x[1] for x in entries}
  if len(mids)<2 or len(branches)<2 or len(mids)!=len(branches) or merchant not in mids or not request_matches(text,base):continue
  eligible.append((base,sorted(mids)))
 if len(eligible)!=1:return None
 return {'kind':'clarify_observed_merchant_branches','action':{'type':'call','name':'sys.ask_missing_info','arguments':{'tool_name':'ewallet.pay_qr','params':['merchant_id']}},'spoken_base':eligible[0][0],'observed_merchant_ids':eligible[0][1]}
