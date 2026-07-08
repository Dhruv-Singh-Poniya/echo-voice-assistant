"""The agent brain — provider-agnostic tool-use loop.

Given a user message, the active LLM (local Ollama or cloud Claude) decides
whether to answer directly or call tools (web search / productivity / system
automation). We run the loop until it produces a final answer.

Conversation history is kept per ``session_id`` in memory in a normalized
format (see llm/base.py) — simple and fine for a single-user assistant.
"""
from __future__ import annotations

import json

from .config import BACKEND_DIR, settings
from .llm import get_provider
from .tools.registry import TOOL_SCHEMAS, dispatch

_MAX_TURNS = 8  # safety cap on tool-use loops per user message

# session_id -> normalized message list. Persisted to disk so a session
# survives a backend restart.
_HISTORY: dict[str, list[dict]] = {}
_SESSIONS_FILE = BACKEND_DIR / "sessions.json"


def _load_history() -> None:
    global _HISTORY
    try:
        if _SESSIONS_FILE.exists():
            _HISTORY = json.loads(_SESSIONS_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        _HISTORY = {}


def _save_history() -> None:
    try:
        _SESSIONS_FILE.write_text(json.dumps(_HISTORY), encoding="utf-8")
    except Exception:
        pass


_load_history()


def _system_prompt() -> str:
    return (
        f"You are {settings.assistant_name}, a helpful, friendly voice assistant.\n"
        "Your replies are READ ALOUD, so keep them SHORT — ideally one or two "
        "sentences. Speak like a person, not a document. Never use markdown, bullet "
        "lists, code blocks, emojis or long URLs. Get to the point; skip preamble like "
        "'Sure, I can help with that.'\n"
        "You can take real actions with your tools: search the web, manage to-dos, "
        "notes and reminders, do math, tell the time, open apps and websites, close "
        "windows/tabs by name, PLAY music/videos on YouTube, control playback "
        "(pause/stop/skip/volume), and send WhatsApp messages. When the user asks you to "
        "DO something, actually use the "
        "right tool rather than saying they must do it themselves. To pause or STOP "
        "music, use media_control — never call play_youtube again for that. Only ask "
        "for clarification if a required detail is genuinely missing.\n"
        "After acting, confirm what you did in one short sentence."
    )


def reset(session_id: str) -> None:
    _HISTORY.pop(session_id, None)
    _save_history()


def chat(session_id: str, user_text: str) -> dict:
    """Run one full turn. Returns {reply, actions} where actions is a list of
    tool names that were executed (for the UI to display)."""
    messages = _HISTORY.setdefault(session_id, [])
    messages.append({"role": "user", "content": user_text})

    provider = get_provider()
    actions: list[str] = []

    for _ in range(_MAX_TURNS):
        turn = provider.chat(_system_prompt(), messages, TOOL_SCHEMAS)

        # Record the assistant turn in normalized form.
        messages.append(
            {
                "role": "assistant",
                "content": turn.text,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in turn.tool_calls
                ],
            }
        )

        if not turn.tool_calls:
            _save_history()
            return {"reply": turn.text or "Done.", "actions": actions}

        # Execute every requested tool and feed results back.
        for tc in turn.tool_calls:
            actions.append(tc.name)
            result = dispatch(tc.name, tc.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                }
            )

    _save_history()
    return {
        "reply": "Sorry, I got stuck working on that. Could you rephrase?",
        "actions": actions,
    }
