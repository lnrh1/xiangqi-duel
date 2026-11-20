"""本地模型库：把“棋手”与“模型”解耦。

API Key 与模型配置只保存在本机（默认 ~/.xiangqi-duel/models.json，
权限 600），对局开始时从模型库里挑一个编号即可。密钥不会出现在
接口响应、对局日志或页面里。
"""
from __future__ import annotations

import json
import os
import time
import uuid

from .llm import PRESETS, ProviderConfig, make_client, normalise_effort

DEFAULT_HOME = os.path.join(os.path.expanduser("~"), ".xiangqi-duel")
DEFAULT_PATH = os.path.join(DEFAULT_HOME, "models.json")


def _json_object(value, label):
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            raise RegistryError("%s 必须是 JSON 对象：%s" % (label, exc))
        if isinstance(parsed, dict):
            return parsed
    raise RegistryError("%s 必须是 JSON 对象" % label)


def _int_value(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


class RegistryError(ValueError):
    """模型库操作失败。"""


class ModelRegistry:
    def __init__(self, path=None):
        self.path = path or os.environ.get("XIANGQI_DUEL_MODELS") or DEFAULT_PATH
        self._models = []
        self.load()

    # --------------------------------------------------------------- storage
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError) as exc:
            raise RegistryError("读取模型库失败：%s" % (exc,))
        models = data.get("models") if isinstance(data, dict) else None
        self._models = [
            entry for entry in (models or []) if isinstance(entry, dict) and entry.get("id")
        ]

    def save(self):
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        os.makedirs(directory, exist_ok=True)
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "models": self._models}, handle, ensure_ascii=False, indent=2)
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.path)

    # ----------------------------------------------------------------- query
    def entries(self):
        return list(self._models)

    def public(self):
        return [self.to_public(entry) for entry in self._models]

    def to_public(self, entry):
        preset = PRESETS.get(entry.get("provider"), {})
        provider = entry.get("provider", "")
        model = entry.get("model", "")
        return {
            "id": entry["id"],
            "provider": provider,
            "model": model,
            "label": entry.get("label") or "%s · %s" % (provider, model),
            "base_url": entry.get("base_url") or preset.get("base_url", ""),
            "temperature": entry.get("temperature", 0.6),
            "max_tokens": entry.get("max_tokens", 1200),
            "reasoning_effort": entry.get("reasoning_effort", ""),
            "thinking_budget": entry.get("thinking_budget", 0),
            "extra_body": entry.get("extra_body") or {},
            "extra_headers": entry.get("extra_headers") or {},
            "has_key": bool(entry.get("api_key")),
            "created_at": entry.get("created_at"),
        }

    def get(self, model_id):
        for entry in self._models:
            if entry["id"] == model_id:
                return entry
        raise RegistryError("模型库里没有 %r，请先添加模型" % (model_id,))

    def find_by_model(self, provider, model):
        for entry in self._models:
            if entry.get("provider") == provider and entry.get("model") == model:
                return entry
        return None

    # ---------------------------------------------------------------- mutate
    def add(
        self,
        provider,
        model="",
        api_key="",
        base_url="",
        label="",
        temperature=0.6,
        max_tokens=1200,
        reasoning_effort="",
        thinking_budget=0,
        extra_body=None,
        extra_headers=None,
    ):
        provider = str(provider or "").strip()
        if provider not in PRESETS and not str(base_url or "").strip():
            raise RegistryError(
                "未知提供商 %r；可选：%s，或填写自定义 base_url"
                % (provider, "、".join(sorted(PRESETS)))
            )
        preset = PRESETS.get(provider, {}) or {}
        model = str(model or "").strip() or preset.get("model", "")
        if not model:
            raise RegistryError("请填写模型名称")
        if preset.get("kind") not in ("engine",) and not str(api_key or "").strip():
            for name in preset.get("env", ()):
                if os.environ.get(name, "").strip():
                    api_key = os.environ[name].strip()
                    break
        try:
            temperature = float(temperature)
        except (TypeError, ValueError):
            temperature = 0.6
        effort = str(reasoning_effort or "").strip().lower()
        normalised_effort = normalise_effort(effort)
        if effort and not normalised_effort:
            raise RegistryError("思考档位只能是 off/minimal/low/medium/high/max")
        entry = {
            "id": "m-" + uuid.uuid4().hex[:8],
            "provider": provider,
            "model": model,
            "api_key": str(api_key or "").strip(),
            "base_url": str(base_url or "").strip(),
            "label": str(label or "").strip(),
            "temperature": max(0.0, min(2.0, temperature)),
            "max_tokens": _int_value(max_tokens, 1200, 1, 128000),
            "reasoning_effort": normalised_effort,
            "thinking_budget": _int_value(thinking_budget, 0, 0, 128000),
            "extra_body": _json_object(extra_body, "extra_body"),
            "extra_headers": _json_object(extra_headers, "extra_headers"),
            "created_at": time.time(),
        }
        self._models.append(entry)
        self.save()
        return entry

    def update(self, model_id, **fields):
        entry = self.get(model_id)
        for key in (
            "provider", "model", "base_url", "label", "temperature",
            "max_tokens", "reasoning_effort", "thinking_budget",
            "extra_body", "extra_headers",
        ):
            if key not in fields:
                continue
            value = fields[key]
            if key in ("extra_body", "extra_headers"):
                entry[key] = _json_object(value, key)
            elif key == "temperature":
                try:
                    entry[key] = max(0.0, min(2.0, float(value)))
                except (TypeError, ValueError):
                    entry[key] = 0.6
            elif key == "max_tokens":
                entry[key] = _int_value(value, 1200, 1, 128000)
            elif key == "thinking_budget":
                entry[key] = _int_value(value, 0, 0, 128000)
            elif key == "reasoning_effort":
                raw = str(value or "").strip().lower()
                normalised = normalise_effort(raw)
                if raw and not normalised:
                    raise RegistryError("思考档位只能是 off/minimal/low/medium/high/max")
                entry[key] = normalised
            elif key == "provider":
                provider = str(value or "").strip()
                if provider not in PRESETS and not str(entry.get("base_url") or "").strip():
                    raise RegistryError("未知提供商 %r" % provider)
                entry[key] = provider
            else:
                entry[key] = str(value or "").strip()
        if fields.get("api_key"):
            entry["api_key"] = str(fields["api_key"]).strip()
        if not str(entry.get("model") or "").strip():
            raise RegistryError("模型名称不能为空")
        self.save()
        return entry

    def remove(self, model_id):
        before = len(self._models)
        self._models = [entry for entry in self._models if entry["id"] != model_id]
        if len(self._models) == before:
            raise RegistryError("模型库里没有 %r" % (model_id,))
        self.save()

    def bootstrap_from_env(self):
        """把环境变量里的 Key 导入模型库，方便服务器直接开箱使用。"""
        added = []
        for name, preset in PRESETS.items():
            if preset.get("kind") == "engine":
                continue
            if any(entry.get("provider") == name for entry in self._models):
                continue
            for env_name in preset.get("env", ()):
                value = os.environ.get(env_name, "").strip()
                if not value:
                    continue
                entry = self.add(
                    name,
                    preset.get("model", ""),
                    value,
                    label="%s（来自 %s）" % (name, env_name),
                )
                added.append(entry)
                break
        return added

    # ---------------------------------------------------------------- runtime
    def config_for(self, model_id):
        entry = self.get(model_id)
        return ProviderConfig(
            provider=entry.get("provider", "custom"),
            model=entry.get("model", ""),
            api_key=entry.get("api_key", ""),
            base_url=entry.get("base_url", ""),
            temperature=entry.get("temperature", 0.6),
            max_tokens=entry.get("max_tokens", 1200),
            reasoning_effort=entry.get("reasoning_effort", ""),
            thinking_budget=entry.get("thinking_budget", 0),
            extra_body=entry.get("extra_body") or {},
            extra_headers=entry.get("extra_headers") or {},
        ).resolved()

    def test(self, model_id, timeout=45.0):
        config = self.config_for(model_id)
        config.max_tokens = 24
        config.timeout = timeout
        client = make_client(config)
        started = time.time()
        result = client.chat(
            "你是一个接口连通性测试助手。",
            [{"role": "user", "content": "只回复两个字：收到"}],
        )
        return {
            "ok": True,
            "seconds": round(time.time() - started, 2),
            "reply": (result.text or "")[:80],
            "usage": result.usage,
        }
