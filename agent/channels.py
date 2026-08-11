from __future__ import annotations
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import subprocess
import sys
import tempfile
import shutil
import threading
import time
import urllib.parse
import urllib.request
import unicodedata
from dataclasses import dataclass
from collections import deque
from typing import Iterator, List, Optional

import curses


@dataclass
class Message:
    text: str
    chat_id: Optional[str] = None
    chat_type: Optional[str] = None


TUI_MAX_ATTACHMENTS = 5
TUI_MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024


def _terminal_width(text: str) -> int:
    """Return terminal-cell width (``len`` breaks on emoji and CJK text)."""
    total = 0
    for char in text:
        if unicodedata.combining(char) or char in "\ufe0e\ufe0f":
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
    return total


def _clip_terminal_text(text: str, width: int) -> str:
    out, used = [], 0
    for char in text:
        size = _terminal_width(char)
        if used + size > width:
            break
        out.append(char)
        used += size
    return "".join(out)


def _wrap_terminal_text(text: str, width: int) -> List[str]:
    """Wrap each logical line before it reaches curses.addstr()."""
    width = max(1, width)
    result = []
    for logical_line in (text.splitlines() or [""]):
        line = ""
        for char in logical_line:
            if _terminal_width(line + char) > width:
                result.append(line.rstrip() or _clip_terminal_text(line, width))
                line = char.lstrip()
            else:
                line += char
        result.append(line)
    return result


def terminal_attachment(path: str):
    """Подготавливает локальный файл для TUI без чтения содержимого в память."""
    expanded = os.path.abspath(os.path.expanduser(path.strip()))
    if not os.path.isfile(expanded):
        raise ValueError("файл не найден или это не обычный файл")
    if os.path.getsize(expanded) > TUI_MAX_ATTACHMENT_BYTES:
        raise ValueError("файл больше 8 MiB")
    mime = mimetypes.guess_type(expanded)[0] or "application/octet-stream"
    text_ext = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".xml", ".csv", ".html", ".css", ".sh", ".java", ".kt", ".c", ".h", ".cpp", ".go", ".rs", ".sql"}
    ext = os.path.splitext(expanded)[1].lower()
    kind = "image" if mime.startswith("image/") else "text" if mime.startswith("text/") or ext in text_ext else "file"
    return {"path": expanded, "name": os.path.basename(expanded), "mime": mime, "kind": kind}


def capture_terminal_screenshot():
    """Создаёт скриншот штатной утилитой ОС и возвращает attachment."""
    fd, path = tempfile.mkstemp(prefix="ideal-agent-shot-", suffix=".png")
    os.close(fd)
    if os.environ.get("TERMUX_VERSION"):
        command = ["termux-screenshot", "-p", path]
    elif sys.platform == "darwin":
        command = ["screencapture", "-x", path]
    elif shutil.which("gnome-screenshot"):
        command = ["gnome-screenshot", "-f", path]
    elif shutil.which("scrot"):
        command = ["scrot", path]
    else:
        os.unlink(path)
        raise RuntimeError("скриншоты не поддерживаются: нужен termux-screenshot, screencapture, gnome-screenshot или scrot")
    try:
        subprocess.run(command, check=True, timeout=20, capture_output=True)
        att = terminal_attachment(path)
        att["temporary"] = True
        return att
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


class Channel:
    def read(self) -> Optional[Message]:
        raise NotImplementedError

    def write(self, msg: Message):
        raise NotImplementedError

    def close(self):
        pass


class CLIChannel(Channel):
    def __init__(self, prompt: str = "you> "):
        self.prompt = prompt
        self._argv = sys.argv[1:]

    def read(self) -> Optional[Message]:
        if self._argv:
            line = " ".join(self._argv)
            self._argv = []
            return Message(line)
        try:
            return Message(input(self.prompt))
        except EOFError:
            return None

    def write(self, msg: Message):
        print(msg.text)


