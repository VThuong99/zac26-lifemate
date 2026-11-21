"""Expose an exact, unique direct-chat binding from a real just-returned list."""
import copy,json,re,unicodedata
UNSAFE=re.compile(r'(?<!\w)(?:đừng|chớ|không|chưa|chẳng|hông|hổng|khum|thôi|nhầm|thay\s+vì|ý\s+là|nói\s+lại|nhưng|trừ|nếu|hay|hoặc)(?!\w)',re.I)
PREFIX=r'(?<!\w)nhắn\s+(?:zalo|tin\s+nhắn\s+zalo)\s+cho\s+'
SUFFIX=r'(?=$|[,.!?]|\s+(?:là|rằng|giúp|dùm|rằng|rồi|nhé|nha|ạ)(?!\w))'
def norm(x):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',x).casefold()).strip() if isinstance(x,str) else ''
def bind(payload):
 text=payload.get('user_request');steps=payload.get('previous_steps')
 if not isinstance(text,str) or not isinstance(steps,list) or not steps or UNSAFE.search(text):return None
 latest=steps[-1]
 if not isinstance(latest,dict) or not isinstance(latest.get('action'),dict) or not isinstance(latest.get('result'),dict):return None
 action=latest['action'];res=latest['result']
 if action.get('type')!='call' or action.get('name')!='chat_ott.list_chats' or res.get('ok') is not True or not isinstance(res.get('chats'),list):return None
 chats=res['chats'];ids=[c.get('id') for c in chats if isinstance(c,dict)]
 if len(ids)!=len(chats) or any(not isinstance(i,str) or not i for i in ids) or len(ids)!=len(set(ids)):return None
 matches=[];t=norm(text)
 for c in chats:
  name=norm(c.get('name'))
  if c.get('type')!='direct' or not name:continue
  m=re.search(PREFIX+re.escape(name)+SUFFIX,t,re.I)
  if m:matches.append(c)
 if len(matches)!=1:return None
 return {'user_named_chat':matches[0]['name'],'chat_id':matches[0]['id'],'source':'chat_ott.list_chats','evidence':'unique direct chat with an exact named-recipient match'}
def intervene(req):
 q=copy.deepcopy(req)
 try:
  payload=json.loads(q['messages'][1]['content']);binding=bind(payload)
  if binding is not None:payload['observed_unique_chat_binding']=binding;q['messages'][1]['content']=json.dumps(payload,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(req)
 return q
