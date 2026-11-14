"""零依赖的 LLM 客户端：OpenAI 兼容协议与 Anthropic 原生协议。"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

RETRY_STATUS = (408, 409, 425, 429, 500, 502, 503, 504)

_ACTIVE_LOCK = threading.Lock()
_ACTIVE_RESPONSES = []


def _register_response(response):
    with _ACTIVE_LOCK:
        _ACTIVE_RESPONSES.append(response)


def _unregister_response(response):
    with _ACTIVE_LOCK:
        if response in _ACTIVE_RESPONSES:
            _ACTIVE_RESPONSES.remove(response)


def cancel_all():
    """Close every in-flight HTTP response so a blocked request unwinds."""
    with _ACTIVE_LOCK:
        responses = list(_ACTIVE_RESPONSES)
        _ACTIVE_RESPONSES.clear()
    for response in responses:
        try:
            response.close()
        except Exception:  # noqa: BLE001
            pass


class LLMError(RuntimeError):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class ProviderConfig:
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.6
    max_tokens: int = 1200
    timeout: float = 120.0

    def resolved(self):
        preset = PRESETS.get(self.provider)
        if preset is None and not self.base_url:
            raise LLMError(
                "unknown provider %r; use one of %s or set base_url"
                % (self.provider, ", ".join(sorted(PRESETS)))
            )
        if preset and not self.base_url:
            self.base_url = preset["base_url"]
        if preset and not self.model:
            self.model = preset["model"]
        if not self.api_key and preset:
            for name in preset.get("env", ()):
                value = os.environ.get(name, "").strip()
                if value:
                    self.api_key = value
                    break
        if self.api_key.startswith("$"):
            self.api_key = os.environ.get(self.api_key.strip("{} $"), "")
        return self

    def to_public(self):
        return {
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "base_url": self.base_url or (PRESETS.get(self.provider, {}) or {}).get("base_url", ""),
            "has_api_key": bool(self.api_key),
        }


PRESETS = {
    "deepseek": {
        "kind": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env": ("DEEPSEEK_API_KEY",),
    },
    "dashscope": {
        "kind": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "env": ("DASHSCOPE_API_KEY", "ALIYUN_API_KEY"),
    },
    "openai": {
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "env": ("OPENAI_API_KEY",),
    },
    "moonshot": {
        "kind": "openai",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "env": ("MOONSHOT_API_KEY",),
    },
    "zhipu": {
        "kind": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
        "env": ("ZHIPU_API_KEY", "BIGMODEL_API_KEY"),
    },
    "siliconflow": {
        "kind": "openai",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-72B-Instruct",
        "env": ("SILICONFLOW_API_KEY",),
    },
    "openrouter": {
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat",
        "env": ("OPENROUTER_API_KEY",),
    },
    "ollama": {
        "kind": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5:7b",
        "env": (),
    },
    "anthropic": {
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-4-5",
        "env": ("ANTHROPIC_API_KEY",),
    },
    "engine": {
        "kind": "engine",
        "base_url": "",
        "model": "alpha-beta",
        "env": (),
    },
}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: object = field(default_factory=dict)


@dataclass
class ChatResult:
    text: str = ""
    reasoning: str = ""
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def normalise_usage(usage):
    """Map provider usage fields onto a stable {input, output} dict."""
    if not usage:
        return {}
    input_tokens = (
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("promptTokens")
        or 0
    )
    output_tokens = (
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("completionTokens")
        or 0
    )
    total = usage.get("total_tokens") or (input_tokens + output_tokens)
    details = usage.get("prompt_tokens_details") or {}
    cached_tokens = (
        (details.get("cached_tokens") if isinstance(details, dict) else 0)
        or usage.get("cached_tokens")
        or usage.get("prompt_cache_hit_tokens")
        or usage.get("cache_read_input_tokens")
        or 0
    )
    return {
        "input": int(input_tokens or 0),
        "output": int(output_tokens or 0),
        "total": int(total or 0),
        "cached": int(cached_tokens or 0),
    }


def _request_json(url, payload, headers, timeout, attempts=3):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                _register_response(response)
                try:
                    raw = response.read().decode("utf-8", "replace")
                finally:
                    _unregister_response(response)
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:600]
            last_error = LLMError(
                "HTTP %s from %s: %s" % (exc.code, url, detail),
                status=exc.code,
                body=detail,
            )
            if exc.code in RETRY_STATUS and attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_error
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            last_error = LLMError("cannot reach %s: %s" % (url, exc))
            if attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_error
    raise last_error or LLMError("request failed")


def _stream_events(url, payload, headers, timeout, on_event, attempts=2):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = dict(headers)
    headers["Accept"] = "text/event-stream"
    last_error = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                _register_response(response)
                try:
                    for raw in response:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            event = json.loads(data)
                        except ValueError:
                            continue
                        on_event(event)
                finally:
                    _unregister_response(response)
                return
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            last_error = LLMError(
                "HTTP %s from %s: %s" % (exc.code, url, detail),
                status=exc.code,
                body=detail,
            )
            if exc.code in RETRY_STATUS and attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_error
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            last_error = LLMError("cannot reach %s: %s" % (url, exc))
            if attempt < attempts - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last_error
    raise last_error or LLMError("stream failed")


class OpenAIClient:
    """Client for any OpenAI-compatible /chat/completions endpoint."""

    kind = "openai"
    supports_streaming = True

    def __init__(self, config):
        self.config = config
        self.base_url = (config.base_url or "").rstrip("/")
        self.environment = PRESETS.get(config.provider, {}).get("env", ())

    def cancel(self):
        cancel_all()

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = "Bearer " + self.config.api_key
        if self.config.provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/lnrh1/xiangqi-duel"
            headers["X-Title"] = "xiangqi-duel"
        return headers

    def chat(self, system, messages, tools=None, on_delta=None):
        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system}] + _to_openai_messages(messages),
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        url = self.base_url + "/chat/completions"
        if on_delta is not None:
            try:
                return self._stream(url, payload, on_delta)
            except LLMError:
                pass
        data = _request_json(
            url, payload, self._headers(), self.config.timeout
        )
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected response: %r" % (str(data)[:400],))
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            raw_args = function.get("arguments")
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except ValueError:
                arguments = raw_args or {}
            calls.append(
                ToolCall(
                    id=str(call.get("id") or "call_%d" % len(calls)),
                    name=str(function.get("name") or ""),
                    arguments=arguments,
                )
            )
        return ChatResult(
            text=(message.get("content") or "").strip(),
            reasoning=(message.get("reasoning_content") or "").strip(),
            tool_calls=calls,
            usage=normalise_usage(data.get("usage") or {}),
            raw=data,
        )


    def _stream(self, url, payload, on_delta):
        payload = dict(payload)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        text_parts = []
        reasoning_parts = []
        calls = {}
        usage = {}

        def handle(event):
            if event.get("usage"):
                for key, value in normalise_usage(event["usage"]).items():
                    if value:
                        usage[key] = value
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    reasoning_parts.append(delta["reasoning_content"])
                    on_delta("reasoning", delta["reasoning_content"])
                if delta.get("content"):
                    text_parts.append(delta["content"])
                    on_delta("text", delta["content"])
                for tool_call in delta.get("tool_calls") or []:
                    index = tool_call.get("index", 0)
                    slot = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if tool_call.get("id"):
                        slot["id"] = tool_call["id"]
                    function = tool_call.get("function") or {}
                    if function.get("name"):
                        slot["name"] += function["name"]
                    if function.get("arguments"):
                        slot["arguments"] += function["arguments"]

        _stream_events(url, payload, self._headers(), self.config.timeout, handle)
        tool_calls = []
        for index in sorted(calls):
            slot = calls[index]
            raw_arguments = slot["arguments"]
            try:
                arguments = json.loads(raw_arguments) if raw_arguments else {}
            except ValueError:
                arguments = raw_arguments or {}
            tool_calls.append(
                ToolCall(
                    id=slot["id"] or "call_%d" % index,
                    name=slot["name"],
                    arguments=arguments,
                )
            )
        return ChatResult(
            text="".join(text_parts).strip(),
            reasoning="".join(reasoning_parts).strip(),
            tool_calls=tool_calls,
            usage=usage or {},
            raw={},
        )

class AnthropicClient:
    """Client for the Anthropic Messages API."""

    kind = "anthropic"
    supports_streaming = True

    def __init__(self, config):
        self.config = config
        self.base_url = (config.base_url or "https://api.anthropic.com").rstrip("/")

    def cancel(self):
        cancel_all()

    def _headers(self):
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.config.api_key:
            headers["x-api-key"] = self.config.api_key
        return headers

    def chat(self, system, messages, tools=None, on_delta=None):
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "system": system,
            "messages": _to_anthropic_messages(messages),
        }
        if tools:
            payload["tools"] = [
                {
                    "name": item["function"]["name"],
                    "description": item["function"].get("description", ""),
                    "input_schema": item["function"].get("parameters") or {"type": "object"},
                }
                for item in tools
            ]
        if on_delta is not None:
            try:
                return self._stream(payload, on_delta)
            except LLMError:
                pass
        data = _request_json(
            self.base_url + "/v1/messages", payload, self._headers(), self.config.timeout
        )
        texts = []
        calls = []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                texts.append(block.get("text") or "")
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=str(block.get("id") or "tool_%d" % len(calls)),
                        name=str(block.get("name") or ""),
                        arguments=block.get("input") or {},
                    )
                )
        return ChatResult(
            text="".join(texts).strip(),
            tool_calls=calls,
            usage=normalise_usage(data.get("usage") or {}),
            raw=data,
        )


    def _stream(self, payload, on_delta):
        payload = dict(payload)
        payload["stream"] = True
        text_parts = []
        calls = {}
        usage = {}

        def handle(event):
            kind = event.get("type")
            if kind == "message_start":
                for key, value in normalise_usage(
                    (event.get("message") or {}).get("usage") or {}
                ).items():
                    if value:
                        usage[key] = value
            elif kind == "content_block_start":
                block = event.get("content_block") or {}
                if block.get("type") == "tool_use":
                    calls[event.get("index", 0)] = {
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "json": "",
                    }
            elif kind == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text_parts.append(delta.get("text", ""))
                    on_delta("text", delta.get("text", ""))
                elif delta.get("type") == "input_json_delta":
                    index = event.get("index", 0)
                    slot = calls.setdefault(index, {"id": "", "name": "", "json": ""})
                    slot["json"] += delta.get("partial_json", "")
            elif kind == "message_delta":
                for key, value in normalise_usage(event.get("usage") or {}).items():
                    if value:
                        usage[key] = value

        _stream_events(
            self.base_url + "/v1/messages",
            payload,
            self._headers(),
            self.config.timeout,
            handle,
        )
        tool_calls = []
        for index in sorted(calls):
            slot = calls[index]
            try:
                arguments = json.loads(slot["json"]) if slot["json"] else {}
            except ValueError:
                arguments = {}
            tool_calls.append(
                ToolCall(
                    id=slot["id"] or "tool_%d" % index,
                    name=slot["name"],
                    arguments=arguments,
                )
            )
        return ChatResult(
            text="".join(text_parts).strip(),
            tool_calls=tool_calls,
            usage=usage or {},
            raw={},
        )

def _to_openai_messages(messages):
    out = []
    for message in messages:
        role = message.get("role")
        if role == "user":
            out.append({"role": "user", "content": message.get("content") or ""})
        elif role == "assistant":
            entry = {"role": "assistant", "content": message.get("content") or ""}
            calls = message.get("tool_calls") or []
            if calls:
                entry["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": (
                                call["arguments"]
                                if isinstance(call["arguments"], str)
                                else json.dumps(call["arguments"], ensure_ascii=False)
                            ),
                        },
                    }
                    for call in calls
                ]
            out.append(entry)
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": message.get("tool_call_id", ""),
                    "content": message.get("content") or "",
                }
            )
    return out


def _to_anthropic_messages(messages):
    out = []
    for message in messages:
        role = message.get("role")
        if role == "user":
            out.append(
                {
                    "role": "user",
                    "content": [{"type": "text", "text": message.get("content") or ""}],
                }
            )
        elif role == "assistant":
            blocks = []
            if message.get("content"):
                blocks.append({"type": "text", "text": message["content"]})
            for call in message.get("tool_calls") or []:
                arguments = call["arguments"]
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["name"],
                        "input": arguments,
                    }
                )
            if not blocks:
                blocks.append({"type": "text", "text": ""})
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id", ""),
                            "content": message.get("content") or "",
                        }
                    ],
                }
            )
    merged = []
    for entry in out:
        if merged and merged[-1]["role"] == entry["role"]:
            merged[-1]["content"].extend(entry["content"])
        else:
            merged.append({"role": entry["role"], "content": list(entry["content"])})
    return merged


def _get_json(url, headers, timeout, attempts=2):
    last_error = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            last_error = LLMError("HTTP %s: %s" % (exc.code, detail), status=exc.code)
            if exc.code in RETRY_STATUS and attempt < attempts - 1:
                time.sleep(1.2)
                continue
            raise last_error
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            last_error = LLMError("cannot reach %s: %s" % (url, exc))
            if attempt < attempts - 1:
                time.sleep(1.2)
                continue
            raise last_error
    raise last_error or LLMError("request failed")


def list_models(provider, base_url="", api_key="", timeout=20.0):
    """Ask a provider for its model list (OpenAI /models or Anthropic /v1/models)."""
    preset = PRESETS.get(provider, {}) or {}
    config = ProviderConfig(
        provider=provider,
        base_url=base_url or preset.get("base_url", ""),
        api_key=api_key or "",
    ).resolved()
    base = (config.base_url or "").rstrip("/")
    if not base:
        raise LLMError("缺少 base_url，无法获取模型列表")
    kind = preset.get("kind", "openai")
    headers = {"Accept": "application/json"}
    if kind == "anthropic":
        url = base + "/v1/models"
        headers["anthropic-version"] = "2023-06-01"
        if config.api_key:
            headers["x-api-key"] = config.api_key
    else:
        url = base + "/models"
        if config.api_key:
            headers["Authorization"] = "Bearer " + config.api_key
    data = _get_json(url, headers, timeout)
    items = data.get("data") or data.get("models") or []
    found = set()
    for item in items:
        if isinstance(item, str):
            found.add(item)
        elif isinstance(item, dict):
            name = item.get("id") or item.get("name")
            if name:
                found.add(str(name))
    return sorted(found)


def make_client(config):
    config = config.resolved()
    preset = PRESETS.get(config.provider, {})
    kind = preset.get("kind", "openai")
    if kind == "anthropic":
        return AnthropicClient(config)
    return OpenAIClient(config)


def config_from_dict(data):
    data = dict(data or {})
    known = {
        "provider", "model", "api_key", "base_url", "temperature",
        "max_tokens", "timeout",
    }
    return ProviderConfig(**{k: v for k, v in data.items() if k in known})
