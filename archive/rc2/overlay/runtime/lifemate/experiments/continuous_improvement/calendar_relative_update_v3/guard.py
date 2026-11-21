"""Correct only proposed relative calendar updates justified by an actual event."""
import copy
from experiments.continuous_improvement.calendar_relative_update_v3.observation import evidence

def repair(text,steps,proposal,names):
 if not isinstance(proposal,dict) or proposal.get('type')!='call' or proposal.get('name')!='calendar.update_event' or 'calendar.update_event' not in names:return None
 args=proposal.get('arguments')
 if not isinstance(args,dict) or set(args)!={'event_id','start','end'}:return None
 proof=evidence({'user_request':text,'previous_steps':steps})
 if proof is None or args['event_id']!=proof['observed_event_id']:return None
 desired={'event_id':proof['observed_event_id'],'start':proof['calculated_start'],'end':proof['calculated_end']}
 if args==desired:return None
 return {'action':{'type':'call','name':'calendar.update_event','arguments':desired},'kind':'calendar_shift','reason':'explicit relative offset from uniquely observed calendar event','observed_start':proof['observed_start'],'observed_end':proof['observed_end'],'requested_relative_minutes':proof['requested_relative_minutes']}

def confirmed(replacement,result):
 if replacement.get('kind')!='calendar_shift':return True
 if not isinstance(result,dict) or result.get('ok') is not True:return False
 item=result.get('item');a=replacement['action']['arguments']
 return isinstance(item,dict) and all(item.get(k)==a[k] for k in ('id','start','end') if k!='id') and item.get('id')==a['event_id']
