"""Repeat only observed contact-field bindings from the latest real contact search."""
import copy,json

def evidence(payload):
 if not isinstance(payload,dict) or not isinstance(payload.get('previous_steps'),list):return None
 last=None
 for step in payload['previous_steps']:
  if not isinstance(step,dict):continue
  action=step.get('action');result=step.get('result')
  if not isinstance(action,dict):continue
  name=action.get('name')
  if name=='contacts.search':
   last=(action,result) if isinstance(result,dict) and result.get('ok') is True and isinstance(result.get('contacts'),list) else None
  elif isinstance(name,str) and name.startswith('contacts.') and name not in ('contacts.get',):
   last=None
 if last is None:return None
 action,result=last;contacts=result['contacts']
 if len(contacts)>30:return None
 found=[];ids=set()
 for c in contacts:
  if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not c['id'] or not isinstance(c.get('name'),str) or not c['name'] or c['id'] in ids:return None
  ids.add(c['id']);record={k:c[k] for k in ('id','name','relation','phone','email') if k in c and isinstance(c[k],str) and c[k]};found.append(record)
 args=action.get('arguments',{})
 if not isinstance(args,dict):return None
 out={'source':'contacts.search','contacts':found,'interpretation':'Mỗi tên, ID, số và email trong một dòng chỉ thuộc liên hệ đó; kết quả không xác nhận liên hệ khác.'}
 if isinstance(args.get('query'),str):out['search_query']=args['query']
 return out

def intervene(request):
 q=copy.deepcopy(request)
 try:
  p=json.loads(q['messages'][1]['content']);v=evidence(p)
  if v is not None:p['observed_contact_bindings']=v;q['messages'][1]['content']=json.dumps(p,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return q
