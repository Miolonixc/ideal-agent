from __future__ import annotations
import base64
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import llm as llm_mod
from . import builtin_tools
from . import safety
from . import memory as memory_mod
from .tools import ToolRegistry


MAX_ITER = 12
MAX_INLINE_ATTACHMENT_BYTES = 512 * 1024
MAX_IMAGE_ATTACHMENT_BYTES = 8 * 1024 * 1024


def _safe_tool_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "extension"


def _content_to_text(content):
    """Превращает content сообщения (str или список частей) в текст для
    подсчёта токенов и сжатия истории."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    out.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    out.append("[изображение]")
                else:
                    out.append(str(part))
            else:
                out.append(str(part))
        return "\n".join(out)
    return str(content)


class HistoryManager:
    def __init__(self, provider, budget=6000):
        self.provider = provider
        self.budget = budget
        self.messages: List[Dict[str, Any]] = []

    def add(self, msg):
        self.messages.append(msg)

    def tokens(self):
        total = 0
        for m in self.messages:
            total += self.provider.count_tokens(
                _content_to_text(m.get("content")) + json.dumps(m.get("tool_calls") or "")
            )
        return total

    def compact(self):
        if self.tokens() <= self.budget or len(self.messages) < 4:
            return
        keep = self.messages[-3:]
        to_sum = self.messages[:-3]
        text = "\n".join(
            f"{m.get('role')}: {_content_to_text(m.get('content'))}" for m in to_sum
        )
        summary = self.provider.complete(
            [
                {"role": "system", "content": "Сожми ниже в краткое резюме контекста для агента."},
                {"role": "user", "content": text},
            ],
            stream=False,
        )
        if isinstance(summary, str):
            summ = summary
        else:
            choices = summary.get("choices") if isinstance(summary, dict) else None
            summ = choices[0]["message"]["content"] if choices else ""
        self.messages = [
            {"role": "system", "content": f"[summary of earlier context]\n{summ}"}
        ] + keep


class Agent:
    def __init__(self, cfg, registry=None):
        self.cfg = cfg
        self.provider = llm_mod.get_provider(cfg.llm)
        self._sessions: Dict[str, HistoryManager] = {}
        self._session_id = "default"
        self._run_lock = threading.RLock()
        self.registry = registry or ToolRegistry()
        self.gate = safety.ApprovalGate(cfg.mode, cfg.allow, cfg.deny)
        self.audit = safety.AuditLog()
        self.repo_index = None
        self.memory = None
        self._context_ready = False
        self._closed = False
        self._loaded_skills = []
        self._register_defaults()

    def _register_defaults(self):
        builtin_tools.register_builtin_tools(self.registry, self.cfg)
        self.registry.register(
            "echo",
            "Возвращает переданный текст (демо-тул).",
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            lambda a: a.get("text", ""),
        )
        self._mcp_clients = []

    @property
    def history(self):
        h = self._sessions.get(self._session_id)
        if h is None:
            h = HistoryManager(self.provider, budget=getattr(self.cfg, "context_budget", 6000))
            self._sessions[self._session_id] = h
        return h

    def load_skills_dir(self, skills_dir):
        from .skills import load_skills
        self._loaded_skills = load_skills(
            self.registry, skills_dir,
            trusted_extensions=getattr(self.cfg, "trusted_extensions", []),
        )
        return self._loaded_skills

    def connect_mcp(self, command, args=None):
        from .mcp import MCPClient
        server_name = Path(command).name
        if args:
            for arg in args:
                if str(arg).endswith((".py", ".sh", ".js", ".mjs")):
                    server_name = Path(arg).name
                    break
        allowed = set(getattr(self.cfg, "trusted_extensions", []) or [])
        if "mcp:*" not in allowed and f"mcp:{server_name}" not in allowed:
            raise PermissionError(
                f"MCP '{server_name}' не отмечен доверенным; добавь 'mcp:{server_name}' "
                "в trusted_extensions конфига."
            )
        client = MCPClient(command, args)
        client.initialize()
        tools = client.list_tools()
        for t in tools:
            name = t["name"]
            schema = t.get("inputSchema", {"type": "object", "properties": {}})

            def make_handler(client_ref, tname):
                def handler(args):
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    res = client_ref.call_tool(tname, args)
                    content = res.get("content", [])
                    text = "".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    )
                    return text[:4000]
                return handler

            exposed_name = "mcp_" + _safe_tool_part(server_name) + "_" + _safe_tool_part(name)
            self.registry.register(
                exposed_name, t.get("description", ""), schema,
                make_handler(client, name), source="mcp",
            )
        self._mcp_clients.append(client)
        return ["mcp_" + _safe_tool_part(server_name) + "_" + _safe_tool_part(t["name"])
                for t in tools]

    def close(self):
        if self._closed:
            return
        self._closed = True
        for client in self._mcp_clients:
            try:
                client.close()
            except Exception:
                pass
        for resource in (self.repo_index, self.memory, self.audit):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass

    def _extract_tool_calls(self, msg):
        tcs = msg.get("tool_calls")
        if tcs:
            return [(tc["id"], tc["function"]["name"], tc["function"].get("arguments", "")) for tc in tcs]
        content = msg.get("content") or ""
        found = re.findall(r"TOOL:\s*(\w+)\s*(\{.*?\})", content, re.S)
        return [("md_%d" % i, n, a) for i, (n, a) in enumerate(found)]

    def _ensure_context(self):
        if not self.cfg.use_context or self._context_ready:
            return
        self._context_ready = True
        ws = self.cfg.workspace
        if os.path.isdir(ws):
            self.repo_index = memory_mod.RepoIndex(memory_mod.workspace_db_path("repo_index", ws))
            try:
                self.repo_index.build(ws)
            except Exception:
                self.repo_index = None
        self.memory = memory_mod.MemoryStore(memory_mod.workspace_db_path("memory", ws))

    def _retrieve(self, text):
        parts = []
        if self.repo_index:
            for h in self.repo_index.search(text, top_k=3):
                meta = h.get("meta") or {}
                parts.append(
                    f"[файл {meta.get('path')}:{meta.get('start', 0)}]\n{h['text'][:500]}"
                )
        if self.memory:
            for f in self.memory.recall(text, top_k=3):
                parts.append(f"[память] {f['text']}")
        return "\n\n".join(parts)

    def _inject_context(self, text):
        sys_msg = "Ты — полезный AI-агент для разработки."
        if self.cfg.use_context:
            ctx = self._retrieve(text)
            if ctx:
                sys_msg += "\n\nРелевантный контекст из репозитория и памяти:\n" + ctx
        if self.history.messages and self.history.messages[0].get("role") == "system":
            self.history.messages[0]["content"] = sys_msg
        else:
            self.history.messages.insert(0, {"role": "system", "content": sys_msg})

    def command(self, text):
        """Обработка слэш-команд. Возвращает текст ответа или None (не команда).
        Спец. значение '__EXIT__' — канал должен завершиться."""
        if not text.startswith("/"):
            return None
        parts = text[1:].split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in ("exit", "quit"):
            return "__EXIT__"
        if cmd == "help":
            return (
                "Команды:\n"
                "/help — справка\n"
                "/mode [auto|suggest|full-auto] — режим апрува\n"
                "/clear — очистить контекст диалога\n"
                "/status — модель/режим/число тулов\n"
                "/skills — список доступных навыков и тулов\n"
                "/provider — текущий провайдер/модель"
            )
        if cmd == "mode":
            if arg in ("auto", "suggest", "full-auto"):
                self.gate.mode = arg
                return f"режим апрува: {arg}"
            return "используй: /mode auto | suggest | full-auto"
        if cmd == "clear":
            self.history.messages = []
            self._context_ready = False
            return "контекст диалога очищен"
        if cmd == "status":
            return (f"провайдер={self.provider.__class__.__name__} модель={self.provider.model} "
                    f"режим={self.gate.mode} тулов={len(self.registry._tools)}")
        if cmd == "provider":
            return f"{self.provider.__class__.__name__} / {self.provider.model}"
        if cmd == "skills":
            names = sorted(self.registry._tools.keys())
            return "навыки и тулы: " + ", ".join(names)
        return None

    def command_in_session(self, session_id, text):
        with self._run_lock:
            self._session_id = session_id or "default"
            return self.command(text)

    def _handle_tools(self, msg, tool_calls):
        if "tool_calls" in msg:
            self.history.add(msg)
        else:
            self.history.add({"role": "assistant", "content": msg.get("content")})
        for tc_id, name, args in tool_calls:
            decision, reason = self.gate.decide(name, args)
            if decision == "deny":
                result = f"ошибка: запрещено ({reason})"
            elif decision == "ask":
                if sys.stdin.isatty():
                    ans = input(f"разрешить {name}({args})? [y/N] ")
                    result = self.registry.call(name, args) if ans.lower() == "y" else "ошибка: отклонено пользователем"
                else:
                    result = "ошибка: требуется подтверждение (нет TTY)"
            else:
                result = self.registry.call(name, args)
            self.audit.record(decision, name, args, result)
            self.history.add({"role": "tool", "tool_call_id": tc_id, "content": result})

    def _build_user_message(self, text, attachments):
        if not attachments:
            return {"role": "user", "content": text}
        parts = []
        if text:
            parts.append({"type": "text", "text": text})
        for att in attachments:
            kind = att.get("kind")
            if kind == "image":
                try:
                    with open(att["path"], "rb") as f:
                        raw = f.read(MAX_IMAGE_ATTACHMENT_BYTES + 1)
                    if len(raw) > MAX_IMAGE_ATTACHMENT_BYTES:
                        raise ValueError("изображение больше 8 MiB")
                    b64 = base64.b64encode(raw).decode()
                    mime = att.get("mime") or "image/jpeg"
                    parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
                except Exception:
                    parts.append({"type": "text", "text": f"[не удалось прочитать изображение {att.get('name', '')}]"})
            elif kind == "text":
                try:
                    with open(att["path"], "r", errors="replace") as f:
                        body = f.read(MAX_INLINE_ATTACHMENT_BYTES + 1)
                    if len(body) > MAX_INLINE_ATTACHMENT_BYTES:
                        body = body[:MAX_INLINE_ATTACHMENT_BYTES] + "\n[файл обрезан: лимит 512 KiB]"
                except Exception:
                    body = ""
                parts.append({"type": "text", "text": f"[содержимое файла {att.get('name', '')}]:\n{body}"})
            else:
                parts.append({"type": "text", "text": f"[файл {att.get('name', '')} сохранён по пути {att['path']} — при необходимости прочитай его]"})
        return {"role": "user", "content": parts}

    def run(self, text, attachments=None):
        self.history.add(self._build_user_message(text, attachments))
        self._ensure_context()
        self._inject_context(text)
        for _ in range(MAX_ITER):
            resp = self.provider.complete(
                self.history.messages, tools=self.registry.schema(), stream=False
            )
            msg = resp["choices"][0]["message"]
            tool_calls = self._extract_tool_calls(msg)
            if tool_calls:
                self._handle_tools(msg, tool_calls)
                continue
            reply = msg.get("content") or ""
            self.history.add({"role": "assistant", "content": reply})
            self.history.compact()
            return reply
        return "[достигнут лимит итераций]"

    def run_in_session(self, session_id, text, attachments=None):
        """Keep mutable history and provider state isolated between HTTP requests."""
        with self._run_lock:
            self._session_id = session_id or "default"
            return self.run(text, attachments)

    def stream(self, text, attachments=None):
        """Генератор: yield куски ответа по мере генерации (streaming)."""
        self.history.add(self._build_user_message(text, attachments))
        self._ensure_context()
        self._inject_context(text)
        for _ in range(MAX_ITER):
            if hasattr(self.provider, "stream_completion"):
                content = ""
                saw_tool = False
                tcs = []
                for kind, data in self.provider.stream_completion(
                    self.history.messages, self.registry.schema()
                ):
                    if kind == "content":
                        content += data
                        yield data
                    elif kind == "tool":
                        saw_tool = True
                        tcs = data
                if saw_tool:
                    msg = {"role": "assistant", "content": content, "tool_calls": tcs}
                    self._handle_tools(msg, [
                        (tc.get("id"), tc.get("function", {}).get("name"),
                         tc.get("function", {}).get("arguments", ""))
                        for tc in tcs
                    ])
                    continue
                self.history.add({"role": "assistant", "content": content})
                self.history.compact()
                return
            # fallback: без потоковой генерации — отдаём весь ответ целиком
            resp = self.provider.complete(
                self.history.messages, tools=self.registry.schema(), stream=False
            )
            msg = resp["choices"][0]["message"]
            tool_calls = self._extract_tool_calls(msg)
            if tool_calls:
                self._handle_tools(msg, tool_calls)
                continue
            reply = msg.get("content") or ""
            self.history.add({"role": "assistant", "content": reply})
            self.history.compact()
            yield reply
            return
        yield "[достигнут лимит итераций]"

    def stream_in_session(self, session_id, text, attachments=None):
        with self._run_lock:
            self._session_id = session_id or "default"
            yield from self.stream(text, attachments)
