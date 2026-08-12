from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

from .channels import CLIChannel, TelegramChannel, serve
from .config import load
from .core import Agent


def _parse_args(argv):
    opts = {"config": None, "mode": None, "provider": None, "model": None,
            "workspace": None, "port": None, "dry_run": False}
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-c", "--config"):
            opts["config"] = argv[i + 1]; i += 2; continue
        if a in ("-m", "--mode"):
            opts["mode"] = argv[i + 1]; i += 2; continue
        if a in ("--provider",):
            opts["provider"] = argv[i + 1]; i += 2; continue
        if a in ("--model",):
            opts["model"] = argv[i + 1]; i += 2; continue
        if a in ("-w", "--workspace"):
            opts["workspace"] = argv[i + 1]; i += 2; continue
        if a in ("-p", "--port"):
            opts["port"] = int(argv[i + 1]); i += 2; continue
        if a == "--dry-run":
            opts["dry_run"] = True; i += 1; continue
        rest.append(a); i += 1
    return opts, rest


def main():
    opts, rest = _parse_args(sys.argv[1:])
    if rest and rest[0] in ("cli", "tui", "opentui", "ide", "http", "telegram"):
        sub, extra = rest[0], rest[1:]
    else:
        sub, extra = None, rest

    config_path = opts["config"] or os.path.expanduser("~/.config/ideal-agent/config.json")
    cfg = load(config_path)
    cfg._config_path = config_path
    if opts["mode"]: cfg.mode = opts["mode"]
    if opts["provider"]: cfg.llm.provider = opts["provider"]
    if opts["model"]: cfg.llm.model = opts["model"]
    if opts["workspace"]: cfg.workspace = opts["workspace"]
    agent = Agent(cfg)

    skills_dir = os.environ.get("SKILLS_DIR") or cfg.skills_dir
    if skills_dir:
        print("навыки:", agent.load_skills_dir(skills_dir))
    mcp_specs = os.environ.get("MCP_SERVERS")
    specs = mcp_specs.split("|") if mcp_specs else cfg.mcp_servers
    if opts["dry_run"]:
        print(agent.dry_run_report(specs)); agent.close(); return
    if sub not in ("tui", "opentui"):
        for spec in specs:
            if not spec: continue
            try:
                agent.connect_mcp_spec(spec); print("mcp:", spec)
            except (PermissionError, ValueError) as e:
                print("mcp пропущен:", e)

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or (getattr(cfg, "telegram", None) or {}).get("token")
    if sub == "tui":
        from .channels import TUIChannel
        try: TUIChannel().run_session(agent)
        finally: agent.close()
        return
    if sub == "opentui":
        bun = shutil.which("bun")
        client = os.path.join(os.path.dirname(os.path.dirname(__file__)), "opentui", "src", "index.ts")
        if not bun:
            print("OpenTUI требует Bun. Установи Bun, либо используй: python3 main.py tui")
            agent.close()
            return
        if not os.path.exists(client):
            print("OpenTUI client не найден; используй: python3 main.py tui")
            agent.close()
            return
        from .channels import HTTPChannel
        http_cfg = getattr(cfg, "http", None) or {}
        port = opts["port"] or int(os.environ.get("IDEAL_HTTP_PORT", "8080"))
        host = os.environ.get("IDEAL_HTTP_HOST", http_cfg.get("host", "127.0.0.1"))
        http_token = os.environ.get("IDEAL_HTTP_TOKEN", http_cfg.get("token", ""))
        if host not in ("127.0.0.1", "::1", "localhost"):
            print("OpenTUI запускает локальный HTTP-сервер; для внешнего доступа используй отдельный http-режим с токеном.")
            agent.close()
            return
        server = HTTPChannel(host=host, port=port, token=http_token)
        threading.Thread(target=server.run, args=(agent,), daemon=True).start()
        env = os.environ.copy()
        env["IDEAL_AGENT_URL"] = f"http://{host}:{port}"
        if http_token:
            env["IDEAL_HTTP_TOKEN"] = http_token
        try:
            subprocess.run([bun, "run", client], env=env, check=False)
        finally:
            agent.close()
        return
    if sub == "ide":
        from .channels import SocketChannel
        ide_cfg = getattr(cfg, "ide", None) or {}
        port = opts["port"] or int(os.environ.get("IDEAL_IDE_PORT", "8765"))
        host = os.environ.get("IDEAL_IDE_HOST", ide_cfg.get("host", "127.0.0.1"))
        ide_token = os.environ.get("IDEAL_IDE_TOKEN", ide_cfg.get("token", ""))
        serve(SocketChannel(host=host, port=port, token=ide_token), agent)
        return
    if sub == "http":
        from .channels import HTTPChannel
        http_cfg = getattr(cfg, "http", None) or {}
        port = opts["port"] or int(os.environ.get("IDEAL_HTTP_PORT", "8080"))
        host = os.environ.get("IDEAL_HTTP_HOST", http_cfg.get("host", "127.0.0.1"))
        token = os.environ.get("IDEAL_HTTP_TOKEN", http_cfg.get("token", ""))
        secret = os.environ.get("IDEAL_GITHUB_WEBHOOK_SECRET", http_cfg.get("github_webhook_secret", ""))
        HTTPChannel(host=host, port=port, token=token, github_webhook_secret=secret).run(agent)
        return
    if sub == "telegram" or (sub is None and token and not extra):
        if not token:
            print("TELEGRAM_BOT_TOKEN не задан и нет telegram.token в конфиге"); return
        tg_cfg = getattr(cfg, "telegram", None) or {}
        allowed_env = [int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").replace(",", " ").split() if x]
        allowed = allowed_env or tg_cfg.get("allowed", [])
        if not allowed and os.environ.get("IDEAL_ALLOW_PUBLIC_TELEGRAM") != "1":
            print("telegram.allowed обязателен; для явного публичного режима задай IDEAL_ALLOW_PUBLIC_TELEGRAM=1")
            agent.close(); return
        print("telegram-канал: запущен long-poll")
        serve(TelegramChannel(token, allowed=allowed), agent)
        return
    if extra:
        try: print(agent.run(" ".join(extra)))
        finally: agent.close()
        return
    serve(CLIChannel(), agent)
