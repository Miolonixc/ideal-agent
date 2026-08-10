from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Callable, Dict, List


MAX_TOOL_OUTPUT = 12_000


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[[dict], str]


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, name, description, parameters, func):
        self._tools[name] = Tool(name, description, parameters, func)

    def schema(self) -> List[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def call(self, name, arguments_json):
        tool = self._tools.get(name)
        if not tool:
            return f"ошибка: unknown tool '{name}'"
        try:
            args = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as e:
            return f"ошибка: bad arguments json: {e}"
        validation_error = _validate_arguments(args, tool.parameters)
        if validation_error:
            return f"ошибка: неверные аргументы: {validation_error}"
        try:
            result = str(tool.func(args))
            if len(result) > MAX_TOOL_OUTPUT:
                return result[:MAX_TOOL_OUTPUT] + "\n[результат обрезан]"
            return result
        except Exception as e:
            return f"ошибка: {e}"


def _validate_arguments(args, schema) -> str:
    """Small, dependency-free subset of JSON Schema used by registered tools."""
    if not isinstance(args, dict):
        return "ожидается JSON-объект"
    if not isinstance(schema, dict) or schema.get("type", "object") != "object":
        return "некорректная схема tool"
    properties = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in args:
            return f"отсутствует обязательное поле '{name}'"
    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    for name, value in args.items():
        spec = properties.get(name)
        if not spec:
            continue  # extensions are allowed for forward-compatible MCP tools
        expected = type_map.get(spec.get("type"))
        if expected and (not isinstance(value, expected) or
                         (spec.get("type") in ("integer", "number") and isinstance(value, bool))):
            return f"поле '{name}' должно иметь тип {spec['type']}"
    return ""
