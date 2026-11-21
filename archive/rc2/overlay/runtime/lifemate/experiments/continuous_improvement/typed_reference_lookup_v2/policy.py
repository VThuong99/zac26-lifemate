"""Use a schema-declared read to resolve a demonstrably cross-domain ID.

No IDs are generated, mapped, or replaced. Every returned call is a cataloged
zero-required-argument read and its actual ToolEnv observation goes to the
unchanged model. All ambiguous situations fail closed to the original action.
"""
import re

def _steps(history):
 for entry in history:
  if not isinstance(entry,dict):continue
  action=entry.get('action');result=entry.get('result')
  if isinstance(action,dict) and isinstance(result,dict):yield action,result
  calls,results=entry.get('tool_calls'),entry.get('tool_results')
  if isinstance(calls,list) and isinstance(results,list) and len(calls)==len(results):
   for a,r in zip(calls,results):
    if isinstance(a,dict) and isinstance(r,dict):yield a,r

def _parameters(tool):
 nested=tool.get('parameters')
 return nested if isinstance(nested,dict) else tool

def propose(text,history,current,action,tools,kinds):
 if not isinstance(text,str) or not isinstance(history,list) or not isinstance(current,list) or not isinstance(action,dict) or not isinstance(tools,list) or not isinstance(kinds,dict):return None
 name=action.get('name');args=action.get('arguments')
 if action.get('type')!='call' or kinds.get(name)!='write' or not isinstance(args,dict):return None
 lookup={t.get('name'):t for t in tools if isinstance(t,dict) and isinstance(t.get('name'),str)};schema=lookup.get(name)
 if not schema:return None
 refs=set()
 for tool in lookup.values():
  for spec in (_parameters(tool).get('properties') or {}).values():
   ref=spec.get('x-ref') if isinstance(spec,dict) else None
   if isinstance(ref,str) and len(ref.split('.'))==2:refs.add(ref)
 targets=[]
 for field,spec in (_parameters(schema).get('properties') or {}).items():
  ref=spec.get('x-ref') if isinstance(spec,dict) else None;value=args.get(field)
  if ref not in refs or not isinstance(value,str) or not value:continue
  if re.search(r'(?<!\w)'+re.escape(value)+r'(?!\w)',text,flags=re.IGNORECASE):continue
  sources=set()
  for prev,result in _steps(history+current):
   prev_name=prev.get('name');app=prev_name.split('.',1)[0] if isinstance(prev_name,str) and '.' in prev_name else None
   if result.get('ok') is not True or not app:continue
   for source_ref in refs:
    source_app,collection=source_ref.split('.')
    if source_app!=app:continue
    values=result.get(collection)
    if isinstance(values,list) and any(isinstance(obj,dict) and obj.get('id')==value for obj in values):sources.add(source_ref)
  if ref in sources or not sources:continue
  app,collection=ref.split('.')
  choices=[n for n in (app+'.list_'+collection,app+'.list') if n in lookup and kinds.get(n)=='read' and not _parameters(lookup[n]).get('required')]
  choices=list(dict.fromkeys(choices))
  if len(choices)!=1:continue
  read=choices[0]
  if any(a.get('name')==read for a,r in _steps(current)):continue
  targets.append({'source_refs':sorted(sources),'expected_ref':ref,'field':field,'value':value,'read_tool':read})
 if len(targets)!=1:return None
 evidence=targets[0];return {'action':{'type':'call','name':evidence['read_tool'],'arguments':{}},'evidence':evidence}
