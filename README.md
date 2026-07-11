# 🎙️ Echo — A Voice AI Assistant with an Iron-Man-style HUD

Talk to it in your voice, and it talks back in a natural voice — while actually
**doing things**: searching the web, playing music, opening & closing apps,
sending WhatsApp messages, managing reminders, and more. All wrapped in an
animated **J.A.R.V.I.S.-style holographic interface**.

Built with a **Python / FastAPI** backend and a **React** frontend, with a
**provider-agnostic** design: the brain (LLM) and the voice are swappable between
a **free local model**, **Claude**, or an **OpenAI-compatible AI gateway** — with a
single line in `.env`.

> ⭐ A portfolio project demonstrating full-stack development, real-time audio,
> LLM agent/tool-use design, desktop automation, and a clean provider abstraction.

> 📖 **New here? Read [`docs/PROJECT_GUIDE.md`](docs/PROJECT_GUIDE.md)** — a full
> walkthrough from basics to advanced: the concepts, every file, and how to extend it.

*(The assistant's name is configurable — set `ASSISTANT_NAME` in `.env`. "Echo" is
just the default; call it whatever you like.)*

---

## ✨ Features

| Capability | What it does |
|---|---|
| 🎙️ **Voice in** | Records your mic, auto-stops when you pause, and transcribes it |
| 🔊 **Voice out** | Replies in a natural voice (ElevenLabs) |
| 🧠 **Swappable brain** | Local Ollama, Claude, or an AI gateway — one `.env` switch |
| 🛠️ **Agentic tool use** | The model decides *when* to talk vs. *when* to act (20 tools) |
| 🔎 **Web search** | Live info via DuckDuckGo — no API key |
| 🎵 **Play & control media** | "Play Shape of You" actually plays it; pause / skip / volume |
| 🖥️ **Desktop automation** | Open apps (verified installed), open/close windows |
| 💬 **Messaging** | Sends confirmed WhatsApp or Discord messages via desktop automation |
| ✅ **Productivity** | To-dos, notes, reminders, calculator, date/time |
| 🧠 **Long-term memory** | Optional RecallrAI memory with low-latency recall and proxy routing |
| 🗣️ **3 ways to talk** | Tap-once (auto-send on pause), continuous hands-free, or type |
| 🌌 **Sci-fi HUD** | Reactive arc-reactor, aurora backdrop, live telemetry |

---

## 🏗️ Architecture

The LLM and voice both sit behind small **provider interfaces**, so the agent loop
and all tools are identical no matter which backend you choose.

```
┌──────────────────────────┐          ┌───────────────────────────────────────────┐
│   React frontend (Vite)  │          │            FastAPI backend (Python)        │
│  🔮 reactive HUD + orb   │          │                                            │
│  🎙 mic (silence detect) ─┼─ audio ─►│  Speech-to-Text  ─►  Agent loop (LLM +     │
│  🔊 audio playback   ◄────┼── mp3 ───┼─  Text-to-Speech ◄─  tool use)             │
│  🏷 active-brain badge   │          │                        │                   │
└──────────────────────────┘          │        ┌───────────────┴───────────────┐   │
                                       │        ▼               ▼               ▼   │
                                       │  🖥 Ollama        ☁ Claude       🔀 Gateway│
                                       │  (local)          (cloud)     (one key→many)│
                                       │              picks & runs tools:            │
                                       │   web · media · apps · windows · whatsapp   │
                                       │   todos · notes · reminders · calc · system │
                                       └───────────────────────────────────────────┘
```

**Voice-turn flow:** mic (auto-stops on silence) → transcribe → agentic loop (the
model may call tools) → final reply → speak it → the UI plays it and shows the
actions taken.

---

## 🚀 Quick start

