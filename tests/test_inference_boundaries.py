"""Exercise HTTP and audio boundaries without model libraries or network access."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from lifemate.asr import audio_path, inference_input, transcribe_input
from lifemate.llm_client import DECISION_SCHEMA, InferenceMetrics, InferenceResult, LLMClient
from lifemate.llm_planner import LLMPlanner
from lifemate.tool_catalog import load_available_tools


class ClientTests(unittest.TestCase):
    def response(self):
        return io.BytesIO(json.dumps({
            "choices": [{"message": {"content": '{"type":"finish"}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }).encode())

    def test_strict_schema_and_remaining_timeout_are_sent(self):
        client = LLMClient(decoding_mode="strict")
        with patch("lifemate.llm_client.urlopen", return_value=self.response()) as send:
            result = client.generate([{"role": "user", "content": "synthetic"}], timeout=2.5)
        args, kwargs = send.call_args
        payload = json.loads(args[0].data)
        self.assertEqual(payload["response_format"]["schema"], DECISION_SCHEMA)
        self.assertEqual(payload["temperature"], 0)
        self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(kwargs["timeout"], 2.5)
        self.assertEqual(result.metrics.prompt_tokens, 12)

    def test_native_tool_request_omits_grammar(self):
        with patch("lifemate.llm_client.urlopen", return_value=self.response()) as send:
            LLMClient().generate([], tools=[], parallel_tool_calls=False)
        payload = json.loads(send.call_args.args[0].data)
        self.assertNotIn("response_format", payload)
        self.assertFalse(payload["parallel_tool_calls"])

    def test_mixed_interfaces_fail_before_network(self):
        with patch("lifemate.llm_client.urlopen") as send, self.assertRaises(ValueError):
            LLMClient().generate([], response_schema={}, tools=[])
        send.assert_not_called()

    def test_server_errors_are_not_converted_to_finish(self):
        failures = [
            (HTTPError("http://localhost", 400, "context overflow", {}, io.BytesIO(b"context overflow")), RuntimeError),
            (URLError("unavailable"), ConnectionError),
            (TimeoutError("deadline"), TimeoutError),
        ]
        for error, expected in failures:
            with self.subTest(error=error), patch("lifemate.llm_client.urlopen", side_effect=error):
                with self.assertRaises(expected):
                    LLMClient().generate([])

    def test_missing_response_choice_rejected(self):
        with patch("lifemate.llm_client.urlopen", return_value=io.BytesIO(b'{}')):
            with self.assertRaises(ValueError):
                LLMClient().generate([])

    def test_native_multiple_calls_rejected(self):
        planner = LLMPlanner([{"name": "demo.read"}], interface_mode="native_tools")
        response = InferenceResult(None, InferenceMetrics(0, None, None, None, None),
                                   tool_calls=[{}, {}], finish_reason="tool_calls")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            planner._normalize_native(response)


class AudioTests(unittest.TestCase):
    def test_inference_projection_excludes_labels_and_reference_text(self):
        row = {"id": "synthetic", "audio": "audio/a.wav", "context": {},
               "history": [{"role": "user", "audio": "audio/h.wav", "audio_text": "reference", "text": "reference"}],
               "label": {"secret": "synthetic marker"}, "audio_text": "reference"}
        projected = inference_input(row)
        self.assertEqual(set(projected), {"id", "audio", "context", "history"})
        self.assertNotIn("audio_text", projected["history"][0])
        self.assertNotIn("text", projected["history"][0])
        self.assertIn("audio_text", row["history"][0])

    def test_path_traversal_and_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "synthetic/audio").mkdir(parents=True)
            (root / "outside.wav").touch()
            (root / "synthetic/audio/link.wav").symlink_to(root / "outside.wav")
            for path in ("../outside.wav", "audio/link.wav", "audio/a.mp3"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    audio_path(root, "synthetic", path)

    def test_history_and_current_audio_use_the_injected_recognizer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "synthetic/audio").mkdir(parents=True)
            for name in ("current", "prior"):
                (root / f"synthetic/audio/{name}.wav").touch()
            class ASR:
                def transcribe(self, path):
                    return {"text": f"mock {path.stem}", "audio_seconds": 1.0, "seconds": 0.0}
            item = {"audio": "audio/current.wav", "history": [{"role": "user", "audio": "audio/prior.wav", "audio_text": "discard"}]}
            text, history, clips = transcribe_input(item, root, "synthetic", ASR())
            self.assertEqual(text, "mock current")
            self.assertEqual(history[0]["audio_text"], "mock prior")
            self.assertEqual(len(clips), 2)
            self.assertEqual(item["history"][0]["audio_text"], "discard")

    def test_reference_transcript_without_audio_rejected(self):
        with self.assertRaisesRegex(ValueError, "leak"):
            transcribe_input({"history": [{"role": "user", "audio_text": "synthetic"}]}, Path("/unused"), "synthetic", None)


class ToolCatalogTests(unittest.TestCase):
    def test_only_installed_tools_plus_clarification_are_exposed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "synthetic").mkdir()
            catalog = {"apps": [{"tools": [{"name": name, "parameters": {}} for name in
                                           ("demo.allowed", "demo.hidden", "sys.ask_missing_info")]}]}
            (root / "synthetic/synthetic_tools_catalog.json").write_text(json.dumps(catalog))
            tools = load_available_tools(root, "synthetic", {"installed_apps": {"demo": {"tools": ["demo.allowed"]}}})
            self.assertEqual([tool["name"] for tool in tools], ["demo.allowed", "sys.ask_missing_info"])
