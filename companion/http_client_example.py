#!/usr/bin/env python3
"""Пример клиента к HTTP-каналу ideal-agent.

Использование:
  python3 client.py "привет"
  python3 client.py "/status"
  python3 client.py --host 127.0.0.1 --port 8080 "сделай коммит"

Отправляет POST /message и печатает ответ агента. Чистый stdlib.
"""
import json
import sys
import urllib.request


def ask(host, port, text):
    url = f"http://{host}:{port}/message"
    req = urllib.request.Request(
        url,
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def main():
    args = sys.argv[1:]
    host, port = "127.0.0.1", 8080
    if "--host" in args:
        i = args.index("--host"); host = args[i + 1]; args = args[:i] + args[i + 2:]
    if "--port" in args:
        i = args.index("--port"); port = int(args[i + 1]); args = args[:i] + args[i + 2:]
    text = " ".join(args).strip()
    if not text:
        print("usage: client.py [--host H] [--port P] <текст>")
        return
    res = ask(host, port, text)
    print(res.get("reply", res))


if __name__ == "__main__":
    main()
