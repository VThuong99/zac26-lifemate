"""Reference-anchored binary preference at one verified differing token."""
import torch
import torch.nn.functional as F

def branch_preference(logits,chosen_id,rejected_id,reference_margin,beta=1.0):
    if logits.ndim!=1 or not (0<=chosen_id<logits.numel()) or not (0<=rejected_id<logits.numel()) or chosen_id==rejected_id:
        raise ValueError('invalid single-token contrast')
    if not isinstance(reference_margin,(int,float)) or not torch.isfinite(torch.tensor(reference_margin)) or beta<=0:
        raise ValueError('invalid reference margin or beta')
    margin=logits[chosen_id].float()-logits[rejected_id].float()
    return -F.logsigmoid(beta*(margin-reference_margin))
