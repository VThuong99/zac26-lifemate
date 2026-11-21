"""Clarify text-search fields only after an actual corresponding search result."""
import copy,json
from experiments.continuous_improvement.text_search_identity_schema_v1.compose import intervene as explain

def has_named_entity(value,depth=0):
 if depth>8:return False
 if isinstance(value,dict):
  if isinstance(value.get('id'),str) and any(isinstance(value.get(k),str) and value[k].strip() for k in ('name','title')):return True
  return any(has_named_entity(v,depth+1) for v in value.values())
 if isinstance(value,list):return any(has_named_entity(v,depth+1) for v in value)
 return False

_COLLECTIONS={'maps.search_place':'places','bike_rental.find_bikes':'bikes','contacts.search':'contacts','library.search':'books'}

def intervene(request):
 try:
  p=json.loads(request['messages'][1]['content']);steps=p.get('previous_steps')
  if not isinstance(steps,list):return copy.deepcopy(request)
  actions=[s for s in steps if isinstance(s,dict) and isinstance(s.get('action'),dict)]
  if not actions:return copy.deepcopy(request)
  last=actions[-1]; result=last.get('result'); collection=_COLLECTIONS.get(last['action'].get('name'))
  if not collection or not isinstance(result,dict) or result.get('ok') is not True or not isinstance(result.get(collection),list) or not has_named_entity(result[collection]):return copy.deepcopy(request)
  return explain(request)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
