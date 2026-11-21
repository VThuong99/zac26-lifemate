"""Repair a single pending eligible light before an excluded-light or AC proposal."""
import re
from experiments.continuous_improvement.light_fan_exception_guard_v1.guard import norm,FLOORS,FLOOR,NUM
REQUEST=re.compile(rf'^tắt(?:\s+giúp\s+(?:anh|chị|em|tôi|mình))?\s+(?:hết|toàn\s+bộ)\s+đèn\s+(?:ở\s+)?tầng\s+(?P<floor>{FLOOR})(?:\s+giúp\s+(?:anh|chị|em|tôi|mình))?\s+trừ\s+phòng\s+nào\s+(?:đang\s+bật\s+quạt|quạt\s+đang\s+chạy)\s+thì\s+(?:cứ\s+)?(?:để\s+đèn\s+đó|để\s+nguyên\s+đèn|để\s+sáng)(?:\s+(?:nhé|nha|ạ))?(?:\s+(?:rồi|xong)\s+bật\s+điều\s+(?:hòa|hoà)\s+phòng\s+ngủ\s+(?P<temperature>{NUM}(?:\s+{NUM})*)\s+độ(?:\s+(?:nhé|nha|ạ))?)?[\s.!?]*$',re.I)
ONES={'một':1,'mốt':1,'hai':2,'ba':3,'bốn':4,'tư':4,'năm':5,'lăm':5,'sáu':6,'bảy':7,'tám':8,'chín':9}

def temperature(s):
 s=norm(s)
 if re.fullmatch(r'\d{2}',s):value=int(s)
 elif s=='hai lăm':value=25
 elif s=='hai mươi':value=20
 elif s.startswith('hai mươi ') and s[9:] in ONES:value=20+ONES[s[9:]]
 elif s=='ba mươi':value=30
 elif s.startswith('mười ') and s[5:] in ONES:value=10+ONES[s[5:]]
 else:return None
 return value if 16<=value<=30 else None

def repair(text,history,proposal,names):
 if not isinstance(text,str) or not isinstance(history,list) or not isinstance(proposal,dict) or not isinstance(names,set):return None
 if proposal.get('type')!='call' or proposal.get('name') not in ('smart_home.light_set','smart_home.climate_set') or 'smart_home.light_set' not in names:return None
 m=REQUEST.fullmatch(norm(text));args=proposal.get('arguments')
 if not m or not isinstance(args,dict):return None
 light=proposal['name']=='smart_home.light_set'
 if light and (set(args)!={'device_id','power'} or args.get('power')!='off'):return None
 expected_temp=temperature(m.group('temperature')) if m.group('temperature') else None
 if not light and (expected_temp is None or set(args)!={'device_id','mode','temperature'} or args.get('mode')!='cool' or isinstance(args.get('temperature'),bool) or args.get('temperature')!=expected_temp):return None
 floor=FLOORS[m.group('floor')];reads=[(i,z) for i,z in enumerate(history) if isinstance(z,dict) and isinstance(z.get('action'),dict) and z['action'].get('name')=='smart_home.get_status']
 if len(reads)!=1:return None
 idx,step=reads[0];r=step.get('result')
 if idx!=0 or step['action'].get('arguments')!={} or not isinstance(r,dict) or r.get('ok') is not True or not isinstance(r.get('devices'),list):return None
 devices={};fans={};lights={};climates=[]
 for x in r['devices']:
  if not isinstance(x,dict) or x.get('type') not in ('light','fan','climate'):continue
  f=x.get('floor');room=norm(x.get('room'));state=x.get('state');id_=x.get('id')
  if not isinstance(f,int) or isinstance(f,bool) or not room or not isinstance(state,dict) or not isinstance(id_,str) or not id_ or id_ in devices:return None
  devices[id_]=x
  if x['type']=='climate':
   if room=='phòng ngủ':climates.append(id_)
   continue
  power=state.get('power')
  if power not in ('on','off'):return None
  if f!=floor:continue
  if x['type']=='fan':fans.setdefault(room,[]).append(power)
  else:lights[id_]={'id':id_,'room':room,'power':power}
 target=lights.get(args.get('device_id')) if light else None
 if light and (target is None or 'on' not in fans.get(target['room'],[])):return None
 if not light and (len(climates)!=1 or args.get('device_id')!=climates[0]):return None
 eligible={i:z for i,z in lights.items() if 'on' not in fans.get(z['room'],[]) and z['power']=='on'};completed=set()
 for z in history[idx+1:]:
  if not isinstance(z,dict) or not isinstance(z.get('action'),dict) or z['action'].get('name')!='smart_home.light_set':return None
  a=z['action'].get('arguments');res=z.get('result')
  if not isinstance(a,dict) or set(a)!={'device_id','power'} or a.get('power')!='off' or a.get('device_id') not in eligible or a['device_id'] in completed or not isinstance(res,dict) or res.get('ok') is not True:return None
  item=res.get('item')
  if not isinstance(item,dict) or item.get('id')!=a['device_id'] or not isinstance(item.get('state'),dict) or item['state'].get('power')!='off':return None
  completed.add(a['device_id'])
 pending=sorted(set(eligible)-completed)
 if len(pending)!=1:return None
 action={'type':'call','name':'smart_home.light_set','arguments':{'device_id':pending[0],'power':'off'}}
 if light:return {'kind':'replace_excluded_light_with_unique_eligible','action':action,'observed_excluded_room':target['room'],'observed_excluded_light':args['device_id'],'observed_eligible_light':pending[0],'floor':floor}
 return {'kind':'defer_matching_ac_for_unique_eligible_light','action':action,'observed_climate_id':climates[0],'spoken_temperature':expected_temp,'observed_eligible_light':pending[0],'floor':floor}
