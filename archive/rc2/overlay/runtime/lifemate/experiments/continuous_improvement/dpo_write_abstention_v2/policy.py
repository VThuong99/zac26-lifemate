"""Accept only an adapter's termination or well-formed same-tool clarification."""
import copy

def eligible(action,kinds):
 return isinstance(action,dict) and action.get('type')=='call' and isinstance(action.get('name'),str) and isinstance(action.get('arguments'),dict) and kinds.get(action['name'])=='write'

def select(primary,secondary,kinds,tools):
 if not eligible(primary,kinds) or not isinstance(secondary,dict):return primary
 if secondary=={'type':'finish'}:return copy.deepcopy(secondary)
 if set(secondary)!={'type','name','arguments'} or secondary.get('type')!='call' or secondary.get('name')!='sys.ask_missing_info':return primary
 args=secondary.get('arguments')
 if not isinstance(args,dict) or set(args)!={'tool_name','params'} or args['tool_name']!=primary['name'] or not isinstance(args['params'],list) or not args['params'] or any(not isinstance(x,str) for x in args['params']) or len(set(args['params']))!=len(args['params']):return primary
 schema=[x for x in tools if isinstance(x,dict) and x.get('name')==primary['name']];ask=[x for x in tools if isinstance(x,dict) and x.get('name')=='sys.ask_missing_info']
 if len(schema)!=1 or len(ask)!=1:return primary
 props=schema[0].get('properties')
 if props is None and isinstance(schema[0].get('parameters'),dict):props=schema[0]['parameters'].get('properties')
 if not isinstance(props,dict) or any(p not in props for p in args['params']):return primary
 return copy.deepcopy(secondary)
