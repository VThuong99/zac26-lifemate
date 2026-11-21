"""Combine guarded temporal hints with exact unique direct-chat evidence."""
from experiments.continuous_improvement.combined_temporal_v1.combined import apply_annotated_request
from experiments.continuous_improvement.unique_chat_binding_v2.binding import intervene as chat_intervene
def intervene(req):return chat_intervene(apply_annotated_request(req))
