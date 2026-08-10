from __future__ import annotations
import json
import os
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    provider: str = "openrouter"
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    model: str = "openrouter/free"
    temperature: float = 0.3
    timeout: int = 120
    max_tokens: int = 2048
    retries: int = 2


@dataclass
class AgentConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    mode: str = "auto"
    allow: list = field(default_factory=list)
    deny: list = field(default_factory=list)
    workspace: str = os.path.expanduser("~/dev")
    sandbox_mode: str = "required"
    context_budget: int = 6000
    skills_dir: Optional[str] = None
    mcp_servers: list = field(default_factory=list)
    embeddings: Optional[dict] = None
    use_context: bool = True
    telegram: Optional[dict] = None
    http: Optional[dict] = None
    ide: Optional[dict] = None


def _read_file(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load(path=None):
    path = path or os.path.expanduser("~/.config/ideal-agent/config.json")
    data = _read_file(path)
    llm_data = data.get("llm", {})
    provider = (llm_data.get("provider") or LLMConfig.provider).lower()
    provider_env_keys = {
        "openrouter": ("OPENROUTER_API_KEY",),
        "openai": ("OPENAI_API_KEY",),
        "anthropic": ("ANTHROPIC_API_KEY",),
        "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "groq": ("GROQ_API_KEY",),
        "deepseek": ("DEEPSEEK_API_KEY",),
        "moonshot": ("MOONSHOT_API_KEY",),
        "together": ("TOGETHER_API_KEY",),
        "openai-compatible": ("TOKENROUTER_API_KEY",),
    }
    env_key = os.environ.get("IDEAL_LLM_API_KEY")
    if not env_key:
        env_key = next((os.environ[key] for key in provider_env_keys.get(provider, ())
                        if os.environ.get(key)), "")
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
