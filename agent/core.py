from __future__ import annotations
import base64
from collections import OrderedDict
import json
import os
import re
import sys
import threading
import time
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
MAX_SESSIONS = 32


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
        self._sessions: OrderedDict[str, HistoryManager] = OrderedDict()
        self._session_id = "default"
        self._run_lock = threading.RLock()
        self._cancellation_lock = threading.Lock()
        self._stream_cancellations: Dict[str, threading.Event] = {}
        self.registry = registry or ToolRegistry()
        self.gate = safety.ApprovalGate(cfg.mode, cfg.allow, cfg.deny)
        self.audit = safety.AuditLog()
        metrics_cfg = getattr(cfg, "metrics", None) or {}
        self.metrics = None
        if metrics_cfg.get("enabled"):
            from .metrics import MetricsStore
            self.metrics = MetricsStore(metrics_cfg.get("path"))
        self.repo_index = None
        self.memory = None
        self._context_ready = False
        self._closed = False
        self._loaded_skills = []
        self.extension_approval_callback = None
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
            if len(self._sessions) >= MAX_SESSIONS:
                self._sessions.popitem(last=False)
            h = HistoryManager(self.provider, budget=getattr(self.cfg, "context_budget", 6000))
            self._sessions[self._session_id] = h
        else:
            self._sessions.move_to_end(self._session_id)
        return h

    def cancel_session(self, session_id):
        """Request cooperative cancellation of an active streaming session."""
        with self._cancellation_lock:
            event = self._stream_cancellations.get(session_id)
        if not event:
            return False
        event.set()
        return True

    def clear_session(self, session_id):
        """Cancel and forget one conversation without revealing its history.

        The run lock means a concurrent stream finishes its cleanup before the
        cached history is removed.  This keeps the next message in the same
        session from inheriting stale context.
        """
        session_id = session_id or "default"
        self.cancel_session(session_id)
        with self._run_lock:
            existed = self._sessions.pop(session_id, None) is not None
            if self._session_id == session_id:
                self._session_id = "default"
            return existed

    def active_streams(self):
        with self._cancellation_lock:
            return len(self._stream_cancellations)

    def session_count(self):
        """Return the number of cached conversations without exposing their data."""
        with self._run_lock:
            return len(self._sessions)

    @staticmethod
    def session_limit():
        return MAX_SESSIONS

    def load_skills_dir(self, skills_dir):
        from .skills import load_skills
        self._loaded_skills = load_skills(
            self.registry, skills_dir,
            trusted_extensions=getattr(self.cfg, "trusted_extensions", []),
            allowed_permissions=getattr(self.cfg, "extension_permissions", []),
            policy_getter=self.extension_policy,
            approval_callback=self._request_extension_approval,
        )
        return self._loaded_skills

    def extension_policy(self, kind, name):
        allowed = set(getattr(self.cfg, "trusted_extensions", []) or [])
        trusted = f"{kind}:*" in allowed or f"{kind}:{name}" in allowed
        return trusted, set(getattr(self.cfg, "extension_permissions", []) or [])

    def approve_extension(self, kind, name, permissions):
        identifier = f"{kind}:{name}"
        trusted = list(getattr(self.cfg, "trusted_extensions", []) or [])
        if identifier not in trusted:
            trusted.append(identifier)
        allowed = list(getattr(self.cfg, "extension_permissions", []) or [])
        for permission in permissions:
            if permission not in allowed:
                allowed.append(permission)
        self.cfg.trusted_extensions = trusted
        self.cfg.extension_permissions = allowed

    def _request_extension_approval(self, kind, name, permissions):
        callback = self.extension_approval_callback
        return bool(callback and callback(kind, name, permissions))

    def mcp_spec(self, spec):
        """Validate a declarative MCP manifest without starting its process."""
        if isinstance(spec, str):
            import shlex
            parts = shlex.split(spec)
            if not parts:
                raise ValueError("пустая MCP-спецификация")
            command, args, name, permissions = parts[0], parts[1:], None, ["shell"]
        elif isinstance(spec, dict):
            command = str(spec.get("command") or "").strip()
            raw_args = spec.get("args", [])
            if not command or not isinstance(raw_args, list) or not all(isinstance(x, str) for x in raw_args):
                raise ValueError("MCP manifest требует command и строковый массив args")
            args = raw_args
            name = str(spec.get("name") or "").strip() or None
            permissions = spec.get("permissions", [])
            if not isinstance(permissions, list) or not permissions or not all(isinstance(p, str) for p in permissions):
                raise ValueError("MCP manifest требует непустой массив permissions")
        else:
            raise ValueError("MCP manifest должен быть строкой или объектом")
        server_name = name or self._mcp_name(command, args)
        # Starting any stdio server is executable code, therefore shell is an
        # unavoidable capability even when the server advertises no other one.
        requested = sorted(set(permissions) | {"shell"})
        return command, args, server_name, requested

    @staticmethod
    def _mcp_name(command, args):
        server_name = Path(command).name
        for arg in args or []:
            if str(arg).endswith((".py", ".sh", ".js", ".mjs")):
                return Path(arg).name
        return server_name

    def connect_mcp_spec(self, spec):
        command, args, name, permissions = self.mcp_spec(spec)
        return self.connect_mcp(command, args, name=name, permissions=permissions)

    def connect_mcp(self, command, args=None, *, name=None, permissions=None):
        from .mcp import MCPClient
        server_name = name or self._mcp_name(command, args)
        requested = sorted(set(permissions or ["shell"]) | {"shell"})
        trusted, allowed = self.extension_policy("mcp", server_name)
        if not trusted or not set(requested).issubset(allowed):
            if self._request_extension_approval("mcp", server_name, requested):
                trusted, allowed = self.extension_policy("mcp", server_name)
            if not trusted or not set(requested).issubset(allowed):
                missing = sorted(set(requested) - set(allowed))
                raise PermissionError(
                    f"MCP '{server_name}' требует доверия и capabilities: {', '.join(missing or requested)}"
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
        with self._cancellation_lock:
            for event in self._stream_cancellations.values():
                event.set()
        for client in self._mcp_clients:
            try:
                client.close()
            except Exception:
                pass
        for resource in (self.repo_index, self.memory, self.audit, self.metrics):
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
                "/provider — текущий провайдер/модель\n"
                "/health — локальная диагностика без сетевого запроса\n"
                "/metrics — локальные агрегатные метрики (если включены)\n"
                "/audit [N] — последние N записей выполнения tools"
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
        if cmd == "health":
            return self.health_report()
        if cmd == "metrics":
            if not self.metrics:
                return "локальные метрики выключены (metrics.enabled: true в config.json)"
            rows = self.metrics.summary()
            if not rows:
                return "локальные метрики пока пусты"
            return "локальные метрики (без промптов и вложений): " + ", ".join(
                f"{event}={count}" for event, count in rows.items()
            )
        if cmd == "audit":
            try:
                limit = int(arg) if arg else 10
            except ValueError:
                return "используй: /audit [1..50]"
            rows = self.audit.recent(limit)
            if not rows:
                return "audit-log пока пуст"
            return "\n".join(
                f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(row['ts']))} "
                f"{row['decision']} {row['tool']} — {str(row['result'])[:160]}"
                for row in rows
            )
        return None

    def health_report(self):
        """Local-only health information safe to show in any channel."""
        from . import __version__
        workspace = os.path.expanduser(self.cfg.workspace)
        clients = getattr(self, "_mcp_clients", [])
        alive = sum(1 for client in clients if client.proc.poll() is None)
        return "\n".join((
            f"status: ok (ideal-agent v{__version__})",
            f"provider: {self.provider.__class__.__name__} / {self.provider.model}",
            f"workspace: {'ok' if os.path.isdir(workspace) else 'не найдена'} ({workspace})",
            f"tools: {len(self.registry._tools)}; skills: {len(self._loaded_skills)}",
            f"mcp: {alive}/{len(clients)} запущено",
            f"sessions: {self.session_count()}/{MAX_SESSIONS}; streams: {self.active_streams()}",
            f"mode: {self.gate.mode}; sandbox: {self.cfg.sandbox_mode}",
        ))

    def dry_run_report(self, mcp_specs=None):
        """Report effective setup without contacting an LLM or starting MCP."""
        from . import __version__
        mcp_specs = [str(spec) for spec in (mcp_specs or []) if str(spec).strip()]
        trusted = sorted(getattr(self.cfg, "trusted_extensions", []) or [])
        return "\n".join((
            f"dry-run: ideal-agent v{__version__}; LLM, tools и MCP не запускались",
            f"provider: {self.provider.__class__.__name__} / {self.provider.model}",
            f"workspace: {os.path.expanduser(self.cfg.workspace)}",
            f"built-in tools: {len(self.registry._tools)}; discovered skills: {len(self._loaded_skills)}",
            f"configured MCP: {len(mcp_specs)}; trusted extensions: {', '.join(trusted) or 'нет'}",
        ))

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
        self._record_metric("requests")
        try:
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
                self._record_metric("replies")
                return reply
            self._record_metric("iteration_limits")
            return "[достигнут лимит итераций]"
        except Exception:
            self._record_metric("errors")
            raise

    def run_in_session(self, session_id, text, attachments=None):
        """Keep mutable history and provider state isolated between HTTP requests."""
        with self._run_lock:
            self._session_id = session_id or "default"
            return self.run(text, attachments)

    def stream(self, text, attachments=None, cancel_event=None):
        """Генератор: yield куски ответа по мере генерации (streaming)."""
        self._record_metric("requests")
        try:
            yield from self._stream_impl(text, attachments, cancel_event)
        except Exception:
            self._record_metric("errors")
            raise

    def _stream_impl(self, text, attachments=None, cancel_event=None):
        """Streaming implementation, separated so failures are counted once."""
        self.history.add(self._build_user_message(text, attachments))
        self._ensure_context()
        self._inject_context(text)
        for _ in range(MAX_ITER):
            if self._stream_cancelled(cancel_event):
                return
            if hasattr(self.provider, "stream_completion"):
                content = ""
                saw_tool = False
                tcs = []
                for kind, data in self.provider.stream_completion(
                    self.history.messages, self.registry.schema()
                ):
                    if self._stream_cancelled(cancel_event):
                        return
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
                self._record_metric("replies")
                return
            # fallback: без потоковой генерации — отдаём весь ответ целиком
            resp = self.provider.complete(
                self.history.messages, tools=self.registry.schema(), stream=False
            )
            if self._stream_cancelled(cancel_event):
                return
            msg = resp["choices"][0]["message"]
            tool_calls = self._extract_tool_calls(msg)
            if tool_calls:
                self._handle_tools(msg, tool_calls)
                continue
            reply = msg.get("content") or ""
            self.history.add({"role": "assistant", "content": reply})
            self.history.compact()
            self._record_metric("replies")
            yield reply
            return
        self._record_metric("iteration_limits")
        yield "[достигнут лимит итераций]"

    def _stream_cancelled(self, cancel_event):
        if not cancel_event or not cancel_event.is_set():
            return False
        self.history.add({"role": "assistant", "content": "[генерация отменена пользователем]"})
        self.history.compact()
        self._record_metric("cancelled")
        return True

    def _record_metric(self, event):
        if self.metrics:
            self.metrics.record(event)

    def stream_in_session(self, session_id, text, attachments=None):
        session_id = session_id or "default"
        with self._run_lock:
            cancellation = threading.Event()
            with self._cancellation_lock:
                self._stream_cancellations[session_id] = cancellation
            try:
                self._session_id = session_id
                yield from self.stream(text, attachments, cancel_event=cancellation)
            finally:
                with self._cancellation_lock:
                    if self._stream_cancellations.get(session_id) is cancellation:
                        self._stream_cancellations.pop(session_id, None)