class TelegramChannel(Channel):
    def __init__(self, token: str, allowed: Optional[List[int]] = None, poll: float = 1.0):
        self.url = f"https://api.telegram.org/bot{token}"
        self.allowed = set(allowed or [])
        self.poll = poll
        self._offset = 0
        self._pending: List[Message] = []

    def _api(self, method: str, data: Optional[dict] = None):
        req = urllib.request.Request(
            f"{self.url}/{method}",
            data=urllib.parse.urlencode(data or {}).encode(),
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def _poll_once(self) -> List[Message]:
        updates = self._api(
            "getUpdates", {"offset": self._offset, "timeout": int(self.poll)}
        )
        out: List[Message] = []
        for u in updates.get("result", []):
            self._offset = u["update_id"] + 1
            msg = u.get("message") or u.get("edited_message")
            if not msg:
                continue
            uid = msg["from"]["id"]
            if self.allowed and uid not in self.allowed:
                continue
            text = msg.get("text")
            if text:
                out.append(Message(text, str(msg["chat"]["id"]), msg["chat"].get("type")))
        return out

    def read(self) -> Optional[Message]:
        if self._pending:
            return self._pending.pop(0)
        while True:
            self._pending = self._poll_once()
            if self._pending:
                return self._pending.pop(0)
            time.sleep(self.poll)

    def write(self, msg: Message):
        self._api("sendMessage", {"chat_id": msg.chat_id, "text": msg.text})


def serve(channel: Channel, agent, stop_on_none: bool = True):
    try:
        while True:
            try:
                msg = channel.read()
            except Exception as e:
                time.sleep(1)
                continue
            if msg is None:
                if stop_on_none:
                    break
                continue
            cmd_reply = agent.command(msg.text)
            if cmd_reply == "__EXIT__":
                break
            if cmd_reply is not None:
                try:
                    channel.write(Message(cmd_reply, msg.chat_id))
                except Exception as e:
                    print("ошибка отправки:", e)
                continue
            try:
                reply = agent.run(msg.text)
            except Exception as e:
                import traceback
                traceback.print_exc()
                reply = f"[ошибка агента] {e}"
            try:
                channel.write(Message(reply, msg.chat_id))
            except Exception as e:
                print("ошибка отправки:", e)
    finally:
        channel.close()
        agent.close()


class TUIChannel(Channel):
    def __init__(self, title: str = "ideal-agent"):
        self.title = title
        self.lines: List[str] = []

    def read(self) -> Optional[Message]:
        raise NotImplementedError("TUIChannel использует run_session(agent)")

    def write(self, msg: Message):
        raise NotImplementedError("TUIChannel использует run_session(agent)")

    def run_session(self, agent):
        try:
            curses.wrapper(self._loop, agent)
        except Exception as e:
            print("ошибка TUI:", e)

    def _loop(self, stdscr, agent):
        from . import __version__
        from .config import save_runtime_settings
        from .llm import get_provider
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_RED, -1)
            curses.init_pair(5, curses.COLOR_WHITE, -1)
        except curses.ошибка:
            pass

        def c(n):
            try:
                return curses.color_pair(n)
            except curses.ошибка:
                return 0

        h = w = 0
        hist = inp = None
        stdscr.keypad(True)

        history: List[str] = []
        hist_idx = 0
        buf = ""
        attachments = []
        screen = "chat"
        settings_idx = 0
        view_offset = 0
        settings = [
            ("Провайдер", "provider"), ("Модель", "model"), ("Base URL", "base_url"),
            ("Режим апрува", "mode"), ("Workspace", "workspace"),
            ("Sandbox", "sandbox_mode"), ("Контекст", "use_context"),
            ("Доверенные extensions", "trusted_extensions"),
            ("Разрешения extensions", "extension_permissions"),
            ("Таймаут (сек)", "timeout"), ("Повторы HTTP", "retries"),
        ]

        def rebuild_windows():
            nonlocal h, w, hist, inp
            h, w = stdscr.getmaxyx()
            # Header (1) + history + input (4) + footer (1).  Do not draw
            # into a border row: small mobile terminals expose it immediately.
            input_y = h - 5
            hist = curses.newwin(max(2, input_y - 1), max(1, w), 1, 0)
            inp = curses.newwin(4, max(1, w), max(1, input_y), 0)
            inp.keypad(True)
            hist.scrollok(True)

        def setting_value(key):
            if key in ("trusted_extensions", "extension_permissions"):
                return ", ".join(getattr(agent.cfg, key) or []) or "нет"
            if key in ("provider", "model", "base_url", "timeout", "retries"):
                return str(getattr(agent.cfg.llm, key))
            return str(getattr(agent.cfg, key))

        def wrapped_lines():
            width = max(8, w - 4)
            out = []
            for raw in self.lines:
                if raw.startswith("you> "):
                    prefix, color, body = "you> ", c(2), raw[5:]
                elif raw.startswith("agent> "):
                    prefix, color, body = "agent> ", c(1), raw[7:]
                else:
                    prefix, color, body = "", c(5), raw
                chunks = _wrap_terminal_text(body, max(1, width - _terminal_width(prefix)))
                out.append((prefix + chunks[0], color))
                indent = " " * _terminal_width(prefix)
                out.extend((indent + chunk, color) for chunk in chunks[1:])
            return out

        def save_settings():
            try:
                save_runtime_settings(agent.cfg, getattr(agent.cfg, "_config_path", None))
                return "Настройки сохранены"
            except Exception as exc:
                return f"Не удалось сохранить: {exc}"

        def edit_setting():
            nonlocal settings_idx
            label, key = settings[settings_idx]
            if key == "use_context":
                agent.cfg.use_context = not agent.cfg.use_context
            elif key == "mode":
                modes = ("suggest", "auto", "full-auto")
                agent.cfg.mode = modes[(modes.index(agent.cfg.mode) + 1) % len(modes)] if agent.cfg.mode in modes else "auto"
                agent.gate.mode = agent.cfg.mode
            elif key == "sandbox_mode":
                modes = ("required", "best-effort", "disabled")
                current = agent.cfg.sandbox_mode
                agent.cfg.sandbox_mode = modes[(modes.index(current) + 1) % len(modes)] if current in modes else "required"
            else:
                try:
                    inp.erase()
                    inp.box()
                    current = setting_value(key)
                    inp.addstr(0, 2, f" {label}: {current} ", c(5) | curses.A_BOLD)
                    inp.addstr(1, 1, "> ", c(2))
                    inp.move(1, 3)
                    curses.echo()
                    raw = inp.getstr(1, 3, max(1, w - 5)).decode("utf-8").strip()
                    curses.noecho()
                except Exception:
                    return
                if not raw:
                    return
                try:
                    if key in ("timeout", "retries"):
                        setattr(agent.cfg.llm, key, int(raw))
                    elif key in ("trusted_extensions", "extension_permissions"):
                        values = [item.strip() for item in raw.split(",") if item.strip()]
                        if key == "extension_permissions":
                            values = [item.lower() for item in values]
                        setattr(agent.cfg, key, values)
                    elif key in ("provider", "model", "base_url"):
                        old = (agent.cfg.llm.provider, agent.cfg.llm.model, agent.cfg.llm.base_url, agent.provider)
                        setattr(agent.cfg.llm, key, raw)
                        try:
                            agent.provider = get_provider(agent.cfg.llm)
                        except Exception:
                            agent.cfg.llm.provider, agent.cfg.llm.model, agent.cfg.llm.base_url, agent.provider = old
                            raise
                    else:
                        setattr(agent.cfg, key, raw)
                except Exception as exc:
                    self.lines.append(f"system> Некорректное значение: {exc}")
                    return
            self.lines.append("system> " + save_settings())

        def draw_input():
            inp.erase()
            inp.box()
            try:
                attachment_label = ", ".join(a["name"] for a in attachments)
                title = " ввод · F2 настройки · F3 модули · Ctrl+D выход "
                if attachment_label:
                    title = f" 📎 {attachment_label} "
                inp.addstr(0, 2, title[: max(1, w - 4)], c(5) | curses.A_BOLD)
            except curses.ошибка:
                pass
            for row, part in enumerate(_wrap_terminal_text("> " + buf, max(1, w - 4))[:2]):
                try: inp.addstr(1 + row, 2, _clip_terminal_text(part, w - 4), c(2))
                except curses.ошибка: pass
            inp.noutrefresh()

        def add_attachment(path):
            if len(attachments) >= TUI_MAX_ATTACHMENTS:
                self.lines.append(f"system> Можно прикрепить не более {TUI_MAX_ATTACHMENTS} файлов")
                return
            try:
                attachment = terminal_attachment(path)
                attachments.append(attachment)
                self.lines.append(f"system> Прикреплён {attachment['kind']}: {attachment['name']}")
            except Exception as exc:
                self.lines.append(f"system> Не удалось прикрепить файл: {exc}")

        def clear_attachments(items):
            for attachment in items:
                if attachment.get("temporary"):
                    try:
                        os.unlink(attachment["path"])
                    except OSError:
                        pass

        def draw_header():
            stdscr.erase()
            title = f" ⚡ {self.title} v{__version__} · {agent.provider.__class__.__name__}/{agent.provider.model} "
            try:
                clipped = _clip_terminal_text(title, w - 1)
                stdscr.addstr(0, 0, clipped, c(1) | curses.A_BOLD)
                stdscr.addstr(0, _terminal_width(clipped), " " * max(0, w - _terminal_width(clipped) - 1), c(5))
            except curses.ошибка:
                pass
            stdscr.noutrefresh()

        def draw_footer():
            footer = " ↑/↓ история · PgUp/PgDn прокрутка · F2 настройки · F3 модули · Ctrl+D выход "
            try:
                stdscr.addstr(h - 1, 0, footer[: w - 1], c(3))
            except curses.ошибка:
                pass
            stdscr.noutrefresh()

        def refresh():
            # Soft keyboards and Termux can resize without delivering a
            # KEY_RESIZE event to the active child window.
            if stdscr.getmaxyx() != (h, w):
                rebuild_windows()
            draw_header()
            hist.erase()
            hist.box()
            maxl = hist.getmaxyx()[0] - 2
            if screen == "settings":
                view = [("Настройки (Enter изменить/переключить, S сохранить, Esc назад)", c(1))]
                view.extend((f"{'›' if i == settings_idx else ' '} {label}: {setting_value(key)}", c(2 if i == settings_idx else 5))
                            for i, (label, key) in enumerate(settings))
                view.append((f"Конфиг: {getattr(agent.cfg, '_config_path', '~/.config/ideal-agent/config.json')}", c(3)))
            elif screen == "modules":
                clients = getattr(agent, "_mcp_clients", [])
                extension_tools = [f"{t.name} ({t.source})" for t in agent.registry.details()
                                   if t.source != "builtin"]
                view = [("Подключённые модули (F3/Esc назад)", c(1)),
                        (f"Tools: {', '.join(sorted(agent.registry._tools)) or 'нет'}", c(5)),
                        (f"Extensions: {', '.join(extension_tools) or 'нет'}", c(5)),
                        (f"Skills: {', '.join(getattr(agent, '_loaded_skills', [])) or 'нет'}", c(5)),
                        (f"MCP: {len(clients)} подключено", c(3))]
                for client in clients:
                    state = "работает" if client.proc.poll() is None else f"завершён ({client.proc.returncode})"
                    view.append((f"  • {client.command} {' '.join(client.args)} — {state}", c(2 if client.proc.poll() is None else 4)))
                if not clients and agent.cfg.mcp_servers:
                    view.extend((f"  • {spec} — не подключён", c(4)) for spec in agent.cfg.mcp_servers)
            else:
                view = wrapped_lines()
            start = max(0, len(view) - maxl - view_offset)
            end = len(view) - view_offset if view_offset else len(view)
            for i, item in enumerate(view[start:end][:maxl]):
                ln, color = item
                try:
                    hist.addstr(1 + i, 1, _clip_terminal_text(ln, w - 2), color)
                except curses.ошибка:
                    pass
            hist.noutrefresh()
            draw_footer()
            if screen == "chat": draw_input()
            curses.doupdate()

        rebuild_windows()
        refresh()
        while True:
            source = inp if screen == "chat" else stdscr
            ch = source.get_wch()
            if isinstance(ch, int):
                code, char = ch, None
            elif isinstance(ch, tuple):
                if len(ch) == 2 and isinstance(ch[0], int):
                    code, char = ch
                else:
                    code, char = None, ch[0] if ch else None
            else:
                code, char = None, ch

            o = ord(char) if char else None

            if code == getattr(curses, "KEY_RESIZE", -999):
                rebuild_windows(); refresh(); continue
            if code in (4, -1) or o == 4:
                break
            if code == 3 or o == 3:
                break
            if code == getattr(curses, "KEY_F2", -999) or o == 15:
                screen = "settings"; view_offset = 0; refresh(); continue
            if code == getattr(curses, "KEY_F3", -999):
                screen = "chat" if screen == "modules" else "modules"
                view_offset = 0; refresh(); continue
            if screen != "chat":
                if code == 27 or o == 27 or code == getattr(curses, "KEY_F3", -998):
                    screen = "chat"; refresh(); continue
                if code == curses.KEY_UP:
                    settings_idx = max(0, settings_idx - 1); refresh(); continue
                if code == curses.KEY_DOWN:
                    settings_idx = min(len(settings) - 1, settings_idx + 1); refresh(); continue
                if screen == "settings" and (code in (10, 13, curses.KEY_ENTER) or o in (10, 13)):
                    edit_setting(); refresh(); continue
                if screen == "settings" and char and char.lower() == "s":
                    self.lines.append("system> " + save_settings()); refresh(); continue
                continue
            if code == getattr(curses, "KEY_F1", -999) or (char and char == "?"):
                self.lines.append("system> /attach ПУТЬ · /files · /detach N · /screenshot · /settings · /modules · /about")
                refresh(); continue
            if code == getattr(curses, "KEY_PPAGE", -999):
                view_offset = min(len(wrapped_lines()), view_offset + max(1, h - 6)); refresh(); continue
            if code == getattr(curses, "KEY_NPAGE", -999):
                view_offset = max(0, view_offset - max(1, h - 6)); refresh(); continue
            if code in (curses.KEY_UP,):
                if history:
                    hist_idx = max(0, hist_idx - 1)
                    buf = history[hist_idx]
                    refresh()
                continue
            if code in (curses.KEY_DOWN,):
                if history:
                    hist_idx = min(len(history), hist_idx + 1)
                    buf = history[hist_idx] if hist_idx < len(history) else ""
                    refresh()
                continue
            if code in (127, 8, curses.KEY_BACKSPACE) or o in (127, 8):
                buf = buf[:-1]
                refresh()
                continue
            if code in (10, 13, curses.KEY_ENTER) or o in (10, 13):
                text = buf.strip()
                buf = ""
                view_offset = 0
                if text in ("/exit", "/quit"):
                    break
                if text.startswith("/attach "):
                    add_attachment(text.split(None, 1)[1]); refresh(); continue
                if text == "/files":
                    names = [f"{i + 1}. {a['name']} ({a['kind']})" for i, a in enumerate(attachments)]
                    self.lines.append("system> Вложения: " + (" · ".join(names) if names else "нет"))
                    refresh(); continue
                if text.startswith("/detach"):
                    try:
                        index = int(text.split(None, 1)[1]) - 1
                        attachment = attachments.pop(index)
                        clear_attachments([attachment])
                        self.lines.append(f"system> Убрано: {attachment['name']}")
                    except (ValueError, IndexError):
                        self.lines.append("system> Используй: /detach НОМЕР (см. /files)")
                    refresh(); continue
                if text == "/screenshot":
                    try:
                        screenshot = capture_terminal_screenshot()
                        if len(attachments) >= TUI_MAX_ATTACHMENTS:
                            clear_attachments([screenshot])
                            self.lines.append(f"system> Можно прикрепить не более {TUI_MAX_ATTACHMENTS} файлов")
                        else:
                            attachments.append(screenshot)
                            self.lines.append(f"system> Прикреплён скриншот: {screenshot['name']}")
                    except Exception as exc:
                        self.lines.append(f"system> Не удалось сделать скриншот: {exc}")
                    refresh(); continue
                if text == "/settings":
                    screen = "settings"; refresh(); continue
                if text == "/modules":
                    screen = "modules"; refresh(); continue
                if text == "/about":
                    self.lines.append(f"system> {self.title} v{__version__} · Python {sys.version.split()[0]}")
                    refresh(); continue
                if not text and not attachments:
                    refresh()
                    continue
                cmd_reply = agent.command(text)
                if cmd_reply is not None:
                    if cmd_reply == "__EXIT__":
                        break
                    history.append(text)
                    hist_idx = len(history)
                    self.lines.append("you> " + text)
                    self.lines.append("agent> " + cmd_reply)
                    refresh()
                    continue
                history.append(text)
                hist_idx = len(history)
                label = text if text else "(только вложения)"
                if attachments:
                    label += " [📎 " + ", ".join(a["name"] for a in attachments) + "]"
                self.lines.append("you> " + label)
                self.lines.append("agent> " + self.title + " думает...")
                refresh()
                acc = ""
                selected_attachments = attachments[:]
                attachments.clear()
                try:
                    for chunk in agent.stream(text, attachments=selected_attachments):
                        acc += chunk
                        self.lines[-1] = "agent> " + acc
                        refresh()
                except Exception as e:
                    acc = f"[ошибка] {e}"
                    self.lines[-1] = "agent> " + acc
                    refresh()
                finally:
                    clear_attachments(selected_attachments)
                continue
            if char and o is not None and o >= 32 and o != 127:
                buf += char
                refresh()

        clear_attachments(attachments)


