import json
from dataclasses import dataclass
from typing import Callable, Dict, List


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
            return f"error: unknown tool '{name}'"
        try:
            args = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as e:
            return f"error: bad arguments json: {e}"
        try:
            return str(tool.func(args))
        except Exception as e:
            return f"error: {e}"
