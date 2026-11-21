"""Expose a strictly grounded wallet-vs-bill comparison at a single decision."""
import copy,json,re,unicodedata
TYPES={'electricity':r'\b(?:tiền điện|hóa đơn điện|hoá đơn điện)\b','water':r'\b(?:tiền nước|hóa đơn nước|hoá đơn nước)\b','internet':r'\b(?:tiền mạng|tiền internet|hóa đơn mạng|hoá đơn mạng)\b','tv':r'\b(?:tiền truyền hình|hóa đơn truyền hình|hoá đơn truyền hình)\b'}

def evidence(payload):
 u=unicodedata.normalize('NFC',payload.get('user_request','')).lower()
 if not re.search(r'\bbằng ví(?: điện tử)?\b',u):return None
 if not re.search(r'(?:ví\s+(?:mà\s+)?không đủ|(?:nếu\s+)?ví\s+thiếu)\s+thì\b[^,.!?]{0,60}\bngân hàng\b',u):return None
 if re.search(r'\b(?:đừng|không được|chớ|khỏi|trừ khi|hoặc|hay là|thay vì|nhầm|sửa lại)\b',u):return None
 kinds=[k for k,pattern in TYPES.items() if re.search(pattern,u)]
 if len(kinds)!=1:return None
 steps=[s for s in payload.get('previous_steps',[]) if isinstance(s,dict) and 'action' in s and 'result' in s]
 if len(steps)!=2:return None
 a,b=steps
 if a['action'].get('name')!='bill_payment.list_bills' or b['action'].get('name')!='ewallet.get_balance':return None
 ra,rb=a['result'],b['result']
 if not isinstance(ra,dict) or not isinstance(rb,dict) or ra.get('ok') is not True or rb.get('ok') is not True:return None
 balance=rb.get('balance');bills=ra.get('bills')
 if type(balance) is not int or balance<0 or not isinstance(bills,list):return None
 matches=[v for v in bills if isinstance(v,dict) and v.get('type')==kinds[0] and v.get('paid') is False]
 if len(matches)!=1:return None
 bill=matches[0];amount=bill.get('amount');bid=bill.get('id')
 if type(amount) is not int or amount<0 or not isinstance(bid,str) or not bid:return None
 return {'bill_id':bid,'bill_type':kinds[0],'bill_amount':amount,'wallet_balance':balance,'wallet_covers_bill':balance>=amount,'source_if_sufficient':'ewallet','source_if_insufficient':'bank'}

def intervene(request):
 q=copy.deepcopy(request)
 try:
  payload=json.loads(q['messages'][1]['content']);proof=evidence(payload)
  if proof is not None:
   payload['observed_bill_and_wallet_comparison']=proof
   q['messages'][1]['content']=json.dumps(payload,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return q
