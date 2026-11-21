"""Reconstruct the FIRST planner request from recorded ASR, using pure RC2 code.

No models, sockets or ToolEnv are used. This is diagnostic reconstruction, not
a captured failed HTTP payload. Later planner/review calls need their full
execution history and are deliberately not inferred here.
"""
import copy
import sys


def first_messages(item, receipt, frozen_runtime, split):
    bundle = frozen_runtime / 'results/p19_submission_staging_v1'
    sys.path[:0] = [str(bundle), str(frozen_runtime)]
    from src.llm_planner import LLMPlanner
    from src.tool_catalog import load_available_tools
    from src.tool_schema_formatter import compact_tools
    from src.p14_formatting import normalize_format
    from experiments.p43_safe_temporal_itn.temporal import annotate
    from experiments.continuous_improvement.temporal_chat_wallet_v1.compose import intervene as candidate
    from experiments.continuous_improvement.weekday_temporal_scope_v3.anchor import intervene as weekday
    from experiments.continuous_improvement.colloquial_clock_scope_v4.compose import intervene as eligibility
    from experiments.continuous_improvement.corroborated_digit_evidence_q8_v1.compose import intervene as digit
    from experiments.continuous_improvement.secondary_digit_consensus_screen_v1.compose import intervene as secondary
    from experiments.continuous_improvement.finish_consistent_review_e2e_v1.compose import intervene as pair

    history = copy.deepcopy(item['history'])
    clips = receipt['transcripts']
    expected = [(i, t['audio']) for i, t in enumerate(history) if t.get('role') == 'user' and 'audio' in t]
    expected.append((None, item['audio']))
    if [(c.get('history_index'), c.get('audio')) for c in clips] != expected:
        raise ValueError('Saved ASR clips do not cover the complete original input in order')
    for clip in clips[:-1]:
        turn = history[clip['history_index']]
        turn.pop('text', None)
        turn['audio_text'] = clip['text']
    text = annotate(normalize_format(clips[-1]['text']))['text']
    tools = load_available_tools(split.parent, split.name, item['context'])
    prompt = (bundle / 'prompts/explicit_stopping.txt').read_text().strip()
    messages = LLMPlanner(tools, tool_formatter=compact_tools, system_prompt=prompt)._custom_messages(text, item['context'], history)
    independent = {e['source']: e['independent'] for e in receipt['acoustic_evidence'] if 'independent' in e}
    ctc = {e['source']: e['ctc'] for e in receipt['ctc_evidence'] if 'ctc' in e}
    request = {'messages': messages}
    for compose in (candidate, weekday, eligibility):
        request = compose(request)
    request = digit(request, independent)
    request = secondary(request, independent, ctc)
    return pair(request)['messages']
