"""Show ASR digit sequences only after same-clip independent exact agreement."""
import copy,json,re,unicodedata
from experiments.continuous_improvement.spoken_digit_evidence_q8_v1.compose import facts as primary_facts,spans


def independent_sequences(text):
    if not isinstance(text,str):return set()
    found={x['literal_digits'] for x in spans(text)}
    found.update(re.findall(r'(?<!\d)\d{8,12}(?!\d)',text))
    return found


def facts(payload, independent_by_source):
    if not isinstance(independent_by_source,dict):return None
    entries=primary_facts(payload) or []
    result=[x for x in entries if x['literal_digits'] in independent_sequences(independent_by_source.get(x['source']))]
    return result or None


def intervene(request,independent_by_source):
    q=copy.deepcopy(request)
    try:
        p=json.loads(q['messages'][1]['content']);entries=facts(p,independent_by_source)
        if entries is not None:
            p['unverified_asr_digit_sequences']=entries
            q['messages'][1]['content']=json.dumps(p,ensure_ascii=False)
    except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
    return q
