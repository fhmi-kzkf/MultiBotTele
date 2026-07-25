"""
Database Layer — aiosqlite wrapper for the Multi-Agent Telegram Crowd Simulator.

Manages SQLite tables:
  - chat_history: Sliding window context storage
  - agent_sessions: Agent state tracking (locks, activity)
  - llm_metrics: LLM API usage monitoring
"""

import os
import asyncio
import aiosqlite
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "multibot.db")

_db_lock = asyncio.Lock()


# ── Schema DDL ──────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Stores the sliding window context for each group
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    sender_name TEXT,
    text_content TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_human BOOLEAN DEFAULT 1
);

-- Index for fast sliding window queries
CREATE INDEX IF NOT EXISTS idx_chat_history_chat_ts
    ON chat_history(chat_id, timestamp DESC);

-- Tracks agent states to manage locks and activity
CREATE TABLE IF NOT EXISTS agent_sessions (
    agent_id TEXT PRIMARY KEY,
    phone_number TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    is_typing BOOLEAN DEFAULT 0,
    last_message_timestamp DATETIME,
    current_persona_hash TEXT
);

-- Tracks LLM usage for failover and rate-limit monitoring
CREATE TABLE IF NOT EXISTS llm_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    tokens_used INTEGER,
    status_code INTEGER,
    is_rate_limited BOOLEAN DEFAULT 0
);

-- Index for metrics queries
CREATE INDEX IF NOT EXISTS idx_llm_metrics_ts
    ON llm_metrics(timestamp DESC);
"""


# ── Initialization ──────────────────────────────────────────────────

async def init_db() -> None:
    """Initialize the database: create data directory and all tables."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()
    logger.info(f"Database initialized at {DB_PATH}")


async def get_connection() -> aiosqlite.Connection:
    """Get a new database connection. Caller must close it."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


# ── Chat History CRUD ───────────────────────────────────────────────

async def insert_chat_message(
    chat_id: int,
    message_id: int,
    sender_id: int,
    sender_name: Optional[str],
    text_content: str,
    is_human: bool = True,
    timestamp: Optional[datetime] = None,
) -> int:
    """Insert a new message into chat_history. Returns the row ID."""
    ts = timestamp or datetime.utcnow()
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                """
                INSERT INTO chat_history
                    (chat_id, message_id, sender_id, sender_name, text_content, timestamp, is_human)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (chat_id, message_id, sender_id, sender_name, text_content, ts.isoformat(), int(is_human)),
            )
            await db.commit()
            return cursor.lastrowid


async def get_context_window(chat_id: int, limit: int = 15) -> List[Dict[str, Any]]:
    """
    Fetch the last `limit` messages for the given chat (sliding window).
    Returns oldest-first order for LLM context building.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, chat_id, message_id, sender_id, sender_name,
                   text_content, timestamp, is_human
            FROM chat_history
            WHERE chat_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        # Reverse to oldest-first for LLM context
        messages = [dict(row) for row in reversed(rows)]
        return messages


async def get_all_chat_history(chat_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch recent chat history for the monitor screen."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, chat_id, message_id, sender_id, sender_name,
                   text_content, timestamp, is_human
            FROM chat_history
            WHERE chat_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


# ── Agent Sessions CRUD ────────────────────────────────────────────

async def upsert_agent_session(
    agent_id: str,
    phone_number: str,
    is_active: bool = True,
    persona_hash: Optional[str] = None,
) -> None:
    """Insert or update an agent session record."""
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO agent_sessions (agent_id, phone_number, is_active, is_typing, current_persona_hash)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    phone_number = excluded.phone_number,
                    is_active = excluded.is_active,
                    current_persona_hash = excluded.current_persona_hash
                """,
                (agent_id, phone_number, int(is_active), persona_hash),
            )
            await db.commit()


async def update_agent_state(agent_id: str, **kwargs) -> None:
    """
    Update specific fields of an agent session.
    Supported kwargs: is_active, is_typing, last_message_timestamp, current_persona_hash
    """
    allowed_fields = {"is_active", "is_typing", "last_message_timestamp", "current_persona_hash"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
    if not updates:
        return

    set_clauses = []
    values = []
    for field, value in updates.items():
        set_clauses.append(f"{field} = ?")
        if isinstance(value, bool):
            values.append(int(value))
        elif isinstance(value, datetime):
            values.append(value.isoformat())
        else:
            values.append(value)

    values.append(agent_id)

    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                f"UPDATE agent_sessions SET {', '.join(set_clauses)} WHERE agent_id = ?",
                values,
            )
            await db.commit()


async def get_agent_sessions() -> List[Dict[str, Any]]:
    """Fetch all agent sessions."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM agent_sessions ORDER BY agent_id")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_agent_session(agent_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single agent session by ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM agent_sessions WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def set_all_agents_inactive() -> None:
    """Set all agents to inactive and not typing (for kill switch)."""
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE agent_sessions SET is_active = 0, is_typing = 0"
            )
            await db.commit()


async def set_all_agents_active() -> None:
    """Re-activate all agents (for restart after kill switch)."""
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE agent_sessions SET is_active = 1")
            await db.commit()


# ── LLM Metrics CRUD ───────────────────────────────────────────────

async def log_llm_metric(
    provider: str,
    status_code: Optional[int] = None,
    tokens_used: Optional[int] = None,
    is_rate_limited: bool = False,
) -> None:
    """Log an LLM API call for monitoring and failover tracking."""
    async with _db_lock:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO llm_metrics (provider, tokens_used, status_code, is_rate_limited)
                VALUES (?, ?, ?, ?)
                """,
                (provider, tokens_used, status_code, int(is_rate_limited)),
            )
            await db.commit()


async def get_llm_metrics(
    limit: int = 100,
    provider: Optional[str] = None,
    rate_limited_only: bool = False,
) -> List[Dict[str, Any]]:
    """Fetch LLM metrics with optional filters."""
    conditions = []
    params = []

    if provider:
        conditions.append("provider = ?")
        params.append(provider)
    if rate_limited_only:
        conditions.append("is_rate_limited = 1")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT * FROM llm_metrics {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_rate_limit_count_last_hour(provider: Optional[str] = None) -> int:
    """Count rate-limited requests in the last hour."""
    conditions = ["is_rate_limited = 1", "timestamp >= datetime('now', '-1 hour')"]
    params = []

    if provider:
        conditions.append("provider = ?")
        params.append(provider)

    where = f"WHERE {' AND '.join(conditions)}"

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM llm_metrics {where}",
            params,
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_token_usage_summary() -> List[Dict[str, Any]]:
    """Aggregate token usage grouped by provider."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT provider,
                   COUNT(*) as total_requests,
                   SUM(COALESCE(tokens_used, 0)) as total_tokens,
                   SUM(CASE WHEN is_rate_limited = 1 THEN 1 ELSE 0 END) as rate_limited_count
            FROM llm_metrics
            GROUP BY provider
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
