"""P19 controller that substitutes a validated, read-only menu lookup."""
from src.agent import Agent
from experiments.continuous_improvement.gold_price_comparison_v1.observation import context_with_evidence
from experiments.continuous_improvement.gold_branch_reminder_guard_v1.guard import repair
from experiments.continuous_improvement.weather_false_branch_stop_v1.guard import stop
from experiments.continuous_improvement.wallet_vague_amount_guard_v2.guard import repair as missing_amount_repair
from experiments.continuous_improvement.missed_callback_ambiguity_v1.guard import repair as callback_repair
from experiments.continuous_improvement.bill_threshold_workflow_v3.guard import repair as bill_repair
from experiments.continuous_improvement.qr_branch_ambiguity_v1.guard import repair as qr_repair
from experiments.continuous_improvement.qr_history_ambiguity_v1.guard import repair as history_qr_repair
from experiments.continuous_improvement.light_fan_exception_guard_v2.guard import repair as light_repair
from experiments.continuous_improvement.library_history_binding_v1.binding import derive as library_derive, effect_confirmed as library_effect_confirmed
from experiments.continuous_improvement.delivery_branch_stop_v1.guard import stop as delivery_stop
class DeliveryComposedAgent(Agent):
 def run(self,text,context,prior_history=None):
  if prior_history is None:prior_history=[]
  if not isinstance(prior_history,list):raise TypeError('prior history must be a list')
  planner_history=list(prior_history);history=[];started=self.clock()
  for _ in range(self.max_steps):
   remaining=None
   if self.sample_timeout is not None:
    remaining=self.sample_timeout-(self.clock()-started)
    if remaining<=0:return self._timeout(history)
   decision_context=context_with_evidence(text,context,history)
   action=self.planner.next_action(text,decision_context,planner_history) if remaining is None else self.planner.next_action(text,decision_context,planner_history,timeout=remaining)
   if self.sample_timeout is not None and self.clock()-started>=self.sample_timeout:return self._timeout(history)
   if not isinstance(action,dict):raise TypeError('planner must return a dictionary')
   names={x.get('name') for x in self.planner.tools if isinstance(x,dict)}
   bill_replacement=bill_repair(text,context,history,action,names)
   if bill_replacement:
    if self.trace_sink is not None:self.trace_sink({'type':'bill_workflow_replaced','proposal':action,'replacement':bill_replacement})
    action=bill_replacement['action']
   if action.get('type')=='finish':return {'status':'finished','history':history}
   if action.get('type')!='call':raise ValueError('unknown action type')
   delivery_proof=delivery_stop(text,history,action)
   if delivery_proof:
    if self.trace_sink is not None:self.trace_sink({'type':'delivery_branch_stopped','proposal':action,'proof':delivery_proof})
    return {'status':'finished','history':history}
   weather=stop(text,context,history,action)
   if weather:
    if self.trace_sink is not None:self.trace_sink({'type':'weather_branch_stopped','proposal':action,'replacement':weather})
    return {'status':'finished','history':history}
   names={x.get('name') for x in self.planner.tools if isinstance(x,dict)};replacement=repair(text,context,history,action,names)
   if replacement:
    if self.trace_sink is not None:self.trace_sink({'type':'gold_branch_replaced','proposal':action,'replacement':replacement})
    action=replacement['action']
    if action['type']=='finish':return {'status':'finished','history':history}
   amount_replacement=missing_amount_repair(text,context,prior_history,history,action,names)
   if amount_replacement:
    if self.trace_sink is not None:self.trace_sink({'type':'wallet_amount_replaced','proposal':action,'replacement':amount_replacement})
    action=amount_replacement['action']
   callback_replacement=callback_repair(text,prior_history,history,action,names)
   if callback_replacement:
    if self.trace_sink is not None:self.trace_sink({'type':'callback_ambiguity_replaced','proposal':action,'replacement':callback_replacement})
    action=callback_replacement['action']
   qr_replacement=qr_repair(text,prior_history,history,action,names)
   if qr_replacement:
    if self.trace_sink is not None:self.trace_sink({'type':'qr_branch_replaced','proposal':action,'replacement':qr_replacement})
    action=qr_replacement['action']
   history_qr_replacement=history_qr_repair(text,prior_history,history,action,names)
   if history_qr_replacement:
    if self.trace_sink is not None:self.trace_sink({'type':'qr_history_replaced','proposal':action,'replacement':history_qr_replacement})
    action=history_qr_replacement['action']
   light_replacement=light_repair(text,history,action,names)
   if light_replacement:
    if self.trace_sink is not None:self.trace_sink({'type':'light_fan_replaced','proposal':action,'replacement':light_replacement})
    action=light_replacement['action']
   library_replacement=library_derive(text,prior_history,history,action,names)
   if library_replacement:
    if self.trace_sink is not None:self.trace_sink({'type':'library_binding_replaced','proposal':action,'replacement':library_replacement})
    action=library_replacement['action']
   if self.sample_timeout is not None and self.clock()-started>=self.sample_timeout:return self._timeout(history)
   result=self.controller.execute(action);step={'action':action,'result':result};history.append(step);planner_history.append(step)
   if self.trace_sink is not None:self.trace_sink({'type':'tool_result','action':action,'result':result})
   if not result.get('ok'):return {'status':'tool_error','history':history}
   if library_replacement and not library_effect_confirmed(result,action):return {'status':'binding_effect_unverified','history':history}
   if (amount_replacement or callback_replacement or qr_replacement or history_qr_replacement) and result.get('waiting_for_user') is True:return {'status':'finished','history':history}
  return {'status':'max_steps','history':history}