### Prerequisites
- **Python 3.10+** and **Node.js 18+**
- **A brain** — one of: [Ollama](https://ollama.com) (free, local) · an
  [Anthropic key](https://console.anthropic.com/settings/keys) · an AI gateway URL+key
- **A voice** — an [ElevenLabs key](https://elevenlabs.io/app/settings/api-keys)
  (or route voice through your gateway)

### 1. Configure
```bash
cd backend
copy .env.example .env        # (macOS/Linux: cp .env.example .env)
```
Open `backend/.env`, pick your `LLM_PROVIDER` + `VOICE_PROVIDER`, and add the
relevant key(s). *(For the fully-free path: `LLM_PROVIDER=ollama` +
`ollama pull llama3.2:3b`, and an ElevenLabs key for the voice.)*

Optional: set `RECALLRAI_ENABLED=true`, add your RecallrAI API key/project ID,
and point `RECALLRAI_BASE_URL` at your low-latency forward proxy if you have one.

### 2. Start the backend (terminal 1)
```powershell
./start-backend.ps1
```
First run creates a virtualenv, installs deps, and serves the API at
**http://127.0.0.1:8000**.

### 3. Start the frontend (terminal 2)
```powershell
./start-frontend.ps1
```
Open **http://localhost:5173**, allow the microphone, tap the reactor core, and talk.

> The app's status banner tells you exactly what's missing (e.g. "run `ollama pull …`"
> or "…KEY is missing"), so setup is self-guiding.
>
> Not on Windows / prefer manual commands? See [Manual setup](#-manual-setup).

---

## 🗣️ Try saying…

- *"What's the weather in Tokyo right now?"* → web search
- *"Play Shape of You by Ed Sheeran."* → plays it on YouTube
- *"Pause the music."* / *"Volume up."* → media control
- *"Open Notepad."* / *"Close the YouTube window."* → app / window control
- *"Send a WhatsApp to Alex saying I'm running late."* → sends it
- *"Message Alex on Discord saying I'm joining in five."* → asks for confirmation, then sends
- *"Add 'finish the report' to my to-do list."* · *"Remind me to stretch in 20 minutes."*
- *"What's 18% of 2,450?"* · *"What's today's date?"*

---

## ⚙️ Configuration (`backend/.env`)

| Setting | Meaning |
|---|---|
| `LLM_PROVIDER` | `ollama` (local/free), `anthropic` (cloud), or `gateway` |
| `VOICE_PROVIDER` | `elevenlabs` or `gateway` |
| `OLLAMA_MODEL` / `OLLAMA_HOST` | local model + server |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Claude direct |
| `GATEWAY_BASE_URL` / `GATEWAY_API_KEY` / `GATEWAY_*_MODEL` | AI-gateway settings |
| `ELEVENLABS_API_KEY` / `ELEVENLABS_VOICE_ID` | voice out (+ Scribe STT) |
| `ASSISTANT_NAME` | the name it uses everywhere |
| `REPLY_MAX_TOKENS` | caps reply length (shorter = faster) |
| `RECALLRAI_ENABLED` / `RECALLRAI_API_KEY` / `RECALLRAI_PROJECT_ID` | optional RecallrAI long-term memory |
| `RECALLRAI_RECALL_STRATEGY` | memory recall mode; defaults to `low_latency` for voice speed |
| `RECALLRAI_BASE_URL` | RecallrAI API endpoint, or a low-latency forward proxy exposing the same API |
| `RECALLRAI_FORWARD_PROXY_URL` | optional classic HTTP(S) forward proxy for RecallrAI SDK traffic |
| `ALLOW_SHELL_COMMANDS` | let it run shell commands (⚠️ off by default) |

See [`.env.example`](backend/.env.example) for the full annotated template.

---

## 🔒 Safety notes

- **Secrets never get committed** — `.env` is git-ignored; only `.env.example` (no
  keys) is tracked.
- **Shell command execution is OFF by default** (`ALLOW_SHELL_COMMANDS=false`).
- The calculator uses a **safe AST evaluator**, never Python `eval`.
- App-opening **verifies the app is installed** before launching (honest failures).
- WhatsApp/Discord/media/window tools use OS automation — they act on *your* machine only.

---

## 🧰 Tech stack

- **Backend:** Python, FastAPI, Uvicorn, SQLite (stdlib), httpx
- **AI (brain):** Ollama (local) · Anthropic Claude · any OpenAI-compatible gateway
- **Voice:** ElevenLabs (TTS) + Whisper/Scribe (STT)
- **Automation:** pyautogui / pygetwindow (media, messaging, windows)
- **Web search:** DuckDuckGo (`ddgs`) — no key
- **Frontend:** React 18, Vite, MediaRecorder + Web Audio (silence detection), SVG/CSS HUD

---

## 📁 Project structure

```
voice-assistant/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI endpoints (+ timing instrumentation)
│   │   ├── agent.py           # provider-agnostic tool-use loop
│   │   ├── config.py          # env/settings + provider selection
│   │   ├── db.py              # SQLite (todos, notes, reminders)
│   │   ├── voice.py           # voice dispatcher (ElevenLabs / gateway)
│   │   ├── voice_gateway.py   # STT/TTS via OpenAI-compatible gateway
│   │   ├── llm/               # the swappable brain
│   │   │   ├── base.py            # LLMProvider interface + normalized types
│   │   │   ├── ollama_provider.py
│   │   │   ├── anthropic_provider.py
│   │   │   └── gateway_provider.py
│   │   └── tools/             # everything the assistant can DO (20 tools)
│   │       ├── registry.py        # schemas + dispatch
│   │       ├── web_search.py
│   │       ├── productivity.py    # todos, notes, reminders, calc, time
│   │       └── system_automation.py # open/close apps & windows, media,
│   │                                 # whatsapp, play youtube, sysinfo, shell
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── App.jsx            # the HUD + all logic
│       ├── listen.js          # silence-detecting recorder
│       ├── api.js
│       └── styles.css         # the J.A.R.V.I.S. HUD styling
├── docs/PROJECT_GUIDE.md      # full basics→advanced guide
├── start-backend.ps1
└── start-frontend.ps1
```

---

## 🧑‍💻 Manual setup

**Backend**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
```

---

## 🌟 Resume highlights

- **Provider-agnostic architecture** — the LLM and voice are swappable (local Ollama
  ↔ cloud Claude ↔ OpenAI-compatible gateway) behind clean interfaces with a
  normalized message/tool-call format.
- **LLM agentic tool-use loop** — the model plans, calls 20 typed tools, reads
  results, and iterates.
- **Real desktop automation** — verified app-launching, media control, window
  management, WhatsApp messaging (UI automation).
- **Real-time audio** — browser mic capture with **Web-Audio silence detection**,
  server transcription, and spoken-reply playback; a hands-free conversation loop.
- **Latency engineering** — connection reuse, timing instrumentation, fast models.
- **Custom animated HUD** (SVG + CSS) inspired by Iron Man's J.A.R.V.I.S.
- **Security-conscious defaults** — git-ignored secrets, sandboxed calculator,
  opt-in shell access, honest failure reporting.

---

## 📌 Roadmap ideas
- Streaming playback (start speaking before the full reply is generated)
- Wake-word / always-on mode
- Spotify playback, email sending, calendar integration

---

*Built with Python, React, and your choice of local or cloud AI. Voice by ElevenLabs.*
