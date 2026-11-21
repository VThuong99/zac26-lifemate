"""Independent, intentionally narrow Vietnamese clock-span annotation.

Input is the already formatted latest P34 transcript. History is never touched.
No date, event, object, or tool argument is inferred.
"""
import re

_HOURS={'một':1,'hai':2,'ba':3,'bốn':4,'năm':5,'sáu':6,'bảy':7,'tám':8,'chín':9,'mười':10,'mười một':11,'mười hai':12}
_MINUTES={'năm':5,'mười':10,'mười lăm':15,'hai mươi':20,'ba mươi':30,'bốn mươi lăm':45}
_H=r'(?:mười\s+(?:một|hai)|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|1[0-2]|[1-9])'
_M=r'(?:bốn\s+mươi\s+lăm|ba\s+mươi|hai\s+mươi|mười\s+lăm|mười|năm|45|30|20|15|10|5)'
_TIME=re.compile(r'(?<!\w)(?P<h>'+_H+r')\s+giờ(?:\s+(?:(?P<half>rưỡi)|(?P<minus>kém)\s+(?P<mm>'+_M+r')|(?P<plus>'+_M+r'))(?:\s+phút)?)?\s+(?P<period>sáng|chiều|tối)(?!\w)',re.I)
_MARKERS=re.compile(r'(?<!\w)(?:giờ|\d{1,2}\s*:\s*\d{2}|\d{1,2}\s*h\s*\d{0,2})(?!\w)',re.I)
_NEGATION_OR_REVISION=re.compile(r'(?<!\w)(?:không|chưa|chẳng|chả|đừng|chớ|khỏi|hủy|huỷ|sai|nhầm|sửa|thay|đổi|chuyển|dời|lùi|hoãn|hoặc|hay|nhưng|chứ|mà|trừ|khoảng|tầm|gần|chừng|hơn|ý\s+là|nói\s+lại|đính\s+chính|thay\s+vì)(?!\w)',re.I)
_RANGE=re.compile(r'(?<!\w)từ\b.{0,100}\b(?:đến|tới|cho\s+đến)\b',re.I|re.S)
_NUM_PREFIX=re.compile(r'(?<!\w)(?:mười|mươi|trăm|nghìn|ngàn|\d)\s*$',re.I)
_ALT_TIME=re.compile(r'(?<!\w)'+_H+r'\s+rưỡi(?!\w)',re.I)
_BARE_TIME=re.compile(r'(?<!\w)'+_H+r'\s+(?:sáng|chiều|tối)(?!\w)',re.I)

def annotate(text):
    """Return unchanged input plus at most one literal span and HH:MM annotation."""
    if not isinstance(text,str): raise TypeError('text must be a string')
    empty={'text':text,'annotations':[]}
    if _NEGATION_OR_REVISION.search(text) or _RANGE.search(text): return empty
    if len(list(_MARKERS.finditer(text))) != 1: return empty
    matches=list(_TIME.finditer(text))
    if len(matches)!=1 or _ALT_TIME.search(text): return empty
    match=matches[0]
    if any(m.end()<=match.start() or m.start()>=match.end() for m in _BARE_TIME.finditer(text)): return empty
    if _NUM_PREFIX.search(text[:match.start()]): return empty
    hstr=' '.join(match.group('h').lower().split()); hour=int(hstr) if hstr.isdecimal() else _HOURS[hstr]
    period=match.group('period').lower()
    # Skip twelve and atypical cue/hour combinations instead of guessing.
    if period=='sáng' and 1<=hour<=11: hour24=hour
    elif period=='chiều' and 1<=hour<=6: hour24=hour+12
    elif period=='tối' and 6<=hour<=11: hour24=hour+12
    else: return empty
    part=match.group('mm') or match.group('plus')
    if match.group('half'): minute=30
    elif part:
        key=' '.join(part.lower().split()); minute=int(key) if key.isdecimal() else _MINUTES[key]
    else: minute=0
    if match.group('minus'):
        if not 0<minute<60: return empty
        total=hour24*60-minute
    else: total=hour24*60+minute
    if not 0<=total<24*60: return empty
    value=f'{total//60:02d}:{total%60:02d}';span=text[match.start():match.end()]
    annotation={'start':match.start(),'end':match.end(),'span':span,'time':value}
    return {'text':text+f'\n[Giờ chuẩn hóa: "{span}" = {value}]','annotations':[annotation]}
