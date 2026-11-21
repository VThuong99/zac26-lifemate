"""Expose literal digit-word sequences from ASR as unverified text, not phone facts."""
import copy,json,re,unicodedata
TOKEN=re.compile(r'[^\W_]+',re.UNICODE)
DIGITS={'không':'0','một':'1','hai':'2','ba':'3','bốn':'4','tư':'4','năm':'5','lăm':'5','sáu':'6','bảy':'7','tám':'8','chín':'9',**{str(i):str(i) for i in range(10)}}


def spans(text):
    if not isinstance(text,str) or unicodedata.normalize('NFC',text)!=text:return []
    tokens=list(TOKEN.finditer(text));out=[];i=0
    while i<len(tokens):
        start=i;digits=[]
        while i<len(tokens):
            word=tokens[i].group().casefold()
            if word not in DIGITS or (i>start and not text[tokens[i-1].end():tokens[i].start()].isspace()):break
            digits.append(DIGITS[word]);i+=1
        if 8<=len(digits)<=12:
            out.append({'asr_words':text[tokens[start].start():tokens[i-1].end()],'literal_digits':''.join(digits)})
        if i==start:i+=1
    return out


def facts(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('previous_steps'),list):return None
    sources=[('current_user',payload.get('user_request'))]
    for i,step in enumerate(payload['previous_steps']):
        if isinstance(step,dict) and step.get('role')=='user':sources.append(('user_history_'+str(i),step.get('audio_text',step.get('text'))))
    out=[]
    for source,text in sources:
        for entry in spans(text):out.append({'source':source,**entry})
    return out if 0<len(out)<=8 else None


def intervene(request):
    q=copy.deepcopy(request)
    try:
        p=json.loads(q['messages'][1]['content']);entries=facts(p)
        if entries is not None:
            p['unverified_asr_digit_sequences']=entries
            q['messages'][1]['content']=json.dumps(p,ensure_ascii=False)
    except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
    return q
