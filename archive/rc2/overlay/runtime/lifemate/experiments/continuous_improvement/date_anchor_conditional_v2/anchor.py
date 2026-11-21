"""Preserve P34 on requests expressing conditions; otherwise reuse date v1."""
import copy,json,re,unicodedata
from experiments.continuous_improvement.date_anchor_v1.anchor import intervene as base
CONDITIONAL=re.compile(r'(?<!\w)(?:nếu|thì|khi|trừ\s+khi|chỉ\s+khi|miễn\s+là|trường\s+hợp|hễ|giả\s+sử|tùy|tùy\s+theo|mà)(?!\w)',re.I)
def intervene(req):
 payload=json.loads(req['messages'][1]['content']);text=payload.get('user_request')
 if not isinstance(text,str) or CONDITIONAL.search(unicodedata.normalize('NFC',text)):return copy.deepcopy(req)
 return base(req)
