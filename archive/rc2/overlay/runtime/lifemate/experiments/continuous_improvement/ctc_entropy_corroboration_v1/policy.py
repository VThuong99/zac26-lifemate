"""Propose one uncertain CTC word only with unique independent phrase support."""
import re,unicodedata
from experiments.continuous_improvement.asr_entropy_substitution_v1.policy import propose
TOKEN=re.compile(r'\w+',re.UNICODE)
EXTRA_PROTECTED={'đổi','sửa','nhầm','lộn','hủy','huỷ','dừng','ngừng','trừ','chỉ','ngoại','riêng','thay','khỏi','chưa','hông','đừng'}
def tok(s):return [(unicodedata.normalize('NFC',m.group()).casefold(),m.span()) for m in TOKEN.finditer(s)]
def decide(raw,ctc,emissions,independent,native_parity):
 out={'raw':raw,'text':raw,'change':None,'reason':'no_supported_change'}
 if native_parity is not True or not isinstance(raw,str) or not isinstance(ctc,str) or not isinstance(independent,str):return out
 z=propose(raw,ctc,emissions);change=z['change']
 if not change:return out
 original=unicodedata.normalize('NFC',change['original']).casefold();replacement=unicodedata.normalize('NFC',change['replacement']).casefold()
 if original in EXTRA_PROTECTED or replacement in EXTRA_PROTECTED:return out
 a=tok(raw);b=tok(independent);inds=[i for i,(_,span) in enumerate(a) if span==(change['start'],change['end'])]
 if len(inds)!=1 or inds[0]<1:return out
 i=inds[0];phrase=[a[i-1][0],replacement];vals=[t for t,_ in b]
 if sum(vals[j:j+2]==phrase for j in range(len(vals)-1))!=1:return out
 # No change to formatting, neighboring words, punctuation, or the raw transcript.
 return {'raw':raw,'text':z['text'],'change':change,'reason':'uncertain_single_ctc_word_unique_independent_left_phrase'}
