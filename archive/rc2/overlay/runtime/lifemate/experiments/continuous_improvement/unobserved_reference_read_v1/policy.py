"""Obtain an unfiltered collection read before a wholly unobserved referenced ID.

No ID is invented, substituted, or declared invalid. Absence is not proof of
invalidity; fail closed whenever history, schema or read choice is ambiguous.
"""
import copy,re

def _parameters(t):
 p=t.get('parameters');return p if isinstance(p,dict) else t

def _strings(x):
 if isinstance(x,str):yield x
 elif isinstance(x,list):
  for v in x:yield from _strings(v)
 elif isinstance(x,dict):
  for v in x.values():yield from _strings(v)

def propose(text,context,history,current,action,tools,kinds):
 if not isinstance(text,str) or not isinstance(context,dict) or not isinstance(history,list) or not isinstance(current,list) or not isinstance(action,dict) or not isinstance(tools,list) or not isinstance(kinds,dict):return None
 name=action.get('name');args=action.get('arguments')
 if action.get('type')!='call' or kinds.get(name)!='write' or not isinstance(args,dict):return None
 by={t['name']:t for t in tools if isinstance(t,dict) and isinstance(t.get('name'),str)};schema=by.get(name)
 if not schema:return None
 evidence=[text,*_strings(context)]
 for step in history+current:
  if not isinstance(step,dict):continue
  for k in ('text','audio_text','result','tool_results'):evidence.extend(_strings(step.get(k)))
 targets=[]
 for field,spec in (_parameters(schema).get('properties') or {}).items():
  ref=spec.get('x-ref') if isinstance(spec,dict) else None;value=args.get(field)
  if not isinstance(ref,str) or len(ref.split('.'))!=2 or not isinstance(value,str) or not value.strip():continue
  # Substring checks are conservative: any occurrence means do not intervene.
  if any(value.casefold() in s.casefold() for s in evidence):continue
  app,collection=ref.split('.')
  if not app or not collection:continue
  candidates=[app+'.list_'+collection,app+'.list']
  if app==collection:candidates.append(app+'.search')
  if collection.endswith('s'):candidates.append(app+'.get_'+collection[:-1])
  candidates=list(dict.fromkeys(n for n in candidates if n in by and kinds.get(n)=='read' and not _parameters(by[n]).get('required') and not _parameters(by[n]).get('x-one-of')))
  if len(candidates)!=1:continue
  read=candidates[0]
  # Never repeat a current-path collection read, whether or not it succeeded.
  if any(isinstance(z,dict) and isinstance(z.get('action'),dict) and z['action'].get('name')==read for z in current):continue
  targets.append({'field':field,'value':value,'expected_ref':ref,'read_tool':read})
 if len(targets)!=1:return None
 target=targets[0];return {'action':{'type':'call','name':target['read_tool'],'arguments':{}},'evidence':target}
