"""Reject a clarification only for an explicitly referenced profile address."""
import re
from experiments.continuous_improvement.dpo_write_abstention_v2.policy import select as base_select
WORK=re.compile(r'(?<!\w)(?:công\s+ty|chỗ\s+làm|văn\s+phòng|cơ\s+quan)(?!\w)',re.I)
HOME=re.compile(r'(?<!\w)(?:nhà|chỗ\s+ở)(?!\w)',re.I)
DIRECTION=re.compile(r'(?<!\w)(?:tới|đến|tại|ở|về|ra)(?!\w)',re.I)
DIRECT_BEFORE=re.compile(r'(?<!\w)(?:tới|đến|tại|ở|về|ra)\s*$',re.I)
UNSAFE=re.compile(r'(?<!\w)(?:không|đừng|chớ|nếu|trừ|hoặc|hay|khác|mới|nhầm|sửa|khoan|từ)(?!\w)',re.I)
CONFLICT=re.compile(r'(?<!\w)(?:đổi\s+địa\s+chỉ|địa\s+chỉ\s+mới|chuyển\s+(?:nhà|công\s+ty|văn\s+phòng)|công\s+ty\s+mới|nhà\s+mới)(?!\w)',re.I)
NEAR=re.compile(r'(?<!\w)(?:gần|cạnh|đối\s+diện|phía\s+trước|phía\s+sau|bên\s+ngoài)(?:\s+(?:cái|tòa|khu))?\s*$',re.I)
MODIFIER=re.compile(r'^\s+(?:của|bên|đối\s+tác|bạn|anh|chị|họ|người|hàng|cung\s+cấp)(?!\w)',re.I)
HIST_LOCATION=re.compile(r'(?<!\w)(?:công\s+ty|văn\s+phòng|chỗ\s+làm|cơ\s+quan|nhà|chỗ\s+ở|company|office|workplace|home)(?!\w)',re.I)
ADDRESS_FIELDS=frozenset(('address','pickup','pickup_address'))
FOLLOWERS=frozenset('lấy đón nhận trả gửi để rồi nhé nha ạ giúp cho lúc ngày sáng chiều tối vào về xong đi'.split())
def conflicting_address(value,expected):
 if isinstance(value,dict):
  for k,v in value.items():
   if k in ('address','pickup','pickup_address','dropoff','delivery_address','home_address','work_address','current_address') and isinstance(v,str) and v.strip() and v!=expected:return True
   if conflicting_address(v,expected):return True
 elif isinstance(value,list):return any(conflicting_address(v,expected) for v in value)
 return False

def profile_address_grounded(primary,secondary,text,context,history):
 if not isinstance(primary,dict) or not isinstance(secondary,dict) or not isinstance(text,str) or not isinstance(context,dict) or not isinstance(history,list):return False
 if secondary.get('type')!='call' or secondary.get('name')!='sys.ask_missing_info':return False
 arg=secondary.get('arguments',{})
 if not isinstance(arg,dict):return False
 params=arg.get('params')
 if arg.get('tool_name')!=primary.get('name') or not isinstance(params,list) or len(params)!=1 or params[0] not in ADDRESS_FIELDS:return False
 if UNSAFE.search(text):return False
 profile=context.get('user_profile');values=primary.get('arguments')
 if not isinstance(profile,dict) or not isinstance(values,dict):return False
 work=list(WORK.finditer(text));home=list(HOME.finditer(text))
 if bool(work)==bool(home):return False
 matches,key=(work,'work_address') if work else (home,'home_address')
 if len(matches)!=1 or NEAR.search(text[:matches[0].start()]) or MODIFIER.search(text[matches[0].end():]):return False
 if not DIRECT_BEFORE.search(text[:matches[0].start()]) or len(DIRECTION.findall(text))!=1:return False
 if len(set(values).intersection(ADDRESS_FIELDS))!=1:return False
 # A bare location followed by another name may refer to someone else's
 # company/home; accept only an unmodified location or a clear clause start.
 tail=text[matches[0].end():].strip()
 if tail:
  first=re.match(r'([^\W_]+)',tail,re.UNICODE)
  if first is None or first.group(1).casefold() not in FOLLOWERS:return False
 value=profile.get(key)
 if not isinstance(value,str) or not value.strip() or values.get(params[0])!=value:return False
 for turn in history:
  if not isinstance(turn,dict):continue
  if turn.get('role') in ('user','assistant'):
   for field in ('text','audio_text'):
    spoken=turn.get(field)
    if isinstance(spoken,str) and (CONFLICT.search(spoken) or HIST_LOCATION.search(spoken)):return False
  # Historical and current actual tool results can reveal a conflicting address.
  if conflicting_address(turn.get('tool_results'),value) or conflicting_address(turn.get('result'),value):return False
 return True

def select(primary,secondary,kinds,tools,text,context,history):
 candidate=base_select(primary,secondary,kinds,tools)
 if candidate!=primary and profile_address_grounded(primary,candidate,text,context,history):return primary
 return candidate
