"""Select a same-domain source-grounded read from an adapter review; no generated writes."""
import copy
from experiments.continuous_improvement.conditional_precondition_review_v1.policy import select as base_select
from k_schema_helpers import schema_error

def select(primary,review,text,steps,kinds,tools):
 if not isinstance(tools,list):return primary
 allowed={t.get('name') for t in tools if isinstance(t,dict) and isinstance(t.get('name'),str)}
 chosen=base_select(primary,review,text,steps,kinds,allowed)
 if chosen==primary:return primary
 if not isinstance(primary.get('name'),str) or not isinstance(chosen.get('name'),str):return primary
 if '.' not in primary['name'] or primary['name'].split('.',1)[0]!=chosen['name'].split('.',1)[0]:return primary
 spec=next((t for t in tools if t.get('name')==chosen['name']),None)
 if not isinstance(spec,dict):return primary
 params=spec.get('parameters') if isinstance(spec.get('parameters'),dict) else {'type':'object','properties':spec.get('properties',{}),'required':spec.get('required',[])}
 props=params.get('properties')
 if not isinstance(props,dict) or not set(chosen['arguments']).issubset(props):return primary
 native={'name':spec['name'],'parameters':params}
 if schema_error(chosen['name'],chosen['arguments'],[native],allowed):return primary
 return copy.deepcopy(chosen)
