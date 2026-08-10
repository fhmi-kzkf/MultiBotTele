"""
Streamlit Dashboard — Multi-page Web UI for Community Managers.

6 Screens:
  1. Login / Auth
  2. Command Dashboard
  3. Agent & Persona Manager
  4. Scheduling & Behavior
  5. Live Chat & Context Monitor
  6. System & LLM Metrics
"""

import os
import time
import json
import streamlit as st
import httpx
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ───────────────────────────────────────────────────

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8100")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# ── Page Config ─────────────────────────────────────────────────────

st.set_page_config(
    page_title="MultiBotTele — Command Center",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────────────────

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&display=swap');

    /* Global Cosmos Dark System */
    .stApp {
        font-family: 'Geist', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        background-color: #000000;
        color: #ffffff;
        letter-spacing: 0.025em;
    }

    /* Main header styling */
    .main-header {
        background: #181818;
        border: 1px solid #333333;
        padding: 2rem 2.5rem;
        border-radius: 20px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
    }
    .main-header h1 {
        color: #ffffff;
        font-size: 2rem;
        font-weight: 400;
        margin: 0;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .main-header p {
        color: #807f7f;
        font-size: 0.95rem;
        margin: 0.5rem 0 0 0;
        letter-spacing: 0.02em;
    }

    /* Status & Metric cards */
    .status-card, .metric-card {
        background: #1e1f20;
        border: 1px solid #333333;
        border-radius: 20px;
        padding: 1.5rem;
        margin-bottom: 1.25rem;
        text-align: left;
        transition: border-color 0.2s ease, transform 0.2s ease;
    }
    .status-card:hover, .metric-card:hover {
        border-color: #666666;
        transform: translateY(-2px);
    }
    .metric-card h3 {
        color: #807f7f;
        font-size: 0.75rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        margin: 0;
    }
    .metric-card .value {
        color: #ffffff;
        font-size: 2.2rem;
        font-weight: 400;
        letter-spacing: 0.03em;
        margin: 0.5rem 0 0 0;
    }

    /* Agent card */
    .agent-card {
        background: #1e1f20;
        border: 1px solid #333333;
        border-radius: 20px;
        padding: 1.5rem;
        margin-bottom: 1.25rem;
        transition: all 0.2s ease;
    }
    .agent-card.active {
        border-color: #22e2a8;
        box-shadow: 0 0 20px rgba(34, 226, 168, 0.08);
    }
    .agent-card.inactive {
        border-color: #333333;
        opacity: 0.6;
    }

    /* Ghost Pill Button */
    .stButton > button {
        background: transparent !important;
        color: #ffffff !important;
        border: 1px solid #ffffff !important;
        border-radius: 20px !important;
        padding: 0.5rem 1.5rem !important;
        font-family: 'Geist', 'Inter', sans-serif !important;
        font-size: 0.9rem !important;
        font-weight: 400 !important;
        letter-spacing: 0.025em !important;
        transition: all 0.2s ease !important;
    }
    .stButton > button:hover {
        background: #ffffff !important;
        color: #000000 !important;
        border-color: #ffffff !important;
        box-shadow: 0 0 15px rgba(255, 255, 255, 0.2) !important;
    }

    /* Chat bubble */
    .chat-bubble {
        padding: 1rem 1.25rem;
        border-radius: 16px;
        margin-bottom: 0.75rem;
        max-width: 85%;
        font-size: 0.95rem;
        line-height: 1.6;
        letter-spacing: 0.02em;
    }
    .chat-bubble.human {
        background: #181818;
        border: 1px solid #22e2a8;
        color: #ffffff;
        margin-left: auto;
        border-bottom-right-radius: 4px;
    }
    .chat-bubble.bot {
        background: #1e1f20;
        border: 1px solid #333333;
        color: #f1f4f4;
        border-bottom-left-radius: 4px;
    }
    .chat-sender {
        font-size: 0.75rem;
        font-weight: 500;
        margin-bottom: 0.3rem;
        color: #22e2a8;
        letter-spacing: 0.03em;
        text-transform: uppercase;
    }
    .chat-time {
        font-size: 0.7rem;
        color: #807f7f;
        margin-top: 0.4rem;
    }

    /* Status indicators */
    .status-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 8px;
    }
    .status-dot.active { background: #22e2a8; box-shadow: 0 0 10px #22e2a8; }
    .status-dot.typing { background: #fbbf24; animation: pulse 0.8s infinite; }
    .status-dot.inactive { background: #807f7f; }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
    }

    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #181818 !important;
        border-right: 1px solid #333333;
    }
    .sidebar-logo {
        text-align: left;
        padding: 1.5rem 1rem 1rem 1rem;
        margin-bottom: 1.5rem;
        border-bottom: 1px solid #333333;
    }
    .sidebar-logo h2 {
        color: #ffffff;
        font-size: 1.2rem;
        font-weight: 400;
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }

    /* Warning banner */
    .warning-banner {
        background: #181818;
        color: #ef4444;
        border: 1px solid #ef4444;
        padding: 1rem 1.5rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
        font-weight: 500;
        text-align: center;
        letter-spacing: 0.02em;
    }
</style>
""", unsafe_allow_html=True)


# ── API Helper ──────────────────────────────────────────────────────

def api_call(method: str, endpoint: str, **kwargs):
    """Make a synchronous API call to the backend."""
    try:
        url = f"{API_BASE}{endpoint}"
        with httpx.Client(timeout=10.0) as client:
            if method == "GET":
                resp = client.get(url, params=kwargs.get("params"))
            elif method == "POST":
                resp = client.post(url, json=kwargs.get("json"))
            elif method == "PUT":
                resp = client.put(url, json=kwargs.get("json"))
            else:
                return None

            if resp.status_code == 200:
                return resp.json()
            else:
                st.error(f"API Error {resp.status_code}: {resp.text}")
                return None
    except httpx.ConnectError:
        st.warning("⚠️ Backend tidak terhubung. Pastikan `main.py` sudah berjalan.")
        return None
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


def load_config_file():
    """Load config.json directly (fallback when API is down)."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_config_file(data):
    """Save config.json directly (fallback when API is down)."""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        st.error(f"Error saving config: {e}")
        return False


# ── Authentication ──────────────────────────────────────────────────

def check_auth():
    """Check if user is authenticated."""
    return st.session_state.get("is_authenticated", False)


def login_page():
    """Render the login page."""
    st.markdown("""
    <div style="display: flex; justify-content: center; align-items: center; min-height: 60vh;">
        <div style="text-align: center;">
            <h1 style="font-size: 3rem; font-weight: 800; background: linear-gradient(135deg, #8b5cf6, #06b6d4);
                        -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                🤖 MultiBotTele
            </h1>
            <p style="color: rgba(255,255,255,0.5); font-size: 1.1rem; margin-bottom: 2rem;">
                Multi-Agent Telegram Crowd Simulator
            </p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("### 🔐 Login")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")

        if st.button("Login", use_container_width=True, type="primary"):
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                st.session_state["is_authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Username atau password salah!")


# ── Screen 1: Command Dashboard ────────────────────────────────────

def dashboard_screen():
    """Main command dashboard with agent status and kill switch."""
    st.markdown("""
    <div class="main-header">
        <h1>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2" style="vertical-align: sub; margin-right: 8px;"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>
            Command Dashboard
        </h1>
        <p>Monitor dan kontrol seluruh jaringan agent dalam satu tampilan</p>
    </div>
    """, unsafe_allow_html=True)

    # Try to get live status from API
    status = api_call("GET", "/api/v1/status")
    config = api_call("GET", "/api/v1/config") or load_config_file()

    if not config:
        st.error("Tidak dapat memuat konfigurasi. Periksa file config.json.")
        return

    kill_switch_active = config.get("global_settings", {}).get("kill_switch", False)

    # ── Kill Switch Banner ──
    if kill_switch_active:
        st.markdown("""
        <div class="warning-banner">
            🚨 KILL SWITCH AKTIF — Semua aktivitas bot dihentikan!
        </div>
        """, unsafe_allow_html=True)

    # ── Top Metrics Row ──
    agents = config.get("agents", [])
    active_count = sum(1 for a in agents if a.get("is_active", False))
    typing_agents = []
    if status and status.get("agents"):
        typing_agents = [a for a in status["agents"] if a.get("is_typing")]

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Total Agents</h3>
            <div class="value">{len(agents)}</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Active</h3>
            <div class="value" style="color: #34d399;">{active_count}</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Typing Now</h3>
            <div class="value" style="color: #fbbf24;">{len(typing_agents)}</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <h3>Kill Switch</h3>
            <div class="value" style="color: {'#ef4444' if kill_switch_active else '#34d399'};">
                {'🔴 ON' if kill_switch_active else '🟢 OFF'}
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Kill Switch Control ──
    col_left, col_right = st.columns([3, 1])
    with col_right:
        if kill_switch_active:
            if st.button("✅ Nonaktifkan Kill Switch", use_container_width=True, type="primary"):
                result = api_call("POST", "/api/v1/kill-switch", json={"enabled": False})
                if result is None:
                    # Fallback: update config directly
                    config["global_settings"]["kill_switch"] = False
                    save_config_file(config)
                st.rerun()
        else:
            if st.button("🚨 EMERGENCY KILL SWITCH", use_container_width=True, type="secondary"):
                result = api_call("POST", "/api/v1/kill-switch", json={"enabled": True})
                if result is None:
                    config["global_settings"]["kill_switch"] = True
                    save_config_file(config)
                st.rerun()

    # ── Agent Status Grid ──
    st.markdown("### 👥 Agent Network Status")
    cols = st.columns(min(len(agents), 3) if agents else 1)

    for i, agent in enumerate(agents):
        agent_id = agent.get("id", f"agent_{i+1}")
        agent_name = agent.get("name", agent_id)
        is_active = agent.get("is_active", False)
        phone = agent.get("phone", "N/A")

        # Check typing status from live data
        is_typing = False
        last_msg = "N/A"
        if status and status.get("agents"):
            for sess in status["agents"]:
                if sess.get("agent_id") == agent_id:
                    is_typing = sess.get("is_typing", False)
                    last_msg = sess.get("last_message_timestamp", "N/A")
                    break

        status_class = "active" if is_active else "inactive"
        status_dot = "typing" if is_typing else ("active" if is_active else "inactive")
        status_text = "Mengetik..." if is_typing else ("Aktif" if is_active else "Nonaktif")

        with cols[i % len(cols)]:
            st.markdown(f"""
            <div class="agent-card {status_class}">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <h3 style="color: #fff; margin: 0; font-size: 1.2rem;">{agent_name}</h3>
                        <p style="color: rgba(255,255,255,0.5); margin: 0.2rem 0; font-size: 0.8rem;">
                            {agent_id} • {phone if phone else 'No phone'}
                        </p>
                    </div>
                    <div>
                        <span class="status-dot {status_dot}"></span>
                        <span style="color: rgba(255,255,255,0.7); font-size: 0.85rem;">{status_text}</span>
                    </div>
                </div>
                <p style="color: rgba(255,255,255,0.4); font-size: 0.75rem; margin: 0.5rem 0 0 0;">
                    Last message: {last_msg}
                </p>
            </div>
            """, unsafe_allow_html=True)

    # ── System Info ──
    st.markdown("### ⚙️ System Info")
    info_cols = st.columns(2)
    with info_cols[0]:
        active_hours = config.get("global_settings", {}).get("active_hours", {})
        st.info(f"🕐 Jam Aktif: {active_hours.get('start', 'N/A')} - {active_hours.get('end', 'N/A')}")
    with info_cols[1]:
        burst = config.get("global_settings", {}).get("burst_delay_minutes", {})
        st.info(f"⏱️ Burst Delay: {burst.get('min', 'N/A')} - {burst.get('max', 'N/A')} menit")


# ── Screen 2: Agent & Persona Manager ──────────────────────────────

def agent_persona_screen():
    """Manage agent identities and persona prompts."""
    st.markdown("""
    <div class="main-header">
        <h1>👤 Agent & Persona Manager</h1>
        <p>Kelola identitas dan kepribadian masing-masing agent</p>
    </div>
    """, unsafe_allow_html=True)

    config = api_call("GET", "/api/v1/config") or load_config_file()
    if not config:
        st.error("Tidak dapat memuat konfigurasi.")
        return

    agents = config.get("agents", [])

    for i, agent in enumerate(agents):
        agent_id = agent.get("id", f"agent_{i+1}")
        agent_name = agent.get("name", agent_id)
        is_active = agent.get("is_active", False)

        with st.expander(
            f"{'🟢' if is_active else '🔴'} {agent_name} ({agent_id})",
            expanded=(i == 0),
        ):
            col1, col2 = st.columns([2, 1])

            with col1:
                new_name = st.text_input(
                    "Nama Agent", value=agent_name, key=f"name_{agent_id}"
                )
                new_phone = st.text_input(
                    "Nomor Telepon", value=agent.get("phone", ""),
                    key=f"phone_{agent_id}",
                    help="Format internasional: +628xxxx"
                )
                new_session = st.text_input(
                    "Session String", value=agent.get("session_string", ""),
                    key=f"session_{agent_id}",
                    type="password",
                    help="Telethon session string (opsional jika login via phone)"
                )

            with col2:
                new_active = st.toggle(
                    "Agent Aktif",
                    value=is_active,
                    key=f"active_{agent_id}",
                )

                ts = agent.get("typing_speed_wpm", {"min": 25, "max": 50})
                new_ts_min = st.number_input(
                    "WPM Min", value=ts.get("min", 25),
                    min_value=10, max_value=100,
                    key=f"wpm_min_{agent_id}",
                )
                new_ts_max = st.number_input(
                    "WPM Max", value=ts.get("max", 50),
                    min_value=15, max_value=120,
                    key=f"wpm_max_{agent_id}",
                )

            # Persona editor
            st.markdown("**📝 System Prompt (Persona)**")
            new_persona = st.text_area(
                "Persona Prompt",
                value=agent.get("persona_prompt", ""),
                height=150,
                key=f"persona_{agent_id}",
                label_visibility="collapsed",
            )

            # Save button
            if st.button(f"💾 Simpan {agent_name}", key=f"save_{agent_id}", type="primary"):
                updates = {
                    "name": new_name,
                    "phone": new_phone,
                    "session_string": new_session,
                    "is_active": new_active,
                    "persona_prompt": new_persona,
                    "typing_speed_min": new_ts_min,
                    "typing_speed_max": new_ts_max,
                }

                result = api_call("PUT", f"/api/v1/agent/{agent_id}", json=updates)
                if result is None:
                    # Fallback: update config directly
                    config_data = load_config_file()
                    if config_data:
                        for ag in config_data.get("agents", []):
                            if ag["id"] == agent_id:
                                ag["name"] = new_name
                                ag["phone"] = new_phone
                                ag["session_string"] = new_session
                                ag["is_active"] = new_active
                                ag["persona_prompt"] = new_persona
                                ag["typing_speed_wpm"] = {"min": new_ts_min, "max": new_ts_max}
                                break
                        if save_config_file(config_data):
                            st.success(f"✅ {agent_name} berhasil disimpan!")
                else:
                    st.success(f"✅ {agent_name} berhasil disimpan!")


# ── Screen 3: Scheduling & Behavior ────────────────────────────────

def scheduling_screen():
    """Configure organic scheduling and anti-ban behavior."""
    st.markdown("""
    <div class="main-header">
        <h1>⏰ Scheduling & Behavior</h1>
        <p>Atur jadwal organik dan parameter anti-ban untuk simulasi natural</p>
    </div>
    """, unsafe_allow_html=True)

    config = api_call("GET", "/api/v1/config") or load_config_file()
    if not config:
        st.error("Tidak dapat memuat konfigurasi.")
        return

    global_settings = config.get("global_settings", {})
    active_hours = global_settings.get("active_hours", {"start": "08:00", "end": "23:00"})
    burst_delay = global_settings.get("burst_delay_minutes", {"min": 20, "max": 40})

    # ── Active Hours ──
    st.markdown("### 🕐 Jam Aktif")
    st.caption("Bot hanya akan aktif pada rentang jam ini. Di luar jam ini, bot akan 'tidur'.")

    col1, col2 = st.columns(2)
    with col1:
        start_hour = st.slider(
            "Jam Mulai",
            min_value=0, max_value=23,
            value=int(active_hours.get("start", "08:00").split(":")[0]),
            format="%d:00",
            key="active_start",
        )
    with col2:
        end_hour = st.slider(
            "Jam Selesai",
            min_value=0, max_value=23,
            value=int(active_hours.get("end", "23:00").split(":")[0]),
            format="%d:00",
            key="active_end",
        )

    if start_hour == end_hour:
        st.warning("⚠️ Jam mulai dan selesai tidak boleh sama!")

    st.markdown("---")

    # ── Burst Delay ──
    st.markdown("### 💬 Burst Delay (Jeda Percakapan)")
    st.caption(
        "Rentang waktu acak antara setiap 'burst' percakapan. "
        "Semakin bervariasi = semakin natural."
    )

    burst_col1, burst_col2 = st.columns(2)
    with burst_col1:
        burst_min = st.slider(
            "Minimum (menit)",
            min_value=5, max_value=120,
            value=burst_delay.get("min", 20),
            key="burst_min",
        )
    with burst_col2:
        burst_max = st.slider(
            "Maximum (menit)",
            min_value=10, max_value=180,
            value=burst_delay.get("max", 40),
            key="burst_max",
        )

    if burst_max <= burst_min:
        st.warning("⚠️ Maximum harus lebih besar dari minimum!")

    st.markdown("---")

    # ── Typing Speed Info ──
    st.markdown("### ⌨️ Kecepatan Mengetik (per Agent)")
    st.caption(
        "Kecepatan mengetik diatur per-agent di halaman Agent & Persona Manager. "
        "Berikut ringkasan pengaturan saat ini:"
    )

    agents = config.get("agents", [])
    for agent in agents:
        ts = agent.get("typing_speed_wpm", {"min": 25, "max": 50})
        st.markdown(
            f"- **{agent.get('name', agent.get('id'))}**: "
            f"{ts.get('min', 25)} - {ts.get('max', 50)} WPM"
        )

    st.markdown("---")

    # ── Target Chat ID ──
    st.markdown("### 🎯 Target Group Chat")
    target_chat = st.number_input(
        "Chat ID (format negatif untuk grup, misal: -1001234567890)",
        value=global_settings.get("target_chat_id") or 0,
        step=1,
        key="target_chat_id",
        help="ID grup Telegram yang akan diramaikan. Gunakan @userinfobot untuk mendapatkan ID.",
    )

    st.markdown("---")

    # ── Save Button ──
    if st.button("💾 Simpan Pengaturan", type="primary", use_container_width=True):
        if start_hour == end_hour:
            st.error("Jam mulai dan selesai tidak boleh sama!")
            return
        if burst_max <= burst_min:
            st.error("Maximum burst delay harus lebih besar dari minimum!")
            return

        settings = {
            "active_hours_start": f"{start_hour:02d}:00",
            "active_hours_end": f"{end_hour:02d}:00",
            "burst_delay_min": burst_min,
            "burst_delay_max": burst_max,
            "target_chat_id": target_chat if target_chat != 0 else None,
        }

        result = api_call("PUT", "/api/v1/config/global", json=settings)
        if result is None:
            # Fallback: update config directly
            config_data = load_config_file()
            if config_data:
                config_data["global_settings"]["active_hours"] = {
                    "start": f"{start_hour:02d}:00",
                    "end": f"{end_hour:02d}:00",
                }
                config_data["global_settings"]["burst_delay_minutes"] = {
                    "min": burst_min,
                    "max": burst_max,
                }
                config_data["global_settings"]["target_chat_id"] = target_chat if target_chat != 0 else None
                if save_config_file(config_data):
                    st.success("✅ Pengaturan berhasil disimpan!")
        else:
            st.success("✅ Pengaturan berhasil disimpan dan scheduler di-reload!")


# ── Screen 4: Live Chat Monitor ────────────────────────────────────

def chat_monitor_screen():
    """Live view of the sliding window context."""
    st.markdown("""
    <div class="main-header">
        <h1>💬 Live Chat & Context Monitor</h1>
        <p>Lihat percakapan real-time dan sliding window context</p>
    </div>
    """, unsafe_allow_html=True)

    config = api_call("GET", "/api/v1/config") or load_config_file()
    target_chat_id = config.get("global_settings", {}).get("target_chat_id") if config else None

    if not target_chat_id:
        st.warning("⚠️ Target Chat ID belum diatur. Atur di halaman Scheduling & Behavior.")
        return

    # Auto-refresh toggle
    col1, col2 = st.columns([3, 1])
    with col2:
        auto_refresh = st.toggle("Auto Refresh (5s)", value=False, key="auto_refresh_chat")

    # Fetch chat history
    chat_data = api_call("GET", f"/api/v1/chat-history/{target_chat_id}", params={"limit": 30})

    if not chat_data or not chat_data.get("messages"):
        st.info("📭 Belum ada pesan di chat ini. Pesan akan muncul saat bot mulai aktif.")

        # Show typing indicators
        status = api_call("GET", "/api/v1/status")
        if status and status.get("agents"):
            typing_agents = [a for a in status["agents"] if a.get("is_typing")]
            if typing_agents:
                for agent in typing_agents:
                    st.markdown(f"⌨️ **{agent.get('agent_id', 'Unknown')}** sedang mengetik...")
        return

    messages = chat_data.get("messages", [])

    # Sliding window indicator
    context_data = api_call("GET", f"/api/v1/context-window/{target_chat_id}")
    if context_data:
        st.caption(f"📊 Sliding Window: {context_data.get('count', 0)}/15 pesan dalam konteks LLM")

    # Chat feed
    st.markdown("### 📨 Chat Feed")

    for msg in reversed(messages):  # Show newest at bottom
        sender = msg.get("sender_name", "Unknown")
        text = msg.get("text_content", "")
        timestamp = msg.get("timestamp", "")
        is_human = msg.get("is_human", True)

        bubble_class = "human" if is_human else "bot"
        role_label = "👤 Human" if is_human else "🤖 Bot"

        st.markdown(f"""
        <div class="chat-bubble {bubble_class}">
            <div class="chat-sender">{role_label} • {sender}</div>
            {text}
            <div class="chat-time">{timestamp}</div>
        </div>
        """, unsafe_allow_html=True)

    # Typing indicators
    status = api_call("GET", "/api/v1/status")
    if status and status.get("agents"):
        typing_agents = [a for a in status["agents"] if a.get("is_typing")]
        if typing_agents:
            st.markdown("---")
            for agent in typing_agents:
                st.markdown(f"⌨️ **{agent.get('agent_id', 'Unknown')}** sedang mengetik...")

    # Auto-refresh
    if auto_refresh:
        time.sleep(5)
        st.rerun()


# ── Screen 5: System & LLM Metrics ─────────────────────────────────

def metrics_screen():
    """Monitor LLM API health, token usage, and failover events."""
    st.markdown("""
    <div class="main-header">
        <h1>📊 System & LLM Metrics</h1>
        <p>Monitor kesehatan API, penggunaan token, dan event failover</p>
    </div>
    """, unsafe_allow_html=True)

    metrics_data = api_call("GET", "/api/v1/metrics")

    if not metrics_data:
        st.info("📭 Belum ada data metrik. Data akan muncul setelah bot melakukan panggilan API LLM.")

        # Show LLM router status
        st.markdown("### 🔧 LLM Provider Status")
        config = api_call("GET", "/api/v1/config") or load_config_file()
        if config:
            providers = config.get("llm_providers", {})
            col1, col2 = st.columns(2)
            with col1:
                primary = providers.get("primary", {})
                st.markdown(f"""
                <div class="status-card">
                    <h4 style="color: #34d399;">🟢 Primary: {primary.get('name', 'N/A')}</h4>
                    <p style="color: rgba(255,255,255,0.6);">Model: {primary.get('model', 'N/A')}</p>
                </div>
                """, unsafe_allow_html=True)
            with col2:
                fallback = providers.get("fallback", {})
                st.markdown(f"""
                <div class="status-card">
                    <h4 style="color: #fbbf24;">🟡 Fallback: {fallback.get('name', 'N/A')}</h4>
                    <p style="color: rgba(255,255,255,0.6);">Model: {fallback.get('model', 'N/A')}</p>
                </div>
                """, unsafe_allow_html=True)
        return

    # ── Token Usage Summary ──
    st.markdown("### 📈 Token Usage Summary")
    token_summary = metrics_data.get("token_summary", [])

    if token_summary:
        cols = st.columns(len(token_summary))
        for i, summary in enumerate(token_summary):
            with cols[i]:
                st.markdown(f"""
                <div class="metric-card">
                    <h3>{summary.get('provider', 'N/A').upper()}</h3>
                    <div class="value">{summary.get('total_tokens', 0):,}</div>
                    <p style="color: rgba(255,255,255,0.5); font-size: 0.8rem;">
                        {summary.get('total_requests', 0)} requests •
                        {summary.get('rate_limited_count', 0)} rate-limited
                    </p>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Rate Limit Alerts ──
    rate_limit_count = metrics_data.get("rate_limit_last_hour", 0)
    if rate_limit_count > 0:
        st.markdown(f"""
        <div class="warning-banner" style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);">
            ⚠️ {rate_limit_count} rate-limit events in the last hour!
        </div>
        """, unsafe_allow_html=True)

    # ── Recent API Calls ──
    st.markdown("### 📋 Recent API Calls")
    metrics = metrics_data.get("metrics", [])

    if metrics:
        # Convert to displayable format
        for metric in metrics[:20]:
            provider = metric.get("provider", "")
            status_code = metric.get("status_code", "")
            tokens = metric.get("tokens_used", 0) or 0
            timestamp = metric.get("timestamp", "")
            is_rl = metric.get("is_rate_limited", False)

            status_icon = "🟢" if status_code == 200 else ("🟡" if status_code == 429 else "🔴")
            rl_badge = " ⚡ RATE LIMITED" if is_rl else ""

            st.markdown(
                f"{status_icon} **{provider}** — `{status_code}` — "
                f"{tokens:,} tokens — {timestamp}{rl_badge}"
            )


# ── Main App ────────────────────────────────────────────────────────

def main():
    """Main Streamlit application entry point."""

    # Authentication check
    if not check_auth():
        login_page()
        return

    # Sidebar navigation
    with st.sidebar:
        st.markdown("""
        <div class="sidebar-logo">
            <h2>
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle; margin-right: 6px;"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>
                MultiBotTele
            </h2>
            <p style="color: #807f7f; font-size: 0.75rem; letter-spacing: 0.04em;">COMMAND CENTER V1.0</p>
        </div>
        """, unsafe_allow_html=True)

        page = st.radio(
            "Navigation",
            [
                "Dashboard",
                "Agent & Persona",
                "Scheduling",
                "Live Chat",
                "Metrics",
            ],
            label_visibility="collapsed",
        )

        st.markdown("---")

        # Quick status
        config = load_config_file()
        if config:
            kill_switch = config.get("global_settings", {}).get("kill_switch", False)
            if kill_switch:
                st.error("Kill Switch: AKTIF")
            else:
                st.success("Sistem: Berjalan")

        st.markdown("---")

        if st.button("Logout", use_container_width=True):
            st.session_state["is_authenticated"] = False
            st.rerun()

    # Route to selected screen
    if page == "Dashboard":
        dashboard_screen()
    elif page == "Agent & Persona":
        agent_persona_screen()
    elif page == "Scheduling":
        scheduling_screen()
    elif page == "Live Chat":
        chat_monitor_screen()
    elif page == "Metrics":
        metrics_screen()


if __name__ == "__main__":
    main()
else:
    main()
