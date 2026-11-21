"""CPU-only input-length screening, not inference or an exact runtime prompt.

Uses the packaged base planner, with an empty latest transcript and original
audio-bearing history. ASR text, runtime annotations, and new tool observations
are absent, so these lengths cannot certify that a request fits at runtime.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ['USE_TORCH'] = '0'
os.environ['USE_TF'] = '0'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'lifemate-private-rc2-host-20261120'))
import run_private_test as host
from check_results import read, rows, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    host.require(not args.output.exists(), 'Output already exists')
    host.load_verifier(ROOT)
    rc = ROOT / 'lifemate-final-20261116-rc2'
    model = ROOT / 'lifemate/experiments/continuous_improvement/p19_champion_q8_v1/p19_q8.gguf'
    expected = next(x['sha256'] for x in read(rc / 'overlay/manifests/models.json') if x['path'].endswith('/p19_q8.gguf'))
    host.require(sha(model) == expected, 'Local GGUF differs from the frozen image manifest')
    sys.path.insert(0, str(ROOT / 'third_party/llama.cpp-p9-8ca4060b/gguf-py'))
    from gguf import GGUFReader
    from transformers import AutoTokenizer
    gguf = GGUFReader(model, 'r')  # Read-only metadata/memory map; no tensor computation.
    template = gguf.fields['tokenizer.chat_template'].contents()
    tokenizer_path = ROOT / 'models/qwen35-4b-source-851bf6e806efd8'
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True)

    def tokens(messages):
        rendered = tokenizer.apply_chat_template(messages, chat_template=template, tokenize=False,
                                                add_generation_prompt=True, enable_thinking=False)
        return len(tokenizer.encode(rendered, add_special_tokens=False))

    verified = 0
    pilot = rc / 'runs/20261116T143345Z-pilot-65KOaw/submission.diagnostics'
    for path in sorted(pilot.glob('*.result.json')):
        for request in read(path)['requests']:
            host.require(tokens(request['request']['messages']) == request['prompt_tokens'],
                         'Offline token count does not match recorded RC2 server usage')
            verified += 1
    host.require(verified == 44, 'Unexpected recorded pilot request count')
    bundle = rc / 'overlay/runtime/lifemate/results/p19_submission_staging_v1'
    sys.path.insert(0, str(bundle))
    from src.llm_planner import LLMPlanner
    from src.tool_catalog import load_available_tools
    from src.tool_schema_formatter import compact_tools
    split = ROOT / 'lifemate/results/private_test_k48_46_rc2_audit_20261120T114547Z/dataset/private_test'
    host.require(sha(split / 'private_test.jsonl') == host.INPUT_SHA, 'Private input changed')
    host.require(sha(split / 'private_test_tools_catalog.json') == host.CATALOG_SHA, 'Private catalog changed')
    prompt = (bundle / 'prompts/explicit_stopping.txt').read_text().strip()
    result = []
    for index, item in enumerate(rows(split / 'private_test.jsonl')):
        tools = load_available_tools(split.parent, split.name, item['context'])
        planner = LLMPlanner(tools, tool_formatter=compact_tools, system_prompt=prompt)
        messages = planner._custom_messages('', item['context'], item['history'])
        result.append({'index': index, 'id': item['id'], 'static_base_prompt_tokens': tokens(messages),
                       'base_without_history_tokens': tokens(planner._custom_messages('', item['context'], [])),
                       'history_turns': len(item['history']),
                       'history_user_audio_clips': sum(t.get('role') == 'user' and 'audio' in t for t in item['history']),
                       'history_tool_results': sum(len(t.get('tool_results', [])) for t in item['history']),
                       'available_tool_schemas': len(tools)})
    report = {'method': __doc__, 'gpu_or_model_inference': False, 'toolenv_instances': 0,
              'model_sha256': expected, 'input_sha256': host.INPUT_SHA,
              'tokenizer_json_sha256': sha(tokenizer_path / 'tokenizer.json'),
              'gguf_chat_template_sha256': hashlib.sha256(template.encode()).hexdigest(),
              'gguf_architecture': gguf.fields['general.architecture'].contents(),
              'gguf_training_context_length': gguf.fields['qwen35.context_length'].contents(),
              'recorded_server_token_counts_matched': verified,
              'screen_at_or_above_8192': [r['id'] for r in result if r['static_base_prompt_tokens'] >= 8192],
              'screen_at_or_above_7500': [r['id'] for r in result if r['static_base_prompt_tokens'] >= 7500],
              'largest_15_static_base_prompts': sorted(result, key=lambda r: -r['static_base_prompt_tokens'])[:15],
              'candidate_failure': result[323], 'requests': result}
    write(args.output, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'requests'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
