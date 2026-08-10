from __future__ import annotations
import glob as gmod
import os
import re
import subprocess

from . import safety


ALLOWED_NOTE = "операция вне workspace запрещена"


def _roots(cfg):
    return [os.path.realpath(os.path.expanduser(cfg.workspace))]


def _check(p, roots):
    if not p:
        return None
    rp = os.path.realpath(os.path.expanduser(p))
    for r in roots:
        if rp == r or rp.startswith(r + os.sep):
            return rp
    return None


def register_builtin_tools(registry, cfg):
    roots = _roots(cfg)

    def read_file(args):
        p = _check(args.get("path", ""), roots)
        if not p:
            return "ошибка: " + ALLOWED_NOTE
        try:
            with open(p, encoding="utf-8") as f:
                data = f.read()
        except Exception as e:
            return f"ошибка: {e}"
        limit = int(args.get("limit", 0) or 0)
        if limit > 0:
            data = "\n".join(data.splitlines()[:limit])
        return data

    def write_file(args):
        p = _check(args.get("path", ""), roots)
        if not p:
            return "ошибка: " + ALLOWED_NOTE
        try:
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(args.get("content", ""))
        except Exception as e:
            return f"ошибка: {e}"
        return f"записано: {p}"

    def edit_file(args):
        p = _check(args.get("path", ""), roots)
        if not p:
            return "ошибка: " + ALLOWED_NOTE
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        try:
            with open(p, encoding="utf-8") as f:
                data = f.read()
        except Exception as e:
            return f"ошибка: {e}"
        if old not in data:
            return "ошибка: old_string не найдена"
        data = data.replace(old, new, 1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(data)
        return f"изменено: {p}"

    def glob_files(args):
        pat = args.get("pattern", "*")
        out = []
        for r in roots:
            for m in gmod.glob(os.path.join(r, pat), recursive=True):
                if os.path.isfile(m):
                    out.append(m)
        return "\n".join(out[:200]) or "нет совпадений"

    def grep_files(args):
        pat = args.get("pattern", "")
        path = args.get("path", roots[0])
        rp = _check(path, roots)
        if not rp:
            return "ошибка: " + ALLOWED_NOTE
        if not os.path.isdir(rp):
            return "ошибка: path не каталог"
        rx = re.compile(pat)
        res = []
        for dp, _, fs in os.walk(rp):
            if ".git" in dp:
                continue
            for fn in fs:
                fp = os.path.join(dp, fn)
                try:
                    with open(fp, encoding="utf-8") as f:
                        lines = f.readlines()
                except (OSError, UnicodeDecodeError):
                    continue
                for i, l in enumerate(lines, 1):
                    if rx.search(l):
                        res.append(f"{fp}:{i}: {l.rstrip()}")
                    if len(res) >= 200:
                        break
                if len(res) >= 200:
                    break
        return "\n".join(res) or "не найдено"

    def shell(args):
        cmd = args.get("command", "")
        return safety.run_sandboxed(cmd, timeout=int(args.get("timeout", 30)), cwd=roots[0])

    registry.register(
        "read_file",
        "Прочитать файл. Аргументы: path (str), limit (int, опц.).",
        {"type": "object", "properties": {
            "path": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["path"]},
        read_file,
    )
    registry.register(
        "write_file",
        "Записать файл. Аргументы: path (str), content (str).",
        {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]},
        write_file,
    )
    registry.register(
        "edit_file",
        "Заменить old_string на new_string в файле. Аргументы: path, old_string, new_string.",
        {"type": "object", "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"}},
            "required": ["path", "old_string", "new_string"]},
        edit_file,
    )
    registry.register(
        "glob",
        "Найти файлы по шаблону. Аргументы: pattern (str).",
        {"type": "object", "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"]},
        glob_files,
    )
    registry.register(
        "grep",
        "Поиск по содержимому файлов. Аргументы: pattern (str), path (str, опц.).",
        {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"}},
            "required": ["pattern"]},
        grep_files,
    )
    registry.register(
        "shell",
        "Выполнить shell-команду с таймаутом. Аргументы: command (str), timeout (int, опц.).",
        {"type": "object", "properties": {
            "command": {"type": "string"}, "timeout": {"type": "integer"}},
            "required": ["command"]},
        shell,
    )
