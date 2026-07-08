# 🎙️ Jarvis — Complete Project Guide (Basics → Advanced)

This guide explains **everything** about the Jarvis voice assistant: what it is,
the concepts behind it, how each file works, and how to extend it. It assumes
you know a little coding but explains the important ideas from scratch.

---

## Table of Contents
1. [What this project is (plain English)](#1-what-this-project-is)
2. [Core concepts you need (explained simply)](#2-core-concepts)
3. [The big picture: how one voice request flows](#3-the-big-picture)
4. [Tech stack & why](#4-tech-stack)
5. [Project structure (every file)](#5-project-structure)
6. [Backend deep dive](#6-backend-deep-dive)
7. [Frontend deep dive](#7-frontend-deep-dive)
8. [The AI Gateway (Bifrost) explained](#8-the-ai-gateway)
9. [How to run & configure](#9-how-to-run--configure)
10. [How to extend it (add your own tool)](#10-how-to-extend-it)
11. [Glossary](#11-glossary)
12. [Resume talking points](#12-resume-talking-points)

---

## 1. What this project is

**Jarvis is a voice assistant, like a mini Iron Man J.A.R.V.I.S.** You talk to it,
it understands you, it *does things* (searches the web, opens apps, sends
WhatsApp messages, manages reminders), and it talks back in a natural voice — all
wrapped in a sci-fi holographic interface.

It has **two halves**:
- A **frontend** (the web page you see and talk to, in your browser).
- A **backend** (a program running on your PC that does the actual thinking, voice
  processing, and actions).

They talk to each other over HTTP (the same protocol websites use).

---

## 2. Core concepts

Before the code, here are the ideas everything is built on.

### 🧠 LLM (Large Language Model)
An LLM (like **Claude**) is an AI trained on huge amounts of text. You send it a
message, it sends back a smart response. It's the "brain." On its own it can only
*talk* — it can't open apps or search the web.

### 🔧 Tool use / function calling — *the key idea*
This is how an LLM goes from "just talking" to "actually doing things."

You give the LLM a **list of tools** it's allowed to use, each with a name and
description (e.g. `open_application`, `web_search`, `send_whatsapp`). When you ask
it something, the LLM can reply in two ways:
1. **Normal answer** — "The capital of France is Paris."
2. **"I want to use a tool"** — instead of answering, it says *"call
   `send_whatsapp` with contact='Devashish', message='hi'."*

When it picks option 2, **your code runs that tool**, gets the result, and hands
it back to the LLM, which then continues. This back-and-forth is called the
**agentic loop**:

```
You: "text Devashish hi"
  → LLM: "call send_whatsapp(Devashish, hi)"
      → your code sends the WhatsApp message, returns "sent!"
          → LLM: "Done — I've texted Devashish." (final answer)
```

That loop is the heart of the whole project (see `agent.py`).

### 🎙️ STT & TTS (the voice parts)
- **STT — Speech-to-Text**: converts your recorded voice into text (so the LLM can
  read it). We use **Whisper**.
- **TTS — Text-to-Speech**: converts the LLM's text reply into spoken audio. We use
  **ElevenLabs**.

### 🔑 API & API key
An **API** is a way for one program to ask another program to do something over
the internet. To use a paid API (like ElevenLabs or Claude) you need an **API
key** — a secret password that identifies you and bills your account. Keys live in
a private file (`.env`) and must never be shared or committed to GitHub.

### 🔌 Provider abstraction
Our code doesn't hard-wire *one* AI. It defines a common "shape" (an interface)
and can plug in **different brains** — a free local model (Ollama), Claude in the
cloud, or an AI gateway — by changing one line in `.env`. Same for voice. This is
the project's cleanest engineering idea.

---

## 3. The big picture

Here's what happens end-to-end when you **speak** to Jarvis:

```
   YOU speak
      │  (browser records your mic → audio file)
      ▼
┌─────────────┐   audio    ┌───────────────────────────────────────────┐
│  FRONTEND   │ ─────────► │                 BACKEND                    │
│ (React app) │            │                                           │
│  in browser │            │  1. STT: audio → text  (Whisper)          │
│             │            │  2. AGENT LOOP: text → LLM (Claude)        │
│             │            │       ↳ LLM may call TOOLS:                │
│             │            │          web_search / open_app /           │
│             │            │          send_whatsapp / reminders / …     │
│             │            │  3. LLM produces a final text reply        │
│             │            │  4. TTS: reply text → speech (ElevenLabs)  │
│             │ ◄───────── │                                           │
│ plays audio │  reply +   └───────────────────────────────────────────┘
│ shows text  │  mp3 audio
└─────────────┘
```

Typing works the same way, just skipping step 1 (STT).

---

## 4. Tech stack

| Layer | Technology | Why |
|---|---|---|
| Backend web server | **Python + FastAPI** | Fast, simple, great for APIs; Python is the language of AI |
| Frontend | **React + Vite** | Standard modern UI library; Vite = instant hot-reload dev server |
| Brain (LLM) | **Claude** (via gateway), or **Ollama** local | Strong tool-use reasoning |
| Voice | **ElevenLabs** (TTS) + **Whisper** (STT) | Natural voice + accurate transcription |
| Storage | **SQLite** | Zero-setup file database for to-dos/notes/reminders |
| Automation | **pyautogui** | Controls keyboard/mouse to actually perform tasks |
| Web search | **DuckDuckGo (ddgs)** | Free, no API key |

---

## 5. Project structure

```
voice-assistant/
├── backend/                    # The Python "brain + actions" server
│   ├── app/
│   │   ├── main.py             # FastAPI web server — the API endpoints
│   │   ├── config.py           # Reads settings/keys from .env
│   │   ├── agent.py            # THE AGENT LOOP (LLM + tool use)
│   │   ├── db.py               # SQLite database (to-dos, notes, reminders)
│   │   ├── voice.py            # Voice dispatcher (picks ElevenLabs or gateway)
│   │   ├── voice_gateway.py    # Voice via the OpenAI-compatible gateway
│   │   ├── llm/                # ← the swappable "brain" layer
│   │   │   ├── base.py             # The common interface + data types
│   │   │   ├── ollama_provider.py  # Local free model
│   │   │   ├── anthropic_provider.py # Claude directly (needs Anthropic key)
│   │   │   └── gateway_provider.py  # Claude/others via the gateway
│   │   └── tools/              # ← everything the assistant can DO
│   │       ├── registry.py         # List of tools + how to run each
│   │       ├── web_search.py       # DuckDuckGo search
│   │       ├── productivity.py     # to-dos, notes, reminders, calculator
│   │       └── system_automation.py # open apps, send WhatsApp, run commands
│   ├── requirements.txt        # Python dependencies
│   └── .env                    # YOUR secret keys/settings (git-ignored)
│
├── frontend/                   # The React web UI
│   └── src/
│       ├── App.jsx             # The whole UI + logic (the HUD)
│       ├── useRecorder.js      # Records mic audio (push-to-talk)
│       ├── listen.js           # Silence-detecting recorder (hands-free mode)
│       ├── api.js              # Calls the backend endpoints
│       └── styles.css          # The Iron Man HUD styling
│
├── start-backend.ps1           # One-click backend launcher
├── start-frontend.ps1          # One-click frontend launcher
└── docs/PROJECT_GUIDE.md       # ← you are here
```

---

## 6. Backend deep dive

### `config.py` — settings & keys
Loads your `.env` file into a `settings` object the whole app reads. It decides
**which brain** (`LLM_PROVIDER`) and **which voice** (`VOICE_PROVIDER`) to use, and
holds the gateway URL, model names, etc. `require_keys()` returns a friendly list
of what's missing (that's what powers the "Setup needed" banner in the UI).

### `llm/` — the swappable brain (provider abstraction)
This is the elegant part. `base.py` defines:
- `LLMProvider` — an interface with one method: `chat(system, messages, tools)`.
- `ToolCall` and `AssistantTurn` — a **normalized** way to represent "the model
  replied with this text and wants to call these tools" — *independent of which
  provider we used.*

Then each provider translates that normal format to/from its own API:
- `ollama_provider.py` → talks to a local model on your PC.
- `anthropic_provider.py` → talks to Claude directly.
- `gateway_provider.py` → talks to the Bifrost gateway (OpenAI-compatible).

`llm/__init__.py` has `get_provider()` which reads `LLM_PROVIDER` and returns the
right one. **Add a new AI provider = add one file; nothing else changes.**

### `agent.py` — THE agentic loop (most important file)
This runs the tool-use loop described in [concepts](#2-core-concepts):

```python
messages = history + [your message]
for a few iterations:
    turn = provider.chat(system_prompt, messages, TOOL_SCHEMAS)   # ask the LLM
    messages.append(the assistant turn)
    if turn has NO tool calls:
        return turn.text            # ← final answer, we're done
    for each tool call:
        result = dispatch(tool_name, arguments)   # run the tool
        messages.append(the tool result)
    # loop again so the LLM can react to the tool results
```

The `system_prompt` is the instruction that shapes Jarvis's personality ("you are
a helpful voice assistant, keep replies short since they're spoken aloud, use
tools when asked to DO something"). Conversation history is kept per session in
memory so it remembers earlier turns.

### `tools/` — everything Jarvis can DO
`registry.py` has two things:
- `TOOL_SCHEMAS` — the JSON descriptions the LLM sees (name, description, inputs).
  This is the "menu" of tools the model can pick from.
- `dispatch(name, args)` — looks up the matching Python function and runs it.

The actual tools:
- **`web_search.py`** — searches DuckDuckGo (no key needed), returns top results.
- **`productivity.py`** — to-dos, notes, reminders (saved in SQLite), and a **safe
  calculator** (uses Python's AST parser, never the dangerous `eval`).
- **`system_automation.py`** — the powerful one:
  - `open_application` — **verifies** an app is really installed (checks real
    install paths and registered Windows app protocols) *before* launching, so it
    never lies about success.
  - `send_whatsapp` — actually **types and sends** a WhatsApp message using
    `pyautogui` (opens WhatsApp → searches the contact → pastes the message →
    presses Enter).
  - `open_url`, `get_system_info`, `run_command` (shell, off by default for safety).

### `voice.py` + `voice_gateway.py` — hearing & speaking
`voice.py` is a **dispatcher**: based on `VOICE_PROVIDER`, it routes to either
ElevenLabs directly or the gateway.
- `speech_to_text(audio)` → sends your recording to Whisper, gets text.
- `text_to_speech(text)` → sends the reply text to ElevenLabs, gets MP3 audio.

Both are just HTTP calls (using `httpx`).

### `db.py` — storage
A tiny SQLite database (a single `.db` file). Three tables: `todos`, `notes`,
`reminders`. No server to install — perfect for a personal app.

### `main.py` — the web server (FastAPI)
Defines the **API endpoints** the frontend calls:

| Endpoint | What it does |
|---|---|
| `GET /api/health` | Reports status: which brain/voice, what's missing |
| `POST /api/voice` | audio in → transcribe → agent → reply text + reply audio |
| `POST /api/text` | text in → agent → reply text (+ optional audio) |
| `GET /api/reminders/due` | reminders that have come due (for pop-ups) |
| `POST /api/reset` | clears the conversation memory |

CORS middleware lets the frontend (on port 5173) talk to the backend (port 8000).

---

## 7. Frontend deep dive

### React in 30 seconds
React builds UIs from **components** (functions that return HTML-like markup
called JSX). **State** (via `useState`) is data that, when it changes, re-renders
the screen. **Hooks** (`useEffect`, `useRef`, custom ones like `useRecorder`) add
behavior. That's 90% of what you need to read `App.jsx`.

### `api.js` — talking to the backend
Small wrapper functions: `sendVoice(blob)`, `sendText(text)`, `getHealth()`, etc.
Each does a `fetch()` (HTTP request) to a `/api/...` endpoint. During development,
Vite **proxies** `/api` to the backend so there are no cross-origin issues (see
`vite.config.js`).

### `useRecorder.js` — push-to-talk
A custom hook wrapping the browser's **MediaRecorder API**. `start()` asks for mic
permission and begins recording; `stop()` returns the recorded audio as a `Blob`
(a file-like object) which we upload to `/api/voice`.

### `listen.js` — hands-free conversation mode
This is the clever one. It records **and automatically stops when you stop
talking**, using the **Web Audio API**: it watches the microphone's volume in real
time. Once you've spoken and then go quiet for ~1.3 seconds, it stops and returns
the audio. That's what makes the back-and-forth conversation loop possible (Jarvis
replies, then auto-listens for your next turn).

### `App.jsx` — the whole UI + logic
Holds all state (messages, busy, speaking, hands-free on/off) and the handlers:
- `toggleRecording()` — manual push-to-talk (tap the reactor).
- `converseLoop()` — the hands-free loop: listen → send → reply → listen again.
- `runText()` / `submitText()` — send a typed command.
- `playReply()` — plays the MP3 audio and *resolves a Promise when it finishes*, so
  conversation mode waits for Jarvis to stop speaking before listening again.
- The `Reactor` component — the SVG arc-reactor that changes color/animation based
  on state (idle / listening / thinking / speaking).

### `styles.css` — the Iron Man HUD
Pure CSS/SVG effects: an animated **aurora** background, a **grid** and moving
**scanlines**, glass panels with corner brackets, and the reactor's rotating rings
(SVG circles + 60 tick marks) that spin via CSS `@keyframes`. The cyan/gold color
scheme and monospace telemetry text sell the sci-fi look.

---

## 8. The AI Gateway (optional provider)

One of the supported brain/voice providers is an **OpenAI-compatible AI gateway**
(e.g. [Bifrost](https://github.com/maximhq/bifrost), LiteLLM, Portkey). This is
worth understanding because it's a real production pattern.

**A gateway is a single door in front of many AI providers.** Instead of holding
separate keys for ElevenLabs, OpenAI, and AWS Bedrock, you hold **one gateway key**,
and the gateway routes each request to the right provider based on the **model name**
you send:

```
your one key  ─►  AI gateway  ─┬─► elevenlabs/eleven_flash_v2_5  (voice out)
                               ├─► openai/whisper-1              (voice in)
                               └─► openai/gpt-4o-mini            (brain)
```

Because the gateway speaks the **OpenAI-compatible** format, our
`gateway_provider.py` and `voice_gateway.py` just call standard endpoints
(`/v1/chat/completions`, `/v1/audio/speech`, `/v1/audio/transcriptions`). You point
the app at it with `GATEWAY_BASE_URL` in `.env`.

**Reaching a self-hosted gateway:** if the gateway runs on another machine behind a
hostname that isn't in public DNS, you can add an entry to your OS `hosts` file
(`C:\Windows\System32\drivers\etc\hosts` on Windows) mapping that hostname to the
server's IP — a manual DNS override so the app resolves and connects to it like any
website.

---

## 9. How to run & configure

**Run (two terminals):**
```powershell
./start-backend.ps1     # starts the Python API on http://127.0.0.1:8000
./start-frontend.ps1    # starts the React UI on http://localhost:5173
```
Open http://localhost:5173, allow the microphone, and talk.

**Configure everything in `backend/.env`:**
| Setting | Meaning |
|---|---|
| `LLM_PROVIDER` | `gateway` (Claude via Bifrost), `ollama` (local free), or `anthropic` |
| `VOICE_PROVIDER` | `gateway` (ElevenLabs+Whisper via Bifrost) or `elevenlabs` |
| `GATEWAY_BASE_URL` / `GATEWAY_API_KEY` | your gateway address + key |
| `GATEWAY_CHAT_MODEL` / `_TTS_MODEL` / `_STT_MODEL` | which models to route to |
| `ASSISTANT_NAME` | what it calls itself |
| `ALLOW_SHELL_COMMANDS` | let it run shell commands (⚠️ off by default) |

---

## 10. How to extend it (add your own tool)

Adding a new capability is 3 small steps. Say you want a `play_spotify` tool:

**1. Write the function** in `backend/app/tools/system_automation.py`:
```python
def play_spotify(args: dict) -> str:
    song = args.get("song", "")
    # ... automation to play the song ...
    return f"Playing {song} on Spotify."
```

**2. Register it** in `backend/app/tools/registry.py` — add to `_HANDLERS`:
```python
"play_spotify": s.play_spotify,
```
…and add its schema to `TOOL_SCHEMAS`:
```python
{
  "name": "play_spotify",
  "description": "Play a song on Spotify.",
  "input_schema": {"type": "object",
    "properties": {"song": {"type": "string"}}, "required": ["song"]},
},
```

**3. Done.** The LLM now sees the tool and will call it when you say "play X on
Spotify." No other file changes. That's the power of the tool registry.

To add a whole new **AI provider** or **voice provider**, add one file in `llm/`
(or a `voice_*` module) implementing the same interface — again, nothing else
changes.

---

## 11. Glossary

- **API** — a way for programs to talk over the internet.
- **API key** — secret password that authorizes/bills API use. Keep it in `.env`.
- **LLM** — large language model (the AI brain, e.g. Claude).
- **Tool / function calling** — letting the LLM trigger your code to do real actions.
- **Agentic loop** — the LLM ↔ tools back-and-forth until a final answer.
- **STT / TTS** — speech-to-text / text-to-speech.
- **Endpoint** — a specific URL the backend responds to (e.g. `/api/voice`).
- **CORS** — browser security that must be allowed for frontend↔backend calls.
- **Provider abstraction** — a common interface so components (brain, voice) are swappable.
- **Gateway** — one entry point that routes to many AI providers behind one key.
- **Hook (React)** — reusable stateful logic (`useState`, `useEffect`, `useRecorder`).
- **Blob** — a file-like chunk of binary data (here, recorded audio).
- **SQLite** — a database that's just a single file, no server needed.

---

## 12. Resume talking points

When describing this project, these are the strong, true claims:

- Built a **full-stack voice assistant** (Python/FastAPI backend + React frontend)
  with real-time audio capture, transcription, and playback.
- Designed a **provider-agnostic architecture** — the LLM and voice services are
  swappable (local Ollama ↔ cloud Claude ↔ an AI gateway) behind clean interfaces.
- Implemented an **LLM agentic tool-use loop**: the model plans, calls typed tools
  (web search, productivity, OS automation), reads results, and iterates.
- Integrated an **OpenAI-compatible AI gateway** (Bifrost) so one key powers
  ElevenLabs voice + Whisper transcription + Claude reasoning.
- Wrote **real desktop automation** (verified app-launching, WhatsApp message
  sending via UI automation).
- Built **hands-free conversation mode** with Web Audio silence detection.
- Designed a **custom animated HUD** (SVG + CSS) inspired by Iron Man's J.A.R.V.I.S.
- Practiced **security-conscious defaults**: git-ignored secrets, a sandboxed
  calculator (AST, not `eval`), opt-in shell access, honest failure reporting.

---

*Built with Python, React, Claude, ElevenLabs, Whisper, and a Bifrost AI gateway.*
