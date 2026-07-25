# App Flow and Screen Inventory: Multi-Agent Telegram Crowd Simulator

## 1. User Journey Map (Primary Flows)

### Flow 1: Initial Setup & Activation (Onboarding)
1. **Authentication**: Community Manager (CM) accesses the Streamlit URL and logs in via Basic Auth.
2. **Agent Configuration**: CM navigates to the *Agent & Persona* screen, inputs the phone numbers/API credentials for the 5 Userbots, and defines the System Prompt (persona) for each.
3. **Behavioral Tuning**: CM moves to the *Scheduling & Behavior* screen, sets the active/sleep hours using sliders, and configures the anti-ban jitter parameters (typing speed, burst delays).
4. **Activation**: CM returns to the *Dashboard*, verifies all 5 agents are toggled `ON`, and clicks "Start Simulation". The backend initializes the Telethon clients and APScheduler.

### Flow 2: Daily Monitoring & Context Adjustment
1. **Dashboard Review**: CM logs in and checks the *Dashboard* for real-time agent statuses (who is typing, who is sleeping).
2. **Live Monitoring**: CM opens the *Live Chat & Context* screen to observe the sliding window (last 15 messages) and ensure bots are responding naturally to human interruptions.
3. **Dynamic Adjustment**: If a bot's persona drifts, CM quickly edits the System Prompt in the *Agent & Persona* screen. The backend validates and hot-reloads the persona without restarting the Telegram session.

### Flow 3: Emergency Intervention (Kill Switch)
1. **Anomaly Detection**: CM notices abnormal behavior (e.g., bots spamming, Telegram rate-limit warnings on the *Metrics* screen).
2. **Emergency Halt**: CM immediately clicks the red "Emergency Kill Switch" button on the *Dashboard*.
3. **System Freeze**: The backend instantly pauses the APScheduler, clears the message queue, and sets all `AgentSession.isTyping` to `false` and `isActive` to `false`.

---

## 2. Screen Inventory

| Screen Name | Purpose | Target User |
| :--- | :--- | :--- |
| **1. Login / Auth** | Secure access to the Streamlit dashboard using Basic Auth (Username/Password). | Community Manager |
| **2. Command Dashboard** | High-level overview of the network. Displays active agents, real-time typing status, and the Emergency Kill Switch. | Community Manager |
| **3. Agent & Persona Manager** | Manage the 5 Userbot identities. Toggle agents on/off, update phone numbers, and edit System Prompts (personas). | Community Manager |
| **4. Scheduling & Behavior** | Configure organic scheduling. Set active/sleep hours, randomized burst delays, and typing speed (WPM) jitter via interactive sliders. | Community Manager |
| **5. Live Chat & Context Monitor** | View the real-time sliding window context (last 15 messages). Highlights human interventions and bot responses. | Community Manager |
| **6. System & LLM Metrics** | Monitor API health, token usage, and failover events. Displays rate-limit (HTTP 429) occurrences and provider switchovers. | Community Manager / Admin |

---

## 3. State & Data Requirements per Screen

### Screen 1: Login / Auth
* **Purpose**: Restrict access to authorized personnel.
* **State Requirements**:
  * Session State: `is_authenticated` (Boolean).
  * Data Source: Environment Variables (`ADMIN_USERNAME`, `ADMIN_PASSWORD`).
  * *Note: No database interaction required for this screen.*

### Screen 2: Command Dashboard
* **Purpose**: Central hub for system control and high-level status.
* **State & Data Requirements**:
  * **Agent Status Grid**: Fetches `AgentSession` model.
    * Displays: `agentId`, `phoneNumber`, `isActive`, `isTyping`, `lastMessageTimestamp`.
  * **Kill Switch Action**: 
    * Triggers backend endpoint to set `AgentSession.isActive = false` for all agents.
    * Clears APScheduler jobs.
  * **Global System State**: Reads `config.json` for `global_kill_switch` status.

### Screen 3: Agent & Persona Manager
* **Purpose**: Configure bot identities and manage the 5-agent registry.
* **State & Data Requirements**:
  * **Agent List**: Fetches `AgentSession` model.
    * Fields: `agentId`, `phoneNumber`, `isActive` (Toggle Switch).
  * **Persona Editor**: 
    * Input: `TextArea` for System Prompt.
    * State: Reads/Writes to `config.json` (Agent Personas).
    * Validation: Backend sanitizes input to prevent JSON injection/syntax errors before saving. Updates `AgentSession.currentPersonaHash` upon successful save.

### Screen 4: Scheduling & Behavior
* **Purpose**: Define organic behavior to prevent Telegram bans.
* **State & Data Requirements**:
  * **Time Sliders**: 
    * Inputs: Start Hour (0-23), End Hour (0-23).
    * State: Writes to `config.json` (`active_hours`).
  * **Jitter & Typing Controls**:
    * Inputs: Min/Max Burst Delay (minutes), Typing Speed WPM range.
    * State: Writes to `config.json` (`jitter_config`).
  * **Validation**: Ensures Start Hour != End Hour, and WPM values are within human limits (e.g., 20-90 WPM).

### Screen 5: Live Chat & Context Monitor
* **Purpose**: Observe the sliding window context and human interruptions.
* **State & Data Requirements**:
  * **Chat Feed**: Fetches `ChatHistory` model.
    * Query: `ORDER BY timestamp DESC LIMIT 15` (Sliding Window).
    * Fields: `senderName`, `textContent`, `timestamp`, `isHuman`.
    * UI Logic: Highlights messages where `isHuman == true` to show human interruptions.
  * **Typing Indicators**: Polls `AgentSession.isTyping` to show "Bot X is typing..." status in the UI.

### Screen 6: System & LLM Metrics
* **Purpose**: Monitor LLM API health, costs, and failover guard effectiveness.
* **State & Data Requirements**:
  * **Metrics Table/Chart**: Fetches `LlmMetric` model.
    * Fields: `provider`, `timestamp`, `tokensUsed`, `statusCode`, `isRateLimited`.
  * **Failover Alerts**: 
    * Filters `LlmMetric` where `isRateLimited == true` or `statusCode == 429`.
    * Displays a warning banner if the primary provider (e.g., Gemini) has failed over to the secondary (e.g., Groq) more than X times in the last hour.
  * **Token Usage Summary**: Aggregates `tokensUsed` grouped by `provider` to track Free Tier limits.