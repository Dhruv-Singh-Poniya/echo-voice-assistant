"""FastAPI server — the seam between the React UI and the assistant.

Endpoints
  GET  /api/health          -> config/key status
  POST /api/voice           -> audio in  -> transcript + reply text + reply audio
  POST /api/text            -> text in   -> reply text (+ optional reply audio)
  GET  /api/reminders/due   -> reminders that have come due (for UI popups)
  POST /api/reset           -> clear conversation memory for a session
"""
from __future__ import annotations

import base64
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Windows consoles can default to legacy cp1252; a mere print() of a Unicode
# character would then raise and 500 the request. Force UTF-8, never crash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agent, recallr_memory, voice
from .config import settings
from .db import get_conn, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # ensure SQLite tables exist before serving
    yield


app = FastAPI(title="Voice Assistant API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
class TextIn(BaseModel):
    session_id: str = "default"
    text: str
    speak: bool = True


class ResetIn(BaseModel):
    session_id: str = "default"


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    problems = settings.require_keys()
    problems = problems + recallr_memory.health()

    # Also surface provider-specific problems (e.g. Ollama not running / model not pulled).
    from .llm import get_provider

    try:
        problems = problems + get_provider().health()
    except Exception as exc:  # provider failed to construct
        problems = problems + [f"LLM provider error: {exc}"]

    model = {
        "ollama": settings.ollama_model,
        "anthropic": settings.anthropic_model,
        "gateway": settings.gateway_chat_model,
    }.get(settings.llm_provider, settings.ollama_model)

    return {
        "ok": not problems,
        "assistant_name": settings.assistant_name,
        "provider": settings.llm_provider,
        "model": model,
        "voice_provider": settings.voice_provider,
        "shell_enabled": settings.allow_shell_commands,
        "recallrai_enabled": settings.recallrai_enabled,
        "recallrai_strategy": settings.recallrai_recall_strategy,
        "recallrai_base_url": settings.recallrai_base_url,
        "recallrai_forward_proxy": bool(settings.recallrai_forward_proxy_url),
        "recallrai_last_error": recallr_memory.last_error(),
        "problems": problems,
    }


@app.post("/api/voice")
async def voice_turn(
    session_id: str = Form("default"),
    audio: UploadFile = File(...),
) -> dict:
    """Full voice loop: speech -> text -> agent -> reply text -> speech."""
    _guard_keys()
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio upload.")

    t0 = time.perf_counter()
    transcript = await voice.speech_to_text(audio_bytes, audio.filename or "audio.webm")
    t1 = time.perf_counter()
    if not transcript:
        return {
            "transcript": "",
            "reply": "I didn't catch that. Could you try again?",
            "actions": [],
            "tool_events": [],
            "pending_confirmation": False,
            "listen_mode": "none",
            "expects_response": False,
            "audio": None,
        }

    result = agent.chat(session_id, transcript)
    t2 = time.perf_counter()
    reply_audio = await voice.text_to_speech(result["reply"])
    t3 = time.perf_counter()

    timing = _timing(stt=t1 - t0, agent=t2 - t1, tts=t3 - t2, total=t3 - t0)
    print(f"[timing] voice -> {timing}")

    return {
        "transcript": transcript,
        "reply": result["reply"],
        "actions": result["actions"],
        "tool_events": result.get("tool_events", []),
        "pending_confirmation": result.get("pending_confirmation", False),
        "listen_mode": result.get("listen_mode", "none"),
        "expects_response": result.get("expects_response", False),
        "audio": base64.b64encode(reply_audio).decode("ascii"),
        "timing": timing,
    }


def _timing(**secs) -> dict:
    return {k: round(v * 1000) for k, v in secs.items()}


@app.post("/api/text")
async def text_turn(body: TextIn) -> dict:
    """Type instead of talk. Optionally returns spoken audio too."""
    _guard_keys()
    result = agent.chat(body.session_id, body.text)
    audio_b64 = None
    if body.speak:
        reply_audio = await voice.text_to_speech(result["reply"])
        audio_b64 = base64.b64encode(reply_audio).decode("ascii")
    return {
        "transcript": body.text,
        "reply": result["reply"],
        "actions": result["actions"],
        "tool_events": result.get("tool_events", []),
        "pending_confirmation": result.get("pending_confirmation", False),
        "listen_mode": result.get("listen_mode", "none"),
        "expects_response": result.get("expects_response", False),
        "audio": audio_b64,
    }


@app.get("/api/reminders/due")
def due_reminders() -> dict:
    """Return reminders whose time has passed and mark them as notified."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, text FROM reminders WHERE notified = 0 AND due_at <= ?",
            (now_iso,),
        ).fetchall()
        if rows:
            ids = [r["id"] for r in rows]
            conn.execute(
                f"UPDATE reminders SET notified = 1 WHERE id IN ({','.join('?' * len(ids))})",
                ids,
            )
    return {"due": [{"id": r["id"], "text": r["text"]} for r in rows]}


@app.post("/api/reset")
def reset(body: ResetIn) -> dict:
    agent.reset(body.session_id)
    return {"ok": True}


def _guard_keys() -> None:
    problems = settings.require_keys()
    if problems:
        raise HTTPException(503, " ".join(problems))
