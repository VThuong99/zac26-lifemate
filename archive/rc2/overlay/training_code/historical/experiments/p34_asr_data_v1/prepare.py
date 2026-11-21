"""Non-lossy organizer audio inventory and leakage-aware draft ASR split."""
import argparse,collections,hashlib,json,math,unicodedata,wave
from pathlib import Path
import numpy as np
ROOT=Path('/workspace/GPU_benchmark/lifemate')
BPE=ROOT.parent/'models/gipformer15-68m-dd9227d-p12/bpe.model'
SPLIT=ROOT/'experiments/supervised_family_split_v2.json'
DATA=ROOT/'train/train.jsonl'
FLAGS=ROOT/'results/p32_oracle_text_v1/reference_audio_review_flags.json'
ANNOT=ROOT/'results/p13_review_v1/annotations.json'
P13_MANIFEST=ROOT/'results/p13_review_v1/manifest.json'
SEED=20261103

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def normalize(text):
    if not isinstance(text,str): raise TypeError('transcript must be text')
    return ' '.join(unicodedata.normalize('NFC',text).split())

def token_audit(text,sp):
    ids=sp.encode(text,out_type=int); unknown=sum(i==sp.unk_id() for i in ids)
    decoded=sp.decode(ids) if ids else ''
    return {'unknown_tokens':unknown,'exact_roundtrip':decoded==text,'compatible':bool(ids) and not unknown and decoded==text}

def inspect_audio(audio_root,relative):
    if not isinstance(relative,str): raise ValueError('audio path is not a string')
    path=(audio_root.parent/relative).resolve(); base=audio_root.resolve()
    if not path.is_relative_to(base) or path.suffix.lower()!='.wav': raise ValueError('audio path outside split audio or not WAV')
    if not path.is_file(): raise ValueError('missing WAV')
    with wave.open(str(path),'rb') as f:
        channels,rate,width,frames,compression=f.getnchannels(),f.getframerate(),f.getsampwidth(),f.getnframes(),f.getcomptype()
        data=f.readframes(frames)
    if len(data)!=frames*channels*width: raise ValueError('truncated WAV')
    result={'audio_sha256':sha(path),'pcm_sha256':hashlib.sha256(data).hexdigest(),'channels':channels,'sample_rate':rate,'sample_width_bytes':width,'frames':frames,'compression':compression,'duration_seconds':frames/rate if rate else None}
    if (channels,rate,width,compression)!=(1,16000,2,'NONE'): raise ValueError('expected mono 16kHz PCM16 WAV')
    if frames==0: raise ValueError('empty WAV')
    samples=np.frombuffer(data,dtype='<i2').astype(np.int32)
    result.update({'silent':not bool(np.any(samples)),'clipped_fraction':float(np.mean(np.abs(samples)>=32767)),'rms':float(np.sqrt(np.mean(samples.astype(np.float64)**2))/32768)})
    return result

class UnionFind:
    def __init__(self,ids): self.parent={i:i for i in ids}
    def find(self,i):
        while self.parent[i]!=i:
            self.parent[i]=self.parent[self.parent[i]]; i=self.parent[i]
        return i
    def union(self,a,b):
        a,b=self.find(a),self.find(b)
        if a!=b: self.parent[max(a,b)]=min(a,b)

def group_requests(ids,families,records):
    uf=UnionFind(ids)
    for fam in families:
        for i in fam[1:]: uf.union(fam[0],i)
    for field in ('audio','pcm_sha256','group_text','speaker_id'):
        owners={}
        for r in records:
            value=r.get(field)
            if value is None or value=='': continue
            if value in owners: uf.union(r['request_id'],owners[value])
            else: owners[value]=r['request_id']
    groups=collections.defaultdict(list)
    for i in ids: groups[uf.find(i)].append(i)
    return {k:sorted(v) for k,v in groups.items()}

