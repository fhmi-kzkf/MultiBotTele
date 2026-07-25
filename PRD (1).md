# Product Requirements Document (PRD): Multi-Agent Telegram Crowd Simulator

## 1. Executive Summary
**Multi-Agent Telegram Crowd Simulator (Group Warmer Network)** adalah sistem orkestrasi backend terpusat yang dirancang untuk mensimulasikan diskusi komunitas Telegram yang hidup, natural, dan terjadwal. Sistem ini mengendalikan jaringan 5 akun Userbot dengan kepribadian (persona) unik, ditenagai oleh Live LLM API (Gemini/Groq/Qwen). Produk ini dikirimkan sebagai aplikasi *self-hosted* (Modular Monolith) pada VPS tunggal, dilengkapi dengan antarmuka Streamlit untuk memudahkan Community Manager non-teknis. Tujuan utamanya adalah membangun *social proof* yang sempurna untuk komunitas baru (Web3, kripto, startup) tanpa memunculkan label "BOT" dan tanpa merusak alur obrolan organik.

## 2. Problem Statement & Goals

### Problem Statement
* **Grup "Mati" Menghalangi Pertumbuhan:** Komunitas Telegram baru (produk, kripto, startup) sering kali terlihat sepi, sehingga menurunkan kepercayaan pengguna asli untuk bergabung dan berinteraksi.
* **Bot Standar Terlihat Palsu:** Penggunaan Telegram Bot API standar memunculkan lencana "BOT" yang merusak ilusi interaksi manusia dan menurunkan kredibilitas *social proof*.
* **Risiko Banned Telegram:** Penggunaan script otomatis yang tidak meniru perilaku manusia (pola ketik robotik, spam pesan) berisiko tinggi terkena *ban hammer* oleh Telegram.
* **Konfigurasi Teknis yang Rumit:** Community Manager sering kali tidak memiliki latar belakang teknis, sehingga konfigurasi berbasis kode (JSON/YAML) rawan kesalahan dan sulit dikelola.

### Goals
1. **Menciptakan Ilusi Organik Sempurna:** Mensimulasikan diskusi yang 100% terlihat seperti pengguna manusia asli menggunakan akun Userbot (tanpa label BOT).
2. **Interaksi Dinamis dengan Manusia:** Memastikan bot dapat menyela skenario dan merespons pengguna asli secara kontekstual tanpa merusak alur obrolan.
3. **Mitigasi Risiko Banned:** Menerapkan *jitter* dan penjadwalan organik yang meniru perilaku manusia (kecepatan mengetik, waktu tidur, jeda acak).
4. **Aksesibilitas Manajemen:** Menyediakan antarmuka visual (Web UI) yang aman dan intuitif bagi Community Manager non-teknis.
5. **Efisiensi Biaya & Ketersediaan:** Mengoptimalkan penggunaan token LLM dan menjamin *uptime* 24/7 dengan mekanisme *failover* API.

## 3. Target Audience
* **Pemilik Proyek / Klien:** Pendiri startup, proyek Web3/Kripto, atau pemilik produk yang ingin membangun *social proof* dan meramaikan komunitas Telegram baru mereka agar terlihat aktif dan kredibel.
* **Community Managers (CM):** Pengelola grup yang membutuhkan asisten otomatis untuk memicu diskusi berkualitas. Mereka adalah pengguna utama sistem yang membutuhkan antarmuka visual untuk mengontrol bot tanpa harus menyentuh kode.

## 4. Core Features & User Stories

### 4.1. Centralized Multi-Agent Registry & Queue Manager
Sistem backend terpusat yang mengatur antrean pesan dari 5 bot dengan persona berbeda. Menerapkan sistem *locking* saat bot berstatus `is_typing` untuk mencegah *race conditions* dan tabrakan pesan.
* **User Story:** *Sebagai sistem orkestrasi, saya perlu mengunci agen yang sedang "mengetik" agar tidak ada dua bot yang mengirim pesan secara bersamaan atau memotong pesan satu sama lain.*

### 4.2. Context-Aware Human Interruption Handling
Fitur deteksi intervensi manusia berprioritas tinggi. Jika pengguna asli mengirim pesan, sistem menunda antrean skenario, memasukkan input manusia ke memori, dan memerintahkan bot paling relevan untuk membalas secara dinamis.
* **User Story:** *Sebagai pengguna asli di grup, ketika saya bertanya atau menyela, saya ingin direspons secara natural oleh salah satu anggota grup (bot) yang paling relevan, tanpa mengabaikan pertanyaan saya.*

