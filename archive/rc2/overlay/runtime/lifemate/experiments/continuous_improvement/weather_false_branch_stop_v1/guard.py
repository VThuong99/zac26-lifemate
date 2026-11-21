"""Stop a dry-weather path only when the whole user request says do nothing."""
import datetime as dt
import re
import unicodedata
PATTERN=re.compile(r'^\s*(?:nếu\s+)?mai(?:\s+mà)?\s+mưa\s+thì\s+(.{1,350}?)\s+(?:còn\s+)?(?:không|hông)\s+mưa\s+thì\s+thôi(?:\s+(?:nhé|nha|ạ|nghe))?[\s.!?]*$',re.I)

def norm(s):return re.sub(r'\s+',' ',unicodedata.normalize('NFC',s).casefold()).strip() if isinstance(s,str) else ''

def stop(text,context,history,proposal):
 if not isinstance(text,str) or not isinstance(context,dict) or not isinstance(history,list) or not isinstance(proposal,dict):return None
 if proposal.get('type')!='call':return None
 match=PATTERN.fullmatch(unicodedata.normalize('NFC',text))
 if not match:return None
 body=norm(match.group(1))
 if re.search(r'\b(?:nếu|thì|trừ|ngoài\s+ra|ngoài\s+việc|đồng\s+thời|dù\s+sao)\b',body):return None
 if len(history)!=1:return None
 try:
  now=dt.datetime.fromisoformat(context['current_time']);assert now.utcoffset() is not None
  tomorrow=(now.date()+dt.timedelta(days=1)).isoformat();city=norm(context['user_profile']['city']);assert city
  step=history[0];action=step['action'];result=step['result'];args=action['arguments']
  assert action['name']=='weather.get_forecast' and result['ok'] is True and args['date']==tomorrow
  location=norm(args.get('location'));assert not location or location==city
  forecasts=result['forecast'];assert isinstance(forecasts,list) and len(forecasts)==1
  f=forecasts[0];assert f['date']==tomorrow and norm(f['location'])==city and f['rain'] is False
 except (AssertionError,KeyError,TypeError,ValueError):return None
 return {'kind':'verified_dry_branch_is_noop','action':{'type':'finish'},'forecast_date':tomorrow,'forecast_location':f['location']}
