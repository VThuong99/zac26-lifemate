"""Prepare conservative targets from the frozen P34 inventory; no audio relabeling."""
import argparse
import collections
import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BPE = ROOT.parent / 'models/gipformer15-68m-dd9227d-p12/bpe.model'
TOKENS = BPE.with_name('tokens.txt')
INVENTORY = ROOT / 'results/p34_asr_data_v1/inventory.jsonl'
REVIEWS = ROOT / 'results/p34_asr_data_v1/prior_human_audio_review.jsonl'
EXPECTED = {'inventory':'98ddb61de5887f1d807038bcc424186c38dbbfb3e329ff63b8ae902c0ba4ad9e', 'bpe':'289dbb44527c13c419ae3a4d8ce6a349f01a97f8777e69934a77e3692d2f10db', 'tokens':'f536d03c2e95ebd2930cf0abec88e823bd17d3c1933da7ae6a82db3b80605e15', 'reviews':'451a4b462f31272c8cf30d782fb8dba0faaca5b4845c42fd66a6ad07d03286f5'}

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def read(path):
    return [json.loads(x) for x in path.read_text(encoding='utf8').splitlines() if x.strip()]

def normalize(text):
    """Only case, whitespace and isolated prose punctuation; never expand words."""
    text=' '.join(unicodedata.normalize('NFC',text).split())
    reasons=[]
    if any(c.isdecimal() for c in text): reasons.append('digit_or_numeric_identifier')
    if re.search(r'(?<!\w)[A-Z]{2,}(?!\w)',text) or re.search(r'(?<!\w)(?:sms|wifi|gps|atm|otp|usb|cpu|id|tv)(?!\w)',text,flags=re.IGNORECASE): reasons.append('abbreviation_or_identifier')
    if re.search(r'\b(?:mã|phòng|tuyến|số)\s+[A-Z](?!\w)',text,flags=re.UNICODE): reasons.append('single_letter_identifier')
    if any(len(c.upper())!=1 for c in text): reasons.append('case_expansion')
    # Embedded punctuation can be a decimal, abbreviation, identifier, or name.
    if re.search(r'[^\W\d_][.,?!][^\W\d_]',text,flags=re.UNICODE): reasons.append('embedded_punctuation')
    if any(not (c.isalpha() or unicodedata.category(c).startswith('M') or c.isspace() or c in ',.?!') for c in text): reasons.append('other_symbol_or_identifier')
    # Removing punctuation after a negation or correction can lose an interpretation.
    if re.search(r'\b(?:không|chưa|chẳng|đừng|thôi|trừ)\s*[,;:]',text,flags=re.IGNORECASE): reasons.append('potentially_semantic_punctuation')
    cleaned=' '.join(re.sub(r'[, .?!]',lambda m: ' ' if m.group()!=' ' else ' ', text).upper().split())
    if not cleaned: reasons.append('empty_target')
    return cleaned, sorted(set(reasons))

def stats(sp,texts):
    total=unk=clips=0; spans=collections.Counter(); chars=collections.Counter()
    for text in texts:
        pieces=sp.encode_as_immutable_proto(text).pieces
        total+=len(pieces); u=[p for p in pieces if p.id==sp.unk_id()]; unk+=len(u); clips+=bool(u)
        for p in u: spans[p.surface]+=1; chars.update(p.surface)
    return {'clips':len(texts),'unknown_clips':clips,'tokens':total,'unknown_tokens':unk,'unknown_token_rate':unk/total if total else None,'unknown_spans':spans.most_common(30),'unknown_characters':chars.most_common(30)}

def main():
    import sentencepiece as spm
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    for name,path in [('inventory',INVENTORY),('reviews',REVIEWS),('bpe',BPE),('tokens',TOKENS)]:
        if sha(path)!=EXPECTED[name]: raise ValueError(f'{name} hash mismatch')
    sp=spm.SentencePieceProcessor(model_file=str(BPE)); token_map={int(x.rsplit(' ',1)[1]):x.rsplit(' ',1)[0] for x in TOKENS.read_text().splitlines()}
    if len(token_map)!=sp.get_piece_size() or any(token_map.get(i)!=sp.id_to_piece(i) for i in range(sp.get_piece_size())): raise ValueError('token dictionary mismatch')
    rows=read(INVENTORY); reviews={r['clip_id']:r for r in read(REVIEWS)}; result=[]
    for row in rows:
        label,reasons=normalize(row['original_text']); reasons += list(row['invalid_reasons']) + list(row['flags'])
        if row['clip_id'] in reviews and not reviews[row['clip_id']]['normalized_token_sequences_match']: reasons.append('prior_human_audio_disagreement')
        ids=sp.encode(label,out_type=int); unknown=sum(i==sp.unk_id() for i in ids)
        if not ids or unknown or sp.decode(ids)!=label: reasons.append('tokenizer_not_exact')
        if 0 in ids: reasons.append('blank_token_in_target')
        reasons=sorted(set(reasons)); status='protected' if row['split']=='heldout_prior_evaluation' else ('review' if reasons else 'eligible')
        result.append({**row,'training_text':label if not reasons else None,'training_token_ids':ids if not reasons else None,'training_unknown_tokens':unknown,'review_reasons':reasons,'status':status})
    # Existing grouping is unchanged; ensure no normalized target collides across partitions.
    owners=collections.defaultdict(set)
    for r in result:
        for k,v in [('request',r['request_id']),('group',r['group_id']),('pcm',r['pcm_sha256']),('audio',r['audio']),('normalized_training_text',normalize(r['original_text'])[0])]:owners[(k,v)].add(r['split'])
    conflicts=[(k,sorted(v)) for k,v in owners.items() if len(v)>1]
    if conflicts: raise ValueError(f'cross-split leakage: {conflicts[:5]}')
    selected={s:[r for r in result if r['split']==s and r['status']=='eligible'] for s in ('train','dev')}
    summary={'input_hashes':EXPECTED,'vocabulary_size':sp.get_piece_size(),'blank_id':0,'unknown_id':sp.unk_id(),'token_dictionary_mapping_mismatches':0,'baseline':stats(sp,[r['normalized_text'] for r in rows]),'uppercase_diagnostic':stats(sp,[r['normalized_text'].upper() for r in rows]),'all_candidates_before_exclusions':stats(sp,[normalize(r['original_text'])[0] for r in result]),'eligible_combined':stats(sp,[r['training_text'] for r in result if r['status']=='eligible']),'splits':{},'review_reasons':dict(collections.Counter(reason for r in result if r['status']=='review' for reason in r['review_reasons'])),'review_clips':sum(r['status']=='review' for r in result),'protected_clips':sum(r['status']=='protected' for r in result),'cross_split_conflicts':len(conflicts),'speaker_metadata':'absent; speaker separation cannot be established','quality':'text compatibility and known flags only; unreviewed audio/reference alignment is not proven'}
    for s,rs in selected.items():summary['splits'][s]={'clips':len(rs),'requests':len({r['request_id'] for r in rs}),'groups':len({r['group_id'] for r in rs}),'duration_seconds':sum(r['duration_seconds'] for r in rs)}
    args.output.mkdir(parents=True,exist_ok=False)
    def write(name,items):
        with (args.output/name).open('x',encoding='utf8') as f:
            for x in items:f.write(json.dumps(x,ensure_ascii=False)+'\n')
    write('inventory.jsonl',result)
    for s,rs in selected.items(): write(s+'.jsonl',rs)
    write('review_queue.jsonl',[r for r in result if r['review_reasons']])
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
