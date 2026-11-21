"""Two-stage, raw-preserving local acoustic corroboration."""
import difflib,math,re,unicodedata
from experiments.continuous_improvement.asr_entropy_substitution_v1.policy import protected
from experiments.continuous_improvement.ctc_entropy_corroboration_v1.policy import EXTRA_PROTECTED
TOKEN=re.compile(r'\w+',re.UNICODE)
ASPECT_MODAL=frozenset('đã đang sẽ từng vừa mới sắp còn vẫn lại rồi xong được bị phải nên muốn cần định luôn tiếp chưa'.split())
def normalize(x):return unicodedata.normalize('NFC',x).casefold()
def preflight(raw,ctc,emissions,native_parity):
 if native_parity is not True or not isinstance(raw,str) or not isinstance(ctc,str) or not isinstance(emissions,list):return []
 full='';spans=[]
 for e in emissions:
  if not isinstance(e,dict) or not isinstance(e.get('piece'),str) or isinstance(e.get('entropy'),bool) or not isinstance(e.get('entropy'),(int,float)) or not math.isfinite(e['entropy']) or e['entropy']<0:return []
  piece=e['piece'].replace('▁',' ');start=len(full);full+=piece;spans.append((start,len(full),float(e['entropy'])))
 left=len(full)-len(full.lstrip())
 if full.strip()!=raw:return []
 old=list(re.finditer(r'\S+',raw));new=list(re.finditer(r'\S+',ctc));a=[normalize(x.group()) for x in old];b=[normalize(x.group()) for x in new];qualified=[]
 for op,i,j,k,l in difflib.SequenceMatcher(a=a,b=b,autojunk=False).get_opcodes():
  if op!='replace' or j-i!=1 or l-k!=1 or i<1 or j>=len(a) or k<1 or l>=len(b):continue
  original=old[i].group();replacement=new[k].group()
  if not TOKEN.fullmatch(original) or not TOKEN.fullmatch(replacement) or a[i-1]!=b[k-1] or a[j]!=b[l]:continue
  if protected(original) or protected(replacement) or normalize(original) in EXTRA_PROTECTED or normalize(replacement) in EXTRA_PROTECTED or normalize(original) in ASPECT_MODAL or normalize(replacement) in ASPECT_MODAL:continue
  if not TOKEN.fullmatch(old[i-1].group()) or not TOKEN.fullmatch(old[j].group()):continue
  start,end=old[i].span();scores=[v for x,y,v in spans if x<end+left and y>start+left and full[max(x,start+left):min(y,end+left)].strip()]
  if not scores or max(scores)<1.0:continue
  qualified.append({'start':start,'end':end,'original':original,'replacement':replacement,'mean_entropy':sum(scores)/len(scores),'max_entropy':max(scores),'emission_count':len(scores),'corroborating_neighbor_words':[old[i-1].group(),old[j].group()]})
 return qualified
def decide(raw,ctc,emissions,independent,native_parity):
 out={'raw':raw,'text':raw,'change':None,'reason':'no_supported_change'}
 if not isinstance(independent,str):return out
 ind=[normalize(m.group()) for m in TOKEN.finditer(independent)];qualified=[]
 for z in preflight(raw,ctc,emissions,native_parity):
  phrase=[normalize(z['corroborating_neighbor_words'][0]),normalize(z['replacement']),normalize(z['corroborating_neighbor_words'][1])]
  if sum(ind[n:n+3]==phrase for n in range(len(ind)-2))==1:qualified.append(z)
 if len(qualified)!=1:return out
 change=qualified[0];out.update(text=raw[:change['start']]+change['replacement']+raw[change['end']:],change=change,reason='unique_uncertain_local_ctc_substitution_with_independent_three_word_support');return out
