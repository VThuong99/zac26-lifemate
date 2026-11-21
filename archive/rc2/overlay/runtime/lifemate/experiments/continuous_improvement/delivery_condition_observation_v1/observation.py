"""Summarize an unambiguous actual order status for conditional requests."""
import copy
import json
import re
import unicodedata
from experiments.continuous_improvement.temporal_chat_wallet_v1.compose import intervene as base

ORDER=re.compile(r'(?<!\w)đơn\s+([\wÀ-ỹ]+(?:\s+[\wÀ-ỹ]+){0,3}?)\s+(?:giao|đã|đang|chưa)(?!\w)',re.I)
CONDITION=re.compile(r'(?<!\w)(?:nếu|thì)(?!\w)',re.I)
STATUS_WORDS=re.compile(r'(?<!\w)(?:giao\s+rồi|đã\s+giao|chưa\s+giao)(?!\w)',re.I)
TEMPORAL=re.compile(r'(?<!\w)(?:hôm\s+qua|hôm\s+nay|sáng\s+nay|chiều\s+nay|tối\s+qua|hôm\s+trước|tuần\s+trước)(?!\w)',re.I)

def norm(s):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s).casefold()).strip() if isinstance(s,str) else ''

def evidence(payload):
    text=payload.get('user_request');steps=payload.get('previous_steps')
    if not isinstance(text,str) or not isinstance(steps,list):return None
    text=unicodedata.normalize('NFC',text)
    matches=list(ORDER.finditer(text))
    if len(matches)!=1 or not CONDITION.search(text) or not STATUS_WORDS.search(text) or TEMPORAL.search(text):return None
    phrase=norm(matches[0].group(1));tokens=phrase.split()
    if not 1<=len(tokens)<=4:return None
    last=None
    for i,x in enumerate(steps):
        if isinstance(x,dict) and isinstance(x.get('action'),dict) and x['action'].get('name')=='food_delivery.order_history':last=i
    if last is None:return None
    result=steps[last].get('result')
    if not isinstance(result,dict) or result.get('ok') is not True or not isinstance(result.get('orders'),list):return None
    for x in steps[last+1:]:
        if not isinstance(x,dict) or not isinstance(x.get('action'),dict):return None
        name=x['action'].get('name','')
        if name.startswith('food_delivery.') and name not in ('food_delivery.list_restaurants','food_delivery.get_menu'):return None
    found=[]
    for order in result['orders']:
        if not isinstance(order,dict) or not isinstance(order.get('items'),list):return None
        names=[z.get('name') for z in order['items'] if isinstance(z,dict) and isinstance(z.get('name'),str)]
        if any(re.search(r'(?<!\w)'+re.escape(phrase)+r'(?!\w)',norm(name)) for name in names):found.append((order,names))
    if len(found)!=1:return None
    order,names=found[0];status=order.get('status');identifier=order.get('id')
    if status not in ('delivered','placed','delivering') or not isinstance(identifier,str) or not identifier:return None
    return {'requested_item_phrase':phrase,'observed_order_id':identifier,'observed_matching_items':[n for n in names if re.search(r'(?<!\w)'+re.escape(phrase)+r'(?!\w)',norm(n))],'observed_status':status,'delivered':status=='delivered','guidance':'Đối chiếu điều kiện với trạng thái thực tế; chỉ thực hiện nhánh phù hợp và tiếp tục các yêu cầu khác.'}

def annotate(request):
    q=copy.deepcopy(request)
    try:
        p=json.loads(q['messages'][1]['content']);v=evidence(p)
        if v is not None:p['observed_delivery_condition']=v;q['messages'][1]['content']=json.dumps(p,ensure_ascii=False)
    except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
    return q

def intervene(request):return annotate(base(request))
