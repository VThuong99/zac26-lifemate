"""Resolve unobserved or cross-namespace IDs using one unambiguous real read.

This does not infer a replacement identifier or claim that an unobserved ID is
invalid. It fails closed for collisions, explicit IDs, ambiguous reads and
already attempted reads. User text and all original observations are retained.
"""
import re
from experiments.continuous_improvement.typed_reference_lookup_v2.policy import _steps,_parameters
from experiments.continuous_improvement.unobserved_reference_read_v1.policy import _strings

def propose(text,context,history,current,action,tools,kinds):
 if not isinstance(text,str) or not isinstance(context,dict) or not isinstance(history,list) or not isinstance(current,list) or not isinstance(action,dict) or not isinstance(tools,list) or not isinstance(kinds,dict):return None
 name=action.get('name');args=action.get('arguments')
 if action.get('type')!='call' or kinds.get(name)!='write' or not isinstance(args,dict):return None
 by={t['name']:t for t in tools if isinstance(t,dict) and isinstance(t.get('name'),str)};schema=by.get(name)
 if not schema:return None
 refs=set()
 for tool in by.values():
  for spec in (_parameters(tool).get('properties') or {}).values():
   ref=spec.get('x-ref') if isinstance(spec,dict) else None
   if isinstance(ref,str) and len(ref.split('.'))==2:refs.add(ref)
 evidence=[text,*_strings(context)]
 for step in history+current:
  if isinstance(step,dict):
   for key in ('text','audio_text','result','tool_results'):evidence.extend(_strings(step.get(key)))
 targets=[]
 for field,spec in (_parameters(schema).get('properties') or {}).items():
  ref=spec.get('x-ref') if isinstance(spec,dict) else None;value=args.get(field)
  if ref not in refs or not isinstance(value,str) or not value.strip():continue
  if re.search(r'(?<!\w)'+re.escape(value)+r'(?!\w)',text,re.I):continue
  sources=set()
  for prev,result in _steps(history+current):
   pn=prev.get('name');app=pn.split('.',1)[0] if isinstance(pn,str) and '.' in pn else None
   if result.get('ok') is not True or not app:continue
   for source in refs:
    source_app,collection=source.split('.')
    if source_app!=app:continue
    values=result.get(collection)
    if isinstance(values,list) and any(isinstance(v,dict) and v.get('id')==value for v in values):sources.add(source)
  if ref in sources:continue
  if not sources and any(value.casefold() in s.casefold() for s in evidence):continue
  app,collection=ref.split('.')
  names=[app+'.list_'+collection,app+'.list']
  if app==collection:names.append(app+'.search')
  if collection.endswith('s'):names.append(app+'.get_'+collection[:-1])
  choices=list(dict.fromkeys(n for n in names if n in by and kinds.get(n)=='read' and not _parameters(by[n]).get('required') and not _parameters(by[n]).get('x-one-of')))
  if len(choices)!=1:continue
  read=choices[0]
  if any(a.get('name')==read for a,r in _steps(current)):continue
  targets.append({'field':field,'value':value,'expected_ref':ref,'source_refs':sorted(sources),'reason':'cross_namespace' if sources else 'unobserved','read_tool':read})
 if len(targets)!=1:return None
 proof=targets[0];return {'action':{'type':'call','name':proof['read_tool'],'arguments':{}},'evidence':proof}
