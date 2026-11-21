"""Stop one explicitly excluded branch after its positive branch actually succeeded."""
import re
import unicodedata
from experiments.continuous_improvement.delivery_condition_observation_v1.observation import evidence,norm

REQUEST=re.compile(r'^\s*nếu\s+đơn\s+.{1,60}?\s+giao\s+rồi\s+thì\s+đánh\s+dấu\s+(?:đã\s+)?xem\s+(?:cái\s+)?báo\s+chuông\s+(?:ở|tại)\s+cổng\s+không\s+thì\s+bật\s+báo\s+động\s+vắng\s+nhà(?:\s+giúp\s+(?:chị|anh|em|tôi|cô|chú))?(?:\s+(?:nhé|nha|nghe))?\s*[.!?]?\s*$',re.I)

def stop(text,steps,proposal):
    if not isinstance(text,str) or not isinstance(steps,list) or not isinstance(proposal,dict):return None
    if not REQUEST.fullmatch(unicodedata.normalize('NFC',text)):return None
    if proposal.get('type')!='call' or proposal.get('name')!='home_security.arm' or proposal.get('arguments')!={'mode':'away'}:return None
    status=evidence({'user_request':text,'previous_steps':steps})
    if status is None or status['delivered'] is not True:return None
    acknowledgments=[]
    for step in steps:
        if not isinstance(step,dict) or not isinstance(step.get('action'),dict):continue
        if step['action'].get('name')!='home_security.acknowledge_alert':continue
        result=step.get('result');item=result.get('item') if isinstance(result,dict) else None
        if isinstance(item,dict) and result.get('ok') is True and item.get('acknowledged') is True and norm(item.get('location'))=='cổng' and 'chuông' in norm(item.get('message')) and item.get('id')==step['action'].get('arguments',{}).get('alert_id'):
            acknowledgments.append(item['id'])
    if len(acknowledgments)!=1:return None
    return {'kind':'completed_positive_branch','observed_order_id':status['observed_order_id'],'observed_status':status['observed_status'],'acknowledged_alert_id':acknowledgments[0]}
