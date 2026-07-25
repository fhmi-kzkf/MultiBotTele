"""
FastAPI IPC Server — Local REST API for Streamlit ↔ Backend communication.

Runs on localhost only (port 8100). Provides endpoints for:
  - Kill switch control
  - Agent toggling
  - Config management
  - Status monitoring
  - Chat history & metrics retrieval
"""

import asyncio
import logging
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import database as db
from core.config_manager import (
    get_config,
    save_config,
    load_config,
    toggle_kill_switch,
    update_agent_config,
    update_config_section,
    AppConfig,
)

logger = logging.getLogger(__name__)

# ── FastAPI App ─────────────────────────────────────────────────────

app = FastAPI(
    title="MultiBotTele IPC",
    description="Internal API for Streamlit dashboard ↔ Backend communication",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Localhost only, CORS relaxed
    allow_methods=["*"],
    allow_headers=["*"],
)

# References to orchestrator and scheduler (set by main.py on startup)
_orchestrator = None
_scheduler = None


def set_orchestrator(orchestrator) -> None:
    """Set the orchestrator reference for API endpoints."""
    global _orchestrator
    _orchestrator = orchestrator


def set_scheduler(scheduler) -> None:
    """Set the scheduler reference for API endpoints."""
    global _scheduler
    _scheduler = scheduler


# ── Request Models ──────────────────────────────────────────────────

class KillSwitchRequest(BaseModel):
    enabled: bool


class AgentToggleRequest(BaseModel):
    is_active: bool


class AgentPersonaRequest(BaseModel):
    persona_prompt: str


class GlobalSettingsRequest(BaseModel):
    active_hours_start: Optional[str] = None
    active_hours_end: Optional[str] = None
    burst_delay_min: Optional[int] = None
    burst_delay_max: Optional[int] = None
    target_chat_id: Optional[int] = None


class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    session_string: Optional[str] = None
    is_active: Optional[bool] = None
    persona_prompt: Optional[str] = None
    typing_speed_min: Optional[int] = None
    typing_speed_max: Optional[int] = None


# ── Endpoints: Kill Switch ──────────────────────────────────────────