def assign_groups(groups,protected,seed=SEED):
    mapping={}; meta={}
    for ids in groups.values():
        label='heldout_prior_evaluation' if set(ids)&protected else ('dev' if int(hashlib.sha256(f"{seed}\0{'|'.join(ids)}".encode()).hexdigest()[:16],16)<(1<<64)//10 else 'train')
        gid=hashlib.sha256('\n'.join(ids).encode()).hexdigest()[:16]
        for i in ids: mapping[i]=(label,gid)
        meta[gid]={'request_count':len(ids),'split':label}
    return mapping,meta

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True); args=parser.parse_args()
    import sentencepiece as spm
    if sha(BPE)!='289dbb44527c13c419ae3a4d8ce6a349f01a97f8777e69934a77e3692d2f10db': raise ValueError('tokenizer checksum mismatch')
    sp=spm.SentencePieceProcessor(model_file=str(BPE)); prior=json.loads(SPLIT.read_text());
    if sha(DATA)!=prior['dataset_sha256']: raise ValueError('dataset and family split mismatch')
    input_rows=[json.loads(line) for line in DATA.read_text(encoding='utf8').splitlines() if line.strip()]
    ids=[r['id'] for r in input_rows]
    if len(set(ids))!=len(ids) or set(ids)!=set(sum(prior['splits'].values(),[])): raise ValueError('duplicate or missing request IDs')
    if set(sum(prior['groups'],[]))!=set(ids) or len(sum(prior['groups'],[]))!=len(ids): raise ValueError('invalid family groups')
    p32={(x['id'],x['history_index'],x['audio']) for x in json.loads(FLAGS.read_text())}
    annotation=json.loads(ANNOT.read_text()); p13sha=sha(P13_MANIFEST)
    if annotation['manifest_sha256']!=p13sha: raise ValueError('P13 annotation manifest mismatch')
    reviewed={(x['id'],x['history_index'],x['audio']):x for x in annotation['annotations'] if x['status']=='verified' and x.get('listened')}
    records=[]; referenced=set(); seen_ids=set()
    for row in input_rows:
        rid=row['id']; clips=[(i,t.get('audio'),t.get('audio_text'),t.get('speaker_id')) for i,t in enumerate(row.get('history',[])) if t.get('role')=='user']
        clips.append((None,row.get('audio'),row.get('audio_text'),row.get('speaker_id')))
        for index,audio,text,speaker in clips:
            clip_id=f"{rid}:"+('latest' if index is None else f'history:{index}')
            if clip_id in seen_ids: raise ValueError('duplicate clip identity')
            seen_ids.add(clip_id); flags=[]; reasons=[]; info={}
            if isinstance(audio,str): referenced.add(audio)
            try:
                info=inspect_audio(ROOT/'train/audio',audio)
                if info['silent']: reasons.append('silent_audio')
                if info['clipped_fraction']>=.01: flags.append('clipping_at_least_1_percent')
                if info['duration_seconds']>30: flags.append('longer_than_30_seconds')
            except (OSError,ValueError,wave.Error,EOFError) as e: reasons.append('invalid_audio: '+str(e))
            try:
                norm=normalize(text)
                if not norm: reasons.append('empty_transcript')
                if any(unicodedata.category(ch)=='Cc' and ch not in '\t\n\r' for ch in text): reasons.append('control_character')
                ta=token_audit(norm,sp); upper=token_audit(norm.upper(),sp)
                if any(ch.isdecimal() for ch in norm): flags.append('contains_digit_spoken_form_unverified')
                if info.get('duration_seconds'):
                    rate=len(norm.split())/info['duration_seconds']
                    if rate<0.5 or rate>8: flags.append('extreme_text_to_duration_rate')
                else: rate=None
            except (TypeError,ValueError): norm=None;ta=None;upper=None;rate=None;reasons.append('missing_or_invalid_transcript')
            key=(rid,index,audio)
            if key in p32: flags.append('p32_reference_asr_disagreement')
            if rid=='train_0999': flags.append('requested_train_0999_review')
            note=None
            if key in reviewed:
                old=reviewed[key]
                if old.get('audio_sha256')!=info.get('pcm_sha256'): raise ValueError('P13 review PCM identity mismatch')
                note={'source':'results/p13_review_v1/annotations.json','status':'human_attested_listened','reference_not_replaced':True}
            records.append({'clip_id':clip_id,'request_id':rid,'history_index':index,'audio':audio,'original_text':text,'normalized_text':norm,'group_text':norm.casefold() if norm else None,'speaker_id':speaker,'text_tokens_per_second':rate,'tokenizer':ta,'uppercase_only_tokenizer_diagnostic':upper,'flags':flags,'invalid_reasons':reasons,'prior_audio_review':note,**info})
    if len(p32-{(r['request_id'],r['history_index'],r['audio']) for r in records}): raise ValueError('P32 review flag missing')
    bypcm=collections.defaultdict(list)
    for r in records:
        if r.get('pcm_sha256'): bypcm[r['pcm_sha256']].append(r)
    for group in bypcm.values():
        if len(group)<2: continue
        labels={r['normalized_text'] for r in group}
        if len(labels)>1:
            for r in group:r['invalid_reasons'].append('conflicting_transcripts_for_same_pcm')
        else:
            for r in sorted(group,key=lambda x:x['clip_id'])[1:]:r['invalid_reasons'].append('duplicate_pcm')
    groups=group_requests(ids,prior['groups'],records); protected=set(prior['splits']['validation']+prior['splits']['excluded']); assignment,group_meta=assign_groups(groups,protected)
    for r in records:
        r['split'],r['group_id']=assignment[r['request_id']]
        r['training_ready']=bool(not r['invalid_reasons'] and not r['flags'] and r['tokenizer'] and r['tokenizer']['compatible'] and r['split'] in ('train','dev'))
        r.pop('group_text',None)
    # Assert every boundary is disjoint for request, family, identical text, PCM, path, and explicit speaker.
    key_splits=collections.defaultdict(set)
    for r in records:
        for field,value in [('request',r['request_id']),('family',r['group_id']),('path',r.get('audio')),('pcm',r.get('pcm_sha256')),('text',r['normalized_text'].casefold() if r['normalized_text'] else None),('speaker',r.get('speaker_id'))]:
            if value is not None and value!='':key_splits[(field,value)].add(r['split'])
    conflicts=[(k,sorted(v)) for k,v in key_splits.items() if len(v)>1]
    if conflicts: raise ValueError(f'cross-split leakage: {conflicts[:3]}')
    orphans=sorted(str(p.relative_to(ROOT/'train')) for p in (ROOT/'train/audio').rglob('*.wav') if str(p.relative_to(ROOT/'train')) not in referenced)
    valid=[r for r in records if not r['invalid_reasons']]; split_counts={}
    for part in ('train','dev','heldout_prior_evaluation'):
        rr=[r for r in valid if r['split']==part]
        split_counts[part]={'clips':len(rr),'requests':len({r['request_id'] for r in rr}),'hours':sum(r['duration_seconds'] for r in rr)/3600,'groups':len({r['group_id'] for r in rr}),'unknown_token_clips':sum(not r['tokenizer']['compatible'] for r in rr),'training_ready':sum(r['training_ready'] for r in rr)}
    flagcounts=collections.Counter(x for r in records for x in r['flags']); invalid=collections.Counter(x for r in records for x in r['invalid_reasons']); meta={'dataset_sha256':sha(DATA),'family_split_sha256':sha(SPLIT),'tokenizer_sha256':sha(BPE),'p32_flags_sha256':sha(FLAGS),'p13_annotation_sha256':sha(ANNOT),'records':len(records),'requests':len(ids),'valid_unique_clips':len(valid),'valid_unique_requests':len({r['request_id'] for r in valid}),'valid_unique_duration_seconds':sum(r['duration_seconds'] for r in valid),'invalid_or_duplicate_records':sum(bool(r['invalid_reasons']) for r in records),'invalid_reasons':dict(invalid),'flagged_records':sum(bool(r['flags']) for r in records),'flags':dict(flagcounts),'prior_human_attested_clips':sum(bool(r['prior_audio_review']) for r in records),'normalization_changed':sum(r['original_text']!=r['normalized_text'] for r in records if r['normalized_text'] is not None),'unknown_literal':sum(bool(r['tokenizer'] and r['tokenizer']['unknown_tokens']) for r in records),'not_tokenizer_compatible':sum(bool(r['tokenizer'] and not r['tokenizer']['compatible']) for r in records),'unknown_uppercase_diagnostic':sum(bool(r['uppercase_only_tokenizer_diagnostic'] and r['uppercase_only_tokenizer_diagnostic']['unknown_tokens']) for r in records),'speaker_ids_present':sum(bool(r['speaker_id']) for r in records),'candidate_splits':split_counts,'prior_protected_request_count':len(protected),'extra_requests_linked_to_protected':sum(assignment[i][0]=='heldout_prior_evaluation' and i not in protected for i in ids),'groups':len(groups),'largest_group':max(map(len,groups.values())),'cross_split_conflicts':len(conflicts),'unreferenced_wavs':len(orphans),'unreferenced_wav_paths':orphans,'seed':SEED,'quality':'structural validity only; speech/reference correctness not inferred','training_decision':'NO-GO: exact normalized labels are not tokenizer-compatible; acoustic and speaker checks incomplete'}
    args.output.mkdir(parents=True,exist_ok=False)
    def write(name,rows):
        with (args.output/name).open('x',encoding='utf8') as f:
            for r in rows:f.write(json.dumps(r,ensure_ascii=False)+'\n')
    write('inventory.jsonl',records)
    for part in split_counts:write(part+'.jsonl',[r for r in valid if r['split']==part])
    write('excluded.jsonl',[r for r in records if r['invalid_reasons']])
    write('review_queue.jsonl',[r for r in records if r['flags'] or r['prior_audio_review']])
    write('training_ready.jsonl',[r for r in records if r['training_ready']])
    (args.output/'summary.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    (args.output/'groups.json').write_text(json.dumps(group_meta,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(meta,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
