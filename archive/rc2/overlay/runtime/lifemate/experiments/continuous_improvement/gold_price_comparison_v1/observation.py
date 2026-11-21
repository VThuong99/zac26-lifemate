"""Expose only exact, current-trajectory SJC sell-price comparisons."""
import copy,re,unicodedata
ONES={'một':1,'mốt':1,'hai':2,'ba':3,'bốn':4,'tư':4,'năm':5,'lăm':5,'sáu':6,'bảy':7,'tám':8,'chín':9}
WORD=r'(?:một|mốt|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín)'
NUMBER=rf'(?:[1-9]\d{{0,2}}|một\s+trăm(?:\s+(?:(?:lẻ|linh)\s+{WORD}|mười(?:\s+{WORD})?|{WORD}\s+mươi(?:\s+{WORD})?))?)'
PATTERN=re.compile(rf'\bvàng\s+sjc\s+bán\s+ra\s+(?:mà\s+)?(?:trên|vượt|hơn|quá)\s+(?P<number>{NUMBER})\s+triệu(?:\s+đồng)?\s+thì\b',re.I)
ELSE=re.compile(r'\b(?:(?:còn\s+)?không\s+thì|chưa\s+(?:tới|vượt)\s+thì)\b',re.I)

def normalize(s):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s).casefold()).strip() if isinstance(s,str) else ''
def million_number(s):
 s=normalize(s)
 if re.fullmatch(r'[1-9]\d{0,2}',s):return int(s)
 tokens=s.split()
 if tokens[:2]!=['một','trăm']:return None
 rest=tokens[2:]
 if not rest:return 100
 if rest[0] in ('lẻ','linh') and len(rest)==2:return 100+ONES.get(rest[1],-1000)
 if rest[0]=='mười' and len(rest)<=2:return 110+(ONES.get(rest[1],-1000) if len(rest)==2 else 0)
 if len(rest) in (2,3) and rest[0] in ONES and rest[1]=='mươi':return 100+10*ONES[rest[0]]+(ONES.get(rest[2],-1000) if len(rest)==3 else 0)
 return None

def evidence(text,history):
 if not isinstance(text,str) or not isinstance(history,list):return None
 s=normalize(text);matches=list(PATTERN.finditer(s));else_matches=list(ELSE.finditer(s))
 if len(matches)!=1 or len(else_matches)!=1 or else_matches[0].start()<=matches[0].end():return None
 m=matches[0]
 if re.search(r'\b(?:không|đừng|chớ|khỏi|chưa|trừ)\b',s[max(0,m.start()-50):m.start()]):return None
 num=million_number(m.group('number'))
 if not isinstance(num,int) or not 1<=num<=999:return None
 readings=[]
 for step in history:
  if not isinstance(step,dict):continue
  act=step.get('action');res=step.get('result')
  if not isinstance(act,dict) or act.get('name')!='gold_price.get_price' or not isinstance(res,dict) or res.get('ok') is not True:continue
  args=act.get('arguments',{});prices=res.get('prices')
  if not isinstance(args,dict) or args.get('type') not in (None,'sjc') or not isinstance(prices,list):continue
  readings.extend(x for x in prices if isinstance(x,dict) and x.get('type')=='sjc')
 if len(readings)!=1:return None
 price=readings[0].get('sell');unit=readings[0].get('unit')
 if not isinstance(price,int) or isinstance(price,bool) or price<=0 or unit!='VND/lượng':return None
 threshold=num*1000000
 return {'loại':'SJC','giá_bán_ra_thực_tế_đồng_mỗi_lượng':price,'ngưỡng_người_dùng_nói_đồng_mỗi_lượng':threshold,'điều_kiện_so_sánh':'lớn hơn nghiêm ngặt','điều_kiện_đúng':price>threshold,'nguồn':'giá bán ra từ lần tra cứu công cụ trong yêu cầu hiện tại'}

def context_with_evidence(text,context,history):
 proof=evidence(text,history)
 if proof is None or not isinstance(context,dict):return context
 c=copy.deepcopy(context);c['so_sánh_giá_vàng_đã_quan_sát']=proof;return c
