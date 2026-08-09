from __future__ import annotations
import json
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterator, List, Optional

import curses


@dataclass
class Message:
    text: str
    chat_id: Optional[str] = None
    chat_type: Optional[str] = None


class Channel:
    def read(self) -> Optional[Message]:
        raise NotImplementedError

    def write(self, msg: Message):
        raise NotImplementedError


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
                print("write error:", e)
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
            print("write error:", e)


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
            print("TUI error:", e)

    def _loop(self, stdscr, agent):
        agent.gate.mode = "full-auto"
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_RED, -1)
            curses.init_pair(5, curses.COLOR_WHITE, -1)
        except curses.error:
            pass

        def c(n):
            try:
                return curses.color_pair(n)
            except curses.error:
                return 0

        h, w = stdscr.getmaxyx()
        hist = curses.newwin(h - 3, w, 1, 0)
        inp = curses.newwin(2, w, h - 2, 0)
        inp.keypad(True)
        hist.scrollok(True)
        stdscr.keypad(True)

        history: List[str] = []
        hist_idx = 0
        buf = ""

        def draw_input():
            inp.erase()
            inp.box()
            try:
                inp.addstr(0, 2, " ввод (Ctrl+D выход) ", c(5) | curses.A_BOLD)
            except curses.error:
                pass
            prompt = "> " + buf
            try:
                inp.addstr(1, 1, prompt[: w - 2], c(2))
            except curses.error:
                pass
            inp.noutrefresh()

        def draw_header():
            stdscr.erase()
            title = " ⚡ " + self.title + " "
            try:
                stdscr.addstr(0, 0, title, c(1) | curses.A_BOLD)
                stdscr.addstr(0, len(title), " " * (w - len(title) - 1), c(5))
            except curses.error:
                pass
            stdscr.noutrefresh()

        def draw_footer():
            footer = " ↑/↓ история · Enter отправить · Ctrl+D выход "
            try:
                stdscr.addstr(h - 1, 0, footer[: w - 1], c(3))
            except curses.error:
                pass
            stdscr.noutrefresh()

        def refresh():
            draw_header()
            hist.erase()
            hist.box()
            maxl = hist.getmaxyx()[0] - 2
            view = self.lines[-maxl:]
            for i, ln in enumerate(view):
                try:
                    if ln.startswith("you> "):
                        hist.addstr(1 + i, 1, ln[: w - 2], c(2))
                    elif ln.startswith("agent> "):
                        hist.addstr(1 + i, 1, ln[: w - 2], c(1))
                    else:
                        hist.addstr(1 + i, 1, ln[: w - 2], c(5))
                except curses.error:
                    pass
            hist.noutrefresh()
            draw_footer()
            draw_input()
            curses.doupdate()

        refresh()
        while True:
            ch = inp.get_wch()
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

            if code in (4, -1) or o == 4:
                break
            if code == 3 or o == 3:
                break
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
                if text in ("/exit", "/quit"):
                    break
                if not text:
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
                self.lines.append("you> " + text)
                self.lines.append("agent> " + self.title + " думает...")
                refresh()
                acc = ""
                try:
                    for chunk in agent.stream(text):
                        acc += chunk
                        self.lines[-1] = "agent> " + acc
                        refresh()
                except Exception as e:
                    acc = f"[ошибка] {e}"
                    self.lines[-1] = "agent> " + acc
                    refresh()
                continue
            if char and o is not None and o >= 32 and o != 127:
                buf += char
                refresh()


class SocketChannel(Channel):
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self._conn = None
        self._file = None

    def read(self) -> Optional[Message]:
        import socket
        if self._conn is None:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen(1)
            print(f"IDE channel: слушаю {self.host}:{self.port}")
            self._conn, _ = s.accept()
            self._file = self._conn.makefile("rwb", buffering=0)
        for line in self._file:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            return Message(obj.get("text", ""))
        return None

    def write(self, msg: Message):
        if self._file:
            self._file.write((json.dumps({"text": msg.text}) + "\n").encode())


class HTTPChannel(Channel):
    """HTTP-интерфейс для компаньон-приложения (Android) и внешних сервисов
    (например, GitHub webhooks). Чистый stdlib, без зависимостей.

    Эндпоинты:
      GET  /            -> статус агента
      POST /message     -> {"text": "..."}  => {"reply": "...", "chat_id": "http"}
      POST /webhook/github -> GitHub-событие (push/issue) проксируется агенту
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.host = host
        self.port = port
        self._agent = None

    def read(self) -> Optional[Message]:
        raise NotImplementedError("HTTPChannel использует run(agent)")

    def write(self, msg: Message):
        raise NotImplementedError("HTTPChannel использует run(agent)")

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

            def do_GET(self):
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
                    raw = self.rfile.read(length) if length else b"{}"
                    data = json.loads(raw.decode() or "{}")
                except Exception:
                    data = {}
                # переопределение провайдера/модели/ключа на лету (из компаньона)
                override = None
                if data.get("provider") or data.get("api_key") or data.get("model"):
                    try:
                        from agent import llm as _llm
                        override = _llm.build_provider(
                            name=data.get("provider") or "openai-compatible",
                            api_key=data.get("api_key"),
                            model=data.get("model"),
                            base_url=data.get("base_url"),
                        )
                    except Exception:
                        override = None
                if self.path == "/message":
                    text = (data.get("text") or "").strip()
                    if not text:
                        self._send(400, {"ok": False, "error": "empty text"})
                        return
                    cmd = bot._agent.command(text)
                    if cmd == "__EXIT__":
                        self._send(200, {"ok": True, "reply": "bye"})
                        return
                    if cmd is not None:
                        self._send(200, {"ok": True, "reply": cmd, "chat_id": "http"})
                        return
                    try:
                        if override:
                            saved = bot._agent.provider
                            bot._agent.provider = override
                            try:
                                reply = bot._agent.run(text)
                            finally:
                                bot._agent.provider = saved
                        else:
                            reply = bot._agent.run(text)
                    except Exception as e:
                        reply = f"[ошибка агента] {e}"
                    self._send(200, {"ok": True, "reply": reply, "chat_id": "http"})
                elif self.path == "/webhook/github":
                    event = self.headers.get("X-GitHub-Event", "ping")
                    if event == "ping":
                        self._send(200, {"ok": True})
                        return
                    text = bot._format_github(event, data)
                    try:
                        bot._agent.run(text)
                    except Exception as e:
                        print("github webhook agent error:", e)
                    self._send(200, {"ok": True})
                elif self.path == "/message/stream":
                    text = (data.get("text") or "").strip()
                    if not text:
                        self._send(400, {"ok": False, "error": "empty text"})
                        return
                    cmd = bot._agent.command(text)
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
                            saved = None
                            if override:
                                saved = bot._agent.provider
                                bot._agent.provider = override
                            try:
                                for chunk in bot._agent.stream(text):
                                    self.wfile.write(b"data: " + json.dumps({"chunk": chunk}, ensure_ascii=False).encode() + b"\n\n")
                                    self.wfile.flush()
                            finally:
                                if saved is not None:
                                    bot._agent.provider = saved
                    except Exception as e:
                        self.wfile.write(b"data: " + json.dumps({"chunk": f"[ошибка] {e}"}).encode() + b"\n\n")
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                else:
                    self._send(404, {"ok": False, "error": "not found"})

        print(f"HTTP channel: http://{self.host}:{self.port} (message + github webhook)")
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
