# Technical Requirements Document (TRD): Multi-Agent Telegram Crowd Simulator

## 1. Architecture Overview

The system is designed as an **Asynchronous Modular Monolith** deployed on a single-node Ubuntu VPS. It utilizes Python's `asyncio` event loop to handle concurrent Telegram MTProto connections, LLM API requests, and scheduling tasks without blocking.

### Core Architectural Components
1. **MTProto Client Layer:** Manages 5 concurrent Telethon/Pyrogram user sessions. Handles raw message ingestion, `send_typing` actions, and message dispatching.
2. **Orchestration & Queue Manager:** The central brain. Maintains a priority queue. 
   * *Standard Queue:* Scheduled scenario messages.
   * *Priority Queue:* Human interruptions (highest priority).
   * *State Locking:* Maintains an `is_typing` lock per agent to prevent race conditions and overlapping messages.
3. **Context & Persona Engine:** Manages the Sliding Window Context. Intercepts incoming messages, trims history to the last 10-15 messages, injects the specific agent's system prompt, and formats the payload for the LLM.
4. **LLM Router & Failover Guard:** An asynchronous HTTP client wrapper that routes requests to the primary LLM (e.g., Gemini). If a `429 Too Many Requests` or timeout occurs, it seamlessly retries against the fallback provider (e.g., Groq) without dropping the queue item.
5. **Scheduler & Jitter Engine:** Uses APScheduler to trigger organic bursts. Calculates dynamic delays based on text length and randomized `typing_speed_wpm` to simulate human behavior.
6. **Streamlit Dashboard & Local IPC:** The frontend UI for Community Managers. Communicates with the backend monolith via a local Inter-Process Communication (IPC) mechanism (e.g., a lightweight local FastAPI server on `localhost` or Unix Domain Sockets) to execute the Kill Switch, toggle agents, and update configurations safely.

### Message Flow (Human Interruption Scenario)
1. Human sends message in Telegram group.
2. MTProto Layer receives event -> Passes to Orchestration.
3. Orchestration checks `is_typing` locks. If clear, it selects the most contextually relevant agent (based on persona matching or round-robin).
4. Context Engine fetches the last 15 messages, appends the human's message, and adds the agent's persona prompt.
5. LLM Router generates a response.
6. Jitter Engine calculates typing delay -> MTProto Layer sends `typing` action -> waits -> sends message -> releases lock.

---

## 2. Technology Stack & Rationale

| Component | Technology | Rationale |
| :--- | :--- | :--- |
| **Language** | Python 3.10+ | Native `asyncio` support, rich ecosystem for Telegram and LLM integrations. |
| **Telegram Client** | Telethon (MTProto) | Mandatory for Userbot functionality. Bypasses standard Bot API to avoid the "BOT" tag, ensuring 100% organic illusion. |
| **Scheduler** | APScheduler | Robust async scheduling, supports cron-like and interval-based triggers with jitter capabilities. |
| **LLM Engine** | Gemini Flash / Groq (Llama3/Qwen) | High speed, low latency, and generous free tiers. Ideal for high-volume, low-cost conversational simulation. |
| **HTTP Client** | `httpx` (Async) | Required for asynchronous, non-blocking API calls to LLM providers with built-in timeout and retry mechanisms. |
| **Database** | SQLite | Zero-configuration, file-based relational DB. Perfect for single-node VPS to store chat history and session states without the overhead of PostgreSQL/MySQL. |
| **Frontend UI** | Streamlit | Rapid development of data-driven web apps. Excellent for non-technical users to interact with sliders, toggles, and text areas. |
| **Process Mgmt** | `systemd` | Ensures 24/7 uptime with automatic restart capabilities upon script crash or VPS reboot. |
| **IPC / Local API** | FastAPI (Localhost) | Provides a secure, local REST interface for the Streamlit UI to send commands (Kill Switch, Config Reload) to the main asyncio event loop. |

---

