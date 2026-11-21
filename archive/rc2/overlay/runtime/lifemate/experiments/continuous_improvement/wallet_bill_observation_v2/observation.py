"""Annotate only sufficient-wallet decisions with an affirmative bank fallback."""
import copy,json,re,unicodedata
from experiments.continuous_improvement.wallet_bill_observation_v1.observation import evidence as evidence_v1

def evidence(payload):
 p=evidence_v1(payload)
 if p is None or not p['wallet_covers_bill']:return None
 u=unicodedata.normalize('NFC',payload.get('user_request','')).lower()
 pay=re.search(r'\bbằng ví(?: điện tử)?\b',u)
 if not pay or re.search(r'\b(?:không|chưa|chẳng|tránh|thôi|hủy|huỷ)\b',u[:pay.start()]):return None
 m=re.search(r'(?:ví\s+(?:mà\s+)?không đủ|(?:nếu\s+)?ví\s+thiếu)\s+thì\b([^,.!?]{0,60})\bngân hàng\b',u)
 if not m or re.search(r'\b(?:không|chưa|đừng|chớ|khỏi|cấm|tránh|thôi|chẳng|hủy|huỷ)\b',m.group(1)):return None
 return p

def intervene(request):
 q=copy.deepcopy(request)
 try:
  payload=json.loads(q['messages'][1]['content']);proof=evidence(payload)
  if proof is not None:
   payload['observed_bill_and_wallet_comparison']=proof
   q['messages'][1]['content']=json.dumps(payload,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return q