### 4.3. Config-Driven Organic Scheduling & Anti-Ban Jitter
Penjadwalan otomatis berbasis waktu aktif/tidur menggunakan *randomized burst delays* (jeda 20-40 menit). Menggunakan *jitter* pada kecepatan mengetik (`typing_speed_wpm`) yang dihitung dari panjang teks untuk mengaburkan pola robotik dan mencegah *ban* dari Telegram.
* **User Story:** *Sebagai sistem, saya perlu mensimulasikan jeda waktu acak dan kecepatan mengetik yang bervariasi layaknya manusia, untuk menghindari deteksi spam oleh sistem keamanan Telegram.*

### 4.4. Sliding Window Context & Persona Lock
Mekanisme pembatasan memori yang hanya mengirimkan 10–15 pesan terakhir di grup ke LLM. Mencegah *context drift* (bot kehilangan watak asli) dan menghemat kuota token input secara drastis.
* **User Story:** *Sebagai sistem LLM, saya perlu membatasi konteks hanya pada 15 pesan terakhir agar persona bot tetap konsisten dan biaya API tetap rendah.*

### 4.5. Multi-Provider API Router & Failover Guard
Sistem pertahanan backend yang secara otomatis mengalihkan *request* LLM ke penyedia cadangan (misal: dari Gemini ke Groq Llama 3/Qwen) jika terkena *rate limit* (HTTP 429) tanpa memutus percakapan.
* **User Story:** *Sebagai sistem, jika API LLM utama mencapai batas rate limit, saya harus secara instan beralih ke API cadangan agar percakapan di grup tidak terhenti.*

### 4.6. Streamlit Web UI Dashboard (Non-Technical Configuration)
Antarmuka Web UI berbasis Streamlit dengan proteksi *Basic Auth* untuk Community Manager. Fitur meliputi:
* **Slider Interaktif:** Mengatur jam aktif/tidup grup dan durasi jeda acak.
* **Text Area Persona:** Menulis/mengubah *System Prompt* (watak) masing-masing dari 5 agen.
* **Toggle Switch:** Menyalakan/mematikan agen tertentu.
* **Emergency Kill Switch:** Tombol darurat untuk membekukan seluruh aktivitas grup secara instan.
* **Validasi Backend:** Memvalidasi input UI sebelum menulisnya ke `config.json` untuk mencegah *syntax error*.
* **User Story:** *Sebagai Community Manager non-teknis, saya ingin menggunakan dashboard visual dengan tombol dan slider untuk mengatur jadwal, persona, dan mematikan bot secara darurat tanpa harus mengedit file konfigurasi via SSH.*

## 5. Non-Functional Requirements

### 5.1. Architecture & Deployment
* **Model Delivery:** *Self-Hosted Application* (Asynchronous Modular Monolith MVP).
* **Infrastruktur:** Single-node Ubuntu VPS.
* **Process Management:** Dijalankan 24/7 di *background* menggunakan `systemd` service atau `tmux`.
* **Isolasi:** Berjalan di *environment* terisolasi pada VPS klien.

### 5.2. Technology Stack
* **Language:** Python 3.10+
* **Telegram Client:** Telethon / Pyrogram (100% Userbot via MTProto Client API, **bukan** Telegram Bot API standar).
* **Scheduler:** APScheduler.
* **LLM Engine:** Google Gemini Flash API & Groq Cloud API (Free Tiers).
* **Database:** SQLite (penyimpanan riwayat sesi ringan lokal).
* **Frontend/Config UI:** Streamlit.

### 5.3. Security & Safety
* **Access Control:** Dashboard Streamlit harus dilindungi dengan *Basic Auth* (Username/Password).
* **Data Protection:** File `config.json` dan database SQLite harus memiliki *permission* yang ketat (hanya dapat dibaca/ditulis oleh user service).
* **Input Validation:** Semua input dari Streamlit UI harus divalidasi (sanitized) sebelum di-*inject* ke `config.json` untuk mencegah injeksi kode atau kerusakan sintaks.

### 5.4. Reliability & Performance
* **Uptime:** Sistem harus mampu berjalan 24/7 dengan mekanisme *auto-restart* jika script *crash* (via systemd).
* **Latency:** Respons LLM harus di-*stream* atau di-*handle* secara asinkron agar tidak memblokir *event loop* Telegram.
* **Token Efficiency:** Implementasi *Sliding Window* harus secara ketat membatasi payload ke LLM maksimal 15 pesan untuk menjaga latensi rendah dan biaya nol/minim (menggunakan Free Tiers).

### 5.5. Constraints & Risks
* **Risk:** Penggunaan Userbot (MTProto) memiliki risiko *banned* oleh Telegram.
* **Mitigation:** Wajib menerapkan *Organic Scheduling* dengan *jitter* (`typing_speed_wpm`), membatasi jumlah pesan per jam, dan menyediakan *Kill Switch* di dashboard untuk menghentikan aktivitas segera jika terdeteksi anomali.