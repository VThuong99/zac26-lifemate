"""Describe text-search fields using only the executor's real matching contract."""
import copy,json
_FIELDS={
 'bike_rental.find_bikes':{'near':'Tìm theo tên trạm, khu vực hoặc tên xe; không tra cứu theo ID địa điểm từ công cụ khác.'},
 'contacts.search':{'query':'Tìm theo tên, quan hệ hoặc số điện thoại; không tra cứu theo ID của thực thể.'},
 'library.search':{'query':'Tìm theo tên sách hoặc tác giả; không tra cứu theo ID của thực thể.'},
 'maps.search_place':{'query':'Tìm theo từ khóa tên, loại, mô tả hoặc địa chỉ; không tra cứu theo ID địa điểm.','near':'Lọc theo từ khóa địa chỉ, mô tả hoặc tên; không tra cứu theo ID địa điểm.'}}
def intervene(request):
 q=copy.deepcopy(request)
 try:
  m=q['messages'][1]
  if m.get('role')!='user':return q
  p=json.loads(m['content']);tools=p.get('available_tools')
  if not isinstance(tools,list):return q
  for t in tools:
   if not isinstance(t,dict):continue
   fields=_FIELDS.get(t.get('name'),{});props=t.get('properties')
   if not isinstance(props,dict):continue
   for name,note in fields.items():
    v=props.get(name)
    if isinstance(v,dict):
     desc=v.get('description','')
     if isinstance(desc,str) and note not in desc:v['description']=(desc+' '+note).strip()
  m['content']=json.dumps(p,ensure_ascii=False)
 except (KeyError,IndexError,TypeError,ValueError):return copy.deepcopy(request)
 return q
