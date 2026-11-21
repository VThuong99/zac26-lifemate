"""Compose unchanged safe clock annotation and guarded date anchors."""
import copy,json
from experiments.p43_safe_temporal_itn.temporal import annotate
from experiments.continuous_improvement.date_anchor_conditional_v2.anchor import intervene as date_intervene

def apply_annotated_request(req):
 """Add date hints to a request whose latest transcript was already clock-annotated."""
 return date_intervene(req)

def compose_for_test(req):
 """Model the real two-stage ordering for contract checks, without modifying caller data."""
 q=copy.deepcopy(req);p=json.loads(q['messages'][1]['content']);p['user_request']=annotate(p['user_request'])['text'];q['messages'][1]['content']=json.dumps(p,ensure_ascii=False);return apply_annotated_request(q)
