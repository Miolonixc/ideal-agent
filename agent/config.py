import json
import os
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    provider: str = "openai-compatible"
    base_url: str = "https://api.tokenrouter.com/v1"
    api_key: str = ""
    model: str = "moonshotai/kimi-k3-free"
    temperature: float = 0.3
    timeout: int = 120
    max_tokens: int = 2048


@dataclass
class AgentConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    mode: str = "auto"
    allow: list = field(default_factory=list)
    deny: list = field(default_factory=list)
    workspace: str = os.path.expanduser("~/dev")
    context_budget: int = 6000
    skills_dir: Optional[str] = None
    mcp_servers: list = field(default_factory=list)
    embeddings: Optional[dict] = None
    use_context: bool = True
    telegram: Optional[dict] = None


def _read_file(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load(path=None):
    path = path or os.path.expanduser("~/.config/ideal-agent/config.json")
    data = _read_file(path)
    llm_data = data.get("llm", {})
    env_key = os.environ.get("IDEAL_LLM_API_KEY") or os.environ.get("TOKENROUTER_API_KEY")
    if not llm_data.get("api_key"):
        if env_key:
            llm_data["api_key"] = env_key
    known_llm = {f for f in LLMConfig.__dataclass_fields__}
    llm = LLMConfig(**{k: v for k, v in llm_data.items() if k in known_llm})
    known_agent = {f for f in AgentConfig.__dataclass_fields__ if f != "llm"}
    agent_data = {k: v for k, v in data.items() if k in known_agent}
    cfg = AgentConfig(**agent_data)
    cfg.llm = llm
    if cfg.skills_dir:
        cfg.skills_dir = os.path.expanduser(cfg.skills_dir)
    return cfg
