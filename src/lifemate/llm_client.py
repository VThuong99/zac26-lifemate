"""HTTP inference client with structured timing metrics."""

import json
import logging
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


DECISION_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "type": {"const": "finish"},
            },
            "required": ["type"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "type": {"const": "call"},
                "name": {"type": "string", "minLength": 1},
                "arguments": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "required": ["type", "name", "arguments"],
            "additionalProperties": False,
        },
    ],
}


@dataclass(frozen=True)
class InferenceMetrics:
    wall_ms: float
    prompt_tokens: int | None
    output_tokens: int | None
    prompt_ms: float | None
    decode_ms: float | None


@dataclass(frozen=True)
class InferenceResult:
    content: str | None
    metrics: InferenceMetrics
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
    raw_response: dict | None = None


class LLMClient:
    """Transport adapter for llama.cpp's chat completion endpoint."""

    def __init__(
        self,
        endpoint="http://127.0.0.1:8080/v1/chat/completions",
        timeout=30.0,
        model="local",
        metrics_sink=None,
        decoding_mode="json_object",
    ):
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        self.endpoint = endpoint
        self.timeout = timeout
        self.model = model
        self.metrics_sink = metrics_sink

        if decoding_mode not in ("json_object", "strict"):
            raise ValueError(f"Unknown decoding mode: {decoding_mode}")
        self.decoding_mode = decoding_mode

    def generate(
        self,
        messages,
        max_tokens=256,
        tools=None,
        parallel_tool_calls=None,
        stop=None,
        response_schema=None,
        timeout=None,
    ):
        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be positive")
        request_timeout = self.timeout if timeout is None else timeout
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "chat_template_kwargs": {
                "enable_thinking": False,
            },
        }

        # llama-server cannot combine a grammar-backed JSON response with
        # native tool calls.  In native mode the model's chat template owns
        # tool-call syntax and the server parses it into OpenAI fields.
        if response_schema is not None and tools is not None:
            raise ValueError("response_schema cannot be combined with native tools")
        if response_schema is not None and not isinstance(response_schema, dict):
            raise TypeError("response_schema must be an object")

        if tools is None:
            payload["response_format"] = (
                {
                    "type": "json_object",
                    "schema": response_schema or DECISION_SCHEMA,
                }
                if self.decoding_mode == "strict"
                else {"type": "json_object"}
            )
        else:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            payload["parallel_tool_calls"] = bool(parallel_tool_calls)

        if stop is not None:
            payload["stop"] = stop

        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        start = time.perf_counter()

        try:
            with urlopen(request, timeout=request_timeout) as response:
                data = json.load(response)

        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM server returned HTTP {exc.code}: {body}") from exc

        except URLError as exc:
            raise ConnectionError(
                f"Cannot connect to LLM server at {self.endpoint}: {exc}"
            ) from exc

        except TimeoutError as exc:
            raise TimeoutError(f"LLM request exceeded {request_timeout}s") from exc

        wall_ms = (time.perf_counter() - start) * 1000

        usage = data.get("usage", {})
        timings = data.get("timings", {})

        metrics = InferenceMetrics(
            wall_ms=wall_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            prompt_ms=timings.get("prompt_ms"),
            decode_ms=timings.get("predicted_ms"),
        )

        logger.debug("LLM inference metrics: %s", metrics)

        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("LLM response has no valid first choice") from exc

        content = message.get("content")
        tool_calls = message.get("tool_calls")

        if tools is None and not isinstance(content, str):
            raise TypeError("LLM content must be a string")
        if tools is not None:
            if content is not None and not isinstance(content, str):
                raise TypeError("Native LLM content must be a string or null")
            if tool_calls is not None and not isinstance(tool_calls, list):
                raise TypeError("Native LLM tool_calls must be a list or null")

        if self.metrics_sink is not None:
            self.metrics_sink(metrics)

        return InferenceResult(
            content=content,
            metrics=metrics,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            raw_response=data,
        )
