"""Conservative task-scoped validation for date-only format repairs."""
import re,unicodedata
from experiments.continuous_improvement.schema_date_reference_v2.policy import accept as old_accept,date_grounded,invalid_formats,REFERENCE
CLAUSE=re.compile(r'[,;.!?\n]|(?<!\w)(?:rồi|xong|đồng\s+thời|sau\s+đó|và)(?!\w)',re.I)
OFFSET=re.compile(r'(?<!\w)(?:trước|sau|trễ|chậm|sớm|lùi|dời|hoãn|khoảng|tầm|kể\s+từ|trừ|nếu|không|đừng|chớ|nhầm|sửa)(?!\w)',re.I)
RELATIVE_ADD=re.compile(r'(?<!\w)(?:thêm|bớt)\s+(?:\d+|một|hai|ba|bốn|năm|sáu|bảy|mười)\s+(?:ngày|giờ|tuần|tháng)(?!\w)',re.I)
DATE_MENTION=re.compile(r'(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)(?!\d)')
CLOCK_HINT=re.compile(r'\[Giờ chuẩn hóa:\s*"([^"\n]+)"\s*=\s*([0-2]\d:[0-5]\d)\]')
WORDS=re.compile(r'[^\W\d_]+',re.UNICODE)
STOP={'của','vào','lúc','ngày','việc','cần','làm','cho','một','cái','kiểm','nhắc','tôi','chị','anh','em','giúp','đến','thì','đó','các','với','đã'}
def tokens(s):return [x for x in WORDS.findall(unicodedata.normalize('NFC',s).casefold()) if len(x)>1 and x not in STOP]
def scopes(s):return [x.strip() for x in CLAUSE.split(s) if x.strip()]
def match_task(action,clause):
 args=action.get('arguments',{});label=next((args[k] for k in ('title','content') if isinstance(args.get(k),str) and args[k].strip()),None)
 if label is None:return False
 a=tokens(label);b=tokens(clause)
 return len(a)>=2 and any(a[i:i+2]==b[j:j+2] for i in range(len(a)-1) for j in range(len(b)-1))
def accept(original,secondary,tools,text,context,history):
 if not old_accept(original,secondary,tools,text,context,history):return False
 fields=invalid_formats(original,tools);clauses=scopes(text);possible=[c for c in clauses if match_task(original,c) and not OFFSET.search(c) and not RELATIVE_ADD.search(c)]
 if len(possible)!=1:return False
 clause=possible[0];value=next(iter(original['arguments'][k] for k in fields));clock=next(iter(secondary['arguments'][k][11:16] for k in fields))
 if len(DATE_MENTION.findall(clause))>1:return False
 if not re.search(r'(?<!\d)'+re.escape(clock)+r'(?!\d)',clause):
  hints=[m for m in CLOCK_HINT.finditer(text) if m.group(2)==clock and m.group(1).casefold() in clause.casefold() and text.casefold().count(m.group(1).casefold())==2]
  if len(hints)!=1:return False
 if date_grounded(value,clause,context,[]):return True
 if not REFERENCE.search(clause):return False
 turns=[z for z in history if isinstance(z,dict) and z.get('role') in ('user','assistant')]
 if len(turns)<2 or turns[-1].get('role')!='assistant' or turns[-2].get('role')!='user':return False
 last=turns[-1].get('text')
 if not isinstance(last,str):return False
 matching=[c for c in scopes(last) if not OFFSET.search(c) and not RELATIVE_ADD.search(c) and len(DATE_MENTION.findall(c))==1 and match_task(original,c) and date_grounded(value,c,context,[])]
 return len(matching)==1
