from __future__ import annotations
#!/usr/bin/env python3
"""Отправить push-уведомление пользователю через Telegram-бота агента.

Использование:
  python3 notify.py "агент закончил задачу"
  echo "текст" | python3 notify.py

Берёт токен и список allowed из ~/.config/ideal-agent/config.json
(поле telegram.token / telegram.allowed). Чистый stdlib.
"""
import json
import os
import sys
import urllib.request
import urllib.parse


def _cfg():
    p = os.path.expanduser("~/.config/ideal-agent/config.json")
    if not os.path.exists(p):
        return None, []
    c = json.load(open(p, encoding="utf-8"))
    tg = c.get("telegram") or {}
    return tg.get("token"), tg.get("allowed") or []


def main():
    token, allowed = _cfg()
    if not token:
        print("нет telegram.token в config.json", file=sys.stderr)
        sys.exit(1)
    text = sys.stdin.read().strip() if not sys.argv[1:] else " ".join(sys.argv[1:])
    if not text:
        print("пустое сообщение", file=sys.stderr)
        sys.exit(1)
    chat = allowed[0] if allowed else None
    if not chat:
        print("нет telegram.allowed в config.json", file=sys.stderr)
        sys.exit(1)
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=data, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print("отправлено:", r.status)
    except Exception as e:
        print("ошибка:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
