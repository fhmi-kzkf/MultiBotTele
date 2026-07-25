"""
Config Manager — Pydantic-validated configuration for the Multi-Agent system.

Handles loading, validation, and hot-reload of config.json.
Thread-safe writes via asyncio Lock.
"""

import os
import json
import asyncio
import hashlib
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

_config_lock = asyncio.Lock()
_current_config: Optional["AppConfig"] = None
_reload_callbacks: List = []


# ── Pydantic Models ─────────────────────────────────────────────────

class TimeRange(BaseModel):
    start: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    end: str = Field(default="23:00", pattern=r"^\d{2}:\d{2}$")


class BurstDelayRange(BaseModel):
    min: int = Field(default=20, ge=5, le=120)
    max: int = Field(default=40, ge=10, le=180)

    @field_validator("max")
    @classmethod
    def max_must_be_greater_than_min(cls, v, info):
        if "min" in info.data and v <= info.data["min"]:
            raise ValueError("max must be greater than min")
        return v


class GlobalSettings(BaseModel):
    kill_switch: bool = False
    active_hours: TimeRange = Field(default_factory=TimeRange)
    burst_delay_minutes: BurstDelayRange = Field(default_factory=BurstDelayRange)
    target_chat_id: Optional[int] = None


class LlmProviderConfig(BaseModel):
    name: str
    model: str


class LlmProviders(BaseModel):
    primary: LlmProviderConfig
    fallback: LlmProviderConfig


class TypingSpeedRange(BaseModel):
    min: int = Field(default=25, ge=10, le=100)
    max: int = Field(default=50, ge=15, le=120)


class AgentConfig(BaseModel):
    id: str
    name: str
    phone: str = ""
    session_string: str = ""
    is_active: bool = True
    persona_prompt: str = ""
    typing_speed_wpm: TypingSpeedRange = Field(default_factory=TypingSpeedRange)

    def persona_hash(self) -> str:
        """Generate a hash of the persona prompt for drift detection."""
        return hashlib.md5(self.persona_prompt.encode()).hexdigest()[:12]


class AppConfig(BaseModel):
    global_settings: GlobalSettings = Field(default_factory=GlobalSettings)
    llm_providers: LlmProviders
    agents: List[AgentConfig] = Field(default_factory=list)

    def get_agent_by_id(self, agent_id: str) -> Optional[AgentConfig]:
        """Find an agent by its ID."""
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        return None

    def get_active_agents(self) -> List[AgentConfig]:
        """Return only agents that are toggled active."""
        return [a for a in self.agents if a.is_active]


# ── Load / Save ─────────────────────────────────────────────────────

def load_config(path: Optional[str] = None) -> AppConfig:
    """Load and validate config.json. Returns an AppConfig instance."""
    global _current_config
    config_path = path or CONFIG_PATH

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    config = AppConfig(**raw)
    _current_config = config
    logger.info(f"Config loaded from {config_path} — {len(config.agents)} agents")
    return config


def get_config() -> AppConfig:
    """Get the currently loaded config. Loads from disk if not yet loaded."""
    global _current_config
    if _current_config is None:
        return load_config()
    return _current_config


async def save_config(config: AppConfig, path: Optional[str] = None) -> None:
    """Validate and save config to disk. Thread-safe."""
    global _current_config
    config_path = path or CONFIG_PATH

    async with _config_lock:
        data = config.model_dump()
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _current_config = config
        logger.info(f"Config saved to {config_path}")

    # Notify reload callbacks
    for cb in _reload_callbacks:
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(config)
            else:
                cb(config)
        except Exception as e:
            logger.error(f"Config reload callback error: {e}")


async def update_config_section(section: str, data: Dict[str, Any]) -> AppConfig:
    """
    Update a specific section of the config (e.g., 'global_settings', 'agents').
    Validates the full config after patching.
    """
    config = get_config()
    config_dict = config.model_dump()

    if section not in config_dict:
        raise ValueError(f"Unknown config section: {section}")

    config_dict[section] = data
    new_config = AppConfig(**config_dict)
    await save_config(new_config)
    return new_config


async def update_agent_config(agent_id: str, updates: Dict[str, Any]) -> AppConfig:
    """Update a specific agent's configuration fields."""
    config = get_config()
    config_dict = config.model_dump()

    for i, agent in enumerate(config_dict["agents"]):
        if agent["id"] == agent_id:
            agent.update(updates)
            config_dict["agents"][i] = agent
            break
    else:
        raise ValueError(f"Agent not found: {agent_id}")

    new_config = AppConfig(**config_dict)
    await save_config(new_config)
    return new_config


async def toggle_kill_switch(enabled: bool) -> AppConfig:
    """Toggle the global kill switch."""
    config = get_config()
    config_dict = config.model_dump()
    config_dict["global_settings"]["kill_switch"] = enabled
    new_config = AppConfig(**config_dict)
    await save_config(new_config)
    logger.warning(f"Kill switch {'ACTIVATED' if enabled else 'DEACTIVATED'}")
    return new_config


def register_reload_callback(callback) -> None:
    """Register a callback to be invoked when config is saved/reloaded."""
    _reload_callbacks.append(callback)
    logger.debug(f"Registered config reload callback: {callback.__name__}")