class SocketChannel(Channel):
    MAX_LINE_BYTES = 64 * 1024

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, token: str = ""):
        self.host = host
        self.port = port
        self.token = token
        self._conn = None
        self._file = None
        self._server = None

    def _authorized(self, obj):
        if not self.token:
            return self.host in ("127.0.0.1", "::1", "localhost")
        return hmac.compare_digest(str(obj.get("token", "")), self.token)

    def read(self) -> Optional[Message]:
        import socket
        if self._conn is None:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind((self.host, self.port))
            self._server.listen(1)
            print(f"IDE channel: слушаю {self.host}:{self.port}")
            self._conn, _ = self._server.accept()
            self._file = self._conn.makefile("rwb", buffering=0)
        for line in self._file:
            if len(line) > self.MAX_LINE_BYTES:
                self.write(Message("ошибка: сообщение слишком длинное"))
                return None
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not self._authorized(obj):
                self.write(Message("ошибка: unauthorized"))
                return None
            return Message(obj.get("text", ""))
        return None

    def write(self, msg: Message):
        if self._file:
            self._file.write((json.dumps({"text": msg.text}) + "\n").encode())

    def close(self):
        for resource in (self._file, self._conn, self._server):
            if resource is not None:
                try:
                    resource.close()
                except OSError:
                    pass
        self._file = self._conn = self._server = None


