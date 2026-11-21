"""Augment message-content schema with a general grounded-content instruction."""
import copy,json
NOTE=('Nội dung tin phải đúng chủ đề và thời gian người dùng yêu cầu; '
      'nếu phụ thuộc dữ liệu khác, dùng kết quả công cụ đã quan sát. '
      'Không tự bịa chi tiết chưa được xác nhận.')
def intervene(request):
 out=copy.deepcopy(request);payload=json.loads(out['messages'][1]['content']);changed=False
 for tool in payload['available_tools']:
  if tool.get('name') in ('sms.send','chat_ott.send_message'):
   content=tool.get('properties',{}).get('content')
   if isinstance(content,dict):
    old=content.get('description','');content['description']=(old+' '+NOTE).strip();changed=True
 if not changed:return request
 out['messages'][1]['content']=json.dumps(payload,ensure_ascii=False);return out
