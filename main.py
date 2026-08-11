from __future__ import annotations
import os
import sys

from agent.config import load
from agent.core import Agent
from agent.channels import CLIChannel, TelegramChannel, Message, serve


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

    if rest and rest[0] in ("cli", "tui", "ide", "http", "telegram"):
        sub = rest[0]
        extra = rest[1:]
    else:
        sub = None
        extra = rest

    config_path = opts["config"] or os.path.expanduser("~/.config/ideal-agent/config.json")
    cfg = load(config_path)
    cfg._config_path = config_path
    if opts["mode"]:
        cfg.mode = opts["mode"]
    if opts["provider"]:
        cfg.llm.provider = opts["provider"]
    if opts["model"]:
        cfg.llm.model = opts["model"]
    if opts["workspace"]:
        cfg.workspace = opts["workspace"]

    agent = Agent(cfg)

    skills_dir = os.environ.get("SKILLS_DIR") or cfg.skills_dir
    if skills_dir:
        loaded = agent.load_skills_dir(skills_dir)
        print("навыки:", loaded)

    mcp_specs = os.environ.get("MCP_SERVERS")
    specs = mcp_specs.split("|") if mcp_specs else cfg.mcp_servers
    if opts["dry_run"]:
        print(agent.dry_run_report(specs))
        agent.close()
        return
    for spec in specs:
        spec = spec.strip()
        if not spec:
            continue
        parts = spec.split()
        try:
            agent.connect_mcp(parts[0], parts[1:])
            print("mcp:", parts[0])
        except (PermissionError, ValueError) as e:
            print("mcp пропущен:", e)

    token = os.environ.get("TELEGRAM_BOT_TOKEN") or (getattr(cfg, "telegram", None) or {}).get("token")

    if sub == "tui":
        from agent.channels import TUIChannel
        try:
            TUIChannel().run_session(agent)
        finally:
            agent.close()
        return

    if sub == "ide":
        from agent.channels import SocketChannel
        ide_cfg = getattr(cfg, "ide", None) or {}
        port = opts["port"] or int(os.environ.get("IDEAL_IDE_PORT", "8765"))
        host = os.environ.get("IDEAL_IDE_HOST", ide_cfg.get("host", "127.0.0.1"))
        ide_token = os.environ.get("IDEAL_IDE_TOKEN", ide_cfg.get("token", ""))
        serve(SocketChannel(host=host, port=port, token=ide_token), agent)
        return

    if sub == "http":
        from agent.channels import HTTPChannel
        port = opts["port"] or int(os.environ.get("IDEAL_HTTP_PORT", "8080"))
        http_cfg = getattr(cfg, "http", None) or {}
        host = os.environ.get("IDEAL_HTTP_HOST", http_cfg.get("host", "127.0.0.1"))
        token = os.environ.get("IDEAL_HTTP_TOKEN", http_cfg.get("token", ""))
        secret = os.environ.get("IDEAL_GITHUB_WEBHOOK_SECRET", http_cfg.get("github_webhook_secret", ""))
        HTTPChannel(host=host, port=port, token=token, github_webhook_secret=secret).run(agent)
        return

    if sub == "telegram" or (sub is None and token and not extra):
        if not token:
            print("TELEGRAM_BOT_TOKEN не задан и нет telegram.token в конфиге")
            return
        tg_cfg = getattr(cfg, "telegram", None) or {}
        allowed_env = [int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").replace(",", " ").split() if x]
        allowed = allowed_env or tg_cfg.get("allowed", [])
        if not allowed and os.environ.get("IDEAL_ALLOW_PUBLIC_TELEGRAM") != "1":
            print("telegram.allowed обязателен; для явного публичного режима задай IDEAL_ALLOW_PUBLIC_TELEGRAM=1")
            agent.close()
            return
        channel = TelegramChannel(token, allowed=allowed)
        print("telegram-канал: запущен long-poll")
        serve(channel, agent)
        return

    # CLI (по умолчанию)
    channel = CLIChannel()
    if extra:
        # одноразовый запрос
        reply = agent.run(" ".join(extra))
        print(reply)
        return
    serve(channel, agent)


if __name__ == "__main__":
    main()
