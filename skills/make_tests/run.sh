#!/bin/sh
python3 - "$@" <<'PY'
import sys, json, ast, os

raw = os.environ.get("IDEAL_SKILL_INPUT")
data = json.loads(raw) if raw else (json.load(sys.stdin) if not sys.stdin.isatty() else {})
path = (data.get("input") or data.get("message") or "").strip()
if not path:
    print("usage: make_tests <path.py>")
    sys.exit(0)
if not os.path.isfile(path):
    print("error: файл не найден: " + path)
    sys.exit(0)

src = open(path, encoding="utf-8").read()
try:
    tree = ast.parse(src)
except SyntaxError as e:
    print("error: синтаксис: " + str(e))
    sys.exit(0)

funcs = []
classes = []
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
        fargs = [a.arg for a in node.args.args if a.arg != "self" and not a.arg.startswith("_")]
        fargs = ", ".join(fargs)
        fargs = (", " + fargs) if fargs else ""
        funcs.append(("test_" + node.name, fargs))
    elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
        methods = [s.name for s in node.body
                   if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and not s.name.startswith("_")]
        classes.append((node.name, methods))

mod = os.path.splitext(os.path.basename(path))[0]
out_path = os.path.join(os.path.dirname(path), mod + "_test.py")
todo = "TODO: реализовать тест"
lines = ['"""Автосгенерированные заготовки тестов для ' + os.path.basename(path) + '."""',
         "import pytest", "", "import " + mod + "  # или нужный import", ""]
for fname, fargs in funcs:
    lines.append("def " + fname + fargs + ":")
    lines.append('    """' + todo + '."""')
    lines.append("    assert True")
    lines.append("")
for cname, methods in classes:
    lines.append("class Test" + cname + ":")
    if not methods:
        lines.append("    def test_smoke(self):")
        lines.append("        assert True")
    for m in methods:
        lines.append("    def test_" + m + "(self):")
        lines.append('        """' + todo + '."""')
        lines.append("        assert True")
    lines.append("")

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("создан тест-заготовка: " + out_path + " (" + str(len(funcs)) + " функций, " + str(len(classes)) + " классов)")
PY
