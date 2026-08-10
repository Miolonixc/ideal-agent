from __future__ import annotations
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Iterator, List, Optional


class ProviderError(RuntimeError):
    """Нормализованная ошибка провайдера без URL и секретов."""

    def __init__(self, provider, message, *, status=None, retryable=False):
        self.provider = provider
        self.status = status
        self.retryable = retryable
        super().__init__(f"{provider}: {message}")


_RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}


def _error_detail(exc):
    try:
        raw = exc.read().decode(errors="replace").strip()
        if raw:
            return raw[:300]
    except Exception:
        pass
    finally:
        try:
            exc.close()
        except Exception:
            pass
    return "без деталей"


def _retry_delay(exc, attempt):
    retry_after = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
    try:
        return min(float(retry_after), 10.0)
    except (TypeError, ValueError):
        return min(0.25 * (2 ** attempt), 2.0)


def _open_request(url, body, headers, timeout, provider, retries=2):
    """Открывает запрос и повторяет только явно временные HTTP-ответы.

    Таймауты и обрывы сети не повторяются: сервер мог принять POST, и повтор
    мог бы создать дублирующий запрос/списание.
    """
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    for attempt in range(max(0, retries) + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            retryable = exc.code in _RETRYABLE_HTTP_STATUSES
            error = ProviderError(
                provider, f"HTTP {exc.code}: {_error_detail(exc)}",
                status=exc.code, retryable=retryable,
            )
            if retryable and attempt < retries:
                time.sleep(_retry_delay(exc, attempt))
                continue
            raise error from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise ProviderError(provider, "не удалось подключиться или истёк таймаут") from exc


def _post(url, body, headers, timeout=120, provider="LLM", retries=2):
    with _open_request(url, body, headers, timeout, provider, retries) as resp:
        raw = resp.read().decode(errors="replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(provider, f"некорректный JSON в ответе: {raw[:300]}") from exc


class OpenAICompatible:
    """OpenAI-совместимый провайдер (также Ollama/OpenRouter/TokenRouter)."""

    def __init__(self, base_url, api_key, model, temperature=0.3, timeout=120, max_tokens=2048):
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.retries = 2

    def _headers(self):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        headers.update(getattr(self, "extra_headers", {}))
        return headers

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
        with _open_request(
            f"{self.base_url}/chat/completions", body, self._headers(), self.timeout,
            self.__class__.__name__, self.retries,
        ) as resp:
            raw = resp.read().decode(errors="replace")
        if stream:
            return self._parse_sse(raw)
        try:
            resp = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError(self.__class__.__name__, f"некорректный JSON в ответе: {raw[:300]}") from exc
        if not resp.get("choices"):
            raise ProviderError(self.__class__.__name__, f"пустой ответ: {raw[:300]}")
        return resp

    def _parse_sse(self, raw):
        out = ""
        payloads = malformed = 0
        saw_done = False
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                saw_done = True
                break
            payloads += 1
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                malformed += 1
                continue
            choices = obj.get("choices")
            if not choices:
                continue
            delta = choices[0].get("delta", {}).get("content")
            if delta:
                out += delta
        if payloads and malformed == payloads:
            raise ProviderError(self.__class__.__name__, "некорректный SSE-ответ")
        if payloads and not saw_done:
            raise ProviderError(self.__class__.__name__, "оборванный SSE-ответ")
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
        tool_acc = {}
        with _open_request(
            f"{self.base_url}/chat/completions", body, self._headers(), self.timeout,
            self.__class__.__name__, self.retries,
        ) as resp:
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
                choices = obj.get("choices")
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
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
        self.retries = 2

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
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        ptype = part.get("type")
                        if ptype == "text":
                            blocks.append({"type": "text", "text": part.get("text", "")})
                        elif ptype == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            if url.startswith("data:") and ";base64," in url:
                                meta, b64 = url.split(",", 1)
                                media_type = meta[len("data:"):meta.index(";")] or "image/jpeg"
                                blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
            elif content:
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
        resp = _post(
            f"{self.base_url}/v1/messages", body,
            {"Content-Type": "application/json", "x-api-key": self.api_key,
             "anthropic-version": "2023-06-01"},
            timeout=self.timeout, provider="Anthropic", retries=self.retries,
        )
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
        self.retries = 2

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
            content = m.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        ptype = part.get("type")
                        if ptype == "text":
                            parts.append({"text": part.get("text", "")})
                        elif ptype == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            if url.startswith("data:") and ";base64," in url:
                                meta, b64 = url.split(",", 1)
                                mime = meta[len("data:"):meta.index(";")] or "image/jpeg"
                                parts.append({"inline_data": {"mime_type": mime, "data": b64}})
            elif content:
                parts.append({"text": content})
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
        resp = _post(url, body, {"Content-Type": "application/json"}, timeout=self.timeout,
                     provider="Gemini", retries=self.retries)
        cands = resp.get("candidates") or []
        if not cands:
            return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": []}}]}
        text = ""
        tool_calls = []
        for c in cands[0].get("content", {}).get("parts", []):
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
    # Старые конфиги использовали TokenRouter как глобальный URL. Не позволяем
    # этому значению ломать нативные провайдеры при смене только `provider`.
    inherited_urls = {
        "https://api.tokenrouter.com/v1",
        "https://openrouter.ai/api/v1",
    }
    base_url = cfg.base_url
    if name not in ("openai-compatible", "openai") and base_url in inherited_urls:
        base_url = ""
    provider = cls(base_url, cfg.api_key, cfg.model, cfg.temperature, cfg.timeout, cfg.max_tokens)
    try:
        retries = int(getattr(cfg, "retries", 2))
    except (TypeError, ValueError):
        retries = 2
    provider.retries = max(0, min(retries, 5))
    return provider
