"""The agent brain — provider-agnostic tool-use loop.

Given a user message, the active LLM (local Ollama or cloud Claude) decides
whether to answer directly or call tools (web search / productivity / system
automation). We run the loop until it produces a final answer.

Conversation history is kept per ``session_id`` in memory in a normalized
format (see llm/base.py) — simple and fine for a single-user assistant.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from . import intent_router, recallr_memory, skills
from .config import BACKEND_DIR, settings
from .llm.base import ToolCall
from .llm import get_provider
from .tools.registry import TOOL_SCHEMAS, dispatch

_MAX_TURNS = 8  # safety cap on tool-use loops per user message
_CONFIRM_TOOLS = {"send_whatsapp", "send_discord_message", "run_command", "close_window", "install_software"}
_YES = {"yes", "y", "yeah", "yep", "confirm", "confirmed", "proceed", "do it", "go ahead", "ok", "okay"}
_NO = {"no", "n", "nope", "cancel", "stop", "don't", "do not", "never mind", "nevermind"}
_ASK_USER_TOOL = {
    "name": "ask_user",
    "description": (
        "Ask the user a short follow-up question when a required detail is missing. "
        "Use this instead of replying with a normal question, so the UI knows to listen."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The short question to ask the user aloud.",
            }
        },
        "required": ["question"],
    },
}
_AGENT_TOOL_SCHEMAS = [*TOOL_SCHEMAS, _ASK_USER_TOOL]

# session_id -> normalized message list. Persisted to disk so a session
# survives a backend restart.
_HISTORY: dict[str, list[dict]] = {}
_PENDING_CONFIRMATIONS: dict[str, list[dict]] = {}
_PENDING_CLARIFICATIONS: dict[str, dict] = {}
_SESSIONS_FILE = BACKEND_DIR / "sessions.json"


@dataclass
class ToolEvent:
    name: str
    arguments: dict
    result: str | None = None
    status: str = "done"

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "result": self.result,
            "status": self.status,
        }


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


def _system_prompt(recallr_context: str = "", skills_context: str = "") -> str:
    prompt = (
        f"You are {settings.assistant_name}, a helpful, friendly voice assistant.\n"
        "Your replies are READ ALOUD, so keep them SHORT — ideally one or two "
        "sentences. Speak like a person, not a document. Never use markdown, bullet "
        "lists, code blocks, emojis or long URLs. Get to the point; skip preamble like "
        "'Sure, I can help with that.'\n"
        "You can take real actions with your tools: search the web, manage to-dos, "
        "notes and reminders, do math, tell the time, open apps and websites, close "
        "windows/tabs by name, PLAY music/videos on YouTube, control playback "
        "(pause/stop/skip/volume), send WhatsApp messages, and send Discord messages. "
        "When the user asks you to "
        "DO something, actually use the "
        "right tool rather than saying they must do it themselves. Never swap platforms: "
        "if the user says Discord, use Discord tools; if they say WhatsApp, use WhatsApp tools. "
        "If they ask you to message someone but do not name the app, ask which app to use. "
        "To pause or STOP "
        "music, use media_control — never call play_youtube again for that. Only ask "
        "for clarification if a required detail is genuinely missing. When you need "
        "that missing detail, call ask_user with your short question instead of "
        "replying with a normal question.\n"
        "Some actions require user confirmation before execution. If a tool result says "
        "confirmation is pending, wait for the user's yes/no answer instead of claiming it is done. "
        "Never say you are proceeding, sending, opening, playing, or done unless you called the needed tool in this turn. "
        "After acting, confirm what you did in one short sentence.\n"
        "NEVER give up on the first failure. If you don't know how to do something, "
        "or a tool fails, use web_search to find a working method, then try it "
        "(run_command can execute it if the user has enabled shell commands). "
        "When a non-obvious method works, call save_skill to record it so you can "
        "do it instantly next time. You can check what's installed on this PC with "
        "list_installed_apps. If the user wants an app that is NOT installed, offer "
        "to install it: search_software to find the exact package id, then "
        "install_software with that id (the user confirms before it runs). "
        "For music: use play_spotify when the user says Spotify (or as the default "
        "when Spotify is connected); use play_youtube for videos or when they say YouTube. "
        "When pausing/stopping media, pass media_control a target if the user names one "
        "or if multiple things are playing (get_now_playing shows all sessions). "
        "For COMPLEX multi-step requests (research + setup, several dependent actions, "
        "things you couldn't solve directly), call delegate_task to hand it to the "
        "stronger agent brain — but never for simple commands."
    )
    if skills_context:
        prompt += f"\n\n{skills_context}"
    if recallr_context:
        prompt += (
            "\n\nRelevant long-term memory from RecallrAI:\n"
            f"{recallr_context}\n"
            "Use this context quietly when it helps. Do not mention memory retrieval "
            "unless the user asks about it."
        )
    return prompt


def _normalize_confirmation(text: str) -> str:
    return " ".join(text.strip().lower().replace(".", "").split())


def _is_yes(text: str) -> bool:
    normalized = _normalize_confirmation(text)
    return normalized in _YES


def _is_no(text: str) -> bool:
    normalized = _normalize_confirmation(text)
    return normalized in _NO


def _looks_like_message_request(text: str) -> bool:
    normalized = text.lower()
    message_words = ("message", "text", "dm", "send")
    platforms = ("whatsapp", "discord", "telegram", "email", "gmail", "sms")
    return any(word in normalized for word in message_words) and not any(
        platform in normalized for platform in platforms
    )


def _confirmation_summary(calls: list[dict]) -> str:
    parts = []
    for call in calls:
        name = call["name"]
        args = call.get("arguments") or {}
        if name in {"send_whatsapp", "send_discord_message"}:
            platform = "WhatsApp" if name == "send_whatsapp" else "Discord"
            parts.append(
                f'send "{args.get("message", "")}" to {args.get("contact", "the contact")} on {platform}'
            )
        elif name == "close_window":
            parts.append(f'close the window matching "{args.get("name", "")}"')
        elif name == "open_application":
            parts.append(f'open {args.get("name", "the application")}')
        elif name == "open_url":
            parts.append(f'open {args.get("url", "the website")}')
        elif name == "run_command":
            parts.append(f'run `{args.get("command", "")}`')
        elif name == "install_software":
            parts.append(f'install {args.get("id", "the software")} on this PC')
        else:
            parts.append(name)
    return "; ".join(parts)


def _call_name(call: ToolCall | dict) -> str:
    return call.name if isinstance(call, ToolCall) else call["name"]


def _call_arguments(call: ToolCall | dict) -> dict:
    return call.arguments if isinstance(call, ToolCall) else call.get("arguments") or {}


def _call_id(call: ToolCall | dict, idx: int) -> str:
    return call.id if isinstance(call, ToolCall) else call.get("id") or f"call_{idx}"


def _call_dict(call: ToolCall | dict, idx: int) -> dict:
    return {
        "id": _call_id(call, idx),
        "name": _call_name(call),
        "arguments": _call_arguments(call),
    }


def _needs_confirmation(calls: list[ToolCall | dict]) -> bool:
    return any(_call_name(call) in _CONFIRM_TOOLS for call in calls)


def _event(name: str, arguments: dict, result: str | None = None, status: str = "done") -> dict:
    return ToolEvent(name=name, arguments=arguments or {}, result=result, status=status).as_dict()


def _response(
    reply: str,
    *,
    actions: list[str] | None = None,
    tool_events: list[dict] | None = None,
    pending_confirmation: bool = False,
    listen_mode: str | None = None,
) -> dict:
    mode = listen_mode or ("confirmation" if pending_confirmation else "none")
    return {
        "reply": reply,
        "actions": actions or [],
        "tool_events": tool_events or [],
        "pending_confirmation": pending_confirmation,
        "listen_mode": mode,
        "expects_response": mode in {"confirmation", "follow_up"},
    }


def _execute_calls(calls: list[dict]) -> tuple[list[str], list[dict], list[dict]]:
    actions: list[str] = []
    events: list[dict] = []
    tool_messages: list[dict] = []
    for idx, call in enumerate(calls):
        name = call["name"]
        args = call.get("arguments") or {}
        actions.append(name)
        result = dispatch(name, args)
        events.append(_event(name, args, result, status=_event_status(result)))
        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": call.get("id") or f"confirmed_{idx}",
                "name": name,
                "content": result,
            }
        )
    return actions, events, tool_messages


def _reply_from_events(events: list[dict]) -> str:
    if not events:
        return "Done."
    failed = [
        e for e in events
        if e.get("status") == "failed"
        or e.get("result", "").lower().startswith(("tool ", "could not", "i couldn't"))
    ]
    if failed:
        return failed[0].get("result") or "That did not complete."
    needs_verification = [e for e in events if e.get("status") == "needs_verification"]
    if needs_verification:
        return needs_verification[0].get("result") or "I could not verify that action."
    if len(events) == 1:
        return events[0].get("result") or "Done."
    return "Done. I completed the requested actions."


def _event_status(result: str) -> str:
    lowered = (result or "").strip().lower()
    if lowered.startswith("verified"):
        return "verified"
    if lowered.startswith("unverified"):
        return "needs_verification"
    if lowered.startswith(("tool ", "could not", "i couldn't", "something went wrong")):
        return "failed"
    return "done"


def _run_tool_batch(
    session_id: str,
    messages: list[dict],
    calls: list[ToolCall | dict],
    *,
    source: str,
) -> dict:
    """Execute safe tools now and hold sensitive tools for confirmation."""
    normalized = [_call_dict(call, idx) for idx, call in enumerate(calls)]
    safe_calls = [call for call in normalized if call["name"] not in _CONFIRM_TOOLS]
    confirm_calls = [call for call in normalized if call["name"] in _CONFIRM_TOOLS]

    actions: list[str] = []
    events: list[dict] = []

    if safe_calls:
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": call["id"], "name": call["name"], "arguments": call.get("arguments") or {}}
                    for call in safe_calls
                ],
            }
        )
        safe_actions, safe_events, tool_messages = _execute_calls(safe_calls)
        actions.extend(safe_actions)
        events.extend(safe_events)
        messages.extend(tool_messages)

    if confirm_calls:
        _PENDING_CONFIRMATIONS[session_id] = confirm_calls
        summary = _confirmation_summary(confirm_calls)
        pending_events = [
            _event(call["name"], call.get("arguments") or {}, status="pending")
            for call in confirm_calls
        ]
        if safe_calls:
            lead = _reply_from_events(events)
            reply = f"{lead} I can {summary}. Do you want me to proceed?"
        else:
            reply = f"I can {summary}. Do you want me to proceed?"
        messages.append({"role": "assistant", "content": reply, "tool_calls": []})
        _save_history()
        recallr_memory.after_turn(session_id, reply)
        return _response(
            reply,
            actions=actions + [call["name"] for call in confirm_calls],
            tool_events=events + pending_events,
            pending_confirmation=True,
        )

    reply = _reply_from_events(events)
    if source == "fast_path":
        # Keep direct automation responses short and action-oriented.
        messages.append({"role": "assistant", "content": reply, "tool_calls": []})
        _save_history()
        recallr_memory.after_turn(session_id, reply)
        return _response(reply, actions=actions, tool_events=events)

    return _response(reply, actions=actions, tool_events=events)


def _run_calls_with_followup(
    session_id: str,
    messages: list[dict],
    calls: list[dict],
    reply: str,
    pending: dict | None,
) -> dict:
    actions: list[str] = []
    events: list[dict] = []
    if calls:
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": call["id"], "name": call["name"], "arguments": call.get("arguments") or {}}
                    for call in calls
                ],
            }
        )
        actions, events, tool_messages = _execute_calls(calls)
        messages.extend(tool_messages)

    if pending:
        _PENDING_CLARIFICATIONS[session_id] = pending

    lead = _reply_from_events(events) if events else ""
    final_reply = f"{lead} {reply}".strip()
    messages.append({"role": "assistant", "content": final_reply, "tool_calls": []})
    _save_history()
    recallr_memory.after_turn(session_id, final_reply)
    return _response(final_reply, actions=actions, tool_events=events, listen_mode="follow_up")


def _handle_pending_confirmation(session_id: str, user_text: str) -> dict | None:
    pending = _PENDING_CONFIRMATIONS.get(session_id)
    if not pending:
        return None

    messages = _HISTORY.setdefault(session_id, [])
    messages.append({"role": "user", "content": user_text})

    if _is_no(user_text):
        _PENDING_CONFIRMATIONS.pop(session_id, None)
        reply = "Cancelled. I did not run the pending action."
        messages.append({"role": "assistant", "content": reply, "tool_calls": []})
        _save_history()
        recallr_memory.after_turn(session_id, reply)
        return _response(reply)

    if not _is_yes(user_text):
        summary = _confirmation_summary(pending)
        reply = f"Please answer yes or no. Should I {summary}?"
        messages.append({"role": "assistant", "content": reply, "tool_calls": []})
        _save_history()
        recallr_memory.after_turn(session_id, reply)
        return _response(
            reply,
            actions=[c["name"] for c in pending],
            tool_events=[_event(c["name"], c.get("arguments") or {}, status="pending") for c in pending],
            pending_confirmation=True,
        )

    _PENDING_CONFIRMATIONS.pop(session_id, None)
    actions, events, tool_messages = _execute_calls(pending)
    messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": c.get("id") or f"confirmed_{i}", "name": c["name"], "arguments": c.get("arguments") or {}}
                for i, c in enumerate(pending)
            ],
        }
    )
    messages.extend(tool_messages)
    reply = _reply_from_events(events)
    messages.append({"role": "assistant", "content": reply, "tool_calls": []})
    _save_history()
    recallr_memory.after_turn(session_id, reply)
    return _response(reply, actions=actions, tool_events=events)


def _platform_from_text(text: str) -> str | None:
    lowered = text.lower()
    if "discord" in lowered:
        return "discord"
    if "whatsapp" in lowered or "whats app" in lowered:
        return "whatsapp"
    return None


def _handle_pending_clarification(session_id: str, user_text: str) -> dict | None:
    pending = _PENDING_CLARIFICATIONS.get(session_id)
    if not pending:
        return None

    messages = _HISTORY.setdefault(session_id, [])
    messages.append({"role": "user", "content": user_text})

    kind = pending.get("type")
    if kind == "message_platform":
        platform = _platform_from_text(user_text)
        if not platform:
            reply = (
                f"I still need the app for the message to {pending.get('contact', 'that contact')}: "
                "WhatsApp or Discord?"
            )
            messages.append({"role": "assistant", "content": reply, "tool_calls": []})
            _save_history()
            recallr_memory.after_turn(session_id, reply)
            return _response(reply, listen_mode="follow_up")

        _PENDING_CLARIFICATIONS.pop(session_id, None)
        tool_name = "send_discord_message" if platform == "discord" else "send_whatsapp"
        calls = [
            {
                "id": f"clarified_{tool_name}",
                "name": tool_name,
                "arguments": {
                    "contact": pending.get("contact", ""),
                    "message": pending.get("message", ""),
                },
            }
        ]
        return _run_tool_batch(session_id, messages, calls, source="fast_path")

    if kind == "music_query":
        query = user_text.strip()
        if not query:
            reply = "What kind of music would you like to hear?"
            messages.append({"role": "assistant", "content": reply, "tool_calls": []})
            _save_history()
            recallr_memory.after_turn(session_id, reply)
            return _response(reply, listen_mode="follow_up")

        _PENDING_CLARIFICATIONS.pop(session_id, None)
        return _run_tool_batch(
            session_id, messages, [intent_router.play_call(query)], source="fast_path"
        )

    _PENDING_CLARIFICATIONS.pop(session_id, None)
    return None


def reset(session_id: str) -> None:
    recallr_memory.finalize_session(session_id)
    _HISTORY.pop(session_id, None)
    _PENDING_CONFIRMATIONS.pop(session_id, None)
    _PENDING_CLARIFICATIONS.pop(session_id, None)
    _save_history()


def chat(session_id: str, user_text: str) -> dict:
    """Run one full turn. Returns {reply, actions} where actions is a list of
    tool names that were executed (for the UI to display)."""
    pending_result = _handle_pending_confirmation(session_id, user_text)
    if pending_result is not None:
        return pending_result

    clarification_result = _handle_pending_clarification(session_id, user_text)
    if clarification_result is not None:
        return clarification_result

    messages = _HISTORY.setdefault(session_id, [])
    recallr_context = recallr_memory.before_turn(session_id, user_text)
    messages.append({"role": "user", "content": user_text})

    routed = intent_router.route(user_text)
    if routed and routed.handled:
        if routed.reply:
            return _run_calls_with_followup(
                session_id,
                messages,
                routed.calls,
                routed.reply,
                routed.pending,
            )
        if routed.calls:
            return _run_tool_batch(session_id, messages, routed.calls, source="fast_path")

    # Learned fast path: this exact phrase was resolved by the LLM before and the
    # tool call succeeded, so replay it instantly (no LLM round-trip, no cost).
    route = skills.lookup_route(user_text)
    if route is not None:
        call = {"id": "learned_route", "name": route["name"], "arguments": route.get("arguments") or {}}
        messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
        route_actions, route_events, tool_messages = _execute_calls([call])
        messages.extend(tool_messages)
        if all(e.get("status") in {"done", "verified"} for e in route_events):
            reply = _reply_from_events(route_events)
            messages.append({"role": "assistant", "content": reply, "tool_calls": []})
            _save_history()
            recallr_memory.after_turn(session_id, reply)
            return _response(reply, actions=route_actions, tool_events=route_events)
        # The replay failed (app uninstalled, etc.) — self-heal: forget the route
        # and fall through so the LLM can solve it fresh (and re-learn).
        skills.forget_route(user_text)

    if _looks_like_message_request(user_text):
        reply = "Which app should I use for that message: WhatsApp or Discord?"
        messages.append({"role": "assistant", "content": reply, "tool_calls": []})
        _save_history()
        recallr_memory.after_turn(session_id, reply)
        return _response(reply, listen_mode="follow_up")

    provider = get_provider()
    actions: list[str] = []
    events: list[dict] = []
    resolved_calls: list[dict] = []   # what the LLM did this turn, for route learning
    resolved_results: list[str] = []
    skills_context = skills.relevant_skills(user_text)

    for _ in range(_MAX_TURNS):
        turn = provider.chat(_system_prompt(recallr_context, skills_context), messages, _AGENT_TOOL_SCHEMAS)

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
            reply = turn.text or "Done."
            recallr_memory.after_turn(session_id, reply)
            # If this phrase resolved to exactly one safe, successful tool call,
            # remember the mapping so next time we skip the LLM entirely.
            skills.learn_route(user_text, resolved_calls, resolved_results)
            return _response(reply, actions=actions, tool_events=events)

        ask_calls = [tc for tc in turn.tool_calls if tc.name == "ask_user"]
        if ask_calls:
            messages.pop()
            question = (ask_calls[0].arguments.get("question") or turn.text or "What should I know?").strip()
            messages.append({"role": "assistant", "content": question, "tool_calls": []})
            _save_history()
            recallr_memory.after_turn(session_id, question)
            return _response(
                question,
                actions=actions,
                tool_events=events,
                listen_mode="follow_up",
            )

        if _needs_confirmation(turn.tool_calls):
            messages.pop()
            result = _run_tool_batch(session_id, messages, turn.tool_calls, source="model")
            result["actions"] = actions + result.get("actions", [])
            result["tool_events"] = events + result.get("tool_events", [])
            return result

        # Execute every requested tool and feed results back.
        for tc in turn.tool_calls:
            actions.append(tc.name)
            result = dispatch(tc.name, tc.arguments)
            resolved_calls.append({"name": tc.name, "arguments": tc.arguments})
            resolved_results.append(result)
            events.append(_event(tc.name, tc.arguments, result))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                }
            )

    _save_history()
    reply = "Sorry, I got stuck working on that. Could you rephrase?"
    recallr_memory.after_turn(session_id, reply)
    return _response(reply, actions=actions, tool_events=events)