@app.post("/api/v1/kill-switch")
async def handle_kill_switch(request: KillSwitchRequest):
    """Toggle the global emergency kill switch."""
    try:
        config = await toggle_kill_switch(request.enabled)

        if request.enabled:
            # Activate kill switch: stop scheduler, deactivate agents
            if _orchestrator:
                await _orchestrator.activate_kill_switch()
            if _scheduler:
                await _scheduler.stop()
            logger.warning("🚨 Kill switch ACTIVATED via API")
        else:
            # Deactivate: restart operations
            if _orchestrator:
                await _orchestrator.deactivate_kill_switch()
            if _scheduler:
                await _scheduler.start(config)
            logger.info("Kill switch DEACTIVATED via API")

        return {
            "success": True,
            "kill_switch": request.enabled,
            "message": "Kill switch " + ("activated" if request.enabled else "deactivated"),
        }
    except Exception as e:
        logger.error(f"Kill switch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints: Agent Control ────────────────────────────────────────

@app.post("/api/v1/agent/{agent_id}/toggle")
async def toggle_agent(agent_id: str, request: AgentToggleRequest):
    """Toggle a specific agent on or off."""
    try:
        config = await update_agent_config(agent_id, {"is_active": request.is_active})
        await db.update_agent_state(agent_id, is_active=request.is_active)

        return {
            "success": True,
            "agent_id": agent_id,
            "is_active": request.is_active,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v1/agent/{agent_id}")
async def update_agent(agent_id: str, request: AgentUpdateRequest):
    """Update an agent's configuration."""
    try:
        updates = {k: v for k, v in request.model_dump().items() if v is not None}

        # Handle typing speed separately
        if "typing_speed_min" in updates or "typing_speed_max" in updates:
            config = get_config()
            agent = config.get_agent_by_id(agent_id)
            if agent:
                ts = agent.typing_speed_wpm.model_dump()
                if "typing_speed_min" in updates:
                    ts["min"] = updates.pop("typing_speed_min")
                if "typing_speed_max" in updates:
                    ts["max"] = updates.pop("typing_speed_max")
                updates["typing_speed_wpm"] = ts

        if updates:
            config = await update_agent_config(agent_id, updates)

        return {"success": True, "agent_id": agent_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v1/agent/{agent_id}/persona")
async def update_agent_persona(agent_id: str, request: AgentPersonaRequest):
    """Update an agent's persona/system prompt."""
    try:
        config = await update_agent_config(
            agent_id, {"persona_prompt": request.persona_prompt}
        )

        # Update persona hash in DB
        agent = config.get_agent_by_id(agent_id)
        if agent:
            await db.update_agent_state(
                agent_id, current_persona_hash=agent.persona_hash()
            )

        return {
            "success": True,
            "agent_id": agent_id,
            "persona_hash": agent.persona_hash() if agent else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints: Config ──────────────────────────────────────────────

@app.get("/api/v1/config")
async def get_current_config():
    """Get the current configuration."""
    try:
        config = get_config()
        return config.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v1/config/global")
async def update_global_settings(request: GlobalSettingsRequest):
    """Update global settings (active hours, burst delay, etc.)."""
    try:
        config = get_config()
        settings = config.global_settings.model_dump()

        if request.active_hours_start:
            settings["active_hours"]["start"] = request.active_hours_start
        if request.active_hours_end:
            settings["active_hours"]["end"] = request.active_hours_end
        if request.burst_delay_min is not None:
            settings["burst_delay_minutes"]["min"] = request.burst_delay_min
        if request.burst_delay_max is not None:
            settings["burst_delay_minutes"]["max"] = request.burst_delay_max
        if request.target_chat_id is not None:
            settings["target_chat_id"] = request.target_chat_id

        new_config = await update_config_section("global_settings", settings)

        # Reschedule if burst delay changed
        if _scheduler and (request.burst_delay_min or request.burst_delay_max):
            await _scheduler.reschedule(new_config)

        return {"success": True, "global_settings": new_config.global_settings.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/config/reload")
async def reload_config():
    """Trigger a hot-reload of config.json."""
    try:
        config = load_config()
        if _scheduler:
            await _scheduler.reschedule(config)
        return {"success": True, "message": "Config reloaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints: Status & Monitoring ──────────────────────────────────

@app.get("/api/v1/status")
async def get_system_status():
    """Get comprehensive system status."""
    try:
        config = get_config()
        agent_sessions = await db.get_agent_sessions()

        status = {
            "kill_switch": config.global_settings.kill_switch,
            "active_hours": config.global_settings.active_hours.model_dump(),
            "agents": agent_sessions,
            "orchestrator": _orchestrator.get_status() if _orchestrator else None,
            "scheduler": _scheduler.get_status() if _scheduler else None,
        }
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/chat-history/{chat_id}")
async def get_chat_history(chat_id: int, limit: int = 50):
    """Get chat history for a specific chat (for the monitor screen)."""
    try:
        messages = await db.get_all_chat_history(chat_id, limit=limit)
        return {"chat_id": chat_id, "messages": messages, "count": len(messages)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/context-window/{chat_id}")
async def get_context_window(chat_id: int, limit: int = 15):
    """Get the current sliding window context."""
    try:
        context = await db.get_context_window(chat_id, limit=limit)
        return {"chat_id": chat_id, "context": context, "count": len(context)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/metrics")
async def get_metrics(
    limit: int = 100,
    provider: Optional[str] = None,
    rate_limited_only: bool = False,
):
    """Get LLM metrics with optional filters."""
    try:
        metrics = await db.get_llm_metrics(
            limit=limit, provider=provider, rate_limited_only=rate_limited_only
        )
        token_summary = await db.get_token_usage_summary()
        rate_limit_count = await db.get_rate_limit_count_last_hour(provider)

        return {
            "metrics": metrics,
            "token_summary": token_summary,
            "rate_limit_last_hour": rate_limit_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "service": "MultiBotTele IPC"}
