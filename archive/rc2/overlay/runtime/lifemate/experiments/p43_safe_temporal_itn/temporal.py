"""P42 annotation grammar with additional fail-closed context checks.

This module adds no supported clock expression; all normalization and output
formatting remain P42's frozen implementation. No dates or actions are inferred.
"""
import re
from experiments.p42_temporal_itn.temporal import annotate as p42_annotate

# Require exactly the daypart within the recognized span. Additional dayparts,
# including incomplete/relative expressions, can change the interpretation.
_DAYPART=re.compile(r'(?<!\w)(?:sáng|chiều|tối|trưa|đêm|khuya|rạng\s+sáng)(?!\w)',re.I)
_CORRECTION=re.compile(r'(?<!\w)(?:hông|hổng|hong|hem|khum|nhầm|sửa|đính\s+chính|ý\s+tôi\s+là|ý\s+là|nói\s+lại|thực\s+ra|thật\s+ra)(?!\w)',re.I)
_UNCLEAR_ANCHOR=re.compile(r'(?<!\w)(?:trước|sau|sớm|muộn|trễ|cỡ|chừng|quanh|xấp\s+xỉ|lần\s+nào|khi\s+nào)(?!\w)',re.I)
_NUMBER=r'(?:không|một|mốt|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|mười|mươi|trăm|linh|lẻ|nửa|rưỡi|\d+)'
_ADJACENT_PREFIX=re.compile(r'(?<!\w)'+_NUMBER+r'\s*$',re.I)
_ADJACENT_SUFFIX=re.compile(r'^\s*(?:'+_NUMBER+r'|phút|giờ|kém|hơn)(?!\w)',re.I)

def annotate(text):
    if not isinstance(text,str):raise TypeError('text must be a string')
    empty={'text':text,'annotations':[]}
    if _CORRECTION.search(text) or _UNCLEAR_ANCHOR.search(text):return empty
    result=p42_annotate(text)
    if not result['annotations']:return empty
    span=result['annotations'][0];parts=list(_DAYPART.finditer(text))
    if len(parts)!=1 or not(span['start']<=parts[0].start() and parts[0].end()<=span['end']):return empty
    if _ADJACENT_PREFIX.search(text[:span['start']]) or _ADJACENT_SUFFIX.search(text[span['end']:]):return empty
    return result
