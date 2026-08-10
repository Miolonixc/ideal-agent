from __future__ import annotations
import json
import os
import subprocess
import re
from typing import List, Optional


def _parse_manifest(path: str):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    meta = {}
    desc = ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            desc = parts[2].strip()
    return meta, desc


def _find_script(skill_dir: str) -> Optional[str]:
    for name in ("run.py", "run.sh"):
        p = os.path.join(skill_dir, name)
        if os.path.isfile(p):
            return p
    return None


def tool_name(name: str) -> str:
    """Names exposed to providers are stable and cannot shadow built-ins."""
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "extension"
    return "skill_" + safe_name


def load_skills(registry, skills_dir: str, trusted_extensions=None) -> List[str]:
    if not os.path.isdir(skills_dir):
        return []
    loaded = []
    for name in sorted(os.listdir(skills_dir)):
        skill_dir = os.path.join(skills_dir, name)
        manifest = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(manifest):
            continue
        meta, desc = _parse_manifest(manifest)
        sname = meta.get("name", name)
        sdesc = meta.get("description", desc) or name
        script = _find_script(skill_dir)
        trusted = trusted_extensions is None or _is_trusted(trusted_extensions, "skill", sname)

        def make_handler(script, skill_dir, desc, trusted, sname):
            def handler(args):
                if script and not trusted:
                    return (f"заблокировано: skill '{sname}' не отмечен доверенным. "
                            f"Добавь 'skill:{sname}' в trusted_extensions конфига.")
                if script:
                    try:
                        env = dict(os.environ)
                        env["IDEAL_SKILL_INPUT"] = json.dumps(args)
                        r = subprocess.run(
                            [script], input=json.dumps(args), capture_output=True,
                            text=True, cwd=skill_dir, env=env, timeout=60,
                        )
                        return (r.stdout or r.stderr)[:4000]
                    except Exception as e:
                        return f"ошибка: {e}"
                return desc[:4000]
            return handler

        registry.register(
            tool_name(sname),
            sdesc,
            {"type": "object", "properties": {"input": {"type": "string"}},
             "required": []},
            make_handler(script, skill_dir, desc, trusted, sname),
            source="skill",
        )
        loaded.append(sname)
    return loaded


def _is_trusted(allowed, kind: str, name: str) -> bool:
    allowed = set(allowed or [])
    return f"{kind}:*" in allowed or f"{kind}:{name}" in allowed
