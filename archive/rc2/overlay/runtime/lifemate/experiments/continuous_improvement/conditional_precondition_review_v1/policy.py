"""Permit only a new source-grounded read before a conditional write."""
import copy,json,re,unicodedata
COND=re.compile(r'(?<!\w)(?:nếu|nếu\s+như|hễ|khi|thì)(?!\w)',re.I)
GUIDANCE=('\n- Before the proposed write below, check whether the user made it conditional on a current fact that has not actually been observed. '
 'If a current prerequisite is missing, choose an available read-only tool to obtain it; use only arguments supported by the user or real prior observations. '
 'If the condition is already established or no useful read is available, return the proposed action unchanged. Do not invent observations or create any new write.')
def literals(value):
 if isinstance(value,str):yield value
 elif isinstance(value,list):
  for x in value:yield from literals(x)
 elif isinstance(value,dict):
  for x in value.values():yield from literals(x)
def supported(value,strings):
 if not isinstance(value,str) or not value.strip() or value!=value.strip():return False
 v=unicodedata.normalize('NFC',value).casefold();pat=re.compile(r'(?<!\w)'+re.escape(v)+r'(?!\w)');return any(pat.search(unicodedata.normalize('NFC',s).casefold()) for s in strings)
def review_request(base,primary,kinds):
 if not isinstance(primary,dict) or primary.get('type')!='call' or kinds.get(primary.get('name'))!='write':return None
 q=copy.deepcopy(base);p=json.loads(q['messages'][1]['content']);text=p.get('user_request')
 if not isinstance(text,str) or not COND.search(text):return None
 p['local_precondition_proposal']=copy.deepcopy(primary);q['messages'][1]['content']=json.dumps(p,ensure_ascii=False);q['messages'][0]['content']+=GUIDANCE;return q
def select(primary,secondary,text,previous_steps,kinds,available):
 if not isinstance(primary,dict) or kinds.get(primary.get('name'))!='write' or not isinstance(text,str) or not COND.search(text):return primary
 if not isinstance(secondary,dict) or set(secondary)!={'type','name','arguments'} or secondary.get('type')!='call' or kinds.get(secondary.get('name'))!='read' or secondary.get('name') not in available or not isinstance(secondary.get('arguments'),dict):return primary
 if not isinstance(previous_steps,list):return primary
 actual=[z for z in previous_steps if isinstance(z,dict) and isinstance(z.get('action'),dict) and isinstance(z.get('result'),dict)]
 if any(z['action']==secondary for z in actual):return primary
 strings=[text]
 for z in previous_steps:
  if isinstance(z,dict):
   for field in ('audio_text','text','result','tool_results'):strings.extend(literals(z.get(field)))
 for v in secondary['arguments'].values():
  if not isinstance(v,str) or not supported(v,strings):return primary
 return copy.deepcopy(secondary)