class HTTPChannel(Channel):
    """HTTP-интерфейс для компаньон-приложения (Android) и внешних сервисов
    (например, GitHub webhooks). Чистый stdlib, без зависимостей.

    Эндпоинты:
      GET  /            -> статус агента
      POST /message     -> {"text": "..."}  => {"reply": "...", "chat_id": "http"}
      POST /webhook/github -> GitHub-событие (push/issue) проксируется агенту
    """

    MAX_BODY_BYTES = 12 * 1024 * 1024
    MAX_ATTACHMENTS = 5
    MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
    MAX_TEXT_CHARS = 64 * 1024

    def __init__(self, host: str = "127.0.0.1", port: int = 8080,
                 token: str = "", github_webhook_secret: str = ""):
        self.host = host
        self.port = port
        self.token = token
        self.github_webhook_secret = github_webhook_secret
        self._agent = None
        self.rate_limit = 60
        self.rate_window_seconds = 60
        self._rate_lock = threading.Lock()
        self._rate_events = {}

    def _allow_request(self, key: str) -> bool:
        now = time.monotonic()
        with self._rate_lock:
            events = self._rate_events.setdefault(key, deque())
            while events and events[0] <= now - self.rate_window_seconds:
                events.popleft()
            if len(events) >= self.rate_limit:
                return False
            events.append(now)
            return True

    def read(self) -> Optional[Message]:
        raise NotImplementedError("HTTPChannel использует run(agent)")

    def write(self, msg: Message):
        raise NotImplementedError("HTTPChannel использует run(agent)")

    @staticmethod
    def _prepare_attachments(data):
        """Извлекает вложения из JSON-поля attachments (base64) во временные
        файлы и возвращает список словарей для agent.run/stream.
        Формат элемента: {"name": str, "mime": str, "data": <base64 str>}."""
        atts = data.get("attachments") or []
        if not atts:
            return None, None
        if not isinstance(atts, list) or len(atts) > HTTPChannel.MAX_ATTACHMENTS:
            return None, None
        out = []
        d = tempfile.mkdtemp(prefix="ideal-att-")
        for i, a in enumerate(atts):
            if not isinstance(a, dict):
                continue
            raw = a.get("data")
            if not raw:
                continue
            try:
                blob = base64.b64decode(raw, validate=True)
            except Exception:
                continue
            if len(blob) > HTTPChannel.MAX_ATTACHMENT_BYTES:
                continue
            name = (a.get("name") or f"file{i}").replace("/", "_")
            mime = a.get("mime") or "application/octet-stream"
            path = os.path.join(d, name)
            try:
                with open(path, "wb") as f:
                    f.write(blob)
            except Exception:
                continue
            if mime.startswith("image/"):
                kind = "image"
            elif mime.startswith("text/") or name.lower().endswith(
                (".txt", ".md", ".py", ".json", ".csv", ".log", ".xml", ".yaml",
                 ".yml", ".sh", ".kt", ".java", ".js", ".ts", ".html", ".css",
                 ".go", ".rs", ".c", ".cpp", ".h", ".toml", ".ini", ".env")
            ):
                kind = "text"
            else:
                kind = "binary"
            out.append({"kind": kind, "name": name, "mime": mime, "path": path})
        if not out:
            shutil.rmtree(d, ignore_errors=True)
            return None, None
        return out, d

    @staticmethod
    def _cleanup_attachments(directory):
        if directory:
            shutil.rmtree(directory, ignore_errors=True)

    def run(self, agent):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self._agent = agent
        bot = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code, obj):
                body = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

            def _authorized(self):
                # A token is mandatory on any non-loopback listener.  Loopback
                # remains convenient for the Termux companion, but may opt in
                # to the same token with IDEAL_HTTP_TOKEN.
                if not bot.token:
                    return self.client_address[0] in ("127.0.0.1", "::1")
                supplied = self.headers.get("X-Ideal-Agent-Token", "")
                return hmac.compare_digest(supplied, bot.token)

            def _forbidden(self):
                self._send(401, {"ok": False, "error": "unauthorized"})

            def _rate_limited(self):
                self._send(429, {"ok": False, "error": "rate limit exceeded"})

            def _rate_key(self):
                if bot.token:
                    return "token:" + self.headers.get("X-Ideal-Agent-Token", "")
                return "ip:" + self.client_address[0]

            def _valid_github_signature(self, raw):
                if not bot.github_webhook_secret:
                    return False
                header = self.headers.get("X-Hub-Signature-256", "")
                expected = "sha256=" + hmac.new(
                    bot.github_webhook_secret.encode(), raw, hashlib.sha256
                ).hexdigest()
                return hmac.compare_digest(header, expected)

            def do_GET(self):
                if not self._authorized():
                    self._forbidden()
                    return
                if self.path in ("/", "/status"):
                    self._send(200, {
                        "ok": True,
                        "provider": bot._agent.provider.__class__.__name__,
                        "model": bot._agent.provider.model,
                        "mode": bot._agent.gate.mode,
                        "tools": len(bot._agent.registry._tools),
                    })
                else:
                    self._send(404, {"ok": False, "error": "not found"})

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > HTTPChannel.MAX_BODY_BYTES:
                        self._send(413, {"ok": False, "error": "request too large"})
                        return
                    raw = self.rfile.read(length) if length else b"{}"
                    data = json.loads(raw.decode() or "{}")
                    if not isinstance(data, dict):
                        data = {}
                except Exception:
                    data = {}
                if not self._authorized():
                    self._forbidden()
                    return
                if not bot._allow_request(self._rate_key()):
                    self._rate_limited()
                    return
                if self.path == "/message":
                    text = (data.get("text") or "").strip()
                    if len(text) > HTTPChannel.MAX_TEXT_CHARS:
                        self._send(413, {"ok": False, "error": "text too large"})
                        return
                    attachments, attachment_dir = HTTPChannel._prepare_attachments(data)
                    session_id = data.get("session_id") or "default"
                    if not text and not attachments:
                        HTTPChannel._cleanup_attachments(attachment_dir)
                        self._send(400, {"ok": False, "error": "empty text"})
                        return
                    cmd = bot._agent.command_in_session(session_id, text) if text else None
                    if cmd == "__EXIT__":
                        HTTPChannel._cleanup_attachments(attachment_dir)
                        self._send(200, {"ok": True, "reply": "bye"})
                        return
                    if cmd is not None:
                        HTTPChannel._cleanup_attachments(attachment_dir)
                        self._send(200, {"ok": True, "reply": cmd, "chat_id": "http"})
                        return
                    try:
                        reply = bot._agent.run_in_session(session_id, text, attachments=attachments)
                    except Exception as e:
                        reply = f"[ошибка агента] {e}"
                    finally:
                        HTTPChannel._cleanup_attachments(attachment_dir)
                    self._send(200, {"ok": True, "reply": reply, "chat_id": "http"})
                elif self.path == "/webhook/github":
                    if not self._valid_github_signature(raw):
                        self._send(401, {"ok": False, "error": "invalid github signature"})
                        return
                    event = self.headers.get("X-GitHub-Event", "ping")
                    if event == "ping":
                        self._send(200, {"ok": True})
                        return
                    text = bot._format_github(event, data)
                    try:
                        bot._agent.run_in_session("github-webhook", text)
                    except Exception as e:
                        print("ошибка агента (github webhook):", e)
                    self._send(200, {"ok": True})
                elif self.path == "/message/stream":
                    text = (data.get("text") or "").strip()
                    if len(text) > HTTPChannel.MAX_TEXT_CHARS:
                        self._send(413, {"ok": False, "error": "text too large"})
                        return
                    attachments, attachment_dir = HTTPChannel._prepare_attachments(data)
                    session_id = data.get("session_id") or "default"
                    if not text and not attachments:
                        HTTPChannel._cleanup_attachments(attachment_dir)
                        self._send(400, {"ok": False, "error": "empty text"})
                        return
                    cmd = bot._agent.command_in_session(session_id, text) if text else None
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    try:
                        if cmd == "__EXIT__":
                            self.wfile.write(b"data: " + json.dumps({"chunk": "bye"}).encode() + b"\n\n")
                        elif cmd is not None:
                            self.wfile.write(b"data: " + json.dumps({"chunk": cmd}).encode() + b"\n\n")
                        else:
                            try:
                                for chunk in bot._agent.stream_in_session(session_id, text, attachments=attachments):
                                    self.wfile.write(b"data: " + json.dumps({"chunk": chunk}, ensure_ascii=False).encode() + b"\n\n")
                                    self.wfile.flush()
                            finally:
                                HTTPChannel._cleanup_attachments(attachment_dir)
                    except Exception as e:
                        self.wfile.write(b"data: " + json.dumps({"chunk": f"[ошибка] {e}"}).encode() + b"\n\n")
                    finally:
                        HTTPChannel._cleanup_attachments(attachment_dir)
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                else:
                    self._send(404, {"ok": False, "error": "not found"})

        print(f"HTTP-канал запущен: http://{self.host}:{self.port} (сообщения + github webhook)")
        srv = ThreadingHTTPServer((self.host, self.port), Handler)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()

    @staticmethod
    def _format_github(event, data):
        if event == "push":
            repo = data.get("repository", {}).get("full_name", "?")
            branch = data.get("ref", "").replace("refs/heads/", "")
            commits = data.get("commits", [])
            summary = "; ".join(c.get("message", "").splitlines()[0] for c in commits[:5])
            return f"[GitHub push] {repo} -> {branch}: {summary}"
        if event in ("issues", "issue_comment"):
            act = data.get("action", "")
            repo = data.get("repository", {}).get("full_name", "?")
            title = data.get("issue", {}).get("title", "")
            return f"[GitHub {event}] {act} в {repo}: {title}"
        if event == "pull_request":
            act = data.get("action", "")
            repo = data.get("repository", {}).get("full_name", "?")
            pr = data.get("pull_request", {})
            return f"[GitHub PR] {act} в {repo}: {pr.get('title','')}"
        return f"[GitHub {event}] событие получено"
