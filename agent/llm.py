from __future__ import annotations
import json
import urllib.request
from typing import Any, Dict, Iterator, List, Optional


def _post(url, body, headers, timeout=120):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


class OpenAICompatible:
    """OpenAI-совместимый провайдер (также Ollama/OpenRouter/TokenRouter)."""

    def __init__(self, base_url, api_key, model, temperature=0.3, timeout=120, max_tokens=2048):
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_tokens = max_tokens

    def complete(self, messages, tools=None, stream=False):
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if tools:
            body["tools"] = tools
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode()
        if stream:
            return self._parse_sse(raw)
        return json.loads(raw)

    def _parse_sse(self, raw):
        out = ""
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            delta = obj["choices"][0]["delta"].get("content")
            if delta:
                out += delta
        return out

    def count_tokens(self, text):
        return max(1, len(text) // 4)

    def stream_completion(self, messages, tools=None):
        """Генератор: yield ("content", str) для кусков текста и
        ("tool", [tool_calls]) в конце, если модель вызвала тулы."""
        import json as _json
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
        data = _json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        tool_acc = {}
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = _json.loads(payload)
                except _json.JSONDecodeError:
                    continue
                delta = obj["choices"][0]["delta"]
                if delta.get("content"):
                    yield ("content", delta["content"])
                for tc in delta.get("tool_calls", []) or []:
                    idx = tc.get("index", 0)
                    acc = tool_acc.setdefault(idx, {"id": "", "type": "function",
                                                   "function": {"name": "", "arguments": ""}})
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        acc["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        acc["function"]["arguments"] += fn["arguments"]
        tcs = [v for v in tool_acc.values()]
        if tcs:
            yield ("tool", tcs)


class OpenRouterProvider(OpenAICompatible):
    def __init__(self, base_url, api_key, model, temperature=0.3, timeout=120, max_tokens=2048):
        base_url = base_url or "https://openrouter.ai/api/v1"
        model = model or "openai/gpt-4o-mini"
        super().__init__(base_url, api_key, model, temperature, timeout, max_tokens)
        self.extra_headers = {"HTTP-Referer": "https://ideal-agent.local", "X-Title": "ideal-agent"}


class OllamaProvider(OpenAICompatible):
    def __init__(self, base_url, api_key, model, temperature=0.3, timeout=180, max_tokens=2048):
        base_url = base_url or "http://localhost:11434/v1"
        model = model or "llama3.1"
        # Ollama локальный не требует ключ, но принимает любой
        super().__init__(base_url, api_key or "ollama", model, temperature, timeout, max_tokens)


class AnthropicProvider:
    """Anthropic Messages API (claude). Нормализует ответ к OpenAI-форме."""

    def __init__(self, base_url, api_key, model, temperature=0.3, timeout=120, max_tokens=2048):
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.api_key = api_key
        self.model = model or "claude-3-5-sonnet-20241022"
        self.temperature = temperature
        self.timeout = timeout
        self.max_tokens = max_tokens

    def _to_anthropic(self, messages, tools):
        system = None
        conv = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                system = m.get("content", "")
                continue
            if role == "tool":
                conv.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id"),
                        "content": m.get("content", ""),
                    }],
                })
                continue
            content = m.get("content") or ""
            blocks = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in m.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                try:
                    inp = json.loads(fn.get("arguments", "{}") or "{}")
                except json.JSONDecodeError:
                    inp = {}
                blocks.append({"type": "tool_use", "id": tc.get("id", "t1"),
                               "name": fn.get("name"), "input": inp})
            conv.append({"role": role, "content": blocks})
        # Anthropic требует чередования user/assistant
        out = []
        for m in conv:
            if out and out[-1]["role"] == m["role"]:
                out[-1]["content"].extend(m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}])
            else:
                out.append(m)
        ath_tools = None
        if tools:
            ath_tools = [{
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            } for t in tools]
        return system, out, ath_tools

    def complete(self, messages, tools=None, stream=False):
        system, conv, ath_tools = self._to_anthropic(messages, tools)
        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": conv,
            "temperature": self.temperature,
        }
        if system:
            body["system"] = system
        if ath_tools:
            body["tools"] = ath_tools
        try:
            resp = _post(
                f"{self.base_url}/v1/messages", body,
                {"Content-Type": "application/json", "x-api-key": self.api_key,
                 "anthropic-version": "2023-06-01"},
                timeout=self.timeout,
            )
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Anthropic HTTP {e.code}: {e.read().decode()[:300]}")
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        tool_calls = []
        for b in resp.get("content", []):
            if b.get("type") == "tool_use":
                tool_calls.append({
                    "id": b.get("id"),
                    "type": "function",
                    "function": {"name": b.get("name"), "arguments": json.dumps(b.get("input", {}), ensure_ascii=False)},
                })
        return {"choices": [{"message": {"role": "assistant", "content": text, "tool_calls": tool_calls}}]}

    def count_tokens(self, text):
        return max(1, len(text) // 4)

    def stream_completion(self, messages, tools=None):
        resp = self.complete(messages, tools, stream=True)
        msg = resp["choices"][0]["message"]
        text = msg.get("content") or ""
        if text:
            yield ("content", text)
        tcs = msg.get("tool_calls") or []
        if tcs:
            yield ("tool", tcs)


class GeminiProvider:
    """Google Gemini (generativeLanguage API). Нормализует к OpenAI-форме."""

    def __init__(self, base_url, api_key, model, temperature=0.3, timeout=120, max_tokens=2048):
        self.api_key = api_key
        self.model = model or "gemini-1.5-flash"
        self.temperature = temperature
        self.timeout = timeout
        self.max_tokens = max_tokens

    def _to_gemini(self, messages, tools):
        sys_inst = None
        contents = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                sys_inst = m.get("content", "")
                continue
            if role == "tool":
                contents.append({"role": "user", "parts": [{"text": f"[tool result {m.get('tool_call_id')}]: {m.get('content')}"}]})
                continue
            parts = []
            if m.get("content"):
                parts.append({"text": m["content"]})
            for tc in m.get("tool_calls", []) or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}") or "{}")
                except json.JSONDecodeError:
                    args = {}
                parts.append({"functionCall": {"name": fn.get("name"), "args": args}})
            contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
        gtools = None
        if tools:
            gtools = [{
                "functionDeclarations": [{
                    "name": t["function"]["name"],
                    "description": t["function"]["description"],
                    "parameters": t["function"]["parameters"],
                } for t in tools]
            }]
        return sys_inst, contents, gtools

    def complete(self, messages, tools=None, stream=False):
        sys_inst, contents, gtools = self._to_gemini(messages, tools)
        body = {
            "contents": contents,
            "generationConfig": {"temperature": self.temperature, "maxOutputTokens": self.max_tokens},
        }
        if sys_inst:
            body["systemInstruction"] = {"parts": [{"text": sys_inst}]}
        if gtools:
            body["tools"] = gtools
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        try:
            resp = _post(url, body, {"Content-Type": "application/json"}, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Gemini HTTP {e.code}: {e.read().decode()[:300]}")
        text = ""
        tool_calls = []
        for c in resp.get("candidates", [{}])[0].get("content", {}).get("parts", []):
            if "text" in c:
                text += c["text"]
            if "functionCall" in c:
                fc = c["functionCall"]
                tool_calls.append({
                    "id": "gc_" + fc.get("name"),
                    "type": "function",
                    "function": {"name": fc.get("name"), "arguments": json.dumps(fc.get("args", {}), ensure_ascii=False)},
                })
        return {"choices": [{"message": {"role": "assistant", "content": text, "tool_calls": tool_calls}}]}

    def count_tokens(self, text):
        return max(1, len(text) // 4)

    def stream_completion(self, messages, tools=None):
        resp = self.complete(messages, tools, stream=True)
        msg = resp["choices"][0]["message"]
        text = msg.get("content") or ""
        if text:
            yield ("content", text)
        tcs = msg.get("tool_calls") or []
        if tcs:
            yield ("tool", tcs)


class GroqProvider(OpenAICompatible):
    """Groq — сверхбыстрый inference, есть бесплатные модели."""

    def __init__(self, base_url=None, api_key=None, model=None, temperature=0.3, timeout=120, max_tokens=2048):
        super().__init__("https://api.groq.com/openai/v1", api_key, model, temperature, timeout, max_tokens)


class DeepSeekProvider(OpenAICompatible):
    """DeepSeek — бесплатный и недорогой API."""

    def __init__(self, base_url=None, api_key=None, model=None, temperature=0.3, timeout=120, max_tokens=2048):
        super().__init__("https://api.deepseek.com/v1", api_key, model, temperature, timeout, max_tokens)


class MoonshotProvider(OpenAICompatible):
    """Moonshot AI / Kimi — есть бесплатные модели (kimi-k3-free и т.п.)."""

    def __init__(self, base_url=None, api_key=None, model=None, temperature=0.3, timeout=120, max_tokens=2048):
        super().__init__("https://api.moonshot.ai/v1", api_key, model, temperature, timeout, max_tokens)


class TogetherProvider(OpenAICompatible):
    """Together AI — открытые модели."""

    def __init__(self, base_url=None, api_key=None, model=None, temperature=0.3, timeout=120, max_tokens=2048):
        super().__init__("https://api.together.xyz/v1", api_key, model, temperature, timeout, max_tokens)


_PROVIDERS = {
    "openai-compatible": OpenAICompatible,
    "openai": OpenAICompatible,
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "deepseek": DeepSeekProvider,
    "moonshot": MoonshotProvider,
    "together": TogetherProvider,
}


def build_provider(name, api_key=None, model=None, base_url=None, temperature=0.3, timeout=120, max_tokens=2048):
    """Создаёт провайдера по имени (для переопределения на лету, напр. из компаньона)."""
    name = (name or "openai-compatible").lower()
    cls = _PROVIDERS.get(name, OpenAICompatible)
    return cls(base_url, api_key, model, temperature, timeout, max_tokens)


def get_provider(cfg: "LLMConfig"):
    name = (cfg.provider or "openai-compatible").lower()
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"unknown provider: {cfg.provider}")
    return cls(cfg.base_url, cfg.api_key, cfg.model, cfg.temperature, cfg.timeout, cfg.max_tokens)
