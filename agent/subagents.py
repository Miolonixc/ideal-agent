from __future__ import annotations
from typing import List, Optional

from . import builtin_tools
from .core import Agent
from .safety import ApprovalGate
from .tools import ToolRegistry


def run_subagent(task: str, cfg, provider, tools: Optional[List[str]] = None) -> str:
    sub = Agent(cfg)
    sub.provider = provider
    if tools is not None:
        sub.registry = ToolRegistry()
        builtin_tools.register_builtin_tools(sub.registry, cfg)
        for k in list(sub.registry._tools):
            if k not in tools:
                del sub.registry._tools[k]
        sub.gate = ApprovalGate("full-auto", cfg.allow, cfg.deny)
    return sub.run(task)
