"""One locally uncertain substitution; preserve raw Vietnamese and fail closed."""
import difflib,re,unicodedata,statistics,math
THRESHOLD_NATS=1.0
PROTECTED=frozenset('không chẳng đừng chưa chớ nếu thì hoặc hay thôi khỏi hủy huỷ có một mốt hai ba bốn tư năm lăm sáu bảy tám chín mười mươi chục trăm nghìn ngàn triệu tỷ đồng giờ phút giây hôm nay mai ngày tháng năm trước sau'.split())
def protected(word):
 s=unicodedata.normalize('NFC',word).casefold()
 return bool(re.search(r'\d',s)) or s in PROTECTED

def propose(raw,alternate,emissions):
 result={'raw':raw,'alternate':alternate,'text':raw,'change':None}
 if not isinstance(raw,str) or not isinstance(alternate,str) or not isinstance(emissions,list) or raw==alternate:return result
 pieces=[];spans=[];offset=0
 for e in emissions:
  if not isinstance(e,dict) or not isinstance(e.get('piece'),str) or not isinstance(e.get('entropy'),(int,float)):return result
  piece=e['piece'].replace('▁',' ');pieces.append(piece);spans.append((offset,offset+len(piece),float(e['entropy'])));offset+=len(piece)
 full=''.join(pieces);left=len(full)-len(full.lstrip())
 if full.strip()!=raw:return result
 old=list(re.finditer(r'\S+',raw));new=list(re.finditer(r'\S+',alternate));a=[m.group() for m in old];b=[m.group() for m in new];ops=[x for x in difflib.SequenceMatcher(a=a,b=b,autojunk=False).get_opcodes() if x[0]!='equal']
 if len(ops)!=1:return result
 op,i,j,k,l=ops[0]
 if op!='replace' or j-i!=1 or l-k!=1 or i==0 or j==len(a) or k==0 or l==len(b):return result
 if a[i-1]!=b[k-1] or a[j]!=b[l] or protected(a[i]) or protected(b[k]):return result
 start,end=old[i].span();scores=[v for x,y,v in spans if x<end+left and y>start+left and full[max(x,start+left):min(y,end+left)].strip()]
 if not scores or not all(math.isfinite(v) and v>=0 for v in scores):return result
 entropy=statistics.mean(scores)
 if entropy<THRESHOLD_NATS:return result
 result['text']=raw[:start]+b[k]+raw[end:];result['change']={'start':start,'end':end,'original':a[i],'replacement':b[k],'mean_entropy':entropy,'emission_count':len(scores)};return result
