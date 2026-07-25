# 🤖 MultiBotTele — Multi-Agent Telegram Crowd Simulator

Sistem simulasi percakapan kerumunan (*crowd simulator*) berbasis **Multi-Agent AI** di Telegram. Aplikasi ini memungkinkan beberapa bot pengguna (Userbot) untuk berinteraksi secara alami di dalam grup/channel Telegram dengan berbagai kepribadian (persona), simulasi kecepatan mengetik (*typing jitter delay*), serta kontrol penuh melalui **Web Dashboard Streamlit** dan **FastAPI IPC System**.

---

## 🌟 Fitur Utama

- **Multi-Agent Userbots (Telethon MTProto)**: Mengelola beberapa akun Telegram secara bersamaan dengan sesi aman.
- **LLM Failover Guard**: Menggunakan Google **Gemini 3.5 Flash-Lite** sebagai LLM utama dan **Groq (Llama 3)** sebagai cadangan otomatis (*auto-failover*) saat batas kuota/rate limit tercapai.
- **Organic Human Behavior Simulation**:
  - **Typing Delay Calculation**: Kecepatan mengetik realistis berdasarkan kata per menit (WPM).
  - **Natural Jitter**: Waktu tunggu acak antar pesan (*inter-message delay*).
  - **Smart Anti-Spam / Skip Logic**: AI secara cerdas dapat mengabaikan pesan sistem atau pesan yang tidak relevan (`<SKIP>`).
- **Interactive Streamlit Web Dashboard**:
  - **Command Center**: Status agen real-time & *Emergency Kill Switch*.
  - **Live Chat Monitor**: Feed obrolan real-time & pemantauan *sliding window context*.
  - **Agent & Persona Manager**: Ubah prompt sifat/karakter agen secara langsung (*hot-reload*).
  - **Behavior & Scheduling Settings**: Atur jam aktif dan frekuensi obrolan.
- **SQLite & Context Engine**: Menyimpan riwayat chat dan konteks pembicaraan untuk menjaga konsistensi ingatan bot.

---

## 🏗️ Struktur Proyek

```text
MultiBotTele/
├── api/                  # REST API Server (FastAPI) & Endpoints
│   ├── server.py         # Main IPC Server
│   └── ...
├── core/                 # Core Engine & Business Logic
│   ├── config_manager.py # Pydantic configuration & hot-reload
│   ├── context_engine.py # Context builder & payload generator
│   ├── database.py       # SQLite database manager
│   ├── jitter.py         # Typing delay & timing logic
│   ├── llm_router.py     # Gemini & Groq failover router
│   ├── orchestrator.py   # Multi-agent conversation coordinator
│   ├── scheduler.py      # APScheduler background tasks
│   └── telegram_client.py# Telethon MTProto client manager
├── dashboard/            # Web UI Manager (Streamlit)
│   └── app.py            # Dashboard entrypoint (6 Screens)
├── data/                 # SQLite database storage & logs (Ignored in git)
├── sessions/             # Telethon userbot .session files (Ignored in git)
├── .env.example          # Template environment variable
├── config.json           # Agent & system configuration
├── main.py               # Application Entry Point
├── requirements.txt      # Python dependencies
└── README.md             # Dokumentasi Proyek
```

---

## 🚀 Panduan Instalasi & Penggunaan

### 1. Prasyarat
- Python `3.10` atau versi lebih baru.
- Akun Telegram (beserta `API_ID` & `API_HASH` dari [my.telegram.org](https://my.telegram.org)).
- Google Gemini API Key dari [Google AI Studio](https://aistudio.google.com).

### 2. Clone & Setup Virtual Environment

```bash
# Clone repository
git clone https://github.com/fhmi-kzkf/MultiBotTele.git
cd MultiBotTele

# Buat dan aktifkan virtual environment
python -m venv .venv

# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

# Linux/macOS:
source .venv/bin/activate

# Install dependensi
pip install -r requirements.txt
```

### 3. Konfigurasi Environment Variables

Salin file `.env.example` menjadi `.env`:

```bash
cp .env.example .env
```

Buka file `.env` dan isi kredensial yang dibutuhkan:

```env
# Dashboard Auth
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_me_to_a_strong_password

# Telegram Credentials (dari my.telegram.org)
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash_here

# Target Chat Group ID (Gunakan ID negatif untuk group)
TARGET_CHAT_ID=-1001234567890

# LLM API Keys
GEMINI_API_KEY=your_gemini_api_key_here
GROQ_API_KEY=your_groq_api_key_here (opsional)
```

### 4. Konfigurasi Agen & Persona (`config.json`)

Buka [`config.json`](file:///c:/Users/GC/Desktop/MultiBotTele/config.json) untuk mengatur nomor HP agen dan kepribadiannya:

```json
{
  "global_settings": {
    "kill_switch": false,
    "target_chat_id": -1001234567890
  },
  "llm_providers": {
    "primary": {
      "name": "gemini",
      "model": "gemini-3.5-flash-lite"
    }
  },
  "agents": [
    {
      "id": "agent_1",
      "name": "Ardi",
      "phone": "+6281234567890",
      "is_active": true,
      "persona_prompt": "Kamu adalah Ardi, seorang Web3 developer..."
    }
  ]
}
```

---

## 💻 Menjalankan Aplikasi

### 1. Jalankan Core System & Userbots

Buka terminal pertama dan jalankan:

```bash
python main.py
```
> **Catatan**: Saat pertama kali dijalankan untuk agen baru, terminal akan meminta **Kode OTP Telegram** yang dikirim ke HP akun terkait.

### 2. Jalankan Web Dashboard

Buka terminal kedua dan jalankan:

```bash
streamlit run dashboard/app.py
```
Akses dashboard di browser melalui **http://localhost:8501** (Login dengan Username & Password dari `.env`).

---

## 🛡️ Keamanan & Privasi

- **Jangan Commit File Rahasia**: File `.env`, `config.json`, folder `sessions/`, dan file database `data/*.db` telah dimasukkan ke dalam `.gitignore` untuk mencegah kebocoran credentials atau akses akun Telegram Anda.
- **Auto Logout**: Hapus file di folder `sessions/` untuk memutus akses Telethon dari akun Telegram.

---

## 📄 Lisensi

Proyek ini dibuat untuk tujuan edukasi dan simulasi. Gunakan secara bijak dan pastikan mematuhi *Terms of Service* dari Telegram dan penyedia LLM.