## 3. Data Model Overview

### 3.1. SQLite Schema (Local Persistence)
Used for storing sliding window context and agent states.

```sql
-- Stores the sliding window context for each group
CREATE TABLE chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    sender_name TEXT,
    text_content TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_human BOOLEAN DEFAULT TRUE
);

-- Tracks agent states to manage locks and activity
CREATE TABLE agent_sessions (
    agent_id TEXT PRIMARY KEY,
    phone_number TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_typing BOOLEAN DEFAULT FALSE,
    last_message_timestamp DATETIME,
    current_persona_hash TEXT
);

-- Tracks LLM usage for failover and rate-limit monitoring
CREATE TABLE llm_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    tokens_used INTEGER,
    status_code INTEGER,
    is_rate_limited BOOLEAN DEFAULT FALSE
);
```

### 3.2. Configuration Model (`config.json`)
Managed via the Streamlit UI. Must be strictly validated before writing.

```json
{
  "global_settings": {
    "kill_switch": false,
    "active_hours": {"start": "08:00", "end": "23:00"},
    "burst_delay_minutes": {"min": 20, "max": 40}
  },
  "llm_providers": {
    "primary": {"name": "gemini", "api_key": "encrypted_or_env_ref", "model": "gemini-1.5-flash"},
    "fallback": {"name": "groq", "api_key": "encrypted_or_env_ref", "model": "llama3-70b-8192"}
  },
  "agents": [
    {
      "id": "agent_1",
      "phone": "+1234567890",
      "session_string": "telethon_session_string...",
      "is_active": true,
      "persona_prompt": "You are a cynical Web3 developer...",
      "typing_speed_wpm": {"min": 30, "max": 50}
    }
  ]
}
```

---

## 4. API Design / Integration Points

### 4.1. External Integrations
* **Telegram MTProto API:** 
  * *Methods:* `client.send_message()`, `client.send_read_acknowledge()`, `client.action('typing')`.
  * *Events:* `NewMessage` event handler for intercepting human inputs.
* **LLM Provider APIs (REST):**
  * *Endpoint:* `POST /v1/chat/completions` (OpenAI compatible format for Groq/Gemini).
  * *Headers:* `Authorization: Bearer <API_KEY>`.
  * *Payload:* Strictly limited to `messages` array containing max 15 objects (System prompt + last 14 context messages).

### 4.2. Internal Module Interfaces (Monolith)
Since it's a monolith, modules communicate via async function calls, but strict interfaces are defined:

* **Queue Manager Interface:**
  * `acquire_lock(agent_id: str) -> bool`: Prevents concurrent typing.
  * `release_lock(agent_id: str)`: Frees the agent.
  * `enqueue_human_interrupt(chat_id: int, message: str)`: Pushes to the front of the priority queue.
* **Context Engine Interface:**
  * `get_context_window(chat_id: int, limit: int = 15) -> List[Dict]`: Fetches and formats the last N messages.
* **Config Manager Interface:**
  * `load_config() -> Dict`: Reads and validates `config.json`.
  * `update_config(patch: Dict) -> bool`: Validates input, writes to `config.json`, and emits a reload signal to the event loop.

### 4.3. Streamlit to Backend IPC (Local FastAPI)
To allow the Streamlit UI to control the running bot without restarting it:
* `POST /api/v1/kill-switch`: Toggles `global_settings.kill_switch`.
* `POST /api/v1/agent/{id}/toggle`: Toggles `is_active` for a specific agent.
* `POST /api/v1/config/reload`: Triggers a hot-reload of `config.json` in the main event loop.

---

## 5. Security & Performance Constraints

### 5.1. Security & Safety Constraints
* **Access Control:** Streamlit UI must be wrapped with `streamlit-authenticator` or a custom Basic Auth middleware. Credentials must be hashed and stored securely, not in plain text.
* **Data Protection:** 
  * `config.json` and the SQLite database must have strict OS-level