"""Offline audio input and timing around the unchanged P9 agent."""

import copy
import time
from pathlib import Path

from src.agent import Agent
from src.llm_planner import LLMPlanner
from src.tool_catalog import load_available_tools
from src.tool_schema_formatter import compact_tools


class GipformerASR:
    def __init__(self, model_dir: Path, num_threads: int = 4):
        if num_threads < 1:
            raise ValueError("num_threads must be positive")
        import sherpa_onnx

        model_dir = Path(model_dir)
        paths = {name: model_dir / filename for name, filename in {
            "encoder": "encoder.onnx", "decoder": "decoder.onnx",
            "joiner": "joiner.onnx", "tokens": "tokens.txt",
        }.items()}
        for path in paths.values():
            if not path.is_file():
                raise FileNotFoundError(f"Missing ASR model file: {path}")
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            **{name: str(path) for name, path in paths.items()},
            num_threads=num_threads, sample_rate=16000, feature_dim=80,
            decoding_method="greedy_search", provider="cpu",
        )

    def transcribe(self, audio_path: Path) -> dict:
        import soundfile as sf

        started = time.perf_counter()
        samples, rate = sf.read(audio_path, dtype="float32", always_2d=False)
        if rate != 16000 or samples.ndim != 1 or len(samples) == 0:
            raise ValueError(f"Expected nonempty mono 16 kHz audio: {audio_path}")
        stream = self.recognizer.create_stream()
        stream.accept_waveform(rate, samples)
        self.recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        if not text:
            raise ValueError(f"ASR returned an empty transcript: {audio_path}")
        return {
            "text": text, "audio_seconds": len(samples) / rate,
            "seconds": time.perf_counter() - started,
        }


def inference_input(row: dict) -> dict:
    """Keep only organizer inputs; never pass a training label to the agent."""
    item = {key: copy.deepcopy(row[key]) for key in ("id", "audio", "context", "history")}
    for turn in item["history"]:
        if turn.get("role") == "user" and "audio" in turn:
            turn.pop("audio_text", None)
            turn.pop("text", None)
    return item


def audio_path(root: Path, split: str, relative: str) -> Path:
    if not isinstance(relative, str):
        raise TypeError("Audio path must be a string")
    base = (root / split / "audio").resolve()
    path = (root / split / relative).resolve()
    if not path.is_relative_to(base) or path.suffix.lower() != ".wav":
        raise ValueError(f"Audio path must be a WAV inside the split audio directory: {relative}")
    if not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {path}")
    return path


def transcribe_input(item: dict, root: Path, split: str, asr) -> tuple[str, list, list]:
    history = copy.deepcopy(item["history"])
    if not isinstance(history, list):
        raise TypeError("Conversation history must be a list")
    clips = []
    for index, turn in enumerate(history):
        if not isinstance(turn, dict):
            raise TypeError("Conversation turns must be objects")
        if turn.get("role") != "user":
            continue
        if "audio" in turn:
            turn.pop("audio_text", None)
            turn.pop("text", None)
            result = asr.transcribe(audio_path(root, split, turn["audio"]))
            turn["audio_text"] = result["text"]
            clips.append({"history_index": index, "audio": turn["audio"], **result})
        elif "audio_text" in turn:
            raise ValueError("User audio_text without audio would leak a reference transcript")
        elif not isinstance(turn.get("text"), str):
            raise ValueError("User history turn requires audio or text")
    result = asr.transcribe(audio_path(root, split, item["audio"]))
    clips.append({"history_index": None, "audio": item["audio"], **result})
    return result["text"], history, clips


class TimedEnv:
    def __init__(self, env):
        self.env = env
        self.validation_seconds = 0.0
        self.call_seconds = 0.0

    def validate(self, name, arguments):
        started = time.perf_counter()
        try:
            return self.env.validate(name, arguments)
        finally:
            self.validation_seconds += time.perf_counter() - started

    def call(self, name, arguments):
        started = time.perf_counter()
        try:
            return self.env.call(name, arguments)
        finally:
            self.call_seconds += time.perf_counter() - started


def run_trajectory(item, text, history, root, split, tool_env, client, prompt,
                   timeout, max_steps=7, started=None):
    """Run one trajectory with exactly one newly-created organizer ToolEnv."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    started = time.perf_counter() if started is None else started
    setup_started = time.perf_counter()
    env = TimedEnv(tool_env(split, item["id"], root=root))
    tools = load_available_tools(root, split, item["context"])
    setup_seconds = time.perf_counter() - setup_started
    events = []
    planner = LLMPlanner(
        tools, client=client, tool_formatter=compact_tools, system_prompt=prompt,
        trace_sink=events.append,
    )
    remaining = timeout - (time.perf_counter() - started)
    error = None
    if remaining <= 0:
        result = {"status": "timeout", "history": []}
        agent_seconds = 0.0
    else:
        agent_started = time.perf_counter()
        try:
            result = Agent(planner, env, max_steps=max_steps, trace_sink=events.append,
                           sample_timeout=remaining).run(text, item["context"], history)
        except (TimeoutError, ConnectionError, RuntimeError, TypeError, ValueError) as exc:
            result = {"status": "timeout" if isinstance(exc, TimeoutError) else "inference_error"}
            error = f"{type(exc).__name__}: {exc}"
        agent_seconds = time.perf_counter() - agent_started
    hash_started = time.perf_counter()
    prediction = {"id": item["id"], "tool_calls": env.env.get_tool_calls(),
                  "state_hash": env.env.get_state_hash()}
    hash_seconds = time.perf_counter() - hash_started
    total = time.perf_counter() - started
    status = "timeout" if total >= timeout else result["status"]
    decision_seconds = sum(e["metrics"]["wall_ms"] / 1000 for e in events
                           if e["type"] == "llm_decision")
    return {
        "status": status, "error": error, "prediction": prediction, "events": events,
        "timing": {
            "setup_seconds": setup_seconds, "agent_seconds": agent_seconds,
            "decision_seconds": decision_seconds,
            "tool_validation_seconds": env.validation_seconds,
            "tool_call_seconds": env.call_seconds, "hash_seconds": hash_seconds,
            "total_seconds": total,
        },
    }


def run_audio(item, root, split, asr, tool_env, client, prompt, timeout, max_steps=7):
    started = time.perf_counter()
    text, history, clips = transcribe_input(item, root, split, asr)
    transcription_seconds = time.perf_counter() - started
    result = run_trajectory(item, text, history, root, split, tool_env, client, prompt,
                            timeout, max_steps=max_steps, started=started)
    result["timing"]["asr_seconds"] = transcription_seconds
    result["transcripts"] = clips
    return result
